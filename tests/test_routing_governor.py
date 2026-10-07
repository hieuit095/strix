from __future__ import annotations

import pytest

from strix.routing.governor import BudgetGovernor
from strix.routing.types import Tier


def test_worker_is_never_downgraded() -> None:
    g = BudgetGovernor(specialist_cap=0.0)
    assert g.admit(Tier.WORKER) is Tier.WORKER


def test_specialist_share_cap_steps_down_to_worker() -> None:
    g = BudgetGovernor(specialist_cap=0.25)
    assert g.admit(Tier.SPECIALIST) is Tier.SPECIALIST
    assert g.admit(Tier.SPECIALIST) is Tier.WORKER
    assert g.counts == {Tier.WORKER: 1, Tier.SPECIALIST: 1}


def test_missing_specialist_falls_to_worker() -> None:
    g = BudgetGovernor(specialist_cap=1.0)
    assert (
        g.admit(
            Tier.SPECIALIST,
            floor=Tier.WORKER,
            available=frozenset({Tier.WORKER}),
        )
        is Tier.WORKER
    )


def test_missing_floor_is_rejected() -> None:
    g = BudgetGovernor(1.0)
    with pytest.raises(ValueError, match="floor"):
        g.admit(Tier.SPECIALIST, floor=Tier.SPECIALIST, available=frozenset({Tier.WORKER}))


def test_hard_floor_overrides_zero_share_cap() -> None:
    g = BudgetGovernor(0.0)
    for _ in range(3):
        assert g.admit(Tier.SPECIALIST, floor=Tier.SPECIALIST) is Tier.SPECIALIST
    assert g.counts == {Tier.WORKER: 0, Tier.SPECIALIST: 3}


def test_requested_tier_below_floor_is_rejected_without_counting() -> None:
    g = BudgetGovernor(1.0)
    with pytest.raises(ValueError, match="floor"):
        g.admit(Tier.WORKER, floor=Tier.SPECIALIST)
    assert sum(g.counts.values()) == 0
