# Task 02 — Settings và clone RunConfig bằng kết nối sẵn có

**Phụ thuộc:** 01. **Đọc:** RULES, plan §3.2/4.2/4.3; settings/loader, runner đoạn tạo RunConfig, inputs.make_model_settings, models.StrixProvider/tool flags.
**Sửa:** `strix/config/settings.py`, `__init__.py`. **Tạo production:** chỉ `strix/routing/runconfig.py`.
**Test:** `tests/test_routing_settings.py`, `tests/test_routing_runconfig.py`; dùng regression config/models/header hiện có.

## Interface bàn giao (đặt hết trong module mới duy nhất)

```python
def run_config_for_model(base: RunConfig, model_name: str, settings: Settings) -> RunConfig: ...
def configured_models(settings: Settings, *, worker_model: str) -> dict[Tier, str]: ...
def validate_routing_config(settings: Settings, *, worker_model: str) -> None: ...
```

`configured_models` trả tên model string, không thêm TierModel/registry. Disabled returns worker-only; enabled require specialist qua validator. Worker name là resolved argument, không đọc settings.llm.model đè override.

## Chu trình A — Settings defaults/env/JSON

- [x] RED đầu tiên, import RoutingSettings chưa có:

```python
from strix.config.settings import RoutingSettings

def test_routing_defaults_disabled() -> None:
    s = RoutingSettings()
    assert not s.enabled and not s.jev_enabled
    assert s.specialist_model is None and s.expert_model is None
    assert (s.specialist_threshold, s.expert_threshold) == (0.65, 0.65)
    assert (s.specialist_cap, s.expert_cap, s.jev_timeout_s) == (0.25, 0.05, 5)
```

Chạy `uv run pytest tests/test_routing_settings.py::test_routing_defaults_disabled -q` → ImportError đúng interface thiếu.

- [x] GREEN thêm submodel: `_BASE_CONFIG`, fields/aliases đúng bảng plan §4.2, `Settings.routing=Field(default_factory=RoutingSettings)`, export. Không thêm field key/base/header.
- [x] Mỗi nhóm input thêm parametrized RED: cap -0.1/1.1/NaN/Infinity; threshold 0/-0.1/1.1/NaN; timeout 0/-1/NaN; specialist/expert whitespace→None. Pydantic Field constraints cộng `allow_inf_nan=False` hoặc validator số hữu hạn; không dùng assertion validation runtime.
- [x] JSON loader test theo pattern `_reset_loader_state` trong test_config_loader.py: monkeypatch loader._cached/_override, clear aliases, ghi tmp JSON `{"env":{"STRIX_ROUTING_ENABLED":"true","STRIX_ROUTING_SPECIALIST_MODEL":"openai/spec"}}`, `apply_config_override`, assert true/spec; setenv specialist=`openai/env`, invalidate cache rồi assert env wins. Test persist_current round-trip với routing aliases; không sửa loader production.

## Chu trình B — Identity và model settings

- [x] Test tối thiểu trước implementation:

```python
from agents import RunConfig
from strix.config.settings import Settings
from strix.routing.runconfig import run_config_for_model

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
```

RED từng node → ModuleNotFoundError/interface thiếu hoặc identity assertion. GREEN bằng implementation trực tiếp:

```python
if model_name == base.model:
    return base
llm = settings.llm
return dataclasses.replace(base, model=model_name,
    model_settings=make_model_settings(llm.reasoning_effort,
        model_name=model_name,
        force_required_tool_choice=llm.force_required_tool_choice,
        request_timeout=llm.timeout, prompt_cache=llm.prompt_cache,
        extra_headers=llm.extra_headers))
```

- [x] Spy `make_model_settings` tại module runconfig, return sentinel ModelSettings, assert đủ kwargs ở block trên. Dùng Settings với timeout/header/prompt_cache/required khác default để test phát hiện bỏ qua lựa chọn; không chỉ test defaults.

## Chu trình C — Validate và availability

- [x] Tạo fixture Settings main đúng CommandCode, API chat, specialist/expert như plan bằng direct nested constructors. Test `configured_models(...worker_model="openai/override")` WORKER đúng override, specialist/expert đúng; không expert thì chỉ hai tiers.
- [x] RED parametrized validator với expected match field: enabled thiếu specialist; wrong base; api_type=None/responses; model không native openai/; header ZDR=1 + jev_enabled=True. Disabled phải không đọc credential/catalog/HTTP, dù main đang dùng provider khác hợp lệ.
- [x] GREEN: validate enabled only; canonical base so bằng `rstrip('/')`; cần key main nonempty khi JEV bật. `x-cmd-zdr` so case-insensitive, giá trị `1` thì reject JEV. Không sửa cấu hình người dùng để pass.
- [x] Validate every tier/tool flags against resolved worker. Reject unknown/mixed wire trước sandbox; error chỉ field/model, không key/headers. API capabilities helper là guard nội bộ, không chứng minh live contract.

## Chu trình D — Wire native SDK thật qua fake HTTP

