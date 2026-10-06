# Task 04 — JEV System One adapter nhỏ, không framework

**Phụ thuộc:** 01–03. **Đọc:** RULES, plan §3.3–3.5, Protocol/DecisionResult từ 01.
**Tạo production:** `strix/routing/jev.py`; **test:** `tests/test_routing_jev.py`. Router chỉ sửa logging/fallback boundary nếu test privacy cần, không thêm policy.

## Contract bàn giao

```python
class JevClient:
    def __init__(self, client: httpx.AsyncClient, *, base_url: str,
        api_key: str, timeout_s: float,
        on_usage: Callable[[Usage], None]) -> None: ...
    async def decide(self, envelope: Envelope, question: str) -> DecisionResult: ...
```

`on_usage` là callback sync chỉ ghi report_state usage; **không** chạy budget guard trong callback. Guard ở runner ngoài router try/except (05). Client HTTP do runner sở hữu, adapter không tự close. Không SDK TypeSafe/key/config riêng; không stream/retry. Chỉ question `route_tier`, question khác reject ValueError trước HTTP.

## Chu trình A — Request/response hợp lệ

- [ ] Đặt fixture dưới trong test file (số synthetic):

```python
VALID = {"model": "typesafe/jev", "answers": {"route_tier": {
    "type": "choice", "choice": "specialist", "confidence": 0.7,
    "probabilities": {"worker": 0.1, "specialist": 0.8, "expert": 0.1}}},
    "usage": {"input_tokens": 180, "output_tokens": 3}}
```

- [ ] Viết RED test:

```python
import json
import httpx
from agents.usage import Usage
from strix.routing.jev import JevClient
from strix.routing.types import Envelope

async def test_jev_wire_and_result() -> None:
    requests: list[httpx.Request] = []
    usage: list[Usage] = []
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=VALID)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = JevClient(client, base_url="https://api.commandcode.ai/provider/v1",
            api_key="dummy", timeout_s=5, on_usage=usage.append)
        result = await adapter.decide(Envelope("synthetic", ("business_logic",)), "route_tier")
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.commandcode.ai/provider/v1/systemone"
    assert requests[0].headers["Authorization"] == "Bearer dummy"
    body = json.loads(requests[0].content)
    assert body["model"] == "typesafe/jev"
    assert isinstance(body["state"], str)
    assert body["questions"]["route_tier"]["type"] == "choice"
    assert result.probabilities == {"worker": 0.1, "specialist": 0.8, "expert": 0.1}
    assert (result.input_tokens, result.output_tokens) == (180, 3)
    assert len(usage) == 1
    assert (usage[0].requests, usage[0].total_tokens) == (1, 183)
```

- [ ] `uv run pytest tests/test_routing_jev.py::test_jev_wire_and_result -q` → ModuleNotFoundError đúng module chưa có.
- [ ] GREEN implement trong một module: URL `base_url.rstrip('/')+'/systemone'`; headers auth/content-type; POST json đúng plan §3.3; `timeout=self._timeout_s`; `response.raise_for_status()`; parse usage trước answer; on_usage once; return DecisionResult.
- [ ] Instructions/criteria copy từ plan §3.3 làm hằng nhỏ trong module; không prompt builder class. Typed parse dùng `isinstance(value,(int,float)) and not isinstance(value,bool)` + math.isfinite, int tokens reject bool. Không dùng float('bad') có đường normalize thành số 0.

## Chu trình B — Allowlist, không gửi task

- [ ] Tạo test body capture với `Envelope(task="https://private.test/a?token=abc XYZ_SECRET_921", skills=("business_logic","XYZ_SECRET_921"), attempts=2, severity="high")`.
- [ ] RED: `json.loads(body['state'])` **bằng** dict `{"skills":["business_logic"],"attempts":2,"severity":"high","task_length_bucket":"short"}`; task/token/hostname/custom skill không có trong body. Đừng chỉ tìm chữ password.
- [ ] GREEN serializer: normalize lower skills, giữ membership `HIGH_IMPACT|AMBIGUOUS`, sorted unique; severity lower thuộc low/medium/high/critical hoặc null; attempts int>=0 hoặc reject invalid; bucket đo len(task), không substring/hash. Không nhận dictionary linh hoạt từ callers.
- [ ] Boundary tests lengths 256/257/2048/2049 → short/medium/medium/long. Unsupported question → ValueError và zero requests/usage. Không gửi notes/tools/finding data vì Envelope không cần chúng.

## Chu trình C — Malformed answer/usage

Dùng `copy.deepcopy(VALID)` trong test parametrized, mỗi case sửa chính một path rồi handler trả JSON đó. Với NaN/Infinity dùng `httpx.Response(200, content=json.dumps(payload, allow_nan=True), headers={"Content-Type":"application/json"})`, không dùng `json=payload` vì httpx có thể reject trước parser và tạo đỏ/xanh sai lý do. RED từng nhóm, GREEN bằng validator chung trong adapter.

| Path/case | Expected |
|---|---|
| Không answers.route_tier, type=score, choice=other | ValueError |
| Thiếu expert, thêm fourth label | ValueError, không fill 0 |
| Prob -0.1/1.1/True/NaN/Infinity | ValueError |
| Prob sum=.8 | ValueError, không normalize |
| Confidence True/NaN/-0.1/1.1 | ValueError |
| Missing usage, tokens -1/True/1.5/string | ValueError, không fake count |
| Field top-level extra | PASS, future-compatible |

