import difflib
import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings, settings as default_settings
from app.services.llm_provider import get_llm_provider
from conftest import upload
from main import app


class _StubProvider:
    def __init__(self, handler):
        self.handler = handler

    def analyze(self, system_prompt: str, user_prompt: str, settings) -> str:
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


@pytest.fixture
def make_step6_client(workspace):
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


def _prepare_generated_patch(
    make_step6_client,
    make_zip,
    workspace,
    archive_files: dict[str, str],
    rel_path: str,
    old_code: str,
    new_code: str,
):
    client = make_step6_client()
    up = upload(client, make_zip(archive_files))
    assert up.status_code == 201
    pid = up.json()["project_id"]

    scan_resp = client.post(f"/api/projects/{pid}/scan")
    assert scan_resp.status_code == 200
    scan_body = scan_resp.json()
    finding = next(f for f in scan_body["findings"] if f["file_path"] == rel_path)

    analysis_json = json.dumps(
        {
            "analyses": [
                {
                    "finding_id": f["id"],
                    "root_cause": f"Rule {f['rule_id']} triggered on {f['file_path']}.",
                    "technical_explanation": "Static flaw confirmed on source line.",
                    "affected_component": f"{f['file_path']}:L{f['line_number']}",
                    "impact": "Potential runtime or security failure.",
                    "recommended_fix": "Replace unsafe expression with safe equivalent.",
                    "evidence": [f.get("evidence", "")],
                    "assumptions_or_uncertainties": [],
                    "related_finding_ids": [],
                    "relationship_explanation": None,
                    "confidence": "HIGH",
                    "confidence_reason": "Directly observed in workspace source.",
                    "analysis_status": "completed",
                }
                for f in scan_body["findings"]
            ],
            "shared_root_cause_groups": [],
            "limitations": [],
        }
    )

    test_settings = replace(
        default_settings,
        workspace_dir=workspace,
        llm_api_key="test-placeholder-key",
    )
    app.dependency_overrides[get_settings] = lambda: test_settings
    app.dependency_overrides[get_llm_provider] = lambda: _StubProvider(lambda *_: analysis_json)
    ana_resp = client.post(f"/api/projects/{pid}/analyze")
    assert ana_resp.status_code == 200

    patch_json = json.dumps(
        {
            "patches": [
                {
                    "finding_id": finding["id"],
                    "target_file": rel_path,
                    "unified_diff": _make_unified_diff(rel_path, old_code, new_code),
                    "summary": "Apply safe fix.",
                    "explanation": "Replaces defective statement with safe implementation.",
                    "confidence": "HIGH",
                }
            ]
        }
    )
    app.dependency_overrides[get_llm_provider] = lambda: _StubProvider(lambda *_: patch_json)
    gen_resp = client.post(
        f"/api/projects/{pid}/patches/generate",
        json={"finding_id": finding["id"]},
    )
    assert gen_resp.status_code == 200
    patch_rec = gen_resp.json()["patches"][0]
    assert patch_rec["status"] == "generated"
    assert patch_rec["applied"] is False
    return client, pid, patch_rec


def test_successful_patch_review_before_approval(make_step6_client, make_zip, workspace):
    old_code = "def greet():\n    return undefined_name\n"
    new_code = "def greet():\n    return 'hello'\n"
    client, pid, patch_rec = _prepare_generated_patch(
        make_step6_client,
        make_zip,
        workspace,
        {"proj/sub/greet.py": old_code, "proj/other.py": "X = 1\n"},
        "sub/greet.py",
        old_code,
        new_code,
    )
    patch_id = patch_rec["patch_id"]

    rev = client.get(f"/api/projects/{pid}/patches/{patch_id}/review")
    assert rev.status_code == 200
    body = rev.json()
    assert body["patch_id"] == patch_id
    assert body["project_id"] == pid
    assert body["finding_id"] == patch_rec["finding_id"]
    assert body["file_path"] == "sub/greet.py"
    assert body["status"] == "generated"
    assert body["approval_status"] == "pending"
    assert body["application_status"] == "not_applied"
    assert body["applied"] is False
    assert body["validation"]["is_valid"] is True
    assert "undefined_name" in body["original_code"]
    assert "'hello'" in body["proposed_code"]
    assert "-    return undefined_name" in body["unified_diff"]
    assert body["generated_at"]
    assert body["is_stale"] is False
    assert body["can_approve"] is True
    assert body["can_reject"] is True
    assert body["can_apply"] is False

    # Review must never mutate source files on disk.
    target = workspace / pid / "source" / "proj" / "sub" / "greet.py"
    assert target.read_text(encoding="utf-8") == old_code


