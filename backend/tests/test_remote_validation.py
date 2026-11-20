import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.core.config import Settings, get_settings
from app.core.errors import ProjectError
from main import app
from app.schemas.validation import TestDetectionResult
from app.services import remote_validation_service as rvs
from app.services.validation_job_store import ValidationJob


def _settings(tmp_path, *, remote_enabled=True, db=True, storage=True):
    return Settings(
        workspace_dir=tmp_path,
        remote_validation_enabled=remote_enabled,
        database_url="postgresql://example" if db else None,
        supabase_url="https://example.supabase.co" if storage else None,
        supabase_service_role_key="service-role-key" if storage else None,
        object_storage_bucket="bucket" if storage else None,
        worker_token_hash="hash",
    )


class FakeStore:
    def __init__(self, database_url):
        self.database_url = database_url
        self.jobs = {}
        self.created = []

    def find_active_job(self, project_id, patch_id):
        for job in self.jobs.values():
            if job.project_id == project_id and job.patch_id == patch_id and job.status in {"PENDING", "RUNNING"}:
                return job
        return None

    def create_job(self, job):
        self.jobs[job.job_id] = job
        self.created.append(job)
        return job


class FakeStorage:
    def __init__(self):
        self.uploads = {}
        self.deleted = []
        self.fail_upload = False

    def upload_bytes(self, key, data, content_type="application/zip", if_none_match=False):
        if self.fail_upload:
            raise RuntimeError("upload failed")
        self.uploads[key] = data

    def delete(self, key):
        self.deleted.append(key)


