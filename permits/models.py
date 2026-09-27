"""The model registry: one record per model this project has called.

Every fact the harness acts on about a model lives here: which provider
serves it, what it costs, how it is asked to reason, what its files are
called, when it was released. Before 2026-09-26 those facts were spread over
seven places in `permits/infer.py` (two price tables, a free set, a reasoning
set, an adaptive-thinking set, a slash test for the provider and a string
rule for the short name). A model added to one and not the others got a
different experiment without anyone deciding it should, which is how two
models that reason came to be run as models that do not (finding F2 in
`docs/evidence/2026-09-26-model-comparison-fairness-audit.md`).

Each entry holds the settings of **protocol v2**, the request policy in step 3
of the audit: output cap, reasoning setting, sampling and allowed host
precisions, each with its source. Protocol v1, the request shape every cell
before 2026-09-26 ran under, is frozen in `permits/infer.py` so those cached
responses still replay.

The registry is also historical: a model stays here after it leaves the
roster, because the ledger, the variance cells and the synthesis artifacts
on disk are all named by ids that have to keep resolving.
"""
from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class Provider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENROUTER = "openrouter"


class Tier(StrEnum):
    """Price tier, as assigned in the 2026-09-26 audit's roster table.

    `FREE` is a smoke-test endpoint, not a tier: OpenRouter does not promise
    which upstream, quantization or context window serves a free request, so
    draws from one are not samples of one condition. It proves the wire works
    and is never a measurement cell.
    """
    TOP = "top"
    MID = "mid"
    CHEAP = "cheap"
    FREE = "free"


class Protocol(StrEnum):
    """The request policy a call is made under.

    The cache key is the request body's hash, so a policy change is a new
    set of requests. Versioning the policy keeps the old one replayable
    instead of silently re-buying or overwriting its cells.

    - `V1`: the request shape every cell before 2026-09-26 ran under, frozen.
      12,000 to 16,000-token answer budgets, 32,000 tokens of headroom for
      five OpenRouter models sent `reasoning_effort: "medium"`, no sampling
      or routing parameters.
    - `V2`: step 3 of `docs/evidence/2026-09-26-model-comparison-fairness-audit.md`.
      One output cap for every model, reasoning at the vendor default,
      sampling from the model card, host precision filtered.
    """
    V1 = "v1"
    V2 = "v2"


class ReasoningControl(StrEnum):
    """What the harness sends when a call asks for reasoning.

    Vendors expose incomparable controls, so this is the control's *kind*,
    and `permits/infer.py` turns it into request fields.

    - `ADAPTIVE`: Anthropic `thinking: {"type": "adaptive"}`. Claude 4.6 and
      later take this and reject `budget_tokens` with a 400.
    - `BUDGET`: Anthropic `thinking: {"type": "enabled", "budget_tokens": n}`.
      Earlier Claude models take this and reject `adaptive` with a 400. Found
      the hard way: the first conformance run died on "adaptive thinking is
      not supported on this model" against Haiku 4.5.
    - `EFFORT`: OpenRouter `reasoning: {"effort": ...}`, at the catalogue's
      default effort unless a cell names another.
    - `SWITCH`: OpenRouter `reasoning: {"enabled": true}`, for a model whose
      catalogue entry lists no effort levels.
    - `NONE`: nothing is sent. OpenRouter silently ignores a reasoning
      parameter on a model that cannot reason, and "silently ignores" is how
      a run gets written up as controlled when it was not, so the parameter
      is only sent where the entry says so.
    """
    ADAPTIVE = "adaptive"
    BUDGET = "budget_tokens"
    EFFORT = "effort"
    SWITCH = "switch"
    NONE = "none"


