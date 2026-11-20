-- RootPatch validation job metadata table.
-- Apply this migration to the Supabase/PostgreSQL database used by Render.

CREATE TABLE IF NOT EXISTS rootpatch_validation_jobs (
    job_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    patch_id TEXT NOT NULL,
    finding_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    worker_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    snapshot_key TEXT NOT NULL,
    snapshot_checksum TEXT NOT NULL,
    baseline_snapshot_key TEXT,
    baseline_checksum TEXT,
    execution_spec JSONB NOT NULL,
    result_id TEXT,
    error_message TEXT,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rootpatch_validation_jobs_status_created
    ON rootpatch_validation_jobs (status, created_at);

CREATE INDEX IF NOT EXISTS idx_rootpatch_validation_jobs_project
    ON rootpatch_validation_jobs (project_id);

CREATE INDEX IF NOT EXISTS idx_rootpatch_validation_jobs_worker
    ON rootpatch_validation_jobs (worker_id);
