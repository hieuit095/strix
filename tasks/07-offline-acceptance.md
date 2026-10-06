# Task 07 — Nghiệm thu offline và hướng dẫn người dùng

**Phụ thuộc:** 00–06. **Đọc:** RULES, toàn bộ biên bản 00–06, plan §1/§6/§7.
**Tạo docs:** `docs/routing/README.md`. **Test:** bổ sung case còn thiếu vào các test routing đã tạo; `tests/test_routing_live.py` ở Task 08.
**Production:** không task tính năng mới. Nếu phát hiện regression, quay task sở hữu để thêm RED/sửa/GREEN; không mở module/feature mới ở task nghiệm thu.

## Chu trình A — Kiểm chứng giữ nguyên sức mạnh

- [x] Parametrize `scan_mode` quick/standard/deep, interactive true/false trên scaffold spawn Task 05. Capture make_child_factory/build_strix_agent args cùng scenario routing off/on, assert equality của scan_mode, skills, is_whitebox, is_diff_scoped, interactive, system_prompt_context, chat_completions_tools, strict_tool_schemas. Chỉ RunConfig model/settings được phép khác.
- [x] Không mock prompt rồi assert prompt giả bằng nhau. Dựng hai agent factory thật cùng inputs, compare instructions/tool names/schema/capabilities trước và sau sử dụng helper RunConfig; giữ bộ tools thực tế của fixture. Tham khảo tests/test_agent_tool_registration.py và test_agent_factory_tool_arguments.py.
- [x] Child history/inherit_context, event_sink/hooks/max_turns vẫn forwarded; budget tests stop/pause/reserve và tool failure contracts vẫn pass. Tests đang có xanh là characterization; case chưa có phải RED đúng bug nếu phát hiện.
- [x] Test error JEV không làm mất nhiệm vụ/skills: child fallback đúng hard floor với nguyên task/history, không có lệnh dừng nhánh hoặc prompt tiết kiệm.
- [x] Compaction theo same gateway/credentials/model child trong scope v1; chạy compaction regression hiện có. Không thêm provider riêng để rồi “sửa compaction” theo phạm vi không được yêu cầu.

## Bước B — Viết README dùng được

- [x] Tạo `docs/routing/README.md` với nội dung cụ thể sau (dùng snapshot ngày, không đổi giá thành sự thật vĩnh viễn):

1. Router chỉ chọn model child một lần, root/model override giữ nguyên; không cắt tools/turns/coverage.
2. Bảng chín routing env aliases/defaults/constraints **giống plan §4.2**; LLM_API_KEY/BASE/API_TYPE dùng chung, không thêm tier credentials.
3. Model prefix/wire IDs ở plan §3.2; ví dụ cấu hình floor-only §6; cách bật JEV explicit true và tắt routing cho scan mới.
4. JEV chỉ metadata allowlist, không ZDR; policy mandatory ZDR giữ JEV off. Không gỡ header tự động.
5. Required specialist/optional expert, hard floor/soft share cap và exception fallback. Cap không phải %tiền.
6. Resume yêu cầu saved model/base/API cùng binding, đổi key được phép; snapshot legacy giữ đường cũ. Không tắt routing để đổi model session cũ.
7. Usage/model đúng nhưng money là estimator/agent token allocation; giá model mới/summary charge còn giới hạn. Đối chiếu dashboard trước billing claim.
8. Offline tests/opt-in live commands của Task 08 và gates target/account/policy; rollback không mua credits/deploy.

Không tạo module telemetry, dashboard hoặc phụ lục calibration framework. Link docs chính thức từ plan, không copy toàn bộ API docs.

## Bước C — Full verification và scope audit

- [x] Chạy:

```bash
make check-all
uv run pytest -q
git diff --stat
git status --short
```

Ghi exit codes/số tests thật. `git diff` không hiển thị untracked: mở/check cả các module/test mới bằng `rg --files strix/routing tests` và status; không lấy diff rỗng làm bằng chứng không thay code.

- [x] Đối chiếu routing production chỉ hai file mới runconfig.py/jev.py ngoài lõi sẵn có. Không dependencies/lock/agent prompts/tool signatures đổi; test scaffolds được cập nhật đủ defaults nhưng assertion không hạ.
- [x] DoD plan §7 ánh xạ qua tasks/README coverage table; mỗi yêu cầu offline có test/command đã chạy. Ticked checkbox không thay bằng chứng.
- [x] Baseline failures Task 00: nếu còn unresolved ảnh hưởng tính năng/gate required thì task chưa complete; không nói “full suite xanh trừ các test đỏ”. Chỉ báo riêng lỗi và phạm vi thực đã kiểm chứng.
- [x] Inspect logs/snapshot tmp test không có dummy secrets/raw task trong routing logs; logger errors safe class names, client closed.

