"""Step 7 Testing and Patch Validation orchestrator.

Validates applied patches inside an isolated, resource-bounded container environment,
compares unpatched baseline vs. patched test outcomes to detect regressions, parses
structured test metrics, and persists full validation history per project and patch.
"""

import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from pydantic import ValidationError

from app.core.config import Settings
from app.core.errors import (
    ExtractionError,
    ProjectNotFoundError,
    TestValidationError,
    ValidationConflictError,
    ValidationNotFoundError,
)
from app.schemas.validation import (
    CommandSource,
    ContainerExecutionSpec,
    ContainerRunResult,
    ParsedTestSummary,
    RegressionComparison,
    TestFrameworkName,
    ValidationHistoryListResponse,
    ValidationReportResponse,
    ValidationRunRequest,
    ValidationStatus,
    ValidationStore,
)
from app.services.analysis_service import _atomic_write_text
from app.services.container_runner import ContainerRunner, DockerContainerRunner
from app.services.context_service import redact_sensitive_text
from app.services.extraction_service import ExtractionLimits, extract_zip
from app.services.inspection_service import find_project_root
from app.services.patch_service import _find_patch_record, _get_project_lock
from app.services.test_detector import (
    detect_test_configuration,
    validate_test_command_override,
)
from app.services.upload_service import ARCHIVE_NAME, ORIGINAL_DIR, SOURCE_DIR, _project_dir, load_project
from app.utils.file_utils import is_within_directory

VALIDATION_RESULT_NAME = "validation_result.json"
MAX_VALIDATION_HISTORY = 200
_VALIDATION_ID_PATTERN = re.compile(r"^val-[0-9a-f]{12}$")

