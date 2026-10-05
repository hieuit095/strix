from __future__ import annotations

from strix.routing.types import Envelope, Tier, max_tier, min_tier


def test_tier_order_is_worker_specialist_expert() -> None:
    assert list(Tier) == [Tier.WORKER, Tier.SPECIALIST, Tier.EXPERT]


def test_max_and_min_tier() -> None:
    assert max_tier(Tier.WORKER, Tier.EXPERT) is Tier.EXPERT
    assert min_tier(Tier.SPECIALIST, Tier.EXPERT) is Tier.SPECIALIST


def test_envelope_defaults() -> None:
    env = Envelope(task="probe /login", skills=())
    assert env.attempts == 0
    assert env.severity is None
