"""PostgreSQL-backed validation job store foundation.

This module provides the durable job metadata layer needed for remote worker
validation. It uses psycopg lazily so importing the module does not require
psycopg unless database operations are actually used.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from contextlib import contextmanager
from datetime import datetime, timezone


VALIDATION_JOB_STATUSES = (
    "PENDING",
    "RUNNING",
    "COMPLETED",
    "FAILED",
    "TIMED_OUT",
    "BLOCKED",
    "ERROR",
    "CANCELLED",
)


@dataclass
class ValidationJob:
    job_id: str
    project_id: str
    patch_id: str
    finding_id: str
    file_path: str
    status: str = "PENDING"
    worker_id: Optional[str] = None
    attempt_count: int = 0
    max_attempts: int = 3
    snapshot_key: str = ""
    snapshot_checksum: str = ""
    baseline_snapshot_key: Optional[str] = None
    baseline_checksum: Optional[str] = None
    execution_spec: Dict[str, Any] = field(default_factory=dict)
    result_id: Optional[str] = None
    error_message: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    claimed_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_record(self) -> Dict[str, Any]:
        record = asdict(self)
        record["execution_spec"] = json.dumps(self.execution_spec)
        return record


class ValidationJobStore:
    """Small PostgreSQL job store with atomic claim support."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise RuntimeError("ROOTPATCH_DATABASE_URL is required for validation job storage.")
        self.database_url = database_url

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is required for validation job storage.") from exc
        return psycopg.connect(self.database_url)

    @contextmanager
    def _connection(self):
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    def create_job(self, job: ValidationJob) -> ValidationJob:
        record = job.to_record()
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO rootpatch_validation_jobs (
                        job_id, project_id, patch_id, finding_id, file_path, status,
                        worker_id, attempt_count, max_attempts, snapshot_key,
                        snapshot_checksum, baseline_snapshot_key, baseline_checksum,
                        execution_spec, result_id, error_message, lease_expires_at,
                        heartbeat_at, claimed_at, completed_at, created_at, updated_at
                    ) VALUES (
                        %(job_id)s, %(project_id)s, %(patch_id)s, %(finding_id)s, %(file_path)s, %(status)s,
                        %(worker_id)s, %(attempt_count)s, %(max_attempts)s, %(snapshot_key)s,
                        %(snapshot_checksum)s, %(baseline_snapshot_key)s, %(baseline_checksum)s,
                        %(execution_spec)s::jsonb, %(result_id)s, %(error_message)s, %(lease_expires_at)s,
                        %(heartbeat_at)s, %(claimed_at)s, %(completed_at)s, %(created_at)s, %(updated_at)s
                    )
                    """,
                    record,
                )
            conn.commit()
        return job

    def claim_next_job(self, worker_id: str, lease_seconds: int = 120) -> Optional[ValidationJob]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH next_job AS (
                        SELECT job_id
                        FROM rootpatch_validation_jobs
                        WHERE status = 'PENDING'
                          AND attempt_count < max_attempts
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE rootpatch_validation_jobs AS jobs
                    SET status = 'RUNNING',
                        worker_id = %s,
                        attempt_count = jobs.attempt_count + 1,
                        claimed_at = now(),
                        heartbeat_at = now(),
                        lease_expires_at = now() + (%s * interval '1 second'),
                        updated_at = now()
                    FROM next_job
                    WHERE jobs.job_id = next_job.job_id
                    RETURNING jobs.*
                    """,
                    (worker_id, lease_seconds),
                )
                row = cur.fetchone()
                columns = [desc[0] for desc in cur.description] if cur.description else []
            conn.commit()

        if row is None:
            return None
        return self._row_to_job(dict(zip(columns, row)))

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int = 120) -> bool:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE rootpatch_validation_jobs
                    SET heartbeat_at = now(),
                        lease_expires_at = now() + (%s * interval '1 second'),
                        updated_at = now()
                    WHERE job_id = %s
                      AND worker_id = %s
                      AND status = 'RUNNING'
                      AND lease_expires_at > now()
                    """,
                    (lease_seconds, job_id, worker_id),
                )
                updated = cur.rowcount
            conn.commit()
        return updated > 0

    def mark_expired_jobs(self) -> int:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE rootpatch_validation_jobs
                    SET status = 'PENDING',
                        worker_id = NULL,
                        lease_expires_at = NULL,
                        heartbeat_at = NULL,
                        updated_at = now()
                    WHERE status = 'RUNNING'
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at < now()
                      AND attempt_count < max_attempts
                    """
                )
                requeued = cur.rowcount
                cur.execute(
                    """
                    UPDATE rootpatch_validation_jobs
                    SET status = 'FAILED',
                        error_message = COALESCE(error_message, 'Validation lease expired after maximum attempts.'),
                        completed_at = now(),
                        updated_at = now()
                    WHERE status = 'RUNNING'
                      AND lease_expires_at IS NOT NULL
                      AND lease_expires_at < now()
                      AND attempt_count >= max_attempts
                    """
                )
                failed = cur.rowcount
            conn.commit()
        return requeued + failed

    def submit_result(
        self,
        job_id: str,
        worker_id: str,
        status: str,
        result_id: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        if status not in VALIDATION_JOB_STATUSES:
            raise ValueError(f"Unsupported validation job status: {status}")
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE rootpatch_validation_jobs
                    SET status = %s,
                        result_id = COALESCE(%s, result_id),
                        error_message = COALESCE(%s, error_message),
                        completed_at = now(),
                        lease_expires_at = NULL,
                        heartbeat_at = now(),
                        updated_at = now()
                    WHERE job_id = %s
                      AND worker_id = %s
                      AND status = 'RUNNING'
                    """,
                    (status, result_id, error_message, job_id, worker_id),
                )
                updated = cur.rowcount
            conn.commit()
        return updated > 0

    def get_job(self, job_id: str) -> Optional[ValidationJob]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM rootpatch_validation_jobs WHERE job_id = %s", (job_id,))
                row = cur.fetchone()
                columns = [desc[0] for desc in cur.description] if cur.description else []
        if row is None:
            return None
        return self._row_to_job(dict(zip(columns, row)))

    def find_active_job(self, project_id: str, patch_id: str) -> Optional[ValidationJob]:
        with self._connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM rootpatch_validation_jobs
                    WHERE project_id = %s
                      AND patch_id = %s
                      AND status IN ('PENDING', 'RUNNING')
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (project_id, patch_id),
                )
                row = cur.fetchone()
                columns = [desc[0] for desc in cur.description] if cur.description else []
        if row is None:
            return None
        return self._row_to_job(dict(zip(columns, row)))

    @staticmethod
    def _row_to_job(row: Dict[str, Any]) -> ValidationJob:
        execution_spec = row.get("execution_spec")
        if isinstance(execution_spec, str):
            execution_spec = json.loads(execution_spec)
        return ValidationJob(
            job_id=row["job_id"],
            project_id=row["project_id"],
            patch_id=row["patch_id"],
            finding_id=row["finding_id"],
            file_path=row["file_path"],
            status=row["status"],
            worker_id=row.get("worker_id"),
            attempt_count=row.get("attempt_count", 0),
            max_attempts=row.get("max_attempts", 3),
            snapshot_key=row["snapshot_key"],
            snapshot_checksum=row["snapshot_checksum"],
            baseline_snapshot_key=row.get("baseline_snapshot_key"),
            baseline_checksum=row.get("baseline_checksum"),
            execution_spec=execution_spec or {},
            result_id=row.get("result_id"),
            error_message=row.get("error_message"),
            lease_expires_at=row.get("lease_expires_at"),
            heartbeat_at=row.get("heartbeat_at"),
            claimed_at=row.get("claimed_at"),
            completed_at=row.get("completed_at"),
            created_at=row.get("created_at", datetime.now(timezone.utc)),
            updated_at=row.get("updated_at", datetime.now(timezone.utc)),
        )
