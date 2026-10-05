from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import httpx
import pytest
from agents import RunConfig

from strix.core import execution, runner
from strix.core.agents import AgentCoordinator
from strix.core.hooks import BudgetExceededError, BudgetPausedError, SubagentBudgetReservedError
from tests.test_routing_jev import VALID
from tests.test_routing_runconfig import commandcode_settings
from tests.test_runner_root_prompt import _patch_engine_scaffold


if TYPE_CHECKING:
    from pathlib import Path


async def run_spawn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    enabled: bool,
    skills: list[str] | None = None,
    model: str | None = None,
    jev: bool = False,
    coordinator: AgentCoordinator | None = None,
    budget_policy: str = "stop",
    max_budget: float | None = None,
    report_state: Any = None,
    outcome: str = "success",
    expected_error: type[Exception] | None = None,
    parent_model: str | None = None,
) -> dict[str, Any]:
    captured = _patch_engine_scaffold(monkeypatch, tmp_path, {"scope": "synthetic"})
    settings = commandcode_settings(jev_enabled=jev)
    settings.routing.enabled = enabled
    monkeypatch.setattr(runner, "load_settings", lambda: settings)
    monkeypatch.setattr(runner, "configure_sdk_api_route", lambda *_args: None)
    monkeypatch.setattr(runner, "get_global_report_state", lambda: report_state)
    captured["settings"] = settings
    captured["children"] = []

    async def start(**kwargs: Any) -> dict[str, Any]:
        captured["children"].append(kwargs)
        return {"success": True, "agent_id": "child"}

    async def loop(**kwargs: Any) -> None:
        captured["root"] = kwargs
        context = kwargs["context"]

        async def spawn() -> Any:
            parent_context = dict(context, model=parent_model) if parent_model else context
            return await context["spawn_child_agent"](
                parent_ctx=parent_context,
                name="probe",
                task="synthetic",
                skills=skills if skills is not None else ["rce"],
                parent_history=[{"role": "user", "content": "background"}],
            )

        if expected_error is None:
            captured["result"] = await spawn()
        else:
            with pytest.raises(expected_error):
                await spawn()
        if outcome == "cancel":
            raise asyncio.CancelledError
        if outcome == "error":
            raise ValueError("synthetic failure")

    monkeypatch.setattr(runner, "start_child_agent", start)
    monkeypatch.setattr(runner, "run_agent_loop", loop)
    await runner.run_strix_scan(
        scan_config={"targets": [], "scan_mode": "quick"},
        scan_id="routing-test",
        image="img",
        coordinator=coordinator,
        model=model,
        max_turns=37,
        max_budget_usd=max_budget,
        budget_policy=budget_policy,
    )
    return captured


