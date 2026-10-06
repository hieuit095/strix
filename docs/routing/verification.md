# Xác minh Hybrid Router

File `scripts/verify_hybrid_routing.py` là một lệnh tái chạy gồm hai phần: chạy kiểm thử router/governor/JEV offline, sau đó chạy một QUICK scan thật với ngân sách tối đa USD 5 và đối chiếu log quyết định với model binding đã lưu. Script yêu cầu app local ở cổng 5173, key trong môi trường được bảo vệ, và rate runner operator-local để ước tính ngân sách trong cùng process với Strix.

## Chạy lại

Không bật shell tracing. Lệnh dưới đây không in hoặc ghi credential vào repo; nó chỉ đọc file mode 0600 bên ngoài repo. Target URL là app local đã được owner cho phép. `host.docker.internal` dùng cho container Strix; script probe `127.0.0.1:5173` trên host.

```bash
set +x
set -a
. /home/hieuit095/.strix-live.env
set +a
trap 'unset LLM_API_KEY CMD_API_KEY COMMAND_CODE_API_BASE LLM_API_BASE STRIX_LLM STRIX_API_TYPE STRIX_REASONING_EFFORT LLM_TIMEOUT STRIX_ROUTING_LIVE_TESTS STRIX_ROUTING_ENABLED STRIX_ROUTING_SPECIALIST_MODEL STRIX_ROUTING_EXPERT_MODEL STRIX_ROUTING_JEV_ENABLED STRIX_ROUTING_JEV_POLICY_VERIFIED STRIX_ROUTING_SPECIALIST_THRESHOLD STRIX_ROUTING_EXPERT_THRESHOLD STRIX_ROUTING_SPECIALIST_CAP STRIX_ROUTING_EXPERT_CAP' EXIT
export STRIX_ROUTING_ENABLED=true
export STRIX_ROUTING_SPECIALIST_MODEL='openai/xiaomi/mimo-v2.6-pro'
export STRIX_ROUTING_EXPERT_MODEL='openai/gpt-6.1-sol'
export STRIX_ROUTING_JEV_ENABLED=true
export STRIX_ROUTING_JEV_POLICY_VERIFIED=1
export STRIX_ROUTING_SPECIALIST_THRESHOLD=0.65 STRIX_ROUTING_EXPERT_THRESHOLD=0.65
export STRIX_ROUTING_SPECIALIST_CAP=0.25 STRIX_ROUTING_EXPERT_CAP=0.05
UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True \
  uv run --offline python scripts/verify_hybrid_routing.py \
  --target http://host.docker.internal:5173 --timeout-seconds 10800
```

The runner prints one `PASS`, `FAIL`, or `SKIP` per live assertion. This reproduction enables JEV and uses the owner's explicit non-ZDR authorization recorded below. It suppresses raw scan stdout/stderr and writes secret-free JSON beside that run under ignored `strix_runs/<run-name>/routing-verification.json`. It asserts completed QUICK status, positive in-process estimated cost no greater than USD 5, DeepSeek root usage, every child log's tier/model/reason/JEV choice against its persisted binding, valid JEV answer/usage logs, and a real failure record for every `jev_error`. A scan exit code of 2 is accepted only with a completed run because Strix uses it when findings are filed.

## Assertions covered

The deterministic tests exercise the actual `HybridModelRouter`, `BudgetGovernor`, hard-rule policy, and `configured_models` mapping with synthetic probability inputs. They assert the worker floor/no-signal path, inclusive specialist/expert thresholds, both share caps and downward fallback, the hard floor, JEV only for open choices, JEV precedence, transport/malformed fallback reason, missing-tier availability, and the DeepSeek → MiMo → GPT model map. Existing `tests/test_routing_jev.py` cases exercise the real adapter parser through fake HTTP transport, including malformed `choice` fallback.

With JEV enabled, the verified `choice` is logged with input/output token usage only. The router honors that choice within probability thresholds, hard-rule bounds, and the governor caps. It does not log task text, request state, probability values, credentials, or response bodies. If a live quick workload does not emit Specialist or Expert children, the verifier reports its tier distribution, choices, and final choice-to-tier reasons; offline tests exercise all three configured model mappings.