## Nghiệm thu

- [ ] Full offline/check-all pass ở diff cuối cùng; chỉ broaden/repeat nếu có sửa mới hoặc failure.
- [x] README đủ dùng và khớp actual aliases/signatures, không quảng cáo billing/quality chưa đo.
- [x] Preserve-functionality assertions và no-scope-creep diff hoàn tất.
- [ ] Đánh dấu bàn giao là **offline verified, live chưa verified** cho đến 08.

## Biên bản hoàn thành

Đã hoàn tất phần implementation/documentation và các kiểm chứng độc lập. Acceptance toàn task **chưa đạt**; không tick full check-all/live.

- Files: `strix/routing/jev.py`, tests/test_routing_jev.py, test_routing_runconfig.py, test_routing_spawn.py, docs/routing/README.md; biên bản task 04 ghi regression đúng task sở hữu.
- Task 04 RED malformed choice list/dict: `uv run pytest tests/test_routing_jev.py::test_malformed_answer_rejected_with_usage -q` exit 1, 2 failed/17 passed (TypeError). Guard string → cùng node exit 0, 19 passed. Resume kiểm cả node fallback: `UV_CACHE_DIR=/tmp/strix-uv-cache uv run --offline pytest tests/test_routing_jev.py::test_malformed_answer_rejected_with_usage tests/test_routing_jev.py::test_non_string_choice_falls_back_safely -q` exit 0, **21 passed**. List/dict → SPECIALIST/jev_error, usage 183 tokens ghi một lần.
- Characterization: routing on/off quick/standard/deep × interactive false/true **6/6**; real factory prompts/tool names/schema/filesystem/shell capabilities **6/6**. Không mock prompt thật. History/task/skills/hooks/event_sink/max_turns/budget forwarding được giữ.
- Trước môi trường bị đổi: `uv run pytest tests/test_routing_runconfig.py tests/test_routing_spawn.py tests/test_compaction.py tests/test_agent_factory_tool_arguments.py -q` exit 0, **116 passed**; JEV/router exit 0, **69 passed**. `uv run pytest -q` exit 0, **2542 passed, 3 existing xfailed, 106 warnings**, 390.23s; `/tmp/strix-hybrid-task07-full-suite.log`.
- Sau resume: `UV_CACHE_DIR=/tmp/strix-uv-cache timeout 45s uv run --offline pytest tests/test_routing_runconfig.py::test_real_agents_keep_prompts_tools_and_capabilities tests/test_routing_spawn.py::test_routing_preserves_scan_and_factory_options tests/test_routing_spawn.py::test_jev_failure_preserves_task_and_history_at_floor tests/test_routing_jev.py tests/test_routing_router.py tests/test_compaction.py tests/test_agent_factory_tool_arguments.py -q` exit 0, **145 passed**; `/tmp/strix-hybrid-task07-targeted-resume.log`.
- `make check-all` trước resume exit 2: Ruff/mypy pass, **910 baseline Pyright errors**. Resume `UV_CACHE_DIR=/tmp/strix-uv-cache make check-all` exit 2: Ruff/mypy pass, **4479 Pyright errors/29 warnings**, gồm missing dependency imports vì môi trường mới không resolve site-packages; chỉ định --pythonpath cũng chưa giải quyết. Không coi 4479 là baseline cũ hoặc routing regression. Log `/tmp/strix-hybrid-task07-check-all-resume.log`. `UV_CACHE_DIR=/tmp/strix-uv-cache uv run --offline bandit -r strix/ -c pyproject.toml` exit 0, no issues.
- Required full-suite rerun đã thử, bị treo ở async thread/session boundary trong sandbox mới và interrupted **exit 130**; không coi đây là pass. Native SDK mock riêng với `timeout 25s ... -o faulthandler_timeout=10` exit **124**, stack event loop chờ selector. Minimal `asyncio.run()` với `asyncio.to_thread()` cũng timeout (executor shutdown/thread wakeup); cần môi trường cho async thread handoff/subprocess discovery hoạt động. `/tmp/strix-native-hang.log`, `/tmp/strix-hybrid-task07-full-suite-resume.log`. Không bỏ/skips/xfail required tests để tạo xanh.
- `git diff --stat`, `git status --short`, `rg --files strix/routing tests` exit 0; chỉ hai production modules mới runconfig/jev ngoài owner core, không dependency/lock/prompts/decorated tool signatures đổi. TDD/alias/usage/privacy/resume mapping giữ tasks/README coverage table. Routing logs/snapshot checks không secret.
- Docs đối chiếu 9 alias/default/constraints với Settings, prefix/wire, shared credentials, floor/cap, metadata/ZDR, resume/rollback, estimator limitations và live prerequisites. Không claim live billing/quality.
- **Commit BLOCKED:** requested `git add ... && git ... commit` exit **128**, `.git/index.lock` read-only theo permission profile mới. Branch vẫn feat/hybrid-router, HEAD 061646b; không push, không đổi branch hoặc bypass restriction.

