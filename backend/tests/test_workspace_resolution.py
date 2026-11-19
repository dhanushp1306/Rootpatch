"""Regression tests for deterministic workspace path resolution and project lookup."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core import config as config_mod
from app.core.config import Settings, get_settings, resolve_workspace_dir, settings as default_settings
from app.services import (
    analysis_service,
    patch_service,
    scan_service,
    upload_service,
    validation_service,
)
from app.services.llm_provider import get_llm_provider
from conftest import upload
from main import app


class _StubProvider:
    def __init__(self, handler):
        self.handler = handler

    def analyze(self, system_prompt: str, user_prompt: str, settings) -> str:
        return self.handler(system_prompt, user_prompt, settings)


def test_workspace_resolution_from_backend_and_repo_root(monkeypatch, tmp_path):
    """Both `workspace` and `backend/workspace` resolve to `<repo>/backend/workspace` regardless of CWD."""
    fake_repo = tmp_path / "repo"
    fake_backend = fake_repo / "backend"
    fake_backend_ws = fake_backend / "workspace"
    fake_empty_root_ws = fake_repo / "workspace"
    fake_backend_ws.mkdir(parents=True)
    fake_empty_root_ws.mkdir(parents=True)

    monkeypatch.setattr(config_mod, "_BACKEND_DIR", fake_backend)
    monkeypatch.setattr(config_mod, "_REPO_ROOT", fake_repo)

    for cwd in (fake_backend, fake_repo):
        monkeypatch.chdir(cwd)
        for env_val in (
            None,
            "",
            "   ",
            "workspace",
            "./workspace",
            " 'workspace' ",
            "backend/workspace",
            "./backend/workspace",
            "backend\\workspace",
        ):
            if env_val is None:
                monkeypatch.delenv("ROOTPATCH_WORKSPACE_DIR", raising=False)
            else:
                monkeypatch.setenv("ROOTPATCH_WORKSPACE_DIR", env_val)

            resolved = Settings().workspace_dir
            assert resolved == fake_backend_ws.resolve()
            assert resolve_workspace_dir(env_val) == fake_backend_ws.resolve()
            assert resolved != fake_empty_root_ws.resolve()


def test_workspace_resolution_explicit_relative_and_absolute_paths(monkeypatch, tmp_path):
    fake_repo = tmp_path / "repo"
    fake_backend = fake_repo / "backend"
    fake_backend.mkdir(parents=True)
    custom_abs = (tmp_path / "external_ws").resolve()

    monkeypatch.setattr(config_mod, "_BACKEND_DIR", fake_backend)
    monkeypatch.setattr(config_mod, "_REPO_ROOT", fake_repo)
    monkeypatch.chdir(fake_repo)

    monkeypatch.setenv("ROOTPATCH_WORKSPACE_DIR", "custom_rel_ws")
    assert Settings().workspace_dir == (fake_backend / "custom_rel_ws").resolve()

    monkeypatch.setenv("ROOTPATCH_WORKSPACE_DIR", str(custom_abs))
    assert Settings().workspace_dir == custom_abs

    # Programmatic relative workspace_dir on Settings resolves deterministically too.
    assert Settings(workspace_dir=Path("workspace")).workspace_dir == (
        fake_backend / "workspace"
    ).resolve()
    assert Settings(workspace_dir=Path("backend/workspace")).workspace_dir == (
        fake_backend / "workspace"
    ).resolve()


def test_existing_project_lookup_and_analysis_from_repo_and_backend_cwd(
    monkeypatch, tmp_path, make_zip
):
    """Existing uploaded project + scan_result.json remain accessible across startup CWDs."""
    fake_repo = tmp_path / "repo"
    fake_backend = fake_repo / "backend"
    fake_backend_ws = fake_backend / "workspace"
    fake_root_ws = fake_repo / "workspace"
    fake_backend_ws.mkdir(parents=True)
    fake_root_ws.mkdir(parents=True)  # Unrelated empty root-level workspace must never be picked.

    monkeypatch.setattr(config_mod, "_BACKEND_DIR", fake_backend)
    monkeypatch.setattr(config_mod, "_REPO_ROOT", fake_repo)

    # Seed an existing project using upload + scan into fake_backend_ws (simulating an earlier run).
    seed_settings = replace(
        default_settings,
        workspace_dir=fake_backend_ws.resolve(),
        llm_api_key="test-placeholder-key",
    )
    app.dependency_overrides[get_settings] = lambda: seed_settings
    try:
        seed_client = TestClient(app)
        up = upload(
            seed_client,
            make_zip({"rootpatch-test/app.py": "def f():\n    return missing_name\n"}),
            "rootpatch-test.zip",
        )
        assert up.status_code == 201
        project_id = up.json()["project_id"]

        scan_resp = seed_client.post(f"/api/projects/{project_id}/scan")
        assert scan_resp.status_code == 200
        scan_body = scan_resp.json()
        assert scan_body["total_findings"] >= 1
    finally:
        app.dependency_overrides.clear()

    # Now simulate restarting backend with either `workspace` or `backend/workspace`
    # from both repo root and backend directory.
    for cwd in (fake_repo, fake_backend):
        monkeypatch.chdir(cwd)
        for configured_dir in ("workspace", "backend/workspace"):
            monkeypatch.setenv("ROOTPATCH_WORKSPACE_DIR", configured_dir)
            resolved_settings = Settings(llm_api_key="test-placeholder-key")
            assert resolved_settings.workspace_dir == fake_backend_ws.resolve()

            def _analysis_json(_sys, _usr, _settings):
                finding = scan_body["findings"][0]
                return json.dumps(
                    {
                        "analyses": [
                            {
                                "finding_id": finding["id"],
                                "root_cause": "missing_name is undefined.",
                                "technical_explanation": "Line 2 references missing_name.",
                                "affected_component": f"{finding['file_path']}:L{finding['line_number']}",
                                "impact": "Raises NameError at runtime.",
                                "recommended_fix": "Define missing_name.",
                                "evidence": ["return missing_name"],
                                "assumptions_or_uncertainties": [],
                                "related_finding_ids": [],
                                "confidence": "HIGH",
                                "confidence_reason": "Observed in static snippet.",
                                "analysis_status": "completed",
                            }
                        ],
                        "shared_root_cause_groups": [],
                        "limitations": [],
                    }
                )

            app.dependency_overrides[get_settings] = lambda s=resolved_settings: s
            app.dependency_overrides[get_llm_provider] = lambda: _StubProvider(_analysis_json)
            try:
                client = TestClient(app)
                get_resp = client.get(f"/api/projects/{project_id}")
                assert get_resp.status_code == 200
                assert get_resp.json()["project_id"] == project_id

                analyze_resp = client.post(f"/api/projects/{project_id}/analyze")
                assert analyze_resp.status_code == 200
                assert analyze_resp.json()["project_id"] == project_id
                assert analyze_resp.json()["scan_id"] == scan_body["scan_id"]
            finally:
                app.dependency_overrides.clear()


def test_post_upload_lookup_all_services_consistent_and_missing_returns_404(
    monkeypatch, tmp_path, make_zip
):
    fake_repo = tmp_path / "repo"
    fake_backend = fake_repo / "backend"
    fake_backend.mkdir(parents=True)

    monkeypatch.setattr(config_mod, "_BACKEND_DIR", fake_backend)
    monkeypatch.setattr(config_mod, "_REPO_ROOT", fake_repo)
    monkeypatch.chdir(fake_backend)
    monkeypatch.setenv("ROOTPATCH_WORKSPACE_DIR", "workspace")

    resolved_settings = Settings()
    expected_ws = (fake_backend / "workspace").resolve()
    assert resolved_settings.workspace_dir == expected_ws

    app.dependency_overrides[get_settings] = lambda: resolved_settings
    try:
        client = TestClient(app)
        up = upload(client, make_zip({"proj/main.py": "def ok():\n    return 1\n"}), "proj.zip")
        assert up.status_code == 201
        pid = up.json()["project_id"]

        # Immediate lookup succeeds
        get_resp = client.get(f"/api/projects/{pid}")
        assert get_resp.status_code == 200
        assert (expected_ws / pid / "metadata.json").is_file()

        # All service modules resolve the exact same project directory inside expected_ws
        assert upload_service._project_dir(pid, resolved_settings) == expected_ws / pid
        assert scan_service._project_dir(pid, resolved_settings) == expected_ws / pid
        assert analysis_service._project_dir(pid, resolved_settings) == expected_ws / pid
        assert patch_service._project_dir(pid, resolved_settings) == expected_ws / pid
        assert validation_service._project_dir(pid, resolved_settings) == expected_ws / pid

        # Missing & invalid IDs still return 404
        for bad_id in ("0" * 32, "not-a-valid-id", "2ea33beab6924fe1ab0262daecad1822"):
            miss = client.get(f"/api/projects/{bad_id}")
            assert miss.status_code == 404
            assert miss.json()["detail"] == "Project not found."
            miss_analyze = client.post(f"/api/projects/{bad_id}/analyze")
            assert miss_analyze.status_code == 404
            assert miss_analyze.json()["detail"] == "Project not found."
    finally:
        app.dependency_overrides.clear()
