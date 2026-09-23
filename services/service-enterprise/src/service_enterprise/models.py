from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Organisation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tenant: the boundary nothing crosses.

    Projects and people belong to one. The isolation is enforced in the same
    place project membership is, because two places that decide who can see what
    is one place too many.
    """

    __tablename__ = "organisations"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_organisations_slug"),
        Index("ix_organisations_slug", "slug"),
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(180), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="standard")
    # Null means no limit. A limit of zero would be a locked-out tenant, which
    # is a different thing and should be `is_active`.
    max_projects: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_datasets: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_rows_per_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # How long a session issued to a member of this tenant lasts, in minutes.
    # Null means "use the deployment default": a tenant that has never set a
    # policy must not be silently given one, and the column cannot distinguish
    # "unset" from "set to the default" any other way.
    session_max_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    settings_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class SecurityPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Which rows and columns a role may see on one dataset."""

    __tablename__ = "security_policies"
    __table_args__ = (
        Index("ix_security_policies_dataset", "dataset_id", "enabled"),
        Index("ix_security_policies_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    row_rules_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    column_rules_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class RetentionPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """How long something is kept before it is deleted.

    Retention is a deletion schedule, so the model records what was deleted and
    when. A policy that quietly removed data with no record would be impossible
    to answer questions about afterwards -- which is the whole point of having
    one.
    """

    __tablename__ = "retention_policies"
    __table_args__ = (
        UniqueConstraint("project_id", "resource_type", name="uq_retention_project_resource"),
        Index("ix_retention_policies_project_id", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    retain_days: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Deleting is irreversible, so a policy runs in report-only mode until
    # somebody has looked at what it would remove.
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_deleted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ErasureRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Somebody asking to be removed, and what was done about it."""

    __tablename__ = "erasure_requests"
    __table_args__ = (
        Index("ix_erasure_requests_project_status", "project_id", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    subject_value: Mapped[str] = mapped_column(String(320), nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="email")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    datasets_searched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_affected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # What was found and where, so the request can be answered with evidence.
    report_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class UsageRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What one piece of work cost.

    Long and narrow like the metric table, and for the same reason: the things
    worth measuring change, and a wide table needs a migration for each one.
    """

    __tablename__ = "usage_records"
    __table_args__ = (
        Index("ix_usage_records_project_period", "project_id", "recorded_at"),
        Index("ix_usage_records_org_period", "organisation_id", "recorded_at"),
        Index("ix_usage_records_subject", "subject_type", "subject_id"),
    )

    organisation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # What did the work: a pipeline, a workflow, an extraction job, a report.
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subject_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    rows_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    compute_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    bytes_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SsoLoginState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The short-lived state of one in-flight SSO sign-in.

    The authorization redirect and the callback are two separate requests, and
    the second must prove it belongs to the first: the `state` guards against a
    forged callback, and the PKCE `code_verifier` is the secret that binds the
    token exchange to the browser that started it. Both live here rather than in
    process memory so the callback works even if it lands on a different gateway
    than the redirect -- and so a restart mid-sign-in does not strand the user.
    Rows are one-time and short-lived; they are deleted on use and swept by age.
    """

    __tablename__ = "sso_login_states"
    __table_args__ = (Index("ix_sso_login_states_state", "state", unique=True),)

    state: Mapped[str] = mapped_column(String(64), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Where to send the browser after a successful sign-in (a relative path).
    next_path: Mapped[str] = mapped_column(String(512), nullable=False, default="/")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SamlLoginState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The short-lived state of one in-flight SAML sign-in.

    The SAML equivalent of `SsoLoginState`, and it does two jobs with one row.
    The `request_id` is demanded back in the assertion's `InResponseTo`, which
    is what makes an assertion minted for somebody else useless here; and
    because the row is deleted the moment it is spent, the same assertion
    cannot be presented twice. A separate "seen assertion ids" table would be a
    second way to say the same thing, and a second thing to sweep.

    A deliberate consequence: an unsolicited (IdP-initiated) assertion has no
    row to match and is refused. That is the intended behaviour, not a gap --
    accepting one means accepting anything the IdP's key has ever signed.
    """

    __tablename__ = "saml_login_states"
    __table_args__ = (Index("ix_saml_login_states_request_id", "request_id", unique=True),)

    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Where to send the browser after a successful sign-in (a relative path).
    next_path: Mapped[str] = mapped_column(String(512), nullable=False, default="/")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
