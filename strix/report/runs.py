"""Summaries of the runs under ./strix_runs, for pickers and listings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from strix.core.paths import run_record_path, runs_base_dir, runtime_state_dir


if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class RunSummary:
    run_name: str
    target: str
    started_at: str
    ended_at: str
    status: str
    findings: int
    resumable: bool


def _json_list_length(value: object) -> int:
    if not isinstance(value, list):
        return 0
    return len(cast("list[object]", value))


def list_run_summaries(*, cwd: Path | None = None) -> list[RunSummary]:
    """Every run with a run.json, newest activity first (run.json mtime)."""
    base = runs_base_dir(cwd=cwd)
    if not base.is_dir():
        return []
    rows: list[tuple[float, RunSummary]] = []
    for child in base.iterdir():
        record_path = run_record_path(child)
        try:
            if not record_path.is_file():
                continue
            modified = record_path.stat().st_mtime
        except OSError:
            continue
        rows.append((modified, _summarize(child, _load_json(record_path, default={}))))
    rows.sort(key=lambda row: (row[0], row[1].run_name), reverse=True)
    return [summary for _, summary in rows]


def _summarize(run_dir: Path, record: Any) -> RunSummary:
    if not isinstance(record, dict):
        record = {}
    record = cast("dict[str, Any]", record)
    empty_findings: list[Any] = []
    findings = _load_json(run_dir / "vulnerabilities.json", default=empty_findings)
    return RunSummary(
        run_name=run_dir.name,
        target=_describe_target(record),
        started_at=str(record.get("start_time") or ""),
        ended_at=str(record.get("end_time") or ""),
        status=str(record.get("status") or "unknown"),
        findings=_json_list_length(findings),
        resumable=(runtime_state_dir(run_dir) / "agents.json").is_file(),
    )


def _describe_target(record: dict[str, Any]) -> str:
    targets_value: Any = record.get("targets_info")
    if not isinstance(targets_value, list):
        targets_value = []
    targets: list[Any] = cast("Any", targets_value)
    originals: list[str] = []
    for entry in targets:
        if isinstance(entry, dict):
            target_entry = cast("dict[str, Any]", entry)
            if target_entry.get("original"):
                originals.append(str(target_entry["original"]))
    if originals:
        if len(originals) == 1:
            return originals[0]
        return f"{originals[0]} +{len(originals) - 1} more"
    mount = record.get("workspace_mount")
    if isinstance(mount, str) and mount:
        return f"{mount} (workspace)"
    instruction = str(record.get("user_instruction") or record.get("instruction") or "").strip()
    return instruction.splitlines()[0] if instruction else ""


def _load_json(path: Path, *, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


__all__ = ["RunSummary", "list_run_summaries"]