- [x] Parametrize ba Strix model IDs và wire IDs theo plan §3.2. Dùng `StrixProvider(api_key="dummy", base_url=canonical)` để tránh môi trường thật; unwrap `_inner` như tests hiện có, assert native Chat type. Inject `_client=AsyncOpenAI(api_key="dummy",base_url=canonical,http_client=httpx.AsyncClient(transport=MockTransport(handler)))` ở inner model trong test; không đổi production provider.
- [x] Handler capture URL/header/JSON rồi trả Chat response tổng hợp: `id="chatcmpl-test"`, object/chat.completion, created=0, model=wire, choices assistant text, finish_reason=stop, usage prompt=10/completion=1/total=11. Gọi get_response với `ModelTracing.DISABLED`, tools=[], input="synthetic", ModelSettings; assert wire ID không còn prefix route, URL Chat đúng, bearer dummy.
- [x] Assert request headers/timeouts/model settings riêng bằng tests helper; test mocks không thể xác nhận reasoning/strict upstream. Close test HTTP clients bằng async context manager.

## Nghiệm thu

```bash
uv run pytest tests/test_routing_settings.py tests/test_routing_runconfig.py tests/test_config_loader.py tests/test_models.py tests/test_llm_extra_headers.py -q
make check-all
```

- [x] Identity/provider/main override/settings đúng; aliases env/JSON/persist đủ.
- [x] Chỉ một module mới, không đổi loader/provider/dedupe/compaction.

## Biên bản hoàn thành

Historical interim status; acceptance was later completed after the required current-source regression and `make check-all` passed. See final evidence reconciliation below.

- Sửa settings/export; thêm duy nhất production `strix/routing/runconfig.py`; tests routing_settings/runconfig. Loader/provider/dedupe/compaction không đổi.
- RED/GREEN `uv run pytest tests/test_routing_settings.py::test_routing_defaults_disabled -q`: exit 4 ImportError RoutingSettings → exit 0/1 passed.
- RED/GREEN từng command cùng prefix, nodes `test_caps_reject_invalid_values`, `test_thresholds_reject_invalid_values`, `test_timeout_rejects_invalid_values`, `test_blank_model_becomes_none`: exit 1 (8/10/4/2 failed, không reject/strip) → exit 0 (8/10/4/2 passed).
- RED/GREEN `uv run pytest tests/test_routing_runconfig.py::<node> -q`, nodes worker_preserves_runconfig_identity/specialist_preserves_provider_and_base (prefix test_): exit 4 ModuleNotFoundError → exit 0/1 passed mỗi node.
- RED/GREEN nodes `test_configured_models_use_resolved_worker_and_optional_expert`, `test_invalid_routing_config_rejected`: exit 1 ImportError interface → exit 0/1 và 8 passed.
- Characterization: đủ sáu LLM options qua builder, JSON/env/persist, disabled không đọc connection, trailing slash/ZDR floor-only, strict flag mismatch và native SDK wire ba IDs. Test scaffold đã sửa field RunConfig không tồn tại và bổ sung required wrapper kwargs; không gọi đó là RED hành vi.
- `uv run pytest tests/test_routing_settings.py tests/test_routing_runconfig.py tests/test_config_loader.py tests/test_models.py tests/test_llm_extra_headers.py -q`: exit 0, 111 passed.
- Ruff format/check exit 0 sau sửa import/with formatting; `make check-all`: exit 2, Ruff/mypy xanh, 910 Pyright baseline errors (không routing errors); `/tmp/strix-hybrid-task02-check-all.log`.
- Fake key + MockTransport, không inference/network/Docker thật. Chưa live verified, chưa thay tool flags/settings để pass upstream.

### Kiểm tra gate cuối trên source hiện tại — 06/10/2026

- Full suite source hiện tại được chạy ở Task 07: exit **0**, **2565 passed, 13 skipped, 3 xfailed, 106 warnings**.
- Final full suite: `UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True timeout 500s uv run --offline pytest -q -o faulthandler_timeout=30` → exit **0**, 2565 passed, 13 skipped, 3 xfailed.
- Final required `UV_CACHE_DIR=/tmp/strix-uv-cache timeout 240s make check-all` → exit **0**; Ruff, Mypy (141 files), Pyright, and Bandit passed. Task 02 acceptance is complete; see Task 07 for aggregate evidence.

### Checklist evidence reconciliation — 2026-10-07

Cycle A settings/default/validation/loader items map to the RED/GREEN node results above (test_routing_defaults_disabled, caps, thresholds, timeout, blank model, JSON/env/persist characterization); exact test-node commands and results are listed in the implementation record. Cycle B model identity/settings items map to uv run pytest tests/test_routing_runconfig.py::<node> -q RED/GREEN results and the six-option spy characterization. Cycle C validator/availability items map to the test_configured_models_use_resolved_worker_and_optional_expert and test_invalid_routing_config_rejected RED/GREEN cases. Cycle D native SDK wire items use fake HTTP only; the exact three-model wire/request contract is offline evidence, not live upstream proof. The task regression command above exited 0 with 111 passed; final current-source suite/check-all are recorded in Task 07. Previous “gate incomplete” text is historical and superseded by the final gates.
