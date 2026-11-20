"""Supabase Storage helper for RootPatch validation snapshots.

Stage 3 replaces the previous S3/R2 implementation with Supabase Storage.
The backend uses the service-role key server-side only. The frontend and worker
never receive Supabase credentials.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import quote

import httpx

from app.core.config import Settings


class ObjectStorage:
    """Thin wrapper around the Supabase Storage REST API."""

    def __init__(self, settings: Settings) -> None:
        self.supabase_url = (settings.supabase_url or "").rstrip("/")
        self.service_role_key = settings.supabase_service_role_key or ""
        self.bucket = settings.object_storage_bucket or ""

        if not self.supabase_url:
            raise RuntimeError("SUPABASE_URL is required for Supabase Storage.")
        if not self.service_role_key:
            raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is required for Supabase Storage.")
        if not self.bucket:
            raise RuntimeError("ROOTPATCH_OBJECT_STORAGE_BUCKET is required for Supabase Storage.")

    def _auth_headers(self, content_type: Optional[str] = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.service_role_key}",
            "apikey": self.service_role_key,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _object_url(self, key: str) -> str:
        if not key or ".." in key.split("/"):
            raise ValueError("Unsafe object key.")
        encoded_key = quote(key, safe="/")
        return f"{self.supabase_url}/storage/v1/object/{self.bucket}/{encoded_key}"

    def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/zip",
        if_none_match: bool = False,
    ) -> None:
        headers = self._auth_headers(content_type)
        if if_none_match:
            headers["x-upsert"] = "false"

        try:
            response = httpx.post(
                self._object_url(key),
                content=data,
                headers=headers,
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("Failed to upload object to Supabase Storage.") from exc

        if response.status_code not in (200, 201):
            raise RuntimeError("Failed to upload object to Supabase Storage.")

    def download_bytes(self, key: str) -> bytes:
        try:
            response = httpx.get(
                self._object_url(key),
                headers=self._auth_headers(),
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("Failed to download object from Supabase Storage.") from exc

        if response.status_code == 404:
            raise RuntimeError("Object not found in Supabase Storage.")
        if response.status_code != 200:
            raise RuntimeError("Failed to download object from Supabase Storage.")
        return response.content

    def delete(self, key: str) -> None:
        try:
            response = httpx.delete(
                self._object_url(key),
                headers=self._auth_headers(),
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise RuntimeError("Failed to delete object from Supabase Storage.") from exc

        if response.status_code not in (200, 204, 404):
            raise RuntimeError("Failed to delete object from Supabase Storage.")
