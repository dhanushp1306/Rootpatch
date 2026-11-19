"""Isolated Docker container test execution runner (Step 7).

SECURITY INVARIANT:
Uploaded project code and test suites MUST NEVER execute directly on the host.
All execution goes through `ContainerRunner` (`DockerContainerRunner` in production).
If Docker / container isolation is unavailable, execution fails safely and reports
that container isolation is unavailable rather than falling back to host execution.
"""

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple

from app.schemas.validation import ContainerExecutionSpec, ContainerRunResult

_SAFE_HOST_ENV_KEYS = (
    "PATH",
    "HOME",
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
    "DOCKER_API_VERSION",
    "SystemRoot",
)


def _sanitized_host_docker_env() -> Dict[str, str]:
    """Minimal environment for invoking the Docker CLI without passing app/LLM secrets."""
    env: Dict[str, str] = {}
    for key in _SAFE_HOST_ENV_KEYS:
        val = os.environ.get(key)
        if val:
            env[key] = val
    if "PATH" not in env:
        env["PATH"] = os.defpath
    return env


def _truncate_bytes_to_text(raw: bytes | str | None, max_bytes: int) -> Tuple[str, bool]:
    if raw is None:
        return "", False
    data = raw.encode("utf-8", errors="replace") if isinstance(raw, str) else raw
    if len(data) <= max_bytes:
        return data.decode("utf-8", errors="replace"), False
    clipped = data[:max_bytes].decode("utf-8", errors="replace")
    return clipped + "\n... [output truncated due to size limit]", True


class ContainerRunner(Protocol):
    """Abstraction over isolated container execution; mocked in unit/integration tests."""

    def is_available(self) -> Tuple[bool, Optional[str]]:
        ...

    def run_tests(
        self,
        workdir: Path,
        spec: ContainerExecutionSpec,
        max_output_bytes: int,
    ) -> ContainerRunResult:
        ...


class DockerContainerRunner:
    """Executes tests inside a hardened, network-disabled, non-root Docker container."""

    def __init__(self, docker_binary: Optional[str] = None) -> None:
        self._docker_binary = docker_binary

    def _resolve_docker_binary(self) -> Optional[str]:
        if self._docker_binary:
            return self._docker_binary
        return shutil.which("docker")

    def is_available(self) -> Tuple[bool, Optional[str]]:
        docker_bin = self._resolve_docker_binary()
        if not docker_bin:
            return (
                False,
                "Docker CLI is not installed or not on PATH; host execution is disabled.",
            )
        try:
            proc = subprocess.run(
                [docker_bin, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                timeout=5,
                shell=False,
                env=_sanitized_host_docker_env(),
            )
        except subprocess.TimeoutExpired:
            return (
                False,
                "Docker daemon health check timed out; host execution is disabled.",
            )
        except OSError as exc:
            return (
                False,
                f"Docker daemon cannot be reached ({exc}); host execution is disabled.",
            )

        if proc.returncode != 0:
            return (
                False,
                "Docker daemon is not running or inaccessible; host execution is disabled.",
            )
        return True, None

    def build_docker_run_args(
        self,
        workdir: Path,
        spec: ContainerExecutionSpec,
        container_name: str,
    ) -> List[str]:
        """Build the strict hardened `docker run` argument vector (never uses shell=True)."""
        docker_bin = self._resolve_docker_binary() or "docker"
        resolved_workdir = str(workdir.resolve())

        args: List[str] = [
            docker_bin,
            "run",
            "--rm",
            "--init",
            "--name",
            container_name,
        ]
        if spec.network_disabled:
            args.extend(["--network", "none"])
        for cap in spec.capabilities_dropped:
            args.extend(["--cap-drop", cap])
        if spec.no_new_privileges:
            args.extend(["--security-opt", "no-new-privileges:true"])
        if spec.read_only_root:
            args.append("--read-only")
            args.extend(["--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"])

        args.extend(["--memory", spec.memory_limit])
        args.extend(["--cpus", spec.cpus])
        args.extend(["--pids-limit", str(spec.pids_limit)])
        args.extend(["--user", spec.non_root_user])

        # Clean container environment with zero host environment leakage.
        args.extend(
            [
                "-e",
                "HOME=/tmp",
                "-e",
                "PYTHONDONTWRITEBYTECODE=1",
                "-e",
                "PYTHONNOUSERSITE=1",
                "-e",
                "CI=true",
                "-e",
                "TERM=dumb",
            ]
        )

        # Mount ONLY the disposable temporary project copy into /workspace.
        args.extend(["-v", f"{resolved_workdir}:/workspace:rw"])
        args.extend(["-w", "/workspace"])
        args.append(spec.image)
        args.extend(spec.command)
        return args

    def _force_remove_container(self, docker_bin: str, container_name: str) -> None:
        try:
            subprocess.run(
                [docker_bin, "rm", "-f", container_name],
                capture_output=True,
                timeout=5,
                shell=False,
                env=_sanitized_host_docker_env(),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def run_tests(
        self,
        workdir: Path,
        spec: ContainerExecutionSpec,
        max_output_bytes: int,
    ) -> ContainerRunResult:
        available, reason = self.is_available()
        if not available:
            return ContainerRunResult(
                exit_code=None,
                stdout="",
                stderr="",
                duration_ms=0,
                timed_out=False,
                output_truncated=False,
                container_available=False,
                error_message=reason
                or "Isolated container execution is unavailable; host execution is disabled.",
            )

        docker_bin = self._resolve_docker_binary() or "docker"
        container_name = f"rootpatch-val-{uuid.uuid4().hex[:12]}"
        argv = self.build_docker_run_args(workdir, spec, container_name)

        start = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                timeout=spec.timeout_seconds,
                shell=False,
                env=_sanitized_host_docker_env(),
            )
        except subprocess.TimeoutExpired as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            self._force_remove_container(docker_bin, container_name)
            stdout_text, trunc_out = _truncate_bytes_to_text(exc.stdout, max_output_bytes)
            stderr_text, trunc_err = _truncate_bytes_to_text(exc.stderr, max_output_bytes)
            return ContainerRunResult(
                exit_code=None,
                stdout=stdout_text,
                stderr=stderr_text,
                duration_ms=elapsed_ms,
                timed_out=True,
                output_truncated=trunc_out or trunc_err,
                container_available=True,
                error_message=f"Test execution exceeded the {spec.timeout_seconds}s timeout and the container was terminated.",
            )
        except FileNotFoundError:
            return ContainerRunResult(
                exit_code=None,
                duration_ms=0,
                container_available=False,
                error_message="Docker CLI is unavailable; host execution is disabled.",
            )
        except OSError as exc:
            self._force_remove_container(docker_bin, container_name)
            return ContainerRunResult(
                exit_code=None,
                duration_ms=int((time.monotonic() - start) * 1000),
                container_available=True,
                error_message=f"Container execution failed to start: {exc}",
            )

        elapsed_ms = int((time.monotonic() - start) * 1000)
        stdout_text, trunc_out = _truncate_bytes_to_text(proc.stdout, max_output_bytes)
        stderr_text, trunc_err = _truncate_bytes_to_text(proc.stderr, max_output_bytes)

        return ContainerRunResult(
            exit_code=proc.returncode,
            stdout=stdout_text,
            stderr=stderr_text,
            duration_ms=elapsed_ms,
            timed_out=False,
            output_truncated=trunc_out or trunc_err,
            container_available=True,
            error_message=None,
        )


def get_container_runner() -> ContainerRunner:
    """FastAPI dependency; tests override this to inject an isolated mock runner."""
    return DockerContainerRunner()
