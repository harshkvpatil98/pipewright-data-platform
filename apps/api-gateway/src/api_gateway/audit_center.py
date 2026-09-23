"""The Audit Center: one cross-project stream of who did what.

The per-project audit log already existed; this is the governance view over all
of it. It is admin-only, because an audit trail that any user could read across
every project would itself be a privacy leak -- it names other people's actions.
The gateway composes it (audit store + project names + the role check together),
filters it, and exports it as CSV or JSON for an auditor who wants it offline.

Retention is enforced, not just displayed: `AUDIT_RETENTION_DAYS` prunes entries
past the window on the schedule ticker's sweep, and the window is surfaced in the
UI so the policy is visible rather than a surprise.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_governance.models import AuditEntry
from service_projects.models import Project
from shared_python.errors import ForbiddenError
from shared_python.logging import get_logger

logger = get_logger(__name__)

MAX_ROWS = 1000
DEFAULT_LIMIT = 100


class AuditCenterRow(BaseModel):
    id: str
    created_at: str
    actor_username: str | None
    project_id: str | None
    project_name: str | None
    method: str
    path: str
    action: str
    resource_type: str | None
    outcome: str
    status_code: int
    correlation_id: str | None


class AuditCenterResponse(BaseModel):
    items: list[AuditCenterRow]
    retention_days: int


def _require_admin(current_user: UserRead) -> None:
    if current_user.role != "admin":
        raise ForbiddenError("Only a platform admin can read the audit centre.")


def _query(
    *,
    outcome: str | None,
    actor: str | None,
    method: str | None,
    query: str | None,
    project_id: str | None,
    since_days: int | None,
    now: datetime,
):
    statement = select(AuditEntry, Project.name).outerjoin(
        Project, Project.id == AuditEntry.project_id
    )
    if outcome:
        statement = statement.where(AuditEntry.outcome == outcome)
    if method:
        statement = statement.where(AuditEntry.method == method.upper())
    if actor:
        statement = statement.where(AuditEntry.actor_username.ilike(f"%{actor.strip()}%"))
    if project_id:
        statement = statement.where(AuditEntry.project_id == project_id)
    if query and query.strip():
        needle = f"%{query.strip()}%"
        statement = statement.where(
            or_(AuditEntry.path.ilike(needle), AuditEntry.action.ilike(needle))
        )
    if since_days and since_days > 0:
        statement = statement.where(AuditEntry.created_at >= now - timedelta(days=since_days))
    return statement.order_by(AuditEntry.created_at.desc())


def _row(entry: AuditEntry, project_name: str | None) -> AuditCenterRow:
    created = entry.created_at
    return AuditCenterRow(
        id=str(entry.id),
        created_at=(created.isoformat() if created else ""),
        actor_username=entry.actor_username,
        project_id=str(entry.project_id) if entry.project_id else None,
        project_name=project_name,
        method=entry.method,
        path=entry.path,
        action=entry.action,
        resource_type=entry.resource_type,
        outcome=entry.outcome,
        status_code=entry.status_code,
        correlation_id=entry.correlation_id,
    )


def list_audit_entries(
    db: Session,
    *,
    current_user: UserRead,
    settings,
    outcome: str | None = None,
    actor: str | None = None,
    method: str | None = None,
    query: str | None = None,
    project_id: str | None = None,
    since_days: int | None = None,
    limit: int = DEFAULT_LIMIT,
    now: datetime | None = None,
) -> AuditCenterResponse:
    _require_admin(current_user)
    moment = now or datetime.now(UTC)
    limit = max(1, min(int(limit), MAX_ROWS))
    statement = _query(
        outcome=outcome, actor=actor, method=method, query=query,
        project_id=project_id, since_days=since_days, now=moment,
    ).limit(limit)
    rows = db.execute(statement).all()
    return AuditCenterResponse(
        items=[_row(entry, name) for entry, name in rows],
        retention_days=settings.audit_retention_days,
    )


def export_csv(
    db: Session,
    *,
    current_user: UserRead,
    settings,
    now: datetime | None = None,
    **filters,
) -> str:
    """The filtered stream as CSV for an offline auditor."""
    _require_admin(current_user)
    moment = now or datetime.now(UTC)
    statement = _query(now=moment, **_filter_kwargs(filters)).limit(MAX_ROWS)
    rows = db.execute(statement).all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["created_at", "actor", "project", "method", "path", "action", "outcome", "status_code", "correlation_id"]
    )
    for entry, name in rows:
        writer.writerow(
            [
                entry.created_at.isoformat() if entry.created_at else "",
                entry.actor_username or "",
                name or "",
                entry.method,
                entry.path,
                entry.action,
                entry.outcome,
                entry.status_code,
                entry.correlation_id or "",
            ]
        )
    return buffer.getvalue()


def _filter_kwargs(filters: dict) -> dict:
    return {
        "outcome": filters.get("outcome"),
        "actor": filters.get("actor"),
        "method": filters.get("method"),
        "query": filters.get("query"),
        "project_id": filters.get("project_id"),
        "since_days": filters.get("since_days"),
    }


def sweep_audit_entries(db: Session, *, retention_days: int, now: datetime | None = None) -> int:
    """Delete entries past the retention window. Zero keeps everything."""
    if retention_days <= 0:
        return 0
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    stale = list(db.scalars(select(AuditEntry).where(AuditEntry.created_at < cutoff)).all())
    for entry in stale:
        db.delete(entry)
    if stale:
        db.commit()
        logger.info("audit_sweep deleted=%s older_than_days=%s", len(stale), retention_days)
    return len(stale)


def total_audit_entries(db: Session) -> int:
    return db.scalar(select(func.count(AuditEntry.id))) or 0


def build_audit_center_router(get_db, get_current_user, settings):
    """Admin-only cross-project audit endpoints. Top-level (no {project_id}), so
    the project guard has nothing to gate; the admin check inside does the work."""
    from fastapi import APIRouter, Depends, Query
    from fastapi.responses import Response

    router = APIRouter(tags=["audit"])

    @router.get("/audits", response_model=AuditCenterResponse)
    def audits(
        outcome: str | None = Query(default=None),
        actor: str | None = Query(default=None),
        method: str | None = Query(default=None),
        q: str | None = Query(default=None),
        project_id: str | None = Query(default=None),
        since_days: int | None = Query(default=None, ge=0, le=3650),
        limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_ROWS),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> AuditCenterResponse:
        return list_audit_entries(
            db, current_user=current_user, settings=settings, outcome=outcome, actor=actor,
            method=method, query=q, project_id=project_id, since_days=since_days, limit=limit,
        )

    @router.get("/audits/export")
    def audits_export(
        format: str = Query(default="csv"),
        outcome: str | None = Query(default=None),
        actor: str | None = Query(default=None),
        method: str | None = Query(default=None),
        q: str | None = Query(default=None),
        project_id: str | None = Query(default=None),
        since_days: int | None = Query(default=None, ge=0, le=3650),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> Response:
        filters = dict(
            outcome=outcome, actor=actor, method=method, query=q,
            project_id=project_id, since_days=since_days,
        )
        if format == "json":
            payload = list_audit_entries(
                db, current_user=current_user, settings=settings, limit=MAX_ROWS, **filters
            )
            return Response(
                content=payload.model_dump_json(),
                media_type="application/json",
                headers={"Content-Disposition": "attachment; filename=audit-export.json"},
            )
        body = export_csv(db, current_user=current_user, settings=settings, **filters)
        return Response(
            content=body,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit-export.csv"},
        )

    return router
