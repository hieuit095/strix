from __future__ import annotations

import pytest

from strix.routing.governor import BudgetGovernor
from strix.routing.router import HybridModelRouter
from strix.routing.runconfig import configured_models
from strix.routing.types import DecisionResult, Envelope, Tier
from tests.test_routing_runconfig import commandcode_settings


class SyntheticJev:
    def __init__(
        self, probabilities: dict[str, float] | None = None, error: Exception | None = None
    ):
        self.probabilities = probabilities or {"worker": 1.0, "specialist": 0.0, "expert": 0.0}
        self.error = error
        self.calls = 0

    async def decide(self, _envelope: Envelope, question: str) -> DecisionResult:
        assert question == "route_tier"
        self.calls += 1
        if self.error:
            raise self.error
        return DecisionResult(self.probabilities, 8, 2)


def router(
    client: SyntheticJev | None,
    *,
    specialist_cap: float = 1.0,
    expert_cap: float = 1.0,
    available: frozenset[Tier] = frozenset(Tier),
) -> HybridModelRouter:
    return HybridModelRouter(
        client,
        BudgetGovernor(specialist_cap, expert_cap),
        specialist_threshold=0.65,
        expert_threshold=0.65,
        available=available,
    )


@pytest.mark.asyncio
async def test_no_signal_uses_worker_floor_without_consulting_jev() -> None:
    jev = SyntheticJev({"worker": 0.0, "specialist": 1.0, "expert": 0.0})
    decision = await router(jev).route(Envelope("routine", ("xss",)))
    assert (decision.tier, decision.reason, jev.calls) == (Tier.WORKER, "rule", 0)


@pytest.mark.parametrize(
    ("probability", "expected"), [(0.649, Tier.WORKER), (0.65, Tier.SPECIALIST)]
)
@pytest.mark.asyncio
async def test_specialist_requires_inclusive_threshold(probability: float, expected: Tier) -> None:
    jev = SyntheticJev({"worker": 1.0 - probability, "specialist": probability, "expert": 0.0})
    decision = await router(jev).route(Envelope("uncertain logic", ("business_logic",)))
    assert decision.tier is expected
    assert jev.calls == 1


@pytest.mark.parametrize(
    ("probability", "expected"), [(0.649, Tier.SPECIALIST), (0.65, Tier.EXPERT)]
)
@pytest.mark.asyncio
async def test_expert_requires_inclusive_threshold(probability: float, expected: Tier) -> None:
    jev = SyntheticJev({"worker": 0.0, "specialist": 1.0 - probability, "expert": probability})
    decision = await router(jev).route(Envelope("complex exploit chain", ("rce",)))
    assert decision.tier is expected


@pytest.mark.asyncio
async def test_expert_share_cap_steps_down_to_nearest_allowed_tier() -> None:
    jev = SyntheticJev({"worker": 0.0, "specialist": 0.1, "expert": 0.9})
    governor = BudgetGovernor(specialist_cap=1.0, expert_cap=0.05)
    routed = HybridModelRouter(jev, governor, specialist_threshold=0.65, expert_threshold=0.65)
    first = await routed.route(Envelope("first chain", ("rce",)))
    second = await routed.route(Envelope("second chain", ("rce",)))
    assert (first.tier, first.reason) == (Tier.EXPERT, "jev")
    assert (second.tier, second.reason) == (Tier.SPECIALIST, "governor")
    assert governor.counts == {Tier.WORKER: 0, Tier.SPECIALIST: 1, Tier.EXPERT: 1}


@pytest.mark.asyncio
async def test_specialist_share_cap_steps_down_to_worker() -> None:
    jev = SyntheticJev({"worker": 0.0, "specialist": 0.9, "expert": 0.1})
    decision = await router(jev, specialist_cap=0.0).route(
        Envelope("uncertain logic", ("business_logic",))
    )
    assert (decision.tier, decision.reason) == (Tier.WORKER, "governor")


@pytest.mark.asyncio
async def test_worker_floor_is_never_downgraded_by_zero_caps() -> None:
    decision = await router(None, specialist_cap=0.0, expert_cap=0.0).route(
        Envelope("routine", ("xss",))
    )
    assert (decision.tier, decision.reason) == (Tier.WORKER, "rule")


