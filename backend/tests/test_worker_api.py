import hashlib
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config import get_settings
from main import app
from app.schemas.worker import WorkerValidationResultRequest
from app.services.validation_job_store import ValidationJob


def _worker_token() -> str:
    return "test-worker-token"


def _worker_token_hash() -> str:
    return hashlib.sha256(_worker_token().encode("utf-8")).hexdigest()


class FakeJobStore:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.jobs = {}

    def mark_expired_jobs(self):
        return 0

    def claim_next_job(self, worker_id: str, lease_seconds: int = 120):
        for job in self.jobs.values():
            if job.status == "PENDING":
                job.status = "RUNNING"
                job.worker_id = worker_id
                return job
        return None

    def get_job(self, job_id: str):
        return self.jobs.get(job_id)

    def heartbeat(self, job_id: str, worker_id: str, lease_seconds: int = 120):
        job = self.jobs.get(job_id)
        return bool(job and job.worker_id == worker_id and job.status == "RUNNING")

    def submit_result(self, job_id: str, worker_id: str, status: str, result_id=None, error_message=None):
        job = self.jobs.get(job_id)
        if not job or job.worker_id != worker_id or job.status != "RUNNING":
            return False
        job.status = status
        job.result_id = result_id
        return True


def _make_job(job_id: str = "job-123", worker_id: str = "worker-1") -> ValidationJob:
    job = ValidationJob(
        job_id=job_id,
        project_id="project-1",
        patch_id="patch-1",
        finding_id="finding-1",
        file_path="src/app.py",
        status="RUNNING",
        worker_id=worker_id,
        snapshot_key="snapshots/project-1/patched.zip",
        snapshot_checksum="abc123",
        execution_spec={
            "framework": "pytest",
            "command": ["python", "-m", "pytest"],
            "image": "rootpatch-python-validate:latest",
            "timeout_seconds": 60,
        },
    )
    return job


