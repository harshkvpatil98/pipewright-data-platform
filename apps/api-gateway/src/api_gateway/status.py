from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_access.status import get_service_status as get_access_status
from service_auth.status import get_service_status as get_auth_status
from service_comparisons.status import get_service_status as get_comparisons_status
from service_connectors.status import get_service_status as get_connectors_status
from service_datasets.status import get_service_status as get_datasets_status
from service_destinations.status import get_service_status as get_destinations_status
from service_enterprise.status import get_service_status as get_enterprise_status
from service_extraction.status import get_service_status as get_extraction_status
from service_governance.status import get_service_status as get_governance_status
from service_ingestion.status import get_service_status as get_ingestion_status
from service_intelligence.status import get_service_status as get_intelligence_status
from service_lineage.status import get_service_status as get_lineage_status
from service_notifications.status import get_service_status as get_notifications_status
from service_observability.status import get_service_status as get_observability_status
from service_pipeline_runs.status import get_service_status as get_pipeline_runs_status
from service_projects.status import get_service_status as get_projects_status
from service_quality.status import get_service_status as get_quality_status
from service_reporting.status import get_service_status as get_reporting_status
from service_schedules.due import (
    count_all_schedules,
    count_due_schedules,
    count_schedules_with_active_lease,
    count_stale_claimed_leases,
)
from service_observability.runtime import EXPECTED_COMPONENTS, runtime_components
from service_schedules.status import get_service_status as get_schedules_status
from service_sources.status import get_service_status as get_sources_status
from service_transformations.status import get_service_status as get_transformations_status
from service_workflows.status import get_service_status as get_workflows_status
from service_workbench.status import get_service_status as get_workbench_status
from service_writeback.status import get_service_status as get_writeback_status
from shared_python.db.health import is_database_ready
from shared_python.status import (
    Ceiling,
    PlatformStatus,
    RuntimeComponentHeartbeat,
    RuntimeSnapshot,
    SchedulerOperationalSnapshot,
    SecuritySnapshot,
    ServiceStatus,
)
from shared_python.status_redaction import redact_details


def collect_service_statuses(db: Session) -> list[ServiceStatus]:
    return [
        get_auth_status(db),
        get_projects_status(db),
        get_access_status(db),
        get_enterprise_status(db),
        get_governance_status(db),
        get_sources_status(db),
        get_connectors_status(db),
        get_datasets_status(db),
        get_destinations_status(db),
        get_ingestion_status(db),
        get_extraction_status(db),
        get_quality_status(db),
        get_pipeline_runs_status(db),
        get_transformations_status(db),
        get_workflows_status(db),
        get_writeback_status(db),
        get_workbench_status(db),
        get_lineage_status(db),
        get_intelligence_status(db),
        get_observability_status(db),
        get_reporting_status(db),
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


def _runtime_snapshot(db: Session) -> RuntimeSnapshot:
    """Heartbeat-based ground truth. Never let a runtime read fail the whole
    status endpoint -- degrade to an empty (unhealthy) snapshot instead."""
    try:
        entries = runtime_components(db)
    except Exception:
        return RuntimeSnapshot(components=[], healthy=False)
    components = [RuntimeComponentHeartbeat(**entry) for entry in entries]
    expected = set(EXPECTED_COMPONENTS)
    healthy_by_component: dict[str, bool] = {}
    for component in components:
        # A component is satisfied if *any* of its hosts has a fresh beat.
        healthy_by_component[component.component] = (
            healthy_by_component.get(component.component, False) or component.healthy
        )
    healthy = bool(expected) and all(healthy_by_component.get(name, False) for name in expected)
    return RuntimeSnapshot(components=components, healthy=healthy)


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
    security: SecuritySnapshot | None = None,
    ceilings: list[Ceiling] | None = None,
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
        runtime=_runtime_snapshot(db),
        security=security or SecuritySnapshot(),
        ceilings=ceilings or [],
    )


def security_snapshot(db: Session, settings) -> SecuritySnapshot:
    """What is switched on, read from the settings and the organisations table."""
    from service_enterprise.models import Organisation

    try:
        organisations = db.scalars(select(Organisation.allowed_networks_json)).all()
        restricted = sum(1 for networks in organisations if networks)
    except Exception:  # noqa: BLE001 - status must answer even when a table is missing
        restricted = 0
    return SecuritySnapshot(
        files_encrypted_at_rest=bool(getattr(settings, "storage_encryption_key", None)),
        idle_timeout_minutes=int(settings.auth_access_token_exp_minutes),
        session_limit_hours=int(settings.auth_session_max_hours),
        organisations_with_network_lists=restricted,
        sso_configured=bool(getattr(settings, "oidc_issuer", None) and getattr(settings, "oidc_client_id", None)),
        trusted_proxy_hops=int(getattr(settings, "trusted_proxy_hops", 0) or 0),
        storage_backend=str(getattr(settings, "storage_backend", "local") or "local"),
    )


