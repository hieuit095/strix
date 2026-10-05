"""Reuse the scan's provider while selecting a child's model settings."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, cast

from strix.config.models import supports_strict_tool_schemas, uses_chat_completions_tool_schema
from strix.core.inputs import make_model_settings
from strix.routing.types import Tier


if TYPE_CHECKING:
    from agents import RunConfig

    from strix.config.settings import Settings


def run_config_for_model(base: RunConfig, model_name: str, settings: Settings) -> RunConfig:
    if model_name == base.model:
        return base
    llm = settings.llm
    return replace(
        base,
        model=model_name,
        model_settings=make_model_settings(
            llm.reasoning_effort,
            model_name=model_name,
            force_required_tool_choice=llm.force_required_tool_choice,
            request_timeout=llm.timeout,
            prompt_cache=llm.prompt_cache,
            extra_headers=llm.extra_headers,
        ),
    )


def configured_models(settings: Settings, *, worker_model: str) -> dict[Tier, str]:
    models = {Tier.WORKER: worker_model}
    if settings.routing.enabled:
        if settings.routing.specialist_model:
            models[Tier.SPECIALIST] = settings.routing.specialist_model
        if settings.routing.expert_model:
            models[Tier.EXPERT] = settings.routing.expert_model
    return models


def validate_routing_config(settings: Settings, *, worker_model: str) -> None:
    if not settings.routing.enabled:
        return
    routing, llm = settings.routing, settings.llm
    if not routing.specialist_model:
        raise ValueError("routing requires specialist_model")
    if (llm.api_base or "").rstrip("/") != "https://api.commandcode.ai/provider/v1":
        raise ValueError("routing requires CommandCode api_base")
    if llm.api_type != "chat_completions":
        raise ValueError("routing requires api_type=chat_completions")
    if routing.jev_enabled:
        if not (llm.api_key or "").strip():
            raise ValueError("JEV requires main api_key")
        if any(
            k.lower() == "x-cmd-zdr" and v.strip() == "1"
            for k, v in (llm.extra_headers or {}).items()
        ):
            raise ValueError("JEV is incompatible with mandatory ZDR")
    flags = (
        uses_chat_completions_tool_schema(worker_model, settings),
        supports_strict_tool_schemas(worker_model),
    )
    for model_name in configured_models(settings, worker_model=worker_model).values():
        if not model_name.startswith("openai/") or not model_name.removeprefix("openai/").strip():
            raise ValueError("routing model requires native openai/ prefix")
        if flags != (
            uses_chat_completions_tool_schema(model_name, settings),
            supports_strict_tool_schemas(model_name),
        ):
            raise ValueError("routing model has incompatible tool schema flags")


def validate_saved_bindings(
    metadata: dict[str, dict[str, Any]], settings: Settings, *, worker_model: str
) -> None:
    models = configured_models(settings, worker_model=worker_model)
    fields = {"version", "tier", "model", "api_base", "api_type"}
    for md in metadata.values():
        if "routing" not in md:
            continue
        if not settings.routing.enabled:
            raise RuntimeError("routing must remain enabled to resume saved bindings")
        candidate = md["routing"]
        if not isinstance(candidate, dict) or set(cast("dict[str, Any]", candidate)) != fields:
            raise RuntimeError("routing binding fields are invalid")
        binding = cast("dict[str, Any]", candidate)
        if type(binding["version"]) is not int or binding["version"] != 1:
            raise RuntimeError("routing binding version is unsupported")
        tier_name = binding["tier"]
        if not isinstance(tier_name, str) or tier_name not in {tier.name.lower() for tier in Tier}:
            raise RuntimeError("routing binding tier is invalid")
        tier = Tier[tier_name.upper()]
        if tier not in models or binding["model"] != models[tier]:
            raise RuntimeError("routing binding model differs from configured tier model")
        if binding["api_base"] != (settings.llm.api_base or "").rstrip("/"):
            raise RuntimeError("routing binding api_base differs from current gateway")
        if (
            binding["api_type"] != settings.llm.api_type
            or binding["api_type"] != "chat_completions"
        ):
            raise RuntimeError("routing binding api_type differs from current route")