async def test_disabled_keeps_original_runconfig(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("routing constructed while disabled")

    monkeypatch.setattr(runner, "HybridModelRouter", forbidden, raising=False)
    monkeypatch.setattr(runner, "JevClient", forbidden, raising=False)
    result = await run_spawn(monkeypatch, tmp_path, enabled=False)
    child, root = result["children"][0], result["root"]
    assert child["run_config"] is root["run_config"]
    assert child["task"] == "synthetic"
    assert child["skills"] == ["rce"]
    assert child["parent_ctx"] is root["context"]
    assert child["parent_history"] == [{"role": "user", "content": "background"}]
    assert child.get("routing") is None


async def test_enabled_routes_specialist_preserving_spawn_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    result = await run_spawn(monkeypatch, tmp_path, enabled=True)
    child, root = result["children"][0], result["root"]
    assert child["run_config"].model == "openai/xiaomi/mimo-v2.6-pro"
    assert root["run_config"].model == "openai/deepseek/deepseek-v4.1-flash"
    assert child["run_config"].model_provider is root["run_config"].model_provider
    assert child["task"] == "synthetic" and child["skills"] == ["rce"]
    assert child["parent_history"] == [{"role": "user", "content": "background"}]
    assert child["hooks"] is root["hooks"]
    assert child["event_sink"] is root["event_sink"]
    assert child["max_turns"] == root["max_turns"] == 37
    assert child["interactive"] is root["interactive"] is False
    assert root["context"]["model"] == root["run_config"].model
    assert child["routing"] == {
        "version": 1,
        "tier": "specialist",
        "model": "openai/xiaomi/mimo-v2.6-pro",
        "api_base": "https://api.commandcode.ai/provider/v1",
        "api_type": "chat_completions",
    }


async def test_root_model_argument_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    result = await run_spawn(
        monkeypatch, tmp_path, enabled=True, skills=["xss"], model="openai/override"
    )
    child, root = result["children"][0], result["root"]
    assert root["run_config"].model == "openai/override"
    assert child["run_config"] is root["run_config"]
    assert child["routing"]["model"] == "openai/override"
    assert child["routing"]["tier"] == "worker"


async def test_binding_exists_before_child_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = AgentCoordinator()
    await coordinator.register("root", "root", None)
    binding = {
        "version": 1,
        "tier": "specialist",
        "model": "openai/xiaomi/mimo-v2.6-pro",
        "api_base": "https://api.commandcode.ai/provider/v1",
        "api_type": "chat_completions",
    }
    started: list[str] = []

    async def start(**kwargs: Any) -> None:
        child_id = kwargs["child_id"]
        assert coordinator.metadata[child_id]["routing"] == binding
        started.append(child_id)

    monkeypatch.setattr(execution, "_start_child_runner", start)
    result = await execution.spawn_child_agent(
        coordinator=coordinator,
        factory=lambda **_kwargs: object(),
        agents_db_path=tmp_path / "agents.db",
        sessions_to_close=[],
        run_config=RunConfig(model=binding["model"]),
        max_turns=50,
        interactive=False,
        parent_ctx={"agent_id": "root"},
        name="probe",
        task="synthetic",
        skills=["rce"],
        parent_history=[],
        routing=binding,
    )
    assert result["success"] is True
    assert started == [result["agent_id"]]


async def test_child_context_uses_own_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    coordinator = AgentCoordinator()
    await coordinator.register("root", "root", None)
    await coordinator.register("child", "child", "root")
    captured: dict[str, Any] = {}

    async def loop(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(execution, "run_agent_loop", loop)
    parent_ctx = {"agent_id": "root", "model": "openai/worker", "other": "preserved"}
    sessions: list[Any] = []
    try:
        await execution._start_child_runner(
            parent_ctx=parent_ctx,
            coordinator=coordinator,
            agents_db_path=tmp_path / "agents.db",
            sessions_to_close=sessions,
            run_config=RunConfig(model="openai/spec"),
            max_turns=50,
            interactive=False,
            child_agent=object(),
            child_id="child",
            name="child",
            parent_id="root",
            task="synthetic",
            initial_input=[],
        )
        await coordinator.runtimes["child"].task
        assert captured["context"]["model"] == "openai/spec"
        assert captured["context"]["other"] == "preserved"
        assert parent_ctx["model"] == "openai/worker"
    finally:
        for session in sessions:
            session.close()


def mock_jev_http(
    monkeypatch: pytest.MonkeyPatch,
    *,
    state: Any = None,
    probs: dict[str, float] | None = None,
    cost: float = 10,
) -> tuple[list[httpx.Request], list[httpx.AsyncClient]]:
    requests: list[httpx.Request] = []
    clients: list[httpx.AsyncClient] = []
    original = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = copy.deepcopy(VALID)
        if probs is not None:
            payload["answers"]["route_tier"]["probabilities"] = probs
        if state is not None:
            state.cost = cost
        return httpx.Response(200, json=payload)

    def client() -> httpx.AsyncClient:
        result = original(transport=httpx.MockTransport(handler))
        clients.append(result)
        return result

    monkeypatch.setattr(runner, "httpx", SimpleNamespace(AsyncClient=client), raising=False)
    return requests, clients


async def test_jev_selects_expert_and_records_usage_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    state = SimpleNamespace(cost=0, get_total_llm_cost=lambda: 0, record_sdk_usage=MagicMock())
    requests, clients = mock_jev_http(
        monkeypatch, probs={"worker": 0.05, "specialist": 0.05, "expert": 0.9}
    )
    result = await run_spawn(monkeypatch, tmp_path, enabled=True, jev=True, report_state=state)
    assert result["children"][0]["run_config"].model == "openai/gpt-6.1-sol"
    assert len(requests) == 1 and len(clients) == 1
    assert clients[0].is_closed
    state.record_sdk_usage.assert_called_once()
    usage_call = state.record_sdk_usage.call_args.kwargs
    assert usage_call["agent_id"] == usage_call["agent_name"] == "routing"
    assert usage_call["model"] == "typesafe/jev"
    assert usage_call["usage"].total_tokens == 183


@pytest.mark.parametrize(
    ("policy", "expected"), [("stop", BudgetExceededError), ("pause", BudgetPausedError)]
)
async def test_budget_rechecked_after_jev(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, policy: str, expected: type[Exception]
) -> None:
    state = SimpleNamespace(cost=0, record_sdk_usage=MagicMock())
    state.get_total_llm_cost = lambda: state.cost
    requests, clients = mock_jev_http(monkeypatch, state=state)
    result = await run_spawn(
        monkeypatch,
        tmp_path,
        enabled=True,
        jev=True,
        report_state=state,
        max_budget=5,
        budget_policy=policy,
        expected_error=expected,
    )
    assert not result["children"]
    assert len(requests) == 1 and clients[0].is_closed


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        ("stop", BudgetExceededError),
        ("reserve", SubagentBudgetReservedError),
        ("pause", BudgetPausedError),
    ],
)
async def test_budget_flags_prevent_routing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flag: str, expected: type[Exception]
) -> None:
    coordinator = AgentCoordinator()
    if flag == "stop":
        await coordinator.trigger_budget_stop()
    elif flag == "reserve":
        await coordinator.claim_reserve_notification()
    else:
        await coordinator.pause_budget()
    requests, clients = mock_jev_http(monkeypatch)
    result = await run_spawn(
        monkeypatch,
        tmp_path,
        enabled=True,
        jev=True,
        coordinator=coordinator,
        expected_error=expected,
    )
    assert not requests and not result["children"]
    assert all(c.is_closed for c in clients)


