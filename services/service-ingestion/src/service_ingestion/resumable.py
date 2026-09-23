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

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_ingestion.models import UploadSessionRecord
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


def _to_session(row: UploadSessionRecord) -> UploadSession:
    created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC)
    return UploadSession(
        id=row.id,
        project_id=row.project_id,
        file_name=row.file_name,
        content_type=row.content_type,
        total_bytes=row.total_bytes,
        chunk_bytes=row.chunk_bytes,
        expected_sha256=row.expected_sha256,
        created_at=created,
        created_by_user_id=row.created_by_user_id,
        received={int(index): int(length) for index, length in (row.received_json or {}).items()},
        completed=row.completed,
    )


class SessionStore:
    """Where in-progress sessions live: the database.

    The chunks were always written to storage as they arrived; what used to be
    in process memory was only the *index* of which chunks had landed. That is
    exactly the state a gateway restart must not lose, or the parts on disk
    become unreassemblable orphans. Persisting it -- one small row, updated once
    per 8MB chunk -- makes a resume survive a restart and lets any gateway
    process serve any upload, so uploads no longer need sticky sessions.
    """

    def create(
        self,
        db: Session,
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
        row = UploadSessionRecord(
            project_id=project_id,
            file_name=file_name,
            content_type=content_type or "",
            total_bytes=total_bytes,
            chunk_bytes=chunk_bytes,
            expected_sha256=(expected_sha256 or "").lower() or None,
            received_json={},
            completed=False,
            created_by_user_id=created_by_user_id,
            created_at=datetime.now(UTC),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        self.sweep(db)
        return _to_session(row)

    def get(self, db: Session, upload_id: uuid.UUID, *, project_id: uuid.UUID) -> UploadSession:
        row = db.get(UploadSessionRecord, upload_id)
        # Scoped to the project: an upload id is a guess away from another
        # project's file otherwise.
        if row is None or row.project_id != project_id:
            raise NotFoundError("Upload session not found or expired.")
        session = _to_session(row)
        if session.expired:
            raise NotFoundError("Upload session not found or expired.")
        return session

    def save(self, db: Session, session: UploadSession) -> None:
        """Persist which chunks have arrived. Called after each chunk, so a
        restart mid-upload still knows exactly where the client left off."""
        row = db.get(UploadSessionRecord, session.id)
        if row is None:
            return
        row.received_json = {str(index): length for index, length in session.received.items()}
        row.completed = session.completed
        db.commit()

    def drop(self, db: Session, upload_id: uuid.UUID) -> None:
        row = db.get(UploadSessionRecord, upload_id)
        if row is not None:
            db.delete(row)
            db.commit()

    def sweep(self, db: Session) -> list[UploadSession]:
        """Delete expired session rows and hand them back so their parts go too."""
        cutoff = datetime.now(UTC) - SESSION_TTL
        rows = list(
            db.scalars(select(UploadSessionRecord).where(UploadSessionRecord.created_at < cutoff)).all()
        )
        stale = [_to_session(row) for row in rows]
        for row in rows:
            db.delete(row)
        if rows:
            db.commit()
        return stale


#: Stateless: every method takes the request's db session, so the store holds
#: no per-process state and any gateway can serve any upload.
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
