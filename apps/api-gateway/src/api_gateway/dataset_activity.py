"""What happened to one dataset, newest first (roadmap Phase 21, C2).

A dataset's History page said where it came from; nothing said what had
happened to it since. This reads everything about one dataset into one
stream, the way the project's activity does for the project:

- versions: each new version, with what made it (an upload, a recipe run,
  an import, a rollback, an erasure) and how its rows changed;
- runs that tried to make a new version and failed (a broken contract
  stops one, for example), since a successful run is its version;
- checks: each time its checks ran, how many passed and failed;
- schema changes, contract problems and changes, alerts, incidents;
- comments and replies, saying which cell a thread is about;
- changes to its settings from the audit log (renamed, delivered...).

Paged by position, as the project's stream is, to `MAX_OFFSET`.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from api_gateway.activity import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MAX_OFFSET,
    RUN_WORDS,
    ActivityItem,
    Level,
    _href,
    _names,
    _utc,
)
from service_auth.schemas import UserRead
from service_governance.audit_words import object_names, summarise
from service_governance.models import AuditEntry, Comment
from service_projects.contracts import ensure_owned_project
from shared_python.words import count_of

DatasetKind = Literal[
    "versions", "runs", "checks", "schema", "contracts", "alerts", "incidents", "comments", "changes"
]


class DatasetActivityItem(ActivityItem):
    kind: DatasetKind  # type: ignore[assignment]


class DatasetActivityResponse(BaseModel):
    items: list[DatasetActivityItem]
    #: Pass as `offset` for the next, older page; null when there is no more.
    next_offset: int | None


def _signed(value: int) -> str:
    return f"+{value:,}" if value > 0 else f"−{abs(value):,}"


def _versions(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, limit: int) -> list[DatasetActivityItem]:
    from service_datasets.models import DatasetVersion
    from service_pipeline_runs.models import PipelineRun
    from service_transformations.models import TransformationPipeline

    rows = list(
        db.scalars(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id)
            .order_by(DatasetVersion.version_number.desc())
            .limit(limit + 1)
        ).all()
    )
    runs = {
        run.id: run
        for run in db.scalars(
            select(PipelineRun).where(PipelineRun.id.in_({row.pipeline_run_id for row in rows if row.pipeline_run_id} or {uuid.uuid4()}))
        ).all()
    }
    recipes = {
        recipe_id: name
        for recipe_id, name in db.execute(
            select(TransformationPipeline.id, TransformationPipeline.name).where(
                TransformationPipeline.id.in_({run.pipeline_id for run in runs.values() if run.pipeline_id} or {uuid.uuid4()})
            )
        ).all()
    }
    people = _names(db, {row.created_by_user_id for row in rows})
    items = []
    for index, row in enumerate(rows[:limit]):
        previous = rows[index + 1] if index + 1 < len(rows) else None
        run = runs.get(row.pipeline_run_id) if row.pipeline_run_id else None
        made_by = _made_by(row, run, recipes)
        sentence = f"Version {row.version_number}: {count_of(int(row.row_count or 0), 'row')}, {count_of(int(row.column_count or 0), 'column')}"
        changes = []
        if previous is not None and row.row_count is not None and previous.row_count is not None and row.row_count != previous.row_count:
            changes.append(f"{_signed(int(row.row_count) - int(previous.row_count))} rows")
        if (
            previous is not None
            and row.column_count is not None
            and previous.column_count is not None
            and row.column_count != previous.column_count
        ):
            moved = int(row.column_count) - int(previous.column_count)
            changes.append(f"{_signed(moved)} {'column' if abs(moved) == 1 else 'columns'}")
        if changes:
            sentence += f" ({', '.join(changes)})"
        items.append(
            DatasetActivityItem(
                # Numbered, so versions made in one moment still list newest first.
                id=f"version:{row.version_number:010d}:{row.id}",
                kind="versions",
                at=_utc(row.created_at),
                who=people.get(row.created_by_user_id),
                sentence=sentence,
                detail=made_by,
                level="info",
                href=_href(project_id, "runs/{id}/audit", run.id) if run is not None else None,
            )
        )
    return items


def _made_by(row, run, recipes: dict) -> str:
    name = (row.file_name or "").lower()
    if name.startswith("restored_v"):
        number = name.removeprefix("restored_v").split(".")[0]
        return f"Restored from version {number}"
    if name.startswith("corrected"):
        return "Corrected to erase a person's data"
    if run is None:
        return "Made from data saved here"
    word = RUN_WORDS.get(run.run_type, run.run_type.replace("_", " ").capitalize())
    summary = run.summary_json if isinstance(run.summary_json, dict) else {}
    if run.pipeline_id and run.pipeline_id in recipes:
        return f"{word}: {recipes[run.pipeline_id]}"
    job = summary.get("job") if isinstance(summary.get("job"), dict) else None
    if job and job.get("name"):
        return f"{word}: {job['name']}"
    return word


def _failed_runs(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, limit: int) -> list[DatasetActivityItem]:
    from service_extraction.models import ExtractionJob
    from service_pipeline_runs.models import PipelineRun
    from service_transformations.models import TransformationPipeline

    recipes = dict(
        db.execute(
            select(TransformationPipeline.id, TransformationPipeline.name).where(
                TransformationPipeline.project_id == project_id, TransformationPipeline.output_dataset_id == dataset_id
            )
        ).all()
    )
    jobs = dict(
        db.execute(
            select(ExtractionJob.id, ExtractionJob.name).where(
                ExtractionJob.project_id == project_id, ExtractionJob.target_dataset_id == dataset_id
            )
        ).all()
    )
    if not recipes and not jobs:
        return []
    candidates = db.scalars(
        select(PipelineRun)
        .where(PipelineRun.project_id == project_id, PipelineRun.status == "failed", PipelineRun.completed_at.is_not(None))
        .order_by(PipelineRun.completed_at.desc(), PipelineRun.id.desc())
        .limit(max(limit * 4, 200))
    ).all()
    people = _names(db, {run.triggered_by_user_id for run in candidates})
    items = []
    for run in candidates:
        summary = run.summary_json if isinstance(run.summary_json, dict) else {}
        job = summary.get("job") if isinstance(summary.get("job"), dict) else {}
        name = recipes.get(run.pipeline_id) if run.pipeline_id else None
        if name is None and job.get("id"):
            try:
                name = jobs.get(uuid.UUID(str(job["id"])))
            except ValueError:
                name = None
        if name is None:
            continue
        word = RUN_WORDS.get(run.run_type, run.run_type.replace("_", " ").capitalize())
        error = summary.get("error")
        items.append(
            DatasetActivityItem(
                id=f"run:{run.id}",
                kind="runs",
                at=_utc(run.completed_at),
                who=people.get(run.triggered_by_user_id),
                sentence=f"{word} failed: {name}",
                detail=str(error)[:300] if error else None,
                level="error",
                href=_href(project_id, "runs/{id}/audit", run.id),
            )
        )
        if len(items) >= limit:
            break
    return items


def _checks(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, limit: int) -> list[DatasetActivityItem]:
    from service_quality.models import DataQualityRunResult

    rows = db.execute(
        select(
            DataQualityRunResult.evaluation_id,
            func.max(DataQualityRunResult.created_at),
            func.count(DataQualityRunResult.id),
            func.sum(case((DataQualityRunResult.status == "failed", 1), else_=0)),
        )
        .where(DataQualityRunResult.project_id == project_id, DataQualityRunResult.dataset_id == dataset_id)
        .group_by(DataQualityRunResult.evaluation_id)
        .order_by(func.max(DataQualityRunResult.created_at).desc())
        .limit(limit)
    ).all()
    items = []
    for evaluation_id, at, total, failed in rows:
        failed = int(failed or 0)
        passed = int(total) - failed
        items.append(
            DatasetActivityItem(
                id=f"checks:{evaluation_id}",
                kind="checks",
                at=_utc(at),
                who=None,
                sentence=(
                    f"Checks ran: {count_of(failed, 'check')} failed, {passed:,} passed"
                    if failed
                    else f"Checks ran: all {count_of(passed, 'check')} passed"
                ),
                detail=None,
                level="error" if failed else "success",
                href=_href(project_id, "checks"),
            )
        )
    return items


def _schema(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, limit: int) -> list[DatasetActivityItem]:
    from service_quality.models import SchemaDriftEvent

    rows = db.scalars(
        select(SchemaDriftEvent)
        .where(SchemaDriftEvent.project_id == project_id, SchemaDriftEvent.dataset_id == dataset_id)
        .order_by(SchemaDriftEvent.created_at.desc(), SchemaDriftEvent.id.desc())
        .limit(limit)
    ).all()
    levels: dict[str, Level] = {"breaking": "error", "risky": "warning"}
    return [
        DatasetActivityItem(
            id=f"schema:{row.id}",
            kind="schema",
            at=_utc(row.created_at),
            who=None,
            sentence="Its columns changed at the source",
            detail=row.summary,
            level=levels.get(row.severity, "info"),
            href=_href(project_id, "schema-drift"),
        )
        for row in rows
    ]


def _contracts(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, limit: int) -> list[DatasetActivityItem]:
    from service_quality.models import DataContractEvent

    rows = db.scalars(
        select(DataContractEvent)
        .where(DataContractEvent.project_id == project_id, DataContractEvent.dataset_id == dataset_id)
        .order_by(DataContractEvent.created_at.desc(), DataContractEvent.id.desc())
        .limit(limit)
    ).all()
    levels: dict[str, Level] = {"broken": "error", "overdue": "warning", "kept": "success"}
    return [
        DatasetActivityItem(
            id=f"contract:{row.id}",
            kind="contracts",
            at=_utc(row.created_at),
            who=None,
            sentence=row.title,
            detail=row.message,
            level=levels.get(row.kind, "info"),
            href=_href(project_id, "datasets/{id}/contract", dataset_id),
        )
        for row in rows
    ]


def _alerts(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, limit: int) -> list[DatasetActivityItem]:
    from service_observability.models import MetricAlertEvent

    rows = db.scalars(
        select(MetricAlertEvent)
        .where(MetricAlertEvent.project_id == project_id, MetricAlertEvent.dataset_id == dataset_id)
        .order_by(MetricAlertEvent.created_at.desc(), MetricAlertEvent.id.desc())
        .limit(limit)
    ).all()
    return [
        DatasetActivityItem(
            id=f"alert:{row.id}",
            kind="alerts",
            at=_utc(row.created_at),
            who=None,
            sentence=row.title,
            detail=row.message,
            level="warning" if row.kind == "crossed" else "success",
            href=_href(project_id, "datasets/{id}/metrics", dataset_id),
        )
        for row in rows
    ]


def _incidents(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, limit: int) -> list[DatasetActivityItem]:
    from api_gateway.activity import INCIDENT_WORDS
    from service_observability.models import Incident, IncidentEvent

    rows = db.execute(
        select(IncidentEvent, Incident.title, Incident.severity)
        .join(Incident, Incident.id == IncidentEvent.incident_id)
        .where(
            IncidentEvent.project_id == project_id,
            Incident.dataset_id == dataset_id,
            IncidentEvent.kind.in_(tuple(INCIDENT_WORDS)),
        )
        .order_by(IncidentEvent.created_at.desc(), IncidentEvent.id.desc())
        .limit(limit)
    ).all()
    people = _names(db, {event.actor_user_id for event, _, _ in rows})
    items = []
    for event, title, severity in rows:
        who = people.get(event.actor_user_id)
        level: Level = (
            ("error" if severity in ("critical", "high") else "warning")
            if event.kind in ("opened", "reopened")
            else "success"
        )
        items.append(
            DatasetActivityItem(
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


def cell_words(anchor: dict | None) -> str:
    """"on amount, the row with order_id 1004" for a thread about a cell."""
    if not anchor:
        return ""
    column = anchor.get("column")
    if anchor.get("row_key_column"):
        return f" on {column}, the row with {anchor['row_key_column']} {anchor.get('row_key_value')}"
    if anchor.get("row_number"):
        return f" on {column}, row {anchor['row_number']} of version {anchor.get('version')}"
    return f" on {column}"


def _comments(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, limit: int) -> list[DatasetActivityItem]:
    rows = db.scalars(
        select(Comment)
        .where(Comment.project_id == project_id, Comment.target_type == "dataset", Comment.target_id == dataset_id)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(limit)
    ).all()
    roots = {
        row.id: row
        for row in db.scalars(
            select(Comment).where(Comment.id.in_({row.parent_id for row in rows if row.parent_id} or {uuid.uuid4()}))
        ).all()
    }
    people = _names(db, {row.author_user_id for row in rows})
    items = []
    for row in rows:
        who = people.get(row.author_user_id) or "Someone"
        root = roots.get(row.parent_id) if row.parent_id else None
        anchor = (root or row).anchor_json
        body = " ".join(row.body.split())
        items.append(
            DatasetActivityItem(
                id=f"comment:{row.id}",
                kind="comments",
                at=_utc(row.created_at),
                who=people.get(row.author_user_id),
                sentence=f"{who} {'replied' if root is not None else 'commented'}{cell_words(anchor)}",
                detail=f"“{body[:200]}{'…' if len(body) > 200 else ''}”",
                level="info",
                href=_href(project_id, "datasets/{id}", dataset_id),
            )
        )
    return items


#: Audit-log changes another source already says, in its own words.
_SAID_ELSEWHERE = ("/rollback", "/contract", "/contract/check", "/discussion")


def _changes(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, limit: int) -> list[DatasetActivityItem]:
    rows = [
        row
        for row in db.scalars(
            select(AuditEntry)
            .where(
                AuditEntry.project_id == project_id,
                AuditEntry.outcome == "succeeded",
                AuditEntry.path.like(f"%/datasets/{dataset_id}%"),
            )
            .order_by(AuditEntry.created_at.desc(), AuditEntry.id.desc())
            .limit(limit * 2)
        ).all()
        if not row.path.rstrip("/").endswith(_SAID_ELSEWHERE)
    ][:limit]
    things = object_names(db, rows)
    people = _names(db, {row.actor_user_id for row in rows})
    return [
        DatasetActivityItem(
            id=f"change:{row.id}",
            kind="changes",
            at=_utc(row.created_at),
            who=people.get(row.actor_user_id) or row.actor_username,
            sentence=f"{people.get(row.actor_user_id) or row.actor_username or 'Someone'} {summarise(row.method, row.path)}",
            detail=things.get(row.id),
            level="info",
            href=None,
        )
        for row in rows
    ]


SOURCES = (_versions, _failed_runs, _checks, _schema, _contracts, _alerts, _incidents, _comments, _changes)


def dataset_activity(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    current_user: UserRead,
    *,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
) -> DatasetActivityResponse:
    from service_datasets.service import get_dataset_model_for_project

    ensure_owned_project(db, project_id, current_user.id)
    get_dataset_model_for_project(db, project_id, dataset_id)
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, min(offset, MAX_OFFSET))
    wanted = offset + limit + 1
    items = [item for source in SOURCES for item in source(db, project_id, dataset_id, wanted)]
    items.sort(key=lambda item: (item.at, item.id), reverse=True)
    page = items[offset : offset + limit]
    more = len(items) > offset + limit and offset + limit < MAX_OFFSET
    return DatasetActivityResponse(items=page, next_offset=offset + limit if more else None)
