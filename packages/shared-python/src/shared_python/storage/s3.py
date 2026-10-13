"""Stored files in an S3-compatible bucket (adoption-readiness A7, X2).

The local backend keeps files on the gateway's own disk, so a second gateway
needs that disk mounted too. With files in a bucket (AWS S3, MinIO, Cloudflare
R2, Backblaze B2 and anything else that speaks the S3 API) every gateway and
worker reads the same files, and none of them holds state of its own: uploads
already keep their sessions in the database and their chunks in storage.

It keeps the local backend's meaning exactly: the same relative paths (under
an optional prefix), `FileNotFoundError` for a file that is not there, and
`list_paths` for the maintenance commands. Encryption at rest wraps it the way
it wraps the local one, so what reaches the bucket is already encrypted when a
key is set.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

from shared_python.storage.base import normalize_relative_path
from shared_python.storage.interface import StoredArtifact


class S3StorageBackend:
    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        client: Any = None,
    ) -> None:
        if not bucket:
            raise ValueError("STORAGE_S3_BUCKET is required when STORAGE_BACKEND is s3.")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        if client is None:
            import boto3

            client = boto3.client(
                "s3",
                endpoint_url=endpoint_url or None,
                region_name=region or None,
                aws_access_key_id=access_key_id or None,
                aws_secret_access_key=secret_access_key or None,
            )
        self.client = client

    def _key(self, relative_path: str) -> str:
        normalized = normalize_relative_path(relative_path)
        return f"{self.prefix}/{normalized}" if self.prefix else normalized

    def save_upload(self, *, relative_path: str, file_bytes: bytes) -> StoredArtifact:
        key = self._key(relative_path)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=file_bytes)
        return StoredArtifact(
            relative_path=normalize_relative_path(relative_path),
            file_name=key.rsplit("/", 1)[-1],
            size_bytes=len(file_bytes),
        )

    def _get(self, relative_path: str) -> Any:
        from botocore.exceptions import ClientError

        try:
            return self.client.get_object(Bucket=self.bucket, Key=self._key(relative_path))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
                raise FileNotFoundError(relative_path) from exc
            raise

    def open_stream(self, relative_path: str):
        # A file-like object, as the local backend's `open` returns; the body
        # is read once so callers can seek in it.
        return io.BytesIO(self._get(relative_path)["Body"].read())

    def read_bytes(self, relative_path: str) -> bytes:
        return self._get(relative_path)["Body"].read()

    def delete(self, relative_path: str) -> None:
        # S3 deletes are already silent for a missing key, as the local one is.
        self.client.delete_object(Bucket=self.bucket, Key=self._key(relative_path))

    def exists(self, relative_path: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(relative_path))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
                return False
            raise
        return True

    def list_paths(self) -> Iterator[str]:
        """Every stored file's relative path, for maintenance commands."""
        paginator = self.client.get_paginator("list_objects_v2")
        start = f"{self.prefix}/" if self.prefix else ""
        for page in paginator.paginate(Bucket=self.bucket, Prefix=start):
            for item in page.get("Contents", []) or []:
                yield item["Key"][len(start):]