## Historical JEV-disabled evidence — 2026-10-06 (Asia/Ho_Chi_Minh)

- Target: owner-authorized isolated snapshot of `/home/hieuit095/h-th-ng-qu-n-l-btxh-nct` at `6c0fc01e7f969bbf75ef663606aa4a4d7c747620`. Host probe returned HTTP 200. The owner repo stayed read-only; final HEAD/status are recorded in Task 08.
- Live verification run: `host-docker-internal-5173_d4d3`, scan command used `--scan-mode quick --max-budget 5`, CLI exit **2**, final `run.json` status **completed**. It recorded 194 requests, 20,122,162 input tokens, 235,558 output tokens, 20,357,720 total tokens and **USD 0.522904632 estimated** (not an account charge). Coverage recorded 19 surfaces, 3 gaps and 5 filed reports.
- Routing assertions: **4/4** logged child decisions matched persisted bindings: `worker`, `openai/deepseek/deepseek-v4.1-flash`, `reason=rule`. The root model was DeepSeek. Specialist and expert live decisions were not emitted by this quick workload; their observations are `SKIP`, not pass. JEV path is `SKIP` because disabled; JEV catalog availability and non-ZDR policy remain unverified.
- The verifier invocation's embedded offline command passed **84 tests**. After adding the final synthetic three-tier model-flow assertion, the exact targeted regression command below passed **85 tests**; Ruff format/check also passed. Thus the final offline test source is verified, while the live artifact reflects the same verifier before that last test was added.

```bash
UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True \
  uv run --offline pytest tests/test_routing_verification.py \
  tests/test_routing_router.py tests/test_routing_jev.py -q
```

That historical run did not verify JEV. It is retained as a record of the earlier JEV-disabled test, not as current JEV evidence. Ground-truth parity, routed-child resume, and actual provider billing remain unverified.

## Owner-provided JEV probe — 2026-10-06 18:06 ICT

The owner reports two successful `POST https://api.commandcode.ai/provider/v1/systemone` calls with `model=typesafe/jev` and question `route_tier`; both returned HTTP 200. The reported sample answer was `choice=specialist`, `input_tokens=410`, `output_tokens=42`. The credential, headers, request body/state, probabilities, and raw response were not provided to or recorded by this evidence. This direct provider result establishes that the account's JEV metadata path is permitted for the authorized test. A prior catalogue response omitted JEV; that catalogue result is retained as a separate fact and is not evidence of policy rejection.

## JEV-enabled live verification — 2026-10-06 19:09 ICT

The owner-authorized target was served from the read-only isolated snapshot `/tmp/strix-live-target-6c0fc01` (source repository HEAD `6c0fc01e7f969bbf75ef663606aa4a4d7c747620`). The completed quick scan used `--scan-mode quick --max-budget 5`, enabled routing and JEV, configured DeepSeek/MiMo/GPT, thresholds `0.65`, and share caps `0.25/0.05`. The local target probe returned HTTP 200. The actual Strix scan process exited **2** (findings reported); its persisted run status was **completed**. It made 168 provider requests, used 17,730,531 input and 216,031 output tokens (17,946,562 total), and the in-process estimator recorded USD **0.516604116** against the USD 5 limit. This is an estimate, not a confirmed account charge. Coverage recorded 22 surfaces reviewed, 8 gaps, and 2 reports filed; outcomes were 3 reported, 4 no-issue-found, 7 ruled-out, 1 not-applicable, and 7 needs-follow-up. The reports are scan outputs, not independently confirmed vulnerabilities.

The scan emitted six child routing decisions. All six were `worker` / `openai/deepseek/deepseek-v4.1-flash`, `reason=rule`, with no JEV choice; it emitted no specialist or expert children, no JEV answer, and no JEV error. Therefore the scan-level JEV assertion **FAILED**: the workload's child decisions had no open choice (`ask_jev`), so the enabled JEV path was not reached. It would be inaccurate to call this a JEV pass or skip. The recorded distribution is worker 6, specialist 0, expert 0. The verifier command below returned exit **1** for that unmet JEV-path assertion, while recording the completed scan and its other passing checks in `strix_runs/host-docker-internal-5173_5b0b/routing-verification.json`.

