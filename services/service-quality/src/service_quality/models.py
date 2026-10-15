from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
# `Uuid`, not the postgresql-specific `UUID`: the dialect type declares a bare
# UUID column, which SQLite gives NUMERIC affinity, so an identifier that
# happens to be all decimal digits is silently converted to a float and comes
# back corrupted. `Uuid` renders native on Postgres and CHAR(32) elsewhere.
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DataQualityRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An assertion about a dataset, evaluated on demand or as a pipeline gate."""

    __tablename__ = "data_quality_rules"
    __table_args__ = (
        Index("ix_data_quality_rules_project_id", "project_id"),
        Index("ix_data_quality_rules_dataset_id", "dataset_id"),
        Index("ix_data_quality_rules_project_enabled", "project_id", "enabled"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Null means the rule is reusable across datasets in the project.
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="error")
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)


class SchemaDriftEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A recorded schema change between two versions of a dataset."""

    __tablename__ = "schema_drift_events"
    __table_args__ = (
        Index("ix_schema_drift_events_project_id", "project_id"),
        Index("ix_schema_drift_events_dataset_id", "dataset_id"),
        Index("ix_schema_drift_events_severity", "severity"),
        Index("ix_schema_drift_events_project_ack", "project_id", "acknowledged"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    previous_dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    # Set when drift was detected during an extraction rather than on demand.
    extraction_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    added_columns: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    removed_columns: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    type_changes: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DataQualityRunResult(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One rule's outcome for one evaluation of one dataset."""

    __tablename__ = "data_quality_run_results"
    __table_args__ = (
        Index("ix_dq_run_results_project_id", "project_id"),
        Index("ix_dq_run_results_dataset_id", "dataset_id"),
        Index("ix_dq_run_results_rule_id", "rule_id"),
        Index("ix_dq_run_results_evaluation_id", "evaluation_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Groups every rule result produced by a single evaluation pass.
    evaluation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_quality_rules.id", ondelete="SET NULL"), nullable=True
    )
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True
    )
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True
    )

    rule_name: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    evaluated_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class DataContract(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A promise about one dataset that new data must keep (Phase 19, C1).

    One per dataset. The terms are kept whole here and in every version, so a
    problem can always say which terms it broke. Whether the contract is kept
    is not stored: it is whether any problem is still open.
    """

    __tablename__ = "data_contracts"
    __table_args__ = (
        UniqueConstraint("dataset_id", name="uq_data_contracts_dataset"),
        Index("ix_data_contracts_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: `stop` (data that breaks it is not saved) or `warn` (saved, and recorded).
    enforcement: Mapped[str] = mapped_column(String(16), nullable=False, default="stop")
    terms_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DataContractVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The contract as it was after one change, with what changed in words."""

    __tablename__ = "data_contract_versions"
    __table_args__ = (
        UniqueConstraint("contract_id", "version", name="uq_data_contract_versions_number"),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enforcement: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    terms_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    changes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DataContractFollower(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Someone who has asked to be told when a contract breaks or changes."""

    __tablename__ = "data_contract_followers"
    __table_args__ = (
        UniqueConstraint("contract_id", "user_id", name="uq_data_contract_followers_person"),
    )

    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


class DataContractProblem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """New data that broke a contract, or new data that is overdue.

    One row per source and set of broken terms while it lasts: the same
    nightly import breaking the same promise is one problem seen many times,
    not a new one each night. Resolved when that source's data keeps the
    contract again (or, for overdue data, when new data arrives).
    """

    __tablename__ = "data_contract_problems"
    __table_args__ = (
        Index("ix_data_contract_problems_contract_open", "contract_id", "resolved_at"),
        Index("ix_data_contract_problems_project_created", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    contract_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: `new_data` (the data broke a term) or `overdue` (no new data in time).
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: `stopped` (not saved), `let_through` (saved anyway) or `overdue`.
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    #: recipe, import, stream, rollback, erasure, check or None.
    source_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    #: [{"term": "email.present", "sentence": "..."}], in the order checked.
    reasons_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    times_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    pipeline_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DataContractEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Something to tell a contract's people, sent by the worker after commit."""

    __tablename__ = "data_contract_events"
    __table_args__ = (Index("ix_data_contract_events_unsent", "sent_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    #: broken, overdue, kept or changed.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Who made a change, so they are not told about their own.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
