from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
# `Uuid`, not the postgresql-specific `UUID`: the dialect type declares a bare
# UUID column, which SQLite gives NUMERIC affinity, so an identifier that
# happens to be all decimal digits is silently converted to a float and comes
# back corrupted. `Uuid` renders native on Postgres and CHAR(32) elsewhere.
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from service_auth.models import User
    from service_datasets.models import Dataset
    from service_pipeline_runs.models import PipelineRun
    from service_projects.models import Project


class TransformationPipeline(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = 'transformation_pipelines'
    __table_args__ = (
        Index('ix_transformation_pipelines_project_id', 'project_id'),
        Index('ix_transformation_pipelines_base_dataset_id', 'base_dataset_id'),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False
    )
    base_dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('datasets.id', ondelete='CASCADE'), nullable=False
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='draft')
    steps_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # The dataset this recipe's runs write to: the first run creates it and
    # every later run adds a version (replays excepted, which stay separate).
    output_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey('datasets.id', ondelete='SET NULL'), nullable=True
    )
    # Which save this is (C2): a save that names an older revision is
    # refused rather than written over someone else's.
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default='1')
    # A stable id per step, in the same order as steps_json, so people
    # editing together can name the step they changed.
    step_ids_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    revised_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    revised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates='transformation_pipelines')
    base_dataset: Mapped[Dataset] = relationship('Dataset', foreign_keys=[base_dataset_id])
    created_by_user: Mapped[User | None] = relationship(foreign_keys=[created_by_user_id])
    derived_datasets: Mapped[list[Dataset]] = relationship(
        'Dataset',
        back_populates='created_from_pipeline',
        foreign_keys='Dataset.created_from_pipeline_id',
    )
    pipeline_runs: Mapped[list[PipelineRun]] = relationship(
        'PipelineRun',
        back_populates='transformation_pipeline',
        foreign_keys='PipelineRun.pipeline_id',
    )


class RecipeSharedCopy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The working copy of a recipe that everyone editing it shares (C2).

    Changes merge on the server (`service_transformations.coedit`), so it
    is what each Studio shows; saving writes it to the recipe. A change made
    outside the Studio starts a new `epoch`, reseeded from the saved recipe.
    """

    __tablename__ = 'recipe_shared_copies'
    __table_args__ = (UniqueConstraint('pipeline_id', name='uq_recipe_shared_copies_pipeline'),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('projects.id', ondelete='CASCADE'), nullable=False
    )
    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('transformation_pipelines.id', ondelete='CASCADE'), nullable=False
    )
    epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The last change merged in; never goes back, across epochs.
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    doc_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    #: Why the copy last started again, said to whoever had it open.
    reset_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class RecipeEditBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One person's changes to a shared copy, in the order they arrived."""

    __tablename__ = 'recipe_edit_batches'
    __table_args__ = (
        UniqueConstraint('pipeline_id', 'seq', name='uq_recipe_edit_batches_seq'),
        Index('ix_recipe_edit_batches_pipeline_seq', 'pipeline_id', 'seq'),
    )

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey('transformation_pipelines.id', ondelete='CASCADE'), nullable=False
    )
    epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    )
    ops_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
