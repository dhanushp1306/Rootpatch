"""Orchestrates Step 3 static bug detection across AST, Ruff, and Bandit.

All analysis is purely static; uploaded code is never executed.
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from app.core.config import Settings
from app.core.errors import ProjectNotFoundError, ScanError, ScanNotFoundError
from app.schemas.scan import (
    FindingRecord,
    ScanResponse,
    ScannerToolSummary,
    SeverityLevel,
    SkippedScanFile,
)
from app.services.inspection_service import IGNORED_DIRECTORIES, find_project_root
from app.services.scanners.ast_scanner import run_ast_scan
from app.services.scanners.bandit_scanner import run_bandit_scan
from app.services.scanners.ruff_scanner import run_ruff_scan
from app.services.upload_service import SOURCE_DIR, _project_dir, load_project
from app.utils.file_utils import is_within_directory

SCAN_RESULT_NAME = "scan_result.json"
PYTHON_EXTENSIONS = frozenset({".py", ".pyw"})

_SEVERITY_ORDER: Dict[SeverityLevel, int] = {
    "CRITICAL": 5,
    "HIGH": 4,
    "MEDIUM": 3,
    "LOW": 2,
    "INFO": 1,
}

_SEMANTIC_RULE_GROUPS: Dict[Tuple[str, str], str] = {
    # Syntax error
    ("ast", "AST001"): "syntax-error",
    ("ruff", "E999"): "syntax-error",
    # Unused import
    ("ast", "AST301"): "unused-import",
    ("ruff", "F401"): "unused-import",
    # Undefined name
    ("ast", "AST401"): "undefined-name",
    ("ruff", "F821"): "undefined-name",
    # Shell execution
    ("ast", "AST104"): "shell-execution",
    ("ruff", "S602"): "shell-execution",
    ("ruff", "S605"): "shell-execution",
    ("bandit", "B602"): "shell-execution",
    ("bandit", "B605"): "shell-execution",
    # Dynamic code execution
    ("ast", "AST101"): "dynamic-exec",
    ("ruff", "S307"): "dynamic-exec",
    ("bandit", "B307"): "dynamic-exec",
    ("bandit", "B102"): "dynamic-exec",
    # Hardcoded credentials
    ("ast", "AST501"): "hardcoded-credential",
    ("ruff", "S105"): "hardcoded-credential",
    ("ruff", "S106"): "hardcoded-credential",
    ("bandit", "B105"): "hardcoded-credential",
    ("bandit", "B106"): "hardcoded-credential",
    ("bandit", "B107"): "hardcoded-credential",
    # Silent broad except
    ("ast", "AST201"): "silent-except",
    ("ruff", "E722"): "silent-except",
    ("ruff", "S110"): "silent-except",
    ("bandit", "B110"): "silent-except",
    # Unsafe deserialization
    ("ast", "AST103"): "unsafe-deserialization",
    ("ruff", "S301"): "unsafe-deserialization",
    ("bandit", "B301"): "unsafe-deserialization",
    # Unsafe YAML load
    ("ast", "AST105"): "unsafe-yaml",
    ("ruff", "S506"): "unsafe-yaml",
    ("bandit", "B506"): "unsafe-yaml",
    # Mutable default
    ("ast", "AST204"): "mutable-default",
    ("ruff", "B006"): "mutable-default",
    # Tuple assert
    ("ast", "AST205"): "tuple-assert",
    ("ruff", "F631"): "tuple-assert",
    # Duplicate dict key
    ("ast", "AST206"): "duplicate-dict-key",
    ("ruff", "F601"): "duplicate-dict-key",
    # Assert used in non-test code
    ("ruff", "S101"): "assert-used",
    ("bandit", "B101"): "assert-used",
}


def _collect_python_files(
    project_root: Path, max_files: int
) -> Tuple[List[str], List[SkippedScanFile]]:
    """Safely discover Python source files inside `project_root`."""
    resolved_root = project_root.resolve()
    rel_files: List[str] = []
    skipped: List[SkippedScanFile] = []
    truncated = False

    for dirpath, dirnames, filenames in os.walk(resolved_root, followlinks=False):
        dirnames.sort()
        filenames.sort()
        current = Path(dirpath)
        rel_dir = current.relative_to(resolved_root).as_posix()

        safe_dirs = []
        for d in dirnames:
            candidate_dir = current / d
            if candidate_dir.is_symlink():
                continue
            if d in IGNORED_DIRECTORIES or d.lower() in IGNORED_DIRECTORIES:
                continue
            if not is_within_directory(resolved_root, candidate_dir):
                continue
            safe_dirs.append(d)
        dirnames[:] = safe_dirs

        for name in filenames:
            full = current / name
            if full.is_symlink():
                continue
            if not is_within_directory(resolved_root, full):
                rel_bad = name if rel_dir == "." else f"{rel_dir}/{name}"
                skipped.append(
                    SkippedScanFile(file_path=rel_bad, reason="Path escapes project workspace.")
                )
                continue
            if Path(name).suffix.lower() not in PYTHON_EXTENSIONS:
                continue
            rel_path = name if rel_dir == "." else f"{rel_dir}/{name}"
            if len(rel_files) >= max_files:
                if not truncated:
                    skipped.append(
                        SkippedScanFile(
                            file_path=rel_path,
                            reason=f"Scan file limit of {max_files} reached.",
                        )
                    )
                    truncated = True
                continue
            rel_files.append(rel_path)

    return rel_files, skipped


def _finding_priority(finding: FindingRecord) -> Tuple[int, int]:
    sev_score = _SEVERITY_ORDER.get(finding.severity, 0)
    if finding.category == "security":
        tool_rank = {"bandit": 3, "ruff": 2, "ast": 1}.get(finding.tool, 0)
    elif finding.category == "syntax":
        tool_rank = {"ast": 3, "ruff": 2, "bandit": 1}.get(finding.tool, 0)
    else:
        tool_rank = {"ruff": 3, "ast": 2, "bandit": 1}.get(finding.tool, 0)
    return (sev_score, tool_rank)


def deduplicate_findings(findings: Sequence[FindingRecord]) -> List[FindingRecord]:
    """Merge duplicate findings reported by multiple tools at the same location."""
    grouped: Dict[str, List[FindingRecord]] = {}
    order: List[str] = []

    for finding in findings:
        semantic = _SEMANTIC_RULE_GROUPS.get((finding.tool, finding.rule_id))
        if semantic:
            key = f"sem:{finding.file_path}:{finding.line_number}:{semantic}"
        else:
            key = (
                f"raw:{finding.file_path}:{finding.line_number}:"
                f"{finding.column or 0}:{finding.tool}:{finding.rule_id}:{finding.title}"
            )
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(finding)

    merged: List[FindingRecord] = []
    for key in order:
        bucket = grouped[key]
        if len(bucket) == 1:
            merged.append(bucket[0])
            continue

        ranked = sorted(bucket, key=_finding_priority, reverse=True)
        primary = ranked[0].model_copy(deep=True)
        for secondary in ranked[1:]:
            if secondary.tool != primary.tool and secondary.tool not in primary.secondary_tools:
                primary.secondary_tools.append(secondary.tool)
            primary.related_findings.append(
                {
                    "tool": secondary.tool,
                    "rule_id": secondary.rule_id,
                    "severity": secondary.severity,
                    "confidence": secondary.confidence,
                    "title": secondary.title,
                    "evidence": secondary.evidence,
                }
            )
            if not primary.suggested_fix and secondary.suggested_fix:
                primary.suggested_fix = secondary.suggested_fix
        merged.append(primary)

    merged.sort(
        key=lambda f: (
            -_SEVERITY_ORDER.get(f.severity, 0),
            f.file_path,
            f.line_number,
            f.column or 0,
            f.rule_id,
        )
    )
    return merged


def run_project_scan(project_id: str, settings: Settings) -> ScanResponse:
    """Run AST, Ruff, and Bandit static analysis on an uploaded project."""
    metadata = load_project(project_id, settings)
    project_dir = _project_dir(project_id, settings)
    source_dir = project_dir / SOURCE_DIR
    if not source_dir.is_dir():
        raise ProjectNotFoundError()

    project_root = find_project_root(source_dir)
    rel_files, discovery_skipped = _collect_python_files(project_root, settings.max_scan_files)

    ast_outcome = run_ast_scan(project_root, rel_files, settings.max_scan_file_bytes)

    # Filter out unreadable/oversized files skipped by AST before invoking Ruff/Bandit
    skipped_set = {item.file_path for item in ast_outcome.skipped_files}
    scannable_files = [f for f in rel_files if f not in skipped_set]

    ruff_outcome = run_ruff_scan(project_root, scannable_files, settings.scanner_timeout_seconds)
    bandit_outcome = run_bandit_scan(
        project_root, scannable_files, settings.scanner_timeout_seconds
    )

    combined = [*ast_outcome.findings, *ruff_outcome.findings, *bandit_outcome.findings]
    findings = deduplicate_findings(combined)

    severity_summary: Dict[SeverityLevel, int] = {
        "CRITICAL": 0,
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
        "INFO": 0,
    }
    tool_summary: Dict[str, int] = {"ast": 0, "ruff": 0, "bandit": 0}
    for f in findings:
        severity_summary[f.severity] = severity_summary.get(f.severity, 0) + 1
        tool_summary[f.tool] = tool_summary.get(f.tool, 0) + 1

    scanner_details: Dict[str, ScannerToolSummary] = {
        "ast": ast_outcome.summary,
        "ruff": ruff_outcome.summary,
        "bandit": bandit_outcome.summary,
    }
    scanner_summary = {name: detail.status for name, detail in scanner_details.items()}

    statuses = {detail.status for detail in scanner_details.values()}
    if not scannable_files:
        overall_status = "completed"
    elif statuses <= {"completed", "skipped"}:
        overall_status = "completed"
    elif "completed" in statuses:
        overall_status = "partial"
    else:
        overall_status = "failed"

    all_skipped = [*discovery_skipped, *ast_outcome.skipped_files]

    limitations = [
        "Static analysis inspects code without executing uploaded files and cannot guarantee detection of all bugs.",
        "Security and quality findings should be reviewed by a developer in context before patching.",
    ]

    non_python_languages = [
        lang.name for lang in metadata.inspection.languages if lang.name != "Python"
    ]
    if non_python_languages:
        limitations.append(
            f"Non-Python language(s) detected: {', '.join(non_python_languages)}. "
            "RootPatch static analysis currently inspects Python source files only; non-Python files were excluded from scanning."
        )

    if not scannable_files:
        if non_python_languages:
            limitations.append(
                f"No scannable Python source files were found in this project. "
                f"Project contains {', '.join(non_python_languages)} which is not supported by the Python static analysis engine."
            )
        else:
            limitations.append(
                "No scannable Python source files were found in this project. The static analysis scanner did not execute."
            )

    for tool_name, tool_outcome in [
        ("AST", ast_outcome.summary),
        ("Ruff", ruff_outcome.summary),
        ("Bandit", bandit_outcome.summary),
    ]:
        if tool_outcome.status in ("failed", "timed_out", "unavailable"):
            limitations.append(
                f"{tool_name} scanner {tool_outcome.status}: {tool_outcome.error or 'Execution could not complete.'} "
                "Static findings from this tool may be missing."
            )

    response = ScanResponse(
        project_id=project_id,
        scan_id=f"scan-{uuid.uuid4().hex[:12]}",
        status=overall_status,
        scanned_at=datetime.now(timezone.utc).isoformat(),
        files_scanned=ast_outcome.files_scanned,
        files_skipped=len(all_skipped),
        skipped_files=all_skipped,
        total_findings=len(findings),
        severity_summary=severity_summary,
        tool_summary=tool_summary,
        findings=findings,
        scanner_summary=scanner_summary,
        scanner_details=scanner_details,
        limitations=limitations,
    )

    try:
        (project_dir / SCAN_RESULT_NAME).write_text(
            response.model_dump_json(indent=2), encoding="utf-8"
        )
    except OSError as exc:
        raise ScanError("Failed to persist scan results.") from exc

    return response


def get_latest_scan(project_id: str, settings: Settings) -> ScanResponse:
    """Load the latest persisted scan response for a project."""
    load_project(project_id, settings)
    scan_path = _project_dir(project_id, settings) / SCAN_RESULT_NAME
    if not scan_path.is_file():
        raise ScanNotFoundError()
    try:
        return ScanResponse.model_validate_json(scan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScanError("Stored scan results could not be read.", 500) from exc
