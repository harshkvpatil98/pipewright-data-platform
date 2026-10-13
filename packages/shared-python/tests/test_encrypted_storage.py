"""Stored files encrypted at rest (adoption-readiness A6, W5)."""

from __future__ import annotations

import base64
import os

import pytest

from shared_python.storage.encrypted import (
    MAGIC,
    EncryptedStorageBackend,
    StorageKeyError,
    load_key,
)
from shared_python.storage.local import LocalStorageBackend

KEY = base64.urlsafe_b64encode(os.urandom(32)).decode()


def test_files_are_ciphertext_on_disk_and_plain_to_callers(tmp_path) -> None:
    inner = LocalStorageBackend(str(tmp_path))
    backend = EncryptedStorageBackend(inner, load_key(KEY))
    stored = backend.save_upload(relative_path="a/orders.csv", file_bytes=b"id,email\n1,ann@example.com\n")
    on_disk = (tmp_path / "a" / "orders.csv").read_bytes()
    assert on_disk.startswith(MAGIC) and b"ann@example.com" not in on_disk
    assert backend.read_bytes("a/orders.csv") == b"id,email\n1,ann@example.com\n"
    assert backend.open_stream("a/orders.csv").read().startswith(b"id,email")
    assert stored.size_bytes == len(b"id,email\n1,ann@example.com\n")


def test_files_stored_before_the_key_still_read_and_can_be_encrypted(tmp_path) -> None:
    inner = LocalStorageBackend(str(tmp_path))
    inner.save_upload(relative_path="old.csv", file_bytes=b"x\n1\n")
    backend = EncryptedStorageBackend(inner, load_key(KEY))
    assert backend.read_bytes("old.csv") == b"x\n1\n"
    assert backend.encrypt_existing() == (1, 0)
    assert (tmp_path / "old.csv").read_bytes().startswith(MAGIC)
    assert backend.read_bytes("old.csv") == b"x\n1\n"
    assert backend.encrypt_existing() == (0, 1)


def test_the_wrong_key_cannot_read(tmp_path) -> None:
    from cryptography.exceptions import InvalidTag

    inner = LocalStorageBackend(str(tmp_path))
    EncryptedStorageBackend(inner, load_key(KEY)).save_upload(relative_path="f", file_bytes=b"secret")
    other = EncryptedStorageBackend(inner, os.urandom(32))
    with pytest.raises(InvalidTag):
        other.read_bytes("f")


def test_a_bad_key_is_explained() -> None:
    with pytest.raises(StorageKeyError, match="32 random bytes"):
        load_key(base64.urlsafe_b64encode(b"short").decode())
