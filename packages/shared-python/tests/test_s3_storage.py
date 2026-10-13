"""Stored files in an S3-compatible bucket (adoption-readiness A7, X2).

The same checks run twice: against a small in-memory stand-in for the S3 API,
always, and against a real store when STORAGE_TEST_S3_ENDPOINT, _BUCKET, _KEY
and _SECRET are set (CI runs MinIO; `docker-compose.connectors.yml` has one
for a laptop on port 19000).
"""

from __future__ import annotations

import os
import uuid

import pytest
from botocore.exceptions import ClientError

from shared_python.storage.encrypted import EncryptedStorageBackend, is_encrypted
from shared_python.storage.factory import build_storage_backend
from shared_python.storage.s3 import S3StorageBackend


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeS3:
    """Just the calls the backend makes, with S3's answers for a missing key."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    @staticmethod
    def _missing(operation: str) -> ClientError:
        return ClientError({"Error": {"Code": "NoSuchKey" if operation == "GetObject" else "404"}}, operation)

    def put_object(self, *, Bucket, Key, Body):  # noqa: N803 - boto3's names
        self.objects[(Bucket, Key)] = bytes(Body)

    def get_object(self, *, Bucket, Key):  # noqa: N803
        if (Bucket, Key) not in self.objects:
            raise self._missing("GetObject")
        return {"Body": _Body(self.objects[(Bucket, Key)])}

    def head_object(self, *, Bucket, Key):  # noqa: N803
        if (Bucket, Key) not in self.objects:
            raise self._missing("HeadObject")
        return {}

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        self.objects.pop((Bucket, Key), None)

    def get_paginator(self, _name):
        objects = self.objects

        class Paginator:
            def paginate(self, *, Bucket, Prefix):  # noqa: N803
                keys = sorted(key for bucket, key in objects if bucket == Bucket and key.startswith(Prefix))
                yield {"Contents": [{"Key": key} for key in keys]}

        return Paginator()


def _real_store() -> dict | None:
    names = ("STORAGE_TEST_S3_ENDPOINT", "STORAGE_TEST_S3_BUCKET", "STORAGE_TEST_S3_KEY", "STORAGE_TEST_S3_SECRET")
    if not all(os.environ.get(name) for name in names):
        return None
    return {name: os.environ[name] for name in names}


def _real_backend(prefix: str) -> S3StorageBackend:
    store = _real_store()
    backend = S3StorageBackend(
        bucket=store["STORAGE_TEST_S3_BUCKET"], prefix=prefix, endpoint_url=store["STORAGE_TEST_S3_ENDPOINT"],
        region="us-east-1", access_key_id=store["STORAGE_TEST_S3_KEY"],
        secret_access_key=store["STORAGE_TEST_S3_SECRET"],
    )
    try:
        backend.client.head_bucket(Bucket=backend.bucket)
    except ClientError:
        backend.client.create_bucket(Bucket=backend.bucket)
    return backend


@pytest.fixture(params=["stand-in", "real store"])
def backend(request) -> S3StorageBackend:
    prefix = f"tests/{uuid.uuid4().hex}"
    if request.param == "stand-in":
        return S3StorageBackend(bucket="files", prefix=prefix, client=FakeS3())
    if _real_store() is None:
        pytest.skip("Set STORAGE_TEST_S3_ENDPOINT, _BUCKET, _KEY and _SECRET to run against a real store.")
    return _real_backend(prefix)


def test_a_file_round_trips(backend) -> None:
    stored = backend.save_upload(relative_path="project/a/orders.csv", file_bytes=b"id\n1\n")
    assert stored.relative_path == "project/a/orders.csv"
    assert stored.file_name == "orders.csv"
    assert backend.read_bytes("project/a/orders.csv") == b"id\n1\n"
    with backend.open_stream("project/a/orders.csv") as stream:
        assert stream.read() == b"id\n1\n"
    assert backend.exists("project/a/orders.csv")


def test_a_missing_file_reads_as_not_found_like_on_disk(backend) -> None:
    with pytest.raises(FileNotFoundError):
        backend.read_bytes("nothing/here.csv")
    assert not backend.exists("nothing/here.csv")
    backend.delete("nothing/here.csv")  # silent, as on disk


def test_files_are_listed_relative_to_the_prefix(backend) -> None:
    backend.save_upload(relative_path="p/one.csv", file_bytes=b"1")
    backend.save_upload(relative_path="p/two.csv", file_bytes=b"2")
    assert sorted(backend.list_paths()) == ["p/one.csv", "p/two.csv"]
    backend.delete("p/one.csv")
    assert list(backend.list_paths()) == ["p/two.csv"]


def test_a_path_cannot_climb_out_of_its_folder(backend) -> None:
    with pytest.raises(ValueError):
        backend.save_upload(relative_path="../other-tenant/x.csv", file_bytes=b"x")


def test_encryption_at_rest_wraps_the_bucket_too(backend) -> None:
    key = os.urandom(32)
    encrypted = EncryptedStorageBackend(backend, key)
    encrypted.save_upload(relative_path="secret.csv", file_bytes=b"card,1234\n")
    assert is_encrypted(backend.read_bytes("secret.csv"))  # what the bucket holds
    assert encrypted.read_bytes("secret.csv") == b"card,1234\n"


def test_the_factory_builds_it_from_settings() -> None:
    class Settings:
        storage_backend = "s3"
        storage_s3_bucket = "files"
        storage_s3_prefix = "pipewright"
        storage_s3_endpoint_url = "http://127.0.0.1:9"
        storage_s3_region = "us-east-1"
        storage_s3_access_key_id = "k"
        storage_s3_secret_access_key = "s"
        storage_encryption_key = None

    backend = build_storage_backend(Settings())
    assert isinstance(backend, S3StorageBackend)
    assert backend.bucket == "files" and backend.prefix == "pipewright"


def test_a_bucket_is_required() -> None:
    with pytest.raises(ValueError, match="STORAGE_S3_BUCKET"):
        S3StorageBackend(bucket="", client=FakeS3())
