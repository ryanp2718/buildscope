# -*- coding: utf-8 -*-
"""Model calls, priced and logged - the first module in this project that
spends money.

Three properties, each of which exists because of something written down
elsewhere in the design, and none of which is about convenience.

**The official `anthropic` SDK speaks the Messages API.** This module used
to hand-roll it over `urllib`, to satisfy a stdlib-only rule that was never
weighed for this purpose and is retired by
[ADR-0017](../docs/adr/0017-the-inference-layer-uses-the-vendor-sdk.md). What
the hand-rolled client cost: no retries at all, so a 429 anywhere in a 55-draw
run would have ended it; a per-model capability table maintained by hand
against 400s from the live API; and a streaming parser whose transport flag
leaked into the cache key and silently orphaned $0.60 of paid responses. The
SDK supplies retry, backoff and streaming; what stays here is the part it does
not have.

**Every call is logged before it is billed.** DESIGN.md section 6: "Log spend
per call class from the first call so the tripwire is readable." The tripwire
is the fallback fraction - if spend starts tracking the high rows of the
section 6 table, the finding is that D8 is not working, and that is only
visible if cost was recorded per call class from the beginning rather than
reconstructed from an invoice later. `data/infer/ledger.jsonl` is append-only
and carries `call_class` on every row.

**Every response is cached on disk by request hash.** The same argument as D1.
A model call is not reproducible - the same prompt can return different bytes
tomorrow - so the *response* has to be the artifact, or a measurement cannot
be re-derived without paying for it again. Re-running an experiment over a
warm cache costs zero dollars, which is what makes the scoring code safe to
iterate on after the money is spent.

A fourth property that is not a design principle, just prudence: `Budget`
refuses a call whose worst case would push the session past a ceiling.
`permits/capture.py` carries the same guard on requests and it has already
stopped one runaway loop.
"""
import hashlib
import io
import json
import os
import time

import anthropic
from opentelemetry.trace import SpanKind, Status, StatusCode

from permits import telemetry

# Retry and timeout are the SDK's, stated explicitly rather than inherited:
# the default is 2 retries and this project's calls are long, expensive and
# run unattended in batches of dozens.
MAX_RETRIES = 5
TIMEOUT_S = 900.0

# USD per million tokens, (input, output). Quoted from DESIGN.md section 6,
# "Anthropic first-party, as of 2026-06-24 - re-verify before quoting". They
# are re-stated here rather than parsed out of prose so a cost figure this
# module prints has one auditable source, and they carry the same staleness
# warning: a price that moved makes every dollar figure wrong while every
# token figure stays right. Report tokens when in doubt.
PRICES = {
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
}
PRICES_AS_OF = "2026-06-24 (DESIGN.md section 6)"

# Cache reads bill at 0.1x input; 5-minute writes at 1.25x. Section 6 lever 3.
CACHE_READ = 0.1
CACHE_WRITE = 1.25

# Extended thinking is configured differently by model generation, and there
# is no form that works on both. Claude 4.6 and later take
# `{"type": "adaptive"}` and reject `budget_tokens` with a 400; earlier models
# take `budget_tokens` and reject `adaptive` with a 400. So the shape is a
# property of the model, not a preference, and asking for "thinking" has to be
# resolved against the model rather than passed through.
#
# Found the hard way: the first conformance run died on
# `adaptive thinking is not supported on this model` against Haiku 4.5. It
# cost nothing - the request was rejected before billing - but it is exactly
# the kind of per-model capability that a hand-rolled client has to carry
# itself, which is the standing cost of not using the SDK.
ADAPTIVE_THINKING = frozenset(["claude-opus-5", "claude-sonnet-5"])

# Above this `max_tokens`, stream. A non-streaming request whose ceiling is
# large enough to run past the server's request timeout is refused outright,
# and one that merely runs long dies on the client socket with the tokens
# already billed. Found by measurement: a 259-record St. Johns page needs
# roughly 22k output tokens to come back as JSON, which is over the line.
#
# This is now a choice of SDK method rather than a key added to `body` after
# the cache key was computed, which is what made the two diverge before.
STREAM_ABOVE = 8192


class Refused(Exception):
    """A call that was not made. Never raised after money has been spent."""


class ApiError(Exception):
    pass


def price(model):
    if model not in PRICES:
        raise Refused(
            "no price on file for %r. Add it to PRICES with a source before "
            "spending - an unpriced call cannot be logged against the "
            "section 6 tripwire, which is the only reason the ledger exists."
            % model)
    return PRICES[model]


