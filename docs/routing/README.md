# Child model routing qua CommandCode

Trạng thái cập nhật 06/10/2026 19:09 ICT: offline router/governor được kiểm thử; JEV đã được gọi live qua `typesafe/jev` và chọn Worker/DeepSeek cùng Specialist/MiMo. Quick scan thật hoàn tất nhưng sáu child đều ở rule floor nên scan-level JEV chưa được chứng minh; live Expert, parity, PoC và billing vẫn chưa xác minh. Router chọn model child một lần tại spawn. Root giữ model resolved, kể cả override từ CLI. Tools, prompts, skills, scan modes, context/history, max turns và budget policy giữ nguyên.

## Cấu hình

Python 3.12+, `uv`, dependencies từ `make dev-install`; chạy scan cần Docker hoạt động và quyền/credits LLM. Các tier dùng chung `LLM_API_KEY`, `LLM_API_BASE`, `STRIX_API_TYPE` và headers chính; không có credential riêng theo tier.

| Biến môi trường | Mặc định | Điều kiện |
|---|---|---|
| `STRIX_ROUTING_ENABLED` | `false` | Opt-in |
| `STRIX_ROUTING_SPECIALIST_MODEL` | Không có | Bắt buộc khi enabled; strip rỗng thành None |
| `STRIX_ROUTING_EXPERT_MODEL` | Không có | Optional; không chọn tier thiếu |
| `STRIX_ROUTING_JEV_ENABLED` | `false` | Opt-in metadata, không ZDR |
| `STRIX_ROUTING_JEV_TIMEOUT_S` | `5` | Hữu hạn, >0 giây |
| `STRIX_ROUTING_SPECIALIST_THRESHOLD` | `0.65` | Hữu hạn, 0<value<=1 |
| `STRIX_ROUTING_EXPERT_THRESHOLD` | `0.65` | Hữu hạn, 0<value<=1 |
| `STRIX_ROUTING_SPECIALIST_CAP` | `0.25` | Hữu hạn, 0<=value<=1 |
| `STRIX_ROUTING_EXPERT_CAP` | `0.05` | Hữu hạn, 0<=value<=1 |

Các trường tương ứng trong JSON settings nằm dưới `routing`: `enabled`, `specialist_model`, `expert_model`, `jev_enabled`, `jev_timeout_s`, `specialist_threshold`, `expert_threshold`, `specialist_cap`, `expert_cap`.

Floor-only là cấu hình khởi đầu; key được cấp qua environment, không ghi literal vào file/history:

```bash
export LLM_API_KEY="$CMD_API_KEY"
export LLM_API_BASE="https://api.commandcode.ai/provider/v1"
export STRIX_API_TYPE="chat_completions"
export STRIX_LLM="openai/deepseek/deepseek-v4.1-flash"
export STRIX_ROUTING_ENABLED=true
export STRIX_ROUTING_SPECIALIST_MODEL="openai/xiaomi/mimo-v2.6-pro"
export STRIX_ROUTING_EXPERT_MODEL="openai/gpt-6.1-sol"
export STRIX_ROUTING_JEV_ENABLED=true
# Chỉ bật JEV nếu policy metadata không-ZDR đã được xác nhận/cho phép:
uv run strix -n -t "$AUTHORIZED_FIXTURE_TARGET" --scan-mode quick --max-budget 5
```

