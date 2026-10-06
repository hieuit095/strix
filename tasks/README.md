# Tasks: Strix multi-model + JEV qua CommandCode

**Đặc tả duy nhất:** [strix_hybrid_router_plan.md](../strix_hybrid_router_plan.md). **Quy tắc bắt buộc:** [RULES.md](RULES.md). Đọc hai file này trước task đầu tiên. Tài liệu này phân rã plan thành thao tác triển khai, không bổ sung tính năng.

**Trạng thái lúc tạo danh sách:** chưa triển khai các task. Các checkbox trống là việc cần thực hiện, không phải bằng chứng đã làm. Lõi routing đang có 26 test xanh; 63 test liên quan đã xanh khi khảo sát trước đó. Không dùng kết quả cũ để nghiệm thu commit mới.

## Thứ tự thực hiện

Chạy tuần tự; task sau nhận interface đã chốt trong task trước. Không chạy nhiều task sửa cùng file đồng thời. Mỗi task đọc được riêng nhưng vẫn phải đọc RULES và plan. Nếu người dùng yêu cầu thực hiện một task, không tự thực hiện toàn bộ danh sách.

| ID | Task | Phụ thuộc | Cổng hoàn thành |
|---|---|---|---|
| 00 | [Baseline và ghi bằng chứng](00-baseline.md) | — | Biết trạng thái thực tế; không ghi đè công việc sẵn có |
| 01 | [Router, governor và availability](01-router-governor.md) | 00 | Floor/ceiling đúng, không chọn tier thiếu |
| 02 | [Settings, validation và RunConfig](02-settings-runconfig.md) | 01 | Dùng chung gateway, giữ model settings và provider |
| 03 | [Usage ghi đúng model](03-model-usage.md) | 00 | Hook dùng model thực, fallback tương thích |
| 04 | [JEV adapter](04-jev-adapter.md) | 01–03 | System One đúng schema, dữ liệu allowlist, usage một lần |
| 05 | [Nối spawn và lifecycle](05-spawn-lifecycle.md) | 01–04 | Route child; root/disabled/budget giữ semantics |
| 06 | [Snapshot và resume](06-snapshot-resume.md) | 05 | Model/counters restore đúng; không gọi JEV lại |
| 07 | [Nghiệm thu offline và tài liệu](07-offline-acceptance.md) | 00–06 | Full tests/check-all; docs và cơ chế cũ không regress |
| 08 | [Contract live, chất lượng và rollout](08-live-rollout.md) | 07 | Có bằng chứng thực hoặc ghi rõ gate chưa được đáp ứng |

Task 03 có thể độc lập sau 00 nhưng danh sách mặc định vẫn làm theo ID. Chưa deploy/merge/release trước Task 06. Task 08 có gate account, policy và target; không có bằng chứng thì **chưa hoàn thành plan**, không thay bằng kết quả mock.

## Đối chiếu đầy đủ với plan

| Yêu cầu plan | Task chịu trách nhiệm | Bằng chứng |
|---|---|---|
| §1/§7 giữ sức mạnh, phạm vi nhỏ | RULES + 05/07/08 | Tool/prompt/settings assertions, coverage/PoC thực |
| §2 baseline/lõi sẵn có | 00/01 | Baseline log + red/green regression |
| §3.2 model IDs/wire | 02/08 | Mock request + synthetic live contracts |
| §3.3 JEV schema/fallback | 01/04 | Parser tests + route errors/cancellation |
| §3.4 privacy/ZDR | 02/04/08 | Startup reject, allowlist, policy gate |
| §3.5 usage/billing limitation | 03/04/07/08 | Model hook, JEV usage, pricing gate và docs |
| §4.1 hard floor/cap/root | 01/05 | 3-RCE regression + root/spawn assertions |
| §4.2 Settings/JSON aliases | 02 | Field/alias/env/JSON tests |
| §4.3 chỉ hai module mới, DRY helper | 02/04/07 | Diff kiểm tra module/unchanged provider |
| §4.3 binding/counters/legacy | 06 | Snapshot/restore/mismatch/legacy tests |
| §5 client lifecycle/budget | 05/06 | Pause/stop/reserve guards + close/cancel |
| §6 cấu hình và rollback | 07/08 | README sử dụng + rollout record |
| §7 offline và live DoD | 07/08 | Evidence tách offline/live, không bịa |

## Bằng chứng

Mỗi task cập nhật mục “Biên bản hoàn thành” ở cuối file của chính nó. Chỉ thêm log ngắn đã lọc secret hoặc đường dẫn log cục bộ; không dựng artifact system. Đừng tạo file bằng chứng trước khi thật sự có kết quả.

Báo cáo cuối phải phân biệt: `offline verified`, `live verified`, `blocked by external gate`. Các từ này là trạng thái ghi nhận, không phải cơ chế chạy nền. Hoàn thành tất cả 00–08 và checklist plan §7 thì mới tuyên bố nâng cấp đã hoàn thành.


## Trạng thái thực thi ngày 06/10/2026

| Task | Trạng thái hiện tại | Evidence |
|---|---|---|
| 00 | Hoàn tất baseline | 2355 passed/3 existing xfailed; quality baseline 910 Pyright errors |
| 01–06 | Implementation và required targeted regressions đã ghi; acceptance quality chưa đạt | Biên bản từng task; commits qua `605e11c` |
| 07 | Full offline suite pass; acceptance remains open because required check-all is red | Current-source run: 2564 passed/13 live skipped/3 xfailed; latest repository Pyright result 136 diagnostics after incremental typing fixes; Ruff/mypy pass |
| 08 | Offline harness pass; catalog and owner target verified; bounded live quick scan blocked at provider auth; rollout incomplete | 20 passed/13 skipped offline; prior chat live 8 passed/4 failed (GPT plan access); catalog confirms three text IDs/endpoints, JEV absent; owner target HEAD authorized and served locally; one new bounded quick scan attempt exited 1 on HTTP 401 before scanning; no findings count; no JEV policy/ground-truth comparator/verified billing |

Không tuyên bố toàn plan complete. Branch vẫn `feat/hybrid-router`; parser fix, Task 07 preservation/docs, Task 08 live harness/evidence và catalog update đã commit. Không push. Task 07 check-all vẫn đỏ; lần `make check-all` gần nhất báo Pyright 138 diagnostics (exit 2), và Pyright hiện trực tiếp 136 diagnostics. Target hiện đã được owner-authorize nhưng live scan chưa qua inference authentication (401); cần key inference hợp lệ trước bất kỳ lần thử nào khác. JEV cần catalog entry/policy non-ZDR; còn thiếu ground-truth comparison/resume và verified billing. Xem commands/exit codes ở biên bản 07/08. Credential ngoài repo không được lưu trong repo/log/evidence.