Two additional bounded, single-request live decisions exercised the real `JevClient` → `HybridModelRouter` → governor/model-binding path. They used the same protected environment and did not use a mock transport. Both returned with `reason=jev` and one JEV request: choice `worker` mapped to `openai/deepseek/deepseek-v4.1-flash` (406 input, 41 output tokens), and choice `specialist` mapped to `openai/xiaomi/mimo-v2.6-pro` (413 input, 42 output tokens). The secret-free record is [live-jev-router-probes.json](../../strix_runs/host-docker-internal-5173_5b0b/live-jev-router-probes.json) (ignored run evidence, not committed). Together with the owner-reported probe above, these establish live JEV endpoint access, schema acceptance, usage parsing, choice propagation, and Worker/Specialist model mapping. No live Expert decision was made; the configured expert mapping is covered by deterministic offline tests only.

To reproduce the bounded scan after starting the owner-authorized local target, source the protected configuration and run the exact verifier command below. It enables JEV and fails if the quick scan does not genuinely log a JEV decision; do not convert that result into a pass by relaxing the assertion.

```bash
set +x
set -a; . /home/hieuit095/.strix-live.env; set +a
trap 'unset LLM_API_KEY CMD_API_KEY COMMAND_CODE_API_BASE LLM_API_BASE STRIX_LLM STRIX_API_TYPE STRIX_REASONING_EFFORT LLM_TIMEOUT STRIX_ROUTING_LIVE_TESTS STRIX_ROUTING_ENABLED STRIX_ROUTING_SPECIALIST_MODEL STRIX_ROUTING_EXPERT_MODEL STRIX_ROUTING_JEV_ENABLED STRIX_ROUTING_JEV_POLICY_VERIFIED STRIX_ROUTING_SPECIALIST_THRESHOLD STRIX_ROUTING_EXPERT_THRESHOLD STRIX_ROUTING_SPECIALIST_CAP STRIX_ROUTING_EXPERT_CAP' EXIT
export STRIX_ROUTING_ENABLED=true STRIX_ROUTING_SPECIALIST_MODEL='openai/xiaomi/mimo-v2.6-pro' STRIX_ROUTING_EXPERT_MODEL='openai/gpt-6.1-sol'
export STRIX_ROUTING_JEV_ENABLED=true STRIX_ROUTING_JEV_POLICY_VERIFIED=1
export STRIX_ROUTING_SPECIALIST_THRESHOLD=0.65 STRIX_ROUTING_EXPERT_THRESHOLD=0.65 STRIX_ROUTING_SPECIALIST_CAP=0.25 STRIX_ROUTING_EXPERT_CAP=0.05
UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True uv run --offline python scripts/verify_hybrid_routing.py --target http://host.docker.internal:5173 --timeout-seconds 10800
```

The exact executed live JEV probes were one `JevClient.decide(envelope, "route_tier")` call routed through `HybridModelRouter.route(envelope)` per synthetic open-choice envelope, with `base_url=COMMAND_CODE_API_BASE`, `api_key=CMD_API_KEY`, `timeout_s=STRIX_ROUTING_JEV_TIMEOUT_S`, thresholds `0.65`, specialist/expert caps `0.25/0.05`, and available configured Worker/DeepSeek, Specialist/MiMo, Expert/GPT tiers. Their outcomes and usage are recorded above; request state and response bodies were intentionally not retained. The direct probe evidence is not a claim that the QUICK scan itself invoked JEV.

### Current assertion status

- **PASS:** offline router/governor assertions cover floor, thresholds, cap downgrade, no worker downgrade, JEV precedence and error/malformed fallback, missing-model availability, and all three configured model mappings.
- **PASS:** live JEV endpoint calls and route decisions for Worker/DeepSeek and Specialist/MiMo; each had `reason=jev`, one request, and safe usage logging.
- **FAIL:** JEV was not reached by any of the six children in the bounded quick scan; all were closed rule-floor choices. The required scan-level live JEV assertion remains failed.
- **NOT OBSERVED:** live Expert/GPT child decision; the prior GPT entitlement response was HTTP 403 `MODEL_NOT_IN_PLAN`. The current configured model label does not prove live entitlement.
- **INCOMPLETE:** routing-off/floor-only/JEV-on finding and coverage parity, ground-truth/PoC validation, routed-child resume, and actual billing reconciliation.


