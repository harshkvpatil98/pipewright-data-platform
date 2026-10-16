"""Making a conversion in a project (E2, X3).

The datasets the work reads are matched by name among the project's (or
chosen), as a bundle's are; a seed is made from its file, unless the project
has a dataset of that name with the same columns, which is used. Then, in
order, each recipe is made and run (a later recipe reads what an earlier one
made), each check is made and run on its dataset, and each workflow is made
of the tasks whose recipes and checks exist. Every item goes through its own
service's create function, so the rules a hand-made item meets, an imported
one meets too.

An item whose name the project already uses is skipped and said so, and so
is anything that reads it; a recipe that did not convert completely is made
as a draft and never run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from shared_python.errors import ApplicationError, BadRequestError
from shared_python.types import PWType
from shared_python.words import count_of

from api_gateway.conversions.model import Conversion, Needed, RecipePlan


# ------------------------------------------------------------------ needs


@dataclass
class Resolver:
    """Which of the project's datasets each need is, as the conversion asks."""

    db: Session
    project_id: uuid.UUID
    reader: UserRead
    mapping: dict[str, str]
    #: need key -> (status, dataset or None, why)
    found: dict[str, tuple[str, Any, str | None]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        from service_datasets.models import Dataset

        self.datasets = {row.id: row for row in self.db.scalars(
            select(Dataset).where(Dataset.project_id == self.project_id).order_by(Dataset.created_at))}

    def __call__(self, need: Needed) -> dict[str, PWType] | None:
        chosen = self.mapping.get(need.key)
        if chosen:
            try:
                dataset = self.datasets.get(uuid.UUID(str(chosen)))
            except ValueError as exc:
                raise BadRequestError(f"The dataset chosen for {need.what} is not recognised.") from exc
            if dataset is None:
                raise BadRequestError(f"The dataset chosen for {need.what} is not in this project.")
            status = "chosen"
        else:
            named = [row for row in self.datasets.values() if (row.name or "").casefold() == need.name.casefold()]
            if len(named) != 1:
                why = (f"Several datasets here are called “{need.name}”; choose one." if named else
                       f"No dataset here is called “{need.name}”; choose the one that holds it.")
                self.found[need.key] = ("missing", None, why)
                return None
            dataset, status = named[0], "matched"
        self.found[need.key] = (status, dataset, None)
        return columns_of(self.db, self.project_id, dataset, self.reader)


def columns_of(db: Session, project_id: uuid.UUID, dataset, reader: UserRead) -> dict[str, PWType]:
    """A dataset's columns and their types, as this reader may know them."""
    from service_enterprise.policy_view import view_for
    from shared_python.types import parse
    from shared_python.types.lattice import UNKNOWN

    schema = dataset.schema_json or {}
    types = {}
    for column in schema.get("columns") or []:
        try:
            types[str(column.get("name"))] = parse(str(column.get("canonical_type") or "unknown"))
        except ValueError:
            types[str(column.get("name"))] = UNKNOWN
    names = [str(name) for name in schema.get("ordered_columns") or list(types)]
    visible = view_for(db, project_id, dataset.id, reader).visible_columns(names)
    return {name: types.get(name, UNKNOWN) for name in visible}


# ---------------------------------------------------------------- payload


def payload(conversion: Conversion, resolver: Resolver) -> dict[str, Any]:
    """What a conversion would make, what it reads, and its report."""
    needs = []
    for need in conversion.needs:
        status, dataset, why = resolver.found.get(need.key, ("missing", None, None))
        needs.append({"key": need.key, "name": need.name, "what": need.what, "columns": need.columns,
                      "status": status, "dataset_id": str(dataset.id) if dataset else None,
                      "dataset_name": dataset.name if dataset else None, "reason": why})
    counts = {"converted": 0, "not converted": 0, "nothing to do": 0}
    for section in conversion.sections:
        for entry in section.entries:
            counts[entry.status] += 1
    return {
        "format": conversion.format,
        "title": conversion.title,
        "needs": needs,
        "seeds": [{"key": seed.key, "name": seed.name, "what": seed.what, "file_name": seed.file_name}
                  for seed in conversion.seeds],
        "recipes": [{"key": recipe.key, "name": recipe.name, "steps": len(recipe.steps), "complete": recipe.complete,
                     "reads": recipe.reads, "parameters": [p["name"] for p in recipe.parameters]}
                    for recipe in conversion.recipes],
        "checks": [{"key": check.key, "name": check.name, "rule_type": check.rule_type, "reads": check.reads}
                   for check in conversion.checks],
        "workflows": [{"key": workflow.key, "name": workflow.name, "tasks": len(workflow.tasks),
                       "trigger_type": workflow.trigger_type, "cron_expression": workflow.cron_expression}
                      for workflow in conversion.workflows],
        "sections": [{"title": section.title, "entries": [
            {"subject": e.subject, "status": e.status, "became": e.became, "reason": e.reason, "notes": e.notes}
            for e in section.entries]} for section in conversion.sections],
        "counts": {"converted": counts["converted"], "not_converted": counts["not converted"],
                   "nothing_to_do": counts["nothing to do"]},
        "notes": conversion.notes,
        "choices": [{"id": str(row.id), "name": row.name} for row in sorted(
            resolver.datasets.values(), key=lambda row: (row.name or "").casefold())],
    }


# ------------------------------------------------------------------ apply


@dataclass
class Made:
    kind: str
    key: str
    name: str
    status: str  # made | used | skipped | failed
    id: str | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "key": self.key, "name": self.name, "status": self.status, "id": self.id,
                "detail": self.detail}


