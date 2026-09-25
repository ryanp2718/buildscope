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

**Two vendor SDKs, and no abstraction over them.** The model axis used to be
three Claude tiers, which is a 5x price band inside one vendor, and a finding
about cost per success measured only inside that band cannot say whether it
survives outside it. Open-weight models reached through OpenRouter are 40-180x
cheaper per draw than Opus 5, so they extend the axis by more than an order of
magnitude. They are reached with the official `openai` SDK pointed at
OpenRouter's base URL, because OpenRouter - like Together, Fireworks, DeepInfra,
Groq, vLLM and Ollama - speaks OpenAI Chat Completions, so one client reaches
all of them and changing provider is a URL.

What there deliberately is not is a `Provider` base class. The two request
shapes differ in the places that matter - the cache breakpoint, the thinking
parameter, the names of the usage fields - and a common interface would push
each of those differences into configuration, which is the argument
[ADR-0009](../docs/adr/0009-adapters-first-generic-extraction-second.md) makes
about extractors and `docs/design/refactoring.md` makes about the adapter
protocol. Two concrete builders and a two-branch dispatch is the right weight.

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
import openai
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

# OpenRouter reaches open-weight models behind an OpenAI-compatible endpoint.
# Its model ids are all `vendor/model`; no Anthropic first-party id contains a
# slash, so the slash is the provider discriminator. That is OpenRouter's own
# addressing scheme rather than a convention invented here.
ANTHROPIC = "anthropic"
OPENROUTER = "openrouter"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def provider_for(model):
    return OPENROUTER if "/" in model else ANTHROPIC


def short_model(model):
    """A filename- and column-safe short name for a model id.

    Synthesis artifacts and variance labels are named by this. An Anthropic id
    carries a date suffix that is noise in a column heading; an OpenRouter id
    carries a vendor prefix and a slash, and a slash in a filename is a
    directory that does not exist. The Anthropic branch is left exactly as the
    three call sites in `scripts/conformance.py` spelled it, so no artifact
    already on disk changes name.
    """
    if provider_for(model) == OPENROUTER:
        return model.split("/")[-1]
    return model.replace("claude-", "").split("-2")[0]


# USD per million tokens, (input, output), read from the live catalogue at
# https://openrouter.ai/api/v1/models on the date below. Unlike PRICES these
# are NOT the figure the ledger bills against: OpenRouter returns what it
# actually charged in `usage.cost`, and that is what gets recorded. A table of
# 459 models whose prices move weekly is precisely the hand-maintained vendor
# capability table that ADR-0017 was written about, so this one is allowed to
# be stale and is used for exactly one thing - the pre-call worst-case budget
# check, where being stale-high stops a run early and stale-low is the only
# dangerous direction. Refresh by re-reading the catalogue.
#
# The ladder spans 88x to 8x cheaper per synthesis draw than Opus 5, which is
# the point: the existing model axis is a 5x band and cannot answer whether
# the cost-per-success inversion survives a wider one.
OPENROUTER_PRICES = {
    "qwen/qwen3.5-flash-02-23": (0.065, 0.260),
    "openai/gpt-oss-120b": (0.150, 0.600),
    # OpenRouter exposes asynchronous variants under a `:batch` suffix at a
    # steep discount - 80% here, not the 50% Anthropic's Batch API gives. The
    # suffix is part of the model id, which is why `--cells` splits on the
    # first and last colon rather than on every one.
    "openai/gpt-oss-120b:batch": (0.0296, 0.136),
    "qwen/qwen3-coder": (0.300, 1.000),
    "moonshotai/kimi-k2-thinking": (0.600, 2.500),
    "z-ai/glm-5.2": (0.650, 2.042),
    "deepseek/deepseek-v4-pro": (0.940, 1.879),
    # Free tier, for verifying the path end to end before any money is added
    # to the account. Deliberately NOT a measurement cell: a free endpoint
    # does not promise which upstream, which quantization or which context
    # window serves a given request, so draws from it are not samples of one
    # condition and a variance number computed over them would describe the
    # routing rather than the model. Use it to prove the wire works.
    "nvidia/nemotron-3-ultra-550b-a55b:free": (0.0, 0.0),
}
OPENROUTER_PRICES_AS_OF = "2026-09-23 (openrouter.ai/api/v1/models)"

