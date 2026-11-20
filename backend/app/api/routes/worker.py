"""Remote Docker validation worker API routes."""

from __future__ import annotations

import io
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from app.api.dependencies.worker_auth import require_worker_token
from app.core.config import Settings, get_settings
from app.core.errors import ProjectError
from app.schemas.worker import (
    WorkerClaimResponse,
    WorkerHeartbeatRequest,
    WorkerHeartbeatResponse,
    WorkerValidationResultRequest,
)
from app.services import validation_job_store as job_store_module
from app.services import validation_service
from app.services.container_runner import ContainerRunResult
from app.services.object_storage import ObjectStorage
from app.services.validation_job_store import ValidationJobStore

router = APIRouter(prefix="/worker", tags=["worker"])


def _require_remote_enabled(settings: Settings) -> None:
    if not settings.remote_validation_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Remote Docker validation is disabled.",
        )


def _job_store(settings: Settings) -> ValidationJobStore:
    _require_remote_enabled(settings)
    if not settings.database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Remote validation job storage is not configured.",
        )
    return ValidationJobStore(settings.database_url)


def _valid_job_id(job_id: str) -> bool:
    return 1 <= len(job_id) <= 128


@router.post("/validation-jobs/claim", response_model=WorkerClaimResponse)
def claim_validation_job(
    x_worker_id: str = Header(..., alias="X-Worker-ID"),
    _token: str = Depends(require_worker_token),
    settings: Settings = Depends(get_settings),
) -> WorkerClaimResponse:
    _require_remote_enabled(settings)
    store = _job_store(settings)
    store.mark_expired_jobs()
    job = store.claim_next_job(worker_id=x_worker_id, lease_seconds=120)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No pending validation jobs.")

    execution_spec = job.execution_spec or {}
    test_command = list(execution_spec.get("command", []))
    container_image = execution_spec.get("image")
    test_framework = execution_spec.get("framework", "none")
    timeout_seconds = int(execution_spec.get("timeout_seconds", 60))

    return WorkerClaimResponse(
        job_id=job.job_id,
        project_id=job.project_id,
        patch_id=job.patch_id,
        finding_id=job.finding_id,
        file_path=job.file_path,
        test_framework=test_framework,
        test_command=test_command,
        container_image=container_image,
        execution_spec=execution_spec,
        snapshot_checksum=job.snapshot_checksum,
        baseline_available=bool(job.baseline_snapshot_key),
        baseline_checksum=job.baseline_checksum,
        timeout_seconds=timeout_seconds,
    )


@router.post(
    "/validation-jobs/{job_id}/heartbeat",
    response_model=WorkerHeartbeatResponse,
)
def heartbeat_validation_job(
    job_id: str,
    payload: WorkerHeartbeatRequest,
    x_worker_id: str = Header(..., alias="X-Worker-ID"),
    _token: str = Depends(require_worker_token),
    settings: Settings = Depends(get_settings),
) -> WorkerHeartbeatResponse:
    _require_remote_enabled(settings)
    if not _valid_job_id(job_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid job ID.")
    store = _job_store(settings)
    job = store.get_job(job_id)
    if job is None or job.worker_id != x_worker_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Validation job not found.")
    if job.status != "RUNNING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Validation job is not running.")
    renewed = store.heartbeat(job_id, x_worker_id, payload.lease_seconds)
    if not renewed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Validation lease expired.")
    return WorkerHeartbeatResponse(renewed=True)


@router.get("/validation-jobs/{job_id}/snapshot")
def get_validation_snapshot(
    job_id: str,
    kind: str = Query(default="patched", pattern="^(patched|baseline)$"),
    x_worker_id: str = Header(..., alias="X-Worker-ID"),
    _token: str = Depends(require_worker_token),
    settings: Settings = Depends(get_settings),
) -> Response:
    _require_remote_enabled(settings)
    if not _valid_job_id(job_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid job ID.")
    store = _job_store(settings)
    job = store.get_job(job_id)
    if job is None or job.worker_id != x_worker_id or job.status != "RUNNING":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Validation job not found.")

    key = job.snapshot_key if kind == "patched" else job.baseline_snapshot_key
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot is not available.")

    try:
        storage = ObjectStorage(settings)
        data = storage.download_bytes(key)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Snapshot download failed.") from exc

    return Response(content=data, media_type="application/zip")


@router.post("/validation-jobs/{job_id}/result")
def submit_validation_result(
    job_id: str,
    payload: WorkerValidationResultRequest,
    x_worker_id: str = Header(..., alias="X-Worker-ID"),
    _token: str = Depends(require_worker_token),
    settings: Settings = Depends(get_settings),
):
    _require_remote_enabled(settings)
    if not _valid_job_id(job_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid job ID.")
    if payload.worker_id != x_worker_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Worker identity mismatch.")

    store = _job_store(settings)
    job = store.get_job(job_id)
    if job is None or job.worker_id != x_worker_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Validation job not found.")
    if job.status != "RUNNING":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Validation job is not running.")

    from app.services import remote_validation_service

    report = remote_validation_service.submit_worker_result(
        job_id=job_id,
        worker_id=x_worker_id,
        payload=payload,
        settings=settings,
        job_store=store,
    )

    ok = store.submit_result(
        job_id=job_id,
        worker_id=x_worker_id,
        status=report.status,
        result_id=report.validation_id,
        error_message="; ".join(report.failure_details[:3]) if report.failure_details else None,
    )
    if not ok:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Validation result was already submitted.")

    return report
