"""Opt-in upstream contracts; offline cases verify gates and complete declarations only."""

from __future__ import annotations

import json
import math
import os
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import httpx
import pytest
from agents import RunContextWrapper, Usage, function_tool
from agents.models import _openai_shared
from agents.models.chatcmpl_converter import Converter
from agents.models.interface import ModelTracing
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.sandbox.manifest import Manifest
from agents.sandbox.runtime_agent_preparation import clone_capabilities, prepare_sandbox_agent
from agents.sandbox.session.base_sandbox_session import BaseSandboxSession
from agents.tool_context import ToolContext
from openai import AsyncOpenAI

from strix.agents.factory import build_strix_agent
from strix.config.loader import load_settings
from strix.config.models import StrixProvider, supports_strict_tool_schemas
from strix.core.inputs import make_model_settings
from strix.routing.jev import JevClient
from strix.routing.runconfig import validate_routing_config
from strix.routing.types import Envelope
from tests.test_routing_runconfig import commandcode_settings


if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agents import ModelSettings
    from agents.agent import Agent
    from agents.tool import Tool

    from strix.config.settings import Settings


BASE = "https://api.commandcode.ai/provider/v1"
MODELS = (
    "openai/deepseek/deepseek-v4.1-flash",
    "openai/xiaomi/mimo-v2.6-pro",
    "openai/gpt-6.1-sol",
)


@pytest.fixture
def commandcode_key() -> str:
    if os.getenv("STRIX_ROUTING_LIVE_TESTS") != "1":
        pytest.skip("live opt-in is disabled")
    key = os.getenv("CMD_API_KEY")
    if not key:
        pytest.skip("CMD_API_KEY is unavailable")
    return key


@pytest.fixture(scope="module")
def catalog() -> dict[str, Any]:
    # Keep the module-scoped request gated independently of function fixtures.
    commandcode_key.__wrapped__()
    with httpx.Client(timeout=10) as client:
        response = client.get(BASE + "/models")
        response.raise_for_status()
        payload = response.json()
    assert isinstance(payload, dict), "catalog must be an object"
    rows = payload.get("data")
    assert isinstance(rows, list), "catalog must contain model data"
    index = {row["id"]: row for row in rows}
    for name in MODELS:
        wire_id = name.removeprefix("openai/")
        assert wire_id in index, "configured model absent from current catalog"
        endpoints = index[wire_id].get("supported_endpoints", [])
        assert "/chat/completions" in {endpoint.removeprefix("/v1") for endpoint in endpoints}, (
            "configured model lacks Chat Completions support"
        )
    return index


def assert_jev_catalog(index: dict[str, Any]) -> None:
    assert "typesafe/jev" in index, "JEV absent from current catalog"
    assert "/systemone" in {
        endpoint.removeprefix("/v1")
        for endpoint in index["typesafe/jev"].get("supported_endpoints", [])
    }, "JEV lacks System One support in the current catalog"


@function_tool
async def echo(value: str) -> str:
    """Return a synthetic string unchanged for the routing contract test."""
    return value


def declared_agent(model_name: str) -> Agent[Any]:
    agent = build_strix_agent(
        is_root=False,
        skills=["rce"],
        scan_mode="quick",
        chat_completions_tools=True,
        strict_tool_schemas=supports_strict_tool_schemas(model_name),
        extra_tools=[echo],
    )
    # A declaration-only session binds real SDK capabilities. No sandbox operation runs.
    session = MagicMock(spec=BaseSandboxSession)
    session.state = SimpleNamespace(manifest=Manifest(root="/workspace"))
    session.supports_pty.return_value = True
    for operation in ("exec", "read", "write", "pty_exec_start", "pty_write_stdin"):
        getattr(session, operation).side_effect = AssertionError("sandbox tool execution forbidden")
    capabilities = clone_capabilities(agent.capabilities)
    for capability in capabilities:
        capability.bind(session)
    return prepare_sandbox_agent(
        agent=agent, session=session, capabilities=capabilities, run_config_model=model_name
    )