@dataclass(frozen=True)
class ModelSpec:
    """One model, as the harness calls it.

    `price` is what `Budget` authorizes against, in USD per million tokens,
    (input, output). For Anthropic it is also what the ledger bills, because
    the Messages API reports no charge. For OpenRouter it is a ceiling: the
    ledger records the provider's reported `usage.cost`, and this rate only
    has to bound it from above. `list_price` is the published rate the
    ceiling was set against, kept so a refresh that drops a ceiling back to
    list is caught (`tests/test_providers.py`).

    `supports_reasoning` is what the catalogue says the model can do.
    `reasoning` is how protocol v2 asks it to, `effort` the catalogue's
    default effort and `efforts` every effort the catalogue lists.
    `tests/test_models.py` fails if a model that reasons is sent nothing.

    `max_output` is the catalogue's `max_completion_tokens`; the cap sent is
    the lower of it and `OUTPUT_CAP`. `temperature` and `top_p` are the model
    card's recommendation, else the catalogue's `default_parameters`, else
    the API default of 1.0. For Claude, temperature is the 1.0 that thinking
    fixes and is not sent.

    `quantizations` are the host precisions OpenRouter may route to: the
    lowest precision the lab itself released, and anything higher. None means
    no filter, for a model with a single, lab-run host.

    `released` is the catalogue's `created` date from
    `openrouter.ai/api/v1/models`, read 2026-09-25, for Claude too, so every
    model's age is measured by one source.
    """
    id: str
    provider: Provider
    lab: str
    tier: Tier
    # Filename- and column-safe. Synthesis artifacts and variance labels are
    # named by this, so it is written out rather than derived: a rule that
    # changes renames files already on disk and orphans them.
    short: str
    released: date
    price: tuple[float, float]
    list_price: tuple[float, float]
    reasoning: ReasoningControl = ReasoningControl.NONE
    supports_reasoning: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_output: int = 0
    effort: str | None = None
    efforts: tuple[str, ...] = ()
    quantizations: tuple[str, ...] | None = None


# Protocol v2's output cap: the whole allowance, reasoning included, for every
# model. Every catalogue `max_completion_tokens` in the registry is at or above
# it, so it is the same number for every vendor (finding F1).
OUTPUT_CAP = 64000


def output_cap(spec: "ModelSpec") -> int:
    return min(spec.max_output, OUTPUT_CAP)


PRICES_AS_OF = "2026-06-24 (DESIGN.md section 6)"
OPENROUTER_PRICES_AS_OF = ("2026-09-23 (openrouter.ai/api/v1/models); reasoning output "
                           "rates reconciled to invoice 2026-09-25")

# Protocol v1 only. Room to think, added on top of the answer budget for the
# models v1 sent `reasoning_effort` to, rather than taken out of it. OpenRouter counts reasoning tokens and output tokens
# against the same `max_tokens`, so passing one ceiling to every model does
# not give every model the same experiment: a model that thinks gets whatever
# is left after thinking, and a model that does not gets all of it. Measured
# 2026-09-24 at a 16,000 ceiling, glm-5.2 spent all 16,000 tokens reasoning on
# both clarkco draws and emitted no extractor either time.
#
# 32,000 is twice the level observed to bind. It is a cap and bills only what
# is drawn against it. Claude's thinking still came out of its own ceiling,
# which is finding F1; protocol v2 replaces both with `OUTPUT_CAP`.
REASONING_HEADROOM = 32000

ANT, OR = Provider.ANTHROPIC, Provider.OPENROUTER

# Host precisions, per the lowest precision each lab released on Hugging Face
# (`data/audit/2026-09-26-huggingface-configs.json`), checked against
# OpenRouter's endpoint list (`data/audit/2026-09-26-openrouter-endpoints.json`).
# Hosts that report `unknown` are excluded.
FROM_FP4 = ("fp4", "fp8", "fp16", "bf16")
FROM_INT4 = ("int4", "int8", "fp8", "fp16", "bf16")
FROM_FP8 = ("fp8", "fp16", "bf16")

