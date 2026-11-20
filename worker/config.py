"""Configuration for the RootPatch local Windows Docker validation worker."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class WorkerConfig:
    backend_url: str
    worker_token: str
    worker_id: str
    docker_binary: str
    poll_interval_seconds: int
    heartbeat_interval_seconds: int
    lease_seconds: int
    max_result_bytes: int
    temp_dir: Path


def load_config() -> WorkerConfig:
    backend_url = os.getenv("ROOTPATCH_BACKEND_URL", "").strip().rstrip("/")
    worker_token = os.getenv("ROOTPATCH_WORKER_TOKEN", "").strip()
    worker_id = os.getenv("ROOTPATCH_WORKER_ID", "").strip() or "windows-worker-1"
    docker_binary = os.getenv("ROOTPATCH_DOCKER_BINARY", "docker").strip() or "docker"
    poll_interval_seconds = int(os.getenv("ROOTPATCH_POLL_INTERVAL_SECONDS", "5"))
    heartbeat_interval_seconds = int(os.getenv("ROOTPATCH_HEARTBEAT_INTERVAL_SECONDS", "10"))
    lease_seconds = int(os.getenv("ROOTPATCH_JOB_LEASE_SECONDS", "120"))
    max_result_bytes = int(os.getenv("ROOTPATCH_MAX_RESULT_BYTES", "65536"))
    temp_dir = Path(os.getenv("ROOTPATCH_TEMP_DIR", "")).expanduser() if os.getenv("ROOTPATCH_TEMP_DIR") else Path(tempfile.gettempdir()) / "rootpatch-worker"

    if not backend_url:
        raise ValueError("ROOTPATCH_BACKEND_URL is required.")
    if not worker_token:
        raise ValueError("ROOTPATCH_WORKER_TOKEN is required.")

    parsed = urlparse(backend_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("ROOTPATCH_BACKEND_URL must use http or https.")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("ROOTPATCH_BACKEND_URL must use HTTPS outside localhost.")

    if poll_interval_seconds < 1:
        raise ValueError("ROOTPATCH_POLL_INTERVAL_SECONDS must be at least 1.")
    if heartbeat_interval_seconds < 1:
        raise ValueError("ROOTPATCH_HEARTBEAT_INTERVAL_SECONDS must be at least 1.")
    if lease_seconds < 30:
        raise ValueError("ROOTPATCH_JOB_LEASE_SECONDS must be at least 30.")
    if max_result_bytes < 1024:
        raise ValueError("ROOTPATCH_MAX_RESULT_BYTES must be at least 1024.")

    return WorkerConfig(
        backend_url=backend_url,
        worker_token=worker_token,
        worker_id=worker_id,
        docker_binary=docker_binary,
        poll_interval_seconds=poll_interval_seconds,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        lease_seconds=lease_seconds,
        max_result_bytes=max_result_bytes,
        temp_dir=temp_dir,
    )
