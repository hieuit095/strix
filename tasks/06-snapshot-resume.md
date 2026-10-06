# Task 06 — Persist binding và counters trong snapshot hiện có

**Phụ thuộc:** 05. **Đọc:** RULES; plan §4.3/Task 5; AgentCoordinator.snapshot/restore/_maybe_snapshot, runner resume path, execution.respawn_subagents.
**Sửa:** `strix/core/{agents,runner,execution}.py`; helper validation nhỏ nếu cần trong **module runconfig đang có**. **Test:** `tests/test_routing_resume.py`, regression coordination/resume hiện có.
**Mục tiêu:** không reroute session, không quota miễn phí sau resume; không persistence framework.

## Quyết định chốt trước viết test

- Child binding là dict runtime Task 05 đã persist. Tier lowercase, model exact Strix ID, base normalized, api_type chat, version=1.
- Coordinator thêm `routing_counts: dict[Tier,int] | None = None`, giữ **tham chiếu trực tiếp governor.counts** trong process. Không copy stale counter sau từng await. Import Tier type trong TYPE_CHECKING; khi restore routing counts cần runtime import cục bộ.
- Snapshot thêm `routing={"version":1,"counts":{"worker":n,"specialist":n,"expert":n}}` chỉ khi counts không None. Disabled/legacy snapshot không thêm field routing. Count int>=0, không bool; đúng ba keys.
- Restore counts một lần, bind governor.counts về dict coordinator; **respawn không admit**. Không JEV/client decision nào cho child cũ.
- Trước respawn bất kỳ child nào, validate **toàn bộ** routed children cùng snapshot; nếu một mismatch không được chạy các child hợp lệ trước rồi mới fail child lỗi.

## Chu trình A — Snapshot round-trip

- [ ] RED test sau (constructor/register binding đã có từ 05):

```python
from strix.core.agents import AgentCoordinator
from strix.routing.types import Tier

async def test_snapshot_preserves_routing_counts() -> None:
    source = AgentCoordinator()
    source.routing_counts = {Tier.WORKER: 4, Tier.SPECIALIST: 2, Tier.EXPERT: 1}
    snap = await source.snapshot()
    assert snap["routing"] == {"version":1, "counts": {
        "worker":4, "specialist":2, "expert":1}}
    restored = AgentCoordinator()
    await restored.restore(snap)
    assert restored.routing_counts == source.routing_counts
```

`uv run pytest tests/test_routing_resume.py::test_snapshot_preserves_routing_counts -q` → KeyError/restore assertion ở current implementation.
- [ ] GREEN snapshot serialize enum names.lower(); restore validate version/counts rồi convert Tier[name.upper()]. Không zero malformed counters âm/unknown; raise RuntimeError có field, không raw secret data.
- [ ] Reference test: `coordinator.routing_counts=g.counts`, call g.admit synchronously, snapshot counts đúng increment mới nhất; không await/copy race. Disabled snapshot không key routing là characterization.
- [ ] Legacy snapshot có routed child metadata nhưng không counters: reconstruct một count/child theo saved tier cho mọi routed child, bao gồm completed/failed, không chỉ runnable; legacy child không binding không tính vào routed share. Ghi warning reconstruction, không gọi đó là exact failed-admission history.

## Chu trình B — Exact model khi respawn

**Helper interface trong runconfig.py:**

```python
def validate_saved_bindings(metadata: dict[str, dict[str, Any]],
    settings: Settings, *, worker_model: str) -> None: ...
```

Chỉ dùng tại preflight resume. Không đặt validator trong generic Session/SQLite layer.

- [ ] RED parameter cases: binding.model khác current tier model; base đổi; api_type đổi; routing disabled nhưng binding có; tier/model/version/key set malformed. Expected RuntimeError(match='routing|binding') trước **zero** child factory/start calls.
- [ ] Model binding/worker override match thì pass; API key thay đổi cùng endpoint/model là pass, snapshot không lưu key nên không compare key. Canonical base remove trailing slash, không coi slash khác là endpoint mới.
- [ ] GREEN validator compare exact tier/model/base/api_type cho từng md.routing, current configured_models uses resolved worker; no gateway substitution. Binding chưa biết version là lỗi actionable, không xử lý như legacy.
- [ ] Test runtime respawn: coordinator có root/child running với saved specialist binding; monkeypatch execution._start_child_runner capture kwargs; factory giả; `respawn_subagents` gọi thật. Assert run_config.model saved specialist, model_provider is base.model_provider, JEV calls=0, counters trước/sau bằng nhau, status/mailbox/history semantics vẫn như legacy.
- [ ] Extend respawn_subagents optional `settings: Settings | None = None`; runner truyền Settings. Metadata legacy dùng base object. Có binding thì require settings và helper RunConfig từ saved model. Không default load_settings trong child loop để config drift.
- [ ] Validation preflight nằm trong runner **ngoài** vòng `respawn_subagents` catch Exception hiện có. Nếu chỉ validate từng child trong vòng catch, mismatch sẽ bị đánh crashed rồi scan tiếp — không đạt plan. Test second-child mismatch, first-child start=0.

