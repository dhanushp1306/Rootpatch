"""RootPatch local Windows Docker validation worker."""

from __future__ import annotations

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import argparse
import logging
import os
import shutil
import signal
import tempfile
import threading
import time
from pathlib import Path

from worker.client import WorkerClient
from worker.config import load_config
from worker.runner import (
    find_project_root,
    run_docker_validation,
    safe_extract_zip,
    sha256_bytes,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rootpatch.worker")

_STOP = threading.Event()


def _handle_signal(signum, frame):
    logger.info("Received signal %s; stopping worker.", signum)
    _STOP.set()


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def process_job(client, config, job):
    job_id = job["job_id"]
    logger.info("Claimed validation job %s for project %s", job_id, job["project_id"])

    heartbeat_thread = None
    heartbeat_stop = threading.Event()
    cancel_event = threading.Event()

    def heartbeat_loop():
        while not heartbeat_stop.wait(config.heartbeat_interval_seconds):
            ok = client.heartbeat(job_id, config.lease_seconds)
            if not ok:
                logger.warning("Heartbeat failed for job %s; cancelling Docker execution.", job_id)
                cancel_event.set()
                break

    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()

    temp_root = Path(tempfile.mkdtemp(prefix="rootpatch-job-", dir=config.temp_dir))
    try:
        patched_data = client.download_snapshot(job_id, "patched")
        if sha256_bytes(patched_data) != job["snapshot_checksum"]:
            raise ValueError("Patched snapshot checksum mismatch.")

        patched_dir = temp_root / "patched"
        safe_extract_zip(patched_data, patched_dir)
        project_root = find_project_root(patched_dir)

        baseline_dir = None
        if job.get("baseline_available"):
            baseline_data = client.download_snapshot(job_id, "baseline")
            expected = job.get("baseline_checksum")
            if expected and sha256_bytes(baseline_data) != expected:
                raise ValueError("Baseline snapshot checksum mismatch.")
            baseline_dir = temp_root / "baseline"
            safe_extract_zip(baseline_data, baseline_dir)

        spec = job["execution_spec"]
        timeout_seconds = int(job.get("timeout_seconds") or spec.get("timeout_seconds", 60))
        max_output_bytes = 65536

        result, docker_unavailable = run_docker_validation(
            config.docker_binary,
            spec,
            project_root,
            timeout_seconds,
            max_output_bytes,
            cancel_event,
        )

        payload = {
            "worker_id": config.worker_id,
            "exit_code": result["exit_code"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "duration_ms": result["duration_ms"],
            "timed_out": result["timed_out"],
            "output_truncated": result["output_truncated"],
            "container_available": result["container_available"],
            "error_message": result["error_message"],
        }

        response = client.submit_result(job_id, payload)
        if isinstance(response, dict) and response.get("duplicate"):
            logger.info("Validation result for job %s was already submitted.", job_id)
        else:
            logger.info("Submitted validation result for job %s: %s", job_id, response.get("status"))

        if docker_unavailable:
            logger.error("Docker is unavailable; validation for job %s was blocked.", job_id)
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=5)
        shutil.rmtree(temp_root, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="RootPatch local Docker validation worker")
    parser.add_argument("--once", action="store_true", help="Process at most one job and exit.")
    args = parser.parse_args()

    config = load_config()
    config.temp_dir.mkdir(parents=True, exist_ok=True)
    client = WorkerClient(config)

    logger.info("RootPatch worker %s started. Backend: %s", config.worker_id, config.backend_url)

    try:
        while not _STOP.is_set():
            try:
                job = client.claim_job()
            except Exception as exc:
                logger.warning("Failed to poll backend: %s", exc)
                time.sleep(config.poll_interval_seconds)
                continue

            if job is None:
                time.sleep(config.poll_interval_seconds)
                continue

            try:
                process_job(client, config, job)
            except Exception as exc:
                logger.exception("Validation job %s failed: %s", job.get("job_id"), exc)
                try:
                    client.submit_result(
                        job["job_id"],
                        {
                            "worker_id": config.worker_id,
                            "exit_code": None,
                            "stdout": "",
                            "stderr": "",
                            "duration_ms": 0,
                            "timed_out": False,
                            "output_truncated": False,
                            "container_available": True,
                            "error_message": str(exc)[:4096],
                        },
                    )
                except Exception as submit_exc:
                    logger.warning("Failed to submit failure result: %s", submit_exc)

            if args.once:
                break
    finally:
        client.close()
        logger.info("RootPatch worker stopped.")


if __name__ == "__main__":
    main()
