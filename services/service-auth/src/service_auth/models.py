from __future__ import annotations

from typing import TYPE_CHECKING

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import Uuid as UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared_python.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from service_pipeline_runs.models import PipelineRun
    from service_projects.models import Project


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_username", "username", unique=True),
        Index("ix_users_is_active", "is_active"),
    )

    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Optional contact + human name. The username is the login handle; a person
    # is greeted and listed by their display name when they have one.
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Every issued token carries the value this had at issue time. Bumping it
    # ends all of that user's sessions at once without a session table.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Which tenant this person belongs to. Null on a single-tenant deployment,
    # where it matches the equally-null organisation on every project.
    organisation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    projects: Mapped[list[Project]] = relationship(back_populates="owner")
    pipeline_runs: Mapped[list[PipelineRun]] = relationship(back_populates="triggered_by_user")


class UserPreference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-person interface settings.

    A separate table rather than columns on `users` because this grows: the
    Studio adds grid density, keyboard scheme and column defaults, and none of
    that belongs in the identity record.

    Stored server-side, not only in localStorage, so someone's setup follows
    them between machines -- and so the server can render the correct theme on
    first paint instead of flashing the wrong one.
    """

    __tablename__ = "user_preferences"
    __table_args__ = (Index("ix_user_preferences_user_id", "user_id", unique=True),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # "system" means follow the operating system, and is the default: it is the
    # only value that stays correct when someone changes their OS setting.
    theme: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    density: Mapped[str] = mapped_column(String(16), nullable=False, default="comfortable")
    # Room for settings added later without a migration each time. Typed columns
    # above are the ones the server itself needs to reason about.
    extra_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    user: Mapped[User] = relationship()


class ApiToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A long-lived credential a person or script authenticates with.

    A data platform is scripted against on day one; without this the only
    credential is a user's short-lived login JWT, and customers end up putting
    a password in a cron job. The secret is shown once at creation and only its
    hash is stored, so a leaked database yields no usable tokens.
    """

    __tablename__ = "api_tokens"
    __table_args__ = (
        Index("ix_api_tokens_user", "user_id"),
        Index("ix_api_tokens_hash", "token_hash", unique=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # The visible, non-secret half (e.g. "pw_ab12cd34"), so a token can be
    # recognised in a list without revealing anything usable.
    prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # read | write | admin. Read cannot mutate; admin can reach admin routes.
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="read")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()


class AuthCode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A one-time code that sets a password: account activation, or admin reset.

    The plaintext is returned once (in a real deployment it would be emailed)
    and only its hash is stored. Single use, short lived, and tied to a
    purpose so an activation code cannot be spent as a password reset.
    """

    __tablename__ = "auth_codes"
    __table_args__ = (
        Index("ix_auth_codes_user", "user_id"),
        Index("ix_auth_codes_hash", "code_hash", unique=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)  # activation | reset
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()


class UserMfa(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person's second factor: a TOTP secret and its recovery codes.

    The secret is stored as-is because a TOTP code is *computed* from it on
    every verification -- unlike a password, it cannot be hashed and still do
    its job. The database is the trust boundary that protects it, the same one
    that protects every session and token here; a deployment that wants envelope
    encryption can layer it under this column without changing the interface.

    Recovery codes are the opposite: they are only ever *checked*, so they are
    hashed like a password reset code and the plaintext is shown once at
    generation. `activated` gates login -- an enrolment that was started but
    never confirmed with a live code must not lock anyone out.
    """

    __tablename__ = "user_mfa"
    __table_args__ = (Index("ix_user_mfa_user", "user_id", unique=True),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    activated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: [{"hash": "...", "used_at": null}] -- SHA-256 hashes, used-once.
    recovery_codes_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)

    user: Mapped[User] = relationship()