def cost(model, usage):
    """Dollars for one response's `usage` block.

    Cache fields are read with `.get` and default to zero: a deployment may
    omit them entirely, and a missing field must not be billed as a full-price
    input token.
    """
    pin, pout = price(model)
    plain = usage.get("input_tokens", 0) or 0
    cread = usage.get("cache_read_input_tokens", 0) or 0
    cwrite = usage.get("cache_creation_input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    return ((plain + cread * CACHE_READ + cwrite * CACHE_WRITE) * pin
            + out * pout) / 1e6


def estimate(model, in_tokens, out_tokens):
    pin, pout = price(model)
    return (in_tokens * pin + out_tokens * pout) / 1e6


def tokens(text):
    """Token count without a tokenizer, for projections only.

    `scripts/measure_tokens.py` established the bracket on this project's own
    pages: plain English runs ~4 chars/token on a BPE vocabulary, HTML nearer
    3 because it is denser in punctuation. A projection quotes the pessimistic
    end, because a budget estimate that is wrong should be wrong in the
    direction that stops early.
    """
    return int(len(text) / 3.0)


class Budget(object):
    """A ceiling in dollars, checked before each call against its worst case.

    Worst case, not expected case: `max_tokens` is what the request authorizes
    the model to bill, so that is what the ceiling is tested against. A guard
    that admits calls on the basis of what usually happens is not a guard.
    """

    def __init__(self, ceiling_usd):
        self.ceiling = float(ceiling_usd)
        self.spent = 0.0
        self.calls = 0

    def check(self, model, in_tokens, max_tokens):
        worst = estimate(model, in_tokens, max_tokens)
        if self.spent + worst > self.ceiling:
            raise Refused(
                "budget ceiling $%.2f would be exceeded: spent $%.4f this "
                "session, this call could bill $%.4f. Raise the ceiling "
                "deliberately or cut the run."
                % (self.ceiling, self.spent, worst))

    def record(self, usd):
        self.spent += usd
        self.calls += 1


class Ledger(object):
    """Append-only JSONL. One row per call that reached the API."""

    def __init__(self, path):
        self.path = path
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)

    def write(self, row):
        with io.open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    def rows(self):
        if not os.path.exists(self.path):
            return []
        out = []
        for line in io.open(self.path, encoding="utf-8"):
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def by_class(self):
        """Spend per call class - the section 6 tripwire, made readable."""
        out = {}
        for r in self.rows():
            a = out.setdefault(r.get("call_class", "?"),
                               {"calls": 0, "usd": 0.0, "in": 0, "out": 0,
                                "cache_read": 0})
            a["calls"] += 1
            a["usd"] += r.get("usd", 0.0)
            a["in"] += r.get("input_tokens", 0)
            a["out"] += r.get("output_tokens", 0)
            a["cache_read"] += r.get("cache_read_input_tokens", 0)
        return out


# Default location for a key file. Deliberately outside the project tree:
# this repo has no git and therefore no .gitignore to forget to update, and a
# credential sitting next to the data directory is one careless archive away
# from being shared. Nothing here ever prints or logs the key, and it is sent
# to exactly one host.
KEY_FILE = os.path.join(os.path.expanduser("~"), ".anthropic_key")


def read_key(path=None):
    """Key from the environment, else from a file holding nothing else."""
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env:
        return env.strip()
    p = path or KEY_FILE
    if os.path.exists(p):
        return io.open(p, encoding="utf-8").read().strip()
    return ""


