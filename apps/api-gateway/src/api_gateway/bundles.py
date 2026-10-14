"""Project bundles: a project's work in one file, and back (adoption-readiness A8, Y2).

A bundle holds a project's recipes, checks, metrics, charts, dashboards,
workflows and schedules, never its data or credentials. References between
things travel by name, as `{"$ref": "dataset", "name": "Orders"}`, so a
bundle moves between projects and between deployments:

- datasets, imports, destinations and connections are what a project
  already has; an import matches each by name in the target project, or the
  person chooses one (`mapping`, keyed `"dataset:Orders"`);
- recipes, checks, metrics and charts are made by the import itself and
  wired up in order (metrics, recipes, checks, charts, dashboards,
  workflows, schedules).

An item whose name the target project already uses is skipped and said so;
one whose required reference is missing is skipped with the reason. A
workflow task whose reference is missing is made empty, so the workflow
saves and says what the task still needs. The preview and the import are
the same plan, so what the preview says is what the import does.

This lives in the gateway because it spans services: each item is made
through its own service's create function, so every rule a service applies
to a hand-made item applies to an imported one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from shared_python.errors import ApplicationError, BadRequestError

FORMAT = "pipewright.bundle"
VERSION = 1

#: Keys whose value is one id, and the kind of thing it names.
REF_KEYS = {
    "dataset_id": "dataset",
    "baseline_dataset_id": "dataset",
    "right_dataset_id": "dataset",
    "other_dataset_id": "dataset",
    "pipeline_id": "recipe",
    "extraction_job_id": "import",
    "destination_id": "destination",
    "connection_id": "connection",
    "metric_id": "metric",
    "chart_id": "chart",
}
#: Keys whose value is a list of ids.
LIST_REF_KEYS = {"rule_ids": "check"}
#: Kinds the target project must already have (matched by name or chosen).
EXTERNAL = ("dataset", "import", "destination", "connection")
KIND_WORDS = {
    "dataset": "dataset", "import": "import", "destination": "destination", "connection": "connection",
    "recipe": "recipe", "check": "check", "metric": "metric", "chart": "chart",
}
SECTIONS = ("metrics", "recipes", "checks", "charts", "dashboards", "workflows", "schedules")
#: The `_models()` key for each section's own kind.
SECTION_MODEL = {
    "metrics": "metric", "recipes": "recipe", "checks": "check", "charts": "chart",
    "dashboards": "dashboards", "workflows": "workflows", "schedules": "schedules",
}
SECTION_WORDS = {
    "metrics": "metric", "recipes": "recipe", "checks": "check", "charts": "chart",
    "dashboards": "dashboard", "workflows": "workflow", "schedules": "schedule",
}


def _models() -> dict[str, Any]:
    from service_datasets.models import Dataset
    from service_destinations.models import DestinationConfig
    from service_extraction.models import ExtractionConnection, ExtractionJob
    from service_quality.models import DataQualityRule
    from service_reporting.models import Dashboard, Metric, SavedChart
    from service_schedules.models import ScheduledOperation
    from service_transformations.models import TransformationPipeline
    from service_workflows.models import Workflow

    return {
        "dataset": Dataset, "import": ExtractionJob, "destination": DestinationConfig,
        "connection": ExtractionConnection, "recipe": TransformationPipeline, "check": DataQualityRule,
        "metric": Metric, "chart": SavedChart, "dashboards": Dashboard, "workflows": Workflow,
        "schedules": ScheduledOperation,
    }


def _names(db: Session, model: Any, project_id: uuid.UUID) -> dict[uuid.UUID, str]:
    rows = db.execute(select(model.id, model.name).where(model.project_id == project_id)).all()
    return {row.id: row.name for row in rows}


# ------------------------------------------------------------------ export


def export_bundle(db: Session, project_id: uuid.UUID, current_user: UserRead) -> dict[str, Any]:
    """The project's work as a bundle. Reading it needs only a viewer."""
    from service_projects.contracts import ensure_owned_project
    from service_projects.models import Project
    from service_reporting.models import DashboardTile
    from service_workflows.models import WorkflowEdge, WorkflowNode

    ensure_owned_project(db, project_id, current_user.id)
    models = _models()
    names = {kind: _names(db, models[kind], project_id) for kind in KIND_WORDS}
    used: dict[str, set[str]] = {kind: set() for kind in EXTERNAL}

    def ref(kind: str, value: Any) -> dict[str, str] | None:
        try:
            name = names[kind].get(uuid.UUID(str(value)))
        except (ValueError, TypeError):
            return None
        if name is None:
            return None
        if kind in used:
            used[kind].add(name)
        return {"$ref": kind, "name": name}

    def to_refs(value: Any) -> Any:
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for key, item in value.items():
                if key in REF_KEYS and item:
                    out[key] = ref(REF_KEYS[key], item)
                elif key in LIST_REF_KEYS and isinstance(item, list):
                    out[key] = [r for r in (ref(LIST_REF_KEYS[key], each) for each in item) if r]
                else:
                    out[key] = to_refs(item)
            return out
        if isinstance(value, list):
            return [to_refs(item) for item in value]
        return value

    def rows(model: Any) -> list[Any]:
        return list(db.scalars(select(model).where(model.project_id == project_id).order_by(model.created_at)))

    bundle: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "source_project": (db.get(Project, project_id).name if db.get(Project, project_id) else None),
    }
    bundle["metrics"] = [
        {"name": m.name, "description": m.description, "dataset": ref("dataset", m.dataset_id),
         "aggregation": m.aggregation, "column": m.column, "formula": m.formula,
         "filters": m.filters_json or [], "dimensions": m.dimensions_json or []}
        for m in rows(models["metric"])
    ]
    bundle["recipes"] = [
        {"name": r.name, "description": r.description, "status": r.status,
         "base_dataset": ref("dataset", r.base_dataset_id), "steps": to_refs(r.steps_json or [])}
        for r in rows(models["recipe"])
    ]
    bundle["checks"] = [
        {"name": c.name, "description": c.description, "rule_type": c.rule_type, "severity": c.severity,
         "dataset": ref("dataset", c.dataset_id) if c.dataset_id else None,
         "config": to_refs(c.config_json or {}), "enabled": c.enabled}
        for c in rows(models["check"])
    ]
    bundle["charts"] = [
        {"name": c.name, "description": c.description, "chart_type": c.chart_type,
         "dataset": ref("dataset", c.dataset_id), "query": to_refs(c.query_json or {}),
         "options": c.options_json, "metric": ref("metric", c.metric_id) if c.metric_id else None}
        for c in rows(models["chart"])
    ]
    dashboards = []
    for d in rows(models["dashboards"]):
        tiles = db.scalars(select(DashboardTile).where(DashboardTile.dashboard_id == d.id).order_by(DashboardTile.position))
        dashboards.append({
            "name": d.name, "description": d.description, "filters": d.filters_json or [],
            "refresh_seconds": d.refresh_seconds,
            "tiles": [
                {"kind": t.kind, "chart": ref("chart", t.chart_id) if t.chart_id else None, "title": t.title,
                 "body": t.body, "position": t.position, "width": t.width, "height": t.height}
                for t in tiles
            ],
        })
    bundle["dashboards"] = dashboards
    workflows = []
    for w in rows(models["workflows"]):
        nodes = db.scalars(select(WorkflowNode).where(WorkflowNode.workflow_id == w.id).order_by(WorkflowNode.created_at))
        edges = db.scalars(select(WorkflowEdge).where(WorkflowEdge.workflow_id == w.id))
        workflows.append({
            "name": w.name, "description": w.description, "trigger_type": w.trigger_type,
            "cron_expression": w.cron_expression, "timezone": w.timezone,
            "default_parameters": w.default_parameters or {},
            "tasks": [
                {"node_key": n.node_key, "name": n.name, "node_type": n.node_type, "config": to_refs(n.config_json or {}),
                 "continue_on_failure": n.continue_on_failure, "retries": n.retries,
                 "retry_delay_seconds": n.retry_delay_seconds, "position_x": n.position_x, "position_y": n.position_y}
                for n in nodes
            ],
            "links": [{"from_node_key": e.from_node_key, "to_node_key": e.to_node_key, "condition": e.condition} for e in edges],
        })
    bundle["workflows"] = workflows
    bundle["schedules"] = [
        {"name": s.name, "description": s.description, "schedule_type": s.schedule_type,
         "cron_expression": s.cron_expression, "timezone": s.timezone, "enabled": s.enabled,
         "target": to_refs(s.target_config_json or {})}
        for s in rows(models["schedules"])
    ]
    # What the target project needs to have already, for the reader's benefit.
    bundle["needs"] = {kind: sorted(values) for kind, values in used.items() if values}
    return bundle


