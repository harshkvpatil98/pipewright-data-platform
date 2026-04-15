from __future__ import annotations

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


class PlatformStatus(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    service: str
    environment: str
    version: str
    services: list[ServiceStatus]
    checked_at: str = Field(description="ISO 8601 UTC timestamp when this snapshot was assembled.")
    scheduler: SchedulerOperationalSnapshot
