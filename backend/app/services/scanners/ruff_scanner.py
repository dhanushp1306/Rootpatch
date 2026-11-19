"""Ruff static analysis integration.

Invokes Ruff in JSON output mode as an isolated subprocess without shell=True
and without executing any uploaded code.
"""

import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from app.schemas.scan import (
    ConfidenceLevel,
    FindingRecord,
    ScannerToolSummary,
    SeverityLevel,
)
from app.utils.file_utils import is_python_test_path

RUFF_LIMITATIONS = [
    "Ruff runs with --isolated and --no-cache so uploaded project configs cannot alter scanner behavior.",
    "Ruff S101 (use of assert) is suppressed in Python test files where assert is idiomatic.",
]


@dataclass
class RuffScanOutcome:
    findings: List[FindingRecord] = field(default_factory=list)
    summary: ScannerToolSummary = field(
        default_factory=lambda: ScannerToolSummary(status="completed")
    )


def _sanitize_rel_path(raw_filename: str, project_root: Path) -> str:
    if not raw_filename:
        return "unknown"
    candidate = Path(raw_filename)
    root_resolved = project_root.resolve()
    try:
        if candidate.is_absolute():
            return candidate.resolve().relative_to(root_resolved).as_posix()
        rel = candidate.as_posix()
        return rel[2:] if rel.startswith("./") else rel
    except ValueError:
        return candidate.name


def _map_ruff_rule(code: str) -> Tuple[str, SeverityLevel, ConfidenceLevel]:
    upper = code.upper()
    if upper in {"E999"} or upper.startswith("E9"):
        return "syntax", "HIGH", "HIGH"
    if upper in {"F821", "F822", "F823"}:
        return "runtime", "HIGH", "HIGH"
    if upper in {"F401", "F841", "F811"}:
        return "quality", "LOW", "HIGH"
    if upper.startswith("S"):
        return "security", "MEDIUM", "MEDIUM"
    if upper.startswith("B"):
        return "suspicious", "MEDIUM", "MEDIUM"
    if upper.startswith("F"):
        return "runtime", "MEDIUM", "HIGH"
    if upper.startswith(("E", "W")):
        return "quality", "LOW", "HIGH"
    return "quality", "INFO", "MEDIUM"


def _finding_id(rule_id: str, file_path: str, line: int, col: Optional[int]) -> str:
    digest = hashlib.sha1(
        f"ruff:{rule_id}:{file_path}:{line}:{col or 0}".encode("utf-8")
    ).hexdigest()[:12]
    return f"fnd-{digest}"


def _read_evidence_line(project_root: Path, rel_path: str, line_number: int) -> str:
    try:
        target = (project_root / rel_path).resolve()
        target.relative_to(project_root.resolve())
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        if 1 <= line_number <= len(lines):
            return lines[line_number - 1].strip()
    except (OSError, ValueError):
        pass
    return ""


def run_ruff_scan(
    project_root: Path, rel_files: Sequence[str], timeout_seconds: int
) -> RuffScanOutcome:
    """Run Ruff against validated relative Python paths inside `project_root`."""
    started = time.monotonic()
    if not rel_files:
        return RuffScanOutcome(
            summary=ScannerToolSummary(
                status="skipped", findings_count=0, duration_ms=0, limitations=list(RUFF_LIMITATIONS)
            )
        )

    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--output-format",
        "json",
        "--no-fix",
        "--no-cache",
        "--isolated",
        "--select",
        "E,F,W,B,S",
        "--",
        *rel_files,
    ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - started) * 1000)
        return RuffScanOutcome(
            summary=ScannerToolSummary(
                status="timed_out",
                duration_ms=duration_ms,
                error=f"Ruff timed out after {timeout_seconds}s.",
                limitations=list(RUFF_LIMITATIONS),
            )
        )
    except FileNotFoundError:
        duration_ms = int((time.monotonic() - started) * 1000)
        return RuffScanOutcome(
            summary=ScannerToolSummary(
                status="unavailable",
                duration_ms=duration_ms,
                error="Ruff executable was not found.",
                limitations=list(RUFF_LIMITATIONS),
            )
        )
    except OSError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return RuffScanOutcome(
            summary=ScannerToolSummary(
                status="failed",
                duration_ms=duration_ms,
                error=f"Failed to execute Ruff: {type(exc).__name__}.",
                limitations=list(RUFF_LIMITATIONS),
            )
        )

    duration_ms = int((time.monotonic() - started) * 1000)

    if proc.returncode not in (0, 1):
        stderr = (proc.stderr or "").strip()
        if "No module named ruff" in stderr:
            return RuffScanOutcome(
                summary=ScannerToolSummary(
                    status="unavailable",
                    duration_ms=duration_ms,
                    error="Ruff package is not installed in this Python environment.",
                    limitations=list(RUFF_LIMITATIONS),
                )
            )
        return RuffScanOutcome(
            summary=ScannerToolSummary(
                status="failed",
                duration_ms=duration_ms,
                error=f"Ruff exited with code {proc.returncode}.",
                limitations=list(RUFF_LIMITATIONS),
            )
        )

    stdout = (proc.stdout or "").strip()
    if not stdout:
        return RuffScanOutcome(
            summary=ScannerToolSummary(
                status="completed",
                findings_count=0,
                duration_ms=duration_ms,
                limitations=list(RUFF_LIMITATIONS),
            )
        )

    try:
        items = json.loads(stdout)
    except json.JSONDecodeError:
        return RuffScanOutcome(
            summary=ScannerToolSummary(
                status="failed",
                duration_ms=duration_ms,
                error="Ruff returned malformed JSON output.",
                limitations=list(RUFF_LIMITATIONS),
            )
        )

    if not isinstance(items, list):
        return RuffScanOutcome(
            summary=ScannerToolSummary(
                status="failed",
                duration_ms=duration_ms,
                error="Ruff JSON output had an unexpected format.",
                limitations=list(RUFF_LIMITATIONS),
            )
        )

    findings: List[FindingRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "RUFF")
        loc = item.get("location") or {}
        line_number = int(loc.get("row") or 1)
        col = loc.get("column")
        column = int(col) if isinstance(col, int) else None
        rel_path = _sanitize_rel_path(str(item.get("filename") or ""), project_root)
        if code.upper() == "S101" and is_python_test_path(rel_path):
            continue
        message = str(item.get("message") or "Ruff rule violation")
        category, severity, confidence = _map_ruff_rule(code)

        fix_info = item.get("fix")
        suggested_fix = None
        if isinstance(fix_info, dict) and fix_info.get("message"):
            suggested_fix = str(fix_info["message"])

        findings.append(
            FindingRecord(
                id=_finding_id(code, rel_path, line_number, column),
                file_path=rel_path,
                line_number=line_number,
                column=column,
                tool="ruff",
                rule_id=code,
                category=category,
                severity=severity,
                confidence=confidence,
                original_severity=code,
                original_confidence=None,
                title=f"Ruff {code}: {message}",
                description=message,
                evidence=_read_evidence_line(project_root, rel_path, line_number),
                suggested_fix=suggested_fix,
            )
        )

    return RuffScanOutcome(
        findings=findings,
        summary=ScannerToolSummary(
            status="completed",
            findings_count=len(findings),
            duration_ms=duration_ms,
            limitations=list(RUFF_LIMITATIONS),
        ),
    )
