"""Durable object-storage helper for RootPatch validation snapshots.

Stage 1 foundation: this module provides a small S3-compatible client for
Cloudflare R2 or any S3-compatible object store. It is intentionally lazy so
that importing it does not require boto3 unless storage operations are used.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from app.core.config import Settings


@dataclass(frozen=True)
class ObjectStorageConfig:
    bucket: str
    endpoint_url: Optional[str]
    region: str
    access_key_id: Optional[str]
    secret_access_key: Optional[str]


class ObjectStorage:
    """Thin wrapper around an S3-compatible object store."""

    def __init__(self, settings: Settings) -> None:
        self.config = ObjectStorageConfig(
            bucket=settings.object_storage_bucket or "",
            endpoint_url=settings.object_storage_endpoint,
            region=settings.object_storage_region,
            access_key_id=settings.object_storage_access_key_id,
            secret_access_key=settings.object_storage_secret_access_key,
        )
        if not self.config.bucket:
            raise RuntimeError("ROOTPATCH_OBJECT_STORAGE_BUCKET is required for object storage.")
        if not self.config.access_key_id or not self.config.secret_access_key:
            raise RuntimeError(
                "ROOTPATCH_OBJECT_STORAGE_ACCESS_KEY_ID and "
                "ROOTPATCH_OBJECT_STORAGE_SECRET_ACCESS_KEY are required."
            )

    def _client(self):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for object storage operations.") from exc

        return boto3.client(
            "s3",
            endpoint_url=self.config.endpoint_url,
            aws_access_key_id=self.config.access_key_id,
            aws_secret_access_key=self.config.secret_access_key,
            region_name=self.config.region,
        )

    def upload_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/zip",
        if_none_match: bool = False,
    ) -> None:
        if not key or ".." in key.split("/"):
            raise ValueError("Unsafe object key.")
        params = {
            "Bucket": self.config.bucket,
            "Key": key,
            "Body": data,
            "ContentType": content_type,
        }
        if if_none_match:
            params["IfNoneMatch"] = "*"
        try:
            self._client().put_object(**params)
        except Exception as exc:
            raise RuntimeError("Failed to upload object to storage.") from exc

    def download_bytes(self, key: str) -> bytes:
        if not key or ".." in key.split("/"):
            raise ValueError("Unsafe object key.")
        try:
            response = self._client().get_object(Bucket=self.config.bucket, Key=key)
            return response["Body"].read()
        except Exception as exc:
            raise RuntimeError("Failed to download object from storage.") from exc

    def create_presigned_get_url(self, key: str, expires_in: int = 300) -> str:
        if not key or ".." in key.split("/"):
            raise ValueError("Unsafe object key.")
        return self._client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.config.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def delete(self, key: str) -> None:
        if not key or ".." in key.split("/"):
            raise ValueError("Unsafe object key.")
        self._client().delete_object(Bucket=self.config.bucket, Key=key)