def _reads(recipe: RecipePlan) -> list[str]:
    return recipe.reads_all()


def _in_order(recipes: list[RecipePlan]) -> list[RecipePlan]:
    """Recipes after the recipes they read, otherwise as given."""
    by_key = {recipe.key: recipe for recipe in recipes}
    done: set[str] = set()
    order: list[RecipePlan] = []

    def visit(recipe: RecipePlan, trail: set[str]) -> None:
        if recipe.key in done or recipe.key in trail:
            return
        for key in _reads(recipe):
            if key in by_key:
                visit(by_key[key], trail | {recipe.key})
        done.add(recipe.key)
        order.append(recipe)

    for recipe in recipes:
        visit(recipe, set())
    return order


def _resolved(value: Any, datasets: dict[str, uuid.UUID]) -> Any:
    if isinstance(value, dict):
        if "$dataset" in value:
            return str(datasets[str(value["$dataset"])])
        return {key: _resolved(item, datasets) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolved(item, datasets) for item in value]
    return value


def apply(db: Session, project_id: uuid.UUID, conversion: Conversion, resolver: Resolver, *, storage_backend,
          settings) -> list[Made]:
    """Make the conversion in the project. Returns what became of each item."""
    from api_gateway.bundles import _names
    from service_projects.contracts import ensure_owned_project
    from service_quality.models import DataQualityRule
    from service_transformations.models import TransformationPipeline
    from service_workflows.models import Workflow

    user = resolver.reader
    ensure_owned_project(db, project_id, user.id)
    datasets: dict[str, uuid.UUID] = {key: found[1].id for key, found in resolver.found.items() if found[1]}
    labels = {**{need.key: f"the dataset “{need.name}”" for need in conversion.needs},
              **{seed.key: f"the seed “{seed.name}”" for seed in conversion.seeds},
              **{recipe.key: f"the recipe “{recipe.name}”" for recipe in conversion.recipes}}
    made: list[Made] = []
    why_missing: dict[str, str] = {}
    for need in conversion.needs:
        if need.key not in datasets:
            why_missing[need.key] = f"It reads {need.what}, which no dataset here is chosen for."

    # ------------------------------------------------------------ seeds
    for seed in conversion.seeds:
        made.append(_seed(db, project_id, seed, resolver, datasets, storage_backend, settings))
        if seed.key not in datasets:
            why_missing[seed.key] = f"It reads the seed “{seed.name}”, which was not made."

    # ---------------------------------------------------------- recipes
    taken = {name.casefold() for name in _names(db, TransformationPipeline, project_id).values()}
    recipe_ids: dict[str, uuid.UUID] = {}
    for recipe in _in_order(conversion.recipes):
        missing = [key for key in _reads(recipe) if key not in datasets]
        if missing:
            why = why_missing.get(missing[0]) or f"It reads {labels.get(missing[0], missing[0])}, which is not here."
            made.append(Made("recipe", recipe.key, recipe.name, "skipped", detail=why))
            why_missing[recipe.key] = f"It reads {labels[recipe.key]}, which was not made."
            continue
        if recipe.name.casefold() in taken:
            made.append(Made("recipe", recipe.key, recipe.name, "skipped",
                             detail=f"This project already has a recipe called “{recipe.name}”."))
            why_missing[recipe.key] = f"It reads {labels[recipe.key]}, which was not made: the name is taken."
            continue
        made.append(_recipe(db, project_id, recipe, datasets, recipe_ids, user, storage_backend, settings))
        taken.add(recipe.name.casefold())
        if recipe.key not in datasets:
            why_missing[recipe.key] = f"It reads {labels[recipe.key]}, which has no result: {made[-1].detail}"

    # ----------------------------------------------------------- checks
    taken_checks = {name.casefold() for name in _names(db, DataQualityRule, project_id).values()}
    check_ids: dict[str, uuid.UUID] = {}
    for check in conversion.checks:
        if check.reads not in datasets:
            made.append(Made("check", check.key, check.name, "skipped",
                             detail=why_missing.get(check.reads) or "What it checks is not here."))
            continue
        if check.name.casefold() in taken_checks:
            made.append(Made("check", check.key, check.name, "skipped",
                             detail=f"This project already has a check called “{check.name}”."))
            continue
        made.append(_check(db, project_id, check, datasets, check_ids, user))
        taken_checks.add(check.name.casefold())
    _run_checks(db, project_id, conversion, datasets, check_ids, made, user, storage_backend, settings)

    # -------------------------------------------------------- workflows
    taken_workflows = {name.casefold() for name in _names(db, Workflow, project_id).values()}
    for workflow in conversion.workflows:
        if workflow.name.casefold() in taken_workflows:
            made.append(Made("workflow", workflow.key, workflow.name, "skipped",
                             detail=f"This project already has a workflow called “{workflow.name}”."))
            continue
        made.append(_workflow(db, project_id, workflow, datasets, recipe_ids, check_ids, user))
    return made


