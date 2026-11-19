"""Bandit security static analysis integration.

Invokes Bandit in JSON mode as an isolated subprocess without shell=True.
Bandit findings are reported with their original severity/confidence and
framed cautiously rather than automatically claiming confirmed exploitability.
"""

import hashlib
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

from app.schemas.scan import (
    ConfidenceLevel,
    FindingRecord,
    ScannerToolSummary,
    SeverityLevel,
)
from app.utils.file_utils import is_python_test_path

BANDIT_LIMITATIONS = [
    "Bandit uses heuristic security rules and may produce false positives; review findings in context.",
    "Bandit B101 (use of assert) is suppressed in Python test files where assert is idiomatic.",
]

_SEVERITY_MAP: dict[str, SeverityLevel] = {
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
    "INFO": "INFO",
}

_CONFIDENCE_MAP: dict[str, ConfidenceLevel] = {
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
}


@dataclass
class BanditScanOutcome:
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


def _finding_id(rule_id: str, file_path: str, line: int, col: Optional[int]) -> str:
    digest = hashlib.sha1(
        f"bandit:{rule_id}:{file_path}:{line}:{col or 0}".encode("utf-8")
    ).hexdigest()[:12]
    return f"fnd-{digest}"


def _suggested_fix_for_bandit(test_id: str) -> str:
    fixes = {
        "B105": "Move hardcoded credentials to environment variables or a secret manager.",
        "B106": "Avoid passing hardcoded password string literals; load secrets from configuration.",
        "B107": "Avoid hardcoded default password values.",
        "B108": "Use tempfile.NamedTemporaryFile or tempfile.TemporaryDirectory instead of predictable /tmp paths.",
        "B301": "Avoid pickle on untrusted inputs; use JSON or another safe serialization format.",
        "B303": "Replace weak hash algorithms (MD5/SHA1) with SHA-256 or a password-hashing library.",
        "B307": "Avoid eval(); use ast.literal_eval() for literals or explicit parsing.",
        "B506": "Use yaml.safe_load() instead of yaml.load().",
        "B602": "Avoid shell=True in subprocess calls; pass an explicit argument list.",
        "B605": "Avoid os.system()/os.popen(); use subprocess.run([...], shell=False).",
        "B608": "Use parameterized SQL queries instead of string formatting or concatenation.",
    }
    return fixes.get(test_id, "Review the flagged pattern to confirm whether untrusted input can reach it.")


def run_bandit_scan(
    project_root: Path, rel_files: Sequence[str], timeout_seconds: int
) -> BanditScanOutcome:
    """Run Bandit against validated relative Python paths inside `project_root`."""
    started = time.monotonic()
    if not rel_files:
        return BanditScanOutcome(
            summary=ScannerToolSummary(
                status="skipped",
                findings_count=0,
                duration_ms=0,
                limitations=list(BANDIT_LIMITATIONS),
            )
        )

    cmd = [
        sys.executable,
        "-m",
        "bandit",
        "-f",
        "json",
        "-q",
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
        return BanditScanOutcome(
            summary=ScannerToolSummary(
                status="timed_out",
                duration_ms=duration_ms,
                error=f"Bandit timed out after {timeout_seconds}s.",
                limitations=list(BANDIT_LIMITATIONS),
            )
        )
    except FileNotFoundError:
        duration_ms = int((time.monotonic() - started) * 1000)
        return BanditScanOutcome(
            summary=ScannerToolSummary(
                status="unavailable",
                duration_ms=duration_ms,
                error="Bandit executable was not found.",
                limitations=list(BANDIT_LIMITATIONS),
            )
        )
    except OSError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return BanditScanOutcome(
            summary=ScannerToolSummary(
                status="failed",
                duration_ms=duration_ms,
                error=f"Failed to execute Bandit: {type(exc).__name__}.",
                limitations=list(BANDIT_LIMITATIONS),
            )
        )

    duration_ms = int((time.monotonic() - started) * 1000)

    # Bandit returns 0 (no issues) or 1 (issues found). Higher codes indicate an error.
    if proc.returncode not in (0, 1):
        stderr = (proc.stderr or "").strip()
        if "No module named bandit" in stderr:
            return BanditScanOutcome(
                summary=ScannerToolSummary(
                    status="unavailable",
                    duration_ms=duration_ms,
                    error="Bandit package is not installed in this Python environment.",
                    limitations=list(BANDIT_LIMITATIONS),
                )
            )
        return BanditScanOutcome(
            summary=ScannerToolSummary(
                status="failed",
                duration_ms=duration_ms,
                error=f"Bandit exited with code {proc.returncode}.",
                limitations=list(BANDIT_LIMITATIONS),
            )
        )

    stdout = (proc.stdout or "").strip()
    if not stdout:
        return BanditScanOutcome(
            summary=ScannerToolSummary(
                status="completed",
                findings_count=0,
                duration_ms=duration_ms,
                limitations=list(BANDIT_LIMITATIONS),
            )
        )

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return BanditScanOutcome(
            summary=ScannerToolSummary(
                status="failed",
                duration_ms=duration_ms,
                error="Bandit returned malformed JSON output.",
                limitations=list(BANDIT_LIMITATIONS),
            )
        )

    if not isinstance(payload, dict):
        return BanditScanOutcome(
            summary=ScannerToolSummary(
                status="failed",
                duration_ms=duration_ms,
                error="Bandit JSON output had an unexpected format.",
                limitations=list(BANDIT_LIMITATIONS),
            )
        )

    raw_results = payload.get("results") or []
    findings: List[FindingRecord] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        test_id = str(item.get("test_id") or "BANDIT")
        rel_path = _sanitize_rel_path(str(item.get("filename") or ""), project_root)
        if test_id.upper() == "B101" and is_python_test_path(rel_path):
            continue
        test_name = str(item.get("test_name") or "security_pattern")
        issue_text = str(item.get("issue_text") or "Potential security issue flagged by Bandit.")
        orig_sev = str(item.get("issue_severity") or "MEDIUM").upper()
        orig_conf = str(item.get("issue_confidence") or "MEDIUM").upper()

        severity = _SEVERITY_MAP.get(orig_sev, "MEDIUM")
        confidence = _CONFIDENCE_MAP.get(orig_conf, "MEDIUM")
        line_number = int(item.get("line_number") or 1)
        col_offset = item.get("col_offset")
        column = int(col_offset) + 1 if isinstance(col_offset, int) else None
        code_snippet = str(item.get("code") or "").strip()

        findings.append(
            FindingRecord(
                id=_finding_id(test_id, rel_path, line_number, column),
                file_path=rel_path,
                line_number=line_number,
                column=column,
                tool="bandit",
                rule_id=test_id,
                category="security",
                severity=severity,
                confidence=confidence,
                original_severity=orig_sev,
                original_confidence=orig_conf,
                title=f"Potential security issue ({test_id}): {test_name.replace('_', ' ')}",
                description=issue_text,
                evidence=code_snippet,
                suggested_fix=_suggested_fix_for_bandit(test_id),
            )
        )

    return BanditScanOutcome(
        findings=findings,
        summary=ScannerToolSummary(
            status="completed",
            findings_count=len(findings),
            duration_ms=duration_ms,
            limitations=list(BANDIT_LIMITATIONS),
        ),
    )
