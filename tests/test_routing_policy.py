from __future__ import annotations

import pytest

from strix.routing.policy import apply_hard_rules
from strix.routing.types import Envelope, Tier


def env(*skills: str, severity: str | None = None) -> Envelope:
    return Envelope(task="t", skills=tuple(skills), severity=severity)


@pytest.mark.parametrize("skills", [(), ("xss",), ("sql_injection", "csrf")])
def test_plain_skills_go_to_worker_without_asking_jev(skills: tuple[str, ...]) -> None:
    r = apply_hard_rules(env(*skills))
    assert (r.floor, r.ceiling, r.ask_jev) == (Tier.WORKER, Tier.WORKER, False)


def test_ambiguous_skill_asks_jev_worker_or_specialist() -> None:
    r = apply_hard_rules(env("business_logic"))
    assert (r.floor, r.ceiling, r.ask_jev) == (Tier.WORKER, Tier.SPECIALIST, True)


def test_high_impact_skill_cannot_be_downgraded_below_specialist() -> None:
    r = apply_hard_rules(env("rce"))
    assert (r.floor, r.ceiling, r.ask_jev) == (Tier.SPECIALIST, Tier.EXPERT, True)


def test_mixed_takes_the_highest_demand() -> None:
    r = apply_hard_rules(env("xss", "business_logic", "ssrf"))
    assert r.floor is Tier.SPECIALIST
    assert r.ceiling is Tier.EXPERT


def test_severity_critical_raises_floor_to_specialist() -> None:
    r = apply_hard_rules(env("xss", severity="critical"))
    assert r.floor is Tier.SPECIALIST
    assert r.ceiling is Tier.SPECIALIST
    assert r.ask_jev is True


def test_skills_are_case_insensitive() -> None:
    assert apply_hard_rules(env("RCE")).floor is Tier.SPECIALIST


@pytest.mark.parametrize(
    ("skill", "floor", "ceiling"),
    [
        ("vulnerabilities/idor", Tier.WORKER, Tier.SPECIALIST),
        ("vulnerabilities/business_logic", Tier.WORKER, Tier.SPECIALIST),
        (
            "vulnerabilities/broken_function_level_authorization",
            Tier.SPECIALIST,
            Tier.EXPERT,
        ),
    ],
)
def test_namespaced_skill_labels_open_the_jev_choice(
    skill: str, floor: Tier, ceiling: Tier
) -> None:
    result = apply_hard_rules(env(skill))
    assert (result.floor, result.ceiling, result.ask_jev) == (floor, ceiling, True)