Gate còn thiếu: Git writable; môi trường test/type discovery hoạt động; baseline Pyright quality failure phải xử lý trước full acceptance. Chưa đánh dấu Task 07 complete. Tiếp tục offline Task 08 theo owner instruction; live quality/rollout vẫn phụ thuộc gates này.

### Kết quả cập nhật 06/10/2026

- JEV parser regression: `UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True uv run --offline pytest tests/test_routing_jev.py -q` → exit **0**, 54 passed.
- Final diff full suite: `UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True timeout 500s uv run --offline pytest -q -o faulthandler_timeout=30` → exit **0**, **2564 passed, 13 skipped, 3 xfailed, 106 warnings**, 382.63s; `/tmp/strix-hybrid-final-fullsuite.log`. The 13 skips are live opt-in cases; 3 xfails are existing suite cases.
- Task 07 routing/preservation plus Task 08 offline harness regression: `UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True timeout 60s uv run --offline pytest tests/test_routing_live.py tests/test_routing_jev.py tests/test_routing_router.py tests/test_routing_spawn.py::test_routing_preserves_scan_and_factory_options tests/test_routing_runconfig.py::test_real_agents_keep_prompts_tools_and_capabilities tests/test_compaction.py tests/test_agent_factory_tool_arguments.py -q` → exit **0**, 162 passed, 13 skipped, 2.91s.
- Final `UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True make check-all` → exit **2**. Ruff format/check and mypy pass; Pyright remains at **910 errors across the same 59 baseline files**, with no `strix/routing` diagnostics. This required gate fails, so Task 07 remains **not accepted**. Task 00 forbids unrelated baseline cleanup; no checks were weakened.
- Git writes are available again. JEV parser fix and test are committed as `605e11c fix(routing): reject malformed JEV choices safely`; no push.

### Kết quả cập nhật 06/10/2026

- `UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True uv run --offline pytest tests/test_routing_jev.py -q` → exit **0**, 54 passed.
- `UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True timeout 500s uv run --offline pytest -q -o faulthandler_timeout=30` → exit **0**, 2562 passed, 13 skipped (live opt-in), 3 xfailed, 106 warnings, 384.47s; log `/tmp/strix-hybrid-task07-fullsuite-traced.log`. This run predates only the Task 08 test-fixture separation below; final full suite must be rerun after that test-only change.
- `UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True timeout 60s uv run --offline pytest tests/test_routing_live.py tests/test_routing_jev.py tests/test_routing_router.py tests/test_routing_spawn.py::test_routing_preserves_scan_and_factory_options tests/test_routing_runconfig.py::test_real_agents_keep_prompts_tools_and_capabilities tests/test_compaction.py tests/test_agent_factory_tool_arguments.py -q` → exit **0**, 162 passed, 13 skipped, 2.91s.
- Final `UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True make check-all` → exit **2**. Ruff format/check and mypy pass; Pyright still reports exactly 910 errors across the same 59 baseline files, with no `strix/routing` diagnostics. Task 07 remains **not accepted** because its required check-all gate is red; Task 00 says not to expand into unrelated baseline cleanup or weaken checks.
- Git is writable. Parser fix and its regression/evidence are committed as `605e11c`; no push.

Final rerun sau harness 08: `UV_CACHE_DIR=/tmp/strix-uv-cache timeout 40s uv run --offline pytest -q -o faulthandler_timeout=10` exit **124**, vẫn treo async/thread boundary (selector; worker threads idle), không phải full pass. Log `/tmp/strix-hybrid-final-full-suite.log`. Final Ruff format/check và git diff --check exit 0.


Environment diagnostic riêng: config Pyright tạm dưới /tmp giữ nguyên strict settings, thêm project/site-packages paths (không sửa repo config) resolve lại imports: exit 1, 962 errors; không diagnostic ở strix/routing. So baseline diagnostic signatures, phần mới chỉ ở viewer/report_pdf.py, report/writer.py, runtime/docker_client.py/docker_connection.py, skills/__init__.py và utils/api_spec.py (dependency/stub discovery khác), không ở routing/core changes. Đây chỉ chẩn đoán môi trường, không thay required make check-all gate hoặc hạ checks. Không sửa unrelated baseline để giả acceptance.

Pending commit groups khi Git writable: (1) JEV choice parser + test/Task04 record; (2) preservation tests + docs/routing + Task07 record; (3) live harness + Task08/README evidence. Không tạo commit giả ở alternate Git directory hoặc push để bypass read-only .git.