# Priced at zero on purpose, as opposed to zero because someone dropped a
# digit. Anything here is excluded from the "every rate is positive" check and
# from anything that reports a measurement.
OPENROUTER_FREE = frozenset(["nvidia/nemotron-3-ultra-550b-a55b:free"])

# Models that accept a reasoning parameter. OpenRouter takes `reasoning` as a
# map and silently ignores it on models that cannot reason, but "silently
# ignores" is how a run gets written up as controlled when it was not, so the
# set is explicit and `build_chat` only sends the key when the model is in it.
OPENROUTER_REASONING = frozenset([
    "moonshotai/kimi-k2-thinking",
    "deepseek/deepseek-v4-pro",
    "z-ai/glm-5.2",
])

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
    """(input, output) $/MTok, from whichever table owns this model."""
    table = OPENROUTER_PRICES if provider_for(model) == OPENROUTER else PRICES
    if model not in table:
        raise Refused(
            "no price on file for %r. Add it to %s with a source before "
            "spending - an unpriced call cannot be logged against the "
            "section 6 tripwire, which is the only reason the ledger exists."
            % (model, "OPENROUTER_PRICES" if provider_for(model) == OPENROUTER
               else "PRICES"))
    return table[model]


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


# Same reasoning as KEY_FILE above, and the same rule: this file is outside
# the project tree, is never printed or logged, and its contents go to exactly
# one host.
OPENROUTER_KEY_FILE = os.path.join(os.path.expanduser("~"), ".openrouter_key")


BOM = "﻿"


def _read_credential(env_name, path):
    """Read a credential from the environment, falling back to a file.

    Decoded as `utf-8-sig`, not `utf-8`, because a key file saved by Notepad
    or written by PowerShell's `Out-File` carries a UTF-8 BOM, and
    `str.strip()` does not remove U+FEFF - it is not whitespace. The BOM then
    rides into the Authorization header, the vendor rejects the request, and
    the 401 reads as a bad key rather than a bad file. `utf-8-sig` is a no-op
    when no BOM is present, so this costs nothing on a clean file.
    """
    env = os.environ.get(env_name)
    if env:
        return env.strip().lstrip(BOM)
    if path and os.path.exists(path):
        return io.open(path, encoding="utf-8-sig").read().strip()
    return ""


def read_key(path=None):
    """Key from the environment, else from a file holding nothing else."""
    return _read_credential("ANTHROPIC_API_KEY", path or KEY_FILE)


def read_openrouter_key(path=None):
    return _read_credential("OPENROUTER_API_KEY", path or OPENROUTER_KEY_FILE)


# OpenAI says "length" where Anthropic says "max_tokens". Every caller reads
# the `truncated` flag, and that flag tests for the Anthropic spelling, so a
# response that ran out of room on OpenRouter would come back looking complete
# if this mapping were missing. That is precisely the silent-truncation
# failure `message` already guards against on the other provider, and it is
# the kind that presents as a short list that looks fine.
FINISH_REASONS = {
    "length": "max_tokens",
    "stop": "end_turn",
    "content_filter": "refusal",
    "tool_calls": "tool_use",
}


def truncated(stop_reason, usage, max_tokens):
    """Whether the answer was cut off, decided on facts and not on a label.

    `stop_reason == "max_tokens"` is the provider's own account of why it
    stopped, and it is the primary signal. It is not the only one: an
    OpenRouter upstream returned `finish_reason: null` on 2026-09-24, and a
    null compares unequal to every spelling of truncation there is. A reply
    that used every token it was authorized is truncated whatever the
    response called it, so the token count is checked too.

    A model that stops naturally on the last authorized token would be
    flagged here as truncated. That is the safe direction: a false positive
    is a visible flag on a good answer, and a false negative is a short list
    of records that looks complete - which is the failure this project exists
    to measure.
    """
    if stop_reason == "max_tokens":
        return True
    out = (usage or {}).get("output_tokens") or 0
    return bool(max_tokens) and out >= max_tokens


