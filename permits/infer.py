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
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from typing import Any

import anthropic
import httpx2
import openai
from opentelemetry.trace import SpanKind, Status, StatusCode

from permits import fileio, models, telemetry
from permits.models import ModelSpec, Protocol, Provider, ReasoningControl

# A request body as it goes on the wire and into the cache key. Left as a
# plain JSON object on purpose: its bytes are the cache identity, and a typed
# wrapper would be one more place for them to drift.
Body = dict[str, Any]

# Retries, timeouts and the wall-clock limit. The fairness audit (F5,
# docs/evidence/2026-09-26-model-comparison-fairness-audit.md) found that a
# single 900 s float bounded each socket read, not the call: one deepseek
# draw held a request open for 65,161 s, and nothing could tell a slow host
# from a sleeping client.
#
# Every call streams, so the SDK's own retries (MAX_RETRIES, with backoff)
# happen only before the response starts. A retry therefore never re-buys a
# generation. The SDK default is 2; this workload is long, expensive and
# unattended, so 429s and 5xx at connect time get more.
MAX_RETRIES = 5
# `read` is the longest silence allowed between two chunks of a stream, not
# the length of the call. Both APIs send keep-alives while a model thinks, so
# 120 s of nothing is a dead connection.
TIMEOUT = httpx2.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
# The harness bounds the call itself: a fixed allowance for queueing and
# first token, plus the ceiling at 10 tokens a second. The slowest successful
# call in the ledger ran at 15 tok/s (41,680 tokens in 2,802 s) and the median
# at 113, so this limit binds on a stalled or trickling host, not on a slow
# model. A call that hits it is an infrastructure error, not a model failure.
WALL_GRACE_S = 300.0
MIN_TOKENS_PER_S = 10.0
# Attempts per draw at the harness level: one retry of a transient failure,
# under the same draw number, then the draw is recorded as `infra_error`.
ATTEMPTS = 2
# HTTP statuses a retry can fix. Everything else below 500 is a rejection
# that will repeat (bad request, credential, credit, unknown model).
RETRYABLE_STATUS = frozenset({408, 409, 429})


def wall_limit(max_tokens: int) -> float:
    """Seconds one attempt may take, end to end."""
    return WALL_GRACE_S + max_tokens / MIN_TOKENS_PER_S

# Every per-model fact - provider, price, reasoning control, short name - is
# in the registry in `permits/models.py`. These names are re-exported because
# they are what the rest of the harness and the tests have always read.
ANTHROPIC = Provider.ANTHROPIC
OPENROUTER = Provider.OPENROUTER
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
PRICES_AS_OF = models.PRICES_AS_OF
OPENROUTER_PRICES_AS_OF = models.OPENROUTER_PRICES_AS_OF
REASONING_HEADROOM = models.REASONING_HEADROOM


def spec(model: str) -> ModelSpec:
    """The registry entry for `model`, or `Refused` if there is none."""
    try:
        return models.get(model)
    except models.UnknownModel as e:
        raise Refused(str(e)) from None


def provider_for(model: str) -> Provider:
    return spec(model).provider


def short_model(model: str) -> str:
    """A filename- and column-safe short name for a model id. See
    `ModelSpec.short`."""
    return spec(model).short


# Protocol v1, frozen: the models v1 sent `reasoning_effort: "medium"` and
# `REASONING_HEADROOM` to. A record of what was sent, not a capability list:
# gpt-oss-120b and qwen3.5-flash reason and are not here (finding F2), and
# four of the five do not accept "medium" (the step 3 plan in the audit).
V1_EFFORT = frozenset({
    "moonshotai/kimi-k2-thinking", "z-ai/glm-5.2", "deepseek/deepseek-v4-pro",
    "z-ai/glm-5.3-flash", "deepseek/deepseek-v4-flash"})

# Protocol v2: tokens kept out of Haiku's thinking budget for the answer, so
# the budget never binds before the cap does. It matches the answer budget
# v1 held constant for the OpenRouter reasoning models.
ANSWER_RESERVE = 16000


def ceiling_for(model: str, max_tokens: int,
                protocol: Protocol = Protocol.V2) -> int:
    """The `max_tokens` to put on the wire.

    Under v2 the caller's `max_tokens` is the whole allowance, reasoning
    included, and goes out unchanged; synthesis passes `output_cap(model)`,
    the same 64,000 for every model. Under v1 the answer budget was held
    constant and the OpenRouter models sent a reasoning effort got
    `REASONING_HEADROOM` on top, while Claude's thinking came out of its own
    budget (finding F1). That rule is kept so v1 requests hash as they did.
    """
    spec(model)
    if protocol is Protocol.V1 and model in V1_EFFORT:
        return max_tokens + REASONING_HEADROOM
    return max_tokens


def output_cap(model: str) -> int:
    """Protocol v2's cap for `model`: see `models.OUTPUT_CAP`."""
    return models.output_cap(spec(model))


def redraw_cap(model: str) -> int:
    """The cap a truncated v2 draw is re-drawn at: see `models.REDRAW_CAP`."""
    return models.redraw_cap(spec(model))


