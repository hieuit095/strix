from __future__ import annotations

import asyncio

import pytest

from strix.routing.governor import BudgetGovernor
from strix.routing.router import HybridModelRouter
from strix.routing.types import DecisionResult, Envelope, Tier


class FakeClient:
    def __init__(
        self,
        probs: dict[str, float] | None = None,
        exc: BaseException | None = None,
        choice: str | None = None,
    ) -> None:
        self.probs = probs or {}
        self.exc = exc
        self.choice = choice
        self.calls = 0

    async def decide(self, envelope: Envelope, question: str) -> DecisionResult:
        del envelope
        assert question == "route_tier"
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        return DecisionResult(self.probs, 10, 1, self.choice)


def make(client: FakeClient, *, cap: float = 1.0) -> HybridModelRouter:
    return HybridModelRouter(client, BudgetGovernor(cap), specialist_threshold=0.65)


def e(*skills: str) -> Envelope:
    return Envelope(task="t", skills=skills)


async def test_obvious_task_never_calls_jev() -> None:
    c = FakeClient()
    d = await make(c).route(e("xss"))
    assert d.tier is Tier.WORKER
    assert c.calls == 0
    assert d.reason == "rule"


@pytest.mark.parametrize(
    ("skill", "probs", "expected"),
    [
        ("business_logic", {"worker": 0.35, "specialist": 0.65, "expert": 0.0}, Tier.SPECIALIST),
        ("business_logic", {"worker": 0.351, "specialist": 0.649, "expert": 0.0}, Tier.WORKER),
    ],
)
async def test_specialist_threshold_is_inclusive(
    skill: str, probs: dict[str, float], expected: Tier
) -> None:
    assert (await make(FakeClient(probs)).route(e(skill))).tier is expected


async def test_expert_jev_answer_clamps_to_specialist() -> None:
    client = FakeClient({"worker": 0.05, "specialist": 0.05, "expert": 0.9}, choice="expert")
    decision = await make(client).route(e("business_logic"))
    assert (decision.tier, decision.reason, decision.jev_choice) == (
        Tier.SPECIALIST,
        "jev",
        "expert",
    )


async def test_severe_plain_task_has_one_choice_without_jev() -> None:
    c = FakeClient({"worker": 0.1, "specialist": 0.1, "expert": 0.8})
    d = await make(c).route(Envelope("t", ("xss",), severity="high"))
    assert (d.tier, d.reason) == (Tier.SPECIALIST, "rule")
    assert c.calls == 0


async def test_router_rejects_missing_floor_before_jev() -> None:
    c = FakeClient()
    r = HybridModelRouter(
        c,
        BudgetGovernor(1.0),
        specialist_threshold=0.65,
        available=frozenset({Tier.WORKER}),
    )
    with pytest.raises(ValueError, match="floor"):
        await r.route(e("rce"))
    assert c.calls == 0


async def test_jev_below_threshold_stays_worker() -> None:
    c = FakeClient({"worker": 0.5, "specialist": 0.4, "expert": 0.1})
    assert (await make(c).route(e("business_logic"))).tier is Tier.WORKER


async def test_jev_cannot_downgrade_below_rule_floor() -> None:
    c = FakeClient({"worker": 0.99, "specialist": 0.005, "expert": 0.005}, choice="worker")
    assert (await make(c).route(e("rce"))).tier is Tier.SPECIALIST
    assert c.calls == 0  # high-impact rules have a closed Specialist-only range


@pytest.mark.parametrize("exc", [TimeoutError(), ValueError("bad json"), RuntimeError()])
async def test_jev_failure_falls_back_to_floor(exc: Exception) -> None:
    d = await make(FakeClient(exc=exc)).route(e("business_logic"))
    assert d.tier is Tier.WORKER
    assert d.reason == "jev_error"


async def test_cancellation_is_not_swallowed() -> None:
    with pytest.raises(asyncio.CancelledError):
        await make(FakeClient(exc=asyncio.CancelledError())).route(e("business_logic"))


async def test_governor_downgrades_specialist_when_cap_overruns() -> None:
    r = make(FakeClient({"worker": 0.0, "specialist": 1.0, "expert": 0.0}), cap=0.25)
    await r.route(e("business_logic"))
    d = await r.route(e("business_logic"))
    assert d.tier is Tier.WORKER
    assert d.reason == "governor"


async def test_repeated_high_impact_never_drops_below_floor() -> None:
    r = make(FakeClient())
    decisions = [await r.route(e("rce")) for _ in range(3)]
    assert [d.tier for d in decisions] == [Tier.SPECIALIST] * 3


async def test_floor_only_routes_without_client() -> None:
    r = HybridModelRouter(None, BudgetGovernor(0.25), specialist_threshold=0.65)
    d = await r.route(e("rce"))
    assert (d.tier, d.reason) == (Tier.SPECIALIST, "rule")


async def test_single_allowed_tier_never_calls_jev() -> None:
    c = FakeClient({"worker": 0.0, "specialist": 0.0, "expert": 1.0}, choice="expert")
    r = HybridModelRouter(
        c,
        BudgetGovernor(1.0),
        specialist_threshold=0.65,
        available=frozenset({Tier.WORKER, Tier.SPECIALIST}),
    )
    assert (await r.route(e("rce"))).tier is Tier.SPECIALIST
    assert c.calls == 0