## Chu trình C — Không reset governor/counter khi resume

- [ ] Đỏ: saved expert count=1, specialist count=1, worker=0, sau restore request high-impact tiếp theo chỉ specialist (floor) theo caps; g.counts tổng tăng đúng một cho **child mới**, không tăng cho respawn.
- [ ] Runner tạo/bind governor sau restore; không tạo rồi restore ghi counts vào dictionary khác bỏ mất reference. Task 05 counters trước spawn persist nhờ coordinator snapshot hiện có; không format file mới.
- [ ] Stopped/waiting/completed candidates vẫn theo bộ lọc interactive/noninteractive hiện có; không “resume tất cả” để ép test pass.
- [ ] Resume main/root routing snapshot chưa có root binding ở legacy: worker current resolved phải match routed WORKER binding nếu tồn tại; không tự viết lại root model session. Nếu root model snapshot cũ không có thì giữ legacy semantics đã có và ghi giới hạn, không migration engine.
- [ ] Serialized JSON không chứa key giả/headers: assert explicit `SECRET_KEY_91`, `X-Secret` absent; task vốn đã có data trong metadata không được dump vào logs để minh họa error.

## Nghiệm thu

```bash
uv run pytest tests/test_routing_resume.py tests/test_routing_spawn.py tests/test_agent_graph_coordination.py tests/test_telemetry_resume.py tests/test_cli_resume_picker.py tests/test_budget_pause_policy.py -q
make check-all
```

- [x] Binding mismatch fail-fast trước mọi respawn, exact model/no JEV/counters stable.
- [x] Counts snapshot shared reference, valid restore/legacy behavior rõ.
- [x] Không credential/file mới, không thay lifecycle filter/status/mailbox.

## Biên bản hoàn thành

Đã triển khai snapshot routing version/counts, shared governor reference, legacy reconstruction, binding preflight toàn bộ trước sandbox/respawn và RunConfig saved model cho child. Files: core/agents.py, execution.py, runner.py, routing/runconfig.py, tests/test_routing_resume.py. Tier import cục bộ đúng interface task; noqa PLC0415 chỉ ghi nhận yêu cầu lazy import này, không bỏ type/behavior gate.

- RED `uv run pytest tests/test_routing_resume.py -q` exit 1: 15 failures (snapshot thiếu key/counters/validation); GREEN cùng lệnh exit 0, 15 passed.
- RED sau thêm respawn contract: cùng lệnh exit 1, 14 failed/15 passed vì optional settings chưa có; GREEN exit 0, 29 passed. Runtime first-valid/second-invalid chưa start bất kỳ factory nào; exact model/provider/legacy identity và counters giữ nguyên.
- Characterization bổ sung runner resume/preflight, không gọi lại JEV child cũ; new child tăng count một lần và snapshot cập nhật reference. Secret/key/header không vào snapshot.
- RED `uv run pytest tests/test_routing_resume.py::test_legacy_unknown_tier_rejected -q` exit 1, 2 failed/2 passed vì tier list/dict gây TypeError; GREEN exit 0, 4 passed sau guard str.
- Required regression `uv run pytest tests/test_routing_resume.py tests/test_routing_spawn.py tests/test_agent_graph_coordination.py tests/test_telemetry_resume.py tests/test_cli_resume_picker.py tests/test_budget_pause_policy.py -q`: exit 0, **95 passed**.
- `make check-all`: exit 2, Ruff/mypy pass, Pyright **910 baseline errors**, không thêm lỗi routing. Logs `/tmp/strix-hybrid-task06-{counts,bindings,legacy}-red.log`, `/tmp/strix-hybrid-task06-check-all.log`.

Chưa đánh dấu acceptance complete vì check-all baseline chưa đạt. Không module/dependency/tool signature/prompt mới ngoài phạm vi task; legacy lifecycle filter giữ nguyên.

### Kiểm tra gate cuối trên source hiện tại — 06/10/2026

- Full suite source hiện tại được chạy ở Task 07: exit **0**, **2565 passed, 13 skipped, 3 xfailed, 106 warnings**.
- Final full suite: `UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True timeout 500s uv run --offline pytest -q -o faulthandler_timeout=30` → exit **0**, 2565 passed, 13 skipped, 3 xfailed.
- Final required `UV_CACHE_DIR=/tmp/strix-uv-cache timeout 240s make check-all` → exit **0**; Ruff, Mypy (141 files), Pyright, and Bandit passed. Task 06 acceptance is complete; see Task 07 for aggregate evidence.