Prefix `openai/` chọn native SDK; wire IDs lần lượt `deepseek/deepseek-v4.1-flash`, `xiaomi/mimo-v2.6-pro`, `gpt-6.1-sol`. Snapshot catalog/giá trong [plan](../../strix_hybrid_router_plan.md) ngày 05/10/2026 cần xác minh lại tại [catalog](https://api.commandcode.ai/provider/v1/models), [Provider API](https://commandcode.ai/docs/provider) và [Pricing & Limits](https://commandcode.ai/docs/resources/pricing-limits) trước live rollout. Startup yêu cầu cùng CommandCode Chat Completions, prefix hợp lệ và flags tool schema tương thích; không tự thay model hoặc bỏ reasoning/tool/cache settings để chạy được.

## Quyết định và dữ liệu JEV

High-impact skills hoặc severity high/critical yêu cầu tối thiểu specialist. Expert optional. JEV tắt thì dùng hard floor; plain task dùng worker và không gọi JEV. Soft caps là tỷ lệ **quyết định**, không phải tỷ lệ tiền; cap=0 cấm upgrade optional, hard floor vẫn ưu tiên. Đầu scan có allowance một upgrade khi cap>0.

Sau khi policy cho phép metadata không ZDR, bật `STRIX_ROUTING_JEV_ENABLED=true`. Adapter gọi `/systemone`, model `typesafe/jev`, question choice `route_tier`. Chỉ gửi policy skill labels, số attempts nguyên không âm, severity enum/null và task length bucket. Không gửi raw task, URL, history hoặc credential trong state. [ZDR policy](https://commandcode.ai/docs/resources/zdr): header `x-cmd-zdr: 1` cùng JEV bị từ chối tại startup; không tự gỡ header. Policy mandatory ZDR cần giữ JEV off.

Timeout, lỗi HTTP hoặc malformed answer fallback về floor; không retry. Valid usage vẫn ghi một lần nếu answer không hợp lệ. Cancellation và budget stop/pause/reserve truyền theo lifecycle, không fallback rồi spawn tiếp. Routing log chỉ tier/model/reason hoặc tên lớp exception.

## Resume, usage và rollback

Child snapshot lưu version/tier/model/base/API type, không key/headers. Resume preflight tất cả bindings trước sandbox/respawn: model của tier, normalized base và API type phải khớp. Đổi API key được phép. Child cũ giữ exact model, không gọi JEV lại; governor counters restore và chia sẻ reference với snapshot. Snapshot cũ không binding giữ đường cũ. Snapshot có bindings nhưng thiếu counters reconstruct count theo mọi child (kể cả completed/failed); lịch sử admission thất bại có thể không đầy đủ và có warning.

Scan mới rollback bằng `STRIX_ROUTING_ENABLED=false`. Không tắt routing hoặc đổi tier model để resume session routed cũ. Root legacy không lưu model binding riêng; worker override được đối chiếu khi có saved worker child binding.

Usage hook ghi model thực của child; JEV ghi `typesafe/jev`. Money vẫn là estimator của ledger hiện có và token allocation theo agent; giá model mới, cache và summary/compaction charge còn giới hạn. Giá unknown/estimate zero không chứng minh miễn phí, không dùng để mở live budget gate. Đối chiếu dashboard charge trước billing claim. Nếu cần reviewed rate registration, merge existing LiteLLM entry, clear resolver cache và chạy scan trong cùng process; không đổi pricing engine.

## Kiểm chứng và gates live

```bash
uv run pytest tests/test_routing_settings.py tests/test_routing_runconfig.py tests/test_routing_jev.py tests/test_routing_spawn.py tests/test_routing_resume.py -q
make check-all
uv run pytest -q
# Opt-in riêng; cần CMD_API_KEY đã cấp và policy/gates bên dưới:
STRIX_ROUTING_LIVE_TESTS=1 uv run pytest tests/test_routing_live.py -q
# Chỉ sau khi account policy cho phép JEV metadata không ZDR:
STRIX_ROUTING_LIVE_TESTS=1 STRIX_ROUTING_LIVE_JEV_ALLOWED=1 uv run pytest tests/test_routing_live.py -q
```

Live tests mặc định skip trước network. Opt-in+key có mà upstream/schema/tool contract lỗi phải fail. Trước inference cần quyền model/credits, reviewed pricing và policy metadata; trước pentest cần target được chủ sở hữu duyệt cùng ground truth. So sánh ba runs routing off / floor-only / JEV với cùng scope/settings/budget: finding, coverage, PoC và resume thật. Skip/mock không chứng minh quality hay billing. Không mua credits, merge/deploy hoặc tự chọn target trong workflow này. Theo [Task 08](../../tasks/08-live-rollout.md) để ghi gate/run evidence.

Biên bản 06/10/2026: harness offline materialize 49 declarations thật (kể cả filesystem/shell), dùng SDK converter và chỉ invoke echo tổng hợp. Live chưa chạy: catalog không truy cập được trong sandbox hiện tại, opt-in/policy/target chưa được cấp; key presence không chứng minh quyền model/credits. `make check-all` còn baseline Pyright failures; rerun full suite trong permission profile mới bị treo async thread handoff. Chi tiết và commands tại [Task 07](../../tasks/07-offline-acceptance.md) và [Task 08](../../tasks/08-live-rollout.md), không gọi đây là release đã nghiệm thu.

Giá được đọc lại từ [bảng chính thức](https://commandcode.ai/docs/resources/pricing-limits) ngày 06/10/2026, phù hợp snapshot plan: DeepSeek input/output có peak/off-peak, MiMo 0.435/0.87, GPT 2/10 và JEV input 0.042 USD/1M. Bundled LiteLLM map hiện thiếu cả bốn IDs; synthetic estimates bằng zero trước registration nên live budget gate chưa được mở từ map đó. Operator-local files `/tmp/strix-hybrid-reviewed-rates.json` và `/tmp/strix-hybrid-rate-runner.py` đã kiểm registration trong cùng process, giữ capability fields hiện có và clear resolver cache. Chúng không được cài vào production và không thực hiện scan mặc định:

```bash
UV_CACHE_DIR=/tmp/strix-uv-cache uv run --offline python /tmp/strix-hybrid-rate-runner.py
# Chỉ sau tất cả account/target/policy/network gates, cùng process với CLI:
UV_CACHE_DIR=/tmp/strix-uv-cache uv run --offline python /tmp/strix-hybrid-rate-runner.py --run-scan -n -t "$AUTHORIZED_FIXTURE_TARGET" --scan-mode quick --max-budget 5
```

Rate review/registration này chỉ kiểm estimator; chưa có account dashboard charge hoặc pentest quality/resume live để đối chiếu. Peak pricing trong local JSON dùng cách ước lượng thận trọng; operator phải review lại theo thời điểm và account trước chạy.

### Xác minh live cập nhật 06/10/2026

Đã có một QUICK scan hoàn tất trên target do owner ủy quyền bằng rate runner trong cùng process. Chi tiết lệnh tái chạy, test offline, mapping log `tier/model/reason`, kết quả, và các `SKIP` trung thực nằm ở [verification.md](verification.md). Kết quả này bổ sung cho lịch sử interrupted run ở Task 08; nó vẫn chưa xác nhận JEV policy, routing parity, PoC/ground truth, routed resume hay charge thực tế.


## Cập nhật live JEV — 06/10/2026 19:09 ICT

Owner đã cho phép metadata không-ZDR cho phiên kiểm thử; hai probe live bổ sung qua adapter/router thật trả về `worker` → `openai/deepseek/deepseek-v4.1-flash` (406/41 tokens) và `specialist` → `openai/xiaomi/mimo-v2.6-pro` (413/42), đều `reason=jev`, một request mỗi quyết định. Xem [biên bản xác minh](verification.md). Trong quick scan hoàn tất cùng ngày, JEV được bật nhưng không được hỏi: cả sáu child là `worker`, `reason=rule`, do các luật đóng lựa chọn; do đó scan-level JEV gate **FAIL**, không phải skip/pass. Không có live expert child; GPT entitlement, parity, ground truth/PoC, resume và actual billing còn mở.