def settings_sent(body: Body, protocol: Protocol) -> dict[str, Any]:
    """The experimental settings a request body carries, for the ledger.

    Read back from the body rather than from the registry, so the row
    records what went on the wire. Temperature is 1.0 on a Claude thinking
    call, which the API fixes and the body does not carry; None elsewhere
    means nothing was sent and the API or host chose.

    `reasoning_level` is the lab's name for the level an effort reaches
    (`models.lab_level`), recorded because OpenRouter's name and the lab's
    differ. None where no effort is sent, and under v1, where what `medium`
    reached depended on the serving endpoint.
    """
    thinking = body.get("thinking")
    reasoning: str | None = None
    level: str | None = None
    if thinking:
        reasoning = ("adaptive" if thinking["type"] == "adaptive"
                     else "budget=%d" % thinking["budget_tokens"])
    elif "reasoning" in body:
        r = body["reasoning"]
        reasoning = "effort=%s" % r["effort"] if "effort" in r else "enabled"
        if "effort" in r:
            level = models.lab_level(spec(str(body["model"])), r["effort"])
    elif "reasoning_effort" in body:
        reasoning = "effort=%s" % body["reasoning_effort"]
    temperature = body.get("temperature", 1.0 if thinking else None)
    return {"protocol": str(protocol), "max_tokens": int(body["max_tokens"]),
            "reasoning": reasoning, "reasoning_level": level,
            "temperature": temperature, "top_p": body.get("top_p")}


# Cache reads bill at 0.1x input; 5-minute writes at 1.25x. Section 6 lever 3.
# A model whose reads bill otherwise (Opus 5.5, 0.05x) says so in its
# registry entry's `cache_read`, which `cost` uses.
CACHE_READ = 0.1
CACHE_WRITE = 1.25

class Refused(Exception):
    """A call that was not made. Never raised after money has been spent."""


class ApiError(Exception):
    """A call that was sent and failed."""


class FatalError(ApiError):
    """Rejected for a reason a retry will not fix: a credential, credit, or a
    malformed request. Stops the run."""


class TransientError(ApiError):
    """Failed on the host side on every attempt: a timeout, a dropped
    connection, overload or a 5xx, an error inside the stream, or the
    wall-clock limit. The draw is recorded as `infra_error` and the cell
    continues."""


class _HostError(Exception):
    """A host failure the harness detects itself rather than the SDK: a
    stream that ended without choices or usage, an `error` finish, a stream
    closed with no finish reason short of the cap, or the wall-clock limit.

    `billed`, `output_tokens` and `host` are set when the stream got as far as
    its usage block, so the failed attempt's ledger row carries what the host
    charged for it rather than zero."""

    def __init__(self, message: str, billed: float | None = None,
                 output_tokens: int | None = None,
                 host: str | None = None) -> None:
        super().__init__(message)
        self.billed = billed
        self.output_tokens = output_tokens
        self.host = host


# What a transport can raise. `httpx2.RequestError` is listed because the
# Anthropic SDK lets transport errors escape unwrapped from inside a stream;
# the OpenAI SDK wraps the same errors as `APIConnectionError`.
TRANSPORT_ERRORS = (anthropic.APIError, openai.APIError, httpx2.RequestError,
                    _HostError)


def is_transient(e: BaseException) -> bool:
    """Whether a failed call is worth one more attempt.

    A status below 400 is an error sent inside a stream that started with
    200; Anthropic reports those with the stream's status. An API error with
    no status at all is the OpenAI SDK's form of the same thing.
    """
    if isinstance(e, (_HostError, httpx2.RequestError,
                      anthropic.APIConnectionError,
                      openai.APIConnectionError)):
        return True
    status = getattr(e, "status_code", None)
    if status is None:
        return True
    return int(status) < 400 or status in RETRYABLE_STATUS or status >= 500


@dataclass
class _Clock:
    """The wall time of one attempt, when its first token arrived, and the
    id the provider gave the response.

    Monotonic, and on Windows it keeps counting while the machine sleeps, so
    a suspended client now trips the wall-clock limit instead of being
    recorded as a 65,000-second call.

    The id is kept here rather than on the reply because a failed attempt
    has no reply, and the failure row needs it most: it is what the
    provider's own record of the call is looked up by (OpenRouter's
    `GET /generation?id=`, which carries the serving host, native token
    counts and cost).
    """
    limit_s: float
    start: float = field(default_factory=time.monotonic)
    first: float | None = None
    response_id: str | None = None

    def token(self) -> None:
        if self.first is None:
            self.first = time.monotonic()

    def check(self) -> None:
        if time.monotonic() - self.start > self.limit_s:
            raise _HostError("wall-clock limit of %.0f s reached"
                             % self.limit_s)

    def elapsed(self) -> float:
        return round(time.monotonic() - self.start, 1)

    def ttft(self) -> float | None:
        return None if self.first is None else round(self.first - self.start,
                                                     1)


# ------------------------------------------------------------ records
# Frozen dataclasses rather than dicts. Before 2026-09-26 every one of these
# was a dict read back with `.get("field", 0) or 0`, so a misspelled field
# read as zero instead of raising - the silent-wrong-number failure this
# project exists to catch. The on-disk formats (cache entries, ledger lines)
# are unchanged; these are the typed view of them.