def _seed(db, project_id, seed, resolver: Resolver, datasets, storage_backend, settings) -> Made:
    from service_ingestion.schemas import IngestionUpload
    from service_ingestion.service import ingest_project_file

    from api_gateway.conversions.dbt import _seed_columns

    try:
        wanted = list(_seed_columns(seed.data))
    except Exception:  # noqa: BLE001 - the ingest below says why, in its own words
        wanted = None
    for row in resolver.datasets.values():
        if (row.name or "").casefold() == seed.name.casefold() and wanted is not None and \
                list((row.schema_json or {}).get("ordered_columns") or []) == wanted:
            datasets[seed.key] = row.id
            return Made("dataset", seed.key, seed.name, "used", str(row.id),
                        "The project already has it, with the same columns.")
    try:
        response = ingest_project_file(
            db, project_id=project_id, dataset_name=seed.name,
            upload_file=IngestionUpload(file_name=seed.file_name, content_type="text/csv", file_bytes=seed.data),
            storage_backend=storage_backend, settings=settings, current_user=resolver.reader)
    except ApplicationError as exc:
        db.rollback()
        return Made("dataset", seed.key, seed.name, "failed", detail=str(exc.detail))
    datasets[seed.key] = response.dataset.id
    return Made("dataset", seed.key, seed.name, "made", str(response.dataset.id),
                f"Made from {seed.file_name}: {count_of(response.dataset.row_count or 0, 'row')}.")


def _recipe(db, project_id, recipe: RecipePlan, datasets, recipe_ids, user, storage_backend, settings) -> Made:
    from service_transformations.run import run_saved_transformation_pipeline
    from service_transformations.schemas import TransformationPipelineCreate
    from service_transformations.service import create_transformation_pipeline

    try:
        pipeline = create_transformation_pipeline(
            db, project_id=project_id, dataset_id=datasets[recipe.reads], current_user=user,
            payload=TransformationPipelineCreate(
                name=recipe.name, description=recipe.description[:2000] or None,
                status="active" if recipe.complete else "draft",
                steps_json=_resolved(recipe.steps, datasets), parameters=recipe.parameters))
    except ApplicationError as exc:
        db.rollback()
        return Made("recipe", recipe.key, recipe.name, "failed", detail=f"Not made: {exc.detail}")
    recipe_ids[recipe.key] = pipeline.id
    if not recipe.complete:
        return Made("recipe", recipe.key, recipe.name, "made", str(pipeline.id),
                    "Made as a draft and not run: a part of it did not convert (see the report).")
    try:
        result = run_saved_transformation_pipeline(
            db, project_id=project_id, pipeline_id=pipeline.id, current_user=user, storage_backend=storage_backend,
            settings=settings, notify_on_complete=False)
    except ApplicationError as exc:
        db.rollback()
        return Made("recipe", recipe.key, recipe.name, "failed", str(pipeline.id),
                    f"Made, but its run stopped: {exc.detail}")
    datasets[recipe.key] = result.dataset.id
    return Made("recipe", recipe.key, recipe.name, "made", str(pipeline.id),
                f"Made and run: “{result.dataset.name}”, {count_of(result.dataset.row_count or 0, 'row')}.")


