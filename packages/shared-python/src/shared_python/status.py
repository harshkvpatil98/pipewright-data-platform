from __future__ import annotations

import re

from typing import Any, Literal

from pydantic import BaseModel, Field


class ServiceStatus(BaseModel):
    name: str
    status: Literal["healthy", "degraded", "unhealthy"]
    details: dict[str, Any] = Field(default_factory=dict)


class SchedulerOperationalSnapshot(BaseModel):
    """Public-safe scheduler counters (no secrets). Internal run endpoint remains token-gated."""

    internal_api_configured: bool = Field(
        description="True when SCHEDULER_INTERNAL_TOKEN is set (does not expose the token)."
    )
    scheduler_runtime_id_configured: bool = Field(
        default=False,
        description="True when SCHEDULER_RUNTIME_ID is set to a non-empty value.",
    )
    total_schedules: int
    due_now_count: int
    lease_active_count: int = Field(
        default=0,
        description="Schedules holding a non-expired automatic-execution lease.",
    )
    stale_lease_count: int = Field(
        default=0,
        description="Schedules with an expired lease row still present (reclaimable on next poll).",
    )
    note: str


class RuntimeComponentHeartbeat(BaseModel):
    """The last beat from one background component on one host."""

    component: str
    host: str | None = None
    last_beat_at: str | None = Field(
        default=None, description="ISO 8601 UTC timestamp of the last beat, or null if none."
    )
    age_seconds: float | None = Field(
        default=None, description="Seconds since the last beat, or null if the component never beat."
    )
    interval_seconds: float | None = None
    status: str = "absent"
    healthy: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)


class RuntimeSnapshot(BaseModel):
    """Ground truth about the background runtime: are the workers actually alive?

    Distinct from the scheduler snapshot (which counts *work*), this counts
    *workers* -- the leading signal that queue-age inference could only guess at.
    """

    components: list[RuntimeComponentHeartbeat] = Field(default_factory=list)
    healthy: bool = Field(
        default=False,
        description="True when every expected component has a fresh, running beat.",
    )


class SecuritySnapshot(BaseModel):
    """The controls a security review asks about, as configured here (A6, W5).

    Facts only, no secrets: whether stored files are encrypted, the session
    policy, how many organisations restrict where people connect from, and
    whether single sign-on is configured."""

    files_encrypted_at_rest: bool = False
    idle_timeout_minutes: int = 60
    session_limit_hours: int = 12
    organisations_with_network_lists: int = 0
    sso_configured: bool = False
    trusted_proxy_hops: int = 0


class PlatformStatus(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    service: str
    environment: str
    version: str
    services: list[ServiceStatus]
    checked_at: str = Field(description="ISO 8601 UTC timestamp when this snapshot was assembled.")
    scheduler: SchedulerOperationalSnapshot
    runtime: RuntimeSnapshot = Field(default_factory=RuntimeSnapshot)
    security: SecuritySnapshot = Field(default_factory=SecuritySnapshot)


class SupportContact(BaseModel):
    """Where people get help: the address a deployment sets (SUPPORT_CONTACT)."""

    #: As written in the setting: an email address or a web address. None when unset.
    contact: str | None = None
    #: What a link to it opens: a `mailto:` for an email, the web address itself.
    href: str | None = None
    version: str


def support_contact(setting: str | None, version: str) -> SupportContact:
    """Reads SUPPORT_CONTACT. Anything that is neither an email nor a web address is ignored."""
    value = (setting or "").strip()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        return SupportContact(contact=value, href=f"mailto:{value}", version=version)
    if re.fullmatch(r"https?://\S+", value):
        return SupportContact(contact=value, href=value, version=version)
    return SupportContact(version=version)
