"""Comprehensive Step 7 tests for isolated testing and patch validation.

All test runs use mocked `ContainerRunner` implementations or mocked `subprocess.run`
on `DockerContainerRunner`. Uploaded project code is NEVER executed on the host.
"""

import difflib
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings, settings as default_settings
from app.schemas.validation import ContainerExecutionSpec, ContainerRunResult
from app.services.container_runner import DockerContainerRunner, get_container_runner
from app.services.llm_provider import get_llm_provider
from app.services.test_detector import detect_test_configuration, validate_test_command_override
from conftest import upload
from main import app


class _StubProvider:
    def __init__(self, handler):
        self.handler = handler

    def analyze(self, system_prompt: str, user_prompt: str, settings) -> str:
        return self.handler(system_prompt, user_prompt, settings)


class _RecordingContainerRunner:
    """In-memory mock ContainerRunner inspecting isolated temp snapshots without executing code."""

    def __init__(self, available: bool = True, unavailable_reason: str | None = None, handler=None):
        self.available = available
        self.unavailable_reason = unavailable_reason
        self.handler = handler
        self.calls: list[dict] = []

    def is_available(self):
        return self.available, self.unavailable_reason

    def run_tests(
        self,
        workdir: Path,
        spec: ContainerExecutionSpec,
        max_output_bytes: int,
    ) -> ContainerRunResult:
        file_snapshot = {
            p.relative_to(workdir).as_posix(): p.read_text(encoding="utf-8", errors="replace")
            for p in sorted(workdir.rglob("*"))
            if p.is_file()
        }
        self.calls.append(
            {
                "workdir": workdir,
                "spec": spec,
                "max_output_bytes": max_output_bytes,
                "files": file_snapshot,
            }
        )
        if self.handler is not None:
            return self.handler(workdir, spec, max_output_bytes, file_snapshot)
        return ContainerRunResult(
            exit_code=0,
            stdout="tests/test_app.py::test_ok PASSED\n=== 1 passed in 0.05s ===\n",
            stderr="",
            duration_ms=42,
            timed_out=False,
            output_truncated=False,
            container_available=True,
        )


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
def make_step7_client(workspace):
    def _make(runner=None, **overrides):
        test_settings = replace(
            default_settings,
            workspace_dir=workspace,
            llm_api_key=overrides.pop("llm_api_key", "test-placeholder-key"),
            **overrides,
        )
        app.dependency_overrides[get_settings] = lambda: test_settings
        if runner is not None:
            app.dependency_overrides[get_container_runner] = lambda: runner
        else:
            app.dependency_overrides.pop(get_container_runner, None)
        return TestClient(app)

    yield _make
    app.dependency_overrides.clear()


_BUGGY_PY = "def run(cmd):\n    return eval(cmd)\n"
_FIXED_PY = "import ast\n\ndef run(cmd):\n    return ast.literal_eval(cmd)\n"
_TEST_PY = "from app import run\n\ndef test_run():\n    assert run('1') == 1\n"


def _setup_patch_lifecycle(
    make_step7_client,
    make_zip,
    workspace,
    archive_files: dict[str, str],
    rel_path: str = "app.py",
    old_code: str = _BUGGY_PY,
    new_code: str = _FIXED_PY,
    *,
    approve: bool = True,
    apply: bool = True,
    runner=None,
    **settings_overrides,
):
    client = make_step7_client(runner=runner, **settings_overrides)
    up = upload(client, make_zip(archive_files))
    assert up.status_code == 201
    pid = up.json()["project_id"]

    scan_resp = client.post(f"/api/projects/{pid}/scan")
    assert scan_resp.status_code == 200
    findings = scan_resp.json()["findings"]
    assert findings, "Expected at least one finding in test fixture"
    finding = next(f for f in findings if f["file_path"] == rel_path)

    analysis_json = json.dumps(
        {
            "analyses": [
                {
                    "finding_id": f["id"],
                    "root_cause": f"Rule {f['rule_id']} triggered on {f['file_path']}.",
                    "technical_explanation": "Unsafe dynamic evaluation detected.",
                    "affected_component": f"{f['file_path']}:L{f['line_number']}",
                    "impact": "Arbitrary code execution risk.",
                    "recommended_fix": "Use ast.literal_eval instead of eval.",
                    "evidence": [f.get("evidence", "")],
                    "assumptions_or_uncertainties": [],
                    "related_finding_ids": [],
                    "relationship_explanation": None,
                    "confidence": "HIGH",
                    "confidence_reason": "Verified from workspace file.",
                    "analysis_status": "completed",
                }
                for f in findings
            ],
            "shared_root_cause_groups": [],
            "limitations": [],
        }
    )

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
                    "summary": "Replace unsafe eval with safe ast.literal_eval.",
                    "explanation": "Eliminates arbitrary code execution.",
                    "confidence": "HIGH",
                    "assumptions_or_uncertainties": [],
                }
            ],
            "limitations": [],
        }
    )
    app.dependency_overrides[get_llm_provider] = lambda: _StubProvider(lambda *_: patch_json)
    gen_resp = client.post(
        f"/api/projects/{pid}/patches/generate",
        json={"finding_id": finding["id"]},
    )
    assert gen_resp.status_code == 200
    patch_id = gen_resp.json()["patches"][0]["patch_id"]

    if approve:
        app_resp = client.post(
            f"/api/projects/{pid}/patches/{patch_id}/approve",
            json={"comment": "Reviewed for Step 7 validation."},
        )
        assert app_resp.status_code == 200

    if apply:
        apply_resp = client.post(f"/api/projects/{pid}/patches/{patch_id}/apply")
        assert apply_resp.status_code == 200

    return client, pid, patch_id


