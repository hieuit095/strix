from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

import httpx

from strix.routing.policy import apply_hard_rules
from strix.routing.types import DecisionResult, Envelope, RouteDecision, Tier, max_tier, min_tier


if TYPE_CHECKING:
    from strix.routing.governor import BudgetGovernor


logger = logging.getLogger(__name__)


class DecisionClient(Protocol):
    async def decide(self, envelope: Envelope, question: str) -> DecisionResult: ...


class HybridModelRouter:
    """Hard rules decide what they can; JEV only breaks genuine ties; a governor caps spend."""

    def __init__(
        self,
        client: DecisionClient | None,
        governor: BudgetGovernor,
        *,
        specialist_threshold: float,
        available: frozenset[Tier] = frozenset(Tier),
    ) -> None:
        self._client = client
        self._governor = governor
        self._specialist_threshold = specialist_threshold
        self._available = available

    def _pick(self, probs: dict[str, float], choice: str | None) -> Tier:
        target = Tier.WORKER
        if choice is None:
            ceiling = Tier.SPECIALIST
        else:
            ceiling = {
                "worker": Tier.WORKER,
                "specialist": Tier.SPECIALIST,
                # JEV's provider schema still has an expert answer; this router
                # deliberately clamps it to the highest configured tier.
                "expert": Tier.SPECIALIST,
            }.get(choice, Tier.WORKER)
        if ceiling >= Tier.SPECIALIST and (
            choice == "expert" or probs.get("specialist", 0.0) >= self._specialist_threshold
        ):
            target = Tier.SPECIALIST
        return target

    async def route(self, envelope: Envelope) -> RouteDecision:
        rules = apply_hard_rules(envelope)
        if rules.floor not in self._available:
            raise ValueError("routing floor is unavailable")
        allowed = frozenset(t for t in self._available if rules.floor <= t <= rules.ceiling)
        if not rules.ask_jev or self._client is None or len(allowed) == 1:
            return RouteDecision(
                self._governor.admit(rules.floor, floor=rules.floor, available=allowed), "rule"
            )
        reason = "jev"
        choice: str | None = None
        try:
            result = await self._client.decide(envelope, "route_tier")
            choice = result.choice
            wanted = self._pick(result.probabilities, result.choice)
        except (TimeoutError, ValueError, RuntimeError, httpx.HTTPError) as exc:
            logger.warning("JEV routing failed (%s); using the rule floor", type(exc).__name__)
            wanted, reason = rules.floor, "jev_error"
        wanted = min_tier(max_tier(wanted, rules.floor), rules.ceiling)
        wanted = max(t for t in allowed if t <= wanted)
        final = self._governor.admit(wanted, floor=rules.floor, available=allowed)
        return RouteDecision(final, "governor" if final != wanted else reason, choice)
