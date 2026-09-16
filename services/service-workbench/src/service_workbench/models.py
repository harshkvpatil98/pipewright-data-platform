"""Saved queries, query history, and notebooks.

Query history is the one here worth explaining. It exists because the commonest
question in a workbench is "what did I run that worked?", and nobody writes that
down. It stores the SQL, who ran it, against what, how long it took and whether
it succeeded -- and deliberately **not the results**, which can be a customer's
personal data and which nobody asked this platform to retain.

The SQL itself *is* stored, and a query can carry a literal in its WHERE clause.
That is the feature working as intended -- history without the query is not
history -- but it means the retention policy that covers this table is the one
that covers whatever people type into it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

CELL_KINDS = ("sql", "python", "recipe", "markdown")


class SavedQuery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A query somebody kept, with the parameters it needs."""

    __tablename__ = "workbench_saved_queries"
    __table_args__ = (
        Index("ix_workbench_saved_queries_project_id", "project_id"),
        Index("ix_workbench_saved_queries_project_name", "project_id", "name", unique=True),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    #: Declared parameters with their default values, so a saved query can be
    #: run by somebody who did not write it.
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class QueryRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One execution. Results are deliberately not stored."""

    __tablename__ = "workbench_query_runs"
    __table_args__ = (
        Index("ix_workbench_query_runs_project_created", "project_id", "created_at"),
        Index("ix_workbench_query_runs_user", "run_by_user_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    saved_query_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workbench_saved_queries.id", ondelete="SET NULL"),
        nullable=True,
    )
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    statement_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: True when any statement in the script changed data or structure.
    wrote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    succeeded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    duration_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rows_returned: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_affected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Notebook(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An ordered set of cells sharing one namespace."""

    __tablename__ = "workbench_notebooks"
    __table_args__ = (Index("ix_workbench_notebooks_project_id", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    cells: Mapped[list["NotebookCell"]] = relationship(
        back_populates="notebook",
        cascade="all, delete-orphan",
        order_by="NotebookCell.position",
        lazy="selectin",
    )


class NotebookCell(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workbench_notebook_cells"
    __table_args__ = (
        Index("ix_workbench_notebook_cells_notebook", "notebook_id", "position"),
    )

    notebook_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workbench_notebooks.id", ondelete="CASCADE"), nullable=False
    )
    # Explicit, because `created_at` defaults to the transaction time in
    # Postgres and every cell saved in one request would tie.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="sql")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    #: The name this cell's output is bound to in the shared namespace.
    output_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Per-cell settings: a recipe cell's steps, a SQL cell's parameters.
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    notebook: Mapped[Notebook] = relationship(back_populates="cells")
