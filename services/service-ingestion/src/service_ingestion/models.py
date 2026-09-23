"""Where a confirmed ingest spec lives between uploads.

The point of storing one is that **next month's file reads the same way as last
month's**. Re-running inference instead would be subtly worse than useless: it
depends on the data, so a column that read as day-first in January because one
row happened to say `15/01` becomes ambiguous in February when no row does, and
the same recurring report is imported two different ways.

A spec is found again by two keys, tried in that order:

1. **The column fingerprint** — the file's column names, normalised and hashed.
   This is the reliable one: the same report has the same columns whatever it
   is called this month.
2. **The filename pattern** — `sales-2026-01.csv` with the digits masked. This
   catches the first upload of a renamed file, and the case where a column was
   added upstream so the fingerprint moved.

Both are stored, both are indexed, and a match on either is offered rather than
applied — "we read this file this way last time, still right?" is a question
worth asking once a month.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class IngestSpecRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One confirmed way of reading one recurring kind of file."""

    __tablename__ = "ingest_specs"
    __table_args__ = (
        Index("ix_ingest_specs_project_id", "project_id"),
        # The lookup the upload path makes on every file.
        Index("ix_ingest_specs_fingerprint", "project_id", "column_fingerprint"),
        Index("ix_ingest_specs_pattern", "project_id", "name_pattern"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    #: What a person calls this: "Monthly bank statement".
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    #: The filename with digits masked: `sales-####-##.csv`.
    name_pattern: Mapped[str] = mapped_column(String(300), nullable=False)
    #: A hash of the normalised column names.
    column_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    file_format: Mapped[str] = mapped_column(String(32), nullable=False)
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: How many uploads have used it, and when it was last useful. A spec that
    #: has never been reused is a spec worth deleting.
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class UploadSessionRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An in-progress chunked upload, durable across a gateway restart.

    The chunks were always written to storage as they arrived; only the record
    of *which* chunks arrived lived in process memory, so a restart orphaned a
    half-finished upload -- the parts sat on disk with nothing that knew how to
    reassemble them. Persisting the session here means a restart resumes rather
    than restarts: the client asks which chunks arrived and gets a true answer.
    """

    __tablename__ = "upload_sessions"
    __table_args__ = (
        Index("ix_upload_sessions_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    expected_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: {chunk_index: byte_length} for every chunk received, keyed by string
    #: because JSON object keys are strings.
    received_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


#: Runs of digits, which is what changes between one month's file and the next.
_DIGITS = re.compile(r"\d")


def name_pattern(file_name: str) -> str:
    """A filename with the parts that change each period masked out.

    `sales-2026-01.csv` and `sales-2026-02.csv` share a pattern; `sales.csv`
    and `returns.csv` do not.
    """
    base = (file_name or "").strip().lower().rsplit("/", 1)[-1]
    return _DIGITS.sub("#", base)[:300]


def column_fingerprint(columns: list[str]) -> str:
    """A stable hash of a file's column names.

    Order-insensitive and case-insensitive: a column reordered upstream is the
    same report, and `Order ID` becoming `order_id` is a rename nobody meant as
    a new file. Whitespace and punctuation are normalised for the same reason.
    """
    normalised = sorted(
        re.sub(r"[^a-z0-9]+", "_", str(name).strip().lower()).strip("_")
        for name in columns
    )
    return hashlib.sha256("".join(normalised).encode("utf-8")).hexdigest()