@pytest.mark.asyncio
async def test_jev_is_only_consulted_for_open_choice_and_overrides_floor_choice() -> None:
    closed = SyntheticJev({"worker": 0.0, "specialist": 1.0, "expert": 0.0})
    open_choice = SyntheticJev({"worker": 0.0, "specialist": 0.8, "expert": 0.2})
    plain = await router(closed).route(Envelope("routine", ("xss",)))
    ambiguous = await router(open_choice).route(Envelope("uncertain", ("business_logic",)))
    assert (plain.tier, closed.calls) == (Tier.WORKER, 0)
    assert (ambiguous.tier, ambiguous.reason, open_choice.calls) == (Tier.SPECIALIST, "jev", 1)


@pytest.mark.parametrize("error", [RuntimeError("transport"), ValueError("malformed choice")])
@pytest.mark.asyncio
async def test_jev_error_falls_back_to_rule_floor_with_reason(
    error: Exception,
) -> None:
    jev = SyntheticJev(error=error)
    decision = await router(jev).route(Envelope("high impact", ("rce",)))
    assert (decision.tier, decision.reason, jev.calls) == (Tier.SPECIALIST, "jev_error", 1)


@pytest.mark.asyncio
async def test_unconfigured_expert_model_is_never_selected() -> None:
    settings = commandcode_settings()
    settings.routing.enabled = True
    settings.routing.specialist_model = "openai/xiaomi/mimo-v2.6-pro"
    settings.routing.expert_model = None
    models = configured_models(settings, worker_model="openai/deepseek/deepseek-v4.1-flash")
    jev = SyntheticJev({"worker": 0.0, "specialist": 0.0, "expert": 1.0})
    decision = await router(jev, available=frozenset(models)).route(
        Envelope("high impact", ("rce",))
    )
    assert models == {
        Tier.WORKER: "openai/deepseek/deepseek-v4.1-flash",
        Tier.SPECIALIST: "openai/xiaomi/mimo-v2.6-pro",
    }
    assert decision.tier is Tier.SPECIALIST
    assert decision.tier in models


def test_configured_route_models_match_worker_specialist_expert_design() -> None:
    settings = commandcode_settings()
    settings.routing.enabled = True
    settings.routing.specialist_model = "openai/xiaomi/mimo-v2.6-pro"
    settings.routing.expert_model = "openai/gpt-6.1-sol"
    assert configured_models(settings, worker_model="openai/deepseek/deepseek-v4.1-flash") == {
        Tier.WORKER: "openai/deepseek/deepseek-v4.1-flash",
        Tier.SPECIALIST: "openai/xiaomi/mimo-v2.6-pro",
        Tier.EXPERT: "openai/gpt-6.1-sol",
    }


@pytest.mark.asyncio
async def test_synthetic_route_flow_selects_worker_specialist_then_expert_model() -> None:
    settings = commandcode_settings()
    settings.routing.enabled = True
    settings.routing.specialist_model = "openai/xiaomi/mimo-v2.6-pro"
    settings.routing.expert_model = "openai/gpt-6.1-sol"
    models = configured_models(settings, worker_model="openai/deepseek/deepseek-v4.1-flash")
    jev = SyntheticJev({"worker": 0.05, "specialist": 0.9, "expert": 0.05})
    router_instance = router(jev)
    observed = []
    cases = (
        (Envelope("routine", ("xss",)), Tier.WORKER),
        (Envelope("uncertain logic", ("business_logic",)), Tier.SPECIALIST),
    )
    for envelope, expected_tier in cases:
        decision = await router_instance.route(envelope)
        observed.append((decision.tier, models[decision.tier]))
        assert decision.tier is expected_tier
    jev.probabilities = {"worker": 0.05, "specialist": 0.05, "expert": 0.9}
    expert = await router_instance.route(Envelope("complex exploit", ("rce",)))
    observed.append((expert.tier, models[expert.tier]))
    assert expert.tier is Tier.EXPERT
    assert observed == [
        (Tier.WORKER, "openai/deepseek/deepseek-v4.1-flash"),
        (Tier.SPECIALIST, "openai/xiaomi/mimo-v2.6-pro"),
        (Tier.EXPERT, "openai/gpt-6.1-sol"),
    ]
    assert jev.calls == 2
