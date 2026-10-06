from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from agents import ModelSettings, RunConfig
from agents.models import _openai_shared
from agents.models.interface import ModelTracing
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from strix.agents.factory import make_child_factory
from strix.config.models import StrixProvider
from strix.config.settings import LlmSettings, RoutingSettings, Settings
from strix.routing.runconfig import configured_models, run_config_for_model, validate_routing_config
from strix.routing.types import Tier


@pytest.mark.parametrize("scan_mode", ["quick", "standard", "deep"])
@pytest.mark.parametrize("interactive", [False, True])
def test_real_agents_keep_prompts_tools_and_capabilities(scan_mode: str, interactive: bool) -> None:
    settings = commandcode_settings()
    base = RunConfig(model=settings.llm.model)
    child = run_config_for_model(base, settings.routing.specialist_model, settings)
    assert child.model != base.model
    options = {
        "scan_mode": scan_mode,
        "interactive": interactive,
        "is_whitebox": True,
        "is_diff_scoped": True,
        "chat_completions_tools": True,
        "strict_tool_schemas": False,
        "system_prompt_context": {"scope": "synthetic"},
    }
    before = make_child_factory(**options)(name="probe", skills=["rce"])
    after = make_child_factory(**options)(name="probe", skills=["rce"])
    assert before.instructions == after.instructions
    assert before.instructions
    assert [tool.name for tool in before.tools] == [tool.name for tool in after.tools]
    assert len(before.tools) > 10
    for old, new in zip(before.tools, after.tools, strict=True):
        assert getattr(old, "params_json_schema", None) == getattr(new, "params_json_schema", None)
        assert getattr(old, "strict_json_schema", None) == getattr(new, "strict_json_schema", None)
    assert (
        [cap.type for cap in before.capabilities]
        == [cap.type for cap in after.capabilities]
        == ["filesystem", "shell"]
    )
    for old, new in zip(before.capabilities, after.capabilities, strict=True):
        assert old.configure_tools is not None and new.configure_tools is not None


def test_worker_preserves_runconfig_identity() -> None:
    base = RunConfig(model="openai/worker")
    assert run_config_for_model(base, "openai/worker", Settings()) is base


def test_specialist_preserves_provider_and_base() -> None:
    base = RunConfig(model="openai/worker")
    result = run_config_for_model(base, "openai/spec", Settings())
    assert result is not base
    assert result.model == "openai/spec"
    assert base.model == "openai/worker"
    assert result.model_provider is base.model_provider
    assert result.model_settings is not base.model_settings


def commandcode_settings(**routing: object) -> Settings:

    return Settings(
        llm=LlmSettings(
            model="openai/deepseek/deepseek-v4.1-flash",
            api_base="https://api.commandcode.ai/provider/v1",
            api_key="dummy",
            api_type="chat_completions",
        ),
        routing=RoutingSettings(
            enabled=True,
            specialist_model="openai/xiaomi/mimo-v2.6-pro",
            expert_model="openai/gpt-6.1-sol",
            **routing,
        ),
    )


def test_configured_models_use_resolved_worker_and_optional_expert() -> None:

    settings = commandcode_settings()
    assert configured_models(settings, worker_model="openai/override") == {
        Tier.WORKER: "openai/override",
        Tier.SPECIALIST: "openai/xiaomi/mimo-v2.6-pro",
        Tier.EXPERT: "openai/gpt-6.1-sol",
    }
    settings.routing.expert_model = None
    assert configured_models(settings, worker_model="openai/override") == {
        Tier.WORKER: "openai/override",
        Tier.SPECIALIST: "openai/xiaomi/mimo-v2.6-pro",
    }
    settings.routing.enabled = False
    assert configured_models(settings, worker_model="openai/override") == {
        Tier.WORKER: "openai/override"
    }


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("specialist_model", None, "specialist"),
        ("api_base", "https://other.test/v1", "api_base"),
        ("api_type", None, "api_type"),
        ("api_type", "responses", "api_type"),
        ("specialist_model", "openrouter/spec", "model"),
        ("expert_model", "anthropic/expert", "model"),
        ("extra_headers", {"X-Cmd-Zdr": "1"}, "ZDR"),
        ("api_key", "", "api_key"),
    ],
)
def test_invalid_routing_config_rejected(field: str, value: object, match: str) -> None:

    settings = commandcode_settings(jev_enabled=True)
    target = settings.routing if field.endswith("model") else settings.llm
    setattr(target, field, value)
    with pytest.raises(ValueError, match=match):
        validate_routing_config(settings, worker_model=settings.llm.model)