def test_successful_approval_is_explicit_and_idempotent(make_step6_client, make_zip, workspace):
    old_code = "def greet():\n    return undefined_name\n"
    new_code = "def greet():\n    return 'hello'\n"
    client, pid, patch_rec = _prepare_generated_patch(
        make_step6_client,
        make_zip,
        workspace,
        {"proj/greet.py": old_code},
        "greet.py",
        old_code,
        new_code,
    )
    patch_id = patch_rec["patch_id"]

    app_resp = client.post(
        f"/api/projects/{pid}/patches/{patch_id}/approve",
        json={"comment": "Reviewed diff and confirmed safe."},
    )
    assert app_resp.status_code == 200
    approved = app_resp.json()
    assert approved["status"] == "approved"
    assert approved["approval_status"] == "approved"
    assert approved["application_status"] == "not_applied"
    assert approved["applied"] is False
    assert approved["reviewed_at"]
    assert approved["review_note"] == "Reviewed diff and confirmed safe."

    # Repeated approval succeeds idempotently without modifying the file.
    app_again = client.post(f"/api/projects/{pid}/patches/{patch_id}/approve")
    assert app_again.status_code == 200
    assert app_again.json()["status"] == "approved"

    target = workspace / pid / "source" / "proj" / "greet.py"
    assert target.read_text(encoding="utf-8") == old_code


def test_successful_rejection_blocks_approval_and_application(make_step6_client, make_zip, workspace):
    old_code = "def greet():\n    return undefined_name\n"
    new_code = "def greet():\n    return 'hello'\n"
    client, pid, patch_rec = _prepare_generated_patch(
        make_step6_client,
        make_zip,
        workspace,
        {"proj/greet.py": old_code},
        "greet.py",
        old_code,
        new_code,
    )
    patch_id = patch_rec["patch_id"]

    rej_resp = client.post(
        f"/api/projects/{pid}/patches/{patch_id}/reject",
        json={"comment": "Prefer explicit parameter instead."},
    )
    assert rej_resp.status_code == 200
    rejected = rej_resp.json()
    assert rejected["status"] == "rejected"
    assert rejected["approval_status"] == "rejected"
    assert rejected["applied"] is False
    assert rejected["review_note"] == "Prefer explicit parameter instead."

    # Repeated rejection is idempotent.
    rej_again = client.post(f"/api/projects/{pid}/patches/{patch_id}/reject")
    assert rej_again.status_code == 200
    assert rej_again.json()["status"] == "rejected"

    # Approving or applying a rejected patch must fail cleanly with 409.
    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/approve").status_code == 409
    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/apply").status_code == 409

    target = workspace / pid / "source" / "proj" / "greet.py"
    assert target.read_text(encoding="utf-8") == old_code