- [ ] Sum valid tolerance <=0.01; test .009 accepted/.011 rejected, tránh float equality sát boundary.
- [ ] Usage hợp lệ + answer malformed → on_usage vẫn một lần rồi ValueError. Usage malformed → không record số bịa. JSON không parse được/HTTP lỗi → không biết charge, không gọi là miễn phí.
- [ ] `requests=1`, `input_tokens`, `output_tokens`, `total_tokens=input+output` khi tạo agents.usage.Usage.

## Chu trình D — Errors, privacy và cancellation

- [ ] Parametrize status 400/401/403/422/429/500/502/503/504: one request, no retry; adapter raises HTTPStatusError; qua router thì tier floor/reason jev_error. Transport raise httpx.ReadTimeout → floor; CancelledError phải propagate.
- [ ] Handler response error chứa `SERVER_SECRET_82`; request key=`KEY_SECRET_51`; caplog ở router mức error: hai chuỗi không có trong log. Đổi router `logger.exception` sang `logger.warning("JEV routing failed (%s); using rule floor", type(exc).__name__)` nếu stack/text đang lộ body. Không log exception repr/full response/request.
- [ ] Test callback chỉ nhận Usage, không có task/key, một lần. Callback lỗi kế toán không được retry HTTP; runner callback giống hook hiện có: logger tên agent/error class, không secret. Không biến lỗi kế toán thành call thêm.
- [ ] Header ZDR policy phải được reject từ startup Task 02/05; adapter không nhận extra_headers main và không tự gỡ header rồi retry. Không set x-cmd-zdr=0.

## Nghiệm thu

```bash
uv run pytest tests/test_routing_jev.py tests/test_routing_router.py tests/test_cost_tracking.py -q
make check-all
```

- [ ] Protocol khớp, body schema đúng, one request/decision, usage once, allowlist thật.
- [ ] HTTP/parse fallback có reason; cancellation không bị nuốt.
- [ ] Chỉ module mới thứ hai; không close ownership sai/secret log.

## Biên bản hoàn thành

Task 07 phát hiện thêm regression malformed choice list/dict: `uv run pytest tests/test_routing_jev.py::test_malformed_answer_rejected_with_usage -q` RED exit 1, 2 failed/17 passed (TypeError unhashable). Thêm guard string, cùng lệnh GREEN exit 0, 19 passed; `uv run pytest tests/test_routing_jev.py tests/test_routing_router.py -q` exit 0, 69 passed. Usage vẫn ghi một lần và malformed response fallback đúng exception contract. Log `/tmp/strix-hybrid-task04-choice-red.log`.

Implementation verified, check-all baseline chưa đạt.

- Thêm production module thứ hai `strix/routing/jev.py`, test_routing_jev; router log error class và catch network/parse RuntimeError/ValueError/TimeoutError/httpx.HTTPError, không log raw exception/body/key.
- RED/GREEN `uv run pytest tests/test_routing_jev.py::test_jev_wire_and_result -q`: exit 4 ModuleNotFoundError → exit 0/1 passed.
- RED/GREEN cùng prefix nodes `test_allowlist_excludes_raw_task_and_custom_skills` (exit 1 empty state → 0/1 passed), `test_unsupported_question_rejected_before_http` (exit 1 KeyError sau HTTP → 0/1 passed), `test_invalid_attempts_rejected_before_http` (exit 1/3 failed → 0/3 passed).
- RED/GREEN nodes `test_malformed_answer_rejected_with_usage` (exit 1/17 failed → 0/17 passed); `test_malformed_usage_not_recorded` (exit 1/6 failed,1 passed qua Usage validation sẵn có → 0/7 passed). RED logs `/tmp/strix-hybrid-task04-{answer,usage}-red.log`.
- RED/GREEN `test_router_logs_only_error_class`: exit 1 dummy secrets lộ traceback → 0/1 passed. Không dump raw errors.
- Characterization: bucket boundaries/normalized allowlist, sum tolerance/extra fields, HTTP 400/401/403/422/429/5xx one call/floor, timeout/non-JSON fallback, cancellation propagate, callback error không retry. AsyncClient caller-owned.
- `uv run pytest tests/test_routing_jev.py tests/test_routing_router.py tests/test_cost_tracking.py -q`: exit 0, 94 passed, 2 baseline warnings (sau diff cuối).
- Ruff format/check exit 0, mypy xanh. `make check-all`: exit 2, 910 Pyright baseline errors; một new UnnecessaryIsInstance đã sửa bằng tái dùng token validator cho attempts, không suppress rule. Log `/tmp/strix-hybrid-task04-check-all.log`.
- Fake HTTP only, chưa gọi System One live. Không dependency/provider/ledger/service mới; ZDR guard nằm startup Task 02, budget guards ngoài router thuộc Task 05. Quality gate chưa tick.

### Kiểm tra gate cuối trên source hiện tại — 06/10/2026

- Full suite source hiện tại được chạy ở Task 07: exit **0**, **2565 passed, 13 skipped, 3 xfailed, 106 warnings**.
- Required `UV_CACHE_DIR=/tmp/strix-uv-cache timeout 240s make check-all` trên source hiện tại → exit **2**; Ruff/Mypy pass, Pyright còn 3 `reportImportCycles` trong MCP client/session/registry. Vì task này yêu cầu gate tổng xanh, Task 04 vẫn **chưa accepted**; xem Task 07 để command/log đầy đủ.