def test_validate_applied_patch_passes_with_baseline_fix_and_persists(
    make_step7_client, make_zip, workspace
):
    def _runner_handler(workdir: Path, spec: ContainerExecutionSpec, max_bytes: int, files: dict):
        # Patched snapshot contains ast.literal_eval; baseline snapshot still has eval().
        if "ast.literal_eval" in files["app.py"]:
            return ContainerRunResult(
                exit_code=0,
                stdout=(
                    "tests/test_app.py::test_run PASSED [ 50%]\n"
                    "tests/test_app.py::test_safe PASSED [100%]\n"
                    "=== 2 passed in 0.08s ===\n"
                ),
                stderr="",
                duration_ms=80,
                container_available=True,
            )
        return ContainerRunResult(
            exit_code=1,
            stdout=(
                "tests/test_app.py::test_run PASSED [ 50%]\n"
                "tests/test_app.py::test_safe FAILED [100%]\n"
                "FAILED tests/test_app.py::test_safe - AssertionError: unsafe eval\n"
                "=== 1 failed, 1 passed in 0.09s ===\n"
            ),
            stderr="",
            duration_ms=90,
            container_available=True,
        )

    runner = _RecordingContainerRunner(handler=_runner_handler)
    client, pid, patch_id = _setup_patch_lifecycle(
        make_step7_client,
        make_zip,
        workspace,
        {
            "proj/app.py": _BUGGY_PY,
            "proj/tests/test_app.py": _TEST_PY,
            "proj/pytest.ini": "[pytest]\n",
        },
        runner=runner,
    )

    resp = client.post(f"/api/projects/{pid}/patches/{patch_id}/validate")
    assert resp.status_code == 200
    body = resp.json()

    assert body["validation_id"].startswith("val-")
    assert body["project_id"] == pid
    assert body["patch_id"] == patch_id
    assert body["status"] == "PASSED"
    assert body["test_framework"] == "pytest"
    assert body["exit_code"] == 0
    assert body["total_tests"] == 2
    assert body["passed_tests"] == 2
    assert body["failed_tests"] == 0
    assert body["skipped_tests"] == 0
    assert body["container_available"] is True
    assert body["execution_spec"]["network_disabled"] is True
    assert body["execution_spec"]["read_only_root"] is True
    assert body["execution_spec"]["capabilities_dropped"] == ["ALL"]
    assert body["execution_spec"]["no_new_privileges"] is True

    reg = body["regression_comparison"]
    assert reg["baseline_available"] is True
    assert reg["regression_detected"] is False
    assert reg["tests_passed_before_and_after"] == ["tests/test_app.py::test_run"]
    assert reg["tests_fixed"] == ["tests/test_app.py::test_safe"]
    assert reg["tests_regressed"] == []

    # Verify runner ran on isolated temp copies, never inside backend workspace `source/`.
    assert len(runner.calls) == 2
    source_root = workspace / pid / "source"
    for call in runner.calls:
        assert not str(call["workdir"]).startswith(str(source_root))
        assert not call["workdir"].exists()  # cleaned up after validation!

    # Verify retrieval endpoints
    hist = client.get(f"/api/projects/{pid}/patches/{patch_id}/validations")
    assert hist.status_code == 200
    assert hist.json()["total_runs"] == 1
    assert hist.json()["passed_count"] == 1

    proj_hist = client.get(f"/api/projects/{pid}/validations")
    assert proj_hist.status_code == 200
    assert proj_hist.json()["total_runs"] == 1

    single = client.get(f"/api/projects/{pid}/validations/{body['validation_id']}")
    assert single.status_code == 200
    assert single.json()["validation_id"] == body["validation_id"]


