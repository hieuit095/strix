from __future__ import annotations

import asyncio
import copy
import json
from typing import TYPE_CHECKING

import httpx
import pytest

from strix.routing.governor import BudgetGovernor
from strix.routing.jev import JevClient
from strix.routing.router import HybridModelRouter
from strix.routing.types import Envelope, Tier


if TYPE_CHECKING:
    from agents.usage import Usage


VALID = {
    "model": "typesafe/jev",
    "answers": {
        "route_tier": {
            "type": "choice",
            "choice": "specialist",
            "confidence": 0.7,
            "probabilities": {"worker": 0.1, "specialist": 0.8, "expert": 0.1},
        }
    },
    "usage": {"input_tokens": 180, "output_tokens": 3},
}


async def test_jev_wire_and_result() -> None:
    requests: list[httpx.Request] = []
    usage: list[Usage] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=VALID)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = JevClient(
            client,
            base_url="https://api.commandcode.ai/provider/v1",
            api_key="dummy",
            timeout_s=5,
            on_usage=usage.append,
        )
        result = await adapter.decide(Envelope("synthetic", ("business_logic",)), "route_tier")
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.commandcode.ai/provider/v1/systemone"
    assert requests[0].headers["Authorization"] == "Bearer dummy"
    assert requests[0].extensions["timeout"]["read"] == 5
    body = json.loads(requests[0].content)
    assert body["model"] == "typesafe/jev"
    assert isinstance(body["state"], str)
    assert body["questions"]["route_tier"]["type"] == "choice"
    assert result.probabilities == {"worker": 0.1, "specialist": 0.8, "expert": 0.1}
    assert (result.input_tokens, result.output_tokens) == (180, 3)
    assert len(usage) == 1
    assert (usage[0].requests, usage[0].total_tokens) == (1, 183)


async def test_allowlist_excludes_raw_task_and_custom_skills() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=VALID)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = JevClient(
            client,
            base_url="https://api.commandcode.ai/provider/v1",
            api_key="dummy",
            timeout_s=5,
            on_usage=lambda _usage: None,
        )
        await adapter.decide(
            Envelope(
                "https://private.test/a?token=abc XYZ_SECRET_921",
                ("business_logic", "XYZ_SECRET_921"),
                attempts=2,
                severity="high",
            ),
            "route_tier",
        )
    body = json.loads(requests[0].content)
    assert json.loads(body["state"]) == {
        "skills": ["business_logic"],
        "attempts": 2,
        "severity": "high",
        "task_length_bucket": "short",
    }
    assert "XYZ_SECRET_921" not in requests[0].content.decode()
    assert "private.test" not in requests[0].content.decode()


@pytest.mark.parametrize("question", ["wrong"])
async def test_unsupported_question_rejected_before_http(question: str) -> None:
    requests: list[httpx.Request] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, json=VALID)
        )
    ) as client:
        adapter = JevClient(
            client,
            base_url="https://example.test/v1",
            api_key="dummy",
            timeout_s=5,
            on_usage=lambda _usage: None,
        )
        with pytest.raises(ValueError, match="question"):
            await adapter.decide(Envelope("t", ()), question)
    assert not requests


@pytest.mark.parametrize("attempts", [-1, True, 1.5])
async def test_invalid_attempts_rejected_before_http(attempts) -> None:
    requests: list[httpx.Request] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, json=VALID)
        )
    ) as client:
        adapter = JevClient(
            client,
            base_url="https://example.test/v1",
            api_key="dummy",
            timeout_s=5,
            on_usage=lambda _usage: None,
        )
        with pytest.raises(ValueError, match="attempts"):
            await adapter.decide(Envelope("t", (), attempts=attempts), "route_tier")
    assert not requests


@pytest.mark.parametrize(
    ("length", "bucket"), [(256, "short"), (257, "medium"), (2048, "medium"), (2049, "long")]
)
async def test_task_length_boundaries(length: int, bucket: str) -> None:
    requests: list[httpx.Request] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, json=VALID)
        )
    ) as client:
        adapter = JevClient(
            client,
            base_url="https://example.test/v1",
            api_key="dummy",
            timeout_s=5,
            on_usage=lambda _usage: None,
        )
        await adapter.decide(
            Envelope("X" * length, ("RCE", "rce", "unknown"), severity="SECRET"), "route_tier"
        )
    state = json.loads(json.loads(requests[0].content)["state"])
    assert state == {
        "skills": ["rce"],
        "attempts": 0,
        "severity": None,
        "task_length_bucket": bucket,
    }


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("answers",), {}),
        (("answers", "route_tier", "type"), "score"),
        (("answers", "route_tier", "choice"), "other"),
        (("answers", "route_tier", "probabilities"), {"worker": 0.2, "specialist": 0.8}),
        (
            ("answers", "route_tier", "probabilities"),
            {"worker": 0.1, "specialist": 0.8, "expert": 0.1, "other": 0},
        ),
        *(
            ((("answers", "route_tier", "probabilities", "worker"), value))
            for value in [-0.1, 1.1, True, float("nan"), float("inf"), "0.1"]
        ),
        (("answers", "route_tier", "probabilities", "worker"), 0),
        *(
            ((("answers", "route_tier", "confidence"), value))
            for value in [True, float("nan"), float("inf"), -0.1, 1.1]
        ),
    ],
)
async def test_malformed_answer_rejected_with_usage(path: tuple[str, ...], value: object) -> None:
    payload = copy.deepcopy(VALID)
    parent = payload
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    usage: list[Usage] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                content=json.dumps(payload, allow_nan=True),
                headers={"Content-Type": "application/json"},
            )
        )
    ) as client:
        adapter = JevClient(
            client,
            base_url="https://example.test/v1",
            api_key="dummy",
            timeout_s=5,
            on_usage=usage.append,
        )
        with pytest.raises(ValueError):
            await adapter.decide(Envelope("synthetic", ()), "route_tier")
    assert len(usage) == 1
    assert usage[0].total_tokens == 183