# ------------------------------------------------------------------ import


@dataclass
class Reference:
    kind: str
    name: str
    status: str  # matched | chosen | missing | made
    id: uuid.UUID | None = None
    used_by: list[str] = field(default_factory=list)


@dataclass
class Planned:
    section: str
    name: str
    action: str  # create | skip
    reason: str | None = None
    item: dict[str, Any] | None = None


@dataclass
class Plan:
    items: list[Planned]
    references: dict[tuple[str, str], Reference]


def _check_bundle(bundle: dict[str, Any]) -> None:
    if not isinstance(bundle, dict) or bundle.get("format") != FORMAT:
        raise BadRequestError("This is not a Pipewright bundle. Export one from a project's Settings.")
    if not isinstance(bundle.get("version"), int) or bundle["version"] > VERSION:
        raise BadRequestError(
            "This bundle was made by a newer version of Pipewright than this one, so it cannot be read here."
        )


def _refs_in(value: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        if "$ref" in value and "name" in value:
            return [(str(value["$ref"]), str(value["name"]))]
        for item in value.values():
            found.extend(_refs_in(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_refs_in(item))
    return found


def plan_import(
    db: Session, project_id: uuid.UUID, bundle: dict[str, Any], mapping: dict[str, str] | None = None
) -> Plan:
    """What an import would make and what it would match. Changes nothing."""
    _check_bundle(bundle)
    models = _models()
    existing = {kind: {name.casefold(): (id_, name) for id_, name in _names(db, models[kind], project_id).items()}
                for kind in (*EXTERNAL, "recipe", "check", "metric", "chart")}
    taken = {
        section: {name.casefold() for name in _names(db, models[SECTION_MODEL[section]], project_id).values()}
        for section in SECTIONS
    }
    mapping = dict(mapping or {})
    made_by_bundle = {
        (SECTION_MODEL[section], str(item.get("name", "")).casefold())
        for section in ("metrics", "recipes", "checks", "charts") for item in bundle.get(section) or []
    }

    references: dict[tuple[str, str], Reference] = {}

    def reference(kind: str, name: str) -> Reference:
        key = (kind, name.casefold())
        if key in references:
            return references[key]
        chosen = mapping.get(f"{kind}:{name}")
        if chosen:
            try:
                chosen_id = uuid.UUID(str(chosen))
            except ValueError as exc:
                raise BadRequestError(f"The {KIND_WORDS.get(kind, kind)} chosen for “{name}” is not recognised.") from exc
            mine = {id_ for id_, _ in existing.get(kind, {}).values()}
            if chosen_id not in mine:
                raise BadRequestError(f"The {KIND_WORDS.get(kind, kind)} chosen for “{name}” is not in this project.")
            references[key] = Reference(kind, name, "chosen", chosen_id)
        elif kind in existing and name.casefold() in existing[kind]:
            references[key] = Reference(kind, name, "matched", existing[kind][name.casefold()][0])
        elif (kind, name.casefold()) in made_by_bundle:
            references[key] = Reference(kind, name, "made")
        else:
            references[key] = Reference(kind, name, "missing")
        return references[key]

    items: list[Planned] = []
    for section in SECTIONS:
        for raw in bundle.get(section) or []:
            name = str(raw.get("name") or "").strip()
            if not name:
                items.append(Planned(section, "(no name)", "skip", "It has no name."))
                continue
            if name.casefold() in taken[section]:
                items.append(Planned(section, name, "skip", f"This project already has a {SECTION_WORDS[section]} called “{name}”."))
                continue
            refs = [reference(kind, ref_name) for kind, ref_name in _refs_in(raw)]
            for ref_ in refs:
                ref_.used_by.append(f"{SECTION_WORDS[section]} “{name}”")
            # In a workflow a missing reference leaves its task to be filled in;
            # anywhere else the item cannot work without it.
            missing = [r for r in refs if r.status == "missing"]
            if missing and section != "workflows":
                first = missing[0]
                items.append(Planned(section, name, "skip",
                                     f"It needs the {KIND_WORDS.get(first.kind, first.kind)} “{first.name}”, which this project does not have."))
                continue
            # A dataset here (matched or chosen) must have the columns the item
            # reads, or it would be made and then fail when opened.
            lacking = _lacking_columns(db, section, raw, references)
            if lacking:
                dataset_name, columns = lacking
                items.append(Planned(section, name, "skip",
                                     f"“{dataset_name}” has no column {_listing(columns)}, which it uses."))
                continue
            items.append(Planned(section, name, "create", item=raw))
    # A reference to something the bundle makes but skipped is missing after all.
    created = {(p.section, p.name.casefold()) for p in items if p.action == "create"}
    section_of = {kind: section for section, kind in SECTION_MODEL.items()}
    for ref_ in references.values():
        if ref_.status == "made" and (section_of[ref_.kind], ref_.name.casefold()) not in created:
            ref_.status = "missing"
    return Plan(items=items, references=references)


def _columns_used(section: str, item: dict[str, Any]) -> set[str]:
    """The columns of its dataset an item reads, where they can be named."""
    used: set[str] = set()
    if section == "metrics":
        used.update(filter(None, [item.get("column")]))
        used.update(str(d) for d in item.get("dimensions") or [])
        used.update(str(f.get("column")) for f in item.get("filters") or [] if isinstance(f, dict) and f.get("column"))
    elif section == "charts":
        query = item.get("query") or {}
        used.update(str(d) for d in query.get("dimensions") or [])
        used.update(str(m.get("column")) for m in query.get("measures") or [] if isinstance(m, dict) and m.get("column"))
        used.update(str(f.get("column")) for f in query.get("filters") or [] if isinstance(f, dict) and f.get("column"))
    elif section == "checks":
        config = item.get("config") or {}
        used.update(filter(None, [config.get("column")]))
        used.update(str(c) for c in config.get("columns") or [])
    return {column for column in used if column and column != "*"}


def _lacking_columns(
    db: Session, section: str, item: dict[str, Any], references: dict[tuple[str, str], Reference]
) -> tuple[str, list[str]] | None:
    dataset = item.get("dataset")
    if not isinstance(dataset, dict) or section not in ("metrics", "charts", "checks"):
        return None
    ref_ = references.get(("dataset", str(dataset.get("name", "")).casefold()))
    if ref_ is None or ref_.id is None:
        return None
    from service_datasets.models import Dataset

    row = db.get(Dataset, ref_.id)
    schema = (row.schema_json or {}).get("columns") if row is not None else None
    if not schema:
        return None  # nothing recorded to compare with; the service decides
    have = {str(column.get("name")) for column in schema}
    lacking = sorted(_columns_used(section, item) - have)
    return (row.name, lacking) if lacking else None


def _listing(names: list[str]) -> str:
    quoted = [f"“{name}”" for name in names]
    return quoted[0] if len(quoted) == 1 else ", ".join(quoted[:-1]) + f" or {quoted[-1]}"


def apply_import(
    db: Session, project_id: uuid.UUID, bundle: dict[str, Any], current_user: UserRead,
    mapping: dict[str, str] | None = None,
) -> tuple[Plan, list[dict[str, Any]]]:
    """Make what the plan says, in order. Returns the plan and what was made."""
    from service_projects.contracts import ensure_owned_project

    ensure_owned_project(db, project_id, current_user.id)
    plan = plan_import(db, project_id, bundle, mapping)
    made_ids: dict[tuple[str, str], uuid.UUID] = {}
    made: list[dict[str, Any]] = []

    def resolve(value: Any) -> Any:
        if isinstance(value, dict):
            if "$ref" in value and "name" in value:
                kind, name = str(value["$ref"]), str(value["name"])
                ref_ = plan.references.get((kind, name.casefold()))
                if ref_ is None:
                    return None
                found = ref_.id or made_ids.get((kind, name.casefold()))
                return str(found) if found else None
            out: dict[str, Any] = {}
            for key, item in value.items():
                resolved = resolve(item)
                if key in LIST_REF_KEYS and isinstance(resolved, list):
                    resolved = [each for each in resolved if each]
                out[key] = resolved
            return out
        if isinstance(value, list):
            return [resolve(item) for item in value]
        return value

    for planned in plan.items:
        if planned.action != "create" or planned.item is None:
            continue
        try:
            new_id = _make(db, project_id, planned.section, resolve(planned.item), current_user)
        except ApplicationError as exc:
            db.rollback()
            planned.action, planned.reason = "skip", f"Not made: {exc.detail}"
            continue
        kind = SECTION_MODEL[planned.section]
        if kind in KIND_WORDS:
            made_ids[(kind, planned.name.casefold())] = new_id
        made.append({"section": planned.section, "name": planned.name, "id": str(new_id)})
    return plan, made


def _make(db: Session, project_id: uuid.UUID, section: str, item: dict[str, Any], user: UserRead) -> uuid.UUID:
    """One item, through its own service's create function."""
    if section == "metrics":
        from service_reporting.metrics import create_metric
        from service_reporting.schemas import MetricCreate

        return create_metric(db, project_id, MetricCreate(
            dataset_id=item["dataset"], name=item["name"], description=item.get("description"),
            aggregation=item.get("aggregation") or "sum", column=item.get("column"), formula=item.get("formula"),
            filters=item.get("filters") or [], dimensions=item.get("dimensions") or [],
        ), user).id
    if section == "recipes":
        from service_transformations.schemas import TransformationPipelineCreate
        from service_transformations.service import create_transformation_pipeline

        return create_transformation_pipeline(
            db, project_id=project_id, dataset_id=uuid.UUID(item["base_dataset"]),
            payload=TransformationPipelineCreate(
                name=item["name"], description=item.get("description"), status=item.get("status") or "draft",
                steps_json=item.get("steps") or [],
            ),
            current_user=user,
        ).id
    if section == "checks":
        from service_quality.schemas import DataQualityRuleCreate
        from service_quality.service import create_rule

        return create_rule(db, project_id, DataQualityRuleCreate(
            name=item["name"], description=item.get("description"), rule_type=item["rule_type"],
            severity=item.get("severity") or "error", dataset_id=item.get("dataset"), config=item.get("config") or {},
        ), user).id
    if section == "charts":
        from service_reporting.schemas import ChartCreate, QueryInput
        from service_reporting.service import create_chart

        return create_chart(db, project_id, ChartCreate(
            dataset_id=item["dataset"], name=item["name"], description=item.get("description"),
            chart_type=item.get("chart_type") or "bar", query=QueryInput.model_validate(item.get("query") or {}),
            options=item.get("options"), metric_id=item.get("metric"),
        ), user).id
    if section == "dashboards":
        from service_reporting.schemas import DashboardCreate, TileInput
        from service_reporting.service import create_dashboard

        tiles = [
            TileInput(kind=tile.get("kind") or "chart", chart_id=tile.get("chart"), title=tile.get("title"),
                      body=tile.get("body"), position=tile.get("position"), width=tile.get("width") or 6,
                      height=tile.get("height") or 1)
            for tile in item.get("tiles") or []
            if (tile.get("kind") or "chart") != "chart" or tile.get("chart")
        ]
        return create_dashboard(db, project_id, DashboardCreate(
            name=item["name"], description=item.get("description"), tiles=tiles,
            filters=item.get("filters") or [], refresh_seconds=item.get("refresh_seconds"),
        ), user).id
    if section == "workflows":
        from service_workflows.schemas import WorkflowCreate, WorkflowEdgeInput, WorkflowNodeInput
        from service_workflows.service import create_workflow

        return create_workflow(db, project_id, WorkflowCreate(
            name=item["name"], description=item.get("description"),
            trigger_type=item.get("trigger_type") or "manual", cron_expression=item.get("cron_expression"),
            timezone=item.get("timezone"), default_parameters=item.get("default_parameters") or {},
            nodes=[
                WorkflowNodeInput(
                    node_key=task["node_key"], name=task["name"], node_type=task["node_type"],
                    config={key: value for key, value in (task.get("config") or {}).items() if value is not None},
                    continue_on_failure=bool(task.get("continue_on_failure")), retries=int(task.get("retries") or 0),
                    retry_delay_seconds=int(task.get("retry_delay_seconds") or 30),
                    position_x=float(task.get("position_x") or 0), position_y=float(task.get("position_y") or 0),
                )
                for task in item.get("tasks") or []
            ],
            edges=[WorkflowEdgeInput(**link) for link in item.get("links") or []],
        ), user).id
    if section == "schedules":
        from service_schedules.schemas import ScheduledOperationCreate
        from service_schedules.service import create_schedule

        return create_schedule(db, project_id=project_id, payload=ScheduledOperationCreate(
            name=item["name"], description=item.get("description"), schedule_type=item["schedule_type"],
            cron_expression=item["cron_expression"], timezone=item.get("timezone"),
            enabled=bool(item.get("enabled", True)), target_config=item.get("target") or {},
        ), current_user=user).id
    raise BadRequestError(f"Unknown section {section}.")


# ------------------------------------------------------------------ API


def _option_lists(db: Session, project_id: uuid.UUID, kinds: set[str]) -> dict[str, list[dict[str, str]]]:
    models = _models()
    return {
        kind: [{"id": str(id_), "name": name} for id_, name in sorted(_names(db, models[kind], project_id).items(), key=lambda pair: pair[1].casefold())]
        for kind in kinds if kind in EXTERNAL
    }


def preview_payload(db: Session, project_id: uuid.UUID, plan: Plan) -> dict[str, Any]:
    references = sorted(plan.references.values(), key=lambda ref: (ref.kind, ref.name.casefold()))
    missing_kinds = {ref.kind for ref in references if ref.status == "missing"}
    return {
        "items": [
            {"section": p.section, "kind": SECTION_WORDS[p.section], "name": p.name, "action": p.action, "reason": p.reason}
            for p in plan.items
        ],
        "references": [
            {"kind": ref.kind, "name": ref.name, "status": ref.status, "id": str(ref.id) if ref.id else None,
             "used_by": sorted(set(ref.used_by))}
            for ref in references
        ],
        "choices": _option_lists(db, project_id, missing_kinds | {ref.kind for ref in references if ref.status == "chosen"}),
        "creates": sum(1 for p in plan.items if p.action == "create"),
        "skips": sum(1 for p in plan.items if p.action == "skip"),
    }


class BundleRequest(BaseModel):
    bundle: dict[str, Any]
    #: Choices for references the target project lacks: {"dataset:Orders": "<dataset id>"}.
    mapping: dict[str, str] = Field(default_factory=dict)

class BundleItem(BaseModel):
    section: str
    kind: str
    name: str
    action: str
    reason: str | None = None

class BundleReference(BaseModel):
    kind: str
    name: str
    status: str
    id: str | None = None
    used_by: list[str]

class BundlePreview(BaseModel):
    items: list[BundleItem]
    references: list[BundleReference]
    choices: dict[str, list[dict[str, str]]]
    creates: int
    skips: int

class BundleMade(BaseModel):
    section: str
    name: str
    id: str

class BundleImportResult(BundlePreview):
    made: list[BundleMade]


def build_bundles_router(get_db: Any, get_current_user: Any) -> Any:
    from fastapi import APIRouter, Body, Depends

    router = APIRouter(tags=["bundles"])

    @router.get("/projects/{project_id}/bundle")
    def get_bundle(
        project_id: uuid.UUID, db: Session = Depends(get_db), current_user: UserRead = Depends(get_current_user)
    ) -> JSONResponse:
        """The project's recipes, checks, metrics, charts, dashboards, workflows and
        schedules as one file. Never its data or credentials."""
        bundle = export_bundle(db, project_id, current_user)
        stem = "".join(ch if ch.isalnum() else "-" for ch in (bundle.get("source_project") or "project")).strip("-").lower()
        return JSONResponse(
            bundle, headers={"Content-Disposition": f'attachment; filename="{stem or "project"}-bundle.json"'}
        )

    @router.post("/projects/{project_id}/bundle/preview", response_model=BundlePreview)
    def post_bundle_preview(
        project_id: uuid.UUID, payload: BundleRequest = Body(...), db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> dict[str, Any]:
        """What importing the bundle would make, match and skip. Changes nothing."""
        from service_projects.contracts import ensure_owned_project

        ensure_owned_project(db, project_id, current_user.id)
        return preview_payload(db, project_id, plan_import(db, project_id, payload.bundle, payload.mapping))

    @router.post("/projects/{project_id}/bundle/import", response_model=BundleImportResult)
    def post_bundle_import(
        project_id: uuid.UUID, payload: BundleRequest = Body(...), db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Make what the preview showed."""
        plan, made = apply_import(db, project_id, payload.bundle, current_user, payload.mapping)
        return {**preview_payload(db, project_id, plan), "made": made}

    return router
