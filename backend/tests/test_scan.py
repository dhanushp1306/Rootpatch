import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.schemas.scan import FindingRecord, ScannerToolSummary
from app.services.scan_service import _collect_python_files, deduplicate_findings
from app.services.scanners.ast_scanner import run_ast_scan
from app.services.scanners.bandit_scanner import BanditScanOutcome
from app.services.scanners.ruff_scanner import RuffScanOutcome
from conftest import upload


def _upload_files(client, make_zip, files):
    resp = upload(client, make_zip(files))
    assert resp.status_code == 201
    return resp.json()["project_id"]


def test_clean_python_project(client, make_zip):
    pid = _upload_files(
        client,
        make_zip,
        {
            "clean_proj/math_utils.py": (
                "def add(a: int, b: int) -> int:\n"
                "    return a + b\n"
            ),
            "clean_proj/tests/test_math.py": (
                "from math_utils import add\n\n"
                "def test_add() -> None:\n"
                "    assert add(1, 2) == 3\n"
            ),
        },
    )

    resp = client.post(f"/api/projects/{pid}/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_id"] == pid
    assert body["scan_id"].startswith("scan-")
    assert body["files_scanned"] == 2
    assert body["total_findings"] == 0
    assert body["findings"] == []
    assert body["severity_summary"] == {
        "CRITICAL": 0,
        "HIGH": 0,
        "MEDIUM": 0,
        "LOW": 0,
        "INFO": 0,
    }


def test_python_syntax_error(client, make_zip):
    pid = _upload_files(
        client,
        make_zip,
        {"proj/broken.py": "def broken(:\n    return 1\n"},
    )

    resp = client.post(f"/api/projects/{pid}/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_findings"] >= 1
    syntax_findings = [f for f in body["findings"] if f["category"] == "syntax"]
    assert syntax_findings
    assert syntax_findings[0]["file_path"] == "broken.py"
    assert syntax_findings[0]["severity"] == "HIGH"


def test_undefined_variable(client, make_zip):
    pid = _upload_files(
        client,
        make_zip,
        {
            "proj/undef.py": (
                "def compute(x):\n"
                "    return x + missing_var\n"
            )
        },
    )

    resp = client.post(f"/api/projects/{pid}/scan")
    assert resp.status_code == 200
    body = resp.json()
    undef = [
        f
        for f in body["findings"]
        if "missing_var" in f["title"] or "missing_var" in f["description"] or f["rule_id"] in {"AST401", "F821"}
    ]
    assert undef
    assert undef[0]["severity"] == "HIGH"
    assert undef[0]["line_number"] == 2


def test_unused_import(client, make_zip):
    pid = _upload_files(
        client,
        make_zip,
        {
            "proj/imports.py": (
                "import json\n\n"
                "def hello():\n"
                "    return 'world'\n"
            )
        },
    )

    resp = client.post(f"/api/projects/{pid}/scan")
    assert resp.status_code == 200
    body = resp.json()
    unused = [f for f in body["findings"] if f["rule_id"] in {"AST301", "F401"}]
    assert unused
    assert unused[0]["file_path"] == "imports.py"
    assert unused[0]["line_number"] == 1


def test_suspicious_subprocess_usage(client, make_zip):
    pid = _upload_files(
        client,
        make_zip,
        {
            "proj/runner.py": (
                "import subprocess\n\n"
                "def run_cmd(cmd):\n"
                "    return subprocess.run(cmd, shell=True)\n"
            )
        },
    )

    resp = client.post(f"/api/projects/{pid}/scan")
    assert resp.status_code == 200
    body = resp.json()
    shell_findings = [
        f
        for f in body["findings"]
        if f["category"] == "security" and f["line_number"] == 4
    ]
    assert shell_findings
    assert shell_findings[0]["severity"] == "HIGH"


