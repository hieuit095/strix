# Task 03 — Ghi SDK usage bằng model đang chạy

**Phụ thuộc:** 00 (làm theo thứ tự sau 02). **Đọc:** RULES, plan §2.2/3.5/Task 3; ReportUsageHooks.on_llm_end và tests/test_cost_tracking.py.
**Sửa production:** chỉ `strix/core/hooks.py`. **Test:** `tests/test_cost_tracking.py`.
**Interface bàn giao:** hằng `MODEL_KEY="model"`; hook lấy nonempty string từ context hoặc fallback self._model. Không ledger/pricing/report format mới.

## Chu trình A — Tên model

- [ ] Thêm test tự đủ imports sau vào cost test:

```python
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from agents import RunContextWrapper
from agents.usage import Usage
from strix.core.hooks import ReportUsageHooks

async def test_hook_records_actual_child_model() -> None:
    state = MagicMock()
    context = RunContextWrapper(context={
        "agent_id": "child", "model": "openai/xiaomi/mimo-v2.6-pro"})
    response = SimpleNamespace(usage=Usage(requests=1, input_tokens=10,
                                          output_tokens=2, total_tokens=12))
    hook = ReportUsageHooks(model="openai/worker")
    with patch("strix.core.hooks.get_global_report_state", return_value=state):
        await hook.on_llm_end(context, SimpleNamespace(name="child"), response)
    assert state.record_sdk_usage.call_args.kwargs["model"] == "openai/xiaomi/mimo-v2.6-pro"
    assert state.record_sdk_usage.call_args.kwargs["agent_id"] == "child"
    assert state.record_sdk_usage.call_args.kwargs["usage"] is response.usage
    state.record_sdk_usage.assert_called_once()
```

SimpleNamespace chỉ fake response/agent shape theo hook, không fake hook behavior; nếu type checks test yêu cầu cast, dùng fixture SDK thật hoặc cast đúng boundary, không suppress whole file.

- [ ] RED `uv run pytest tests/test_cost_tracking.py::test_hook_records_actual_child_model -q` → actual model vẫn worker.
- [ ] GREEN:

```python
raw_model = ctx.get(MODEL_KEY)
actual_model = raw_model if isinstance(raw_model, str) and raw_model.strip() else self._model
# Giữ agent_id/name/usage/catch/budget code; chỉ đổi model=actual_model.
```

Đặt MODEL_KEY cạnh LLM_TURN_KEY; không normalize model ID hoặc dùng settings main để thay actual.
- [ ] Cùng node xanh.

## Chu trình B — Fallback và guard cũ

- [ ] Parametrize raw_model `None`, `""`, `"   "`, `123`, `{}`; same hook setup, assert worker fallback. Thiếu key riêng là characterization compatibility, ghi đúng loại.
- [ ] Actual usage record một lần; `report_state=None` vẫn no-op; giữ budget exceptions/cost checks nguyên vẹn. Chạy regression budget, không sửa để model change né budget.

```bash
uv run pytest tests/test_cost_tracking.py tests/test_budget_pause_policy.py tests/test_e2e_budget_lifecycle.py tests/test_pricing.py -q
make check-all
```

## Nghiệm thu

- [x] Hooks chỉ thay model lookup + hằng; không đổi money aggregation.
- [x] Typed context value, fallback và once recording đúng.
- [x] Tên model đúng không được gọi là charge/billing chính xác; giới hạn trong plan §3.5 vẫn áp dụng.

## Biên bản hoàn thành

Implementation verified, quality gate baseline chưa đạt; chưa tick hoàn thành toàn task.

- Sửa hooks MODEL_KEY/model lookup duy nhất; thêm tests vào cost_tracking, không ledger/pricing/report format mới.
- RED/GREEN `uv run pytest tests/test_cost_tracking.py::test_hook_records_actual_child_model -q`: exit 1 (worker != MiMo), cùng node exit 0/1 passed.
- Characterization sau fix: invalid/blank/missing context model fallback, once recording, absent report state no-op; không gắn nhãn RED giả.
- `uv run pytest tests/test_cost_tracking.py tests/test_budget_pause_policy.py tests/test_e2e_budget_lifecycle.py tests/test_pricing.py -q`: exit 0, 51 passed, 2 baseline Pydantic warnings.
- Ruff import/format exit 0; `make check-all`: exit 2, Ruff/mypy xanh, 910 Pyright baseline errors; `/tmp/strix-hybrid-task03-check-all.log`.
- Usage model đúng không phải bằng chứng gateway charge chính xác. Không inference/scan thật.

### Kiểm tra gate cuối trên source hiện tại — 06/10/2026

- Full suite source hiện tại được chạy ở Task 07: exit **0**, **2565 passed, 13 skipped, 3 xfailed, 106 warnings**.
- Final full suite: `UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True timeout 500s uv run --offline pytest -q -o faulthandler_timeout=30` → exit **0**, 2565 passed, 13 skipped, 3 xfailed.
- Final required `UV_CACHE_DIR=/tmp/strix-uv-cache timeout 240s make check-all` → exit **0**; Ruff, Mypy (141 files), Pyright, and Bandit passed. Task 03 acceptance is complete; estimated usage remains distinct from billing.
