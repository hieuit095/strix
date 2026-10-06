# Task 05 — Nối routing tại spawn, giữ lifecycle Strix

**Phụ thuộc:** 01–04. **Đọc:** RULES, plan Task 5; runner.run_strix_scan, execution.spawn_child_agent/_start_child_runner, agents.register, create_agent tool; tests/test_runner_root_prompt.py helper `_patch_engine_scaffold`, budget tests.
**Sửa:** `strix/core/runner.py`, `execution.py`, `agents.py`. **Test mới:** `tests/test_routing_spawn.py`. Test scaffold cũ chỉ thêm RoutingSettings default khi cần, giữ mọi assertion.
**Bàn giao:** root/child model context, optional runtime binding, client lifecycle và guards. Resume chưa release cho đến 06.

## Runtime interface cần mở rộng

```python
# Optional keyword ở execution.spawn_child_agent và AgentCoordinator.register:
routing: dict[str, Any] | None = None
# Metadata key chỉ thêm khi routing != None:
metadata[child_id]["routing"] = dict(routing)
```

Không đổi decorated create_agent signature hoặc factory API. Binding lưu `version`, `tier` lowercase, `model`, normalized `api_base`, `api_type="chat_completions"`; không task/key/headers. Helper build dict là expression local runner, không module thứ ba.

## Test scaffold cụ thể

- [ ] Tạo tests dùng `_patch_engine_scaffold` pattern sẵn có: patch run_dir/state/logging/hydration/sandbox/factory/session/run_agent_loop; không Docker/network. Có thể dùng lại helper từ module test theo pytest import path, hoặc chuyển helper duy nhất sang fixture test-local dùng cho nhiều test; không copy toàn bộ runner.
- [ ] Sau setup scaffold, thay `runner.load_settings` bằng Settings thật với main CommandCode/key giả/Chat và RoutingSettings. Mock `configure_sdk_model_defaults`, `configure_sdk_api_route` để không chạm process defaults; do scaffold đã fake make_model_settings, test settings thật của helper thuộc 02.
- [ ] Fake root loop nhận **kwargs, lưu `kwargs['run_config']`, `kwargs['context']`; gọi `context['spawn_child_agent'](parent_ctx=context, name='probe', task='synthetic', skills=['rce'], parent_history=[{'role':'user','content':'background'}])`. Return None.
- [ ] Fake `runner.start_child_agent` chỉ capture kwargs và return `{'success':True,'agent_id':'child'}`; dùng test execution riêng để kiểm binding/register và child context, không mock chính runner closure.

## Chu trình A — Disabled là characterization

- [ ] Settings.routing.enabled=False; fake router/client constructors nếu được gọi raise AssertionError. Spawner capture phải có `run_config is root_run_config`, đúng task/skills/parent_ctx/history; không routing binding keyword có giá trị.
- [ ] `uv run pytest tests/test_routing_spawn.py::test_disabled_keeps_original_runconfig -q`. Xanh trước implementation hợp lệ; ghi characterization. Nếu đỏ do fake Settings thiếu routing, cập nhật scaffold default, không sửa behavior tests.

## Chu trình B — Enabled model selection/root override

- [ ] Đỏ `test_enabled_routes_specialist_preserving_spawn_arguments`: fake DecisionClient trả DecisionResult(.1,.8,.1,10,1), capture child model MiMo, root giữ resolved main, provider same object, factory/skills/history/event_sink/hooks/max_turns/interactive như đường cũ.
- [ ] Đỏ `test_root_model_argument_wins`: gọi `run_strix_scan(model='openai/override',...)`, capture root/binding worker đúng override; tier mapping không đọc Settings.llm.model đè override.
- [ ] RED bằng node names trên; hiện mọi child dùng worker nên đúng assertion model đỏ.
- [ ] GREEN: validate_routing_config trước sandbox; configured_models từ resolved_model; router/governor tạo once/scan. Nhánh enabled closure:

```python
# Guard lifecycle trước request, nằm ngoài route() try/except.
# mapping/router đã được tạo một lần trong run_strix_scan.
decision = await router.route(Envelope(task=kwargs["task"],
                                       skills=tuple(kwargs["skills"])))
# Guard lifecycle lần nữa sau usage JEV, trước spawn.
child_config = run_config_for_model(run_config, tier_models[decision.tier], settings)
# await start_child_agent giữ toàn bộ args cũ, chỉ run_config/binding khác.
```

- [ ] Không gọi JEV plain task; enabled JEV false → no HTTP client, router client=None, high-impact floor specialist. Nested parent có specialist MODEL_KEY nhưng task mới plain vẫn worker.
- [ ] ROOT context MODEL_KEY=resolved_model. Execution `_start_child_runner` đặt MODEL_KEY từ own RunConfig string sau `dict(parent_ctx)`; không thay counters/hooks/task/history khác.

## Chu trình C — Binding tồn tại trước child chạy

- [ ] Test execution spawn thật với fake factory và monkeypatch `_start_child_runner`; trong fake start đọc coordinator.metadata[child_id]['routing'] và assert đúng binding. Trước thay đổi metadata chưa có nên RED.
- [ ] Dùng test thực thi runtime sau cho chu trình register/start; không cần Docker/session thật vì fake đúng boundary start runner:

```python
from typing import Any
from pathlib import Path
import pytest
from agents import RunConfig
from strix.core import execution
from strix.core.agents import AgentCoordinator

async def test_binding_exists_before_child_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = AgentCoordinator()
    await coordinator.register("root", "root", None)
    binding = {"version": 1, "tier": "specialist",
        "model": "openai/xiaomi/mimo-v2.6-pro",
        "api_base": "https://api.commandcode.ai/provider/v1",
        "api_type": "chat_completions"}
    started: list[str] = []
    async def fake_start(**kwargs: Any) -> None:
        child_id = kwargs["child_id"]
        assert coordinator.metadata[child_id]["routing"] == binding
        started.append(child_id)
    monkeypatch.setattr(execution, "_start_child_runner", fake_start)
    result = await execution.spawn_child_agent(
        coordinator=coordinator, factory=lambda **_kwargs: object(),
        agents_db_path=tmp_path / "agents.db", sessions_to_close=[],
        run_config=RunConfig(model=binding["model"]), max_turns=50,
        interactive=False, parent_ctx={"agent_id": "root"},
        name="probe", task="synthetic", skills=["rce"], parent_history=[],
        routing=binding)
    assert result["success"] is True
    assert started == [result["agent_id"]]
```

Chạy `uv run pytest tests/test_routing_spawn.py::test_binding_exists_before_child_start -q` → trước khi mở runtime API phải đỏ vì keyword routing chưa được chấp nhận, sau đó phải xanh; nếu metadata được thêm quá muộn sẽ đỏ tại fake_start assertion.
- [ ] Extend optional runtime keyword, forward vào register; metadata thêm trong lock trước `_maybe_snapshot` và trước start. Không write metadata sau detached task chạy.
- [ ] Test `_start_child_runner` với fake run_agent_loop capture context: parent model worker, child config MiMo → child MODEL_KEY MiMo, parent context giữ worker. Tận dụng session fixture của budget tests; await task/cleanup để không orphan task.

## Chu trình D — Budget guards và lifecycle JEV

Không gọi `on_llm_start` để guard routing: hàm này tăng turn và chèn lời nhắc, làm thay đổi hành vi. Dùng logic/exception đang có, không sửa threshold/policy.