@pytest.fixture
def live_settings(commandcode_key: str) -> Settings:
    __tracebackhide__ = True
    settings = load_settings().model_copy(deep=True)
    settings.llm.model = MODELS[0]
    settings.llm.api_key = commandcode_key
    settings.llm.api_base = BASE
    settings.llm.api_type = "chat_completions"
    settings.routing.enabled = True
    settings.routing.specialist_model = MODELS[1]
    settings.routing.expert_model = MODELS[2]
    settings.routing.jev_enabled = False
    validate_routing_config(settings, worker_model=MODELS[0])
    return settings


@pytest.fixture
async def live_provider(
    live_settings: Settings,
    catalog: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[StrixProvider]:
    assert catalog
    monkeypatch.setattr("strix.config.models.load_settings", lambda: live_settings)
    monkeypatch.setattr(_openai_shared, "_use_responses_by_default", False)
    async with AsyncOpenAI(
        api_key=live_settings.llm.api_key,
        base_url=BASE,
        max_retries=0,
        timeout=live_settings.llm.timeout,
    ) as client:
        provider = StrixProvider(openai_client=client)
        for name in MODELS:
            model = provider.get_model(name)
            inner = model
            while hasattr(inner, "_inner"):
                inner = inner._inner
            assert isinstance(inner, OpenAIChatCompletionsModel)
            assert inner.model == name.removeprefix("openai/")
        yield provider


def model_options(settings: Settings, model_name: str) -> ModelSettings:
    llm = settings.llm
    return make_model_settings(
        llm.reasoning_effort,
        model_name=model_name,
        force_required_tool_choice=llm.force_required_tool_choice,
        request_timeout=llm.timeout,
        prompt_cache=llm.prompt_cache,
        extra_headers=llm.extra_headers,
    )


async def sample(
    model: Any,
    *,
    streaming: bool,
    instructions: str | None,
    prompt: str,
    options: ModelSettings,
    tools: list[Tool],
    expected_model: str,
) -> tuple[list[Any], Any]:
    kwargs = {
        "system_instructions": instructions,
        "input": prompt,
        "model_settings": options,
        "tools": tools,
        "output_schema": None,
        "handoffs": [],
        "tracing": ModelTracing.DISABLED,
        "previous_response_id": None,
        "conversation_id": None,
        "prompt": None,
    }
    if not streaming:
        result = await model.get_response(**kwargs)
        return result.output, result.usage
    completed = [
        event.response
        async for event in model.stream_response(**kwargs)
        if event.type == "response.completed"
    ]
    assert len(completed) == 1, "stream must have exactly one completed response"
    result = completed[0]
    assert result.model == expected_model, "completed stream model differs from requested wire ID"
    return result.output, result.usage


def assert_usage(usage: Any, *, allow_zero: bool = False) -> None:
    assert usage is not None, "response must include usage"
    minimum = 0 if allow_zero else 1
    assert type(usage.input_tokens) is int and usage.input_tokens >= minimum
    assert type(usage.output_tokens) is int and usage.output_tokens >= minimum


@pytest.mark.parametrize("model_name", MODELS)
@pytest.mark.parametrize("streaming", [False, True])
async def test_live_text_contract(
    live_provider: StrixProvider,
    live_settings: Settings,
    model_name: str,
    streaming: bool,
) -> None:
    output, usage = await sample(
        live_provider.get_model(model_name),
        streaming=streaming,
        instructions=None,
        prompt="Return the text routing-smoke-ok. This is synthetic data.",
        options=model_options(live_settings, model_name),
        tools=[],
        expected_model=model_name.removeprefix("openai/"),
    )
    assert_usage(usage)
    text = "".join(
        part.text
        for item in output
        if item.type == "message"
        for part in item.content
        if part.type == "output_text"
    )
    assert "routing-smoke-ok" in text, "synthetic text marker missing"


@pytest.mark.parametrize("model_name", MODELS)
@pytest.mark.parametrize("streaming", [False, True])
async def test_live_full_tool_contract(
    live_provider: StrixProvider,
    live_settings: Settings,
    model_name: str,
    streaming: bool,
) -> None:
    agent = declared_agent(model_name)
    context = RunContextWrapper(context={})
    instructions = await agent.get_system_prompt(context)
    output, usage = await sample(
        live_provider.get_model(model_name),
        streaming=streaming,
        instructions=instructions,
        prompt=(
            "Synthetic contract test only. Call echo with value='synthetic'. Call no other tools."
        ),
        options=model_options(live_settings, model_name),
        tools=agent.tools,
        expected_model=model_name.removeprefix("openai/"),
    )
    assert_usage(usage)
    calls = [item for item in output if item.type == "function_call"]
    assert len(calls) == 1, "expected exactly one synthetic function call"
    call = calls[0]
    assert call.name == "echo", "model selected a different tool; no tools executed"
    assert call.call_id, "tool call ID missing"
    assert json.loads(call.arguments) == {"value": "synthetic"}
    tool = next(tool for tool in agent.tools if tool.name == "echo")
    tool_context = ToolContext.from_agent_context(
        context,
        tool_call_id=call.call_id,
        tool_name="echo",
        tool_arguments=call.arguments,
        agent=agent,
    )
    assert await tool.on_invoke_tool(tool_context, call.arguments) == "synthetic"


async def test_live_jev_contract(live_settings: Settings, catalog: dict[str, Any]) -> None:
    assert catalog
    assert_jev_catalog(catalog)
    if os.getenv("STRIX_ROUTING_LIVE_JEV_ALLOWED") != "1":
        pytest.skip("JEV metadata without ZDR requires explicit policy approval")
    live_settings.routing.jev_enabled = True
    validate_routing_config(live_settings, worker_model=MODELS[0])
    usage: list[Usage] = []
    async with httpx.AsyncClient(timeout=live_settings.routing.jev_timeout_s) as client:
        adapter = JevClient(
            client,
            base_url=BASE,
            api_key=live_settings.llm.api_key or "",
            timeout_s=live_settings.routing.jev_timeout_s,
            on_usage=usage.append,
        )
        result = await adapter.decide(Envelope("synthetic", ("rce",)), "route_tier")
    assert len(usage) == 1
    assert_usage(usage[0], allow_zero=True)
    assert set(result.probabilities) == {"worker", "specialist", "expert"}
    assert all(math.isfinite(value) and 0 <= value <= 1 for value in result.probabilities.values())
    assert abs(sum(result.probabilities.values()) - 1) <= 0.01


async def test_live_jev_envelope_contract(
    live_settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    if os.getenv("STRIX_ROUTING_LIVE_JEV_ALLOWED") != "1":
        pytest.skip("JEV metadata without ZDR requires explicit policy approval")
    caplog.set_level("INFO", logger="strix.routing.jev")
    live_settings.routing.jev_enabled = True
    validate_routing_config(live_settings, worker_model=MODELS[0])
    observed: list[dict[str, Any]] = []

    async def inspect_request(request: httpx.Request) -> None:
        payload = json.loads(request.content)
        state = json.loads(payload["state"])
        question = payload["questions"]["route_tier"]
        observed.append(
            {
                "url": str(request.url),
                "model": payload.get("model"),
                "state": state,
                "question_type": question.get("type"),
                "criteria": set(question.get("criteria", {})),
                "secret_absent": (
                    "ENVELOPE_PRIVATE_MARKER_867" not in request.content.decode()
                    and (live_settings.llm.api_key or "") not in request.content.decode()
                ),
            }
        )

    usage: list[Usage] = []
    envelope = Envelope(
        "synthetic private task ENVELOPE_PRIVATE_MARKER_867",
        ("vulnerabilities/idor", "custom ENVELOPE_PRIVATE_MARKER_867"),
        attempts=2,
        severity="HIGH",
    )
    async with httpx.AsyncClient(
        timeout=live_settings.routing.jev_timeout_s,
        event_hooks={"request": [inspect_request]},
    ) as client:
        adapter = JevClient(
            client,
            base_url=BASE,
            api_key=live_settings.llm.api_key or "",
            timeout_s=live_settings.routing.jev_timeout_s,
            on_usage=usage.append,
        )
        result = await adapter.decide(envelope, "route_tier")

    assert len(observed) == 1
    request = observed[0]
    assert request["url"] == BASE + "/systemone"
    assert request["model"] == "typesafe/jev"
    assert request["question_type"] == "choice"
    assert request["criteria"] == {"worker", "specialist", "expert"}
    assert request["state"] == {
        "skills": ["idor"],
        "attempts": 2,
        "severity": "high",
        "task_length_bucket": "short",
    }
    assert request["secret_absent"]
    assert result.choice in {"worker", "specialist", "expert"}
    assert set(result.probabilities) == {"worker", "specialist", "expert"}
    assert all(math.isfinite(value) and 0 <= value <= 1 for value in result.probabilities.values())
    assert abs(sum(result.probabilities.values()) - 1) <= 0.01
    assert len(usage) == 1 and usage[0].requests == 1
    assert type(usage[0].input_tokens) is int and type(usage[0].output_tokens) is int
    assert usage[0].total_tokens == usage[0].input_tokens + usage[0].output_tokens
    assert usage[0].input_tokens > 0 and usage[0].output_tokens >= 0
    assert "ENVELOPE_PRIVATE_MARKER_867" not in caplog.text
    assert live_settings.llm.api_key not in caplog.text


@pytest.mark.parametrize("flag", [None, "0", "1"])
def test_live_gate_skips_before_http(monkeypatch: pytest.MonkeyPatch, flag: str | None) -> None:
    monkeypatch.delenv("STRIX_ROUTING_LIVE_TESTS", raising=False)
    monkeypatch.delenv("CMD_API_KEY", raising=False)
    if flag is not None:
        monkeypatch.setenv("STRIX_ROUTING_LIVE_TESTS", flag)

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("network before live gate")

    monkeypatch.setattr(httpx, "Client", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(pytest.skip.Exception, match=r"opt-in|CMD_API_KEY"):
        commandcode_key.__wrapped__()
    with pytest.raises(pytest.skip.Exception, match=r"opt-in|CMD_API_KEY"):
        catalog.__wrapped__()


@pytest.mark.parametrize("model_name", MODELS)
async def test_full_declarations_offline(model_name: str) -> None:
    agent = declared_agent(model_name)
    names = [tool.name for tool in agent.tools]
    assert {
        "echo",
        "exec_command",
        "write_stdin",
        "apply_patch",
        "view_image",
        "create_agent",
        "agent_finish",
    } <= set(names)
    assert len(names) == len(set(names)) and len(names) > 20
    context = RunContextWrapper(context={})
    prompt = await agent.get_system_prompt(context)
    assert prompt and "Filesystem" in prompt and "shell" in prompt.lower()
    for tool in agent.tools:
        assert tool.params_json_schema["type"] == "object"
    wire = [Converter.tool_to_openai(tool) for tool in agent.tools]
    assert [entry["function"]["name"] for entry in wire] == names
    assert all(entry["type"] == "function" for entry in wire)
    # Strict-capable models retain the factory's intentionally non-strict tools.
    baseline = build_strix_agent(
        is_root=False,
        skills=["rce"],
        scan_mode="quick",
        chat_completions_tools=True,
        strict_tool_schemas=supports_strict_tool_schemas(model_name),
        extra_tools=[echo],
    )
    by_name = {tool.name: tool for tool in agent.tools}
    for tool in baseline.tools:
        assert by_name[tool.name].params_json_schema == tool.params_json_schema
        assert by_name[tool.name].strict_json_schema is tool.strict_json_schema
    for name in ("exec_command", "write_stdin", "apply_patch", "view_image"):
        assert by_name[name].strict_json_schema is False
    tool = next(tool for tool in agent.tools if tool.name == "echo")
    arguments = '{"value":"synthetic"}'
    tool_context = ToolContext.from_agent_context(
        context,
        tool_call_id="synthetic-id",
        tool_name="echo",
        tool_arguments=arguments,
        agent=agent,
    )
    assert await tool.on_invoke_tool(tool_context, arguments) == "synthetic"


def test_opt_in_with_key_does_not_skip_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIX_ROUTING_LIVE_TESTS", "1")
    monkeypatch.setenv("CMD_API_KEY", "synthetic")
    original = httpx.Client
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401)

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(**kw, transport=httpx.MockTransport(handler))
    )
    assert commandcode_key.__wrapped__() == "synthetic"
    with pytest.raises(httpx.HTTPStatusError):
        catalog.__wrapped__()
    assert len(requests) == 1 and str(requests[0].url) == BASE + "/models"


@pytest.mark.parametrize("model_name", MODELS)
@pytest.mark.parametrize("streaming", [False, True])
async def test_sampler_preserves_settings_and_full_tools_offline(
    model_name: str, streaming: bool
) -> None:
    agent = declared_agent(model_name)
    settings = commandcode_settings()
    options = model_options(settings, model_name)
    captured: list[dict[str, Any]] = []
    response = SimpleNamespace(
        output=[
            SimpleNamespace(
                type="function_call",
                name="echo",
                call_id="synthetic-id",
                arguments='{"value":"synthetic"}',
            )
        ],
        usage=Usage(requests=1, input_tokens=10, output_tokens=1, total_tokens=11),
        model=model_name.removeprefix("openai/"),
    )

    class FakeModel:
        async def get_response(self, **kwargs: Any) -> Any:
            captured.append(kwargs)
            return response

        async def stream_response(self, **kwargs: Any) -> AsyncIterator[Any]:
            captured.append(kwargs)
            yield SimpleNamespace(type="response.created")
            yield SimpleNamespace(type="response.completed", response=response)

    output, usage = await sample(
        FakeModel(),
        streaming=streaming,
        instructions="synthetic",
        prompt="synthetic",
        options=options,
        tools=agent.tools,
        expected_model=response.model,
    )
    assert output is response.output and usage is response.usage
    assert_usage(usage)
    assert len(captured) == 1
    assert captured[0]["tools"] is agent.tools
    assert captured[0]["model_settings"] is options
    assert captured[0]["system_instructions"] == "synthetic"
    assert captured[0]["tracing"] is ModelTracing.DISABLED
    assert captured[0]["input"] == "synthetic"


async def test_provider_shares_native_client_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = commandcode_settings()
    source = live_provider.__wrapped__(
        live_settings=settings, catalog={"synthetic": {}}, monkeypatch=monkeypatch
    )
    provider = await anext(source)
    try:
        clients = []
        for name in MODELS:
            inner = provider.get_model(name)
            while hasattr(inner, "_inner"):
                inner = inner._inner
            assert isinstance(inner, OpenAIChatCompletionsModel)
            assert inner.model == name.removeprefix("openai/")
            clients.append(inner._client)
        assert all(client is clients[0] for client in clients)
        assert str(clients[0].base_url).rstrip("/") == BASE
        assert clients[0].api_key == "dummy"
    finally:
        await source.aclose()


@pytest.mark.parametrize("broken", [None, "model", "chat_endpoint"])
def test_catalog_ids_and_endpoints_offline(
    monkeypatch: pytest.MonkeyPatch, broken: str | None
) -> None:
    monkeypatch.setenv("STRIX_ROUTING_LIVE_TESTS", "1")
    monkeypatch.setenv("CMD_API_KEY", "synthetic")
    rows = [
        {"id": name.removeprefix("openai/"), "supported_endpoints": ["/v1/chat/completions"]}
        for name in MODELS
    ]
    if broken == "model":
        rows.pop(0)
    elif broken == "chat_endpoint":
        rows[0]["supported_endpoints"] = ["/v1/responses"]
    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"data": rows})
            ),
        ),
    )
    if broken:
        with pytest.raises(AssertionError, match=r"catalog|Completions|System One"):
            catalog.__wrapped__()
    else:
        assert set(catalog.__wrapped__()) == {name.removeprefix("openai/") for name in MODELS}


@pytest.mark.parametrize("broken", [None, "model", "systemone_endpoint"])
def test_jev_catalog_ids_and_endpoint_offline(broken: str | None) -> None:
    rows = [{"id": "typesafe/jev", "supported_endpoints": ["/v1/systemone"]}]
    if broken == "model":
        rows.clear()
    elif broken == "systemone_endpoint":
        rows[0]["supported_endpoints"] = ["/v1/chat/completions"]
    if broken:
        with pytest.raises(AssertionError, match=r"JEV|System One"):
            assert_jev_catalog({row["id"]: row for row in rows})
    else:
        assert_jev_catalog({row["id"]: row for row in rows})
