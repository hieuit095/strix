from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any

import pytest
from agents import RunConfig

from strix.core import execution, runner
from strix.core.agents import AgentCoordinator
from strix.routing.governor import BudgetGovernor
from strix.routing.types import Tier
from tests.test_routing_runconfig import commandcode_settings
from tests.test_routing_spawn import mock_jev_http, run_spawn
from tests.test_runner_root_prompt import _patch_engine_scaffold


if TYPE_CHECKING:
    from pathlib import Path


BINDING = {
    "version": 1,
    "tier": "specialist",
    "model": "openai/xiaomi/mimo-v2.6-pro",
    "api_base": "https://api.commandcode.ai/provider/v1",
    "api_type": "chat_completions",
}


async def test_snapshot_preserves_routing_counts() -> None:
    source = AgentCoordinator()
    source.routing_counts = {Tier.WORKER: 4, Tier.SPECIALIST: 2}
    snap = await source.snapshot()
    assert snap["routing"] == {"version": 1, "counts": {"worker": 4, "specialist": 2}}
    restored = AgentCoordinator()
    await restored.restore(snap)
    assert restored.routing_counts == source.routing_counts


@pytest.mark.parametrize(
    "routing",
    [
        None,
        {},
        {"version": 2, "counts": {}},
        {"version": True, "counts": {"worker": 0, "specialist": 0}},
        *[
            {"version": 1, "counts": {"worker": value, "specialist": 0}}
            for value in [-1, True, 1.5, "1"]
        ],
        {"version": 1, "counts": {"worker": 0}},
        {"version": 1, "counts": {"worker": 0, "specialist": 0, "unknown": 1}},
    ],
)
async def test_malformed_counts_rejected(routing: Any) -> None:
    with pytest.raises(RuntimeError, match="routing"):
        await AgentCoordinator().restore({"routing": routing})


async def test_counts_share_governor_reference() -> None:
    coordinator = AgentCoordinator()
    governor = BudgetGovernor(0.2)
    coordinator.routing_counts = governor.counts
    governor.admit(Tier.SPECIALIST, floor=Tier.SPECIALIST)
    assert (await coordinator.snapshot())["routing"]["counts"]["specialist"] == 1


async def test_legacy_expert_count_is_preserved_in_specialist_total() -> None:
    coordinator = AgentCoordinator()
    await coordinator.restore(
        {"routing": {"version": 1, "counts": {"worker": 4, "specialist": 2, "expert": 3}}}
    )
    assert coordinator.routing_counts == {Tier.WORKER: 4, Tier.SPECIALIST: 5}
    assert (await coordinator.snapshot())["routing"]["counts"] == {"worker": 4, "specialist": 5}


async def test_disabled_snapshot_is_legacy() -> None:
    coordinator = AgentCoordinator()
    assert "routing" not in await coordinator.snapshot()
    await coordinator.restore({})
    assert coordinator.routing_counts is None


async def test_legacy_bindings_reconstruct_all_children(caplog: pytest.LogCaptureFixture) -> None:
    coordinator = AgentCoordinator()
    await coordinator.restore(
        {
            "metadata": {
                "complete": {"routing": BINDING},
                "failed": {"routing": BINDING},
                "legacy": {},
            },
            "statuses": {"complete": "completed", "failed": "failed", "legacy": "running"},
        }
    )
    assert coordinator.routing_counts == {Tier.WORKER: 0, Tier.SPECIALIST: 2}
    assert "reconstruct" in caplog.text


