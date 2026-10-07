#!/usr/bin/env python3
"""Run deterministic routing assertions, then a bounded local live smoke."""

# ruff: noqa: T201

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from strix.config import load_settings


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "strix_runs"
EXPECTED_MODELS = {
    "worker": "openai/deepseek/deepseek-v4.1-flash",
    "specialist": "openai/xiaomi/mimo-v2.6-pro",
}
ROUTE_LINE = re.compile(
    r"child routing tier=(worker|specialist|expert) model=([^ ]+) reason=([a-z_]+) "
    r"jev_choice=(worker|specialist|expert|none)"
)
JEV_ANSWER_LINE = re.compile(
    r"JEV routing answer choice=(worker|specialist|expert) input_tokens=(\d+) output_tokens=(\d+)"
)
JEV_FAILURE_LINE = re.compile(
    r"JEV routing failed \(([A-Za-z][A-Za-z0-9_]*)\); using the rule floor"
)


def report(status: str, name: str, detail: str) -> bool:
    print(f"{status} {name}: {detail}")
    return status == "PASS"


def _preflight() -> tuple[dict[str, str], dict[str, float], bool, Path, list[str]]:
    env = os.environ
    settings = {
        "worker": env.get("STRIX_LLM", ""),
        "specialist": env.get("STRIX_ROUTING_SPECIALIST_MODEL", ""),
    }
    failures: list[str] = []
    if env.get("STRIX_ROUTING_ENABLED", "").lower() != "true":
        failures.append("STRIX_ROUTING_ENABLED must be true")
    if not env.get("LLM_API_KEY", "").strip():
        failures.append("LLM_API_KEY must be supplied by the protected environment")
    if env.get("LLM_API_BASE", "").rstrip("/") != "https://api.commandcode.ai/provider/v1":
        failures.append("LLM_API_BASE must use the CommandCode provider base")
    if env.get("STRIX_API_TYPE") != "chat_completions":
        failures.append("STRIX_API_TYPE must be chat_completions")
    if env.get("STRIX_ROUTING_EXPERT_MODEL", "").strip():
        failures.append("expert model configuration is no longer supported")
    for tier, expected in EXPECTED_MODELS.items():
        if settings[tier] != expected:
            failures.append(f"{tier} model must be configured as {expected}")
    route_policy = {
        "specialist_threshold": float(env.get("STRIX_ROUTING_SPECIALIST_THRESHOLD", "0.65")),
        "specialist_cap": float(env.get("STRIX_ROUTING_SPECIALIST_CAP", "0.25")),
    }
    if route_policy != {
        "specialist_threshold": 0.65,
        "specialist_cap": 0.25,
    }:
        failures.append("specialist threshold/cap must be 0.65/0.25")

    settings_model = load_settings()
    jev_enabled = settings_model.routing.jev_enabled
    if not jev_enabled:
        failures.append("STRIX_ROUTING_JEV_ENABLED must be true for this verification")
    zdr_required = any(
        key.lower() == "x-cmd-zdr" and value.strip() == "1"
        for key, value in (settings_model.llm.extra_headers or {}).items()
    )
    if jev_enabled and zdr_required:
        failures.append("JEV cannot be enabled while x-cmd-zdr: 1 is configured")
    if jev_enabled and env.get("STRIX_ROUTING_JEV_POLICY_VERIFIED") != "1":
        failures.append(
            "JEV is enabled but STRIX_ROUTING_JEV_POLICY_VERIFIED=1 was not supplied; "
            "non-ZDR metadata approval is required"
        )
    rate_runner = Path(
        env.get(
            "STRIX_ROUTING_RATE_RUNNER",
            "/tmp/strix-hybrid-rate-runner.py",  # noqa: S108 - operator-local rate helper
        )
    )
    if not rate_runner.is_file():
        failures.append(
            "operator-local reviewed-rate runner is unavailable at "
            f"{rate_runner}; the scan budget estimator cannot be verified"
        )
    return settings, route_policy, jev_enabled, rate_runner, failures


