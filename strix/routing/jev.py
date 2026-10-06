"""CommandCode System One adapter; the scan owns the HTTP client's lifecycle."""

from __future__ import annotations

import json
import logging
import math
from typing import TYPE_CHECKING, Any, cast

from agents.usage import Usage

from strix.routing.policy import AMBIGUOUS, HIGH_IMPACT
from strix.routing.types import DecisionResult, Envelope


if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx


logger = logging.getLogger(__name__)


_QUESTION: dict[str, Any] = {
    "type": "choice",
    "instructions": (
        "Choose the minimum reasoning tier needed for this security task from the supplied "
        "metadata. A skill label alone is not evidence of a vulnerability."
    ),
    "criteria": {
        "worker": "Routine discovery, known checks, or execution of an existing plan.",
        "specialist": (
            "Multi-step exploit planning, authorization relationships, or uncertain business logic."
        ),
        "expert": (
            "Difficult reasoning across several conditions or complex high-impact exploit chains."
        ),
    },
}


class JevClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        base_url: str,
        api_key: str,
        timeout_s: float,
        on_usage: Callable[[Usage], None],
    ) -> None:
        self._client = client
        self._url = base_url.rstrip("/") + "/systemone"
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._on_usage = on_usage

    async def decide(self, envelope: Envelope, question: str) -> DecisionResult:
        if question != "route_tier":
            raise ValueError("unsupported JEV question")
        _tokens(envelope.attempts, field="attempts")
        response = await self._client.post(
            self._url,
            headers={
                "Authorization": "Bearer " + self._api_key,
                "Content-Type": "application/json",
            },
            json={
                "model": "typesafe/jev",
                "state": json.dumps(
                    {
                        "skills": sorted(
                            {s.lower() for s in envelope.skills} & (HIGH_IMPACT | AMBIGUOUS)
                        ),
                        "attempts": envelope.attempts,
                        "severity": (
                            (envelope.severity or "").lower()
                            if (envelope.severity or "").lower()
                            in {"low", "medium", "high", "critical"}
                            else None
                        ),
                        "task_length_bucket": (
                            "short"
                            if len(envelope.task) <= 256
                            else "medium"
                            if len(envelope.task) <= 2048
                            else "long"
                        ),
                    }
                ),
                "questions": {question: _QUESTION},
            },
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        payload = _object(response.json())
        tokens = _object(payload.get("usage"))
        input_tokens = _tokens(tokens.get("input_tokens"))
        output_tokens = _tokens(tokens.get("output_tokens"))
        self._on_usage(
            Usage(
                requests=1,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )
        )
        answer = _object(_object(payload.get("answers")).get(question))
        choice = answer.get("choice")
        if (
            answer.get("type") != "choice"
            or not isinstance(choice, str)
            or choice not in _QUESTION["criteria"]
        ):
            raise ValueError("invalid JEV choice answer")
        _probability(answer.get("confidence"))
        raw_probabilities = _object(answer.get("probabilities"))
        if set(raw_probabilities) != {"worker", "specialist", "expert"}:
            raise ValueError("invalid JEV probability labels")
        probabilities = {label: _probability(value) for label, value in raw_probabilities.items()}
        if abs(sum(probabilities.values()) - 1.0) > 0.01:
            raise ValueError("invalid JEV probability sum")
        logger.info(
            "JEV routing answer choice=%s input_tokens=%d output_tokens=%d",
            choice,
            input_tokens,
            output_tokens,
        )
        return DecisionResult(probabilities, input_tokens, output_tokens, choice)


def _object(value: object) -> dict[str, Any]:
    if value is None or not isinstance(value, dict):
        raise ValueError("invalid JEV object")
    return cast("dict[str, Any]", value)


def _tokens(value: object, *, field: str = "token usage") -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"invalid JEV {field}")
    return value


def _probability(value: object) -> float:
    if (
        not isinstance(value, int | float)
        or isinstance(value, bool)
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError("invalid JEV probability or confidence")
    return float(value)
