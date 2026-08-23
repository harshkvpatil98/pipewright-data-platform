from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class StoredArtifact:
    relative_path: str
    file_name: str
    size_bytes: int


class StorageBackend(Protocol):
    def save_upload(self, *, relative_path: str, file_bytes: bytes) -> StoredArtifact: ...

    def open_stream(self, relative_path: str): ...

    def read_bytes(self, relative_path: str) -> bytes: ...

    def delete(self, relative_path: str) -> None: ...

    def exists(self, relative_path: str) -> bool: ...