def test_apply_requires_explicit_approval_and_prevents_duplicates(
    make_step6_client, make_zip, workspace
):
    old_code = "def greet():\n    return undefined_name\n"
    new_code = "def greet():\n    return 'hello'\n"
    unrelated_code = "CONSTANT = 42\n"
    client, pid, patch_rec = _prepare_generated_patch(
        make_step6_client,
        make_zip,
        workspace,
        {"proj/greet.py": old_code, "proj/unrelated.py": unrelated_code},
        "greet.py",
        old_code,
        new_code,
    )
    patch_id = patch_rec["patch_id"]
    proj_dir = workspace / pid
    target = proj_dir / "source" / "proj" / "greet.py"
    unrelated = proj_dir / "source" / "proj" / "unrelated.py"

    # Unapproved patch cannot be applied.
    unapproved_apply = client.post(f"/api/projects/{pid}/patches/{patch_id}/apply")
    assert unapproved_apply.status_code == 409
    assert target.read_text(encoding="utf-8") == old_code

    # Empty application history prior to any apply attempt.
    hist_empty = client.get(f"/api/projects/{pid}/patches/history")
    assert hist_empty.status_code == 200
    assert hist_empty.json()["total_events"] == 0

    # Approve and apply.
    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/approve").status_code == 200
    assert target.read_text(encoding="utf-8") == old_code  # Still unchanged until apply!

    scan_before = (proj_dir / "scan_result.json").read_text(encoding="utf-8")
    analysis_before = (proj_dir / "analysis_result.json").read_text(encoding="utf-8")
    meta_before = (proj_dir / "metadata.json").read_text(encoding="utf-8")

    apply_resp = client.post(f"/api/projects/{pid}/patches/{patch_id}/apply")
    assert apply_resp.status_code == 200
    applied_body = apply_resp.json()
    assert applied_body["patch"]["status"] == "applied"
    assert applied_body["patch"]["application_status"] == "applied"
    assert applied_body["patch"]["applied"] is True
    assert applied_body["patch"]["applied_at"]

    old_sha = hashlib.sha256(old_code.encode("utf-8")).hexdigest()
    new_sha = hashlib.sha256(new_code.encode("utf-8")).hexdigest()
    assert applied_body["patch"]["applied_file_sha256"] == new_sha
    assert applied_body["application_record"]["result"] == "applied"
    assert applied_body["application_record"]["previous_file_sha256"] == old_sha
    assert applied_body["application_record"]["new_file_sha256"] == new_sha
    assert applied_body["application_record"]["file_path"] == "greet.py"

    # Target file updated; unrelated file and prior artifacts untouched; backup preserved.
    assert target.read_text(encoding="utf-8") == new_code
    assert unrelated.read_text(encoding="utf-8") == unrelated_code
    assert (proj_dir / "scan_result.json").read_text(encoding="utf-8") == scan_before
    assert (proj_dir / "analysis_result.json").read_text(encoding="utf-8") == analysis_before
    assert (proj_dir / "metadata.json").read_text(encoding="utf-8") == meta_before

    backup_file = proj_dir / applied_body["patch"]["backup_path"]
    assert backup_file.is_file()
    assert backup_file.read_text(encoding="utf-8") == old_code

    # Duplicate application and post-apply rejection must fail with 409.
    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/apply").status_code == 409
    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/reject").status_code == 409
    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/approve").status_code == 409

    # Post-apply review exposes backup original_code and applied proposed_code.
    rev_after = client.get(f"/api/projects/{pid}/patches/{patch_id}/review").json()
    assert rev_after["status"] == "applied"
    assert rev_after["can_apply"] is False
    assert "undefined_name" in rev_after["original_code"]
    assert "'hello'" in rev_after["proposed_code"]

    # History reflects the applied event.
    hist = client.get(f"/api/projects/{pid}/patches/history")
    assert hist.status_code == 200
    hist_body = hist.json()
    assert hist_body["total_events"] == 1
    assert hist_body["applied_count"] == 1
    assert hist_body["history"][0]["patch_id"] == patch_id
    assert hist_body["history"][0]["result"] == "applied"


