"""Shared fixtures. All tests use temporary directories; nothing touches the real workspace."""

import io
import zipfile
from dataclasses import replace
from typing import Callable

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings, settings as default_settings
from main import app


@pytest.fixture
def workspace(tmp_path):
    return tmp_path / "workspace"


@pytest.fixture
def make_client(workspace):
    """Factory returning a TestClient whose settings point at a temp workspace."""

    def _make(**overrides) -> TestClient:
        test_settings = replace(default_settings, workspace_dir=workspace, **overrides)
        app.dependency_overrides[get_settings] = lambda: test_settings
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def make_zip() -> Callable:
    """Build ZIP bytes from a dict or list of (name_or_ZipInfo, data) pairs."""

    def _make(entries) -> bytes:
        items = entries.items() if isinstance(entries, dict) else entries
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in items:
                archive.writestr(name, data)
        return buffer.getvalue()

    return _make


@pytest.fixture
def python_project_zip(make_zip) -> bytes:
    return make_zip(
        {
            "demo/app/main.py": "def add(a, b):\n    return a + b\n",
            "demo/app/utils.py": "X = 1\n",
            "demo/tests/test_main.py": "def test_ok():\n    assert True\n",
            "demo/requirements.txt": "requests\n",
            "demo/README.md": "# Demo\n",
            "demo/Dockerfile": "FROM python:3.12\n",
        }
    )


def upload(client: TestClient, data: bytes, filename: str = "project.zip"):
    return client.post(
        "/api/projects/upload",
        files={"file": (filename, data, "application/zip")},
    )


def project_dirs(workspace):
    return [p for p in workspace.iterdir()] if workspace.exists() else []
