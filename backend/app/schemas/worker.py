"""Schemas for the RootPatch remote Docker validation worker API."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.validation import ValidationReportResponse


class WorkerClaimResponse(BaseModel):
    """Information returned to a worker after it claims a validation job."""

    job_id: str
    project_id: str
    patch_id: str
    finding_id: str
    file_path: str
    test_framework: str
    test_command: List[str] = Field(default_factory=list)
    container_image: Optional[str] = None
    execution_spec: Dict[str, Any] = Field(default_factory=dict)
    snapshot_checksum: str
    baseline_available: bool = False
    baseline_checksum: Optional[str] = None
    timeout_seconds: int


class WorkerHeartbeatRequest(BaseModel):
    lease_seconds: int = Field(default=120, ge=1, le=600)


class WorkerHeartbeatResponse(BaseModel):
    renewed: bool


class WorkerSnapshotResponse(BaseModel):
    content_type: str = "application/zip"
    size_bytes: int


class WorkerValidationResultRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    exit_code: Optional[int] = None
    stdout: str = Field(default="", max_length=65536)
    stderr: str = Field(default="", max_length=65536)
    duration_ms: int = Field(default=0, ge=0)
    timed_out: bool = False
    output_truncated: bool = False
    container_available: bool = True
    error_message: Optional[str] = Field(default=None, max_length=4096)


class ValidationJobStatusResponse(BaseModel):
    """Project-facing status for a remote validation job."""

    job_id: str
    project_id: str
    patch_id: str
    status: str
    worker_id: Optional[str] = None
    attempt_count: int = 0
    max_attempts: int = 3
    created_at: Optional[str] = None
    claimed_at: Optional[str] = None
    heartbeat_at: Optional[str] = None
    completed_at: Optional[str] = None
    lease_expires_at: Optional[str] = None
    error_message: Optional[str] = None
    report: Optional[ValidationReportResponse] = None
