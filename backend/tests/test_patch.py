import difflib
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings, settings as default_settings
from app.services.llm_provider import get_llm_provider
from conftest import upload
from main import app


class _StubProvider:
    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def analyze(self, system_prompt: str, user_prompt: str, settings) -> str:
        self.calls.append((system_prompt, user_prompt, settings))
        return self.handler(system_prompt, user_prompt, settings)


def _make_unified_diff(rel_path: str, old_source: str, new_source: str) -> str:
    lines = list(
        difflib.unified_diff(
            old_source.splitlines(),
            new_source.splitlines(),
            fromfile=f"a/{rel_path}",
            tofile=f"b/{rel_path}",
            n=3,
            lineterm="",
        )
    )
    return "\n".join(lines) + "\n"


def _setup_analyzed_project(client: TestClient, make_zip, files: dict[str, str]):
    up = upload(client, make_zip(files))
    assert up.status_code == 201
    pid = up.json()["project_id"]

    scan = client.post(f"/api/projects/{pid}/scan")
    assert scan.status_code == 200
    scan_body = scan.json()

    # Build a deterministic valid Step 4 analysis response for all scan findings.
    analyses_payload = {
        "analyses": [
            {
                "finding_id": f["id"],
                "root_cause": f"Static rule {f['rule_id']} detected in {f['file_path']}.",
                "technical_explanation": (
                    f"Line {f['line_number']} violates {f['rule_id']} based on static inspection."
                ),
                "affected_component": f"{f['file_path']}:L{f['line_number']}",
                "impact": "May cause runtime failure or unsafe execution.",
                "recommended_fix": f.get("suggested_fix") or "Apply a safe, minimal code fix.",
                "evidence": [f"{f['file_path']}:{f['line_number']}: {f.get('evidence', '')}"],
                "assumptions_or_uncertainties": [],
                "related_finding_ids": [],
                "relationship_explanation": None,
                "confidence": "HIGH",
                "confidence_reason": "Confirmed directly from source snippet.",
                "analysis_status": "completed",
            }
            for f in scan_body["findings"]
        ],
        "shared_root_cause_groups": [],
        "limitations": [],
    }
    return pid, scan_body, json.dumps(analyses_payload)


@pytest.fixture
def make_patch_client(workspace):
    def _make(provider=None, **overrides):
        test_settings = replace(
            default_settings,
            workspace_dir=workspace,
            llm_api_key=overrides.pop("llm_api_key", "test-placeholder-key"),
            **overrides,
        )
        app.dependency_overrides[get_settings] = lambda: test_settings
        if provider is not None:
            app.dependency_overrides[get_llm_provider] = lambda: provider
        else:
            app.dependency_overrides.pop(get_llm_provider, None)
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()


def _run_step4_analysis(client: TestClient, pid: str, analysis_json: str, workspace, **overrides):
    step4_provider = _StubProvider(lambda *_args: analysis_json)
    test_settings = replace(
        default_settings,
        workspace_dir=workspace,
        llm_api_key=overrides.pop("llm_api_key", "test-placeholder-key"),
        **overrides,
    )
    prev_provider = app.dependency_overrides.get(get_llm_provider)
    prev_settings = app.dependency_overrides.get(get_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_llm_provider] = lambda: step4_provider
    resp = client.post(f"/api/projects/{pid}/analyze")
    assert resp.status_code == 200
    if prev_provider is not None:
        app.dependency_overrides[get_llm_provider] = prev_provider
    else:
        app.dependency_overrides.pop(get_llm_provider, None)
    if prev_settings is not None:
        app.dependency_overrides[get_settings] = prev_settings
    return resp.json()


