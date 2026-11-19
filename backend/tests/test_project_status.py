"""Project status endpoint and machine-readable error codes."""

import json
from dataclasses import replace

from app.core.config import get_settings, settings as default_settings
from app.services.llm_provider import get_llm_provider
from conftest import upload
from main import app

MISSING = "0" * 32


class _Stub:
    def __init__(self, handler):
        self.handler = handler

    def analyze(self, system_prompt, user_prompt, settings):
        return self.handler(system_prompt, user_prompt, settings)


def _new_project(client, make_zip):
    resp = upload(client, make_zip({"p/app.py": "def f():\n    return missing_name\n"}), "p.zip")
    assert resp.status_code == 201
    return resp.json()["project_id"]


def test_status_for_new_project_reports_nothing_generated(client, make_zip):
    pid = _new_project(client, make_zip)
    resp = client.get(f"/api/projects/{pid}/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == pid
    assert body["project"]["available"] is True
    assert body["structure"]["available"] is True
    for key in ("scan", "analysis", "patches", "validations"):
        assert body[key]["state"] == "missing"
        assert body[key]["available"] is False
    assert body["can_analyze"] is True
    assert body["can_generate_patches"] is False


def test_new_project_immediately_retrievable(client, make_zip):
    pid = _new_project(client, make_zip)
    assert client.get(f"/api/projects/{pid}").status_code == 200
    assert client.get(f"/api/projects/{pid}/structure").status_code == 200


def test_status_missing_project_has_code(client):
    resp = client.get(f"/api/projects/{MISSING}/status")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Project not found.", "code": "project_not_found"}


def test_missing_analysis_and_patches_have_distinct_codes(client, make_zip):
    pid = _new_project(client, make_zip)
    a = client.get(f"/api/projects/{pid}/analysis")
    assert a.status_code == 404
    assert a.json() == {
        "detail": "No analysis results found for this project.",
        "code": "analysis_not_found",
    }
    p = client.get(f"/api/projects/{pid}/patches")
    assert p.status_code == 404
    assert p.json()["code"] == "patches_not_found"
    s = client.get(f"/api/projects/{pid}/scan")
    assert s.status_code == 404
    assert s.json()["code"] == "scan_not_found"
    # project-not-found is distinguishable from analysis-not-found
    assert client.get(f"/api/projects/{MISSING}/analysis").json()["code"] == "project_not_found"
    assert client.get(f"/api/projects/{MISSING}/patches").json()["code"] == "project_not_found"


def test_status_reflects_scan_analysis_after_generation(make_client, make_zip, workspace):
    test_settings = replace(default_settings, workspace_dir=workspace, llm_api_key="k")
    app.dependency_overrides[get_settings] = lambda: test_settings
    from fastapi.testclient import TestClient

    client = TestClient(app)
    pid = _new_project(client, make_zip)
    scan = client.post(f"/api/projects/{pid}/scan").json()
    finding = scan["findings"][0]

    def handler(_s, _u, _st):
        return json.dumps(
            {
                "analyses": [
                    {
                        "finding_id": finding["id"],
                        "root_cause": "undefined name",
                        "technical_explanation": "missing_name is not defined.",
                        "affected_component": f"{finding['file_path']}:L{finding['line_number']}",
                        "impact": "NameError",
                        "recommended_fix": "Define it.",
                        "evidence": ["return missing_name"],
                        "assumptions_or_uncertainties": [],
                        "related_finding_ids": [],
                        "confidence": "HIGH",
                        "confidence_reason": "static",
                        "analysis_status": "completed",
                    }
                ],
                "shared_root_cause_groups": [],
                "limitations": [],
            }
        )

    app.dependency_overrides[get_llm_provider] = lambda: _Stub(handler)
    assert client.post(f"/api/projects/{pid}/analyze").status_code == 200

    body = client.get(f"/api/projects/{pid}/status").json()
    assert body["scan"]["available"] is True
    assert body["scan"]["count"] == scan["total_findings"]
    assert body["analysis"]["available"] is True
    assert body["analysis"]["count"] == 1
    assert body["patches"]["state"] == "missing"
    assert body["can_generate_patches"] is True
    assert client.get(f"/api/projects/{pid}/analysis").status_code == 200


def test_status_flags_corrupt_artifact_as_error_not_missing(client, make_zip, workspace):
    pid = _new_project(client, make_zip)
    (workspace / pid / "analysis_result.json").write_text("{not json", encoding="utf-8")
    body = client.get(f"/api/projects/{pid}/status").json()
    assert body["analysis"]["state"] == "error"
    assert body["analysis"]["available"] is False
    assert body["analysis"]["detail"]
    # genuine failure keeps 500 + code on the data endpoint
    resp = client.get(f"/api/projects/{pid}/analysis")
    assert resp.status_code == 500
    assert resp.json()["code"] == "analysis_error"