def test_validate_detects_regression_and_marks_failed(
    make_step7_client, make_zip, workspace
):
    def _runner_handler(workdir: Path, spec, max_bytes, files: dict):
        if "ast.literal_eval" in files["app.py"]:
            return ContainerRunResult(
                exit_code=1,
                stdout=(
                    "tests/test_app.py::test_run FAILED\n"
                    "tests/test_app.py::test_other PASSED\n"
                    "FAILED tests/test_app.py::test_run - AssertionError: broken return\n"
                    "=== 1 failed, 1 passed in 0.05s ===\n"
                ),
                stderr="",
                duration_ms=50,
            )
        return ContainerRunResult(
            exit_code=0,
            stdout=(
                "tests/test_app.py::test_run PASSED\n"
                "tests/test_app.py::test_other PASSED\n"
                "=== 2 passed in 0.05s ===\n"
            ),
            stderr="",
            duration_ms=50,
        )

    runner = _RecordingContainerRunner(handler=_runner_handler)
    client, pid, patch_id = _setup_patch_lifecycle(
        make_step7_client,
        make_zip,
        workspace,
        {"proj/app.py": _BUGGY_PY, "proj/tests/test_app.py": _TEST_PY},
        runner=runner,
    )

    resp = client.post(f"/api/projects/{pid}/patches/{patch_id}/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "FAILED"
    assert body["failed_tests"] == 1
    reg = body["regression_comparison"]
    assert reg["regression_detected"] is True
    assert reg["tests_regressed"] == ["tests/test_app.py::test_run"]
    assert reg["newly_introduced_failures"] == ["tests/test_app.py::test_run"]


def test_validate_rejects_unapplied_patches_with_409(
    make_step7_client, make_zip, workspace
):
    runner = _RecordingContainerRunner()
    # Generated but not approved or applied
    client, pid, patch_id = _setup_patch_lifecycle(
        make_step7_client,
        make_zip,
        workspace,
        {"proj/app.py": _BUGGY_PY, "proj/tests/test_app.py": _TEST_PY},
        approve=False,
        apply=False,
        runner=runner,
    )

    r1 = client.post(f"/api/projects/{pid}/patches/{patch_id}/validate")
    assert r1.status_code == 409

    # Approved but not applied
    client.post(f"/api/projects/{pid}/patches/{patch_id}/approve")
    r2 = client.post(f"/api/projects/{pid}/patches/{patch_id}/validate")
    assert r2.status_code == 409

    # Rejected patch cannot be validated either
    client.post(f"/api/projects/{pid}/patches/{patch_id}/reject")
    r3 = client.post(f"/api/projects/{pid}/patches/{patch_id}/validate")
    assert r3.status_code == 409
    assert runner.calls == []


def test_validate_returns_blocked_when_container_unavailable_and_never_runs_on_host(
    make_step7_client, make_zip, workspace
):
    runner = _RecordingContainerRunner(
        available=False,
        unavailable_reason="Docker daemon is not running; host execution is disabled.",
    )
    client, pid, patch_id = _setup_patch_lifecycle(
        make_step7_client,
        make_zip,
        workspace,
        {"proj/app.py": _BUGGY_PY, "proj/tests/test_app.py": _TEST_PY},
        runner=runner,
    )

    resp = client.post(f"/api/projects/{pid}/patches/{patch_id}/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "BLOCKED"
    assert body["container_available"] is False
    assert "host execution is disabled" in body["failure_details"][0].lower()
    assert runner.calls == []


def test_validate_timeout_returns_timed_out_status(
    make_step7_client, make_zip, workspace
):
    runner = _RecordingContainerRunner(
        handler=lambda *args: ContainerRunResult(
            exit_code=None,
            stdout="collecting ...\n",
            stderr="",
            duration_ms=2000,
            timed_out=True,
            container_available=True,
            error_message="Test execution exceeded timeout and the container was terminated.",
        )
    )
    client, pid, patch_id = _setup_patch_lifecycle(
        make_step7_client,
        make_zip,
        workspace,
        {"proj/app.py": _BUGGY_PY, "proj/tests/test_app.py": _TEST_PY},
        runner=runner,
    )

    resp = client.post(
        f"/api/projects/{pid}/patches/{patch_id}/validate",
        json={"run_regression": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "TIMED_OUT"
    assert body["timed_out"] is True
    assert body["exit_code"] is None


def test_validate_blocks_when_no_tests_exist(make_step7_client, make_zip, workspace):
    runner = _RecordingContainerRunner()
    client, pid, patch_id = _setup_patch_lifecycle(
        make_step7_client,
        make_zip,
        workspace,
        {"proj/app.py": _BUGGY_PY},
        runner=runner,
    )

    resp = client.post(f"/api/projects/{pid}/patches/{patch_id}/validate")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "BLOCKED"
    assert body["test_framework"] == "none"
    assert runner.calls == []


def test_validate_rejects_unsafe_test_command_overrides_with_422(
    make_step7_client, make_zip, workspace
):
    runner = _RecordingContainerRunner()
    client, pid, patch_id = _setup_patch_lifecycle(
        make_step7_client,
        make_zip,
        workspace,
        {"proj/app.py": _BUGGY_PY, "proj/tests/test_app.py": _TEST_PY},
        runner=runner,
    )

    unsafe_commands = [
        "",
        "pytest; rm -rf /",
        "pytest && cat /etc/passwd",
        "sh -c 'pytest'",
        "python -c 'import os; os.system(\"id\")'",
        "python -m pip install evil",
        "node -e 'process.exit(1)'",
        "pytest ../../outside",
        "pytest --rootdir=/etc",
        "curl http://attacker.example",
    ]
    for bad_cmd in unsafe_commands:
        resp = client.post(
            f"/api/projects/{pid}/patches/{patch_id}/validate",
            json={"test_command": bad_cmd},
        )
        assert resp.status_code == 422, f"Expected 422 for unsafe command: {bad_cmd}"

    # Valid allowlisted override executes cleanly
    ok = client.post(
        f"/api/projects/{pid}/patches/{patch_id}/validate",
        json={"test_command": "pytest -k test_run", "run_regression": False},
    )
    assert ok.status_code == 200
    assert ok.json()["command_source"] == "override"
    assert ok.json()["test_framework"] == "pytest"
    assert "-k" in ok.json()["test_command"]


def test_test_framework_detection_unittest_node_and_unsupported(tmp_path):
    s = default_settings

    # Unittest detection
    uni_dir = tmp_path / "uni"
    (uni_dir / "tests").mkdir(parents=True)
    (uni_dir / "tests" / "test_calc.py").write_text(
        "import unittest\nclass T(unittest.TestCase):\n    def test_x(self): pass\n",
        encoding="utf-8",
    )
    res_uni = detect_test_configuration(uni_dir, s)
    assert res_uni.detected is True
    assert res_uni.framework == "unittest"
    assert res_uni.command[:3] == ["python", "-m", "unittest"]

    # Node vitest detection
    vitest_dir = tmp_path / "vitest_proj"
    vitest_dir.mkdir()
    (vitest_dir / "package.json").write_text(
        json.dumps({"name": "demo", "scripts": {"test": "vitest run"}}),
        encoding="utf-8",
    )
    res_vitest = detect_test_configuration(vitest_dir, s)
    assert res_vitest.detected is True
    assert res_vitest.framework == "vitest"
    assert res_vitest.container_image == s.validation_node_image

    # Node placeholder script rejected safely
    placeholder_dir = tmp_path / "placeholder"
    placeholder_dir.mkdir()
    (placeholder_dir / "package.json").write_text(
        json.dumps(
            {
                "name": "demo",
                "scripts": {"test": 'echo "Error: no test specified" && exit 1'},
            }
        ),
        encoding="utf-8",
    )
    res_placeholder = detect_test_configuration(placeholder_dir, s)
    assert res_placeholder.detected is False
    assert res_placeholder.framework == "none"

    # Unsupported Go project
    go_dir = tmp_path / "go_proj"
    go_dir.mkdir()
    (go_dir / "go.mod").write_text("module example.com/demo\n", encoding="utf-8")
    (go_dir / "main_test.go").write_text("package main\n", encoding="utf-8")
    res_go = detect_test_configuration(go_dir, s)
    assert res_go.detected is False
    assert res_go.framework == "unsupported"


def test_docker_container_runner_security_flags_timeout_and_missing_binary(tmp_path):
    runner = DockerContainerRunner(docker_binary="/usr/bin/docker")
    spec = ContainerExecutionSpec(
        image="python:3.11-slim",
        command=["python", "-m", "pytest", "-v"],
        timeout_seconds=15,
        memory_limit="256m",
        cpus="0.5",
        pids_limit=32,
        network_disabled=True,
        read_only_root=True,
        non_root_user="65534:65534",
        capabilities_dropped=["ALL"],
        no_new_privileges=True,
    )
    args = runner.build_docker_run_args(tmp_path, spec, "rootpatch-val-test123")
    assert "--rm" in args
    assert "--init" in args
    assert "--network" in args and "none" in args
    assert "--cap-drop" in args and "ALL" in args
    assert "--security-opt" in args and "no-new-privileges:true" in args
    assert "--read-only" in args
    assert "--memory" in args and "256m" in args
    assert "--cpus" in args and "0.5" in args
    assert "--pids-limit" in args and "32" in args
    assert "--user" in args and "65534:65534" in args
    assert f"{tmp_path.resolve()}:/workspace:rw" in args

    # Never pass host secrets to subprocess env
    with patch("shutil.which", return_value=None):
        no_bin_runner = DockerContainerRunner()
        avail, msg = no_bin_runner.is_available()
        assert avail is False
        assert "host execution is disabled" in msg.lower()
        res = no_bin_runner.run_tests(tmp_path, spec, 4096)
        assert res.container_available is False

    # Timeout cleans up container with `docker rm -f`
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[1] == "info":
            return subprocess.CompletedProcess(cmd, 0, stdout=b"24.0.0\n", stderr=b"")
        if cmd[1] == "run":
            assert kwargs.get("shell") is False
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=15, output=b"partial out", stderr=b"")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    with patch("app.services.container_runner.subprocess.run", side_effect=_fake_run):
        res_to = runner.run_tests(tmp_path, spec, 4096)
        assert res_to.timed_out is True
        assert res_to.exit_code is None
        assert "partial out" in res_to.stdout
        assert any(c[0][1] == "rm" and "-f" in c[0] for c in calls)


def test_source_files_preserved_and_output_bounded_redacted_with_history(
    make_step7_client, make_zip, workspace
):
    huge_out = ("tests/test_app.py::test_run PASSED\n" + ("A" * 5000) + "\n") * 5
    secret_err = "Bearer sk-secret-token-1234567890 leaked\n"

    runner = _RecordingContainerRunner(
        handler=lambda *args: ContainerRunResult(
            exit_code=0,
            stdout=huge_out,
            stderr=secret_err,
            duration_ms=30,
        )
    )
    client, pid, patch_id = _setup_patch_lifecycle(
        make_step7_client,
        make_zip,
        workspace,
        {"proj/app.py": _BUGGY_PY, "proj/tests/test_app.py": _TEST_PY},
        runner=runner,
    )

    target_file = workspace / pid / "source" / "proj" / "app.py"
    archive_file = workspace / pid / "original" / "upload.zip"
    before_source_sha = hashlib.sha256(target_file.read_bytes()).hexdigest()
    before_zip_sha = hashlib.sha256(archive_file.read_bytes()).hexdigest()

    r1 = client.post(
        f"/api/projects/{pid}/patches/{patch_id}/validate",
        json={"run_regression": False},
    )
    assert r1.status_code == 200
    r2 = client.post(
        f"/api/projects/{pid}/patches/{patch_id}/validate",
        json={"run_regression": False},
    )
    assert r2.status_code == 200

    assert hashlib.sha256(target_file.read_bytes()).hexdigest() == before_source_sha
    assert hashlib.sha256(archive_file.read_bytes()).hexdigest() == before_zip_sha
    assert "sk-secret-token" not in r1.json()["stderr"]

    hist = client.get(f"/api/projects/{pid}/patches/{patch_id}/validations")
    assert hist.status_code == 200
    assert hist.json()["total_runs"] == 2
    assert r1.json()["validation_id"] != r2.json()["validation_id"]

    # Unknown validation_id and unknown project return 404
    assert client.get(f"/api/projects/{pid}/validations/val-000000000000").status_code == 404
    assert client.get(f"/api/projects/{'a' * 32}/validations").status_code == 404


def test_validate_command_override_accepts_pytest_markers():
    res = validate_test_command_override("pytest -m unit -k math", default_settings)
    assert res.detected is True
    assert res.framework == "pytest"
    assert "-m" in res.command and "unit" in res.command
    assert "cache_dir=/tmp/.pytest_cache" in res.command


def test_step7_helper_classes_excluded_from_pytest_collection():
    from app.core.errors import TestValidationError
    from app.schemas.validation import TestDetectionResult

    assert getattr(TestValidationError, "__test__", True) is False
    assert getattr(TestDetectionResult, "__test__", True) is False
    assert "__test__" not in TestDetectionResult.model_fields