def _probe_target() -> int | None:
    request = urllib.request.Request("http://127.0.0.1:5173/", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return response.status
    except (OSError, urllib.error.URLError):
        return None


def _new_run(before: set[str]) -> Path | None:
    candidates = [
        path
        for path in RUNS.iterdir()
        if path.is_dir() and path.name not in before and (path / "run.json").is_file()
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def _load_routes(
    run_dir: Path,
) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    log_path = run_dir / "strix.log"
    text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    decisions = [
        {
            "tier": match.group(1),
            "model": match.group(2),
            "reason": match.group(3),
            "jev_choice": None if match.group(4) == "none" else match.group(4),
        }
        for match in ROUTE_LINE.finditer(text)
    ]
    jev_answers = [
        {
            "choice": match.group(1),
            "input_tokens": int(match.group(2)),
            "output_tokens": int(match.group(3)),
        }
        for match in JEV_ANSWER_LINE.finditer(text)
    ]
    jev_failures = [match.group(1) for match in JEV_FAILURE_LINE.finditer(text)]
    state_path = run_dir / ".state" / "agents.json"
    if not state_path.exists():
        return decisions, [], jev_answers, jev_failures
    state = json.loads(state_path.read_text(encoding="utf-8"))
    metadata = state.get("metadata") or {}
    bindings = [
        value["routing"]
        for value in metadata.values()
        if isinstance(value, dict) and isinstance(value.get("routing"), dict)
    ]
    return decisions, bindings, jev_answers, jev_failures


def jev_evidence_matches(
    decisions: list[dict[str, Any]], answers: list[dict[str, Any]], failures: list[str]
) -> bool:
    answered = sum(row["reason"] in {"jev", "governor"} for row in decisions)
    errored = sum(row["reason"] == "jev_error" for row in decisions)
    return len(answers) == answered and len(failures) == errored


def jev_choice_evidence_matches(decisions: list[dict[str, Any]]) -> bool:
    return all(
        (row["reason"] in {"jev", "governor"}) == (row.get("jev_choice") is not None)
        for row in decisions
    )


def run() -> int:  # noqa: PLR0912, PLR0915
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="http://host.docker.internal:5173")
    parser.add_argument("--timeout-seconds", type=int, default=10800)
    args = parser.parse_args()

    if args.target not in {
        "http://host.docker.internal:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    }:
        parser.error("--target must be the authorized local Vite app on port 5173")

    os.chdir(ROOT)
    passed = True
    offline = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_routing_verification.py",
            "tests/test_routing_router.py",
            "tests/test_routing_jev.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    summary = next(
        (line.strip() for line in reversed(offline.stdout.splitlines()) if " passed" in line),
        "pytest output has no passing summary",
    )
    passed &= report(
        "PASS" if offline.returncode == 0 else "FAIL",
        "offline deterministic routing assertions",
        f"exit={offline.returncode}; {summary}",
    )
    if offline.returncode:
        print(offline.stdout)
        print(offline.stderr, file=sys.stderr)
        return 1

    models, route_policy, jev_enabled, rate_runner, failures = _preflight()
    if failures:
        for failure in failures:
            passed &= report("FAIL", "live preflight", failure)
        return 1
    target_status = _probe_target()
    passed &= report(
        "PASS" if target_status == 200 else "FAIL",
        "authorized local target probe",
        f"HTTP {target_status if target_status is not None else 'unreachable'}",
    )
    if target_status != 200:
        return 1

    before = {path.name for path in RUNS.iterdir() if path.is_dir()}
    instruction = (
        "Perform a read-only quick security scan of the authorized local application. "
        "Prioritize authorization boundaries, IDOR, broken function-level authorization, and "
        "business-logic flows where relevant. Use Strix's normal child-agent workflow when a "
        "separate validation task is warranted; do not force a tier/model or invent a finding. "
        "Do not modify files, use destructive actions, or test external services."
    )
    command = [
        "timeout",
        f"{args.timeout_seconds}s",
        sys.executable,
        str(rate_runner),
        "--run-scan",
        "-n",
        "-t",
        args.target,
        "--scan-mode",
        "quick",
        "--max-budget",
        "5",
        "--instruction",
        instruction,
    ]
    print(
        "LIVE_COMMAND: timeout <seconds>s python /tmp/strix-hybrid-rate-runner.py "
        "--run-scan -n "
        f"-t {args.target} --scan-mode quick --max-budget 5 --instruction "
        "'<read-only local target instruction>'"
    )
    timeout_bin = shutil_which_timeout()
    if timeout_bin is None:
        passed &= report("FAIL", "live bounded scan", "GNU timeout command is unavailable")
        return 1
    command[0] = timeout_bin
    os.environ["AUTHORIZED_FIXTURE_TARGET"] = args.target
    try:
        scan = subprocess.run(  # noqa: S603
            command,
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        scan_exit = scan.returncode
    except OSError:
        scan_exit = 127
    run_dir = _new_run(before)
    if run_dir is None:
        passed &= report("FAIL", "live bounded scan", f"exit={scan_exit}; no run.json created")
        return 1

    run_data = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    status = run_data.get("status")
    scan_complete = (
        status == "completed" and run_data.get("scan_mode") == "quick" and scan_exit in (0, 2)
    )
    passed &= report(
        "PASS" if scan_complete else "FAIL",
        "live bounded quick scan completion",
        f"run={run_dir.name}; exit={scan_exit}; status={status}",
    )

    usage = run_data.get("llm_usage") or {}
    cost_value = usage.get("cost")
    cost_ok = isinstance(cost_value, int | float) and 0 < cost_value <= 5.0
    passed &= report(
        "PASS" if cost_ok else "FAIL",
        "budget usage accounting",
        f"estimated_cost={cost_value}; cap=5.00 USD",
    )
    root_models = {
        str(agent.get("model"))
        for agent in usage.get("agents", [])
        if agent.get("agent_name") == "Root Agent"
    }
    root_ok = root_models == {models["worker"]}
    passed &= report(
        "PASS" if root_ok else "FAIL",
        "worker model",
        f"expected={models['worker']}; observed={','.join(sorted(root_models)) or 'none'}",
    )

    decisions, bindings, jev_answers, jev_failures = _load_routes(run_dir)
    expected_by_tier = EXPECTED_MODELS
    log_matches = all(
        row["tier"] in expected_by_tier
        and row["model"] == expected_by_tier[row["tier"]]
        and row["reason"] in {"rule", "jev", "jev_error", "governor"}
        for row in decisions
    )
    binding_matches = all(
        binding.get("tier") in expected_by_tier
        and binding.get("model") == expected_by_tier[binding.get("tier")]
        for binding in bindings
    )
    paired = Counter((row["tier"], row["model"]) for row in decisions) == Counter(
        (binding.get("tier"), binding.get("model")) for binding in bindings
    )
    passed &= report(
        "PASS" if decisions and log_matches and binding_matches and paired else "FAIL",
        "child routing log and persisted bindings",
        f"decisions={len(decisions)}; bindings={len(bindings)}; "
        f"tiers={dict(Counter(row['tier'] for row in decisions))}",
    )
    tier_distribution = dict(Counter(row["tier"] for row in decisions))
    jev_choice_distribution = dict(
        Counter(row["jev_choice"] for row in decisions if row["jev_choice"])
    )
    choice_routes = [
        (row["jev_choice"], row["tier"], row["reason"]) for row in decisions if row["jev_choice"]
    ]
    if any(row["tier"] == "expert" for row in decisions):
        passed &= report("FAIL", "expert tier removed", "an expert child route was logged")
    else:
        passed &= report(
            "PASS", "expert tier removed", "no expert routing tier is configured or logged"
        )
    jev_routes = [row for row in decisions if row["reason"] in {"jev", "governor"}]
    jev_choices_bound = (
        bool(jev_answers)
        and bool(jev_routes)
        and all(
            row.get("jev_choice") in {"worker", "specialist", "expert"}
            and row["tier"] in expected_by_tier
            for row in jev_routes
        )
    )
    passed &= report(
        "PASS" if jev_choices_bound else "FAIL",
        "JEV choices remain within two-model map",
        f"answers={len(jev_answers)}; JEV-bound decisions={len(jev_routes)}; "
        f"tiers={dict(Counter(row['tier'] for row in jev_routes))}",
    )
    for tier in ("worker", "specialist"):
        seen = any(row["tier"] == tier for row in decisions)
        if seen:
            passed &= report("PASS", f"observed {tier} route", models[tier])
        elif jev_enabled:
            passed &= report(
                "PASS",
                f"{tier} route distribution",
                f"no {tier} child; tiers={tier_distribution}; "
                f"JEV choices={jev_choice_distribution}; choice-to-tier/reason={choice_routes}",
            )
        else:
            report(
                "SKIP",
                f"observed {tier} route",
                "quick scan emitted no child decision for this tier",
            )

    if jev_enabled:
        jev_seen = any(row["reason"] == "jev" for row in decisions)
        evidence_matches = jev_evidence_matches(decisions, jev_answers, jev_failures)
        choice_matches = jev_choice_evidence_matches(decisions)
        passed &= report(
            "PASS" if jev_seen and evidence_matches and choice_matches else "FAIL",
            "JEV path",
            f"enabled; jev decisions={sum(row['reason'] == 'jev' for row in decisions)}; "
            f"answers={len(jev_answers)}; jev_error decisions="
            f"{sum(row['reason'] == 'jev_error' for row in decisions)}; "
            f"matching failures={len(jev_failures)}; evidence_matches={evidence_matches}; "
            f"choice_matches={choice_matches}"
            if jev_seen and evidence_matches and choice_matches
            else f"no valid live JEV evidence: jev_decision={jev_seen}; "
            f"evidence_matches={evidence_matches}; choice_matches={choice_matches}",
        )
    else:
        report(
            "SKIP",
            "JEV path",
            "JEV disabled; model availability and non-ZDR policy approval are not verified",
        )

    coverage_path = run_dir / "coverage.json"
    coverage = (
        json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else {}
    )
    summary_data = coverage.get("summary") or {}
    finding_path = run_dir / "vulnerabilities.json"
    findings = json.loads(finding_path.read_text(encoding="utf-8")) if finding_path.exists() else []
    evidence = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "command": (
            "timeout <seconds>s python /tmp/strix-hybrid-rate-runner.py --run-scan "
            "-n -t <local-target> "
            "--scan-mode quick --max-budget 5 (STRIX_ROUTING_JEV_ENABLED=true)"
        ),
        "run_name": run_dir.name,
        "target_url": args.target,
        "scan_exit_code": scan_exit,
        "scan_status": status,
        "models": models,
        "routing_policy": route_policy,
        "routing_decisions": decisions,
        "tier_distribution": tier_distribution,
        "jev_choice_distribution": jev_choice_distribution,
        "jev_answers": jev_answers,
        "jev_failures": jev_failures,
        "persisted_bindings": bindings,
        "coverage": {
            key: summary_data.get(key)
            for key in ("surfaces_reviewed", "findings_filed", "gaps", "outcomes")
        },
        "findings_count": len(findings),
        "llm_usage": {
            key: usage.get(key)
            for key in ("requests", "input_tokens", "output_tokens", "total_tokens", "cost")
        },
        "jev_path": (
            "pass"
            if jev_enabled
            and bool(jev_answers)
            and bool(jev_routes)
            and jev_choices_bound
            and any(row["reason"] == "jev" for row in decisions)
            and jev_evidence_matches(decisions, jev_answers, jev_failures)
            and jev_choice_evidence_matches(decisions)
            else "fail: JEV enabled without matched evidence"
        ),
        "overall": "pass" if passed else "fail",
    }
    evidence_path = run_dir / "routing-verification.json"
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "LIVE_EVIDENCE: "
        f"{evidence_path.relative_to(ROOT)}; findings={len(findings)}; "
        f"coverage={evidence['coverage']}; usage={evidence['llm_usage']}"
    )
    return 0 if passed else 1


def shutil_which_timeout() -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / "timeout"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


if __name__ == "__main__":
    raise SystemExit(run())
