from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from service_schedules.due import (
    count_all_schedules,
    count_due_schedules,
    count_schedules_with_active_lease,
    count_stale_claimed_leases,
)
from service_schedules.scheduler_executor import run_due_schedules_once
from service_schedules.schemas import RunDueSchedulesSummary, SchedulerRuntimeStatusResponse


def build_internal_router(
    get_db: Callable[..., Session],
    get_storage_backend: Callable[..., Any],
    settings: Any,
) -> APIRouter:
    router = APIRouter(tags=["internal-scheduler"])

    def _require_token(x_internal_token: Annotated[str | None, Header()] = None) -> None:
        expected = getattr(settings, "scheduler_internal_token", None)
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Scheduler internal API is not configured (set SCHEDULER_INTERNAL_TOKEN).",
            )
        if not x_internal_token or not secrets.compare_digest(x_internal_token, expected):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal token.")

    @router.post("/internal/schedules/run-due-once", response_model=RunDueSchedulesSummary)
    def post_run_due_once(
        db: Session = Depends(get_db),
        storage_backend=Depends(get_storage_backend),
        _: None = Depends(_require_token),
    ) -> RunDueSchedulesSummary:
        return run_due_schedules_once(db, storage_backend=storage_backend, settings=settings)

    @router.get("/internal/schedules/runtime-status", response_model=SchedulerRuntimeStatusResponse)
    def get_runtime_status(
        db: Session = Depends(get_db),
        _: None = Depends(_require_token),
    ) -> SchedulerRuntimeStatusResponse:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        rid = getattr(settings, "scheduler_runtime_id", None)
        return SchedulerRuntimeStatusResponse(
            internal_api_configured=bool(getattr(settings, "scheduler_internal_token", None)),
            scheduler_runtime_id_configured=bool((rid or "").strip()),
            total_schedules=count_all_schedules(db),
            due_now_count=count_due_schedules(db, now_utc=now),
            lease_active_count=count_schedules_with_active_lease(db, now_utc=now),
            stale_lease_count=count_stale_claimed_leases(db, now_utc=now),
            note=(
                "Automatic runs use DB-backed leases (claim_owner_id / claim_expires_at). "
                "Set SCHEDULER_RUNTIME_ID per poller replica and SCHEDULER_CLAIM_TTL_SECONDS for stall recovery. "
                "This is not a full distributed coordinator (no Redis leader election)."
            ),
        )

    return router