@pytest.mark.parametrize("tier", ["unknown", [], {}, None])
async def test_legacy_unknown_tier_rejected(tier: Any) -> None:
    with pytest.raises(RuntimeError, match="routing"):
        await AgentCoordinator().restore({"metadata": {"child": {"routing": {"tier": tier}}}})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", 2),
        ("version", True),
        ("tier", "unknown"),
        ("tier", []),
        ("model", "openai/changed"),
        ("api_base", "https://other.invalid"),
        ("api_type", "responses"),
        ("secret", "SECRET_KEY_91"),
        ("model", None),
    ],
)
async def test_binding_mismatch_starts_no_children(
    tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    coordinator = AgentCoordinator()
    await coordinator.register("root", "root", None)
    await coordinator.register("valid", "valid", "root", routing=BINDING)
    invalid = dict(BINDING, **{field: value})
    await coordinator.register("invalid", "invalid", "root", routing=invalid)
    starts: list[Any] = []

    def factory(**kwargs: Any) -> object:
        starts.append(kwargs)
        return object()

    with pytest.raises(RuntimeError, match=r"routing|binding"):
        await execution.respawn_subagents(
            coordinator=coordinator,
            factory=factory,
            agents_db_path=tmp_path / "db",
            sessions_to_close=[],
            run_config=RunConfig(model="openai/deepseek/deepseek-v4.1-flash"),
            max_turns=50,
            interactive=False,
            parent_ctx={},
            root_id="root",
            settings=commandcode_settings(),
        )
    assert not starts


@pytest.mark.parametrize("settings_mode", ["disabled", "missing", "changed_base", "changed_type"])
async def test_binding_requires_compatible_settings(
    tmp_path: Path,
    settings_mode: str,
) -> None:
    coordinator = AgentCoordinator()
    await coordinator.register("root", "root", None)
    await coordinator.register("child", "child", "root", routing=BINDING)
    settings = commandcode_settings()
    if settings_mode == "disabled":
        settings.routing.enabled = False
    elif settings_mode == "changed_base":
        settings.llm.api_base = "https://other.invalid"
    elif settings_mode == "changed_type":
        settings.llm.api_type = "responses"
    with pytest.raises(RuntimeError, match=r"routing|binding"):
        await execution.respawn_subagents(
            coordinator=coordinator,
            factory=lambda **_kw: object(),
            agents_db_path=tmp_path / "db",
            sessions_to_close=[],
            run_config=RunConfig(model="openai/deepseek/deepseek-v4.1-flash"),
            max_turns=50,
            interactive=False,
            parent_ctx={},
            root_id="root",
            settings=None if settings_mode == "missing" else settings,
        )


async def test_respawn_preserves_model_provider_counts_and_legacy_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = AgentCoordinator()
    await coordinator.register("root", "root", None)
    await coordinator.register(
        "specialist", "specialist", "root", task="synthetic", skills=["rce"], routing=BINDING
    )
    await coordinator.register("legacy", "legacy", "root")
    coordinator.routing_counts = {Tier.WORKER: 0, Tier.SPECIALIST: 2}
    before = copy.deepcopy(coordinator.routing_counts)
    captured: list[dict[str, Any]] = []

    async def start(**kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(execution, "_start_child_runner", start)
    base = RunConfig(model="openai/deepseek/deepseek-v4.1-flash")
    settings = commandcode_settings()
    settings.llm.api_key = "SECRET_KEY_91"
    settings.llm.extra_headers = {"X-Secret": "hidden"}
    settings.llm.api_base += "/"
    await execution.respawn_subagents(
        coordinator=coordinator,
        factory=lambda **_kw: object(),
        agents_db_path=tmp_path / "db",
        sessions_to_close=[],
        run_config=base,
        max_turns=50,
        interactive=False,
        parent_ctx={},
        root_id="root",
        settings=settings,
    )
    assert captured[0]["run_config"].model == BINDING["model"]
    assert captured[0]["run_config"].model_provider is base.model_provider
    assert captured[1]["run_config"] is base
    assert coordinator.routing_counts == before
    serialized = json.dumps(await coordinator.snapshot())
    assert "SECRET_KEY_91" not in serialized and "X-Secret" not in serialized


async def test_runner_resume_reuses_counts_without_rerouting_old_children(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = AgentCoordinator()
    await source.register("root", "root", None)
    await source.register("old", "old", "root", routing=BINDING)
    source.routing_counts = {Tier.WORKER: 0, Tier.SPECIALIST: 2}
    (tmp_path / "agents.json").write_text(json.dumps(await source.snapshot()))
    (tmp_path / "agents.db").touch()
    respawns: list[dict[str, Any]] = []

    async def respawn(**kwargs: Any) -> None:
        respawns.append(kwargs)
        assert kwargs["coordinator"].routing_counts == source.routing_counts

    monkeypatch.setattr(runner, "respawn_subagents", respawn)
    requests, _clients = mock_jev_http(
        monkeypatch, probs={"worker": 0.05, "specialist": 0.05, "expert": 0.9}
    )
    restored = AgentCoordinator()
    result = await run_spawn(
        monkeypatch,
        tmp_path,
        enabled=True,
        jev=True,
        skills=["business_logic"],
        coordinator=restored,
    )
    assert len(respawns) == 1 and len(requests) == 1
    assert result["children"][0]["routing"]["tier"] == "worker"
    assert restored.routing_counts == {Tier.WORKER: 1, Tier.SPECIALIST: 2}
    assert (
        json.loads((tmp_path / "agents.json").read_text())["routing"]["counts"]["specialist"] == 2
    )


async def test_runner_preflights_bindings_before_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_engine_scaffold(monkeypatch, tmp_path, {})
    source = AgentCoordinator()
    await source.register("root", "root", None)
    await source.register("valid", "valid", "root", routing=BINDING)
    await source.register(
        "invalid", "invalid", "root", routing=dict(BINDING, model="openai/changed")
    )
    (tmp_path / "agents.json").write_text(json.dumps(await source.snapshot()))
    (tmp_path / "agents.db").touch()
    monkeypatch.setattr(runner, "load_settings", commandcode_settings)

    def forbidden(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("sandbox started before routing preflight")

    monkeypatch.setattr(runner.session_manager, "create_or_reuse", forbidden)
    with pytest.raises(RuntimeError, match="routing binding model"):
        await runner.run_strix_scan(scan_config={"targets": []}, scan_id="resume", image="img")