def _error_detail(resp):
    """Whatever OpenRouter put in the body to explain an empty response.

    Defensive about the shape because this runs only when something has
    already gone wrong, and a diagnostic that raises while reporting an error
    replaces a useful message with a traceback from the wrong line.
    """
    try:
        d = resp.model_dump(mode="json") if hasattr(resp, "model_dump") else {}
    except Exception:
        return "no detail in the response body"
    err = d.get("error")
    if isinstance(err, dict):
        code = err.get("code")
        msg = err.get("message") or ""
        meta = err.get("metadata") or {}
        prov = meta.get("provider_name") or d.get("provider") or "?"
        raw = str(meta.get("raw") or "")[:200]
        return "%s from %s: %s%s" % (code, prov, msg, (" | " + raw) if raw else "")
    if err:
        return str(err)[:300]
    return "no error object; provider=%s finish=%s" % (
        d.get("provider"), d.get("choices"))


def _usage_from_chat(u):
    """OpenAI usage in Anthropic field names, plus what was actually billed.

    Two traps here, both of the silent-wrong-number kind that
    `docs/design/testing.md` says this project keeps meeting.

    **`prompt_tokens` includes cached tokens; `input_tokens` excludes them.**
    Anthropic reports the cached portion separately and bills it separately.
    Copying the field straight across would double-count every cached token in
    any sum over the ledger, and the ledger is one table read by `by_class`,
    by the variance analysis and by `scripts/check_internal.py` alike. So the
    cached count is subtracted, and after this both providers' rows mean the
    same thing.

    **`cost` is authoritative and the local price table is not.** OpenRouter
    returns what it actually charged. `OPENROUTER_PRICES` exists only to give
    `Budget` a worst case before the call, where being stale-high is safe. So
    the billed figure is returned separately and preferred by the caller. It
    can be absent, in which case the caller falls back to the table and is
    wrong by however stale that table is - which is worth knowing, and is why
    the fallback is not silent in the ledger row.
    """
    if u is None:
        return {"input_tokens": 0, "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0}, None
    d = u.model_dump(mode="json") if hasattr(u, "model_dump") else dict(u)
    det = d.get("prompt_tokens_details") or {}
    cached = det.get("cached_tokens") or 0
    written = det.get("cache_write_tokens") or 0
    prompt = d.get("prompt_tokens") or 0
    usage = {
        "input_tokens": max(0, prompt - cached),
        "output_tokens": d.get("completion_tokens") or 0,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": written,
    }
    billed = d.get("cost")
    return usage, (float(billed) if billed is not None else None)


class Client(object):
    """One process's worth of model access: key, cache, ledger, ceiling."""

    def __init__(self, root, ceiling_usd, api_key=None, dry_run=False,
                 key_file=None, openrouter_key=None,
                 openrouter_key_file=None):
        self.root = root
        self.dir = os.path.join(root, "data", "infer")
        self.cache_dir = os.path.join(self.dir, "cache")
        self.ledger = Ledger(os.path.join(self.dir, "ledger.jsonl"))
        self.budget = Budget(ceiling_usd)
        self.dry_run = dry_run
        # `None` means resolve from environment or file; `""` means this
        # caller is asserting there is no credential. `or` collapsed those
        # two, so a test passing `api_key=""` silently picked up the real key
        # off the developer's disk - which made the suite's "no key needed"
        # property depend on whether a key happened to exist, and printed key
        # material into an assertion message when it did.
        self.key = read_key(key_file) if api_key is None else api_key
        self.or_key = (read_openrouter_key(openrouter_key_file)
                       if openrouter_key is None else openrouter_key)
        self._sdk = None
        self._oai = None
        if not os.path.isdir(self.cache_dir):
            os.makedirs(self.cache_dir)

    def key_for(self, model):
        """The credential this model's provider needs, or empty string.

        Callers check this rather than `.key` so that having one of the two
        credentials configured does not read as having the other.
        """
        return self.or_key if provider_for(model) == OPENROUTER else self.key

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

    def oai(self):
        """The OpenAI-compatible client, pointed at OpenRouter.

        Lazy for the same reason as `sdk`. Retry and timeout are set to the
        same explicit values: the reason for them is the shape of this
        project's calls - long, expensive, unattended - which is a property
        of the workload and not of the vendor.
        """
        if self._oai is None:
            self._oai = openai.OpenAI(
                api_key=self.or_key, base_url=OPENROUTER_BASE_URL,
                max_retries=MAX_RETRIES, timeout=TIMEOUT_S)
        return self._oai

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

    def build_chat(self, model, system, user, max_tokens, thinking=False,
                   temperature=None):
        """The same question in OpenAI Chat Completions shape.

        Three deliberate differences from `build`, each of which is why there
        is no shared abstraction over the two:

        - **No cache breakpoint.** `cache_control` is an Anthropic request
          field. OpenRouter's upstreams cache on their own terms and report
          what they did in `usage.prompt_tokens_details`. There is nothing to
          ask for, so nothing is asked for. Measured 2026-09-23, this costs
          almost nothing either way: the cacheable prefix is 889 tokens of a
          13,535-token request, so the ceiling on prefix caching for this
          workload is about 6% of input spend.
        - **Reasoning is an effort level, not a token budget.** Sent as
          `reasoning_effort`, which the SDK takes as a named parameter, so
          this body splats into `create()` exactly as the Anthropic one does.
        - **Temperature is not refused alongside thinking.** That refusal in
          `build` exists because the Anthropic API returns a 400 for it. It
          is a fact about one vendor, not a house rule, and asserting it here
          would be inventing a constraint the endpoint does not have.
        """
        body = {
            "model": model,
            # `max_tokens`, not `max_completion_tokens`: the newer name is
            # for OpenAI's own models and this client only ever points at
            # OpenRouter, which takes the original.
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        if thinking and model in OPENROUTER_REASONING:
            body["reasoning_effort"] = "medium"
        if temperature is not None:
            body["temperature"] = temperature
        return body

    # --------------------------------------------------------------- call
    def message(self, model, system, user, max_tokens, call_class,
                thinking=False, tag="", temperature=None, draw=0):
        """One model call, on whichever provider owns `model`.

        Returns (text, usage, meta). `usage` is in Anthropic field names
        whatever the provider was - see `_usage_from_chat` for why the
        translation happens here rather than at every reader.

        On Anthropic, `system` carries the cache breakpoint. Section 6 lever 3:
        synthesis resends a large stable prefix against a small variable
        suffix, so the breakpoint goes after the prefix and resends bill at
        0.1x. The design note says to verify with `cache_read_input_tokens`
        rather than by reading the code, so the ledger records that field and
        the harness prints it. Measured 2026-09-23 over 67 calls, that lever
        is worth about 2% of total spend on this workload, because the prefix
        it caches is 6.6% of the request.
        """
        prov = provider_for(model)
        body = (self.build_chat(model, system, user, max_tokens, thinking,
                                temperature)
                if prov == OPENROUTER
                else self.build(model, system, user, max_tokens, thinking,
                                temperature))
        # Computed from the request body alone. Transport concerns - streaming,
        # retries, backoff - belong to the SDK now and cannot reach this dict,
        # which is structurally the bug `_store` describes.
        #
        # Nothing about the second provider needed a migration here: the two
        # bodies differ in shape and both carry `model`, so an OpenRouter call
        # cannot collide with a Claude one, and every response bought before
        # this existed still hashes to the key it was stored under.
        key = self._key_for(body, draw)

        tr = telemetry.tracer()
        with tr.start_as_current_span("chat %s" % model,
                                      kind=SpanKind.CLIENT) as span:
            # OpenTelemetry GenAI semantic conventions. The names are written
            # out rather than imported from `semconv._incubating`, which is
            # explicitly unstable; these strings are the contract every
            # backend reads.
            span.set_attribute("gen_ai.system", prov)
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
                         "truncated": truncated(hit.get("stop_reason"),
                                                hit.get("usage"),
                                                max_tokens)})

            est_in = tokens(system) + tokens(user)
            self.budget.check(model, est_in, max_tokens)
            if self.dry_run:
                raise Refused(
                    "dry run: would call %s (%s), ~%.1fk input tokens, "
                    "max_tokens %d, worst case $%.4f"
                    % (model, call_class, est_in / 1000.0, max_tokens,
                       estimate(model, est_in, max_tokens)))
            if not self.key_for(model):
                raise Refused(
                    "no API key for %s: set %s or put the key in %s. "
                    "Nothing was sent."
                    % (prov,
                       "OPENROUTER_API_KEY" if prov == OPENROUTER
                       else "ANTHROPIC_API_KEY",
                       OPENROUTER_KEY_FILE if prov == OPENROUTER
                       else KEY_FILE))

            t0 = time.time()
            try:
                if prov == OPENROUTER:
                    (text, usage, stop_reason, resp_model,
                     billed) = self._send_chat(body)
                else:
                    (text, usage, stop_reason, resp_model,
                     billed) = self._send_messages(body, max_tokens)
            except (anthropic.APIError, openai.APIError) as e:
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

            # What the provider says it charged beats what the local table
            # thinks it costs. Anthropic reports no such figure, so that path
            # prices from PRICES exactly as it always has.
            usd = cost(model, usage) if billed is None else billed

            span.set_attribute("gen_ai.response.model", resp_model or model)
            span.set_attribute("gen_ai.response.finish_reasons",
                               [stop_reason or "unknown"])
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
                "provider": prov,
                "draw": draw,
                "ok": True,
                # True when this row's dollars came from the provider rather
                # than from the local price table. A sum over the ledger that
                # mixes the two is still correct; one that needs to know how
                # it was derived can ask.
                "usd_reported": billed is not None,
                "usd": round(usd, 6), "seconds": round(elapsed, 1),
                "stop_reason": stop_reason,
                "input_tokens": usage.get("input_tokens", 0) or 0,
                "output_tokens": usage.get("output_tokens", 0) or 0,
                "cache_read_input_tokens": usage.get(
                    "cache_read_input_tokens", 0) or 0,
                "cache_creation_input_tokens": usage.get(
                    "cache_creation_input_tokens", 0) or 0,
            })
            self._store(key, {"text": text, "usage": usage,
                              "stop_reason": stop_reason})
            # A truncated response is a silent wrong answer, which is the
            # failure family this project keeps meeting. It is surfaced as a
            # flag the caller has to look at rather than a short list that
            # looks fine.
            return text, usage, {"cached": False, "usd": usd, "model": model,
                                 "provider": prov,
                                 "stop_reason": stop_reason,
                                 "truncated": truncated(stop_reason, usage,
                                                        max_tokens)}

    def _send_messages(self, body, max_tokens):
        """Anthropic transport. Returns the five things `message` needs.

        `billed` is None because Anthropic does not report a charge on the
        response; that path prices from PRICES, as it always has.
        """
        if max_tokens > STREAM_ABOVE:
            # Streaming is a method here, not a flag on the request, so it
            # cannot change the request's identity.
            with self.sdk().messages.stream(**body) as stream:
                msg = stream.get_final_message()
        else:
            msg = self.sdk().messages.create(**body)
        usage = msg.usage.model_dump(mode="json")
        text = "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text")
        return text, usage, msg.stop_reason, msg.model, None

    def _send_chat(self, body):
        """OpenRouter transport, same five things.

        No streaming branch. STREAM_ABOVE exists because a long Anthropic
        request can outlive the server's own request timeout; OpenRouter holds
        the connection for the upstream and the 900-second client timeout is
        the binding one. Adding a streaming path here on the strength of the
        other vendor's constraint would be guessing, and a guess that changes
        how a request is sent is how the `stream` cache-key bug happened.
        """
        resp = self.oai().chat.completions.create(**body)
        if not resp.choices:
            # A response with no choices is a wrong answer waiting to happen:
            # the caller would read empty text as an extractor that produced
            # nothing rather than a call that returned nothing.
            #
            # The reason is in the body, not the status line. OpenRouter
            # answers an upstream failure with HTTP 200 and an `error` object,
            # so the SDK raises nothing and there is no status code to report.
            # Without this the operator sees "no choices" and cannot tell a
            # rate limit from a context overflow from a dead provider.
            raise ApiError(
                "OpenRouter returned no choices for %r: %s"
                % (body.get("model"), _error_detail(resp)))
        choice = resp.choices[0]
        text = choice.message.content or ""
        usage, billed = _usage_from_chat(resp.usage)
        stop = FINISH_REASONS.get(choice.finish_reason, choice.finish_reason)
        return text, usage, stop, resp.model, billed

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
            "provider": provider_for(model),
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
