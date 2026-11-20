"""Safe snapshot extraction and restricted Docker execution for the worker."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

MAX_SNAPSHOT_FILES = 10000
MAX_SNAPSHOT_BYTES = 500 * 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_extract_zip(data: bytes, destination: Path) -> Path:
    """Extract a ZIP archive safely, rejecting traversal and symlinks."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if len(members) > MAX_SNAPSHOT_FILES:
            raise ValueError("Snapshot contains too many files.")

        total_size = sum(member.file_size for member in members)
        if total_size > MAX_SNAPSHOT_BYTES:
            raise ValueError("Snapshot is too large.")

        for member in members:
            if member.is_dir():
                continue
            target = destination / member.filename
            resolved_target = target.resolve()
            if not resolved_target.is_relative_to(destination):
                raise ValueError(f"Unsafe snapshot path: {member.filename}")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f"Symlink in snapshot is not allowed: {member.filename}")

        extracted_bytes = 0
        for member in members:
            if member.is_dir():
                continue
            target = destination / member.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, target.open("wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    extracted_bytes += len(chunk)
                    if extracted_bytes > MAX_SNAPSHOT_BYTES:
                        raise ValueError("Snapshot extraction exceeded size limit.")
                    output.write(chunk)

    return destination


def find_project_root(extracted_dir: Path) -> Path:
    candidates = [p for p in extracted_dir.iterdir()] if extracted_dir.is_dir() else []
    dirs = [p for p in candidates if p.is_dir()]
    if len(dirs) == 1 and not (extracted_dir / "package.json").is_file() and not (extracted_dir / "pyproject.toml").is_file():
        return dirs[0]
    return extracted_dir


def build_docker_command(docker_binary: str, spec: Dict[str, Any], snapshot_dir: Path, container_name: str) -> list[str]:
    image = spec.get("image")
    command = spec.get("command")
    if not isinstance(image, str) or not image:
        raise ValueError("Invalid container image in job.")
    if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
        raise ValueError("Invalid container command in job.")

    allowed_images = {
        "rootpatch-python-validate:latest",
        "python:3.11-slim",
        "node:20-slim",
    }
    if image not in allowed_images:
        raise ValueError(f"Container image is not allowlisted: {image}")

    args = [
        docker_binary,
        "run",
        "--rm",
        "--init",
        "--name",
        container_name,
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
    ]

    memory_limit = spec.get("memory_limit", "512m")
    cpus = spec.get("cpus", "1.0")
    pids_limit = spec.get("pids_limit", 64)
    args.extend(["--memory", str(memory_limit)])
    args.extend(["--cpus", str(cpus)])
    args.extend(["--pids-limit", str(pids_limit)])
    args.extend(["--user", str(spec.get("non_root_user", "65534:65534"))])

    args.extend([
        "-e", "HOME=/tmp",
        "-e", "PYTHONDONTWRITEBYTECODE=1",
        "-e", "PYTHONNOUSERSITE=1",
        "-e", "CI=true",
        "-e", "TERM=dumb",
        "-v", f"{str(snapshot_dir.resolve())}:/workspace:rw",
        "-w", "/workspace",
        image,
        *command,
    ])
    return args


def run_docker_validation(
    docker_binary: str,
    spec: Dict[str, Any],
    snapshot_dir: Path,
    timeout_seconds: int,
    max_output_bytes: int,
    cancel_event=None,
) -> Tuple[dict, bool]:
    container_name = f"rootpatch-worker-{os.urandom(6).hex()}"
    args = build_docker_command(docker_binary, spec, snapshot_dir, container_name)

    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env={"PATH": os.environ.get("PATH", "")},
        )
    except FileNotFoundError:
        return {
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "duration_ms": 0,
            "timed_out": False,
            "output_truncated": False,
            "container_available": False,
            "error_message": "Docker CLI is unavailable; host execution is disabled.",
        }, False
    except OSError as exc:
        return {
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "duration_ms": 0,
            "timed_out": False,
            "output_truncated": False,
            "container_available": True,
            "error_message": f"Container execution failed to start: {exc}",
        }, False

    cancelled = False
    timed_out = False
    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            proc.kill()
            break
        if time.monotonic() - start > timeout_seconds:
            timed_out = True
            proc.kill()
            break
        time.sleep(0.5)

    try:
        stdout_raw, stderr_raw = proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout_raw, stderr_raw = proc.communicate()

    elapsed_ms = int((time.monotonic() - start) * 1000)

    if cancelled:
        return {
            "exit_code": None,
            "stdout": (stdout_raw or b"").decode("utf-8", errors="replace")[:max_output_bytes],
            "stderr": (stderr_raw or b"").decode("utf-8", errors="replace")[:max_output_bytes],
            "duration_ms": elapsed_ms,
            "timed_out": False,
            "output_truncated": False,
            "container_available": True,
            "error_message": "Validation was cancelled because the worker lost its lease.",
        }, False

    if timed_out:
        return {
            "exit_code": None,
            "stdout": (stdout_raw or b"").decode("utf-8", errors="replace")[:max_output_bytes],
            "stderr": (stderr_raw or b"").decode("utf-8", errors="replace")[:max_output_bytes],
            "duration_ms": elapsed_ms,
            "timed_out": True,
            "output_truncated": False,
            "container_available": True,
            "error_message": f"Test execution exceeded the {timeout_seconds}s timeout.",
        }, False

    stdout = (stdout_raw or b"").decode("utf-8", errors="replace")
    stderr = (stderr_raw or b"").decode("utf-8", errors="replace")
    stdout_truncated = len(stdout.encode("utf-8")) > max_output_bytes
    stderr_truncated = len(stderr.encode("utf-8")) > max_output_bytes
    if stdout_truncated:
        stdout = stdout.encode("utf-8")[:max_output_bytes].decode("utf-8", errors="replace")
    if stderr_truncated:
        stderr = stderr.encode("utf-8")[:max_output_bytes].decode("utf-8", errors="replace")

    return {
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "duration_ms": elapsed_ms,
        "timed_out": False,
        "output_truncated": stdout_truncated or stderr_truncated,
        "container_available": True,
        "error_message": None,
    }, False
