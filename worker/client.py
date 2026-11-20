"""HTTPS client for the RootPatch remote validation worker."""

from __future__ import annotations

import httpx

from worker.config import WorkerConfig


class WorkerClient:
    def __init__(self, config: WorkerConfig) -> None:
        self.config = config
        self._client = httpx.Client(
            base_url=config.backend_url,
            headers={"Authorization": f"Bearer {config.worker_token}"},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    def close(self) -> None:
        self._client.close()

    def claim_job(self):
        response = self._client.post(
            "/api/worker/validation-jobs/claim",
            headers={"X-Worker-ID": self.config.worker_id},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def heartbeat(self, job_id: str, lease_seconds: int) -> bool:
        response = self._client.post(
            f"/api/worker/validation-jobs/{job_id}/heartbeat",
            json={"lease_seconds": lease_seconds},
            headers={"X-Worker-ID": self.config.worker_id},
        )
        if response.status_code in {404, 409}:
            return False
        response.raise_for_status()
        return bool(response.json().get("renewed", False))

    def download_snapshot(self, job_id: str, kind: str = "patched") -> bytes:
        response = self._client.get(
            f"/api/worker/validation-jobs/{job_id}/snapshot",
            params={"kind": kind},
            headers={"X-Worker-ID": self.config.worker_id},
        )
        response.raise_for_status()
        return response.content

    def submit_result(self, job_id: str, payload: dict) -> dict:
        response = self._client.post(
            f"/api/worker/validation-jobs/{job_id}/result",
            json=payload,
            headers={"X-Worker-ID": self.config.worker_id},
        )
        if response.status_code == 409:
            return {"duplicate": True, "status_code": 409}
        response.raise_for_status()
        return response.json()