_SNAPSHOT_SKIP_DIRS = frozenset(
    {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", "backups"}
)

# Output parsing patterns
_PYTEST_VERBOSE_RE = re.compile(
    r"^([^\s]+::[^\s]+)\s+(PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\b",
    re.MULTILINE,
)
_PYTEST_SHORT_SUMMARY_RE = re.compile(
    r"^(FAILED|ERROR)\s+([^\s]+::[^\s]+)(?:\s+-\s+(.*))?$",
    re.MULTILINE,
)
_PYTEST_SUMMARY_COUNT_RE = re.compile(
    r"(\d+)\s+(passed|failed|skipped|errors?|xfailed|xpassed)\b",
    re.IGNORECASE,
)
_UNITTEST_CASE_RE = re.compile(
    r"^([^\s]+\s+\([^)]+\))\s+\.\.\.\s+(ok|FAIL|ERROR|skipped.*)$",
    re.MULTILINE,
)
_UNITTEST_RAN_RE = re.compile(r"^Ran\s+(\d+)\s+tests?\s+in\b", re.MULTILINE)
_UNITTEST_FAILED_RE = re.compile(
    r"^FAILED\s+\(([^)]+)\)",
    re.MULTILINE,
)
_JEST_SUMMARY_RE = re.compile(r"^Tests:\s+(.+)$", re.MULTILINE)
_NODE_TAP_CASE_RE = re.compile(r"^(ok|not ok)\s+\d+\s+-\s+(.+)$", re.MULTILINE)
_NODE_TAP_SUMMARY_RE = re.compile(
    r"^#\s+(tests|pass|fail|skipped)\s+(\d+)\s*$",
    re.MULTILINE,
)


def _is_valid_validation_id(validation_id: str) -> bool:
    return bool(_VALIDATION_ID_PATTERN.fullmatch(validation_id))


def _sanitize_output(text: str, extra_paths: Optional[List[Path]] = None) -> str:
    cleaned = redact_sensitive_text(text)
    for p in extra_paths or []:
        resolved = str(p.resolve())
        raw = str(p)
        for variant in (resolved, raw):
            if variant:
                cleaned = cleaned.replace(variant, "/workspace")
    return cleaned


def _extract_failure_excerpts(
    combined_output: str, max_lines: int = 8
) -> List[str]:
    excerpts: List[str] = []
    seen: Set[str] = set()
    for line in combined_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (
            stripped.startswith(("FAILED ", "ERROR ", "E   ", "AssertionError", "FAIL:"))
            or "AssertionError" in stripped
            or "Error:" in stripped
        ):
            bounded = stripped[:300]
            if bounded not in seen:
                seen.add(bounded)
                excerpts.append(bounded)
            if len(excerpts) >= max_lines:
                break
    return excerpts


def parse_test_output(
    framework: TestFrameworkName,
    stdout: str,
    stderr: str,
    exit_code: Optional[int],
) -> ParsedTestSummary:
    """Parse test counts, individual test case IDs, and failure details safely."""
    combined = "\n".join(part for part in (stdout, stderr) if part).strip()
    passed_ids: List[str] = []
    failed_ids: List[str] = []
    skipped_ids: List[str] = []
    error_ids: List[str] = []

    passed = 0
    failed = 0
    skipped = 0
    errors = 0

    if framework == "pytest":
        case_status: Dict[str, str] = {}
        for match in _PYTEST_VERBOSE_RE.finditer(combined):
            case_id, status = match.group(1), match.group(2).upper()
            case_status[case_id] = status

        for match in _PYTEST_SHORT_SUMMARY_RE.finditer(combined):
            status, case_id = match.group(1).upper(), match.group(2)
            case_status.setdefault(case_id, status)

        for cid, st in case_status.items():
            if st in ("PASSED", "XPASS"):
                passed_ids.append(cid)
            elif st in ("FAILED",):
                failed_ids.append(cid)
            elif st in ("SKIPPED", "XFAIL"):
                skipped_ids.append(cid)
            elif st == "ERROR":
                error_ids.append(cid)

        # Prefer pytest's final summary line counts when present.
        summary_lines = [
            ln
            for ln in combined.splitlines()
            if ln.strip().startswith("=") and ("in " in ln or "no tests ran" in ln.lower())
        ]
        if summary_lines:
            last_summary = summary_lines[-1]
            for cnt_match in _PYTEST_SUMMARY_COUNT_RE.finditer(last_summary):
                num = int(cnt_match.group(1))
                kind = cnt_match.group(2).lower()
                if kind == "passed":
                    passed = num
                elif kind == "failed":
                    failed = num
                elif kind == "skipped":
                    skipped = num
                elif kind.startswith("error"):
                    errors = num
        if passed == 0 and failed == 0 and skipped == 0 and errors == 0 and case_status:
            passed = len(passed_ids)
            failed = len(failed_ids)
            skipped = len(skipped_ids)
            errors = len(error_ids)

    elif framework == "unittest":
        for match in _UNITTEST_CASE_RE.finditer(combined):
            cid, st = match.group(1).strip(), match.group(2).lower()
            if st == "ok":
                passed_ids.append(cid)
            elif st == "fail":
                failed_ids.append(cid)
            elif st == "error":
                error_ids.append(cid)
            elif st.startswith("skipped"):
                skipped_ids.append(cid)

        ran_match = _UNITTEST_RAN_RE.search(combined)
        ran_total = int(ran_match.group(1)) if ran_match else len(passed_ids) + len(failed_ids) + len(error_ids) + len(skipped_ids)
        fail_match = _UNITTEST_FAILED_RE.search(combined)
        if fail_match:
            details_part = fail_match.group(1)
            for key, var in (("failures", "f"), ("errors", "e"), ("skipped", "s")):
                m = re.search(rf"{key}=(\d+)", details_part)
                if m:
                    val = int(m.group(1))
                    if var == "f":
                        failed = val
                    elif var == "e":
                        errors = val
                    else:
                        skipped = val
            passed = max(0, ran_total - failed - errors - skipped)
        else:
            ok_skip = re.search(r"^OK\s+\(skipped=(\d+)\)", combined, re.MULTILINE)
            if ok_skip:
                skipped = int(ok_skip.group(1))
            elif skipped_ids:
                skipped = len(skipped_ids)
            if failed_ids or error_ids:
                failed = len(failed_ids)
                errors = len(error_ids)
                passed = max(0, ran_total - failed - errors - skipped)
            elif exit_code == 0:
                passed = max(0, ran_total - skipped)
            else:
                failed = len(failed_ids)
                errors = len(error_ids)
                passed = len(passed_ids)

    else:
        # Node / Jest / Vitest / npm parsers
        jest_match = None
        for m in _JEST_SUMMARY_RE.finditer(combined):
            jest_match = m
        if jest_match:
            line_text = jest_match.group(1)
            for kind_re, target in (
                (r"(\d+)\s+passed", "p"),
                (r"(\d+)\s+failed", "f"),
                (r"(\d+)\s+skipped", "s"),
            ):
                km = re.search(kind_re, line_text, re.IGNORECASE)
                if km:
                    val = int(km.group(1))
                    if target == "p":
                        passed = val
                    elif target == "f":
                        failed = val
                    else:
                        skipped = val
        else:
            tap_counts = {m.group(1): int(m.group(2)) for m in _NODE_TAP_SUMMARY_RE.finditer(combined)}
            if tap_counts:
                passed = tap_counts.get("pass", 0)
                failed = tap_counts.get("fail", 0)
                skipped = tap_counts.get("skipped", 0)
            for m in _NODE_TAP_CASE_RE.finditer(combined):
                status, label = m.group(1), m.group(2).strip()
                if label.endswith("# SKIP"):
                    skipped_ids.append(label)
                elif status == "ok":
                    passed_ids.append(label)
                else:
                    failed_ids.append(label)
            if not tap_counts and (passed_ids or failed_ids or skipped_ids):
                passed = len(passed_ids)
                failed = len(failed_ids)
                skipped = len(skipped_ids)

    total = max(
        passed + failed + skipped + errors,
        len(passed_ids) + len(failed_ids) + len(skipped_ids) + len(error_ids),
    )

    failure_details = _extract_failure_excerpts(combined)
    if exit_code not in (None, 0) and not failure_details:
        if framework == "pytest" and exit_code == 5:
            failure_details.append("Pytest collected zero tests (exit code 5).")
        else:
            failure_details.append(f"Test runner exited with non-zero status code {exit_code}.")

    return ParsedTestSummary(
        total_tests=total,
        passed_tests=passed,
        failed_tests=failed,
        skipped_tests=skipped,
        error_tests=errors,
        passed_case_ids=sorted(set(passed_ids)),
        failed_case_ids=sorted(set(failed_ids)),
        skipped_case_ids=sorted(set(skipped_ids)),
        error_case_ids=sorted(set(error_ids)),
        failure_details=failure_details,
    )


def _copy_workspace_safely(project_root: Path, dest_dir: Path) -> None:
    """Copy workspace source into a disposable temp directory, ignoring symlinks and caches."""
    resolved_src = project_root.resolve()
    resolved_dest = dest_dir.resolve()
    resolved_dest.mkdir(parents=True, exist_ok=True)

    for dirpath, dirnames, filenames in os.walk(resolved_src, followlinks=False):
        dirnames.sort()
        filenames.sort()
        current = Path(dirpath)

        safe_dirs = []
        for d in dirnames:
            cand = current / d
            if cand.is_symlink() or d in _SNAPSHOT_SKIP_DIRS:
                continue
            if is_within_directory(resolved_src, cand):
                safe_dirs.append(d)
        dirnames[:] = safe_dirs

        rel_dir = current.relative_to(resolved_src)
        target_dir = resolved_dest if rel_dir == Path(".") else (resolved_dest / rel_dir)
        if not is_within_directory(resolved_dest, target_dir):
            raise TestValidationError("Snapshot copy escaped temporary workspace.", 500)
        target_dir.mkdir(parents=True, exist_ok=True)

        for name in filenames:
            src_file = current / name
            if src_file.is_symlink() or not src_file.is_file():
                continue
            if not is_within_directory(resolved_src, src_file):
                continue
            dst_file = target_dir / name
            if not is_within_directory(resolved_dest, dst_file):
                raise TestValidationError("Snapshot file escaped temporary workspace.", 500)
            shutil.copyfile(src_file, dst_file)


def _prepare_baseline_workspace(
    project_dir: Path, baseline_extract_dir: Path, settings: Settings
) -> Optional[Path]:
    """Safely extract immutable `original/upload.zip` into an isolated baseline directory."""
    archive_path = project_dir / ORIGINAL_DIR / ARCHIVE_NAME
    if not archive_path.is_file():
        return None
    limits = ExtractionLimits(
        max_files=settings.max_extracted_files,
        max_total_bytes=settings.max_extracted_total_bytes,
        max_file_bytes=settings.max_extracted_file_bytes,
    )
    try:
        extract_zip(archive_path, baseline_extract_dir, limits)
    except ExtractionError:
        return None
    return find_project_root(baseline_extract_dir)


def _classify_run_status(
    result: ContainerRunResult,
    parsed: ParsedTestSummary,
    *,
    regression_detected: bool = False,
) -> ValidationStatus:
    if not result.container_available:
        return "BLOCKED"
    if result.timed_out:
        return "TIMED_OUT"
    if result.exit_code is None:
        return "ERROR"
    if regression_detected:
        return "FAILED"
    if result.exit_code == 0 and parsed.failed_tests == 0 and parsed.error_tests == 0:
        return "PASSED"
    return "FAILED"


def _compare_regression(
    baseline_result: ContainerRunResult,
    baseline_parsed: ParsedTestSummary,
    patched_result: ContainerRunResult,
    patched_parsed: ParsedTestSummary,
) -> RegressionComparison:
    baseline_status = _classify_run_status(baseline_result, baseline_parsed)

    if not baseline_result.container_available or baseline_result.timed_out or baseline_result.exit_code is None:
        return RegressionComparison(
            baseline_available=False,
            baseline_status=baseline_status,
            baseline_exit_code=baseline_result.exit_code,
            baseline_total_tests=baseline_parsed.total_tests,
            baseline_passed_tests=baseline_parsed.passed_tests,
            baseline_failed_tests=baseline_parsed.failed_tests,
            baseline_skipped_tests=baseline_parsed.skipped_tests,
            regression_detected=False,
            summary=f"Baseline comparison did not complete cleanly (baseline status: {baseline_status}).",
        )

    base_passed = set(baseline_parsed.passed_case_ids)
    base_failed = set(baseline_parsed.failed_case_ids) | set(baseline_parsed.error_case_ids)
    patch_passed = set(patched_parsed.passed_case_ids)
    patch_failed = set(patched_parsed.failed_case_ids) | set(patched_parsed.error_case_ids)

    passed_before_and_after = sorted(base_passed & patch_passed)
    tests_fixed = sorted(base_failed & patch_passed)
    tests_regressed = sorted(base_passed & patch_failed)
    newly_introduced = sorted(patch_failed - base_failed)

    regression_detected = bool(tests_regressed or newly_introduced)
    if not regression_detected and patched_result.container_available and not patched_result.timed_out:
        if baseline_result.exit_code == 0 and patched_result.exit_code not in (None, 0):
            regression_detected = True
        elif (
            baseline_parsed.total_tests > 0
            and patched_parsed.passed_tests < baseline_parsed.passed_tests
        ):
            regression_detected = True
        elif patched_parsed.failed_tests > baseline_parsed.failed_tests:
            regression_detected = True

    if regression_detected:
        summary = (
            f"Regression detected: {len(tests_regressed)} previously passing test(s) regressed "
            f"and {len(newly_introduced)} new failure(s) appeared after applying the patch."
        )
    elif tests_fixed:
        summary = (
            f"No regressions detected; {len(tests_fixed)} baseline failure(s) now pass and "
            f"{len(passed_before_and_after)} test(s) passed before and after."
        )
    elif baseline_result.exit_code == 0 and patched_result.exit_code == 0:
        summary = (
            f"No regressions detected; baseline and patched suites both passed "
            f"({patched_parsed.passed_tests} passed)."
        )
    else:
        summary = (
            f"Baseline exited {baseline_result.exit_code} ({baseline_parsed.passed_tests} passed, "
            f"{baseline_parsed.failed_tests} failed); patched exited {patched_result.exit_code} "
            f"({patched_parsed.passed_tests} passed, {patched_parsed.failed_tests} failed)."
        )

    return RegressionComparison(
        baseline_available=True,
        baseline_status=baseline_status,
        baseline_exit_code=baseline_result.exit_code,
        baseline_total_tests=baseline_parsed.total_tests,
        baseline_passed_tests=baseline_parsed.passed_tests,
        baseline_failed_tests=baseline_parsed.failed_tests,
        baseline_skipped_tests=baseline_parsed.skipped_tests,
        tests_passed_before_and_after=passed_before_and_after,
        tests_fixed=tests_fixed,
        tests_regressed=tests_regressed,
        newly_introduced_failures=newly_introduced,
        regression_detected=regression_detected,
        summary=summary,
    )


def _load_validation_store(path: Path) -> ValidationStore:
    if not path.is_file():
        return ValidationStore(validations=[])
    try:
        raw = path.read_text(encoding="utf-8")
        return ValidationStore.model_validate_json(raw)
    except (OSError, ValueError, ValidationError) as exc:
        raise TestValidationError(
            "Stored patch validation results are corrupted or unreadable.", 500
        ) from exc


def _persist_validation_report(
    project_id: str, project_dir: Path, report: ValidationReportResponse
) -> None:
    with _get_project_lock(project_id):
        store_path = project_dir / VALIDATION_RESULT_NAME
        existing: List[ValidationReportResponse] = []
        if store_path.is_file():
            try:
                existing = list(_load_validation_store(store_path).validations)
            except TestValidationError:
                existing = []
        updated = ValidationStore(
            validations=[report, *existing][:MAX_VALIDATION_HISTORY]
        )
        try:
            _atomic_write_text(store_path, updated.model_dump_json(indent=2))
        except OSError as exc:
            raise TestValidationError("Failed to persist patch validation report.", 500) from exc


def _build_history_response(
    project_id: str,
    reports: List[ValidationReportResponse],
    patch_id: Optional[str] = None,
) -> ValidationHistoryListResponse:
    return ValidationHistoryListResponse(
        project_id=project_id,
        patch_id=patch_id,
        total_runs=len(reports),
        passed_count=sum(1 for r in reports if r.status == "PASSED"),
        failed_count=sum(1 for r in reports if r.status == "FAILED"),
        blocked_count=sum(1 for r in reports if r.status == "BLOCKED"),
        timed_out_count=sum(1 for r in reports if r.status == "TIMED_OUT"),
        error_count=sum(1 for r in reports if r.status == "ERROR"),
        validations=reports,
    )


def validate_applied_patch(
    project_id: str,
    patch_id: str,
    settings: Settings,
    request: Optional[ValidationRunRequest] = None,
    runner: Optional[ContainerRunner] = None,
) -> ValidationReportResponse:
    """Validate an applied patch in an isolated container with optional baseline comparison."""
    load_project(project_id, settings)
    project_dir = _project_dir(project_id, settings)
    source_dir = project_dir / SOURCE_DIR
    if not source_dir.is_dir():
        raise ProjectNotFoundError()
    project_root = find_project_root(source_dir)

    patch_record = _find_patch_record(project_dir, patch_id)
    if not patch_record.applied or patch_record.status != "applied":
        raise ValidationConflictError(
            f"Patch '{patch_id}' has status '{patch_record.status}' and has not been applied; only applied patches can be validated."
        )

    req = request or ValidationRunRequest()
    command_source: CommandSource = "auto_detected"

    if req.test_command is not None:
        detection = validate_test_command_override(req.test_command, settings)
        command_source = "override"
    else:
        detection = detect_test_configuration(
            project_root=project_root,
            settings=settings,
            target_file=patch_record.file_path,
            target_tests_only=req.target_tests_only,
        )

    now_iso = datetime.now(timezone.utc).isoformat()
    base_limitations = [
        *detection.limitations,
        "Passing tests provide evidence of correctness against existing tests but do not guarantee complete absence of defects.",
    ]

    if not detection.detected or not detection.command or not detection.container_image:
        blocked_report = ValidationReportResponse(
            validation_id=f"val-{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            patch_id=patch_id,
            finding_id=patch_record.finding_id,
            file_path=patch_record.file_path,
            test_framework=detection.framework,
            test_command=[],
            command_source="none",
            status="BLOCKED",
            exit_code=None,
            container_available=True,
            failure_details=[
                detection.reason
                or "No supported test suite or test configuration was detected."
            ],
            limitations=base_limitations,
            validated_at=now_iso,
        )
        _persist_validation_report(project_id, project_dir, blocked_report)
        return blocked_report

    spec = ContainerExecutionSpec(
        image=detection.container_image,
        command=list(detection.command),
        timeout_seconds=settings.validation_timeout_seconds,
        memory_limit=settings.validation_memory_limit,
        cpus=settings.validation_cpus,
        pids_limit=settings.validation_pids_limit,
        network_disabled=settings.validation_network_disabled,
        read_only_root=True,
        non_root_user="65534:65534",
        capabilities_dropped=["ALL"],
        no_new_privileges=True,
    )

    active_runner: ContainerRunner = runner if runner is not None else DockerContainerRunner()
    available, avail_reason = active_runner.is_available()
    if not available:
        blocked_report = ValidationReportResponse(
            validation_id=f"val-{uuid.uuid4().hex[:12]}",
            project_id=project_id,
            patch_id=patch_id,
            finding_id=patch_record.finding_id,
            file_path=patch_record.file_path,
            test_framework=detection.framework,
            test_command=list(detection.command),
            command_source=command_source,
            status="BLOCKED",
            exit_code=None,
            container_available=False,
            execution_spec=spec,
            failure_details=[
                avail_reason
                or "Isolated container execution environment is unavailable; host execution is disabled."
            ],
            limitations=[
                *base_limitations,
                "Execution on the host machine is strictly prohibited; validation remained blocked until Docker isolation is available.",
            ],
            validated_at=now_iso,
        )
        _persist_validation_report(project_id, project_dir, blocked_report)
        return blocked_report

    with tempfile.TemporaryDirectory(prefix="rootpatch-val-") as tmp_root_str:
        tmp_root = Path(tmp_root_str)
        patched_snapshot = tmp_root / "patched"
        _copy_workspace_safely(project_root, patched_snapshot)

        patched_result = active_runner.run_tests(
            patched_snapshot, spec, settings.max_validation_output_bytes
        )
        sanitized_stdout = _sanitize_output(patched_result.stdout, [patched_snapshot, tmp_root])
        sanitized_stderr = _sanitize_output(patched_result.stderr, [patched_snapshot, tmp_root])
        patched_parsed = parse_test_output(
            detection.framework,
            sanitized_stdout,
            sanitized_stderr,
            patched_result.exit_code,
        )

        regression_comparison: Optional[RegressionComparison] = None
        if req.run_regression and patched_result.container_available:
            baseline_extract_dir = tmp_root / "baseline"
            baseline_root = _prepare_baseline_workspace(
                project_dir, baseline_extract_dir, settings
            )
            if baseline_root is not None:
                baseline_result = active_runner.run_tests(
                    baseline_root, spec, settings.max_validation_output_bytes
                )
                base_stdout = _sanitize_output(
                    baseline_result.stdout, [baseline_root, baseline_extract_dir, tmp_root]
                )
                base_stderr = _sanitize_output(
                    baseline_result.stderr, [baseline_root, baseline_extract_dir, tmp_root]
                )
                baseline_parsed = parse_test_output(
                    detection.framework,
                    base_stdout,
                    base_stderr,
                    baseline_result.exit_code,
                )
                regression_comparison = _compare_regression(
                    baseline_result,
                    baseline_parsed,
                    patched_result,
                    patched_parsed,
                )
            else:
                regression_comparison = RegressionComparison(
                    baseline_available=False,
                    regression_detected=False,
                    summary="Original unpatched archive was unavailable; baseline regression comparison skipped.",
                )

    regression_detected = bool(
        regression_comparison and regression_comparison.regression_detected
    )
    final_status = _classify_run_status(
        patched_result, patched_parsed, regression_detected=regression_detected
    )

    failure_details = list(patched_parsed.failure_details)
    if patched_result.error_message:
        err_msg = redact_sensitive_text(patched_result.error_message)
        if err_msg not in failure_details:
            failure_details.insert(0, err_msg)
    if regression_detected and regression_comparison:
        if regression_comparison.summary not in failure_details:
            failure_details.append(regression_comparison.summary)

    limitations = list(base_limitations)
    if patched_result.output_truncated:
        limitations.append(
            f"Captured test output was truncated to {settings.max_validation_output_bytes} bytes."
        )
    if not patched_result.container_available:
        limitations.append(
            "Container isolation became unavailable during execution; host fallback was refused."
        )

    report = ValidationReportResponse(
        validation_id=f"val-{uuid.uuid4().hex[:12]}",
        project_id=project_id,
        patch_id=patch_id,
        finding_id=patch_record.finding_id,
        file_path=patch_record.file_path,
        test_framework=detection.framework,
        test_command=list(detection.command),
        command_source=command_source,
        status=final_status,
        exit_code=patched_result.exit_code,
        total_tests=patched_parsed.total_tests,
        passed_tests=patched_parsed.passed_tests,
        failed_tests=patched_parsed.failed_tests,
        skipped_tests=patched_parsed.skipped_tests,
        error_tests=patched_parsed.error_tests,
        duration_ms=patched_result.duration_ms,
        stdout=sanitized_stdout,
        stderr=sanitized_stderr,
        timed_out=patched_result.timed_out,
        output_truncated=patched_result.output_truncated,
        container_available=patched_result.container_available,
        execution_spec=spec,
        failure_details=failure_details,
        regression_comparison=regression_comparison,
        limitations=limitations,
        validated_at=now_iso,
    )

    _persist_validation_report(project_id, project_dir, report)
    return report


def get_patch_validations(
    project_id: str, patch_id: str, settings: Settings
) -> ValidationHistoryListResponse:
    """Return validation history for a specific patch within a project."""
    load_project(project_id, settings)
    project_dir = _project_dir(project_id, settings)
    _find_patch_record(project_dir, patch_id)
    store = _load_validation_store(project_dir / VALIDATION_RESULT_NAME)
    matching = [v for v in store.validations if v.patch_id == patch_id]
    return _build_history_response(project_id, matching, patch_id=patch_id)


def get_project_validations(
    project_id: str, settings: Settings
) -> ValidationHistoryListResponse:
    """Return all validation runs persisted for a project."""
    load_project(project_id, settings)
    project_dir = _project_dir(project_id, settings)
    store = _load_validation_store(project_dir / VALIDATION_RESULT_NAME)
    return _build_history_response(project_id, store.validations)


def get_validation_by_id(
    project_id: str, validation_id: str, settings: Settings
) -> ValidationReportResponse:
    """Retrieve a single persisted validation report by `validation_id`."""
    load_project(project_id, settings)
    if not _is_valid_validation_id(validation_id):
        raise ValidationNotFoundError()
    project_dir = _project_dir(project_id, settings)
    store = _load_validation_store(project_dir / VALIDATION_RESULT_NAME)
    for report in store.validations:
        if report.validation_id == validation_id:
            return report
    raise ValidationNotFoundError()