def test_valid_patch_generation_and_retrieval(make_patch_client, make_zip, workspace):
    old_code = "def run(cmd):\n    return eval(cmd)\n"
    new_code = "import ast\n\n\ndef run(cmd):\n    return ast.literal_eval(cmd)\n"
    rel_path = "sub/runner.py"
    archive_path = f"proj/{rel_path}"

    captured = {}

    def _patch_handler(sys_p, usr_p, _settings):
        captured["system"] = sys_p
        captured["user"] = usr_p
        finding = scan_body["findings"][0]
        return json.dumps(
            {
                "patches": [
                    {
                        "finding_id": finding["id"],
                        "target_file": rel_path,
                        "unified_diff": _make_unified_diff(rel_path, old_code, new_code),
                        "summary": "Replace eval() with ast.literal_eval() for safe literal parsing.",
                        "explanation": "Eliminates arbitrary code execution via eval().",
                        "confidence": "HIGH",
                        "assumptions_or_uncertainties": ["Assumes cmd represents a Python literal expression."],
                    }
                ],
                "limitations": [],
            }
        )

    patch_provider = _StubProvider(_patch_handler)
    client = make_patch_client(provider=patch_provider)
    pid, scan_body, analysis_json = _setup_analyzed_project(client, make_zip, {archive_path: old_code})
    analysis_body = _run_step4_analysis(client, pid, analysis_json, workspace)

    resp = client.post(f"/api/projects/{pid}/patches/generate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == pid
    assert body["scan_id"] == scan_body["scan_id"]
    assert body["report_id"] == analysis_body["report_id"]
    assert body["status"] == "completed"
    assert body["generated_count"] == 1
    assert body["rejected_count"] == 0
    assert len(body["patches"]) == 1

    patch_rec = body["patches"][0]
    assert patch_rec["patch_id"].startswith("patch-")
    assert patch_rec["applied"] is False
    assert patch_rec["status"] == "generated"
    assert patch_rec["file_path"] == rel_path
    assert "ast.literal_eval" in patch_rec["unified_diff"]
    assert patch_rec["validation"]["is_valid"] is True
    assert patch_rec["validation"]["target_file_verified"] is True
    assert patch_rec["validation"]["workspace_confined"] is True
    assert patch_rec["validation"]["hunks_count"] == 1
    assert patch_rec["validation"]["lines_added"] >= 1
    assert patch_rec["validation"]["lines_removed"] >= 1

    # Verify prompt explicitly carried Step 4 RCA & bounded source context.
    assert "eval(cmd)" in captured["user"]
    assert analysis_body["analyses"][0]["analysis_id"] in captured["user"]

    # Retrieve latest patch batch and individual patch by ID.
    get_latest = client.get(f"/api/projects/{pid}/patches")
    assert get_latest.status_code == 200
    assert get_latest.json()["batch_id"] == body["batch_id"]

    get_one = client.get(f"/api/projects/{pid}/patches/{patch_rec['patch_id']}")
    assert get_one.status_code == 200
    assert get_one.json()["patch_id"] == patch_rec["patch_id"]
    assert get_one.json()["unified_diff"] == patch_rec["unified_diff"]


def test_targeted_generation_by_finding_and_analysis_id(make_patch_client, make_zip, workspace):
    code = "def calc(a):\n    return a + missing_var\n"
    rel_path = "calc.py"
    archive_path = f"app_mod/{rel_path}"
    fixed_code = "def calc(a, missing_var=0):\n    return a + missing_var\n"

    def _handler(_sys, _usr, _settings):
        finding = scan_body["findings"][0]
        return json.dumps(
            {
                "patches": [
                    {
                        "finding_id": finding["id"],
                        "target_file": rel_path,
                        "unified_diff": _make_unified_diff(rel_path, code, fixed_code),
                        "summary": "Add missing_var parameter with safe default.",
                        "explanation": "Defines missing_var in calc signature.",
                        "confidence": "MEDIUM",
                    }
                ]
            }
        )

    client = make_patch_client(provider=_StubProvider(_handler))
    pid, scan_body, analysis_json = _setup_analyzed_project(client, make_zip, {archive_path: code})
    analysis_body = _run_step4_analysis(client, pid, analysis_json, workspace)

    target_finding_id = scan_body["findings"][0]["id"]
    target_analysis_id = analysis_body["analyses"][0]["analysis_id"]

    resp_by_finding = client.post(
        f"/api/projects/{pid}/patches/generate",
        json={"finding_id": target_finding_id},
    )
    assert resp_by_finding.status_code == 200
    assert resp_by_finding.json()["patches"][0]["finding_id"] == target_finding_id

    resp_by_analysis = client.post(
        f"/api/projects/{pid}/patches/generate",
        json={"analysis_id": target_analysis_id},
    )
    assert resp_by_analysis.status_code == 200
    assert resp_by_analysis.json()["patches"][0]["analysis_id"] == target_analysis_id


def test_source_files_and_prior_artifacts_remain_unmodified(make_patch_client, make_zip, workspace):
    rel_path = "buggy.py"
    archive_path = f"proj/{rel_path}"
    old_code = "def greet():\n    return undefined_name\n"
    new_code = "def greet():\n    return 'hello'\n"

    def _handler(_sys, _usr, _settings):
        finding = scan_body["findings"][0]
        return json.dumps(
            {
                "patches": [
                    {
                        "finding_id": finding["id"],
                        "target_file": rel_path,
                        "unified_diff": _make_unified_diff(rel_path, old_code, new_code),
                        "summary": "Return greeting string literal.",
                        "explanation": "Replaces undefined_name with string literal.",
                        "confidence": "HIGH",
                    }
                ]
            }
        )

    client = make_patch_client(provider=_StubProvider(_handler))
    pid, scan_body, analysis_json = _setup_analyzed_project(client, make_zip, {archive_path: old_code})
    _run_step4_analysis(client, pid, analysis_json, workspace)

    proj_dir = workspace / pid
    scan_before = (proj_dir / "scan_result.json").read_text(encoding="utf-8")
    analysis_before = (proj_dir / "analysis_result.json").read_text(encoding="utf-8")
    meta_before = (proj_dir / "metadata.json").read_text(encoding="utf-8")
    source_matches = list((proj_dir / "source").rglob("buggy.py"))
    assert len(source_matches) == 1
    source_before = source_matches[0].read_text(encoding="utf-8")

    resp = client.post(f"/api/projects/{pid}/patches/generate")
    assert resp.status_code == 200

    assert source_matches[0].read_text(encoding="utf-8") == source_before
    assert (proj_dir / "scan_result.json").read_text(encoding="utf-8") == scan_before
    assert (proj_dir / "analysis_result.json").read_text(encoding="utf-8") == analysis_before
    assert (proj_dir / "metadata.json").read_text(encoding="utf-8") == meta_before
    assert (proj_dir / "patches_result.json").is_file()


def test_missing_prerequisites_and_not_found_errors(make_patch_client, make_zip, workspace):
    client = make_patch_client()

    # Unknown project -> 404
    missing_proj = client.post("/api/projects/00000000000000000000000000000000/patches/generate")
    assert missing_proj.status_code == 404

    # Project uploaded without scan -> 404
    up = upload(client, make_zip({"proj/a.py": "x = unknown_var\n"}))
    assert up.status_code == 201
    pid = up.json()["project_id"]

    no_scan = client.post(f"/api/projects/{pid}/patches/generate")
    assert no_scan.status_code == 400
    assert "scan" in no_scan.json()["detail"].lower()

    # Scanned without Step 4 analysis -> 400
    scan_resp = client.post(f"/api/projects/{pid}/scan")
    assert scan_resp.status_code == 200
    no_analysis = client.post(f"/api/projects/{pid}/patches/generate")
    assert no_analysis.status_code == 400
    assert "analysis" in no_analysis.json()["detail"].lower()

    # No patches generated yet -> 404 on GET
    assert client.get(f"/api/projects/{pid}/patches").status_code == 404
    assert client.get(f"/api/projects/{pid}/patches/patch-1234567890ab").status_code == 404
    assert client.get(f"/api/projects/{pid}/patches/invalid-id").status_code == 404

    # Run analysis, then request missing finding_id -> 404
    scan_body = scan_resp.json()
    analysis_json = json.dumps(
        {
            "analyses": [
                {
                    "finding_id": scan_body["findings"][0]["id"],
                    "root_cause": "Undefined symbol.",
                    "technical_explanation": "unknown_var is not defined.",
                    "affected_component": "proj/a.py:L1",
                    "impact": "NameError at runtime.",
                    "recommended_fix": "Define unknown_var.",
                    "evidence": ["unknown_var"],
                    "confidence": "HIGH",
                    "confidence_reason": "Direct AST finding.",
                    "analysis_status": "completed",
                }
            ]
        }
    )
    _run_step4_analysis(client, pid, analysis_json, workspace)

    missing_finding = client.post(
        f"/api/projects/{pid}/patches/generate",
        json={"finding_id": "finding-nonexistent"},
    )
    assert missing_finding.status_code == 404


def test_missing_llm_configuration_returns_503(make_patch_client, make_zip, workspace):
    client = make_patch_client(llm_api_key=None)
    pid, _scan, analysis_json = _setup_analyzed_project(
        client, make_zip, {"proj/a.py": "x = unknown_var\n"}
    )
    _run_step4_analysis(client, pid, analysis_json, workspace)

    resp = client.post(f"/api/projects/{pid}/patches/generate")
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


def test_llm_provider_failure_returns_502_without_exposing_key(make_patch_client, make_zip, workspace):
    secret_key = "AIzaSySecretPatchTestKey1234567890"
    client = make_patch_client(llm_api_key=secret_key)
    pid, _scan, analysis_json = _setup_analyzed_project(
        client, make_zip, {"proj/a.py": "x = unknown_var\n"}
    )
    _run_step4_analysis(client, pid, analysis_json, workspace)

    mock_response = SimpleNamespace(
        status_code=403,
        text=f"Upstream rejected {secret_key}",
        json=lambda: {"error": {"message": f"bad key {secret_key}"}},
    )

    class _MockClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            return mock_response

    with patch("app.services.llm_provider.httpx.Client", _MockClient):
        resp = client.post(f"/api/projects/{pid}/patches/generate")

    assert resp.status_code == 502
    assert secret_key not in resp.text


def test_llm_rate_limit_and_timeout_statuses(make_patch_client, make_zip, workspace):
    client = make_patch_client(llm_api_key="test-key")
    pid, _scan, analysis_json = _setup_analyzed_project(
        client, make_zip, {"proj/a.py": "x = unknown_var\n"}
    )
    _run_step4_analysis(client, pid, analysis_json, workspace)

    class _RateLimitClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            return SimpleNamespace(status_code=429, text="quota exceeded")

    with patch("app.services.llm_provider.httpx.Client", _RateLimitClient):
        r429 = client.post(f"/api/projects/{pid}/patches/generate")
    assert r429.status_code == 429

    class _TimeoutClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            raise httpx.ReadTimeout("timed out")

    with patch("app.services.llm_provider.httpx.Client", _TimeoutClient):
        r504 = client.post(f"/api/projects/{pid}/patches/generate")
    assert r504.status_code == 504


def test_malformed_llm_json_returns_502(make_patch_client, make_zip, workspace):
    provider = _StubProvider(lambda *_args: "not valid json at all")
    client = make_patch_client(provider=provider)
    pid, _scan, analysis_json = _setup_analyzed_project(
        client, make_zip, {"proj/a.py": "x = unknown_var\n"}
    )
    _run_step4_analysis(client, pid, analysis_json, workspace)

    resp = client.post(f"/api/projects/{pid}/patches/generate")
    assert resp.status_code == 502


@pytest.mark.parametrize(
    "bad_diff",
    [
        # Empty diff
        "   \n  ",
        # Directory traversal
        "--- a/../secret.py\n+++ b/../secret.py\n@@ -1,1 +1,1 @@\n-x = unknown_var\n+x = 1\n",
        # Absolute POSIX path
        "--- a//etc/passwd\n+++ b//etc/passwd\n@@ -1,1 +1,1 @@\n-x = unknown_var\n+x = 1\n",
        # Windows drive path
        "--- C:\\temp\\a.py\n+++ C:\\temp\\a.py\n@@ -1,1 +1,1 @@\n-x = unknown_var\n+x = 1\n",
        # File creation (/dev/null)
        "new file mode 100644\n--- /dev/null\n+++ b/a.py\n@@ -0,0 +1,1 @@\n+x = 1\n",
        # File deletion (/dev/null)
        "deleted file mode 100644\n--- a/a.py\n+++ /dev/null\n@@ -1,1 +0,0 @@\n-x = unknown_var\n",
        # Multi-file diff
        (
            "--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-x = unknown_var\n+x = 1\n"
            "--- a/other.py\n+++ b/other.py\n@@ -1,1 +1,1 @@\n-y = 1\n+y = 2\n"
        ),
        # Wrong existing project file
        "--- a/other.py\n+++ b/other.py\n@@ -1,1 +1,1 @@\n-y = 1\n+y = 2\n",
        # No-op diff (no + or - changes)
        "--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n x = unknown_var\n",
        # Malformed hunk / context mismatch
        "--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,1 @@\n-non_matching_line\n+x = 1\n",
        # Binary patch
        "GIT binary patch\nliteral 4\nLcmZQzU|<0R002M$\n",
    ],
)
def test_unsafe_or_malformed_diffs_are_rejected_with_422(
    bad_diff, make_patch_client, make_zip, workspace
):
    def _handler(_sys, _usr, _settings):
        finding = scan_body["findings"][0]
        return json.dumps(
            {
                "patches": [
                    {
                        "finding_id": finding["id"],
                        "target_file": "a.py",
                        "unified_diff": bad_diff,
                        "summary": "Attempted fix.",
                        "explanation": "Explanation.",
                        "confidence": "LOW",
                    }
                ]
            }
        )

    client = make_patch_client(provider=_StubProvider(_handler))
    pid, scan_body, analysis_json = _setup_analyzed_project(
        client,
        make_zip,
        {
            "proj/a.py": "x = unknown_var\n",
            "proj/other.py": "y = 1\n",
        },
    )
    _run_step4_analysis(client, pid, analysis_json, workspace)

    resp = client.post(f"/api/projects/{pid}/patches/generate")
    assert resp.status_code == 422
    # Ensure no invalid patch was persisted
    assert client.get(f"/api/projects/{pid}/patches").status_code == 404


def test_partial_batch_keeps_valid_patch_and_records_rejection(
    make_patch_client, make_zip, workspace
):
    file_a = "def f1():\n    return missing_a\n"
    file_b = "def f2():\n    return missing_b\n"
    fixed_a = "def f1():\n    return 1\n"

    def _handler(_sys, _usr, _settings):
        f_by_path = {f["file_path"]: f for f in scan_body["findings"]}
        fa = f_by_path["a.py"]
        fb = f_by_path["b.py"]
        return json.dumps(
            {
                "patches": [
                    {
                        "finding_id": fa["id"],
                        "target_file": "a.py",
                        "unified_diff": _make_unified_diff("a.py", file_a, fixed_a),
                        "summary": "Return integer constant in f1.",
                        "explanation": "Replaces undefined missing_a with 1.",
                        "confidence": "HIGH",
                    },
                    {
                        "finding_id": fb["id"],
                        "target_file": "../escape.py",
                        "unified_diff": "--- a/../escape.py\n+++ b/../escape.py\n@@ -1,1 +1,1 @@\n-a\n+b\n",
                        "summary": "Unsafe patch.",
                        "explanation": "Should be rejected.",
                        "confidence": "LOW",
                    },
                ]
            }
        )

    client = make_patch_client(provider=_StubProvider(_handler))
    pid, scan_body, analysis_json = _setup_analyzed_project(
        client,
        make_zip,
        {"proj/a.py": file_a, "proj/b.py": file_b},
    )
    _run_step4_analysis(client, pid, analysis_json, workspace)

    resp = client.post(f"/api/projects/{pid}/patches/generate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "partial"
    assert body["generated_count"] == 1
    assert body["rejected_count"] == 1
    assert body["patches"][0]["file_path"] == "a.py"
    assert body["rejected_patches"][0]["file_path"] == "b.py"
