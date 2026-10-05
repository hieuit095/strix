# Task 01 — Router giữ hard floor và chọn tier có thật

**Phụ thuộc:** 00. **Đọc:** RULES, plan §2.3/4.1/4.3; toàn bộ năm module routing và bốn tests routing.
**Allowed production:** `strix/routing/types.py`, `governor.py`, `router.py`; `policy.py` chỉ nếu sửa lỗi thật được test chứng minh, không đổi skill sets.
**Allowed tests:** bốn file `tests/test_routing_*.py` hiện có.
**Mục tiêu:** sửa bug ba RCE, availability/floor-only; chưa runner/network.

## Interface bàn giao

```python
@dataclass(frozen=True)
class DecisionResult:
    probabilities: dict[str, float]
    input_tokens: int
    output_tokens: int

class DecisionClient(Protocol):
    async def decide(self, envelope: Envelope, question: str) -> DecisionResult: ...

# client=None là floor-only. available keyword có default đủ ba tier
# để callers hiện có còn dùng được, nhưng wiring thật phải truyền explicit.
class HybridModelRouter:
    def __init__(self, client: DecisionClient | None, governor: BudgetGovernor, *,
        specialist_threshold: float, expert_threshold: float,
        available: frozenset[Tier] = frozenset(Tier)) -> None: ...

class BudgetGovernor:
    def admit(self, tier: Tier, *, floor: Tier = Tier.WORKER,
        available: frozenset[Tier] = frozenset(Tier)) -> Tier: ...
```

Giữ RouteDecision(tier, reason) và counts dict hiện có. Không thêm confidence vào contract nếu router không dùng. Adapter kiểm tra confidence ở Task 04.

## Chu trình A — Bug đã tái hiện

- [ ] Chỉ thêm test sau vào file router test, dùng helpers `make`, `e`, `FakeClient` hiện có:

```python
async def test_repeated_high_impact_never_drops_below_floor() -> None:
    r = make(FakeClient({"worker": 0.0, "specialist": 0.1, "expert": 0.9}))
    decisions = [await r.route(e("rce")) for _ in range(3)]
    assert [d.tier for d in decisions] == [Tier.EXPERT, Tier.SPECIALIST, Tier.SPECIALIST]
```

- [ ] RED:

```bash
uv run pytest tests/test_routing_router.py::test_repeated_high_impact_never_drops_below_floor -q
```

Kỳ vọng thứ ba là WORKER gây AssertionError. Nếu xanh, kiểm tra HEAD; có thể bug đã được sửa, ghi characterization và chuyển regression còn thiếu, không cố tạo đỏ.

- [ ] GREEN: thêm floor vào admit; `while tier > floor` thay việc hạ đến WORKER; router truyền rules.floor. Chạy lại cùng node. Counter phải phản ánh tier cuối một lần.

## Chu trình B — Cap và tier availability

- [ ] Thêm các tests sau trong governor file, trước sửa availability:

```python
def test_zero_cap_disallows_optional_expert() -> None:
    g = BudgetGovernor(specialist_cap=1.0, expert_cap=0.0)
    assert g.admit(Tier.EXPERT, floor=Tier.WORKER, available=frozenset(Tier)) is Tier.SPECIALIST


def test_missing_expert_falls_to_specialist() -> None:
    g = BudgetGovernor(1.0, 1.0)
    assert g.admit(Tier.EXPERT, floor=Tier.SPECIALIST,
                   available=frozenset({Tier.WORKER, Tier.SPECIALIST})) is Tier.SPECIALIST


def test_missing_floor_is_rejected() -> None:
    g = BudgetGovernor(1.0, 1.0)
    with pytest.raises(ValueError, match="floor"):
        g.admit(Tier.EXPERT, floor=Tier.SPECIALIST,
                available=frozenset({Tier.WORKER, Tier.EXPERT}))
```

Thêm `import pytest` nếu chưa có. RED từng node bằng `uv run pytest tests/test_routing_governor.py::<name> -q`; không gộp ba behavior trước production nếu không lưu từng lý do đỏ.

- [ ] Thuật toán nhỏ nhất: reject floor không available/tier<floor; skip tier không available khi hạ; floor luôn được admit; cap==0 chỉ chặn nâng cấp tùy chọn; cap>0 dùng công thức hiện có `count+1<=max(1,cap*(total+1))`; tăng counter đúng tier cuối. Không lock/await.
- [ ] GREEN từng node rồi test counts/worker/cap boundary đang có. Floor có thể vượt share cap; không biến thành điều kiện stop.

## Chu trình C — DecisionResult và floor-only

