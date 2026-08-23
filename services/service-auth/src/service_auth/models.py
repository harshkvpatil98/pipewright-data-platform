from __future__ import annotations

from typing import TYPE_CHECKING

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, String
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
