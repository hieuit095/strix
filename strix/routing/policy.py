from __future__ import annotations

from dataclasses import dataclass

from strix.routing.types import Envelope, Tier, max_tier


HIGH_IMPACT = frozenset(
    {
        "rce",
        "ssrf",
        "authentication_jwt",
        "insecure_deserialization",
        "broken_function_level_authorization",
        "http_request_smuggling",
    }
)
AMBIGUOUS = frozenset(
    {"business_logic", "race_conditions", "idor", "mass_assignment", "semantic_confusion"}
)
_SEVERE = frozenset({"high", "critical"})


def normalized_skill_labels(skills: tuple[str, ...]) -> set[str]:
    """Match both canonical skill labels and their namespaced scan declarations."""
    return {skill.rsplit("/", maxsplit=1)[-1].lower() for skill in skills}


@dataclass(frozen=True)
class RuleResult:
    floor: Tier
    ceiling: Tier
    ask_jev: bool


def apply_hard_rules(env: Envelope) -> RuleResult:
    """Deterministic bounds on the tier; ``ask_jev`` marks a genuinely open choice."""
    skills = normalized_skill_labels(env.skills)
    floor, ceiling, ask = Tier.WORKER, Tier.WORKER, False
    if skills & AMBIGUOUS:
        ceiling, ask = max_tier(ceiling, Tier.SPECIALIST), True
    if skills & HIGH_IMPACT:
        floor, ceiling, ask = max_tier(floor, Tier.SPECIALIST), Tier.EXPERT, True
    if (env.severity or "").lower() in _SEVERE:
        floor = max_tier(floor, Tier.SPECIALIST)
        ceiling = max_tier(ceiling, Tier.SPECIALIST)
        ask = True
    return RuleResult(floor, ceiling, ask)