- [ ] Chuyển FakeClient đang có sang trả `DecisionResult(probs, 10, 1)` khi thành công; giữ việc raise exc, calls counter và cách khởi tạo FakeClient(probs). Đổi `_pick` lấy result.probabilities. Đây là interface migration, giữ mọi assertion cũ.
- [ ] Thêm và chạy RED:

```python
async def test_floor_only_routes_without_client() -> None:
    r = HybridModelRouter(None, BudgetGovernor(0.25, 0.05),
        specialist_threshold=0.65, expert_threshold=0.65,
        available=frozenset({Tier.WORKER, Tier.SPECIALIST}))
    assert (await r.route(e("rce"))).tier is Tier.SPECIALIST

async def test_single_allowed_tier_never_calls_jev() -> None:
    c = FakeClient({"worker": 0.0, "specialist": 0.0, "expert": 1.0})
    r = HybridModelRouter(c, BudgetGovernor(1.0, 1.0),
        specialist_threshold=0.65, expert_threshold=0.65,
        available=frozenset({Tier.WORKER, Tier.SPECIALIST}))
    assert (await r.route(e("rce"))).tier is Tier.SPECIALIST
    assert c.calls == 0
```

- [ ] Tính allowed = available trong [rules.floor,rules.ceiling]; reject missing floor; sole-choice/client None → floor; expert rồi specialist so >=threshold; clamp/chọn tier hợp lệ trước admit. Reason giữ `rule`, `jev`, `jev_error`, `governor`; floor-only/sole-choice dùng `rule`, không thêm reason enum framework.
- [ ] Keep fake TimeoutError/ValueError/RuntimeError fallback và CancelledError propagate. Task 04 bảo đảm callback usage không phát lifecycle error vào router's generic catch; budget guard phải nằm ngoài decide.
- [ ] Thêm parametrized exact-threshold test: expert=.65/high-impact → expert, specialist=.65/business_logic → specialist; distribution đủ ba nhãn tổng 1. Test severity high chỉ floor specialist, client.calls=0 khi sole-choice.

## Nghiệm thu

```bash
uv run pytest tests/test_routing_types.py tests/test_routing_policy.py tests/test_routing_governor.py tests/test_routing_router.py -q
make check-all
```

- [ ] Existing assertions không bị giảm; tests thêm thật.
- [ ] Không model thiếu/floor violation, lỗi/cancellation đúng, counts increment một lần.
- [ ] Chưa runner/config/HTTP, không tính năng ngoài scope.

## Biên bản hoàn thành

Implementation verified, gate check-all chưa đạt (baseline).

- Production: mở rộng types/governor/router sẵn có; policy/skill sets không đổi. FakeClient chuyển contract sang DecisionResult, giữ assertions cũ.
- RED/GREEN cùng command `uv run pytest tests/test_routing_router.py::test_repeated_high_impact_never_drops_below_floor -q`: exit 1 (lần 3 WORKER), rồi exit 0 (1 passed).
- RED/GREEN từng command `uv run pytest tests/test_routing_governor.py::<node> -q`, nodes `test_zero_cap_disallows_optional_expert`, `test_missing_expert_falls_to_specialist`, `test_missing_floor_is_rejected`: từng exit 1 do available chưa tồn tại; cùng node sau implementation từng exit 0/1 passed.
- RED/GREEN từng command `uv run pytest tests/test_routing_router.py::<node> -q`, nodes `test_floor_only_routes_without_client`, `test_single_allowed_tier_never_calls_jev`: từng exit 1 (available thiếu), sau implementation từng exit 0/1 passed.
- Characterization: thresholds >=.65, missing floor/tier<floor không counting, hard floor thắng cap=0, severity sole-choice; đều xanh sau interfaces trên, không gọi là RED giả.
- Regression `uv run pytest tests/test_routing_types.py tests/test_routing_policy.py tests/test_routing_governor.py tests/test_routing_router.py -q`: exit 0, 38 passed. Một lần test scaffold lỗi NameError do assertion đặt sai chỗ đã sửa; không tính là RED hành vi.
- `uv run ruff format ...`: exit 0; `uv run ruff check strix/routing tests/test_routing_types.py tests/test_routing_policy.py tests/test_routing_governor.py tests/test_routing_router.py`: exit 0.
- `make check-all`: exit 2, cùng 910 Pyright baseline errors; Ruff/mypy xanh. Log `/tmp/strix-hybrid-task01-check-all.log`; không error ở routing. Chưa tick hoàn thành gate này.
- Không runner/config/HTTP/dependency/tools/prompts mới. Chưa hoàn thành nghiệm thu toàn task cho đến quality gate được xử lý.