## Scan-path JEV fix and completed re-run — 2026-10-06 21:02 ICT

### Root cause confirmed from the failed scan's own artifacts

The prior run `host-docker-internal-5173_5b0b` had six `child routing` records at `strix_runs/host-docker-internal-5173_5b0b/strix.log` lines 64, 741, 756, 1918, 2212, and 2622; every record was `reason=rule`, `tier=worker`, `jev_choice=none`. Its verification JSON had `jev_answers=[]`, `jev_choice_distribution={}`, `jev_failures=[]`, and `overall=fail`. The stored child metadata and `coverage.json` show the authorization child was passed skill IDs such as `vulnerabilities/idor`, `vulnerabilities/broken_function_level_authorization`, and `vulnerabilities/business_logic`. In the old policy, `apply_hard_rules` lowercased the entire ID then compared it against bare labels `idor`, `business_logic`, and `broken_function_level_authorization`; those comparisons were false. As a result `ask_jev` remained false and `HybridModelRouter.route` returned from its rule-floor branch before calling the client. The same namespace mismatch in the adapter allowlist would have sent an empty `skills` list even if a caller opened JEV.

The seam is visible in [runner.py](../../strix/core/runner.py#L605): the spawn path passes the original skill strings to `Envelope`; policy canonicalizes a namespaced ID to its final label at [policy.py](../../strix/routing/policy.py#L36), and the JEV allowlist uses that same normalizer at [jev.py](../../strix/routing/jev.py#L59). A real call still uses the fixed contract `model=typesafe/jev`, `questions.route_tier` with type `choice`, and posts to `/systemone`. A validated `worker` / `specialist` / `expert` answer is bounded by the hard-rule floor/ceiling, configured tier availability, probability thresholds, and share governor before the final tier's configured model is bound and logged.

### Test-first evidence

The new policy and runner-level tests were first run before production edits:

```bash
UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True uv run --offline pytest tests/test_routing_policy.py::test_namespaced_skill_labels_open_the_jev_choice tests/test_routing_spawn.py::test_namespaced_scan_skill_reaches_jev_and_logs_bound_choice tests/test_routing_spawn.py::test_namespaced_open_choice_logs_jev_error_only_after_http_failure -q
```

RED exited **1** with five failing cases: three namespaced policy cases remained `ask_jev=False`; the spawn case logged Worker/`rule` without an HTTP request; and the error case had no JEV transport failure because it was bypassed. After normalizing both policy matching and adapter metadata, the same command exited **0**, **5 passed**. One intermediate run after the production change exited **1** only because caplog was scoped to the runner logger and did not capture the JEV logger; the test capture scope was corrected, then the same command passed. The green spawn assertion verifies a real mocked transport path through the runner closure: it captured `typesafe/jev`, `route_tier`, canonical allowlisted `idor`, the `specialist` choice, and a `reason=jev` Specialist/MiMo route log. The separate HTTP 503 case verifies `reason=jev_error` only when transport raises `HTTPStatusError` and falls back to the rule floor.

### Completed real quick scan evidence

The protected environment was sourced with shell tracing disabled. The exact verifier invocation was:

```bash
set +x
set -a; . /home/hieuit095/.strix-live.env; set +a
trap 'unset LLM_API_KEY CMD_API_KEY COMMAND_CODE_API_BASE LLM_API_BASE STRIX_LLM STRIX_API_TYPE STRIX_REASONING_EFFORT LLM_TIMEOUT STRIX_ROUTING_LIVE_TESTS STRIX_ROUTING_ENABLED STRIX_ROUTING_SPECIALIST_MODEL STRIX_ROUTING_EXPERT_MODEL STRIX_ROUTING_JEV_ENABLED STRIX_ROUTING_JEV_POLICY_VERIFIED STRIX_ROUTING_SPECIALIST_THRESHOLD STRIX_ROUTING_EXPERT_THRESHOLD STRIX_ROUTING_SPECIALIST_CAP STRIX_ROUTING_EXPERT_CAP' EXIT
export STRIX_ROUTING_ENABLED=true STRIX_ROUTING_SPECIALIST_MODEL='openai/xiaomi/mimo-v2.6-pro' STRIX_ROUTING_EXPERT_MODEL='openai/gpt-6.1-sol'
export STRIX_ROUTING_JEV_ENABLED=true STRIX_ROUTING_JEV_POLICY_VERIFIED=1
export STRIX_ROUTING_SPECIALIST_THRESHOLD=0.65 STRIX_ROUTING_EXPERT_THRESHOLD=0.65 STRIX_ROUTING_SPECIALIST_CAP=0.25 STRIX_ROUTING_EXPERT_CAP=0.05
UV_CACHE_DIR=/tmp/strix-uv-cache LITELLM_LOCAL_MODEL_COST_MAP=True uv run --offline python scripts/verify_hybrid_routing.py --target http://host.docker.internal:5173 --timeout-seconds 10800
```

The verifier exited **0**. Its offline portion exited **0** (**90 passed**), the target probe returned HTTP **200**, and the Strix QUICK scan exited **2** because it filed a report; persisted status was **completed**. The completed scan's own evidence is [routing-verification.json](../../strix_runs/host-docker-internal-5173_9145/routing-verification.json), `overall=pass`, `jev_path=pass`; its route and answer log is [strix.log](../../strix_runs/host-docker-internal-5173_9145/strix.log).

The scan logged six child decisions and all six matched saved model bindings: Worker **3** (`openai/deepseek/deepseek-v4.1-flash`) and Specialist **3** (`openai/xiaomi/mimo-v2.6-pro`). Four `route_tier` requests to `typesafe/jev` returned `choice=specialist`; safe usage logs recorded respectively **414/42**, **416/42**, **413/42**, and **416/42** input/output tokens. The four scan decisions carried `reason=jev` and that choice. Three selected the Specialist/MiMo model; one stayed Worker/DeepSeek because the specialist probability did not meet the configured **0.65** threshold. The other two Worker children had closed rule choices and correctly logged `reason=rule`, without a JEV request. No JEV failures occurred.

No Expert route was observed: all four valid JEV choices were `specialist`, which cannot request Expert under the router's choice ceiling; the test did not observe an Expert choice or Expert binding. Thus live Worker and Specialist choice/model bindings pass, while live Expert/GPT selection remains unverified (the configured model is `openai/gpt-6.1-sol`; live entitlement was previously HTTP 403 `MODEL_NOT_IN_PLAN`).

Usage was **205 provider requests**, **21,626,792 input + 255,031 output = 21,881,823 tokens**, with estimated cost **USD 0.7686115896** against the USD 5 limit (estimate, not provider billing). Coverage recorded **60 surfaces**, **32 gaps**, and **1 report filed**; outcomes: 2 reported, 16 no-issue-found, 10 ruled-out, 1 not-applicable, 31 needs-follow-up. This is completed bounded coverage, not a ground-truth parity or clean-scan claim. The isolated target remained read-only at source HEAD `6c0fc01e7f969bbf75ef663606aa4a4d7c747620`; Vite and the isolated Supabase services were stopped after the scan.

### Current assertion status

- **PASS:** namespaced IDOR, business-logic, and BFLA labels open policy choices; JEV receives only canonical allowlisted labels.
- **PASS:** scan-path `ask_jev` reaches the real `typesafe/jev` System One endpoint and `route_tier` choice parser; four answers are matched to four `reason=jev` decisions in the scan log.
- **PASS:** all six route-log tier/model pairs match persisted bindings; JEV Specialist answers select MiMo when the threshold permits, while one below-threshold answer remains Worker/DeepSeek.
- **PASS:** `jev_error` fallback is emitted in the runner integration test only after the fake transport returns HTTP 503 and raises `HTTPStatusError`; live scan had zero JEV failures.
- **NOT OBSERVED:** live Expert/GPT decision. JEV answered Specialist four times and never Expert.
- **INCOMPLETE:** off/floor-only/JEV-on quality parity, independent ground-truth/PoC review, routed-child resume in a live scan, and actual billing reconciliation.