def test_invalid_patch_ids_and_missing_project_return_404(
    make_step6_client, make_zip, workspace
):
    old_code = "def greet():\n    return undefined_name\n"
    new_code = "def greet():\n    return 'hello'\n"
    client, pid, _patch_rec = _prepare_generated_patch(
        make_step6_client,
        make_zip,
        workspace,
        {"proj/greet.py": old_code},
        "greet.py",
        old_code,
        new_code,
    )

    missing_pid = "0" * 32
    valid_missing_patch = "patch-000000000000"
    for endpoint in (
        f"/api/projects/{missing_pid}/patches/history",
        f"/api/projects/{missing_pid}/patches/{valid_missing_patch}/review",
        f"/api/projects/{pid}/patches/not-a-valid-patch-id/review",
        f"/api/projects/{pid}/patches/{valid_missing_patch}/review",
    ):
        assert client.get(endpoint).status_code == 404

    for action in ("approve", "reject", "apply"):
        assert client.post(f"/api/projects/{missing_pid}/patches/{valid_missing_patch}/{action}").status_code == 404
        assert client.post(f"/api/projects/{pid}/patches/bad-id/{action}").status_code == 404
        assert client.post(f"/api/projects/{pid}/patches/{valid_missing_patch}/{action}").status_code == 404


def test_stale_source_and_hash_mismatch_rejected(make_step6_client, make_zip, workspace):
    old_code = "def greet():\n    return undefined_name\n"
    new_code = "def greet():\n    return 'hello'\n"
    client, pid, patch_rec = _prepare_generated_patch(
        make_step6_client,
        make_zip,
        workspace,
        {"proj/greet.py": old_code},
        "greet.py",
        old_code,
        new_code,
    )
    patch_id = patch_rec["patch_id"]
    target = workspace / pid / "source" / "proj" / "greet.py"

    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/approve").status_code == 200

    # Simulate external/newer edit to workspace file after patch generation & approval.
    newer_code = "def greet():\n    return 'manual_edit'\n"
    target.write_text(newer_code, encoding="utf-8")

    rev = client.get(f"/api/projects/{pid}/patches/{patch_id}/review").json()
    assert rev["is_stale"] is True
    assert rev["can_apply"] is False

    stale_apply = client.post(f"/api/projects/{pid}/patches/{patch_id}/apply")
    assert stale_apply.status_code == 409
    assert "stale" in stale_apply.json()["detail"].lower()
    # Newer source changes must NOT be overwritten.
    assert target.read_text(encoding="utf-8") == newer_code

    updated_rec = client.get(f"/api/projects/{pid}/patches/{patch_id}").json()
    assert updated_rec["status"] == "stale"
    assert updated_rec["application_status"] == "stale"
    assert updated_rec["applied"] is False

    hist = client.get(f"/api/projects/{pid}/patches/history").json()
    assert hist["stale_count"] == 1
    assert hist["history"][0]["result"] == "stale"


def test_source_hash_mismatch_tampered_metadata_rejected(make_step6_client, make_zip, workspace):
    old_code = "def greet():\n    return undefined_name\n"
    new_code = "def greet():\n    return 'hello'\n"
    client, pid, patch_rec = _prepare_generated_patch(
        make_step6_client,
        make_zip,
        workspace,
        {"proj/greet.py": old_code},
        "greet.py",
        old_code,
        new_code,
    )
    patch_id = patch_rec["patch_id"]
    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/approve").status_code == 200

    # Tamper stored original_file_sha256 to simulate hash mismatch.
    store_path = workspace / pid / "patches_result.json"
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    raw["latest"]["patches"][0]["validation"]["original_file_sha256"] = "0" * 64
    raw["history"][0]["patches"][0]["validation"]["original_file_sha256"] = "0" * 64
    store_path.write_text(json.dumps(raw), encoding="utf-8")

    resp = client.post(f"/api/projects/{pid}/patches/{patch_id}/apply")
    assert resp.status_code == 409
    target = workspace / pid / "source" / "proj" / "greet.py"
    assert target.read_text(encoding="utf-8") == old_code


