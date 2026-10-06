from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Tier(IntEnum):
    WORKER = 0
    SPECIALIST = 1
    EXPERT = 2


def max_tier(a: Tier, b: Tier) -> Tier:
    return a if a >= b else b


def min_tier(a: Tier, b: Tier) -> Tier:
    return a if a <= b else b


@dataclass(frozen=True)
class Envelope:
    """The small, non-sensitive description of a task that routing decides on."""

    task: str
    skills: tuple[str, ...]
    severity: str | None = None  # "low" | "medium" | "high" | "critical"
    attempts: int = 0
    worker_confidence: float | None = None


@dataclass(frozen=True)
class RouteDecision:
    tier: Tier
    reason: str  # "rule" | "jev" | "jev_error" | "governor"
    jev_choice: str | None = None


@dataclass(frozen=True)
class DecisionResult:
    probabilities: dict[str, float]
    input_tokens: int
    output_tokens: int
    choice: str | None = None