@dataclass(frozen=True)
class Usage:
    """Token counts for one response, in Anthropic's field names whatever the
    provider was. `input_tokens` excludes cached tokens on both providers; see
    `_usage_from_chat` for why that needs a subtraction on OpenRouter."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    # The part of `output_tokens` spent reasoning, on both providers. None
    # when the response did not say, which is not the same as zero: the
    # OpenRouter cache entries written before 2026-09-26 did not keep it.
    reasoning_tokens: int | None = None

    @classmethod
    def from_dict(cls, d: Mapping[str, Any] | None) -> "Usage":
        """From a stored or SDK-dumped usage block.

        A missing or null count is zero: a deployment may omit the cache
        fields entirely, and a missing field must not be billed as a
        full-price input token. Reasoning tokens are read from the translated
        OpenRouter field or from Anthropic's
        `output_tokens_details.thinking_tokens`. Other fields (Anthropic's
        `service_tier`) stay in the cache entry and are not read here.
        """
        d = d or {}
        counts = {k: int(d.get(k) or 0) for k in (
            "input_tokens", "output_tokens", "cache_read_input_tokens",
            "cache_creation_input_tokens")}
        r = d.get("reasoning_tokens")
        if r is None:
            r = (d.get("output_tokens_details") or {}).get("thinking_tokens")
        return cls(**counts, reasoning_tokens=None if r is None else int(r))

    def to_dict(self) -> dict[str, int]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass(frozen=True)
class Completion:
    """What `Client.message` returns: the text and everything a caller needs
    to price, flag and record it."""
    text: str
    usage: Usage
    model: str
    provider: Provider
    # True when replayed from the cache, in which case `usd` is 0.0: this
    # call cost nothing, whatever the original purchase cost.
    cached: bool
    usd: float
    stop_reason: str | None
    # A truncated response is a silent wrong answer, which is the failure
    # family this project keeps meeting. It is surfaced as a flag the caller
    # has to look at rather than a short list that looks fine.
    truncated: bool
    # The OpenRouter upstream that served it, or "anthropic". None for a
    # response cached before hosts were recorded.
    host: str | None = None
    # OpenRouter's generation id or Anthropic's message id. None for a
    # response cached before ids were recorded.
    response_id: str | None = None


_WHEN_KNOWN = ("ttft_s", "protocol", "max_tokens", "reasoning",
               "reasoning_level", "temperature", "top_p", "host",
               "reasoning_tokens", "response_id")


@dataclass(frozen=True)
class LedgerRow:
    """One line of `data/infer/ledger.jsonl`: one call that reached the API.

    Success rows carry `usd_reported`; failure rows carry `error_type` and
    `status_code` instead. `to_dict` reproduces exactly that shape, so rows
    written through this type are byte-compatible with the 266 written before
    it existed. The fields after `status_code` were added later and are
    written only when known.
    """
    at: str
    call_class: str
    tag: str
    model: str
    provider: str
    draw: int
    ok: bool
    usd: float
    seconds: float
    stop_reason: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    # True when `usd` came from the provider's reported charge rather than
    # from the registry price. A sum over the ledger that mixes the two is
    # still correct; one that needs to know how it was derived can ask.
    usd_reported: bool | None = None
    error_type: str | None = None
    status_code: int | None = None
    # Seconds from sending to the first streamed token, thinking included
    # where the host streams it. Absent on rows written before 2026-09-26.
    # On a failure row it means tokens were generated before the call died,
    # so the host may have billed for them; `usd` there is 0.0 because
    # nothing reports what, except on a stream the host closed with its usage
    # block sent (`cut_by_host`), where `usd` is the reported charge.
    ttft_s: float | None = None
    # What was asked for (`settings_sent`) and who answered. Absent on rows
    # written before 2026-09-26, whose settings are protocol v1's.
    protocol: str | None = None
    max_tokens: int | None = None
    reasoning: str | None = None
    reasoning_level: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    host: str | None = None
    reasoning_tokens: int | None = None
    # The provider's id for the response, so the row can be reconciled with
    # the provider's record of it. Absent on rows written before 2026-09-27.
    response_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        drop = ("error_type", "status_code") if self.ok else ("usd_reported",)
        for k in drop:
            del d[k]
        for k in _WHEN_KNOWN:
            if d[k] is None:
                del d[k]
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "LedgerRow":
        """Read a ledger line, including the older shapes.

        Rows written before 2026-09-22 have no `ok` field and are successes:
        the old client could not write anything else. Rows written before
        2026-09-23 have no `provider`, and were all Anthropic calls, which
        the registry resolves. Twelve early rows have no `draw`; a missing
        draw hashed as draw 0. A field this type does not name raises,
        because a misspelled field is exactly what the dict version hid.
        """
        known = {f.name for f in fields(cls)}
        extra = sorted(set(d) - known)
        if extra:
            raise ValueError("unknown ledger field(s) %s" % ", ".join(extra))
        row = dict(d)
        row.setdefault("ok", True)
        row.setdefault("draw", 0)
        if "provider" not in row:
            row["provider"] = str(provider_for(row["model"]))
        return cls(**row)


def price(model: str) -> tuple[float, float]:
    """(input, output) $/MTok that `Budget` and `cost` use for this model."""
    return spec(model).price


def cost(model: str, usage: Usage) -> float:
    """Dollars for one response's usage, priced from the registry."""
    pin, pout = price(model)
    return ((usage.input_tokens
             + usage.cache_read_input_tokens * spec(model).cache_read
             + usage.cache_creation_input_tokens * CACHE_WRITE) * pin
            + usage.output_tokens * pout) / 1e6


def estimate(model: str, in_tokens: int, out_tokens: int) -> float:
    pin, pout = price(model)
    return (in_tokens * pin + out_tokens * pout) / 1e6


def tokens(text: str) -> int:
    """Token count without a tokenizer, for projections only.

    `scripts/measure_tokens.py` established the bracket on this project's own
    pages: plain English runs ~4 chars/token on a BPE vocabulary, HTML nearer
    3 because it is denser in punctuation. A projection quotes the pessimistic
    end, because a budget estimate that is wrong should be wrong in the
    direction that stops early.
    """
    return int(len(text) / 3.0)


