"""Uploading a file too big to send in one request.

A 2GB CSV must not fail at 95%. The requirement is not really about size — it
is about the fact that a single HTTP request holding two gigabytes has no way
to recover from a dropped connection, a proxy timeout or a laptop lid closing,
and every one of those happens.

So an upload becomes a session: the client asks for one, sends fixed-size
chunks, and can ask at any point which chunks arrived. Resuming is then not a
special path — it is the ordinary path, with the already-received chunks
skipped.

The design decisions that matter:

* **Chunks are written to storage as they arrive**, not held in memory. The
  whole point is that the file does not fit comfortably in memory.
* **Each chunk is addressed by index**, so a retry of chunk 7 is idempotent:
  it overwrites chunk 7 rather than appending a second copy. A client that
  retries after a timeout it never saw the response to is the common case.
* **The checksum is verified on completion.** A resumed upload assembled from
  two sessions is exactly where a silently truncated chunk would hide, and a
  dataset that is 99.97% of a file is worse than a failed upload.
* **Sessions expire.** An abandoned upload holds disk; a session nobody
  finished is swept with its parts.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from shared_python.errors import BadRequestError, NotFoundError

#: Chunk size the client is told to use. Small enough that re-sending one after
#: a failure is cheap, large enough that a 2GB file is ~250 requests and not
#: 250,000.
CHUNK_BYTES = 8 * 1024 * 1024

#: How long an unfinished session survives.
SESSION_TTL = timedelta(hours=12)

#: A ceiling on parts, so a client sending 1-byte chunks cannot create millions
#: of storage objects.
MAX_CHUNKS = 4096


@dataclass
class UploadSession:
    """One in-progress upload."""

    id: uuid.UUID
    project_id: uuid.UUID
    file_name: str
    content_type: str
    total_bytes: int
    chunk_bytes: int
    #: The client's checksum of the whole file, when it supplied one.
    expected_sha256: str | None
    created_at: datetime
    created_by_user_id: uuid.UUID | None = None
    received: dict[int, int] = field(default_factory=dict)
    completed: bool = False

    @property
    def expected_chunks(self) -> int:
        return max(1, -(-self.total_bytes // self.chunk_bytes))

    @property
    def received_bytes(self) -> int:
        return sum(self.received.values())

    @property
    def missing(self) -> list[int]:
        return [index for index in range(self.expected_chunks) if index not in self.received]

    @property
    def expired(self) -> bool:
        return datetime.now(UTC) - self.created_at > SESSION_TTL

    def to_dict(self) -> dict[str, Any]:
        return {
            "upload_id": str(self.id),
            "file_name": self.file_name,
            "total_bytes": self.total_bytes,
            "chunk_bytes": self.chunk_bytes,
            "expected_chunks": self.expected_chunks,
            "received_chunks": sorted(self.received),
            "missing_chunks": self.missing,
            "received_bytes": self.received_bytes,
            "complete": not self.missing,
            "completed": self.completed,
            "expires_at": (self.created_at + SESSION_TTL).isoformat(),
        }


class SessionStore:
    """Where in-progress sessions live.

    In memory, deliberately. A session is worthless without its chunks, the
    chunks are in this process's storage backend, and a session table would be
    a database write per 8MB of upload for state that cannot outlive the parts
    it describes. A deployment that runs several gateway processes behind a
    load balancer needs sticky sessions for uploads, which is stated rather
    than papered over -- see `docs/HANDOFF.md`.
    """

    def __init__(self) -> None:
        self._sessions: dict[uuid.UUID, UploadSession] = {}

    def create(
        self,
        *,
        project_id: uuid.UUID,
        file_name: str,
        content_type: str,
        total_bytes: int,
        expected_sha256: str | None = None,
        created_by_user_id: uuid.UUID | None = None,
        chunk_bytes: int = CHUNK_BYTES,
    ) -> UploadSession:
        if total_bytes <= 0:
            raise BadRequestError("An upload needs a positive total size.")
        chunks = max(1, -(-total_bytes // chunk_bytes))
        if chunks > MAX_CHUNKS:
            # Raise the chunk size rather than refusing the file: the ceiling
            # exists to bound the number of parts, not the size of the upload.
            chunk_bytes = max(chunk_bytes, -(-total_bytes // MAX_CHUNKS))
        session = UploadSession(
            id=uuid.uuid4(),
            project_id=project_id,
            file_name=file_name,
            content_type=content_type,
            total_bytes=total_bytes,
            chunk_bytes=chunk_bytes,
            expected_sha256=(expected_sha256 or "").lower() or None,
            created_at=datetime.now(UTC),
            created_by_user_id=created_by_user_id,
        )
        self._sessions[session.id] = session
        self.sweep()
        return session

    def get(self, upload_id: uuid.UUID, *, project_id: uuid.UUID) -> UploadSession:
        session = self._sessions.get(upload_id)
        # Scoped to the project: an upload id is a guess away from another
        # project's file otherwise.
        if session is None or session.project_id != project_id or session.expired:
            raise NotFoundError("Upload session not found or expired.")
        return session

    def drop(self, upload_id: uuid.UUID) -> None:
        self._sessions.pop(upload_id, None)

    def sweep(self) -> list[UploadSession]:
        """Forget expired sessions and hand them back so their parts go too."""
        stale = [session for session in self._sessions.values() if session.expired]
        for session in stale:
            self._sessions.pop(session.id, None)
        return stale


#: One store per process. Instantiated here rather than per request, because a
#: session that did not survive the next request would defeat the purpose.
SESSIONS = SessionStore()


def part_path(session: UploadSession, index: int) -> str:
    return f"uploads/incomplete/{session.project_id}/{session.id}/{index:06d}.part"


def receive_chunk(
    session: UploadSession,
    *,
    index: int,
    payload: bytes,
    storage_backend: Any,
) -> UploadSession:
    """Store one chunk. Re-sending the same index replaces it."""
    if session.completed:
        raise BadRequestError("This upload has already been completed.")
    if index < 0 or index >= session.expected_chunks:
        raise BadRequestError(
            f"Chunk {index} is outside this upload, which has "
            f"{session.expected_chunks} chunk(s)."
        )
    if not payload:
        raise BadRequestError("A chunk cannot be empty.")

    last = index == session.expected_chunks - 1
    if not last and len(payload) != session.chunk_bytes:
        # Every chunk but the last must be exactly the agreed size, or the
        # offsets do not line up and the assembled file is silently shuffled.
        raise BadRequestError(
            f"Chunk {index} is {len(payload)} bytes; every chunk except the last must "
            f"be exactly {session.chunk_bytes}."
        )
    if session.received_bytes - session.received.get(index, 0) + len(payload) > session.total_bytes:
        raise BadRequestError("These chunks add up to more than the declared file size.")

    storage_backend.save_upload(relative_path=part_path(session, index), file_bytes=payload)
    session.received[index] = len(payload)
    return session


def assemble(session: UploadSession, *, storage_backend: Any) -> bytes:
    """Join the chunks, check the whole thing, and clean up the parts."""
    if session.missing:
        raise BadRequestError(
            f"This upload is incomplete: chunk(s) {session.missing[:10]} never arrived."
        )

    digest = hashlib.sha256()
    parts: list[bytes] = []
    for index in range(session.expected_chunks):
        chunk = storage_backend.read_bytes(part_path(session, index))
        digest.update(chunk)
        parts.append(chunk)
    payload = b"".join(parts)

    if len(payload) != session.total_bytes:
        raise BadRequestError(
            f"The assembled file is {len(payload):,} bytes; {session.total_bytes:,} were "
            "declared. Start the upload again."
        )
    if session.expected_sha256 and digest.hexdigest() != session.expected_sha256:
        # The case this exists for: a chunk that arrived truncated through a
        # proxy. A dataset that is 99.97% of a file is worse than a failure.
        raise BadRequestError(
            "The assembled file does not match the checksum the client sent. A chunk "
            "arrived corrupted; start the upload again."
        )

    session.completed = True
    cleanup(session, storage_backend=storage_backend)
    return payload


def cleanup(session: UploadSession, *, storage_backend: Any) -> None:
    """Remove the parts. Safe to call twice."""
    for index in range(session.expected_chunks):
        path = part_path(session, index)
        try:
            if storage_backend.exists(path):
                storage_backend.delete(path)
        except Exception:  # noqa: BLE001 - a part that will not delete is not a failed upload
            continue