def test_settings_builder_keeps_all_llm_options() -> None:
    settings = commandcode_settings()
    settings.llm.timeout = 17
    settings.llm.reasoning_effort = "max"
    settings.llm.force_required_tool_choice = True
    settings.llm.prompt_cache = False
    settings.llm.extra_headers = {"X-Test": "synthetic"}
    sentinel = ModelSettings()
    base = RunConfig(model="openai/worker", trace_include_sensitive_data=False)
    with patch("strix.routing.runconfig.make_model_settings", return_value=sentinel) as builder:
        result = run_config_for_model(base, "openai/spec", settings)
    builder.assert_called_once_with(
        "max",
        model_name="openai/spec",
        force_required_tool_choice=True,
        request_timeout=17,
        prompt_cache=False,
        extra_headers={"X-Test": "synthetic"},
    )
    assert result.model_settings is sentinel
    assert result.trace_include_sensitive_data is False


def test_disabled_validation_does_not_read_connection() -> None:

    validate_routing_config(
        SimpleNamespace(routing=SimpleNamespace(enabled=False)), worker_model="anthropic/claude"
    )


def test_compatible_config_accepts_trailing_slash_and_zdr_without_jev() -> None:

    settings = commandcode_settings()
    settings.llm.api_base += "/"
    settings.llm.extra_headers = {"x-cmd-zdr": "1"}
    validate_routing_config(settings, worker_model="openai/override")


def test_incompatible_tool_flags_rejected() -> None:

    settings = commandcode_settings()
    settings.routing.specialist_model = "openai/claude-sonnet-4-6"
    with pytest.raises(ValueError, match="tool schema"):
        validate_routing_config(settings, worker_model=settings.llm.model)


@pytest.mark.parametrize(
    "wire_id", ["deepseek/deepseek-v4.1-flash", "xiaomi/mimo-v2.6-pro", "gpt-6.1-sol"]
)
async def test_native_sdk_wire_ids(wire_id: str, monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setattr(_openai_shared, "_use_responses_by_default", False)
    settings = commandcode_settings()
    monkeypatch.setattr("strix.config.models.load_settings", lambda: settings)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": wire_id,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "synthetic"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
            },
        )

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client,
        AsyncOpenAI(
            api_key="dummy", base_url=settings.llm.api_base, http_client=http_client
        ) as client,
    ):
        model = StrixProvider(api_key="dummy", base_url=settings.llm.api_base).get_model(
            "openai/" + wire_id
        )
        inner = model
        while hasattr(inner, "_inner"):
            inner = inner._inner
        assert isinstance(inner, OpenAIChatCompletionsModel)
        inner._client = client
        response = await model.get_response(
            system_instructions=None,
            input="synthetic",
            model_settings=ModelSettings(extra_headers={"X-Test": "synthetic"}),
            tools=[],
            output_schema=None,
            handoffs=[],
            tracing=ModelTracing.DISABLED,
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 1
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.commandcode.ai/provider/v1/chat/completions"
    assert json.loads(requests[0].content)["model"] == wire_id
    assert requests[0].headers["Authorization"] == "Bearer dummy"
    assert requests[0].headers["X-Test"] == "synthetic"