- [ ] Các case trước route: coordinator.budget_stopped→BudgetExceededError; reserve_stopped→SubagentBudgetReservedError; budget_paused→BudgetPausedError(resume_epoch); recomputed_budget_flags theo current cost/hook max_budget và policy. No client request/no start khi guard chặn.
- [ ] Sau JEV on_usage, recompute cost flags trước spawn. Pause-policy cost>=limit → BudgetPausedError, không fallback thành model khác; stop/reserve dùng thresholds helper hiện có. Exception chạy ngoài router generic catch.
- [ ] Tests fake ledger tăng cost trong JEV callback: request một lần, child start 0; hiện không có routing guard nên RED. Chạy riêng từng budget policy case, dùng APIs pause/resume/coordinator hiện có để dựng trạng thái.
- [ ] Không thay decorated create_agent catch hiện có để router “đẹp hơn”: direct spawner bảo đảm không inference thêm, tool có thể báo spawn error như trước; hook/lifecycle loop quản lý pause. Giữ test tool error contract.
- [ ] Runner callback chuyển Usage vào report_state.record_sdk_usage với agent_id/name='routing', model='typesafe/jev'; không call guard từ callback. Cost có giới hạn estimator, không fake charge.
- [ ] HTTP client chỉ tạo khi enabled+jev_enabled; close trong finally trên success, upstream error, CancelledError và setup failure. Client creation nằm trong try/finally được bảo vệ; không tạo ở startup rồi có đường raise không close.
- [ ] Counter admission once/task, callback once/HTTP response; không tạo client/router cho mỗi spawn. Decision log logger hiện có chỉ model/tier/reason, không task/key/payload.

## Nghiệm thu

```bash
uv run pytest tests/test_routing_spawn.py tests/test_agent_graph_coordination.py tests/test_runner_root_prompt.py tests/test_budget_pause_policy.py tests/test_e2e_budget_lifecycle.py tests/test_agent_tool_registration.py -q
make check-all
```

- [ ] Root/settings/tools/prompts/history/agent creation không bị giảm.
- [ ] Disabled identity/no I/O; enabled routes đúng; usage/context đúng.
- [ ] Guards trước và sau JEV, exception không bị generic catch nuốt.
- [ ] Client closed mọi exit; chưa tuyên bố resume đúng khi 06 chưa xong.

## Biên bản hoàn thành

Đã triển khai routing once/spawn tại runner, optional binding trước start tại execution/coordinator, MODEL_KEY riêng của child và guards trước/sau JEV. Client chỉ tạo enabled+JEV, close trong finally cả setup error/cancellation. Năm scaffold runner cũ chỉ thêm RoutingSettings mặc định; assertion giữ nguyên.

RED thật: model selection/root binding/child context và binding-before-start thất bại trước implementation; JEV selection và budget-after/budget-before thất bại đúng assertion. Logs `/tmp/strix-hybrid-task05-jev-red.log`, `...-budget-after-red.log`, `...-budget-before-red.log`. Sau implementation cùng node xanh (exit 0). Bổ sung characterization nested parent→worker, ambiguous→specialist, current-cost stop/reserve/pause và after-JEV reserve.

Nghiệm thu: `uv run pytest tests/test_routing_spawn.py tests/test_agent_graph_coordination.py tests/test_runner_root_prompt.py tests/test_budget_pause_policy.py tests/test_e2e_budget_lifecycle.py tests/test_agent_tool_registration.py -q` exit **0**, **76 passed**. `make check-all` exit **2**, Ruff/mypy pass, Pyright vẫn **910 baseline errors** (không lỗi mới), log `/tmp/strix-hybrid-task05-check-all.log`. Vì gate quality chưa đạt, chưa đánh dấu task hoàn thành. Tiếp tục 06 theo yêu cầu tuần tự; resume chưa được tuyên bố verified tại task này.

### Kiểm tra gate cuối trên source hiện tại — 06/10/2026

- Full suite source hiện tại được chạy ở Task 07: exit **0**, **2565 passed, 13 skipped, 3 xfailed, 106 warnings**.
- Required `UV_CACHE_DIR=/tmp/strix-uv-cache timeout 240s make check-all` trên source hiện tại → exit **2**; Ruff/Mypy pass, Pyright còn 3 `reportImportCycles` trong MCP client/session/registry. Vì task này yêu cầu gate tổng xanh, Task 05 vẫn **chưa accepted**; xem Task 07 để command/log đầy đủ.