def _client(monkeypatch):
    from dataclasses import replace

    from app.core.config import settings as default_settings

    test_settings = replace(
        default_settings,
        remote_validation_enabled=True,
        database_url="postgresql://example",
        worker_token_hash=_worker_token_hash(),
        object_storage_bucket="bucket",
        object_storage_access_key_id="key",
        object_storage_secret_access_key="secret",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings

    fake_store = FakeJobStore(test_settings.database_url)
    monkeypatch.setattr("app.api.routes.worker.ValidationJobStore", lambda url: fake_store)
    monkeypatch.setattr("app.api.routes.worker.ObjectStorage", lambda settings: type(
        "Storage", (), {"download_bytes": lambda self, key: b"zip-bytes"}
    )())

    def fake_submit(**kwargs):
        from app.schemas.validation import ValidationReportResponse

        return ValidationReportResponse(
            validation_id="val-test123",
            project_id=kwargs["job_store"].jobs[kwargs["job_id"]].project_id,
            patch_id=kwargs["job_store"].jobs[kwargs["job_id"]].patch_id,
            finding_id="finding-1",
            file_path="src/app.py",
            test_framework="pytest",
            test_command=["python", "-m", "pytest"],
            status="PASSED",
            validated_at="2026-01-01T00:00:00+00:00",
        )

    monkeypatch.setattr("app.services.remote_validation_service.submit_worker_result", fake_submit)

    client = TestClient(app)
    client.fake_store = fake_store
    return client


def test_worker_claim_requires_token(monkeypatch):
    client = _client(monkeypatch)
    job = _make_job("job-1")
    client.fake_store.jobs[job.job_id] = job
    job.status = "PENDING"
    job.worker_id = None

    response = client.post("/api/worker/validation-jobs/claim", headers={"X-Worker-ID": "worker-1"})
    assert response.status_code == 401


def test_worker_claim_success(monkeypatch):
    client = _client(monkeypatch)
    job = _make_job("job-1")
    job.status = "PENDING"
    job.worker_id = None
    client.fake_store.jobs[job.job_id] = job

    response = client.post(
        "/api/worker/validation-jobs/claim",
        headers={"X-Worker-ID": "worker-1", "Authorization": f"Bearer {_worker_token()}"},
    )
    assert response.status_code == 200
    assert response.json()["job_id"] == "job-1"
    assert client.fake_store.jobs["job-1"].status == "RUNNING"
    assert client.fake_store.jobs["job-1"].worker_id == "worker-1"


def test_worker_claim_no_jobs_returns_404(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/api/worker/validation-jobs/claim",
        headers={"X-Worker-ID": "worker-1", "Authorization": f"Bearer {_worker_token()}"},
    )
    assert response.status_code == 404


def test_worker_heartbeat_success(monkeypatch):
    client = _client(monkeypatch)
    job = _make_job("job-1")
    client.fake_store.jobs[job.job_id] = job

    response = client.post(
        "/api/worker/validation-jobs/job-1/heartbeat",
        json={"lease_seconds": 120},
        headers={"X-Worker-ID": "worker-1", "Authorization": f"Bearer {_worker_token()}"},
    )
    assert response.status_code == 200
    assert response.json() == {"renewed": True}


def test_worker_heartbeat_wrong_worker_returns_404(monkeypatch):
    client = _client(monkeypatch)
    job = _make_job("job-1")
    client.fake_store.jobs[job.job_id] = job

    response = client.post(
        "/api/worker/validation-jobs/job-1/heartbeat",
        json={"lease_seconds": 120},
        headers={"X-Worker-ID": "worker-2", "Authorization": f"Bearer {_worker_token()}"},
    )
    assert response.status_code == 404


def test_worker_snapshot_success(monkeypatch):
    client = _client(monkeypatch)
    job = _make_job("job-1")
    client.fake_store.jobs[job.job_id] = job

    response = client.get(
        "/api/worker/validation-jobs/job-1/snapshot?kind=patched",
        headers={"X-Worker-ID": "worker-1", "Authorization": f"Bearer {_worker_token()}"},
    )
    assert response.status_code == 200
    assert response.content == b"zip-bytes"


def test_worker_snapshot_wrong_worker_returns_404(monkeypatch):
    client = _client(monkeypatch)
    job = _make_job("job-1")
    client.fake_store.jobs[job.job_id] = job

    response = client.get(
        "/api/worker/validation-jobs/job-1/snapshot?kind=patched",
        headers={"X-Worker-ID": "worker-2", "Authorization": f"Bearer {_worker_token()}"},
    )
    assert response.status_code == 404


def test_worker_result_success(monkeypatch):
    client = _client(monkeypatch)
    job = _make_job("job-1")
    client.fake_store.jobs[job.job_id] = job

    payload = {
        "worker_id": "worker-1",
        "exit_code": 0,
        "stdout": "1 passed",
        "stderr": "",
        "duration_ms": 10,
        "timed_out": False,
        "output_truncated": False,
        "container_available": True,
        "error_message": None,
    }
    response = client.post(
        "/api/worker/validation-jobs/job-1/result",
        json=payload,
        headers={"X-Worker-ID": "worker-1", "Authorization": f"Bearer {_worker_token()}"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PASSED"
    assert client.fake_store.jobs["job-1"].status == "PASSED"


def test_worker_result_wrong_worker_returns_404(monkeypatch):
    client = _client(monkeypatch)
    job = _make_job("job-1")
    client.fake_store.jobs[job.job_id] = job

    payload = {
        "worker_id": "worker-2",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "duration_ms": 10,
        "timed_out": False,
        "output_truncated": False,
        "container_available": True,
        "error_message": None,
    }
    response = client.post(
        "/api/worker/validation-jobs/job-1/result",
        json=payload,
        headers={"X-Worker-ID": "worker-2", "Authorization": f"Bearer {_worker_token()}"},
    )
    assert response.status_code == 404


def test_worker_result_duplicate_returns_409(monkeypatch):
    client = _client(monkeypatch)
    job = _make_job("job-1")
    client.fake_store.jobs[job.job_id] = job

    payload = {
        "worker_id": "worker-1",
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "duration_ms": 10,
        "timed_out": False,
        "output_truncated": False,
        "container_available": True,
        "error_message": None,
    }
    first = client.post(
        "/api/worker/validation-jobs/job-1/result",
        json=payload,
        headers={"X-Worker-ID": "worker-1", "Authorization": f"Bearer {_worker_token()}"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/worker/validation-jobs/job-1/result",
        json=payload,
        headers={"X-Worker-ID": "worker-1", "Authorization": f"Bearer {_worker_token()}"},
    )
    assert second.status_code == 409


def test_worker_disabled_returns_503(monkeypatch):
    from dataclasses import replace

    from app.core.config import settings as default_settings

    test_settings = replace(default_settings, remote_validation_enabled=False)
    app.dependency_overrides[get_settings] = lambda: test_settings
    client = TestClient(app)
    try:
        response = client.post(
            "/api/worker/validation-jobs/claim",
            headers={"X-Worker-ID": "worker-1", "Authorization": "Bearer any-token"},
        )
        assert response.status_code == 503
    finally:
        app.dependency_overrides.clear()