@pytest.mark.parametrize("outcome", ["success", "error", "cancel"])
async def test_jev_client_closed_on_every_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, outcome: str
) -> None:
    requests, clients = mock_jev_http(monkeypatch)
    if outcome == "success":
        await run_spawn(monkeypatch, tmp_path, enabled=True, jev=True, outcome=outcome)
    else:
        error = asyncio.CancelledError if outcome == "cancel" else ValueError
        with pytest.raises(error):
            await run_spawn(monkeypatch, tmp_path, enabled=True, jev=True, outcome=outcome)
    assert len(requests) == 1 and len(clients) == 1 and clients[0].is_closed


async def test_jev_client_closed_on_setup_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_engine_scaffold(monkeypatch, tmp_path, {"scope": "synthetic"})
    settings = commandcode_settings(jev_enabled=True)
    monkeypatch.setattr(runner, "load_settings", lambda: settings)
    requests, clients = mock_jev_http(monkeypatch)

    def fail(_config: Any) -> None:
        raise ValueError("synthetic setup failure")

    monkeypatch.setattr(runner, "build_root_task", fail)
    with pytest.raises(ValueError, match="setup"):
        await runner.run_strix_scan(scan_config={"targets": []}, scan_id="setup", image="img")
    assert not requests
    assert len(clients) == 1 and clients[0].is_closed


async def test_invalid_config_fails_before_sandbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_engine_scaffold(monkeypatch, tmp_path, {})
    settings = commandcode_settings()
    settings.routing.specialist_model = None
    monkeypatch.setattr(runner, "load_settings", lambda: settings)

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("sandbox started")

    monkeypatch.setattr(runner.session_manager, "create_or_reuse", forbidden)
    with pytest.raises(ValueError, match="specialist"):
        await runner.run_strix_scan(scan_config={"targets": []}, scan_id="invalid", image="img")


async def test_plain_task_never_calls_jev(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    requests, clients = mock_jev_http(monkeypatch)
    result = await run_spawn(monkeypatch, tmp_path, enabled=True, jev=True, skills=["xss"])
    assert result["children"][0]["run_config"] is result["root"]["run_config"]
    assert not requests
    assert len(clients) == 1 and clients[0].is_closed


async def test_floor_only_does_not_create_http_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    requests, clients = mock_jev_http(monkeypatch)
    result = await run_spawn(monkeypatch, tmp_path, enabled=True)
    assert result["children"][0]["run_config"].model == "openai/xiaomi/mimo-v2.6-pro"
    assert not requests and not clients


async def test_nested_specialist_parent_can_spawn_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    result = await run_spawn(
        monkeypatch,
        tmp_path,
        enabled=True,
        skills=["xss"],
        parent_model="openai/xiaomi/mimo-v2.6-pro",
    )
    child = result["children"][0]
    assert child["run_config"] is result["root"]["run_config"]
    assert child["parent_ctx"]["model"] == "openai/xiaomi/mimo-v2.6-pro"
    assert child["routing"]["tier"] == "worker"


async def test_jev_selects_specialist_for_ambiguous_task(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    requests, _clients = mock_jev_http(
        monkeypatch, probs={"worker": 0.1, "specialist": 0.8, "expert": 0.1}
    )
    result = await run_spawn(
        monkeypatch, tmp_path, enabled=True, jev=True, skills=["business_logic"]
    )
    assert result["children"][0]["routing"]["tier"] == "specialist"
    assert len(requests) == 1


@pytest.mark.parametrize(
    ("policy", "cost", "expected"),
    [
        ("stop", 10, BudgetExceededError),
        ("stop", 4.6, SubagentBudgetReservedError),
        ("pause", 10, BudgetPausedError),
    ],
)
async def test_current_cost_prevents_routing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    policy: str,
    cost: float,
    expected: type[Exception],
) -> None:
    state = SimpleNamespace(get_total_llm_cost=lambda: cost)
    requests, _clients = mock_jev_http(monkeypatch)
    result = await run_spawn(
        monkeypatch,
        tmp_path,
        enabled=True,
        jev=True,
        report_state=state,
        max_budget=5,
        budget_policy=policy,
        expected_error=expected,
    )
    assert not requests and not result["children"]


async def test_reserve_rechecked_after_jev(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state = SimpleNamespace(cost=0, record_sdk_usage=MagicMock())
    state.get_total_llm_cost = lambda: state.cost
    requests, _clients = mock_jev_http(monkeypatch, state=state, cost=4.6)
    result = await run_spawn(
        monkeypatch,
        tmp_path,
        enabled=True,
        jev=True,
        report_state=state,
        max_budget=5,
        expected_error=SubagentBudgetReservedError,
    )
    assert len(requests) == 1 and not result["children"]
