from __future__ import annotations

from strix.routing.types import Tier


class BudgetGovernor:
    """Caps the share of decisions that may go to the costlier tiers.

    Runs on a single event loop, so it needs no locking.
    """

    def __init__(self, specialist_cap: float) -> None:
        self._caps = {Tier.SPECIALIST: specialist_cap}
        self.counts: dict[Tier, int] = dict.fromkeys(Tier, 0)

    def _allowed(self, tier: Tier) -> bool:
        cap = self._caps.get(tier)
        if cap is None:
            return True
        if cap == 0:
            return False
        total = sum(self.counts.values())
        return self.counts[tier] + 1 <= max(1.0, cap * (total + 1))

    def admit(
        self,
        tier: Tier,
        *,
        floor: Tier = Tier.WORKER,
        available: frozenset[Tier] = frozenset(Tier),
    ) -> Tier:
        """Return ``tier``, or the nearest cheaper tier whose share cap allows it."""
        if floor not in available or tier < floor:
            raise ValueError("routing floor is unavailable or above requested tier")
        while tier > floor and (tier not in available or not self._allowed(tier)):
            tier = Tier(tier - 1)
        self.counts[tier] += 1
        return tier