def test_hardcoded_credentials(client, make_zip):
    pid = _upload_files(
        client,
        make_zip,
        {
            "proj/secrets_demo.py": (
                "def connect():\n"
                "    password = 'super-secret-value-123'\n"
                "    return password\n"
            )
        },
    )

    resp = client.post(f"/api/projects/{pid}/scan")
    assert resp.status_code == 200
    body = resp.json()
    cred_findings = [f for f in body["findings"] if f["category"] == "security"]
    assert cred_findings
    # Secret literal must not be echoed verbatim in AST501 redacted evidence
    ast_cred = [f for f in cred_findings if f["rule_id"] == "AST501"]
    if ast_cred:
        assert "super-secret-value-123" not in ast_cred[0]["evidence"]


def test_multiple_issues_in_one_file(client, make_zip):
    pid = _upload_files(
        client,
        make_zip,
        {
            "proj/multi.py": (
                "import os\n"
                "import sys\n\n"
                "def risky(user_input, items=[]):\n"
                "    items.append(user_input)\n"
                "    return eval(user_input)\n"
            )
        },
    )

    resp = client.post(f"/api/projects/{pid}/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["files_scanned"] == 1
    assert body["total_findings"] >= 3


def test_multiple_python_files(client, make_zip):
    pid = _upload_files(
        client,
        make_zip,
        {
            "proj/a.py": "import math\n\ndef f():\n    return 1\n",
            "proj/sub/b.py": "def g():\n    return unknown_symbol\n",
        },
    )

    resp = client.post(f"/api/projects/{pid}/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["files_scanned"] == 2
    files_with_findings = {f["file_path"] for f in body["findings"]}
    assert files_with_findings == {"a.py", "sub/b.py"}


def test_empty_project_no_python_files(client, make_zip):
    pid = _upload_files(
        client,
        make_zip,
        {"proj/README.md": "# No Python here\n"},
    )

    resp = client.post(f"/api/projects/{pid}/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["files_scanned"] == 0
    assert body["total_findings"] == 0
    assert body["findings"] == []


def test_missing_project_returns_404(client):
    missing_id = "0" * 32
    assert client.post(f"/api/projects/{missing_id}/scan").status_code == 404
    assert client.get(f"/api/projects/{missing_id}/scan").status_code == 404


def test_invalid_project_id_returns_404(client):
    for bad_id in ("not-a-valid-id", "..", "Z" * 32):
        assert client.post(f"/api/projects/{bad_id}/scan").status_code == 404
        assert client.get(f"/api/projects/{bad_id}/scan").status_code == 404


def test_unsupported_file_types_ignored_during_scan(client, make_zip):
    pid = _upload_files(
        client,
        make_zip,
        {
            "proj/index.js": "eval('alert(1)');\n",
            "proj/notes.txt": "password = 'abc'\n",
            "proj/ok.py": "def ok():\n    return 42\n",
        },
    )

    resp = client.post(f"/api/projects/{pid}/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["files_scanned"] == 1
    assert all(f["file_path"].endswith(".py") for f in body["findings"])


def test_unreadable_file_handled_gracefully(tmp_path):
    bad_file = tmp_path / "binary.py"
    bad_file.write_bytes(b"\xff\xfe\x00\x80invalid-utf8")
    good_file = tmp_path / "good.py"
    good_file.write_text("def ok():\n    return 1\n", encoding="utf-8")

    outcome = run_ast_scan(tmp_path, ["binary.py", "good.py"], max_file_bytes=1024 * 1024)

    assert outcome.files_scanned == 1
    assert len(outcome.skipped_files) == 1
    assert outcome.skipped_files[0].file_path == "binary.py"
    assert "UTF-8" in outcome.skipped_files[0].reason
    assert outcome.summary.status == "completed"


@pytest.mark.skipif(os.name == "nt", reason="chmod 000 behavior varies on Windows")
def test_chmod_unreadable_file_handled_gracefully(tmp_path):
    locked = tmp_path / "locked.py"
    locked.write_text("x = 1\n", encoding="utf-8")
    locked.chmod(0o000)
    try:
        outcome = run_ast_scan(tmp_path, ["locked.py"], max_file_bytes=1024 * 1024)
        # If running as root in container, chmod 000 may still be readable; only assert if skipped
        if outcome.files_scanned == 0:
            assert len(outcome.skipped_files) == 1
            assert outcome.skipped_files[0].file_path == "locked.py"
    finally:
        locked.chmod(0o644)


def test_scanner_timeout_and_failure_do_not_crash_scan(client, make_zip):
    pid = _upload_files(
        client,
        make_zip,
        {"proj/app.py": "import os\n\ndef f():\n    return 1\n"},
    )

    timed_out_ruff = RuffScanOutcome(
        findings=[],
        summary=ScannerToolSummary(status="timed_out", error="Ruff timed out after 30s."),
    )
    failed_bandit = BanditScanOutcome(
        findings=[],
        summary=ScannerToolSummary(status="failed", error="Bandit exited with code 2."),
    )

    with (
        patch("app.services.scan_service.run_ruff_scan", return_value=timed_out_ruff),
        patch("app.services.scan_service.run_bandit_scan", return_value=failed_bandit),
    ):
        resp = client.post(f"/api/projects/{pid}/scan")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "partial"
    assert body["scanner_summary"]["ast"] == "completed"
    assert body["scanner_summary"]["ruff"] == "timed_out"
    assert body["scanner_summary"]["bandit"] == "failed"
    assert "timed out" in body["scanner_details"]["ruff"]["error"].lower()
    assert body["total_findings"] >= 1  # AST findings still returned


def test_ruff_subprocess_timeout_handled():
    from app.services.scanners.ruff_scanner import run_ruff_scan

    with patch(
        "app.services.scanners.ruff_scanner.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="ruff", timeout=1),
    ):
        outcome = run_ruff_scan(Path("."), ["a.py"], timeout_seconds=1)

    assert outcome.summary.status == "timed_out"
    assert outcome.findings == []
    assert outcome.summary.error is not None


def test_path_traversal_protection_in_scan_collection(tmp_path):
    project_root = tmp_path / "workspace" / "proj"
    project_root.mkdir(parents=True)
    outside = tmp_path / "secret.py"
    outside.write_text("secret = '123'\n", encoding="utf-8")
    (project_root / "safe.py").write_text("x = 1\n", encoding="utf-8")

    # Even if an adversarial relative path is passed to AST scanner directly, it is blocked
    outcome = run_ast_scan(project_root, ["../secret.py", "safe.py"], max_file_bytes=1024 * 1024)
    assert outcome.files_scanned == 1
    assert any(s.file_path == "../secret.py" and "escapes" in s.reason for s in outcome.skipped_files)

    # Symlinks inside project root pointing outside are skipped during collection
    try:
        (project_root / "link.py").symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation not permitted")
    collected, _ = _collect_python_files(project_root, max_files=100)
    assert collected == ["safe.py"]


def test_duplicate_finding_deduplication_preserves_evidence():
    ast_finding = FindingRecord(
        id="fnd-ast",
        file_path="app.py",
        line_number=4,
        column=5,
        tool="ast",
        rule_id="AST104",
        category="security",
        severity="HIGH",
        confidence="HIGH",
        original_severity="HIGH",
        original_confidence="HIGH",
        title="Shell command execution via subprocess.run()",
        description="AST detected shell=True",
        evidence="subprocess.run(cmd, shell=True)",
        suggested_fix="Use shell=False",
    )
    bandit_finding = FindingRecord(
        id="fnd-bandit",
        file_path="app.py",
        line_number=4,
        column=5,
        tool="bandit",
        rule_id="B602",
        category="security",
        severity="HIGH",
        confidence="HIGH",
        original_severity="HIGH",
        original_confidence="HIGH",
        title="Potential security issue (B602): subprocess popen with shell equals true",
        description="subprocess call with shell=True identified, security issue.",
        evidence="4 subprocess.run(cmd, shell=True)",
        suggested_fix=None,
    )

    deduped = deduplicate_findings([ast_finding, bandit_finding])
    assert len(deduped) == 1
    primary = deduped[0]
    assert primary.tool == "bandit"
    assert primary.secondary_tools == ["ast"]
    assert len(primary.related_findings) == 1
    assert primary.related_findings[0]["rule_id"] == "AST104"
    assert primary.suggested_fix == "Use shell=False"


def test_get_latest_scan_persistence_and_404_before_scan(client, make_zip):
    pid = _upload_files(client, make_zip, {"proj/app.py": "import os\n"})

    assert client.get(f"/api/projects/{pid}/scan").status_code == 404

    post_resp = client.post(f"/api/projects/{pid}/scan")
    assert post_resp.status_code == 200
    scan_id = post_resp.json()["scan_id"]

    get_resp = client.get(f"/api/projects/{pid}/scan")
    assert get_resp.status_code == 200
    assert get_resp.json()["scan_id"] == scan_id


def test_uploaded_code_never_executed(client, make_zip, tmp_path):
    marker = tmp_path / "pwned.txt"
    pid = _upload_files(
        client,
        make_zip,
        {
            "proj/evil.py": (
                f"open({str(marker)!r}, 'w').write('executed')\n"
                "raise RuntimeError('should never execute')\n"
            )
        },
    )

    resp = client.post(f"/api/projects/{pid}/scan")
    assert resp.status_code == 200
    assert not marker.exists()


def test_assert_rules_suppressed_in_test_files_but_kept_in_source_files(tmp_path):
    import json
    from types import SimpleNamespace
    from app.services.scanners.bandit_scanner import run_bandit_scan
    from app.services.scanners.ruff_scanner import run_ruff_scan

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_math.py").write_text("assert True\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("assert user.is_admin\n", encoding="utf-8")

    ruff_payload = [
        {
            "code": "S101",
            "message": "Use of `assert` detected",
            "filename": "tests/test_math.py",
            "location": {"row": 1, "column": 1},
        },
        {
            "code": "S101",
            "message": "Use of `assert` detected",
            "filename": "app.py",
            "location": {"row": 1, "column": 1},
        },
    ]
    bandit_payload = {
        "results": [
            {
                "test_id": "B101",
                "test_name": "assert_used",
                "issue_text": "Use of assert detected.",
                "issue_severity": "LOW",
                "issue_confidence": "HIGH",
                "filename": "tests/test_math.py",
                "line_number": 1,
                "col_offset": 0,
                "code": "1 assert True",
            },
            {
                "test_id": "B101",
                "test_name": "assert_used",
                "issue_text": "Use of assert detected.",
                "issue_severity": "LOW",
                "issue_confidence": "HIGH",
                "filename": "app.py",
                "line_number": 1,
                "col_offset": 0,
                "code": "1 assert user.is_admin",
            },
        ]
    }

    with patch(
        "app.services.scanners.ruff_scanner.subprocess.run",
        return_value=SimpleNamespace(returncode=1, stdout=json.dumps(ruff_payload), stderr=""),
    ):
        ruff_out = run_ruff_scan(tmp_path, ["tests/test_math.py", "app.py"], timeout_seconds=10)

    with patch(
        "app.services.scanners.bandit_scanner.subprocess.run",
        return_value=SimpleNamespace(returncode=1, stdout=json.dumps(bandit_payload), stderr=""),
    ):
        bandit_out = run_bandit_scan(tmp_path, ["tests/test_math.py", "app.py"], timeout_seconds=10)

    assert [f.file_path for f in ruff_out.findings] == ["app.py"]
    assert [f.file_path for f in bandit_out.findings] == ["app.py"]

    deduped = deduplicate_findings([*ruff_out.findings, *bandit_out.findings])
    assert len(deduped) == 1
    assert deduped[0].file_path == "app.py"
    assert len(deduped[0].related_findings) == 1


def test_real_issues_in_test_files_are_not_suppressed(client, make_zip):
    pid = _upload_files(
        client,
        make_zip,
        {
            "proj/tests/test_bad.py": (
                "import subprocess\n\n"
                "def test_cmd():\n"
                "    subprocess.run('ls', shell=True)\n"
                "    assert True\n"
            )
        },
    )

    resp = client.post(f"/api/projects/{pid}/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert any(
        f["file_path"] == "tests/test_bad.py" and f["category"] == "security" and f["line_number"] == 4
        for f in body["findings"]
    )
    assert not any(f["rule_id"] in {"S101", "B101"} for f in body["findings"])
