from __future__ import annotations

import pytest

from scripts import verify_hybrid_routing
from strix.routing.governor import BudgetGovernor
from strix.routing.router import HybridModelRouter
from strix.routing.runconfig import configured_models
from strix.routing.types import DecisionResult, Envelope, Tier
from tests.test_routing_runconfig import commandcode_settings


def test_jev_error_evidence_requires_a_matching_real_failure() -> None:
    decision = [
        {
            "tier": "specialist",
            "model": "openai/xiaomi/mimo-v2.6-pro",
            "reason": "jev_error",
        }
    ]
    audit = getattr(verify_hybrid_routing, "jev_evidence_matches", None)
    assert callable(audit)
    assert not audit(decision, [], [])
    assert audit(decision, [], ["HTTPStatusError"])


def test_jev_route_log_requires_the_observed_choice() -> None:
    decisions = [
        {"reason": "jev", "jev_choice": "specialist"},
        {"reason": "rule", "jev_choice": None},
        {"reason": "jev_error", "jev_choice": None},
    ]
    audit = getattr(verify_hybrid_routing, "jev_choice_evidence_matches", None)
    assert callable(audit)
    assert audit(decisions)
    assert not audit([{"reason": "jev", "jev_choice": None}])


class SyntheticJev:
    def __init__(
        self,
        probabilities: dict[str, float] | None = None,
        error: Exception | None = None,
        choice: str | None = None,
    ):
        self.probabilities = probabilities or {"worker": 1.0, "specialist": 0.0, "expert": 0.0}
        self.error = error
        self.choice = choice
        self.calls = 0

    async def decide(self, _envelope: Envelope, question: str) -> DecisionResult:
        assert question == "route_tier"
        self.calls += 1
        if self.error:
            raise self.error
        return DecisionResult(self.probabilities, 8, 2, self.choice)


def router(
    client: SyntheticJev | None,
    *,
    specialist_cap: float = 1.0,
    available: frozenset[Tier] = frozenset(Tier),
) -> HybridModelRouter:
    return HybridModelRouter(
        client,
        BudgetGovernor(specialist_cap),
        specialist_threshold=0.65,
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


@pytest.mark.asyncio
async def test_specialist_share_cap_steps_down_to_worker() -> None:
    jev = SyntheticJev({"worker": 0.0, "specialist": 0.9, "expert": 0.1})
    decision = await router(jev, specialist_cap=0.0).route(
        Envelope("uncertain logic", ("business_logic",))
    )
    assert (decision.tier, decision.reason) == (Tier.WORKER, "governor")


@pytest.mark.asyncio
async def test_worker_floor_is_never_downgraded_by_zero_caps() -> None:
    decision = await router(None, specialist_cap=0.0).route(Envelope("routine", ("xss",)))
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
    decision = await router(jev).route(Envelope("uncertain logic", ("business_logic",)))
    assert (decision.tier, decision.reason, jev.calls) == (Tier.WORKER, "jev_error", 1)


@pytest.mark.asyncio
async def test_removed_expert_choice_is_clamped_to_configured_specialist() -> None:
    settings = commandcode_settings()
    settings.routing.enabled = True
    settings.routing.specialist_model = "openai/xiaomi/mimo-v2.6-pro"
    models = configured_models(settings, worker_model="openai/deepseek/deepseek-v4.1-flash")
    jev = SyntheticJev({"worker": 0.0, "specialist": 0.0, "expert": 1.0}, choice="expert")
    decision = await router(jev, available=frozenset(models)).route(
        Envelope("ambiguous", ("business_logic",))
    )
    assert models == {
        Tier.WORKER: "openai/deepseek/deepseek-v4.1-flash",
        Tier.SPECIALIST: "openai/xiaomi/mimo-v2.6-pro",
    }
    assert decision.tier is Tier.SPECIALIST
    assert decision.tier in models


def test_configured_route_models_match_two_model_design() -> None:
    settings = commandcode_settings()
    settings.routing.enabled = True
    settings.routing.specialist_model = "openai/xiaomi/mimo-v2.6-pro"
    assert configured_models(settings, worker_model="openai/deepseek/deepseek-v4.1-flash") == {
        Tier.WORKER: "openai/deepseek/deepseek-v4.1-flash",
        Tier.SPECIALIST: "openai/xiaomi/mimo-v2.6-pro",
    }


@pytest.mark.asyncio
async def test_expert_jev_choice_clamps_to_specialist_model() -> None:
    settings = commandcode_settings()
    settings.routing.enabled = True
    settings.routing.specialist_model = "openai/xiaomi/mimo-v2.6-pro"
    models = configured_models(settings, worker_model="openai/deepseek/deepseek-v4.1-flash")
    jev = SyntheticJev({"worker": 0.05, "specialist": 0.05, "expert": 0.9}, choice="expert")
    decision = await router(jev, available=frozenset(models)).route(
        Envelope("uncertain exploit", ("business_logic",))
    )
    assert decision.tier is Tier.SPECIALIST
    assert decision.reason == "jev"
    assert decision.jev_choice == "expert"
    assert models[decision.tier] == "openai/xiaomi/mimo-v2.6-pro"
    assert "expert" not in {tier.name.lower() for tier in models}
    assert jev.calls == 1


@pytest.mark.asyncio
async def test_jev_choices_map_to_worker_and_specialist_models_with_expert_clamp() -> None:
    settings = commandcode_settings()
    models = configured_models(settings, worker_model="openai/deepseek/deepseek-v4.1-flash")
    cases = (
        ("worker", ("business_logic",), {"worker": 0.1, "specialist": 0.8, "expert": 0.1}),
        ("specialist", ("business_logic",), {"worker": 0.1, "specialist": 0.8, "expert": 0.1}),
        ("expert", ("business_logic",), {"worker": 0.05, "specialist": 0.05, "expert": 0.9}),
    )
    expected_models = (
        (Tier.WORKER, "openai/deepseek/deepseek-v4.1-flash"),
        (Tier.SPECIALIST, "openai/xiaomi/mimo-v2.6-pro"),
        (Tier.SPECIALIST, "openai/xiaomi/mimo-v2.6-pro"),
    )
    observed = []
    for (choice, skills, probabilities), (tier, model) in zip(cases, expected_models, strict=True):
        jev = SyntheticJev(probabilities, choice=choice)
        decision = await router(jev, available=frozenset(models)).route(
            Envelope("synthetic", skills)
        )
        observed.append((decision.jev_choice, decision.tier, models[decision.tier]))
        assert (decision.tier, models[decision.tier]) == (tier, model)
    assert [entry[0] for entry in observed] == ["worker", "specialist", "expert"]
    assert [entry[1:] for entry in observed] == list(expected_models)