class Client(object):
    """One process's worth of model access: key, cache, ledger, ceiling."""

    def __init__(self, root, ceiling_usd, api_key=None, dry_run=False,
                 key_file=None):
        self.root = root
        self.dir = os.path.join(root, "data", "infer")
        self.cache_dir = os.path.join(self.dir, "cache")
        self.ledger = Ledger(os.path.join(self.dir, "ledger.jsonl"))
        self.budget = Budget(ceiling_usd)
        self.dry_run = dry_run
        self.key = api_key or read_key(key_file)
        self._sdk = None
        if not os.path.isdir(self.cache_dir):
            os.makedirs(self.cache_dir)

    def sdk(self):
        """The vendor client, built on first use.

        Lazy because `Client(root, ceiling, dry_run=True)` is how every
        projection and most tests construct this, and those must work with no
        credential present.
        """
        if self._sdk is None:
            self._sdk = anthropic.Anthropic(
                api_key=self.key, max_retries=MAX_RETRIES,
                timeout=TIMEOUT_S)
        return self._sdk

    # -------------------------------------------------------------- cache
    def _key_for(self, body, draw=0):
        """Hash the request exactly as it goes on the wire.

        Keys are sorted so a dict reordering is not a cache miss, and the
        model name is already inside `body`, so a model change *is* one -
        which it must be.

        `draw` is the one thing in this key that is deliberately *not* in the
        request, and it is the mirror image of the `stream` bug in `_store`.
        Replay exists so an experiment is free to re-run; a variance
        experiment needs k independent samples of one identical request,
        which is the same hash k times, so replay would return one answer k
        times and report zero variance. Numbering the draw separates them in
        the store while leaving the bytes on the wire untouched.

        `draw=0` hashes exactly as it did before this argument existed, so
        every response bought earlier still replays for nothing.
        """
        raw = json.dumps(body, sort_keys=True).encode("utf-8")
        if draw:
            raw += ("#draw=%d" % draw).encode("ascii")
        return hashlib.sha256(raw).hexdigest()[:24]

    def cached(self, key):
        p = os.path.join(self.cache_dir, key + ".json")
        if os.path.exists(p):
            return json.load(io.open(p, encoding="utf-8"))
        return None

    def _store(self, key, resp):
        """Stored under the key the LOOKUP computes, not the key the final
        request body would hash to.

        These were two different keys for one call, and it was silent. The
        transport flag `stream` is set after the lookup and before the store,
        so every streamed response was written under a hash nothing would ever
        ask for - the cache appeared to work, filled up, and never hit. It
        cost a re-run of two calls before anyone noticed the spend.

        A transport detail must not be part of the identity of a request
        anyway: the same prompt streamed and unstreamed is the same question.
        """
        p = os.path.join(self.cache_dir, key + ".json")
        with io.open(p, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(resp, sort_keys=True, indent=1))

    def build(self, model, system, user, max_tokens, thinking=False,
              temperature=None):
        """The request body, separated out so a dry run can price the exact
        bytes that would be sent rather than an approximation of them."""
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
        }
        if thinking:
            # Synthesis is the call class where reasoning earns its price - an
            # error there propagates to every page the template touches. Which
            # form to ask for is decided by the model, see ADAPTIVE_THINKING.
            if model in ADAPTIVE_THINKING:
                body["thinking"] = {"type": "adaptive"}
            else:
                # `budget_tokens` must leave room for the answer, so it takes
                # half the ceiling. 1024 is the documented floor.
                body["thinking"] = {"type": "enabled",
                                    "budget_tokens": max(1024,
                                                         max_tokens // 2)}
        if temperature is not None:
            if thinking:
                # Measured 2026-09-21 against the live API:
                #   400 `temperature` may only be set to 1 when thinking is
                #   enabled.
                # So a thinking call has no sampling knob. Dropping the
                # argument quietly would be the worse failure - the run would
                # then be written up as controlled sampling when it was the
                # default - so the caller is refused instead.
                if float(temperature) != 1.0:
                    raise Refused(
                        "temperature=%s requested with extended thinking on; "
                        "the API permits only 1.0 there. Nothing was sent."
                        % (temperature,))
                # 1.0 is what the wire already carries by default. Writing it
                # in would change the request hash and orphan every response
                # bought before this argument existed, for no change in what
                # is actually sent.
            else:
                body["temperature"] = temperature
        return body

    # --------------------------------------------------------------- call
    def message(self, model, system, user, max_tokens, call_class,
                thinking=False, tag="", temperature=None, draw=0):
        """One Messages call. Returns (text, usage, meta).

        `system` carries the cache breakpoint. Section 6 lever 3: synthesis
        resends a large stable prefix against a small variable suffix, so the
        breakpoint goes after the prefix and resends bill at 0.1x. The design
        note says to verify with `cache_read_input_tokens` rather than by
        reading the code, so the ledger records that field and the harness
        prints it.
        """
        body = self.build(model, system, user, max_tokens, thinking,
                          temperature)
        # Computed from the request body alone. Transport concerns - streaming,
        # retries, backoff - belong to the SDK now and cannot reach this dict,
        # which is structurally the bug `_store` describes.
        key = self._key_for(body, draw)

        tr = telemetry.tracer()
        with tr.start_as_current_span("chat %s" % model,
                                      kind=SpanKind.CLIENT) as span:
            # OpenTelemetry GenAI semantic conventions. The names are written
            # out rather than imported from `semconv._incubating`, which is
            # explicitly unstable; these strings are the contract every
            # backend reads.
            span.set_attribute("gen_ai.system", "anthropic")
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.request.model", model)
            span.set_attribute("gen_ai.request.max_tokens", max_tokens)
            if "temperature" in body:
                span.set_attribute("gen_ai.request.temperature",
                                   float(body["temperature"]))
            # Project dimensions, so a span joins to a ledger row.
            span.set_attribute("permits.call_class", call_class)
            span.set_attribute("permits.draw", draw)
            if tag:
                span.set_attribute("permits.tag", tag)

            hit = self.cached(key)
            span.set_attribute("permits.cache_hit", hit is not None)
            if hit is not None:
                return (hit["text"], hit["usage"],
                        {"cached": True, "usd": 0.0, "model": model,
                         "stop_reason": hit.get("stop_reason"),
                         "truncated":
                             hit.get("stop_reason") == "max_tokens"})

            est_in = tokens(system) + tokens(user)
            self.budget.check(model, est_in, max_tokens)
            if self.dry_run:
                raise Refused(
                    "dry run: would call %s (%s), ~%.1fk input tokens, "
                    "max_tokens %d, worst case $%.4f"
                    % (model, call_class, est_in / 1000.0, max_tokens,
                       estimate(model, est_in, max_tokens)))
            if not self.key:
                raise Refused(
                    "no API key: set ANTHROPIC_API_KEY or put the key in %s. "
                    "Nothing was sent." % KEY_FILE)

            t0 = time.time()
            try:
                if max_tokens > STREAM_ABOVE:
                    # Streaming is a method here, not a flag on the request,
                    # so it cannot change the request's identity.
                    with self.sdk().messages.stream(**body) as stream:
                        msg = stream.get_final_message()
                else:
                    msg = self.sdk().messages.create(**body)
            except anthropic.APIError as e:
                elapsed = time.time() - t0
                status = getattr(e, "status_code", None)
                # A failed call was invisible until 2026-09-22: the old client
                # raised before it reached the ledger, so the error rate was
                # structurally unobservable and "67 calls" meant "67 calls
                # that happened to work". Failures are rows now, billed at 0.
                self._log_failure(model, call_class, tag, draw, elapsed,
                                  type(e).__name__, status)
                span.set_attribute("error.type", type(e).__name__)
                if status is not None:
                    span.set_attribute(
                        "gen_ai.response.status_code", int(status))
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)[:200]))
                raise ApiError("%s%s: %s"
                               % (type(e).__name__,
                                  "" if status is None else " %s" % status,
                                  str(e)[:400])) from e
            elapsed = time.time() - t0

            usage = msg.usage.model_dump(mode="json")
            text = "".join(b.text for b in msg.content
                           if getattr(b, "type", None) == "text")
            usd = cost(model, usage)

            span.set_attribute("gen_ai.response.model", msg.model)
            span.set_attribute("gen_ai.response.finish_reasons",
                               [msg.stop_reason or "unknown"])
            span.set_attribute("gen_ai.usage.input_tokens",
                               usage.get("input_tokens", 0) or 0)
            span.set_attribute("gen_ai.usage.output_tokens",
                               usage.get("output_tokens", 0) or 0)
            span.set_attribute("permits.usd", usd)
            span.set_attribute("permits.seconds", round(elapsed, 1))

            self.budget.record(usd)
            self.ledger.write({
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "call_class": call_class, "tag": tag, "model": model,
                "draw": draw,
                "ok": True,
                "usd": round(usd, 6), "seconds": round(elapsed, 1),
                "stop_reason": msg.stop_reason,
                "input_tokens": usage.get("input_tokens", 0) or 0,
                "output_tokens": usage.get("output_tokens", 0) or 0,
                "cache_read_input_tokens": usage.get(
                    "cache_read_input_tokens", 0) or 0,
                "cache_creation_input_tokens": usage.get(
                    "cache_creation_input_tokens", 0) or 0,
            })
            self._store(key, {"text": text, "usage": usage,
                              "stop_reason": msg.stop_reason})
            # A truncated response is a silent wrong answer, which is the
            # failure family this project keeps meeting. It is surfaced as a
            # flag the caller has to look at rather than a short list that
            # looks fine.
            return text, usage, {"cached": False, "usd": usd, "model": model,
                                 "stop_reason": msg.stop_reason,
                                 "truncated":
                                     msg.stop_reason == "max_tokens"}

    def _log_failure(self, model, call_class, tag, draw, elapsed,
                     error_type, status):
        """A ledger row for a call that reached the API and failed.

        `usd` is zero because a rejected request is not billed, but the row
        exists so that the denominator of any success rate computed from this
        ledger is the number of calls *made*. Rows written before 2026-09-22
        have no `ok` field and are read as successes, which they are: the old
        client could not write anything else.
        """
        self.ledger.write({
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "call_class": call_class, "tag": tag, "model": model,
            "draw": draw,
            "ok": False,
            "error_type": error_type,
            "status_code": status,
            "usd": 0.0, "seconds": round(elapsed, 1),
            "stop_reason": None,
            "input_tokens": 0, "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        })