def test_path_traversal_blocked_at_apply(make_step6_client, make_zip, workspace, tmp_path):
    old_code = "def greet():\n    return undefined_name\n"
    new_code = "def greet():\n    return 'hello'\n"
    client, pid, patch_rec = _prepare_generated_patch(
        make_step6_client,
        make_zip,
        workspace,
        {"proj/greet.py": old_code},
        "greet.py",
        old_code,
        new_code,
    )
    patch_id = patch_rec["patch_id"]
    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/approve").status_code == 200

    outside_target = tmp_path / "outside_secret.py"
    outside_target.write_text(old_code, encoding="utf-8")

    # Simulate tampered patch metadata attempting path traversal.
    store_path = workspace / pid / "patches_result.json"
    raw = json.loads(store_path.read_text(encoding="utf-8"))
    raw["latest"]["patches"][0]["file_path"] = "../../../outside_secret.py"
    raw["history"][0]["patches"][0]["file_path"] = "../../../outside_secret.py"
    store_path.write_text(json.dumps(raw), encoding="utf-8")

    resp = client.post(f"/api/projects/{pid}/patches/{patch_id}/apply")
    assert resp.status_code == 422
    assert outside_target.read_text(encoding="utf-8") == old_code

    hist = client.get(f"/api/projects/{pid}/patches/history").json()
    assert hist["failed_count"] == 1
    assert hist["history"][0]["result"] == "failed"


def test_symlink_attack_blocked_at_apply(make_step6_client, make_zip, workspace, tmp_path):
    old_code = "def greet():\n    return undefined_name\n"
    new_code = "def greet():\n    return 'hello'\n"
    client, pid, patch_rec = _prepare_generated_patch(
        make_step6_client,
        make_zip,
        workspace,
        {"proj/greet.py": old_code},
        "greet.py",
        old_code,
        new_code,
    )
    patch_id = patch_rec["patch_id"]
    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/approve").status_code == 200

    outside_target = tmp_path / "external_victim.py"
    outside_target.write_text(old_code, encoding="utf-8")
    target = workspace / pid / "source" / "proj" / "greet.py"
    target.unlink()
    try:
        os.symlink(outside_target, target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlink creation unsupported in this environment: {exc}")

    resp = client.post(f"/api/projects/{pid}/patches/{patch_id}/apply")
    assert resp.status_code == 422
    assert outside_target.read_text(encoding="utf-8") == old_code

    rec = client.get(f"/api/projects/{pid}/patches/{patch_id}").json()
    assert rec["status"] == "application_failed"
    assert rec["applied"] is False


def test_application_failure_recovers_and_preserves_original_file(
    make_step6_client, make_zip, workspace
):
    old_code = "def greet():\n    return undefined_name\n"
    new_code = "def greet():\n    return 'hello'\n"
    client, pid, patch_rec = _prepare_generated_patch(
        make_step6_client,
        make_zip,
        workspace,
        {"proj/greet.py": old_code},
        "greet.py",
        old_code,
        new_code,
    )
    patch_id = patch_rec["patch_id"]
    target = workspace / pid / "source" / "proj" / "greet.py"

    assert client.post(f"/api/projects/{pid}/patches/{patch_id}/approve").status_code == 200

    def _corrupt_then_fail(path: Path, _content: bytes) -> None:
        # Simulate partial/corrupted target write followed by failure to test recovery.
        path.write_text("# corrupted partial content", encoding="utf-8")
        raise OSError("Simulated I/O failure during target write")

    with patch("app.services.patch_service._write_target_file_bytes", side_effect=_corrupt_then_fail):
        resp = client.post(f"/api/projects/{pid}/patches/{patch_id}/apply")

    assert resp.status_code == 500
    assert target.read_text(encoding="utf-8") == old_code

    rec = client.get(f"/api/projects/{pid}/patches/{patch_id}").json()
    assert rec["status"] == "application_failed"
    assert rec["application_status"] == "failed"
    assert rec["applied"] is False

    hist = client.get(f"/api/projects/{pid}/patches/history").json()
    assert hist["total_events"] == 1
    assert hist["failed_count"] == 1
    assert hist["history"][0]["result"] == "failed"
