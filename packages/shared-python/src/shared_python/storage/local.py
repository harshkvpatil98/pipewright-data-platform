from __future__ import annotations

from pathlib import Path

from shared_python.storage.base import normalize_relative_path
from shared_python.storage.interface import StoredArtifact


class LocalStorageBackend:
    def __init__(self, root_path: str):
        self.root_path = Path(root_path).resolve()
        self.root_path.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative_path: str) -> Path:
        normalized = normalize_relative_path(relative_path)
        target = (self.root_path / normalized).resolve()
        if not str(target).startswith(str(self.root_path)):
            raise ValueError("Invalid storage target.")
        return target

    def save_upload(self, *, relative_path: str, file_bytes: bytes) -> StoredArtifact:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_bytes)
        return StoredArtifact(
            relative_path=normalize_relative_path(relative_path),
            file_name=target.name,
            size_bytes=len(file_bytes),
        )

    def open_stream(self, relative_path: str):
        return self._resolve(relative_path).open("rb")

    def read_bytes(self, relative_path: str) -> bytes:
        return self._resolve(relative_path).read_bytes()

    def delete(self, relative_path: str) -> None:
        target = self._resolve(relative_path)
        if target.exists():
            target.unlink()

    def exists(self, relative_path: str) -> bool:
        return self._resolve(relative_path).exists()
