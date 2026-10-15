"""What happened in a project, in one stream (adoption-readiness A8, Y6).

The audit log, the runs, incidents, comments and alerts each have their own
page, so "what happened while I was away?" took five of them. This reads
the five together, newest first, as sentences with who and when, and a link
to the thing each is about:

- changes: the audit log's sentences, for requests that succeeded (refused
  attempts stay in the audit log, where they belong);
- runs: uploads, imports, recipe runs and deliveries that finished or
  failed, and workflow runs;
- incidents: opened, reopened and resolved;
- comments, on anything that takes them;
- alerts: a measure crossing its line or coming back (Y5);
- contracts: a dataset's contract broken, overdue or kept again (C1); its
  changes are among the changes already.

Each source is read newest first, as far as the page needs, and the six
are merged, so a page costs a few indexed queries. Pages go back by
position (`offset`) rather than by time: items made in one moment, such as
two alerts from one capture, can never fall between two pages, and the
stream stops at MAX_OFFSET, where the audit log and runs pages go further.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.schemas import UserRead
from service_governance.audit_words import object_names, summarise, target_of
from service_governance.models import AuditEntry, Comment
from service_observability.models import Incident, IncidentEvent, MetricAlertEvent
from service_pipeline_runs.models import PipelineRun
from service_quality.models import DataContractEvent
from service_projects.contracts import ensure_owned_project
from service_workflows.models import Workflow, WorkflowRun
from shared_python.errors import BadRequestError

Kind = Literal["changes", "runs", "incidents", "comments", "alerts", "contracts", "live"]
KINDS: tuple[str, ...] = ("changes", "runs", "incidents", "comments", "alerts", "contracts", "live")
Level = Literal["info", "success", "warning", "error"]
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
#: How far back the stream pages; the audit log and runs pages go further.
MAX_OFFSET = 2000

# The web's words for a run (apps/web/src/lib/run-labels.ts).
RUN_WORDS = {
    "sample_orchestration": "Sample run",
    "dataset_ingestion": "File upload",
    "dataset_upload": "File upload",
    "database_extraction": "Import",
    "dataset_transformation": "Recipe run",
    "dataset_transformation_replay": "Recipe replay",
    "dataset_publish_postgres": "Delivery to PostgreSQL",
    "dataset_delivery": "Delivery",
    "database_copy": "Database copy",
    "dataset_publish_power_bi": "Sending to Power BI",
    "dataset_publish_tableau": "Sending to Tableau",
}

#: What a comment can be on, in words, and where it lives in the web.
COMMENT_TARGETS: dict[str, tuple[str, str | None]] = {
    "dataset": ("the dataset", "datasets/{id}"),
    "workflow": ("the workflow", "workflows/{id}"),
    "pipeline": ("the recipe", "pipelines/{id}"),
    "run": ("a run", "runs"),
    "incident": ("the incident", "incidents/{id}"),
    "change_request": ("the change", "changes"),
    "dashboard": ("the dashboard", "dashboards/{id}"),
    "chart": ("the chart", "charts"),
}

#: Where a changed thing lives in the web, by the noun in its API path.
CHANGE_PAGES: dict[str, str] = {
    "datasets": "datasets/{id}",
    "pipelines": "pipelines/{id}",
    "dashboards": "dashboards/{id}",
    "workflows": "workflows/{id}",
    "incidents": "incidents/{id}",
    "charts": "charts",
    "reports": "reports",
    "metrics": "metrics",
    "schedules": "schedules",
    "destinations": "destinations",
    "rules": "checks",
    "jobs": "sources",
    "connections": "sources",
    "changes": "changes",
    "notebooks": "notebooks",
    "queries": "workbench",
    "notification-targets": "notification-targets",
    "streams": "live/{id}",
}

COMMENT_TABLES = {
    "dataset": ("datasets", "name"),
    "workflow": ("workflows", "name"),
    "pipeline": ("transformation_pipelines", "name"),
    "incident": ("incidents", "title"),
    "change_request": ("change_requests", "title"),
    "dashboard": ("dashboards", "name"),
    "chart": ("saved_charts", "name"),
}


class ActivityItem(BaseModel):
    id: str
    kind: Kind
    at: datetime
    who: str | None
    #: "Ann deleted a dashboard", "Recipe run failed".
    sentence: str
    #: What it was about: a name, a quoted comment, an alert's message.
    detail: str | None
    level: Level
    #: The page in the web it is about, from the site's root.
    href: str | None


class ActivityResponse(BaseModel):
    items: list[ActivityItem]
    #: Pass as `offset` for the next, older page; null when there is no more here.
    next_offset: int | None


def _utc(moment: datetime) -> datetime:
    # SQLite hands back naive datetimes; they were written in UTC.
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _href(project_id: uuid.UUID, page: str | None, thing_id: Any = None) -> str | None:
    if page is None:
        return None
    return f"/projects/{project_id}/" + page.replace("{id}", str(thing_id))


def _names(db: Session, user_ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = {user_id for user_id in user_ids if user_id is not None}
    if not wanted:
        return {}
    rows = db.execute(select(User.id, User.display_name, User.username).where(User.id.in_(wanted))).all()
    return {row.id: row.display_name or row.username for row in rows}


def _changes(db: Session, project_id: uuid.UUID, limit: int) -> list[ActivityItem]:
    rows = db.scalars(
        select(AuditEntry)
        .where(AuditEntry.project_id == project_id, AuditEntry.outcome == "succeeded")
        .order_by(AuditEntry.created_at.desc(), AuditEntry.id.desc())
        .limit(limit)
    ).all()
    things = object_names(db, list(rows))
    people = _names(db, {row.actor_user_id for row in rows})
    items = []
    for row in rows:
        target = target_of(row)
        page = CHANGE_PAGES.get(target[0]) if target else None
        who = people.get(row.actor_user_id) or row.actor_username
        items.append(
            ActivityItem(
                id=f"change:{row.id}",
                kind="changes",
                at=_utc(row.created_at),
                who=who,
                sentence=f"{who or 'Someone'} {summarise(row.method, row.path)}",
                detail=things.get(row.id),
                level="info",
                href=_href(project_id, page, target[1]) if target and page else None,
            )
        )
    return items


def _runs(db: Session, project_id: uuid.UUID, limit: int) -> list[ActivityItem]:
    from service_transformations.models import TransformationPipeline

    runs = db.scalars(
        select(PipelineRun)
        .where(
            PipelineRun.project_id == project_id,
            PipelineRun.status.in_(("succeeded", "failed")),
            PipelineRun.completed_at.is_not(None),
        )
        .order_by(PipelineRun.completed_at.desc(), PipelineRun.id.desc())
        .limit(limit)
    ).all()
    flows = db.execute(
        select(WorkflowRun, Workflow.name)
        .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
        .where(
            WorkflowRun.project_id == project_id,
            WorkflowRun.finished_at.is_not(None),
        )
        .order_by(WorkflowRun.finished_at.desc(), WorkflowRun.id.desc())
        .limit(limit)
    ).all()
    recipes = {
        row.id: row.name
        for row in db.execute(
            select(TransformationPipeline.id, TransformationPipeline.name).where(
                TransformationPipeline.id.in_({run.pipeline_id for run in runs if run.pipeline_id} or {uuid.uuid4()})
            )
        ).all()
    }
    people = _names(db, {run.triggered_by_user_id for run in runs} | {run.triggered_by_user_id for run, _ in flows})

    items = []
    for run in runs:
        word = RUN_WORDS.get(run.run_type, run.run_type.replace("_", " ").capitalize())
        failed = run.status == "failed"
        summary = run.summary_json if isinstance(run.summary_json, dict) else {}
        made = summary.get("dataset") if isinstance(summary.get("dataset"), dict) else {}
        detail = recipes.get(run.pipeline_id) if run.pipeline_id else made.get("name") or summary.get("dataset_name")
        items.append(
            ActivityItem(
                id=f"run:{run.id}",
                kind="runs",
                at=_utc(run.completed_at),
                who=people.get(run.triggered_by_user_id),
                sentence=f"{word} {'failed' if failed else 'finished'}",
                detail=str(detail) if detail else None,
                level="error" if failed else "success",
                href=_href(project_id, "runs"),
            )
        )
    for run, name in flows:
        outcome = WORKFLOW_OUTCOMES.get(run.status, ("finished", "info"))
        items.append(
            ActivityItem(
                id=f"workflow-run:{run.id}",
                kind="runs",
                at=_utc(run.finished_at),
                who=people.get(run.triggered_by_user_id),
                sentence=f"Workflow {outcome[0]}",
                detail=name if run.status == "succeeded" or not run.error_message else f"{name}: {run.error_message[:200]}",
                level=outcome[1],
                href=_href(project_id, "workflows/{id}", run.workflow_id),
            )
        )
    return items


WORKFLOW_OUTCOMES: dict[str, tuple[str, Level]] = {
    "succeeded": ("finished", "success"),
    "failed": ("failed", "error"),
    "partial": ("finished with problems", "warning"),
    "cancelled": ("was cancelled", "info"),
}

INCIDENT_WORDS = {
    "opened": "An incident opened",
    "reopened": "{who} reopened an incident",
    "resolved": "{who} resolved an incident",
    "auto_resolved": "An incident closed by itself",
}


def _incidents(db: Session, project_id: uuid.UUID, limit: int) -> list[ActivityItem]:
    rows = db.execute(
        select(IncidentEvent, Incident.title, Incident.severity)
        .join(Incident, Incident.id == IncidentEvent.incident_id)
        .where(
            IncidentEvent.project_id == project_id,
            IncidentEvent.kind.in_(tuple(INCIDENT_WORDS)),
        )
        .order_by(IncidentEvent.created_at.desc(), IncidentEvent.id.desc())
        .limit(limit)
    ).all()
    people = _names(db, {event.actor_user_id for event, _, _ in rows})
    items = []
    for event, title, severity in rows:
        who = people.get(event.actor_user_id)
        if event.kind == "opened":
            level: Level = "error" if severity in ("critical", "high") else "warning"
        elif event.kind == "reopened":
            level = "warning"
        else:
            level = "success"
        items.append(
            ActivityItem(
                id=f"incident:{event.id}",
                kind="incidents",
                at=_utc(event.created_at),
                who=who,
                sentence=INCIDENT_WORDS[event.kind].format(who=who or "Someone"),
                detail=title,
                level=level,
                href=_href(project_id, "incidents/{id}", event.incident_id),
            )
        )
    return items


def _comments(db: Session, project_id: uuid.UUID, limit: int) -> list[ActivityItem]:
    from shared_python.db import Base

    rows = db.scalars(
        select(Comment)
        .where(Comment.project_id == project_id)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(limit)
    ).all()
    people = _names(db, {row.author_user_id for row in rows})
    titles: dict[tuple[str, uuid.UUID], str] = {}
    for target_type, (table_name, column) in COMMENT_TABLES.items():
        ids = {row.target_id for row in rows if row.target_type == target_type}
        table = Base.metadata.tables.get(table_name)
        if ids and table is not None:
            for thing_id, title in db.execute(select(table.c.id, table.c[column]).where(table.c.id.in_(ids))).all():
                titles[(target_type, thing_id)] = str(title)
    items = []
    for row in rows:
        words, page = COMMENT_TARGETS.get(row.target_type, ("something", None))
        title = titles.get((row.target_type, row.target_id))
        who = people.get(row.author_user_id) or "Someone"
        body = " ".join(row.body.split())
        items.append(
            ActivityItem(
                id=f"comment:{row.id}",
                kind="comments",
                at=_utc(row.created_at),
                who=people.get(row.author_user_id),
                sentence=f"{who} commented on {words}{f' {title}' if title else ''}",
                detail=f"“{body[:200]}{'…' if len(body) > 200 else ''}”",
                level="info",
                href=_href(project_id, page, row.target_id),
            )
        )
    return items


def _alerts(db: Session, project_id: uuid.UUID, limit: int) -> list[ActivityItem]:
    rows = db.scalars(
        select(MetricAlertEvent)
        .where(MetricAlertEvent.project_id == project_id)
        .order_by(MetricAlertEvent.created_at.desc(), MetricAlertEvent.id.desc())
        .limit(limit)
    ).all()
    return [
        ActivityItem(
            id=f"alert:{row.id}",
            kind="alerts",
            at=_utc(row.created_at),
            who=None,
            sentence=row.title,
            detail=row.message,
            level="warning" if row.kind == "crossed" else "success",
            href=_href(project_id, "datasets/{id}/metrics", row.dataset_id),
        )
        for row in rows
    ]


def _contracts(db: Session, project_id: uuid.UUID, limit: int) -> list[ActivityItem]:
    rows = db.scalars(
        select(DataContractEvent)
        .where(DataContractEvent.project_id == project_id, DataContractEvent.kind != "changed")
        .order_by(DataContractEvent.created_at.desc(), DataContractEvent.id.desc())
        .limit(limit)
    ).all()
    return [
        ActivityItem(
            id=f"contract:{row.id}",
            kind="contracts",
            at=_utc(row.created_at),
            who=None,
            sentence=row.title,
            detail=row.message,
            level="success" if row.kind == "kept" else "warning",
            href=_href(project_id, "datasets/{id}/contract", row.dataset_id),
        )
        for row in rows
    ]


def _live(db: Session, project_id: uuid.UUID, limit: int) -> list[ActivityItem]:
    """Live feeds that keep failing (from when their owner was told) and live
    recipes that stopped (D1). Each is shown while it lasts, not as a history."""
    from service_extraction.models import LiveRecipe, StreamSource

    failing = db.scalars(
        select(StreamSource)
        .where(StreamSource.project_id == project_id, StreamSource.failure_notified_at.is_not(None))
        .order_by(StreamSource.failure_notified_at.desc(), StreamSource.id.desc())
        .limit(limit)
    ).all()
    stopped = db.scalars(
        select(LiveRecipe)
        .where(LiveRecipe.project_id == project_id, LiveRecipe.status == "failed")
        .order_by(LiveRecipe.updated_at.desc(), LiveRecipe.id.desc())
        .limit(limit)
    ).all()
    items = [
        ActivityItem(
            id=f"live-feed:{row.id}",
            kind="live",
            at=_utc(row.failure_notified_at),
            who=None,
            sentence=f"{row.name} keeps failing",
            detail=(row.last_error or "")[:300] or None,
            level="error",
            href=_href(project_id, "live/{id}", row.id),
        )
        for row in failing
    ]
    items += [
        ActivityItem(
            id=f"live-recipe:{row.id}",
            kind="live",
            at=_utc(row.updated_at),
            who=None,
            sentence=f"The live recipe {row.name} stopped",
            detail=(row.last_error or "")[:300] or None,
            level="warning",
            href=_href(project_id, "live/{id}", row.source_id),
        )
        for row in stopped
    ]
    return items


SOURCES = {
    "changes": _changes,
    "runs": _runs,
    "incidents": _incidents,
    "comments": _comments,
    "alerts": _alerts,
    "contracts": _contracts,
    "live": _live,
}


def project_activity(
    db: Session,
    project_id: uuid.UUID,
    current_user: UserRead,
    *,
    kinds: list[str] | None = None,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> ActivityResponse:
    ensure_owned_project(db, project_id, current_user.id)
    chosen = kinds or list(KINDS)
    unknown = sorted(set(chosen) - set(KINDS))
    if unknown:
        raise BadRequestError(f"There is no “{unknown[0]}” activity. Choose from {', '.join(KINDS)}.")
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, min(offset, MAX_OFFSET))
    # One more than the page, to know whether another follows.
    wanted = offset + limit + 1
    items = [item for kind in KINDS if kind in chosen for item in SOURCES[kind](db, project_id, wanted)]
    # The same order every source was read in (time, then id), so a page
    # boundary falls in the same place whichever page asks.
    items.sort(key=lambda item: (item.at, item.id), reverse=True)
    page = items[offset : offset + limit]
    more = len(items) > offset + limit and offset + limit < MAX_OFFSET
    return ActivityResponse(items=page, next_offset=offset + limit if more else None)


def build_activity_router(get_db: Any, get_current_user: Any) -> Any:
    from fastapi import APIRouter, Depends, Query

    router = APIRouter(tags=["activity"])

    @router.get("/projects/{project_id}/activity", response_model=ActivityResponse)
    def read_project_activity(
        project_id: uuid.UUID,
        kind: list[str] | None = Query(default=None, description="changes, runs, incidents, comments or alerts"),
        offset: int = Query(0, ge=0, le=MAX_OFFSET, description="the next_offset of the page before"),
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ActivityResponse:
        """What happened in the project, newest first: changes, runs, incidents,
        comments and alerts, with who and when. Repeat `kind` to choose several."""
        return project_activity(db, project_id, current_user, kinds=kind, offset=offset, limit=limit)

    from api_gateway.dataset_activity import DatasetActivityResponse, dataset_activity

    @router.get("/projects/{project_id}/datasets/{dataset_id}/activity", response_model=DatasetActivityResponse)
    def read_dataset_activity(
        project_id: uuid.UUID,
        dataset_id: uuid.UUID,
        offset: int = Query(0, ge=0, le=MAX_OFFSET, description="the next_offset of the page before"),
        limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> DatasetActivityResponse:
        """What happened to one dataset, newest first: its versions and what made
        them, failed runs, checks, schema changes, contracts, alerts, incidents,
        comments and changes to it."""
        return dataset_activity(db, project_id, dataset_id, current_user, offset=offset, limit=limit)

    return router