@pytest.mark.parametrize(
    "tokens",
    [
        None,
        {},
        {"input_tokens": -1, "output_tokens": 3},
        {"input_tokens": True, "output_tokens": 3},
        {"input_tokens": 1.5, "output_tokens": 3},
        {"input_tokens": "180", "output_tokens": 3},
        {"input_tokens": 180, "output_tokens": -1},
    ],
)
async def test_malformed_usage_not_recorded(tokens: object) -> None:
    payload = copy.deepcopy(VALID)
    payload["usage"] = tokens
    usage: list[Usage] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    ) as client:
        adapter = JevClient(
            client,
            base_url="https://example.test/v1",
            api_key="dummy",
            timeout_s=5,
            on_usage=usage.append,
        )
        with pytest.raises(ValueError):
            await adapter.decide(Envelope("synthetic", ()), "route_tier")
    assert not usage


@pytest.mark.parametrize(("delta", "valid"), [(0.009, True), (0.011, False)])
async def test_probability_sum_tolerance_and_extra_fields(delta: float, valid: bool) -> None:
    payload = copy.deepcopy(VALID)
    payload["extra"] = "future"
    payload["answers"]["route_tier"]["probabilities"]["worker"] += delta
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
    ) as client:
        adapter = JevClient(
            client,
            base_url="https://example.test/v1",
            api_key="dummy",
            timeout_s=5,
            on_usage=lambda _usage: None,
        )
        if valid:
            result = await adapter.decide(Envelope("t", ()), "route_tier")
            assert result.probabilities["worker"] == pytest.approx(0.109)
        else:
            with pytest.raises(ValueError, match="sum"):
                await adapter.decide(Envelope("t", ()), "route_tier")


@pytest.mark.parametrize("status", [400, 401, 403, 422, 429, 500, 502, 503, 504])
async def test_http_error_has_one_request_and_router_falls_back(status: int) -> None:
    requests: list[httpx.Request] = []
    usage: list[Usage] = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: (
                requests.append(request) or httpx.Response(status, text="SERVER_SECRET_82")
            )
        )
    ) as client:
        adapter = JevClient(
            client,
            base_url="https://example.test/v1",
            api_key="KEY_SECRET_51",
            timeout_s=5,
            on_usage=usage.append,
        )
        router = HybridModelRouter(
            adapter, BudgetGovernor(1, 1), specialist_threshold=0.65, expert_threshold=0.65
        )
        d = await router.route(Envelope("t", ("rce",)))
        assert (d.tier, d.reason) == (Tier.SPECIALIST, "jev_error")
    assert len(requests) == 1
    assert not usage


async def test_router_logs_only_error_class(caplog: pytest.LogCaptureFixture) -> None:
    class FailedClient:
        async def decide(self, _envelope: Envelope, _question: str):
            raise ValueError("KEY_SECRET_51 SERVER_SECRET_82")

    router = HybridModelRouter(
        FailedClient(), BudgetGovernor(1, 1), specialist_threshold=0.65, expert_threshold=0.65
    )
    d = await router.route(Envelope("t", ("rce",)))
    assert d.reason == "jev_error"
    assert "KEY_SECRET_51" not in caplog.text
    assert "SERVER_SECRET_82" not in caplog.text


@pytest.mark.parametrize("failure", ["timeout", "cancel", "non_json"])
async def test_transport_and_json_errors(failure: str) -> None:
    requests: list[httpx.Request] = []
    usage: list[Usage] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic")
        if failure == "cancel":
            raise asyncio.CancelledError
        return httpx.Response(200, text="not JSON")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = JevClient(
            client,
            base_url="https://example.test/v1",
            api_key="dummy",
            timeout_s=5,
            on_usage=usage.append,
        )
        router = HybridModelRouter(
            adapter, BudgetGovernor(1, 1), specialist_threshold=0.65, expert_threshold=0.65
        )
        if failure == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await router.route(Envelope("t", ("rce",)))
        else:
            d = await router.route(Envelope("t", ("rce",)))
            assert (d.tier, d.reason) == (Tier.SPECIALIST, "jev_error")
    assert len(requests) == 1
    assert not usage


async def test_usage_callback_error_never_retries_http() -> None:
    requests: list[httpx.Request] = []

    def fail(_usage: Usage) -> None:
        raise RuntimeError("synthetic accounting failure")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, json=VALID)
        )
    ) as client:
        adapter = JevClient(
            client, base_url="https://example.test/v1", api_key="dummy", timeout_s=5, on_usage=fail
        )
        with pytest.raises(RuntimeError, match="accounting"):
            await adapter.decide(Envelope("t", ()), "route_tier")
    assert len(requests) == 1
