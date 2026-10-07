from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from strix.config import loader
from strix.config.settings import RoutingSettings


def test_routing_defaults_disabled() -> None:
    s = RoutingSettings()
    assert not {"expert_model", "expert_threshold", "expert_cap"} & set(
        RoutingSettings.model_fields
    )
    assert not s.enabled and not s.jev_enabled
    assert s.specialist_model is None
    assert s.specialist_threshold == 0.65
    assert (s.specialist_cap, s.jev_timeout_s) == (0.25, 5)


@pytest.mark.parametrize("field", ["specialist_cap"])
@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_caps_reject_invalid_values(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        RoutingSettings(**{field: value})


@pytest.mark.parametrize("field", ["specialist_threshold"])
@pytest.mark.parametrize("value", [0, -0.1, 1.1, float("nan"), float("inf")])
def test_thresholds_reject_invalid_values(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        RoutingSettings(**{field: value})


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_timeout_rejects_invalid_values(value: float) -> None:
    with pytest.raises(ValidationError):
        RoutingSettings(jev_timeout_s=value)


@pytest.mark.parametrize("field", ["specialist_model"])
def test_blank_model_becomes_none(field: str) -> None:
    assert getattr(RoutingSettings(**{field: "  "}), field) is None
    assert getattr(RoutingSettings(**{field: " openai/spec "}), field) == "openai/spec"


def test_routing_json_env_and_persistence(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:

    for field in RoutingSettings.model_fields.values():
        monkeypatch.delenv(field.alias, raising=False)
    monkeypatch.setattr(loader, "_cached", None)
    monkeypatch.setattr(loader, "_override", None)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "env": {
                    "STRIX_ROUTING_ENABLED": "true",
                    "STRIX_ROUTING_SPECIALIST_MODEL": "openai/spec",
                }
            }
        )
    )
    loader.apply_config_override(config)
    assert loader.load_settings().routing.enabled is True
    assert loader.load_settings().routing.specialist_model == "openai/spec"
    monkeypatch.setenv("STRIX_ROUTING_SPECIALIST_MODEL", "openai/env")
    monkeypatch.setattr(loader, "_cached", None)
    assert loader.load_settings().routing.specialist_model == "openai/env"
    loader.persist_current()
    stored = json.loads(config.read_text())["env"]
    assert stored["STRIX_ROUTING_SPECIALIST_MODEL"] == "openai/env"
    monkeypatch.delenv("STRIX_ROUTING_SPECIALIST_MODEL")
    monkeypatch.setattr(loader, "_cached", None)
    assert loader.load_settings().routing.specialist_model == "openai/env"
