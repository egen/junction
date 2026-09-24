"""
models.py — Model tier defaults for the agent graph.

The graph assigns every node one of five tiers. Reasoning-heavy tiers (planner,
builder) default to the stronger model; read-only tiers (validator, observer,
curator) default to the cheaper one. Every tier can be overridden from the CLI
(``--model validator=claude-haiku-4-5``), the SDK, or a ``models:`` block in
discovery answers.
"""

from __future__ import annotations

MODEL_TIERS = ["planner", "builder", "validator", "observer", "curator"]

STRONG_MODEL = "claude-opus-5"
EFFICIENT_MODEL = "claude-sonnet-5"

DEFAULT_MODELS: dict[str, str] = {
    "planner": STRONG_MODEL,
    "builder": STRONG_MODEL,
    "validator": EFFICIENT_MODEL,
    "observer": EFFICIENT_MODEL,
    "curator": EFFICIENT_MODEL,
}

# Claude Code subagents accept family aliases that always track the latest model.
_CLAUDE_CODE_ALIASES = ("opus", "sonnet", "haiku", "inherit")


def resolve_models(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Return the tier → model map with overrides applied. Unknown tiers raise."""
    models = dict(DEFAULT_MODELS)
    for tier, model in (overrides or {}).items():
        if tier not in MODEL_TIERS:
            raise ValueError(f"Unknown model tier {tier!r}. Valid tiers: {', '.join(MODEL_TIERS)}")
        if not model or not str(model).strip():
            raise ValueError(f"Model for tier {tier!r} must be a non-empty string")
        models[tier] = str(model).strip()
    return models


def parse_model_overrides(pairs: tuple[str, ...] | list[str]) -> dict[str, str]:
    """Parse ``tier=model`` strings from the CLI into a dict."""
    overrides: dict[str, str] = {}
    for pair in pairs:
        tier, sep, model = pair.partition("=")
        if not sep:
            raise ValueError(f"Invalid --model value {pair!r}; expected TIER=MODEL")
        overrides[tier.strip()] = model.strip()
    resolve_models(overrides)
    return overrides


def claude_code_alias(model: str) -> str:
    """Map a model id to the alias a Claude Code subagent ``model:`` field accepts."""
    lowered = model.lower()
    if lowered in _CLAUDE_CODE_ALIASES:
        return lowered
    for family in ("opus", "sonnet", "haiku"):
        if family in lowered:
            return family
    return "inherit"
