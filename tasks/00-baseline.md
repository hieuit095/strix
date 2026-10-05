# Task 00 — Baseline và bảo vệ công việc sẵn có

**Phụ thuộc:** không. **Đọc bắt buộc:** [RULES](RULES.md), plan §1–2, AGENTS.md, pyproject.toml, Makefile.
**Mục tiêu:** xác định trạng thái repo/test thật trước thay đổi. **Sửa:** chỉ biên bản ở cuối task khi đã chạy; không production/test code.
**Bàn giao:** lệnh baseline, failures sẵn có, diff/untracked cần giữ để Task 01 biết điểm xuất phát.

## Bước 1 — Xác nhận workspace

- [x] Chạy từng lệnh, không sửa repo giữa hai lệnh:

```bash
pwd
git rev-parse --short HEAD
git status --short
uv --version
uv run python --version
```

Kỳ vọng cwd là repo Strix; Python >=3.12. Ghi HEAD thật, không mặc định luôn là snapshot `55bc079`. Routing files/test hiện có không được xóa nếu untracked. Nếu thiếu uv/deps, xác định theo Makefile; chỉ `make dev-install` khi cần, không nâng dependencies ngoài lock.

## Bước 2 — Đọc seam thật

- [x] Dùng `rg -n` tìm tên hàm, không dựa số dòng cũ:

```bash
rg -n 'RunConfig\(|spawn_child_agent|respawn_subagents|make_model_settings' strix/core/runner.py strix/core/execution.py strix/core/inputs.py
rg -n 'on_llm_end|record_sdk_usage|async def register|async def snapshot|async def restore' strix/core/hooks.py strix/core/agents.py
```

Ghi bốn câu trả lời: nơi tạo RunConfig; nơi clone child context; nơi metadata persist; nơi usage nhận tên model. Đọc đầy đủ hàm tương ứng, không sửa.

## Bước 3 — Chạy baseline theo thứ tự

- [x] Routing:

```bash
uv run pytest tests/test_routing_types.py tests/test_routing_policy.py tests/test_routing_governor.py tests/test_routing_router.py -q
```

Snapshot plan có 26 pass, nhưng ghi số thật. Test xanh không khẳng định governor đúng ba lượt RCE; Task 01 sẽ thêm regression.

- [x] Quality gates:

```bash
make check-all
uv run pytest -q
```

Chạy hai lệnh riêng để nếu check-all đỏ vẫn biết baseline tests. Không dùng `-k` để bỏ case khó. Nếu lỗi hạ tầng, ghi exception/dependency/cổng thiếu và lệnh tái hiện. Không sửa lỗi không liên quan chỉ để tạo baseline xanh.

## Nghiệm thu

- [x] Có trạng thái HEAD/worktree và version thật.
- [x] Có số passed/failed/skipped, warnings và exit code thật của từng lệnh.
- [x] Mọi failure được phân biệt code baseline/hạ tầng; downstream biết task nào bị ảnh hưởng.
- [x] Không thay production, dependency, prompt, tool hoặc dữ liệu scan.

**TDD:** đây là task khảo sát, không có tính năng mới nên không ép đỏ/xanh.

## Biên bản hoàn thành

Hoàn tất khảo sát ngày 06/10/2026 trên `feat/hybrid-router`, HEAD ban đầu `55bc079`.

- Workspace `/home/hieuit095/strix`; giữ toàn bộ plan/tasks, năm module routing và bốn test untracked ban đầu. Không đổi nhánh.
- `pwd`, `git rev-parse --short HEAD`, `git status --short`, `uv --version`, `uv run python --version`: exit 0; uv 0.12.23, Python 3.14.4.
- Seam đã đọc: RunConfig tại runner.run_strix_scan; child context clone tại execution._start_child_runner; metadata tại AgentCoordinator.register/snapshot/restore; usage model tại ReportUsageHooks.on_llm_end hiện dùng self._model.
- `uv run pytest tests/test_routing_types.py tests/test_routing_policy.py tests/test_routing_governor.py tests/test_routing_router.py -q`: exit 0, 26 passed.
- `make check-all`: exit 2; Ruff format/check và mypy xanh, Pyright 910 errors/59 files ở baseline, nên Make không chạy Bandit. Không coi gate này xanh.
- `uv run pyright strix/ --outputjson`: exit 1; diagnostic baseline cục bộ `/tmp/strix-hybrid-pyright-baseline.json` để so với diff sau.
- `uv run bandit -r strix/ -c pyproject.toml`: exit 0, no issues; warnings nosec hiện có.
- `uv run pytest -q`: exit 0; 2355 passed, 3 xfailed có sẵn, 106 warnings (Pydantic/LiteLLM), 384.37s. Không thêm skip/xfail.
- Đây là characterization/khảo sát, không TDD đỏ/xanh; chưa sửa production/test/dependency/prompt/tool.

Task 00 hoàn thành: đã xác định baseline. Gate check-all cho các task implementation vẫn đỏ; phải xử lý/ghi riêng, không coi baseline đỏ là nghiệm thu code mới.
