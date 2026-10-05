from __future__ import annotations

import pytest

from strix.routing.governor import BudgetGovernor
from strix.routing.types import Tier


def test_first_expert_is_always_allowed() -> None:
    g = BudgetGovernor(specialist_cap=0.25, expert_cap=0.05)
    assert g.admit(Tier.EXPERT) is Tier.EXPERT


def test_second_expert_downgraded_until_share_allows() -> None:
    g = BudgetGovernor(specialist_cap=0.25, expert_cap=0.05)
    g.admit(Tier.EXPERT)
    assert g.admit(Tier.EXPERT) is Tier.SPECIALIST  # 2/2 > 5%


def test_expert_allowed_again_after_enough_total_decisions() -> None:
    g = BudgetGovernor(specialist_cap=1.0, expert_cap=0.05)
    g.admit(Tier.EXPERT)
    for _ in range(40):
        g.admit(Tier.WORKER)
    assert g.admit(Tier.EXPERT) is Tier.EXPERT  # 2/42 ~ 4.8%


def test_worker_is_never_downgraded() -> None:
    g = BudgetGovernor(specialist_cap=0.0, expert_cap=0.0)
    assert g.admit(Tier.WORKER) is Tier.WORKER


def test_counts_reflect_final_tier_not_requested_tier() -> None:
    g = BudgetGovernor(specialist_cap=0.25, expert_cap=0.05)
    g.admit(Tier.EXPERT)
    g.admit(Tier.EXPERT)
    assert g.counts == {Tier.WORKER: 0, Tier.SPECIALIST: 1, Tier.EXPERT: 1}


def test_zero_cap_disallows_optional_expert() -> None:
    g = BudgetGovernor(1.0, 0.0)
    assert g.admit(Tier.EXPERT, floor=Tier.WORKER, available=frozenset(Tier)) is Tier.SPECIALIST


def test_missing_expert_falls_to_specialist() -> None:
    g = BudgetGovernor(1.0, 1.0)
    assert (
        g.admit(
            Tier.EXPERT,
            floor=Tier.SPECIALIST,
            available=frozenset({Tier.WORKER, Tier.SPECIALIST}),
        )
        is Tier.SPECIALIST
    )


def test_missing_floor_is_rejected() -> None:
    g = BudgetGovernor(1.0, 1.0)
    with pytest.raises(ValueError, match="floor"):
        g.admit(Tier.EXPERT, floor=Tier.SPECIALIST, available=frozenset({Tier.WORKER, Tier.EXPERT}))


def test_hard_floor_overrides_zero_share_cap() -> None:
    g = BudgetGovernor(0.0, 0.0)
    for _ in range(3):
        assert g.admit(Tier.EXPERT, floor=Tier.SPECIALIST) is Tier.SPECIALIST
    assert g.counts == {Tier.WORKER: 0, Tier.SPECIALIST: 3, Tier.EXPERT: 0}


def test_requested_tier_below_floor_is_rejected_without_counting() -> None:
    g = BudgetGovernor(1.0, 1.0)
    with pytest.raises(ValueError, match="floor"):
        g.admit(Tier.WORKER, floor=Tier.SPECIALIST)
    assert sum(g.counts.values()) == 0