def _size(size_bytes: int) -> str:
    megabytes = size_bytes / (1024 * 1024)
    if megabytes >= 1024:
        return f"{megabytes / 1024:g} GB"
    return f"{megabytes:g} MB"


def ceilings(settings) -> list[Ceiling]:
    """The limits this server enforces, read from where each one is enforced (A7, X9).

    Each value comes from the setting or constant the code checks, never a
    copy of it, so this list cannot drift from what actually happens.
    """
    from service_destinations.copy_database import MAX_ROWS_PER_TABLE
    from service_pipeline_runs.limits import default_limit
    from shared_python.memory import run_memory_limit_mb
    from service_destinations.deliver import IN_REQUEST_ROWS
    from service_ingestion.service import IN_REQUEST_BYTES
    from service_extraction.schemas import ExtractionJobBase
    from service_workbench import sandbox
    from service_workbench.notebook import MAX_RUN_SECONDS
    from service_workbench.temporal import MAX_ROWS as SQL_ROWS
    from service_workflows.executor import MAX_RETRY_WAIT_SECONDS
    from service_workflows.schemas import MAX_RETRIES
    from shared_python import rate_limit
    from shared_python.words import count_of

    import_rows = next(
        (meta.le for meta in ExtractionJobBase.model_fields["max_rows"].metadata if getattr(meta, "le", None)),
        None,
    )
    sign_in = rate_limit.SIGN_IN_PER_ACCOUNT
    items = [
        Ceiling(
            name="Largest file you can upload",
            value=_size(int(settings.max_upload_size_bytes)),
            detail=(
                f"Files over {IN_REQUEST_BYTES // (1024 * 1024)} MB are read by the background worker, and the "
                "dataset page shows them being read. Bigger files can come in through a database or storage import."
            ),
            setting="MAX_UPLOAD_SIZE_BYTES",
        ),
        Ceiling(name="Rows shown in a preview", value=f"{int(settings.preview_row_limit):,}", setting="PREVIEW_ROW_LIMIT"),
        Ceiling(
            name="Rows one import brings in",
            value=f"Up to {import_rows:,}" if import_rows else "No fixed limit",
            detail="Each import sets its own limit below this.",
        ),
        Ceiling(
            name="Rows a delivery writes while you wait",
            value=f"{IN_REQUEST_ROWS:,}",
            detail="A larger dataset is delivered by the background worker, and the delivery window shows how far it has got.",
        ),
        Ceiling(
            name="Rows a database copy takes from each table",
            value=f"{MAX_ROWS_PER_TABLE:,}",
            detail="Copies run on the background worker, table by table, with progress.",
        ),
        Ceiling(name="Rows a SQL query over a version returns", value=f"{SQL_ROWS:,}"),
        Ceiling(
            name="Runs of one project at the same time",
            value=str(default_limit(settings)),
            detail=(
                "Recipes, imports, deliveries and workflows. Queued work waits its turn; a run started beyond it "
                "is refused with the reason. A project can set its own."
            ),
            setting="PROJECT_RUNS_AT_ONCE",
        ),
        Ceiling(
            name="Memory one run's data may take",
            value=f"{run_memory_limit_mb():,} MB",
            detail="A recipe whose data grows past it stops, naming the step and the size.",
            setting="RUN_MEMORY_LIMIT_MB",
        ),
        Ceiling(
            name="Tries for a failing workflow task",
            value=f"Up to {MAX_RETRIES + 1}",
            detail=f"Waits double between tries, up to {MAX_RETRY_WAIT_SECONDS // 60} minutes; set on each task.",
        ),
        Ceiling(
            name="A notebook's Python cell",
            value=f"{sandbox.DEFAULT_TIMEOUT_SECONDS} seconds, {sandbox.DEFAULT_MEMORY_MB} MB",
            detail=f"A whole notebook runs for at most {MAX_RUN_SECONDS} seconds.",
        ),
        Ceiling(
            name="Sign-in attempts",
            value=f"{count_of(sign_in.count, 'attempt')} in {sign_in.seconds // 60} minutes",
            detail="Per account and address; then the sign-in page says when to try again.",
        ),
        Ceiling(
            name="A shared dashboard link",
            value=f"{rate_limit.PUBLIC_DASHBOARD_PER_ADDRESS.count} loads a minute per address",
        ),
    ]
    return items
