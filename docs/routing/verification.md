# Xác minh Hybrid Router

File `scripts/verify_hybrid_routing.py` là một lệnh tái chạy gồm hai phần: chạy kiểm thử router/governor/JEV offline, sau đó chạy một QUICK scan thật với ngân sách tối đa USD 5 và đối chiếu log quyết định với model binding đã lưu. Script yêu cầu app local ở cổng 5173, key trong môi trường được bảo vệ, và rate runner operator-local để ước tính ngân sách trong cùng process với Strix.

## Chạy lại

Không bật shell tracing. Lệnh dưới đây không in hoặc ghi credential vào repo; nó chỉ đọc file mode 0600 bên ngoài repo. Target URL là app local đã được owner cho phép. `host.docker.internal` dùng cho container Strix; script probe `127.0.0.1:5173` trên host.

```bash
set +x
set -a
. /home/hieuit095/.strix-live.env
set +a
trap 'unset LLM_API_KEY CMD_API_KEY COMMAND_CODE_API_BASE LLM_API_BASE STRIX_LLM STRIX_API_TYPE STRIX_REASONING_EFFORT LLM_TIMEOUT STRIX_ROUTING_LIVE_TESTS STRIX_ROUTING_ENABLED STRIX_ROUTING_SPECIALIST_MODEL STRIX_ROUTING_EXPERT_MODEL STRIX_ROUTING_JEV_ENABLED STRIX_ROUTING_SPECIALIST_THRESHOLD STRIX_ROUTING_EXPERT_THRESHOLD STRIX_ROUTING_SPECIALIST_CAP STRIX_ROUTING_EXPERT_CAP' EXIT
export STRIX_ROUTING_ENABLED=true
export STRIX_ROUTING_SPECIALIST_MODEL='openai/xiaomi/mimo-v2.6-pro'
export STRIX_ROUTING_EXPERT_MODEL='openai/gpt-6.1-sol'
export STRIX_ROUTING_JEV_ENABLED=false
export STRIX_ROUTING_SPECIALIST_THRESHOLD=0.65 STRIX_ROUTING_EXPERT_THRESHOLD=0.65
export STRIX_ROUTING_SPECIALIST_CAP=0.25 STRIX_ROUTING_EXPERT_CAP=0.05
UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True \
  uv run --offline python scripts/verify_hybrid_routing.py \
  --target http://host.docker.internal:5173 --timeout-seconds 10800
```

The runner prints one `PASS`, `FAIL`, or `SKIP` per live assertion. It suppresses raw scan stdout/stderr and writes secret-free JSON beside that run under ignored `strix_runs/<run-name>/routing-verification.json`. It asserts completed QUICK status, positive in-process estimated cost no greater than USD 5, DeepSeek root usage, every child log's tier/model/reason against its persisted binding, and exact configured model IDs. A scan exit code of 2 is accepted only with a completed run because Strix uses it when findings are filed.

## Assertions covered

The deterministic tests exercise the actual `HybridModelRouter`, `BudgetGovernor`, hard-rule policy, and `configured_models` mapping with synthetic probability inputs. They assert the worker floor/no-signal path, inclusive specialist/expert thresholds, both share caps and downward fallback, the hard floor, JEV only for open choices, JEV precedence, transport/malformed fallback reason, missing-tier availability, and the DeepSeek → MiMo → GPT model map. Existing `tests/test_routing_jev.py` cases exercise the real adapter parser through fake HTTP transport, including malformed `choice` fallback.

For a live run with JEV disabled, JEV is reported as `SKIP`; expert selection is also not expected because the router does not choose above the hard-rule floor without JEV. The synthetic tests still exercise expert selection and its model mapping. Do not enable JEV until both model availability and non-ZDR metadata policy are verified.

## Evidence — 2026-10-06 (Asia/Ho_Chi_Minh)

- Target: owner-authorized isolated snapshot of `/home/hieuit095/h-th-ng-qu-n-l-btxh-nct` at `6c0fc01e7f969bbf75ef663606aa4a4d7c747620`. Host probe returned HTTP 200. The owner repo stayed read-only; final HEAD/status are recorded in Task 08.
- Live verification run: `host-docker-internal-5173_d4d3`, scan command used `--scan-mode quick --max-budget 5`, CLI exit **2**, final `run.json` status **completed**. It recorded 194 requests, 20,122,162 input tokens, 235,558 output tokens, 20,357,720 total tokens and **USD 0.522904632 estimated** (not an account charge). Coverage recorded 19 surfaces, 3 gaps and 5 filed reports.
- Routing assertions: **4/4** logged child decisions matched persisted bindings: `worker`, `openai/deepseek/deepseek-v4.1-flash`, `reason=rule`. The root model was DeepSeek. Specialist and expert live decisions were not emitted by this quick workload; their observations are `SKIP`, not pass. JEV path is `SKIP` because disabled; JEV catalog availability and non-ZDR policy remain unverified.
- The verifier invocation's embedded offline command passed **84 tests**. After adding the final synthetic three-tier model-flow assertion, the exact targeted regression command below passed **85 tests**; Ruff format/check also passed. Thus the final offline test source is verified, while the live artifact reflects the same verifier before that last test was added.

```bash
UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True \
  uv run --offline pytest tests/test_routing_verification.py \
  tests/test_routing_router.py tests/test_routing_jev.py -q
```

Live JEV, a live specialist/expert child decision, comparison against a ground-truth baseline, routed-child resume, and actual provider billing remain unverified. This evidence does not mark Task 08 or the overall plan complete.