class Budget:
    """A ceiling in dollars, checked before each call against its worst case.

    Worst case, not expected case: `max_tokens` is what the request authorizes
    the model to bill, so that is what the ceiling is tested against. A guard
    that admits calls on the basis of what usually happens is not a guard.
    """

    def __init__(self, ceiling_usd: float) -> None:
        self.ceiling = float(ceiling_usd)
        self.spent = 0.0
        self.calls = 0

    def check(self, model: str, in_tokens: int, max_tokens: int) -> None:
        worst = estimate(model, in_tokens, max_tokens)
        if self.spent + worst > self.ceiling:
            raise Refused(
                "budget ceiling $%.2f would be exceeded: spent $%.4f this "
                "session, this call could bill $%.4f. Raise the ceiling "
                "deliberately or cut the run."
                % (self.ceiling, self.spent, worst))

    def record(self, usd: float) -> None:
        self.spent += usd
        self.calls += 1


class Ledger:
    """Append-only JSONL. One row per call that reached the API."""

    def __init__(self, path: str) -> None:
        self.path = path
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            os.makedirs(d)

    def write(self, row: LedgerRow) -> None:
        # Under a lock: two processes appending at once can interleave
        # their bytes on Windows, which leaves one unreadable line that
        # `rows()` then fails on for good.
        with fileio.lock_for(self.path):
            with io.open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row.to_dict(), sort_keys=True) + "\n")

    def rows(self) -> list[LedgerRow]:
        if not os.path.exists(self.path):
            return []
        with io.open(self.path, encoding="utf-8") as fh:
            return [LedgerRow.from_dict(json.loads(line))
                    for line in fh if line.strip()]

    def by_class(self) -> dict[str, dict[str, float]]:
        """Spend per call class - the section 6 tripwire, made readable."""
        out: dict[str, dict[str, float]] = {}
        for r in self.rows():
            a = out.setdefault(r.call_class,
                               {"calls": 0, "usd": 0.0, "in": 0, "out": 0,
                                "cache_read": 0})
            a["calls"] += 1
            a["usd"] += r.usd
            a["in"] += r.input_tokens
            a["out"] += r.output_tokens
            a["cache_read"] += r.cache_read_input_tokens
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


def _read_credential(env_name: str, path: str | None) -> str:
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
        with io.open(path, encoding="utf-8-sig") as fh:
            return fh.read().strip()
    return ""


def read_key(path: str | None = None) -> str:
    """Key from the environment, else from a file holding nothing else."""
    return _read_credential("ANTHROPIC_API_KEY", path or KEY_FILE)


def read_openrouter_key(path: str | None = None) -> str:
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


def truncated(stop_reason: str | None, usage: Usage | None,
              max_tokens: int) -> bool:
    """Whether the answer was cut off, decided on facts and not on a label.

    `stop_reason == "max_tokens"` is the provider's own account of why it
    stopped, and it is the primary signal. It is not the only one: an
    OpenRouter upstream returned `finish_reason: null` on 2026-09-24, and a
    null compares unequal to every spelling of truncation there is. A reply
    that used every token it was authorized is truncated whatever the
    response called it, so the token count is checked too.

    A missing or unrecognised label with the whole budget used is flagged.
    That is the safe direction: a false positive is a visible flag on a good
    answer, and a false negative is a short list of records that looks
    complete - which is the failure this project exists to measure.

    A natural stop is believed over the count. xAI billed grok-4.7 66,437
    output tokens against a `max_tokens` of 64,000 on 2026-09-28 and stopped
    on `end_turn` with a complete answer: the host let it run past the cap,
    and the answer was not cut off. Flagging that as truncated would re-draw
    a finished answer (step 6 pre-registration, deviation 1 and amendment 2).
    """
    if stop_reason == "max_tokens":
        return True
    if stop_reason in NATURAL_STOPS:
        return False
    out = usage.output_tokens if usage is not None else 0
    return bool(max_tokens) and out >= max_tokens


def cut_by_host(stop_reason: str | None, usage: Usage | None,
                max_tokens: int) -> bool:
    """A stream the host closed before the model finished: no stop reason,
    and fewer tokens than the cap.

    Neither a natural stop nor the cap, so neither the model's answer nor a
    truncation. On 2026-09-28 AtlasCloud closed glm-5.3-flash streams at 301 s
    and Phala at 602 s, mid-reasoning, with a usage block and no finish reason
    in OpenRouter's own generation record; the empty text was scored
    `no_code`, a model failure, seven times. It is a host failure (step 6
    pre-registration, deviation 2). With the whole budget used, a missing
    reason is still read as truncation, as `truncated` says."""
    out = usage.output_tokens if usage is not None else 0
    return stop_reason is None and not (max_tokens and out >= max_tokens)


# Stop reasons that say the model finished on its own, in Anthropic's
# spelling, which `FINISH_REASONS` maps OpenRouter's onto.
NATURAL_STOPS = frozenset({"end_turn", "stop_sequence", "tool_use", "refusal"})


def _error_detail(resp: Any) -> str:
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


def _usage_from_chat(u: Any) -> tuple[dict[str, int], float | None]:
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
    returns what it actually charged. The registry ceiling exists only to give
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
    # Part of `completion_tokens`, not in addition to it. Kept only when the
    # response reports it, so a missing figure does not read as zero.
    thought = (d.get("completion_tokens_details") or {}).get("reasoning_tokens")
    if thought is not None:
        usage["reasoning_tokens"] = int(thought)
    billed = d.get("cost")
    return usage, (float(billed) if billed is not None else None)


