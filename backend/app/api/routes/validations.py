"""Step 7 isolated testing and patch validation API routes."""

from typing import Optional

from fastapi import APIRouter, Body, Depends

from app.api.errors import http_error
from app.core.config import Settings, get_settings
from app.core.errors import ProjectError
from app.schemas.validation import (
    ValidationHistoryListResponse,
    ValidationReportResponse,
    ValidationRunRequest,
)
from app.schemas.worker import ValidationJobStatusResponse
from app.services import remote_validation_service, validation_service
from app.services.container_runner import ContainerRunner, get_container_runner
from app.services.upload_service import _project_dir, load_project
from app.services.validation_job_store import ValidationJobStore

router = APIRouter(prefix="/projects", tags=["validations"])


@router.post(
    "/{project_id}/patches/{patch_id}/validate",
    response_model=ValidationReportResponse,
)
def validate_project_patch(
    project_id: str,
    patch_id: str,
    payload: Optional[ValidationRunRequest] = Body(default=None),
    settings: Settings = Depends(get_settings),
    runner: ContainerRunner = Depends(get_container_runner),
) -> ValidationReportResponse:
    try:
        if settings.remote_validation_enabled:
            return remote_validation_service.validate_remote_patch(
                project_id=project_id,
                patch_id=patch_id,
                settings=settings,
                request=payload,
            )
        return validation_service.validate_applied_patch(
            project_id=project_id,
            patch_id=patch_id,
            settings=settings,
            request=payload,
            runner=runner,
        )
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.get(
    "/{project_id}/patches/{patch_id}/validations",
    response_model=ValidationHistoryListResponse,
)
def get_patch_validation_history(
    project_id: str,
    patch_id: str,
    settings: Settings = Depends(get_settings),
) -> ValidationHistoryListResponse:
    try:
        return validation_service.get_patch_validations(
            project_id=project_id,
            patch_id=patch_id,
            settings=settings,
        )
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.get(
    "/{project_id}/validations",
    response_model=ValidationHistoryListResponse,
)
def get_project_validation_history(
    project_id: str,
    settings: Settings = Depends(get_settings),
) -> ValidationHistoryListResponse:
    try:
        return validation_service.get_project_validations(
            project_id=project_id,
            settings=settings,
        )
    except ProjectError as exc:
        raise http_error(exc) from exc


@router.get(
    "/{project_id}/validation-jobs/{job_id}",
    response_model=ValidationJobStatusResponse,
)
def get_validation_job_status(
    project_id: str,
    job_id: str,
    settings: Settings = Depends(get_settings),
) -> ValidationJobStatusResponse:
    try:
        load_project(project_id, settings)
        _project_dir(project_id, settings)
    except ProjectError as exc:
        raise http_error(exc) from exc

    if not settings.database_url:
        raise http_error(ProjectError("Remote validation job storage is not configured.", 503))

    store = ValidationJobStore(settings.database_url)
    job = store.get_job(job_id)
    if job is None or job.project_id != project_id:
        raise http_error(ProjectError("Validation job not found.", 404))

    report = None
    if job.result_id:
        try:
            report = validation_service.get_validation_by_id(project_id, job.result_id, settings)
        except ProjectError:
            report = None

    return ValidationJobStatusResponse(
        job_id=job.job_id,
        project_id=job.project_id,
        patch_id=job.patch_id,
        status=job.status,
        worker_id=job.worker_id,
        attempt_count=job.attempt_count,
        max_attempts=job.max_attempts,
        created_at=job.created_at.isoformat() if job.created_at else None,
        claimed_at=job.claimed_at.isoformat() if job.claimed_at else None,
        heartbeat_at=job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
        lease_expires_at=job.lease_expires_at.isoformat() if job.lease_expires_at else None,
        error_message=job.error_message,
        report=report,
    )
@router.get(
    "/{project_id}/validations/{validation_id}",
    response_model=ValidationReportResponse,
)
def get_validation_report(
    project_id: str,
    validation_id: str,
    settings: Settings = Depends(get_settings),
) -> ValidationReportResponse:
    try:
        return validation_service.get_validation_by_id(
            project_id=project_id,
            validation_id=validation_id,
            settings=settings,
        )
    except ProjectError as exc:
        raise http_error(exc) from exc
