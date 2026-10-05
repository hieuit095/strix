# Quy tắc bắt buộc cho mọi task

Đặc tả: [plan](../strix_hybrid_router_plan.md). Nếu task có quyết định chi tiết hơn thì đó là cách thực hiện trong phạm vi plan. Nếu phát hiện xung đột thực sự, ghi rõ hai yêu cầu, hoàn tất việc độc lập và hỏi người dùng trước phần phụ thuộc; không tự mở rộng kiến trúc.

## 1. Mục tiêu bất biến

Giữ toàn bộ sức mạnh Strix: tools, prompts, skills, agent graph, context inheritance, scan modes, budget policy, session, resume, reporting và PoC. Multi-model chỉ đổi tên model/ModelSettings đúng model tại spawn, không giảm khả năng thực thi. Root dùng model resolved của người dùng; chỉ child được route. Không đổi model trong một session.

## 2. TDD đỏ/xanh thật

Mỗi hành vi mới/sửa bug có chu trình riêng:

1. Chỉ viết test thất bại vì hành vi cần xây dựng. Không viết production trước.
2. Chạy chính node test đó bằng `uv run pytest ... -q`. Lưu exit code và assertion/error chính xác vào biên bản task.
3. Kiểm tra lý do đỏ: bug dự kiến, import interface chưa tồn tại hoặc thiếu field đúng đặc tả. SyntaxError, fixture lỗi, package thiếu, request thật vô tình phát sinh không phải bằng chứng đỏ hợp lệ.
4. Viết phần production nhỏ nhất làm test đó xanh. Chạy lại **cùng node test**, lưu kết quả.
5. Thêm các case biên theo bảng task theo từng chu trình đỏ/xanh, không viết hàng loạt production rồi bổ sung test.
6. Refactor chỉ sau xanh; chạy lại test liên quan. Chạy `make check-all` trước bàn giao task có code và full suite ở Task 00/07.

Test characterization của behavior đang có có thể xanh ngay và phải ghi rõ là characterization, không gắn nhãn TDD đỏ/xanh. Việc viết tài liệu này không cần và không được tạo mã production để tạo “bằng chứng đỏ”.

Cấm xóa assertion cũ, đổi expected theo bug, hạ số test, offline skip/xfail, noqa/type-ignore chỉ để vượt cổng, mock chính hàm đang kiểm thử hoặc chỉ kiểm tra số lần gọi mà không kiểm tra đầu ra. Live test opt-in được skip khi thiếu gate; skip không chứng minh live đã pass.

## 3. YAGNI và DRY là giới hạn thực thi

- Chỉ hai module production mới: `strix/routing/runconfig.py` và `strix/routing/jev.py`.
- Không dependency mới, provider abstraction, registry, factory, plugin, thêm tier, checkpoint/stop/Advisor, ranking/EV, ledger/telemetry/database riêng.
- Không key/base/header riêng từng tier, không tự retry JEV, không trộn API wire. Worker, specialist, expert dùng connection main đã cấu hình.
- Không sửa tool create_agent signature, agent prompt, scan-mode prompt hoặc giới hạn turn/agent để “tối ưu”. Không refactor dedupe/compaction/report vì tiện đường.
- Tái dùng Settings loader, make_model_settings, StrixProvider, report_state.record_sdk_usage, coordinator snapshot và lifecycle guards. Không viết implementation thứ hai của chúng.
- Test helpers chỉ dùng lại khi thật sự cần cho nhiều test; không framework/fixtures tổng quát “cho sau này”. Đọc caller trước khi sửa interface.
- Case behavior disabled phải giữ đúng object RunConfig, không client/router/network/routing files. Logging hiện có là đủ.

## 4. Dữ liệu và thao tác ngoài repo

Offline test không network, Docker hay inference tính phí. Dùng `httpx.MockTransport`, giả SDK/lifecycle theo tests hiện có. Không đọc hoặc in API key thật. Không ghi Settings/key/header vào snapshot/log.

Chỉ Task 08 dùng live inference sau khi người dùng cho phép chạy live và cung cấp các gate. Viết task không phải cho phép chạy scan hoặc mua credits. Không suy target được phép từ URL trong repo. Không tự bỏ ZDR để JEV chạy.

Budget errors/cancellation là lifecycle control, không phải “JEV bị lỗi”: không nuốt chúng rồi spawn child. Cap governor là tỷ lệ quyết định, không hứa là tỷ lệ tiền.

## 5. Kiểm soát file và Git

Đọc `git status --short` trước sửa. Công việc untracked hiện có của người dùng phải được giữ. Không reset/clean/stash/delete để lấy baseline sạch. Không `git add .`; stage đúng file của task nếu session đã cho phép commit. Nếu chưa được yêu cầu commit thì bàn giao diff, không tự commit/push/merge.

Dùng nhánh `codex/hybrid-router-commandcode` chỉ khi cần bắt đầu implementation và session cho phép tạo nhánh. Không đổi nhánh trong task viết tài liệu. Test scaffold thay đổi được khi interface Settings thay đổi, nhưng mọi assertion cũ phải giữ ý nghĩa; ghi riêng thay đổi scaffold.

## 6. Mẫu biên bản task

Điền sau khi thực hiện, không điền sẵn thành công:

- Commit/diff được kiểm chứng và file thực tế đã sửa.
- RED: command, exit code, lỗi/giá trị sai đúng lý do.
- GREEN: cùng command, exit code, số passed.
- Regression/check-all: command, kết quả; failures baseline tách riêng.
- Characterization/live: phân loại đúng, không gộp skip thành pass.
- Scope: module mới, dependency, tools/prompts có đổi không.
- Gate còn thiếu: nêu cụ thể; task không hoàn thành nếu đó là điều kiện nghiệm thu.

Kỹ sư không được đoán một gate đã thỏa mãn từ việc không thấy lỗi. Chỉ tick checkbox sau khi có bằng chứng trực tiếp.