# Request fields OpenRouter reads that the OpenAI SDK has no parameter for.
EXTRA_BODY = frozenset({"reasoning", "provider"})


@dataclass(frozen=True)
class _Reply:
    """What a transport hands back to `message`. `billed` is the provider's
    reported charge (None on Anthropic, which reports none); `host` is who
    served the request."""
    text: str
    usage: dict[str, Any]
    stop_reason: str | None
    model: str
    billed: float | None
    host: str | None


class Client:
    """One process's worth of model access: key, cache, ledger, ceiling."""

    def __init__(self, root: str, ceiling_usd: float,
                 api_key: str | None = None, dry_run: bool = False,
                 key_file: str | None = None,
                 openrouter_key: str | None = None,
                 openrouter_key_file: str | None = None) -> None:
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
        self._sdk: anthropic.Anthropic | None = None
        self._oai: openai.OpenAI | None = None
        if not os.path.isdir(self.cache_dir):
            os.makedirs(self.cache_dir)

    def key_for(self, model: str) -> str:
        """The credential this model's provider needs, or empty string.

        Callers check this rather than `.key` so that having one of the two
        credentials configured does not read as having the other.
        """
        return self.or_key if provider_for(model) == OPENROUTER else self.key

    def sdk(self) -> anthropic.Anthropic:
        """The vendor client, built on first use.

        Lazy because `Client(root, ceiling, dry_run=True)` is how every
        projection and most tests construct this, and those must work with no
        credential present.
        """
        if self._sdk is None:
            self._sdk = anthropic.Anthropic(
                api_key=self.key, max_retries=MAX_RETRIES, timeout=TIMEOUT)
        return self._sdk

    def oai(self) -> openai.OpenAI:
        """The OpenAI-compatible client, pointed at OpenRouter.

        Lazy for the same reason as `sdk`. Retry and timeout are set to the
        same explicit values: the reason for them is the shape of this
        project's calls - long, expensive, unattended - which is a property
        of the workload and not of the vendor.
        """
        if self._oai is None:
            self._oai = openai.OpenAI(
                api_key=self.or_key, base_url=OPENROUTER_BASE_URL,
                max_retries=MAX_RETRIES, timeout=TIMEOUT)
        return self._oai

    # -------------------------------------------------------------- cache
    def _key_for(self, body: Body, draw: int = 0) -> str:
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

    def cached(self, key: str) -> dict[str, Any] | None:
        p = os.path.join(self.cache_dir, key + ".json")
        if os.path.exists(p):
            with io.open(p, encoding="utf-8") as fh:
                entry: dict[str, Any] = json.load(fh)
            return entry
        return None

    def _store(self, key: str, resp: dict[str, Any]) -> None:
        """Stored under the key the LOOKUP computes, not the key the final
        request body would hash to.

        These were two different keys for one call, and it was silent. The
        transport flag `stream` is set after the lookup and before the store,
        so every streamed response was written under a hash nothing would ever
        ask for - the cache appeared to work, filled up, and never hit. It
        cost a re-run of two calls before anyone noticed the spend.

        A transport detail must not be part of the identity of a request
        anyway: the same prompt streamed and unstreamed is the same question.

        Written atomically: a write cut off halfway used to leave truncated
        JSON that failed to load every time the key was hit afterwards, for
        a response already paid for.
        """
        p = os.path.join(self.cache_dir, key + ".json")
        fileio.atomic_write(p, json.dumps(resp, sort_keys=True, indent=1))

    def build(self, model: str, system: str, user: str, max_tokens: int,
              thinking: bool = False, temperature: float | None = None,
              protocol: Protocol = Protocol.V2,
              cache_user: bool = False) -> Body:
        """The request body, separated out so a dry run can price the exact
        bytes that would be sent rather than an approximation of them.

        The two protocols differ only in Haiku's thinking budget: half the
        ceiling under v1, the ceiling less `ANSWER_RESERVE` under v2. Claude
        with thinking takes no sampling parameter in either.

        `cache_user` adds a second breakpoint, at the end of the user
        message, so the whole prompt is the cached prefix. It is for a
        caller that sends one prompt many times, as a variance cell does:
        the first call writes the cache at `CACHE_WRITE` and each resend
        within the 5-minute lifetime reads it at the model's `cache_read`.
        On a prompt sent once the write premium buys nothing, so it is off
        by default. Off, the body is byte for byte what it was before the
        flag existed, so every stored response still replays."""
        content: str | list[dict[str, Any]] = user
        if cache_user:
            content = [{"type": "text", "text": user,
                        "cache_control": {"type": "ephemeral"}}]
        body: Body = {
            "model": model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": content}],
        }
        if thinking:
            # Synthesis is the call class where reasoning earns its price - an
            # error there propagates to every page the template touches. Which
            # form to ask for is decided by the model, see ReasoningControl.
            control = spec(model).reasoning
            if control is ReasoningControl.ADAPTIVE:
                body["thinking"] = {"type": "adaptive"}
            elif control is ReasoningControl.BUDGET:
                # `budget_tokens` must leave room for the answer. 1024 is the
                # documented floor.
                budget = (max_tokens // 2 if protocol is Protocol.V1
                          else max_tokens - ANSWER_RESERVE)
                body["thinking"] = {"type": "enabled",
                                    "budget_tokens": max(1024, budget)}
            else:
                raise Refused("%s has no Anthropic thinking control (%s). "
                              "Nothing was sent." % (model, control))
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

    def build_chat(self, model: str, system: str, user: str, max_tokens: int,
                   thinking: bool = False,
                   temperature: float | None = None,
                   protocol: Protocol = Protocol.V2,
                   effort: str | None = None) -> Body:
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
        - **Reasoning is an effort level or a switch, not a token budget.**
          Under v2 it is `reasoning: {"effort": ...}` at the value that
          reaches the lab's default level, or `{"enabled": true}` where no
          levels are listed, and a cell may name another listed effort. v1
          sent a top-level `reasoning_effort: "medium"` to the models in
          `V1_EFFORT`.
        - **Temperature is not refused alongside thinking.** That refusal in
          `build` exists because the Anthropic API returns a 400 for it. It
          is a fact about one vendor, not a house rule, and asserting it here
          would be inventing a constraint the endpoint does not have.
        """
        body: Body = {
            "model": model,
            # `max_tokens`, not `max_completion_tokens`: the newer name is
            # for OpenAI's own models and this client only ever points at
            # OpenRouter, which takes the original.
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        s = spec(model)
        if protocol is Protocol.V1:
            if effort is not None:
                raise Refused("protocol v1 has no effort setting. Nothing "
                              "was sent.")
            if thinking and model in V1_EFFORT:
                body["reasoning_effort"] = "medium"
            if temperature is not None:
                body["temperature"] = temperature
            return body

        if effort is not None and (not thinking
                                   or s.reasoning is not ReasoningControl.EFFORT
                                   or effort not in s.efforts):
            raise Refused("%s does not take reasoning effort %r (catalogue "
                          "lists %s). Nothing was sent."
                          % (model, effort, ", ".join(s.efforts) or "none"))
        if thinking and s.reasoning is ReasoningControl.EFFORT:
            body["reasoning"] = {"effort": effort or s.effort}
        elif thinking and s.reasoning is ReasoningControl.SWITCH:
            body["reasoning"] = {"enabled": True}
        # Sent explicitly because on OpenRouter "default" is whatever the
        # serving host defaults to, and hosts differ (finding F6).
        t = temperature if temperature is not None else s.temperature
        if t is not None:
            body["temperature"] = t
        if s.top_p is not None:
            body["top_p"] = s.top_p
        # `require_parameters` drops hosts that do not list a parameter
        # above; `quantizations` drops hosts below the lab's own precision
        # (finding F4); `ignore` drops hosts measured accepting the effort
        # parameter and then not acting on it, which `require_parameters`
        # cannot see.
        route: dict[str, Any] = {"require_parameters": True}
        if s.quantizations is not None:
            route["quantizations"] = list(s.quantizations)
        if s.ignore:
            route["ignore"] = list(s.ignore)
        body["provider"] = route
        return body

    def request(self, model: str, system: str, user: str, max_tokens: int,
                thinking: bool = False, temperature: float | None = None,
                protocol: Protocol = Protocol.V2,
                effort: str | None = None,
                cache_user: bool = False) -> Body:
        """The body `message` sends for these arguments, ceiling applied.

        Public so a caller can record the settings a cell runs under from
        the same bytes the calls carry, rather than restating them.
        `cache_user` has no OpenRouter form: see `build_chat`.
        """
        max_tokens = ceiling_for(model, max_tokens, protocol)
        if provider_for(model) == OPENROUTER:
            return self.build_chat(model, system, user, max_tokens, thinking,
                                   temperature, protocol, effort)
        if effort is not None:
            # Which effort parameter Opus 5 and Sonnet 5 take is unverified,
            # and Haiku 4.5's only control is the thinking budget.
            raise Refused("effort settings are not wired for Anthropic "
                          "models. Nothing was sent.")
        return self.build(model, system, user, max_tokens, thinking,
                          temperature, protocol, cache_user)

    # --------------------------------------------------------------- call
    def message(self, model: str, system: str, user: str, max_tokens: int,
                call_class: str, thinking: bool = False, tag: str = "",
                temperature: float | None = None, draw: int = 0,
                protocol: Protocol = Protocol.V2,
                effort: str | None = None,
                cache_user: bool = False) -> Completion:
        """One model call, on whichever provider owns `model`.

        `Completion.usage` is in Anthropic field names whatever the provider
        was - see `_usage_from_chat` for why the translation happens here
        rather than at every reader.

        On Anthropic, `system` carries the cache breakpoint. Section 6 lever 3:
        synthesis resends a large stable prefix against a small variable
        suffix, so the breakpoint goes after the prefix and resends bill at
        0.1x. The design note says to verify with `cache_read_input_tokens`
        rather than by reading the code, so the ledger records that field and
        the harness prints it. Measured 2026-09-23 over 67 calls, that lever
        is worth about 2% of total spend on this workload, because the prefix
        it caches is 6.6% of the request. `cache_user` moves the breakpoint
        to the end of the user message, for a caller that resends the whole
        request (see `build`).
        """
        prov = provider_for(model)
        body = self.request(model, system, user, max_tokens, thinking,
                            temperature, protocol, effort, cache_user)
        # Resolved once, in `request`, so the ceiling that goes on the wire
        # is the same one the budget is checked against, the span records,
        # and `truncated` compares output against. Computing it at any one of
        # those sites and not the others is how a run gets pre-authorized for
        # a third of what it can actually spend.
        max_tokens = int(body["max_tokens"])
        sent = settings_sent(body, protocol)
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
            if sent["temperature"] is not None:
                span.set_attribute("gen_ai.request.temperature",
                                   float(sent["temperature"]))
            if sent["top_p"] is not None:
                span.set_attribute("gen_ai.request.top_p",
                                   float(sent["top_p"]))
            span.set_attribute("permits.protocol", str(protocol))
            if sent["reasoning"]:
                span.set_attribute("permits.reasoning", sent["reasoning"])
            # Project dimensions, so a span joins to a ledger row.
            span.set_attribute("permits.call_class", call_class)
            span.set_attribute("permits.draw", draw)
            if tag:
                span.set_attribute("permits.tag", tag)

            hit = self.cached(key)
            if (hit is not None and protocol is not Protocol.V1
                    and cut_by_host(hit.get("stop_reason"),
                                    Usage.from_dict(hit["usage"]),
                                    max_tokens)):
                # A host-closed stream cached before `cut_by_host` existed is
                # not an answer to replay; the draw is bought again. v1
                # replays are left exactly as they were published.
                hit = None
            span.set_attribute("permits.cache_hit", hit is not None)
            if hit is not None:
                usage = Usage.from_dict(hit["usage"])
                return Completion(
                    text=hit["text"], usage=usage, model=model, provider=prov,
                    cached=True, usd=0.0, stop_reason=hit.get("stop_reason"),
                    truncated=truncated(hit.get("stop_reason"), usage,
                                        max_tokens),
                    host=hit.get("host"), response_id=hit.get("response_id"))

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

            attempt = 1
            while True:
                clock = _Clock(wall_limit(max_tokens))
                try:
                    reply = (self._send_chat(body, clock)
                             if prov == OPENROUTER
                             else self._send_messages(body, clock))
                    break
                except TRANSPORT_ERRORS as e:
                    status = getattr(e, "status_code", None)
                    # A failed call was invisible until 2026-09-22: the old
                    # client raised before it reached the ledger, so the
                    # error rate was structurally unobservable and "67 calls"
                    # meant "67 calls that happened to work". Every failed
                    # attempt is a row, billed at 0.
                    billed = getattr(e, "billed", None)
                    self._log_failure(model, call_class, tag, draw, clock,
                                      type(e).__name__, status, sent,
                                      usd=billed or 0.0,
                                      output_tokens=getattr(
                                          e, "output_tokens", None),
                                      host=getattr(e, "host", None))
                    if billed is not None:
                        # The stream reached its usage block, so the charge
                        # is known.
                        self.budget.record(billed)
                    elif clock.first is not None:
                        # Tokens were generated before the call died and the
                        # host may bill for them; nothing says how many. The
                        # ceiling is a guarantee, so it is charged the worst
                        # case.
                        self.budget.record(estimate(model, est_in,
                                                    max_tokens))
                    span.record_exception(e)
                    detail = "%s%s: %s" % (
                        type(e).__name__,
                        "" if status is None else " %s" % status,
                        str(e)[:400])
                    transient = is_transient(e)
                    if transient and attempt < ATTEMPTS:
                        attempt += 1
                        self.budget.check(model, est_in, max_tokens)
                        continue
                    span.set_attribute("permits.attempts", attempt)
                    span.set_attribute("error.type", type(e).__name__)
                    if status is not None:
                        span.set_attribute(
                            "gen_ai.response.status_code", int(status))
                    span.set_status(Status(StatusCode.ERROR, detail[:200]))
                    if transient:
                        raise TransientError(
                            "%s (after %d attempts)" % (detail, attempt)
                        ) from e
                    raise FatalError(detail) from e
            elapsed = clock.elapsed()
            span.set_attribute("permits.attempts", attempt)
            text, raw_usage, stop_reason = (reply.text, reply.usage,
                                            reply.stop_reason)
            billed, host = reply.billed, reply.host
            usage = Usage.from_dict(raw_usage)

            # What the provider says it charged beats what the local table
            # thinks it costs. Anthropic reports no such figure, so that path
            # prices from the registry exactly as it always has.
            usd = cost(model, usage) if billed is None else billed

            span.set_attribute("gen_ai.response.model", reply.model or model)
            if host:
                span.set_attribute("permits.host", host)
            if usage.reasoning_tokens is not None:
                span.set_attribute("permits.usage.reasoning_tokens",
                                   usage.reasoning_tokens)
            span.set_attribute("gen_ai.response.finish_reasons",
                               [stop_reason or "unknown"])
            span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens",
                               usage.output_tokens)
            span.set_attribute("permits.usd", usd)
            span.set_attribute("permits.seconds", elapsed)
            if clock.ttft() is not None:
                span.set_attribute("permits.ttft_s", clock.ttft() or 0.0)

            self.budget.record(usd)
            self.ledger.write(LedgerRow(
                at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                call_class=call_class, tag=tag, model=model, provider=prov,
                draw=draw, ok=True, usd_reported=billed is not None,
                usd=round(usd, 6), seconds=elapsed,
                stop_reason=stop_reason,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_input_tokens=usage.cache_read_input_tokens,
                cache_creation_input_tokens=usage.cache_creation_input_tokens,
                ttft_s=clock.ttft(), host=host,
                reasoning_tokens=usage.reasoning_tokens,
                response_id=clock.response_id, **sent))
            # The raw usage block, not the typed view, so fields `Usage`
            # does not read stay available to a later reader.
            self._store(key, {"text": text, "usage": raw_usage,
                              "stop_reason": stop_reason, "host": host,
                              "response_id": clock.response_id})
            return Completion(
                text=text, usage=usage, model=model, provider=prov,
                cached=False, usd=usd, stop_reason=stop_reason,
                truncated=truncated(stop_reason, usage, max_tokens),
                host=host, response_id=clock.response_id)

    def _send_messages(self, body: Body, clock: _Clock) -> "_Reply":
        """Anthropic transport.

        Always streamed. Streaming is a method here, not a flag on the
        request, so it cannot change the request's identity. Until 2026-09-26
        calls at or under 8,192 tokens used `create`, where the read timeout
        spans the whole generation and an SDK retry re-sends a request the
        host may already have generated and billed.

        `billed` is None because Anthropic does not report a charge on the
        response; that path prices from the registry, as it always has.
        """
        with self.sdk().messages.stream(**body) as stream:
            for event in stream:
                clock.check()
                if event.type == "message_start":
                    clock.response_id = getattr(
                        getattr(event, "message", None), "id", None)
                elif event.type == "content_block_delta":
                    clock.token()
            msg = stream.get_final_message()
        clock.response_id = getattr(msg, "id", None) or clock.response_id
        usage = msg.usage.model_dump(mode="json")
        text = "".join(b.text for b in msg.content
                       if isinstance(b, anthropic.types.TextBlock))
        return _Reply(text, usage, msg.stop_reason, msg.model, None,
                      "anthropic")

    def _send_chat(self, body: Body, clock: _Clock | None = None) -> "_Reply":
        """OpenRouter transport, streamed.

        `stream` and `stream_options` are arguments to the SDK call and never
        keys in `body`, so they stay out of the cache key. `include_usage`
        makes the last chunk carry the usage block and OpenRouter's reported
        cost. Reasoning deltas count toward the first token and are not kept:
        the text is `content` alone, as it was before this path streamed.
        `reasoning` and `provider` are OpenRouter fields the OpenAI SDK has
        no parameter for, so they go in `extra_body`; the serving host comes
        back as `provider` on each chunk.

        Four ways a stream can end without an answer, each a host failure
        rather than an empty reply. With no choices at all, the caller would
        read empty text as an extractor that produced nothing. With an
        `error` finish, OpenRouter is reporting an upstream failure after a
        200. With no usage block, what the call cost is unknown, and a
        zero-token row would price a paid call at nothing. With no finish
        reason short of the cap, the host closed the stream before the model
        finished (`cut_by_host`); that one was billed, so the error carries
        the charge.
        """
        if clock is None:
            clock = _Clock(wall_limit(int(body.get("max_tokens") or 0)))
        parts: list[str] = []
        finish: str | None = None
        resp_model = str(body["model"])
        raw_usage: Any = None
        saw_choice = False
        last: Any = None
        host: str | None = None
        args = {k: v for k, v in body.items() if k not in EXTRA_BODY}
        extra = {k: v for k, v in body.items() if k in EXTRA_BODY}
        if extra:
            args["extra_body"] = extra
        stream = self.oai().chat.completions.create(
            **args, stream=True, stream_options={"include_usage": True})
        with stream:
            for chunk in stream:
                clock.check()
                last = chunk
                clock.response_id = (clock.response_id
                                     or getattr(chunk, "id", None))
                resp_model = chunk.model or resp_model
                host = getattr(chunk, "provider", None) or host
                if chunk.usage is not None:
                    raw_usage = chunk.usage
                for choice in chunk.choices:
                    saw_choice = True
                    delta = choice.delta
                    if delta.content:
                        parts.append(delta.content)
                        clock.token()
                    elif (getattr(delta, "reasoning", None)
                          or getattr(delta, "reasoning_content", None)):
                        clock.token()
                    if choice.finish_reason:
                        finish = choice.finish_reason
        model = body.get("model")
        if not saw_choice:
            raise _HostError("OpenRouter returned no choices for %r: %s"
                             % (model, _error_detail(last)))
        if finish == "error":
            raise _HostError("OpenRouter stream for %r ended in an error: %s"
                             % (model, _error_detail(last)))
        if raw_usage is None:
            raise _HostError("OpenRouter stream for %r ended without its "
                             "usage block" % (model,))
        usage, billed = _usage_from_chat(raw_usage)
        stop = FINISH_REASONS.get(finish, finish) if finish else finish
        out = int(usage.get("output_tokens") or 0)
        if cut_by_host(stop, Usage(output_tokens=out),
                       int(body.get("max_tokens") or 0)):
            raise _HostError("stream for %r closed with no finish reason "
                             "after %d output tokens" % (model, out),
                             billed=billed, output_tokens=out, host=host)
        return _Reply("".join(parts), usage, stop, resp_model, billed, host)

    def _log_failure(self, model: str, call_class: str, tag: str, draw: int,
                     clock: _Clock, error_type: str,
                     status: int | None, sent: dict[str, Any],
                     usd: float = 0.0, output_tokens: int | None = None,
                     host: str | None = None) -> None:
        """A ledger row for a call that reached the API and failed.

        `usd` is zero because a rejected request is not billed, but the row
        exists so that the denominator of any success rate computed from this
        ledger is the number of calls *made*. Rows written before 2026-09-22
        have no `ok` field and are read as successes, which they are: the old
        client could not write anything else. A row with `ttft_s` failed
        after tokens arrived and may have been billed for them. A stream the
        host closed after sending its usage block reports its charge, and
        `usd`, `output_tokens` and `host` then carry it.
        """
        self.ledger.write(LedgerRow(
            at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            call_class=call_class, tag=tag, model=model,
            provider=provider_for(model), draw=draw, ok=False,
            error_type=error_type, status_code=status,
            usd=round(usd, 6), seconds=clock.elapsed(), stop_reason=None,
            output_tokens=output_tokens or 0, host=host,
            ttft_s=clock.ttft(), response_id=clock.response_id, **sent))