def _patched_project(tmp_path):
    project_dir = tmp_path / "project-1"
    source_dir = project_dir / "source"
    source_dir.mkdir(parents=True)
    (source_dir / "test_main.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    return project_dir, source_dir


def test_remote_validation_disabled_raises(monkeypatch, tmp_path):
    settings = _settings(tmp_path, remote_enabled=False)
    with pytest.raises(ProjectError):
        rvs.validate_remote_patch("project-1", "patch-1", settings, SimpleNamespace())


def test_remote_validation_missing_database_raises(monkeypatch, tmp_path):
    settings = _settings(tmp_path, db=False)
    with pytest.raises(ProjectError):
        rvs.validate_remote_patch("project-1", "patch-1", settings, SimpleNamespace())


def test_remote_validation_missing_storage_raises(monkeypatch, tmp_path):
    settings = _settings(tmp_path, storage=False)
    with pytest.raises(ProjectError):
        rvs.validate_remote_patch("project-1", "patch-1", settings, SimpleNamespace())


def test_remote_validation_no_tests_returns_blocked(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    project_dir, source_dir = _patched_project(tmp_path)
    monkeypatch.setattr(rvs, "load_project", lambda *a, **k: None)
    monkeypatch.setattr(rvs, "_project_dir", lambda *a, **k: project_dir)
    monkeypatch.setattr(rvs, "find_project_root", lambda p: source_dir)
    monkeypatch.setattr(
        rvs.validation_service,
        "_find_patch_record",
        lambda *a, **k: SimpleNamespace(applied=True, status="applied", finding_id="f1", file_path="test_main.py"),
    )
    monkeypatch.setattr(
        rvs,
        "detect_test_configuration",
        lambda **k: TestDetectionResult(detected=False, framework="none", reason="no tests"),
    )

    report = rvs.validate_remote_patch("project-1", "patch-1", settings, SimpleNamespace())
    assert report.status == "BLOCKED"


def test_remote_validation_success_creates_job_and_uploads_snapshot(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    project_dir, source_dir = _patched_project(tmp_path)

    fake_store = FakeStore(settings.database_url)
    fake_storage = FakeStorage()

    monkeypatch.setattr(rvs, "load_project", lambda *a, **k: None)
    monkeypatch.setattr(rvs, "_project_dir", lambda *a, **k: project_dir)
    monkeypatch.setattr(rvs, "find_project_root", lambda p: source_dir)
    monkeypatch.setattr(
        rvs.validation_service,
        "_find_patch_record",
        lambda *a, **k: SimpleNamespace(applied=True, status="applied", finding_id="f1", file_path="test_main.py"),
    )
    monkeypatch.setattr(
        rvs,
        "detect_test_configuration",
        lambda **k: TestDetectionResult(
            detected=True,
            framework="pytest",
            command=["python", "-m", "pytest"],
            container_image="rootpatch-python-validate:latest",
        ),
    )
    monkeypatch.setattr(rvs, "ValidationJobStore", lambda url: fake_store)
    monkeypatch.setattr(rvs, "ObjectStorage", lambda s: fake_storage)

    report = rvs.validate_remote_patch("project-1", "patch-1", settings, SimpleNamespace())

    assert report.status == "PENDING"
    assert report.validation_id.startswith("job-")
    assert len(fake_store.created) == 1
    job = fake_store.created[0]
    assert job.status == "PENDING"
    assert job.snapshot_checksum == hashlib.sha256(fake_storage.uploads[job.snapshot_key]).hexdigest()
    assert len(fake_storage.uploads) == 1
    assert "validation-snapshots/project-1/" in job.snapshot_key


def test_remote_validation_duplicate_active_job_does_not_upload(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    project_dir, source_dir = _patched_project(tmp_path)

    existing_job = ValidationJob(
        job_id="job-existing",
        project_id="project-1",
        patch_id="patch-1",
        finding_id="f1",
        file_path="test_main.py",
        status="RUNNING",
        snapshot_key="existing.zip",
        snapshot_checksum="checksum",
        execution_spec={},
    )
    fake_store = FakeStore(settings.database_url)
    fake_store.jobs[existing_job.job_id] = existing_job
    fake_storage = FakeStorage()

    monkeypatch.setattr(rvs, "load_project", lambda *a, **k: None)
    monkeypatch.setattr(rvs, "_project_dir", lambda *a, **k: project_dir)
    monkeypatch.setattr(rvs, "find_project_root", lambda p: source_dir)
    monkeypatch.setattr(
        rvs.validation_service,
        "_find_patch_record",
        lambda *a, **k: SimpleNamespace(applied=True, status="applied", finding_id="f1", file_path="test_main.py"),
    )
    monkeypatch.setattr(
        rvs,
        "detect_test_configuration",
        lambda **k: TestDetectionResult(
            detected=True,
            framework="pytest",
            command=["python", "-m", "pytest"],
            container_image="rootpatch-python-validate:latest",
        ),
    )
    monkeypatch.setattr(rvs, "ValidationJobStore", lambda url: fake_store)
    monkeypatch.setattr(rvs, "ObjectStorage", lambda s: fake_storage)

    report = rvs.validate_remote_patch("project-1", "patch-1", settings, SimpleNamespace())

    assert report.validation_id == "job-existing"
    assert report.status == "PENDING"
    assert fake_storage.uploads == {}


def test_remote_validation_upload_failure_raises_and_cleans_up(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    project_dir, source_dir = _patched_project(tmp_path)

    fake_store = FakeStore(settings.database_url)
    fake_storage = FakeStorage()
    fake_storage.fail_upload = True

    monkeypatch.setattr(rvs, "load_project", lambda *a, **k: None)
    monkeypatch.setattr(rvs, "_project_dir", lambda *a, **k: project_dir)
    monkeypatch.setattr(rvs, "find_project_root", lambda p: source_dir)
    monkeypatch.setattr(
        rvs.validation_service,
        "_find_patch_record",
        lambda *a, **k: SimpleNamespace(applied=True, status="applied", finding_id="f1", file_path="test_main.py"),
    )
    monkeypatch.setattr(
        rvs,
        "detect_test_configuration",
        lambda **k: TestDetectionResult(
            detected=True,
            framework="pytest",
            command=["python", "-m", "pytest"],
            container_image="rootpatch-python-validate:latest",
        ),
    )
    monkeypatch.setattr(rvs, "ValidationJobStore", lambda url: fake_store)
    monkeypatch.setattr(rvs, "ObjectStorage", lambda s: fake_storage)

    with pytest.raises(ProjectError):
        rvs.validate_remote_patch("project-1", "patch-1", settings, SimpleNamespace())

    assert fake_store.created == []
    assert fake_storage.deleted


def test_remote_validation_unapplied_patch_raises(monkeypatch, tmp_path):
    settings = _settings(tmp_path)
    project_dir, source_dir = _patched_project(tmp_path)

    monkeypatch.setattr(rvs, "load_project", lambda *a, **k: None)
    monkeypatch.setattr(rvs, "_project_dir", lambda *a, **k: project_dir)
    monkeypatch.setattr(rvs, "find_project_root", lambda p: source_dir)
    monkeypatch.setattr(
        rvs.validation_service,
        "_find_patch_record",
        lambda *a, **k: SimpleNamespace(applied=False, status="generated", finding_id="f1", file_path="test_main.py"),
    )

    with pytest.raises(Exception):
        rvs.validate_remote_patch("project-1", "patch-1", settings, SimpleNamespace())
