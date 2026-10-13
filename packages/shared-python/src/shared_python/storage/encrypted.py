"""Stored files encrypted at rest (adoption-readiness A6, W5).

With ``STORAGE_ENCRYPTION_KEY`` set, every file the platform stores (uploads,
dataset versions, upload parts) is written as AES-256-GCM ciphertext and read
back transparently, so callers never see the difference. Files written before
the key was set have no header and are read as they are; the
``platform-encrypt-storage`` command encrypts them in place.

Format: ``PWENC1`` + 12-byte nonce + ciphertext with its 16-byte tag. The key
is 32 random bytes, URL-safe base64 encoded (a Fernet key works). Losing the
key loses the files: keep it with the database backups, not beside the files.
"""

from __future__ import annotations

import base64
import binascii
import io
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from shared_python.storage.interface import StoredArtifact

MAGIC = b"PWENC1"
_NONCE = 12


class StorageKeyError(ValueError):
    """The configured key is not 32 bytes of URL-safe base64."""


def load_key(encoded: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(encoded.strip().encode())
    except (binascii.Error, ValueError) as exc:
        raise StorageKeyError("STORAGE_ENCRYPTION_KEY is not valid base64.") from exc
    if len(key) != 32:
        raise StorageKeyError(
            "STORAGE_ENCRYPTION_KEY must be 32 random bytes, base64 encoded "
            "(python -c \"import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())\")."
        )
    return key


def is_encrypted(data: bytes) -> bool:
    return data.startswith(MAGIC)


def encrypt(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(_NONCE)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, plaintext, MAGIC)


def decrypt(key: bytes, data: bytes) -> bytes:
    if not is_encrypted(data):
        return data
    nonce = data[len(MAGIC) : len(MAGIC) + _NONCE]
    return AESGCM(key).decrypt(nonce, data[len(MAGIC) + _NONCE :], MAGIC)


class EncryptedStorageBackend:
    """Wraps any storage backend; the files it holds are ciphertext."""

    encrypted = True

    def __init__(self, inner, key: bytes):
        self.inner = inner
        self._key = key

    def save_upload(self, *, relative_path: str, file_bytes: bytes) -> StoredArtifact:
        stored = self.inner.save_upload(relative_path=relative_path, file_bytes=encrypt(self._key, file_bytes))
        # Callers record and show the size of their data, not of the ciphertext.
        return StoredArtifact(relative_path=stored.relative_path, file_name=stored.file_name, size_bytes=len(file_bytes))

    def read_bytes(self, relative_path: str) -> bytes:
        return decrypt(self._key, self.inner.read_bytes(relative_path))

    def open_stream(self, relative_path: str):
        return io.BytesIO(self.read_bytes(relative_path))

    def delete(self, relative_path: str) -> None:
        self.inner.delete(relative_path)

    def exists(self, relative_path: str) -> bool:
        return self.inner.exists(relative_path)

    def list_paths(self):
        return self.inner.list_paths()

    def encrypt_existing(self) -> tuple[int, int]:
        """Encrypt every file stored before the key was set. Returns (encrypted, already)."""
        done = already = 0
        for path in self.inner.list_paths():
            data = self.inner.read_bytes(path)
            if is_encrypted(data):
                already += 1
                continue
            self.inner.save_upload(relative_path=path, file_bytes=encrypt(self._key, data))
            done += 1
        return done, already
