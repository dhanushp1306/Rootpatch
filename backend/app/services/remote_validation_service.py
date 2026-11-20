"""Service helpers for remote Docker validation jobs.

Stage 2 provides job/result handling. Full snapshot creation and the worker
client are intentionally deferred to later stages.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
import hashlib
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

from app.core.config import Settings
from app.core.errors import ProjectError, ProjectNotFoundError, ValidationConflictError
from app.schemas.validation import (
    ContainerExecutionSpec,
    ValidationReportResponse,
    ValidationStatus,
)
from app.schemas.worker import WorkerValidationResultRequest
from app.services import validation_service
from app.services.container_runner import ContainerRunResult
from app.services.container_runner import ContainerRunResult
from app.services.extraction_service import ExtractionLimits
from app.services.inspection_service import find_project_root
from app.services.test_detector import detect_test_configuration
from app.services.validation_job_store import ValidationJob, ValidationJobStore
from app.services.validation_service import (
    _atomic_write_text,
    _classify_run_status,
    _copy_workspace_safely,
    _load_validation_store,
    _persist_validation_report,
    _prepare_baseline_workspace,
    _sanitize_output,
    parse_test_output,
)
from app.utils.file_utils import is_within_directory
from app.services.object_storage import ObjectStorage
from app.services.upload_service import ARCHIVE_NAME, ORIGINAL_DIR, SOURCE_DIR, _project_dir, load_project


def submit_worker_result(
    *,
    job_id: str,
    worker_id: str,
    payload,
    settings: Settings,
    job_store: ValidationJobStore,
) -> ValidationReportResponse:
    job = job_store.get_job(job_id)
    if job is None:
        raise ProjectError("Validation job not found.", 404)
    if job.worker_id != worker_id:
        raise ProjectError("Worker is not authorized for this validation job.", 403)
    if job.status != "RUNNING":
        raise ProjectError("Validation job is not running.", 409)

    project_dir = _project_dir(job.project_id, settings)
    load_project(job.project_id, settings)

    execution_spec = job.execution_spec or {}
    framework = str(execution_spec.get("framework", "none"))
    command = list(execution_spec.get("command", []))

    container_result = ContainerRunResult(
        exit_code=payload.exit_code,
        stdout=payload.stdout,
        stderr=payload.stderr,
        duration_ms=payload.duration_ms,
        timed_out=payload.timed_out,
        output_truncated=payload.output_truncated,
        container_available=payload.container_available,
        error_message=payload.error_message,
    )

    sanitized_stdout = _sanitize_output(container_result.stdout)
    sanitized_stderr = _sanitize_output(container_result.stderr)
    parsed = parse_test_output(
        framework,
        sanitized_stdout,
        sanitized_stderr,
        container_result.exit_code,
    )

    final_status = _classify_run_status(container_result, parsed, regression_detected=False)

    failure_details = list(parsed.failure_details)
    if container_result.error_message and container_result.error_message not in failure_details:
        failure_details.insert(0, container_result.error_message)

    limitations = [
        "Remote worker validation result; baseline regression comparison is not included in this Stage 2 foundation.",
    ]
    if container_result.output_truncated:
        limitations.append(
            f"Captured test output was truncated to {settings.max_validation_output_bytes} bytes."
        )

    report = ValidationReportResponse(
        validation_id=job.job_id,
        project_id=job.project_id,
        patch_id=job.patch_id,
        finding_id=job.finding_id,
        file_path=job.file_path,
        test_framework=framework,
        test_command=command,
        command_source="auto_detected",
        status=final_status,
        exit_code=container_result.exit_code,
        total_tests=parsed.total_tests,
        passed_tests=parsed.passed_tests,
        failed_tests=parsed.failed_tests,
        skipped_tests=parsed.skipped_tests,
        error_tests=parsed.error_tests,
        duration_ms=container_result.duration_ms,
        stdout=sanitized_stdout,
        stderr=sanitized_stderr,
        timed_out=container_result.timed_out,
        output_truncated=container_result.output_truncated,
        container_available=container_result.container_available,
        execution_spec=_build_execution_spec(execution_spec),
        failure_details=failure_details,
        regression_comparison=None,
        limitations=limitations,
        validated_at=datetime.now(timezone.utc).isoformat(),
    )

    _upsert_validation_report(job.project_id, project_dir, report)
    return report
    try:
        return ContainerExecutionSpec.model_validate(payload)
    except Exception:
        return None


def create_remote_validation_job(
    *,
    project_id: str,
    patch_id: str,
    snapshot_key: str,
    snapshot_checksum: str,
    execution_spec: Dict[str, Any],
    settings: Settings,
    baseline_snapshot_key: Optional[str] = None,
    baseline_checksum: Optional[str] = None,
    job_store: Optional[ValidationJobStore] = None,
) -> ValidationJob:
    """Create a durable remote validation job for an applied patch."""
    if not settings.database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Remote validation job storage is not configured.",
        )

    load_project(project_id, settings)
    project_dir = _project_dir(project_id, settings)
    patch_record = validation_service._find_patch_record(project_dir, patch_id)
    if not patch_record.applied or patch_record.status != "applied":
        raise ValidationConflictError(
            f"Patch '{patch_id}' has status '{patch_record.status}' and has not been applied."
        )

    store = job_store or ValidationJobStore(settings.database_url)
    job = ValidationJob(
        job_id=f"job-{uuid.uuid4().hex[:12]}",
        project_id=project_id,
        patch_id=patch_id,
        finding_id=patch_record.finding_id,
        file_path=patch_record.file_path,
        status="PENDING",
        snapshot_key=snapshot_key,
        snapshot_checksum=snapshot_checksum,
        baseline_snapshot_key=baseline_snapshot_key,
        baseline_checksum=baseline_checksum,
        execution_spec=execution_spec,
    )
    return store.create_job(job)


def _create_snapshot_archive(source_root: Path, archive_path: Path) -> None:
    resolved_src = source_root.resolve()
    resolved_archive = archive_path.resolve()
    resolved_archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(resolved_archive, "w", zipfile.ZIP_DEFLATED) as archive:
        for dirpath, dirnames, filenames in os.walk(resolved_src, followlinks=False):
            dirnames.sort()
            filenames.sort()
            current = Path(dirpath)
            safe_dirs = []
            for name in dirnames:
                candidate = current / name
                if candidate.is_symlink() or name in {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".tox", "backups"}:
                    continue
                if is_within_directory(resolved_src, candidate):
                    safe_dirs.append(name)
            dirnames[:] = safe_dirs

            for name in filenames:
                source_file = current / name
                if source_file.is_symlink() or not source_file.is_file():
                    continue
                if not is_within_directory(resolved_src, source_file):
                    continue
                relative = source_file.relative_to(resolved_src).as_posix()
                archive.write(source_file, relative)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _upsert_validation_report(project_id: str, project_dir: Path, report) -> None:
    store_path = project_dir / validation_service.VALIDATION_RESULT_NAME
    existing = []
    if store_path.is_file():
        try:
            existing = list(validation_service._load_validation_store(store_path).validations)
        except Exception:
            existing = []
    updated = [report] + [item for item in existing if item.validation_id != report.validation_id]
    updated = updated[:validation_service.MAX_VALIDATION_HISTORY]
    try:
        validation_service._atomic_write_text(
            store_path,
            validation_service.ValidationStore(validations=updated).model_dump_json(indent=2),
        )
    except Exception as exc:
        raise validation_service.TestValidationError("Failed to persist patch validation report.", 500) from exc


def submit_worker_result(
    *,
    job_id: str,
    worker_id: str,
    payload,
    settings: Settings,
    job_store: ValidationJobStore,
) -> ValidationReportResponse:
    job = job_store.get_job(job_id)
    if job is None:
        raise ProjectError("Validation job not found.", 404)
    if job.worker_id != worker_id:
        raise ProjectError("Worker is not authorized for this validation job.", 403)
    if job.status != "RUNNING":
        raise ProjectError("Validation job is not running.", 409)

    project_dir = _project_dir(job.project_id, settings)
    load_project(job.project_id, settings)

    execution_spec = job.execution_spec or {}
    framework = str(execution_spec.get("framework", "none"))
    command = list(execution_spec.get("command", []))

    container_result = ContainerRunResult(
        exit_code=payload.exit_code,
        stdout=payload.stdout,
        stderr=payload.stderr,
        duration_ms=payload.duration_ms,
        timed_out=payload.timed_out,
        output_truncated=payload.output_truncated,
        container_available=payload.container_available,
        error_message=payload.error_message,
    )

    sanitized_stdout = _sanitize_output(container_result.stdout)
    sanitized_stderr = _sanitize_output(container_result.stderr)
    parsed = parse_test_output(
        framework,
        sanitized_stdout,
        sanitized_stderr,
        container_result.exit_code,
    )

    final_status = _classify_run_status(container_result, parsed, regression_detected=False)

    failure_details = list(parsed.failure_details)
    if container_result.error_message and container_result.error_message not in failure_details:
        failure_details.insert(0, container_result.error_message)

    limitations = [
        "Remote worker validation result; baseline regression comparison is not included in this Stage 2 foundation.",
    ]
    if container_result.output_truncated:
        limitations.append(
            f"Captured test output was truncated to {settings.max_validation_output_bytes} bytes."
        )

    report = ValidationReportResponse(
        validation_id=job.job_id,
        project_id=job.project_id,
        patch_id=job.patch_id,
        finding_id=job.finding_id,
        file_path=job.file_path,
        test_framework=framework,
        test_command=command,
        command_source="auto_detected",
        status=final_status,
        exit_code=container_result.exit_code,
        total_tests=parsed.total_tests,
        passed_tests=parsed.passed_tests,
        failed_tests=parsed.failed_tests,
        skipped_tests=parsed.skipped_tests,
        error_tests=parsed.error_tests,
        duration_ms=container_result.duration_ms,
        stdout=sanitized_stdout,
        stderr=sanitized_stderr,
        timed_out=container_result.timed_out,
        output_truncated=container_result.output_truncated,
        container_available=container_result.container_available,
        execution_spec=_build_execution_spec(execution_spec),
        failure_details=failure_details,
        regression_comparison=None,
        limitations=limitations,
        validated_at=datetime.now(timezone.utc).isoformat(),
    )

    _upsert_validation_report(job.project_id, project_dir, report)
    return report
    store_path = project_dir / validation_service.VALIDATION_RESULT_NAME
    existing = []
    if store_path.is_file():
        try:
            existing = list(validation_service._load_validation_store(store_path).validations)
        except Exception:
            existing = []
    updated = [report] + [item for item in existing if item.validation_id != report.validation_id]
    updated = updated[:validation_service.MAX_VALIDATION_HISTORY]
    try:
        validation_service._atomic_write_text(
            store_path,
            validation_service.ValidationStore(validations=updated).model_dump_json(indent=2),
        )
    except Exception as exc:
        raise validation_service.TestValidationError("Failed to persist patch validation report.", 500) from exc


def validate_remote_patch(
    project_id: str,
    patch_id: str,
    settings: Settings,
    request,
    runner=None,
    job_store=None,
    storage=None,
):
    """Create a durable remote validation job for an applied patch."""
    if not settings.remote_validation_enabled:
        raise ProjectError("Remote Docker validation is disabled.", 409)
    if not settings.database_url:
        raise ProjectError("Remote validation job storage is not configured.", 503)
    if not settings.supabase_url or not settings.supabase_service_role_key or not settings.object_storage_bucket:
        raise ProjectError("Remote validation object storage is not configured.", 503)

    load_project(project_id, settings)
    project_dir = _project_dir(project_id, settings)
    source_dir = project_dir / SOURCE_DIR
    if not source_dir.is_dir():
        raise ProjectNotFoundError()
    project_root = find_project_root(source_dir)

    patch_record = validation_service._find_patch_record(project_dir, patch_id)
    if not patch_record.applied or patch_record.status != "applied":
        raise ValidationConflictError(
            f"Patch '{patch_id}' has status '{patch_record.status}' and has not been applied."
        )

    detection = detect_test_configuration(
        project_root=project_root,
        settings=settings,
        target_file=patch_record.file_path,
        target_tests_only=getattr(request, "target_tests_only", False),
    )
    if not detection.detected or not detection.command or not detection.container_image:
        blocked_report = validation_service.ValidationReportResponse(
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
            limitations=[
                *detection.limitations,
                "Passing tests provide evidence of correctness against existing tests but do not guarantee complete absence of defects.",
            ],
            validated_at=datetime.now(timezone.utc).isoformat(),
        )
        validation_service._persist_validation_report(project_id, project_dir, blocked_report)
        return blocked_report

    store = job_store or ValidationJobStore(settings.database_url)
    storage = storage or ObjectStorage(settings)

    existing_job = store.find_active_job(project_id, patch_id)
    if existing_job is not None:
        pending_report = validation_service.ValidationReportResponse(
            validation_id=existing_job.job_id,
            project_id=project_id,
            patch_id=patch_id,
            finding_id=patch_record.finding_id,
            file_path=patch_record.file_path,
            test_framework=detection.framework,
            test_command=list(detection.command),
            command_source="auto_detected",
            status="PENDING",
            container_available=True,
            execution_spec=None,
            limitations=["Remote validation job is already queued or running."],
            validated_at=datetime.now(timezone.utc).isoformat(),
        )
        return pending_report
    command_source = "override" if getattr(request, "test_command", None) is not None else "auto_detected"
    if getattr(request, "test_command", None) is not None:
        detection = validate_test_command_override(request.test_command, settings)

    spec = {
        "framework": detection.framework,
        "command": list(detection.command),
        "image": detection.container_image,
        "timeout_seconds": settings.validation_timeout_seconds,
        "memory_limit": settings.validation_memory_limit,
        "cpus": settings.validation_cpus,
        "pids_limit": settings.validation_pids_limit,
        "network_disabled": settings.validation_network_disabled,
        "read_only_root": True,
        "non_root_user": "65534:65534",
        "capabilities_dropped": ["ALL"],
        "no_new_privileges": True,
    }

    with tempfile.TemporaryDirectory(prefix="rootpatch-remote-snapshot-") as tmp_root_str:
        tmp_root = Path(tmp_root_str)
        patched_snapshot = tmp_root / "patched"
        validation_service._copy_workspace_safely(project_root, patched_snapshot)

        patched_archive = tmp_root / "patched.zip"
        _create_snapshot_archive(patched_snapshot, patched_archive)
        patched_data = patched_archive.read_bytes()
        patched_checksum = _sha256_file(patched_archive)
        snapshot_id = uuid.uuid4().hex
        patched_key = f"validation-snapshots/{project_id}/{snapshot_id}/patched.zip"

        baseline_key = None
        baseline_checksum = None
        baseline_root = validation_service._prepare_baseline_workspace(
            project_dir, tmp_root / "baseline", settings
        )
        if baseline_root is not None:
            baseline_snapshot = tmp_root / "baseline-source"
            validation_service._copy_workspace_safely(baseline_root, baseline_snapshot)
            baseline_archive = tmp_root / "baseline.zip"
            _create_snapshot_archive(baseline_snapshot, baseline_archive)
            baseline_data = baseline_archive.read_bytes()
            baseline_checksum = _sha256_file(baseline_archive)
            baseline_key = f"validation-snapshots/{project_id}/{snapshot_id}/baseline.zip"

        try:
            storage.upload_bytes(patched_key, patched_data, "application/zip", if_none_match=True)
            if baseline_key is not None:
                storage.upload_bytes(baseline_key, baseline_data, "application/zip", if_none_match=True)
        except Exception as exc:
            for key in (patched_key, baseline_key):
                if key:
                    try:
                        storage.delete(key)
                    except Exception:
                        pass
            raise ProjectError("Failed to upload validation snapshot.", 502) from exc

        try:
            job = create_remote_validation_job(
                project_id=project_id,
                patch_id=patch_id,
                snapshot_key=patched_key,
                snapshot_checksum=patched_checksum,
                execution_spec=spec,
                settings=settings,
                baseline_snapshot_key=baseline_key,
                baseline_checksum=baseline_checksum,
                job_store=store,
            )
        except Exception:
            for key in (patched_key, baseline_key):
                if key:
                    try:
                        storage.delete(key)
                    except Exception:
                        pass
            raise

    pending_report = validation_service.ValidationReportResponse(
        validation_id=job.job_id,
        project_id=project_id,
        patch_id=patch_id,
        finding_id=patch_record.finding_id,
        file_path=patch_record.file_path,
        test_framework=detection.framework,
        test_command=list(detection.command),
        command_source=command_source,
        status="PENDING",
        container_available=True,
        execution_spec=validation_service.ContainerExecutionSpec.model_validate(spec),
        limitations=[
            *detection.limitations,
            "Remote Docker validation job has been queued. A local worker must claim and execute it.",
        ],
        validated_at=datetime.now(timezone.utc).isoformat(),
    )
    _upsert_validation_report(project_id, project_dir, pending_report)
    return pending_report