def _check(db, project_id, check, datasets, check_ids, user) -> Made:
    from service_quality.schemas import DataQualityRuleCreate
    from service_quality.service import create_rule

    try:
        rule = create_rule(db, project_id, DataQualityRuleCreate(
            name=check.name, description=check.description, rule_type=check.rule_type, severity=check.severity,
            dataset_id=datasets[check.reads], config=check.config), user)
    except ApplicationError as exc:
        db.rollback()
        return Made("check", check.key, check.name, "failed", detail=f"Not made: {exc.detail}")
    check_ids[check.key] = rule.id
    return Made("check", check.key, check.name, "made", str(rule.id))


def _run_checks(db, project_id, conversion, datasets, check_ids, made, user, storage_backend, settings) -> None:
    """Each made check, run once on its dataset, so the import says how the data stands."""
    from service_quality.schemas import DataQualityEvaluationRequest
    from service_quality.service import evaluate_dataset

    by_dataset: dict[uuid.UUID, list[str]] = {}
    for check in conversion.checks:
        if check.key in check_ids:
            by_dataset.setdefault(datasets[check.reads], []).append(check.key)
    outcome: dict[str, str] = {}
    for dataset_id, keys in by_dataset.items():
        try:
            evaluation = evaluate_dataset(db, project_id, dataset_id, DataQualityEvaluationRequest(
                rule_ids=[check_ids[key] for key in keys]), user, storage_backend, settings)
        except ApplicationError as exc:
            db.rollback()
            for key in keys:
                outcome[key] = f"Made; it could not run: {exc.detail}"
            continue
        by_id = {str(result.rule_id): result for result in evaluation.results}
        for key in keys:
            result = by_id.get(str(check_ids[key]))
            if result is not None:
                outcome[key] = f"Made and run: it {'passes' if result.status == 'passed' else 'fails'}. " \
                               f"{result.message}"
    for item in made:
        if item.kind == "check" and item.key in outcome:
            item.detail = outcome[item.key]


def _workflow(db, project_id, workflow, datasets, recipe_ids, check_ids, user) -> Made:
    from service_workflows.schemas import WorkflowCreate, WorkflowEdgeInput, WorkflowNodeInput
    from service_workflows.service import create_workflow

    def resolve(value: Any) -> Any:
        if isinstance(value, dict):
            if "$recipe" in value:
                return str(recipe_ids[value["$recipe"]])
            if "$dataset" in value:
                return str(datasets[value["$dataset"]])
            if "$checks" in value:
                return [str(check_ids[key]) for key in value["$checks"]]
            return {key: resolve(item) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item) for item in value]
        return value

    nodes, left_out = [], []
    for task in workflow.tasks:
        try:
            config = resolve(task.config)
        except KeyError:
            left_out.append(task.name)
            continue
        nodes.append(WorkflowNodeInput(
            node_key=task.node_key, name=task.name[:160], node_type=task.node_type, config=config,
            continue_on_failure=task.continue_on_failure, retries=task.retries,
            retry_delay_seconds=task.retry_delay_seconds))
    kept = {node.node_key for node in nodes}
    if not nodes:
        return Made("workflow", workflow.key, workflow.name, "skipped",
                    detail="None of its tasks' recipes or checks were made.")
    try:
        made = create_workflow(db, project_id, WorkflowCreate(
            name=workflow.name, description=workflow.description, trigger_type=workflow.trigger_type,
            cron_expression=workflow.cron_expression, timezone=workflow.timezone,
            default_parameters=workflow.default_parameters, nodes=nodes,
            edges=[WorkflowEdgeInput(from_node_key=link.source, to_node_key=link.target, condition=link.condition)
                   for link in workflow.links if link.source in kept and link.target in kept]), user)
    except ApplicationError as exc:
        db.rollback()
        return Made("workflow", workflow.key, workflow.name, "failed", detail=f"Not made: {exc.detail}")
    detail = f"Made with {count_of(len(nodes), 'task')}."
    if left_out:
        detail += f" Left out, as what they run was not made: {', '.join(left_out)}."
    return Made("workflow", workflow.key, workflow.name, "made", str(made.id), detail)
