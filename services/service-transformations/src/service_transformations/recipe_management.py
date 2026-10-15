"""Managing recipes as things of their own (E1, T6).

Parameters a run is given, templates a project saves for itself, branches
of a recipe and merging them back, the same steps on another dataset, and
one recipe per value of a column. Each one changes recipes only through the
ordinary path (`record_save`, `record_recipe_version`), so revisions, the
shared copy, versions and review all see it.

**Merging a branch** is a three-way merge by step: the branch remembers the
steps (and their ids) it was made from, the common ancestor. A step changed
on one side only takes that side's change; settings changed on both sides
merge setting by setting; a setting both changed differently, or a step one
side removed and the other changed, is a conflict, named, and the merge
waits for the person to say which side wins.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared_python.errors import BadRequestError, ConflictError, NotFoundError
from shared_python.words import count_of, listing

from service_auth.schemas import UserRead
from service_datasets.service import get_dataset_model_for_project
from service_projects.contracts import ensure_owned_project
from service_transformations import parameters as recipe_parameters
from service_transformations.coedit import ensure_step_ids, record_save
from service_transformations.contracts import get_transformation_pipeline_for_project
from service_transformations.models import RecipeTemplate, TransformationPipeline
from service_transformations.validators import validate_steps_json
from service_transformations.versioning import record_recipe_version

MAX_SPLIT = 50
#: A setting one side does not have, which is not the same as one set to nothing.
_ABSENT = object()


# ---------------------------------------------------------------- schemas


class ParametersUpdate(BaseModel):
    parameters: list[recipe_parameters.RecipeParameter] = Field(default_factory=list)


class TemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    steps_json: list[dict[str, Any]] = Field(min_length=1)


class TemplateRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    steps_json: list[dict[str, Any]]
    step_count: int
    created_at: datetime


class TemplateListResponse(BaseModel):
    items: list[TemplateRead]


class BranchCreate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)


class MergeRequest(BaseModel):
    #: When both changed the same thing: keep the recipe's, take the branch's, or (None) stop and say.
    prefer: Literal["recipe", "branch"] | None = None


class MergeConflict(BaseModel):
    step_id: str
    step: str
    what: str


class MergeResult(BaseModel):
    applied: bool
    steps_json: list[dict[str, Any]]
    step_ids: list[str]
    added: int
    removed: int
    changed: int
    conflicts: list[MergeConflict]
    message: str


class CopyRequest(BaseModel):
    base_dataset_id: uuid.UUID
    name: str | None = Field(default=None, min_length=2, max_length=160)


class CopyResult(BaseModel):
    pipeline_id: uuid.UUID
    name: str
    warnings: list[str]


class SplitRequest(BaseModel):
    column: str = Field(min_length=1, max_length=255)
    values: list[str] | None = None


class SplitResult(BaseModel):
    created: list[CopyResult]


# ------------------------------------------------------------- parameters


def set_parameters(db: Session, *, project_id: uuid.UUID, pipeline_id: uuid.UUID, payload: ParametersUpdate,
                   current_user: UserRead) -> TransformationPipeline:
    ensure_owned_project(db, project_id, current_user.id)
    pipeline = get_transformation_pipeline_for_project(db, project_id, pipeline_id)
    declared = recipe_parameters.validate(payload.parameters)
    # The steps do not change, so neither does the revision, and the Studio's
    # shared copy, with anyone's unsaved changes in it, stays as it is.
    pipeline.parameters_json = [p.model_dump(mode="json") for p in declared] or None
    db.flush()
    record_recipe_version(db, pipeline, current_user.id)
    db.commit()
    db.refresh(pipeline)
    return pipeline


# -------------------------------------------------------------- templates


def _template_read(row: RecipeTemplate) -> TemplateRead:
    return TemplateRead(id=row.id, name=row.name, description=row.description, steps_json=list(row.steps_json),
                        step_count=len(row.steps_json), created_at=row.created_at)


def list_templates(db: Session, *, project_id: uuid.UUID, current_user: UserRead) -> TemplateListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    rows = db.scalars(select(RecipeTemplate).where(RecipeTemplate.project_id == project_id)
                      .order_by(RecipeTemplate.name)).all()
    return TemplateListResponse(items=[_template_read(row) for row in rows])


def create_template(db: Session, *, project_id: uuid.UUID, payload: TemplateCreate,
                    current_user: UserRead) -> TemplateRead:
    ensure_owned_project(db, project_id, current_user.id)
    steps = [step.model_dump(mode="json") for step in validate_steps_json(payload.steps_json)]
    name = " ".join(payload.name.split())
    if db.scalar(select(RecipeTemplate).where(RecipeTemplate.project_id == project_id, RecipeTemplate.name == name)):
        raise BadRequestError(f"This project already has a template called {name!r}.")
    row = RecipeTemplate(project_id=project_id, name=name, description=payload.description, steps_json=steps,
                         created_by_user_id=current_user.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _template_read(row)


def delete_template(db: Session, *, project_id: uuid.UUID, template_id: uuid.UUID, current_user: UserRead) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    row = db.scalar(select(RecipeTemplate).where(RecipeTemplate.id == template_id,
                                                 RecipeTemplate.project_id == project_id))
    if row is None:
        raise NotFoundError("There is no such template in this project.")
    db.delete(row)
    db.commit()


# --------------------------------------------------------------- branches


def _unique_name(db: Session, project_id: uuid.UUID, wanted: str) -> str:
    wanted = wanted[:160]
    taken = set(db.scalars(select(TransformationPipeline.name).where(
        TransformationPipeline.project_id == project_id)).all())
    if wanted not in taken:
        return wanted
    for number in range(2, 1000):
        candidate = f"{wanted[:150]} ({number})"
        if candidate not in taken:
            return candidate
    raise BadRequestError("Choose another name: this one is taken many times over.")


def _new_recipe(db: Session, source: TransformationPipeline, *, name: str, base_dataset_id: uuid.UUID,
                steps: list[dict[str, Any]], step_ids: list[str] | None, current_user: UserRead,
                branched_from: TransformationPipeline | None = None) -> TransformationPipeline:
    pipeline = TransformationPipeline(
        project_id=source.project_id, base_dataset_id=base_dataset_id, created_by_user_id=current_user.id,
        name=_unique_name(db, source.project_id, name), description=source.description, status="draft",
        steps_json=copy.deepcopy(steps), revision=1,
        step_ids_json=list(step_ids) if step_ids else [uuid.uuid4().hex for _ in steps],
        revised_by_user_id=current_user.id, revised_at=datetime.now(UTC),
        parameters_json=copy.deepcopy(source.parameters_json),
        branched_from_id=branched_from.id if branched_from is not None else None,
        branch_base_json={"steps": copy.deepcopy(steps), "step_ids": list(step_ids or []),
                          "revision": int(branched_from.revision or 1)} if branched_from is not None else None,
    )
    db.add(pipeline)
    db.flush()
    record_recipe_version(db, pipeline, current_user.id)
    return pipeline


def branch(db: Session, *, project_id: uuid.UUID, pipeline_id: uuid.UUID, payload: BranchCreate,
           current_user: UserRead) -> TransformationPipeline:
    """A copy of the recipe to change on its own, merged back when it is ready."""
    ensure_owned_project(db, project_id, current_user.id)
    parent = get_transformation_pipeline_for_project(db, project_id, pipeline_id)
    ids = ensure_step_ids(parent)
    created = _new_recipe(db, parent, name=payload.name or f"{parent.name}: branch",
                          base_dataset_id=parent.base_dataset_id, steps=list(parent.steps_json or []),
                          step_ids=ids, current_user=current_user, branched_from=parent)
    db.commit()
    db.refresh(created)
    return created


def _label(step: dict[str, Any], position: int) -> str:
    config = step.get("config") or {}
    kind = config.get("tool") if step.get("step_type") == "tool" else step.get("step_type")
    return f"step {position} ({str(kind).replace('_', ' ')})"


def three_way(base: list[tuple[str, dict]], ours: list[tuple[str, dict]], theirs: list[tuple[str, dict]],
              prefer: str | None) -> tuple[list[tuple[str, dict]], list[MergeConflict], dict[str, int]]:
    """Merge two edits of a step list against their common ancestor, step by step and setting by setting."""
    base_map, ours_map, theirs_map = dict(base), dict(ours), dict(theirs)
    conflicts: list[MergeConflict] = []
    counts = {"added": 0, "removed": 0, "changed": 0}
    merged: dict[str, dict] = {}
    position = {step_id: index + 1 for index, (step_id, _) in enumerate(theirs or ours)}

    def conflict(step_id: str, step: dict, what: str) -> None:
        conflicts.append(MergeConflict(step_id=step_id, step=_label(step, position.get(step_id, 0)), what=what))

    for step_id in dict.fromkeys([*[i for i, _ in ours], *[i for i, _ in theirs], *[i for i, _ in base]]):
        b, o, t = base_map.get(step_id), ours_map.get(step_id), theirs_map.get(step_id)
        if b is None:
            if o is not None and t is not None and o != t:
                conflict(step_id, o, "added on both sides with different settings")
                merged[step_id] = t if prefer == "branch" else o
            elif o is not None:
                merged[step_id] = o
            else:
                merged[step_id] = t  # added on the branch
                counts["added"] += 1
            continue
        if o is None and t is None:
            continue
        if o is None:
            if t != b:
                conflict(step_id, t, "removed from the recipe but changed on the branch")
                if prefer == "branch":
                    merged[step_id] = t
            continue
        if t is None:
            if o != b:
                conflict(step_id, o, "changed in the recipe but removed on the branch")
                if prefer != "branch":
                    merged[step_id] = o
            else:
                counts["removed"] += 1
            continue
        if o == t or t == b:
            merged[step_id] = o
            continue
        if o == b:
            merged[step_id] = t
            counts["changed"] += 1
            continue
        if o.get("step_type") != t.get("step_type"):
            conflict(step_id, o, "turned into different steps on each side")
            merged[step_id] = t if prefer == "branch" else o
            continue
        config: dict[str, Any] = {}
        base_cfg, ours_cfg, theirs_cfg = b.get("config") or {}, o.get("config") or {}, t.get("config") or {}
        clashes = []
        for key in dict.fromkeys([*ours_cfg, *theirs_cfg, *base_cfg]):
            was, mine, yours = (base_cfg.get(key, _ABSENT), ours_cfg.get(key, _ABSENT),
                                theirs_cfg.get(key, _ABSENT))
            if mine == yours or yours == was:
                value = mine
            elif mine == was:
                value = yours
            else:
                clashes.append(key)
                value = yours if prefer == "branch" else mine
            if value is not _ABSENT:
                config[key] = value
        if clashes:
            conflict(step_id, o, f"both changed {listing(sorted(clashes))}")
        merged[step_id] = {**o, "config": config}
        counts["changed"] += 1

    # The order: the branch's when the recipe kept the order it had at the
    # branch, otherwise the recipe's with the branch's new steps after the step
    # they followed there.
    common = [step_id for step_id, _ in base if step_id in ours_map]
    recipe_kept_order = [i for i, _ in ours if i in base_map] == common
    if recipe_kept_order:
        order = [step_id for step_id, _ in theirs if step_id in merged]
        order += [step_id for step_id, _ in ours if step_id in merged and step_id not in order]
    else:
        order = [step_id for step_id, _ in ours if step_id in merged]
        previous: str | None = None
        for step_id, _ in theirs:
            if step_id in merged and step_id not in order:
                order.insert(order.index(previous) + 1 if previous in order else 0, step_id)
            if step_id in order:
                previous = step_id
    return [(step_id, merged[step_id]) for step_id in order], conflicts, counts


def merge(db: Session, *, project_id: uuid.UUID, branch_id: uuid.UUID, payload: MergeRequest,
          current_user: UserRead, preview: bool = False) -> MergeResult:
    """Merge a branch back into the recipe it came from, or (`preview`) say what that would do.

    A merge with a conflict and no side chosen is refused, saying so; its
    preview lists the conflicts, so a person chooses before merging."""
    ensure_owned_project(db, project_id, current_user.id)
    branch_recipe = get_transformation_pipeline_for_project(db, project_id, branch_id)
    if branch_recipe.branched_from_id is None or not branch_recipe.branch_base_json:
        raise BadRequestError("This recipe is not a branch of another, so there is nothing to merge it into.")
    try:
        parent = get_transformation_pipeline_for_project(db, project_id, branch_recipe.branched_from_id)
    except NotFoundError:
        raise BadRequestError("The recipe this was branched from no longer exists.") from None
    base_json = branch_recipe.branch_base_json
    base = list(zip(base_json.get("step_ids") or [], base_json.get("steps") or []))
    ours = list(zip(ensure_step_ids(parent), parent.steps_json or []))
    theirs = list(zip(ensure_step_ids(branch_recipe), branch_recipe.steps_json or []))
    result, conflicts, counts = three_way(base, ours, theirs, payload.prefer)
    steps, ids = [step for _, step in result], [step_id for step_id, _ in result]
    validate_steps_json(steps)
    blocked = bool(conflicts) and payload.prefer is None
    summary = (f"{count_of(counts['added'], 'step')} added, {counts['removed']:,} removed and "
               f"{counts['changed']:,} changed")
    if blocked and not preview:
        raise ConflictError(f"{count_of(len(conflicts), 'conflict')}: both {parent.name} and this branch changed "
                            f"{listing(sorted({c.step for c in conflicts}))}. Say whose side wins, then merge.")
    if preview:
        message = (f"{count_of(len(conflicts), 'conflict')}: say whether the recipe's or the branch's side wins."
                   if blocked else f"Merging would leave {parent.name} with {summary}.")
        return MergeResult(applied=False, steps_json=steps, step_ids=ids, conflicts=conflicts,
                           message=message, **counts)
    parent.steps_json = steps
    record_save(db, parent, current_user, step_ids=ids, from_shared_epoch=None,
                reason=f"{current_user.username} merged the branch {branch_recipe.name!r} into this recipe.")
    db.flush()
    record_recipe_version(db, parent, current_user.id)
    # A later merge compares from here, not from the first branching.
    branch_recipe.branch_base_json = {"steps": copy.deepcopy(steps), "step_ids": list(ids),
                                      "revision": int(parent.revision or 1)}
    db.commit()
    return MergeResult(applied=True, steps_json=steps, step_ids=ids, conflicts=conflicts,
                       message=f"Merged into {parent.name}: {summary}.", **counts)


# ------------------------------------------------- elsewhere, and per value


def _missing_columns(steps: list[dict[str, Any]], columns: list[str], label: str) -> list[str]:
    from service_lineage.columns import build_pipeline_lineage

    lineage = build_pipeline_lineage(base_columns=columns, steps=steps)
    warnings = []
    for step in lineage.steps:
        absent = sorted(set(step.named_columns) - set(step.input_columns) - set(step.output_columns))
        if absent:
            warnings.append(f"Step {step.step_index + 1} uses {listing(absent)}, which {label} does not have "
                            "at that point.")
    return warnings


def copy_to(db: Session, *, project_id: uuid.UUID, pipeline_id: uuid.UUID, payload: CopyRequest,
            current_user: UserRead) -> CopyResult:
    """The same steps, reading another dataset: last month's file, the next client's export."""
    ensure_owned_project(db, project_id, current_user.id)
    source = get_transformation_pipeline_for_project(db, project_id, pipeline_id)
    dataset = get_dataset_model_for_project(db, project_id, payload.base_dataset_id)
    columns = [str(name) for name in (dataset.schema_json or {}).get("ordered_columns") or []]
    steps = list(source.steps_json or [])
    warnings = _missing_columns(steps, columns, dataset.name) if columns else [
        f"{dataset.name}'s columns are not known yet, so the steps could not be checked against it."]
    created = _new_recipe(db, source, name=payload.name or f"{source.name} on {dataset.name}",
                          base_dataset_id=dataset.id, steps=steps, step_ids=None, current_user=current_user)
    db.commit()
    return CopyResult(pipeline_id=created.id, name=created.name, warnings=warnings)


def split(db: Session, *, project_id: uuid.UUID, pipeline_id: uuid.UUID, payload: SplitRequest,
          current_user: UserRead, storage_backend: Any) -> SplitResult:
    """One recipe for each value of a column: the recipe's steps, then keep that value's rows."""
    ensure_owned_project(db, project_id, current_user.id)
    source = get_transformation_pipeline_for_project(db, project_id, pipeline_id)
    values = [str(v) for v in payload.values] if payload.values else _values_of(
        db, project_id, source, payload.column, storage_backend)
    values = list(dict.fromkeys(values))
    if not values:
        raise BadRequestError(f"There are no values of {payload.column!r} to split by.")
    if len(values) > MAX_SPLIT:
        raise BadRequestError(f"{payload.column!r} has {len(values):,} values; split by up to {MAX_SPLIT}, or "
                              "list the values wanted.")
    created = []
    for value in values:
        steps = [*copy.deepcopy(source.steps_json or []), {"step_type": "filter_rows", "config": {
            "conditions": [{"column": payload.column, "operator": "equals", "value": value}]}}]
        recipe = _new_recipe(db, source, name=f"{source.name}: {value}", base_dataset_id=source.base_dataset_id,
                             steps=steps, step_ids=None, current_user=current_user)
        created.append(CopyResult(pipeline_id=recipe.id, name=recipe.name, warnings=[]))
    db.commit()
    return SplitResult(created=created)


def _values_of(db: Session, project_id: uuid.UUID, source: TransformationPipeline, column: str,
               storage_backend: Any) -> list[str]:
    """The column's values in the recipe's latest output, or else its input."""
    from service_ingestion.read_copy import frame_of

    for dataset_id in (source.output_dataset_id, source.base_dataset_id):
        if dataset_id is None:
            continue
        dataset = get_dataset_model_for_project(db, project_id, dataset_id)
        if not dataset.file_path:
            continue
        frame = frame_of(storage_backend, dataset.file_path, storage_backend.read_bytes(dataset.file_path),
                         file_type=dataset.file_type, spec=dataset.ingest_spec_json)
        if column in frame.columns:
            present = frame[column].dropna()
            distinct = sorted({str(v) for v in present})
            numbers = pd.to_numeric(pd.Series(distinct, dtype=object), errors="coerce")
            if len(distinct) and numbers.notna().all():
                return [value for _, value in sorted(zip(numbers, distinct))]
            return distinct
    raise BadRequestError(f"Neither the recipe's result nor its input has a column {column!r}.")