# Anthropic rates are quoted from DESIGN.md section 6, "Anthropic
# first-party, as of 2026-06-24 - re-verify before quoting". They are billed
# from here, so a price that moved makes every dollar figure wrong while every
# token figure stays right. Report tokens when in doubt.
#
# OpenRouter rates are a CEILING TABLE, reconciled 2026-09-25 against all 132
# paid OpenRouter calls on disk and 2026-09-26 against the newer two, pricing
# the full prompt (`input_tokens + cache_read_input_tokens`, since a cached
# read is discounted but still billed). They diverge from list for two
# separate reasons:
#
#   Under-reported reasoning. glm-5.2 billed 2.09x its list projection on 4 of
#   4 calls, deepseek-v4-pro 1.26x on 3 of 3, glm-5.3-flash 2.40x mean and
#   3.38x max on 9 of 9, because `completion_tokens` does not include every
#   reasoning token those models are charged for. kimi-k2-thinking reconciles
#   at exactly 1.00, so this is a per-model reporting difference and not a
#   rule about reasoning models.
#
#   Routing variance. One OpenRouter model id is not one upstream, and the
#   upstreams do not agree on price. gpt-oss-120b reconciles at a mean of 0.51
#   but a max of 1.88, qwen3-coder at 0.57 mean and 1.33 max.
#   deepseek-v4-flash reconciles at 1.00 on 12 of 15 calls and 4.7-4.8x on the
#   other 3, the slow ones, which fits a different upstream at a different
#   price. The host is not logged (finding F4), so that is not confirmed.
#
# Ceilings therefore carry margin over the worst ratio observed rather than
# tracking it, since the next call can be served by an upstream none of these
# calls used. The two newest entries are about 1.5x the rate that bounds
# their worst call.
_SPECS = [
    # Claude: `max_output` from OpenRouter's `anthropic/*` catalogue entries.
    # Thinking fixes temperature at 1.0 and the API rejects anything else.
    ModelSpec("claude-opus-5", ANT, "anthropic", Tier.TOP, "opus-5",
              date(2026, 7, 24), (5.0, 25.0), (5.0, 25.0),
              ReasoningControl.ADAPTIVE, supports_reasoning=True,
              temperature=1.0, max_output=128000),
    ModelSpec("claude-sonnet-5", ANT, "anthropic", Tier.MID, "sonnet-5",
              date(2026, 6, 30), (2.0, 10.0), (2.0, 10.0),
              ReasoningControl.ADAPTIVE, supports_reasoning=True,
              temperature=1.0, max_output=128000),
    ModelSpec("claude-haiku-4-5-20251001", ANT, "anthropic", Tier.CHEAP, "haiku-4-5",
              date(2025, 10, 15), (1.0, 5.0), (1.0, 5.0),
              ReasoningControl.BUDGET, supports_reasoning=True,
              temperature=1.0, max_output=64000),
    # The hosted version of the open-weight Qwen3.5-35B-A3B, per that model's
    # card, which Alibaba also released as fine-grained FP8 (128x128 blocks).
    # Sampling is the card's "thinking mode for precise coding tasks". Reasoning
    # is off unless enabled and the catalogue lists no effort levels; protocol
    # v1 sent nothing (finding F2). Its one host is Alibaba, which reports
    # `unknown`, so `unknown` is admitted here and nowhere else; a third-party
    # host below fp8 would still be excluded.
    ModelSpec("qwen/qwen3.5-flash-02-23", OR, "qwen", Tier.CHEAP, "qwen3.5-flash-02-23",
              date(2026, 2, 25), (0.065, 0.260), (0.065, 0.260),
              ReasoningControl.SWITCH, supports_reasoning=True,
              temperature=0.6, top_p=0.95, max_output=65536,
              quantizations=(*FROM_FP8, "unknown")),
    # Released in MXFP4. Always reasons, default effort medium; protocol v1
    # sent nothing, so it ran at each host's default (finding F2).
    ModelSpec("openai/gpt-oss-120b", OR, "openai", Tier.CHEAP, "gpt-oss-120b",
              date(2025, 8, 5), (0.300, 1.200), (0.150, 0.600),
              ReasoningControl.EFFORT, supports_reasoning=True,
              temperature=1.0, top_p=1.0, max_output=65536,
              effort="medium", efforts=("low", "medium", "high"),
              quantizations=FROM_FP4),
    # OpenRouter's asynchronous variant, 80% off rather than the 50% Anthropic's
    # Batch API gives. The suffix is part of the id, which is why `--cells`
    # splits on the first and last colon rather than on every one, and why the
    # short name spells it with a hyphen: on NTFS a colon in a filename writes
    # an alternate data stream of a file named by the part before it.
    ModelSpec("openai/gpt-oss-120b:batch", OR, "openai", Tier.CHEAP, "gpt-oss-120b-batch",
              date(2025, 8, 5), (0.0296, 0.136), (0.0296, 0.136),
              ReasoningControl.EFFORT, supports_reasoning=True,
              temperature=1.0, top_p=1.0, max_output=117964,
              effort="medium", efforts=("low", "medium", "high"),
              quantizations=FROM_FP4),
    # Does not reason. The model card recommends 0.7 / 0.8, with top_k 20 and
    # repetition_penalty 1.05, which the policy does not send. Qwen released
    # bf16 and an fp8 checkpoint.
    ModelSpec("qwen/qwen3-coder", OR, "qwen", Tier.CHEAP, "qwen3-coder",
              date(2025, 7, 23), (0.450, 1.500), (0.300, 1.000),
              temperature=0.7, top_p=0.8, max_output=65536,
              quantizations=FROM_FP8),
    # Always reasons and lists no effort levels. Released in INT4. The card
    # recommends temperature 1.0.
    ModelSpec("moonshotai/kimi-k2-thinking", OR, "moonshotai", Tier.CHEAP, "kimi-k2-thinking",
              date(2025, 11, 6), (0.600, 2.500), (0.600, 2.500),
              ReasoningControl.SWITCH, supports_reasoning=True,
              temperature=1.0, top_p=1.0, max_output=98304,
              quantizations=FROM_INT4),
    # Zhipu released bf16 and an fp8 checkpoint. Sampling from the catalogue's
    # `default_parameters`, which is also the card's reasoning setting.
    ModelSpec("z-ai/glm-5.2", OR, "z-ai", Tier.MID, "glm-5.2",
              date(2026, 6, 16), (0.650, 7.500), (0.650, 2.042),
              ReasoningControl.EFFORT, supports_reasoning=True,
              temperature=1.0, top_p=0.95, max_output=131072,
              effort="high", efforts=("high", "xhigh"),
              quantizations=FROM_FP8),
    ModelSpec("deepseek/deepseek-v4-pro", OR, "deepseek", Tier.MID, "deepseek-v4-pro",
              date(2026, 4, 24), (0.940, 5.000), (0.940, 1.879),
              ReasoningControl.EFFORT, supports_reasoning=True,
              temperature=1.0, top_p=1.0, max_output=384000,
              effort="high", efforts=("high", "xhigh"),
              quantizations=FROM_FP8),
    # Current-generation cheap tier, added 2026-09-25. Reasoning was probed,
    # not assumed from the name: both return a populated `reasoning` field and
    # non-zero `reasoning_tokens` when sent no reasoning parameter. Both were
    # released in fp8.
    ModelSpec("z-ai/glm-5.3-flash", OR, "z-ai", Tier.CHEAP, "glm-5.3-flash",
              date(2026, 8, 26), (0.070, 2.300), (0.045, 0.140),
              ReasoningControl.EFFORT, supports_reasoning=True,
              temperature=1.0, top_p=0.95, max_output=128000,
              effort="max", efforts=("low", "high", "max"),
              quantizations=FROM_FP8),
    ModelSpec("deepseek/deepseek-v4-flash", OR, "deepseek", Tier.CHEAP, "deepseek-v4-flash",
              date(2026, 4, 24), (0.075, 0.750), (0.047, 0.095),
              ReasoningControl.EFFORT, supports_reasoning=True,
              temperature=1.0, top_p=1.0, max_output=384000,
              effort="high", efforts=("high", "xhigh"),
              quantizations=FROM_FP8),
    # For verifying the path end to end before any money is added to the
    # account. See `Tier.FREE`. Never a measurement, so no reasoning setting.
    ModelSpec("nvidia/nemotron-3-ultra-550b-a55b:free", OR, "nvidia", Tier.FREE,
              "nemotron-3-ultra-550b-a55b-free",
              date(2026, 6, 4), (0.0, 0.0), (0.0, 0.0),
              supports_reasoning=True,
              temperature=1.0, top_p=0.95, max_output=65536),
]

REGISTRY: dict[str, ModelSpec] = {s.id: s for s in _SPECS}


class UnknownModel(LookupError):
    """A model id with no registry entry. Nothing may be sent for it: an
    unpriced call cannot be checked against the budget or logged against the
    section 6 tripwire."""


def get(model: str) -> ModelSpec:
    try:
        return REGISTRY[model]
    except KeyError:
        raise UnknownModel(
            "no registry entry for %r. Add a ModelSpec to permits/models.py, "
            "with a sourced price, before spending." % (model,)) from None


def measured() -> list[ModelSpec]:
    """Every model that may appear in a measurement cell."""
    return [s for s in REGISTRY.values() if s.tier is not Tier.FREE]
