from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from service_auth.status import get_service_status as get_auth_status
from service_comparisons.status import get_service_status as get_comparisons_status
from service_datasets.status import get_service_status as get_datasets_status
from service_destinations.status import get_service_status as get_destinations_status
from service_ingestion.status import get_service_status as get_ingestion_status
from service_notifications.status import get_service_status as get_notifications_status
from service_pipeline_runs.status import get_service_status as get_pipeline_runs_status
from service_projects.status import get_service_status as get_projects_status
from service_schedules.due import (
    count_all_schedules,
    count_due_schedules,
    count_schedules_with_active_lease,
    count_stale_claimed_leases,
)
from service_schedules.status import get_service_status as get_schedules_status
from service_sources.status import get_service_status as get_sources_status
from service_transformations.status import get_service_status as get_transformations_status
from shared_python.db.health import is_database_ready
from shared_python.status import PlatformStatus, SchedulerOperationalSnapshot, ServiceStatus
from shared_python.status_redaction import redact_details


def collect_service_statuses(db: Session) -> list[ServiceStatus]:
    return [
        get_auth_status(db),
        get_projects_status(db),
        get_sources_status(db),
        get_datasets_status(db),
        get_destinations_status(db),
        get_ingestion_status(db),
        get_pipeline_runs_status(db),
        get_transformations_status(db),
        get_comparisons_status(db),
        get_schedules_status(db),
        get_notifications_status(db),
    ]


def _scheduler_snapshot(
    *,
    db: Session,
    internal_api_configured: bool,
    scheduler_runtime_id_configured: bool,
) -> SchedulerOperationalSnapshot:
    note = (
        "Due counts are reclaimable automatic work only (enabled, cron/retry due, lease clear or expired). "
        "POST /internal/schedules/run-due-once remains token-gated. "
        "Leases reduce duplicate automatic runs across concurrent pollers but are not global distributed locking; "
        "set SCHEDULER_RUNTIME_ID per replica and tune SCHEDULER_CLAIM_TTL_SECONDS for your runtime."
    )
    try:
        now = datetime.now(UTC)
        total = int(count_all_schedules(db))
        due = int(count_due_schedules(db, now_utc=now))
        active_lease = int(count_schedules_with_active_lease(db, now_utc=now))
        stale_lease = int(count_stale_claimed_leases(db, now_utc=now))
    except Exception:
        return SchedulerOperationalSnapshot(
            internal_api_configured=internal_api_configured,
            scheduler_runtime_id_configured=scheduler_runtime_id_configured,
            total_schedules=0,
            due_now_count=0,
            lease_active_count=0,
            stale_lease_count=0,
            note=note + " Schedule counters temporarily unavailable.",
        )
    return SchedulerOperationalSnapshot(
        internal_api_configured=internal_api_configured,
        scheduler_runtime_id_configured=scheduler_runtime_id_configured,
        total_schedules=total,
        due_now_count=due,
        lease_active_count=active_lease,
        stale_lease_count=stale_lease,
        note=note,
    )


def _sanitize_services(services: list[ServiceStatus]) -> list[ServiceStatus]:
    return [
        ServiceStatus(name=s.name, status=s.status, details=redact_details(dict(s.details)))
        for s in services
    ]


def platform_status(
    *,
    db: Session,
    service_name: str,
    environment: str,
    version: str,
    scheduler_internal_api_configured: bool,
    scheduler_runtime_id_configured: bool,
) -> PlatformStatus:
    services_raw = collect_service_statuses(db)
    database_status = "healthy" if is_database_ready(db) else "unhealthy"
    combined = [
        ServiceStatus(name="postgres", status=database_status, details={}),
        *_sanitize_services(services_raw),
    ]
    overall = "healthy" if all(item.status == "healthy" for item in combined) else "degraded"
    checked_at = datetime.now(UTC).isoformat()
    scheduler = _scheduler_snapshot(
        db=db,
        internal_api_configured=scheduler_internal_api_configured,
        scheduler_runtime_id_configured=scheduler_runtime_id_configured,
    )
    return PlatformStatus(
        status=overall,
        service=service_name,
        environment=environment,
        version=version,
        services=combined,
        checked_at=checked_at,
        scheduler=scheduler,
    )
