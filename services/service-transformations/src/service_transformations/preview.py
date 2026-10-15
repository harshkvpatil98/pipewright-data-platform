from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.service import get_dataset_model_for_project
from service_ingestion.read_copy import frame_of
from service_projects.contracts import ensure_owned_project
from service_transformations.dataset_access import build_step_context
from service_transformations.schemas import (
    ExecutionPlanRead,
    StepEstimate,
    ExecutionStepPlacement,
    TransformationPreviewRequest,
    TransformationPreviewResponse,
    TransformationStepOutcome,
)
from service_transformations.tabular import build_schema_summary, json_preview_rows
from shared_python.errors import BadRequestError, NotFoundError


def preview_dataset_transformations(
    db: Session,
    *,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: TransformationPreviewRequest,
    current_user: UserRead,
    storage_backend: Any,
    settings: Any | None = None,
) -> TransformationPreviewResponse:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)

    if not dataset.file_path or not dataset.file_type:
        raise BadRequestError("This dataset has no saved data to preview.")

    from service_datasets.service import stored_file_identity
    from service_enterprise.policy_view import Reader, narrow_frame, view_for
    from service_transformations.executor import apply_single_step, validate_steps_json
    from service_transformations.prefix_cache import describe_input, run_steps

    # A preview hands rows to a person, so it starts from what they may see.
    reader = Reader.for_user(db, project_id, current_user)
    # Parameters are written in first, as a run would (E1).
    from service_transformations.parameters import resolve

    payload = payload.model_copy(update={"steps": resolve(payload.steps, payload.parameters,
                                                          payload.parameter_values)})

    read: dict[str, int] = {}

    def load():
        try:
            file_bytes = storage_backend.read_bytes(dataset.file_path)
            read["bytes"] = len(file_bytes)
        except FileNotFoundError as exc:
            raise NotFoundError(
                "This dataset's stored file is missing. The dataset record still exists, so re-uploading the file restores it."
            ) from exc
        except OSError as exc:
            raise BadRequestError(f"Unable to read dataset file: {exc}") from exc
        frame = frame_of(storage_backend, dataset.file_path, file_bytes, file_type=dataset.file_type,
                         spec=dataset.ingest_spec_json)
        return narrow_frame(db, project_id, dataset.id, reader, frame.copy())

    limit = getattr(settings, "preview_row_limit", 50) if settings is not None else 50
    if not isinstance(limit, int) or limit < 1:
        limit = 50

    # Join/union steps read sibling datasets, scoped to this project.
    context = build_step_context(
        db,
        project_id=project_id,
        storage_backend=storage_backend,
        max_bytes=getattr(settings, "max_upload_size_bytes", None) if settings is not None else None,
        reader=reader,
    )
    # What earlier previews and runs of the same steps made is reused (D2): editing
    # step 14 of 15 runs steps 14 and 15, not all of them over a fresh read.
    identity = stored_file_identity(db, dataset.id, dataset.file_path)
    base = None
    if identity is not None:
        base = "|".join([identity, str(dataset.file_type), json.dumps(dataset.ingest_spec_json, sort_keys=True, default=str),
                         view_for(db, project_id, dataset.id, reader).fingerprint()])

    def other_of(step_type: str, config: dict) -> str | None:
        raw = config.get("right_dataset_id") or config.get("other_dataset_id")
        try:
            other = get_dataset_model_for_project(db, project_id, uuid.UUID(str(raw)))
        except Exception:  # noqa: BLE001 - the step itself reports a missing dataset
            return None
        found = stored_file_identity(db, other.id, other.file_path)
        if found is None:
            return None
        return "|".join([found, json.dumps(other.ingest_spec_json, sort_keys=True, default=str),
                         view_for(db, project_id, other.id, reader).fingerprint()])

    ran = run_steps(
        base=base,
        load=load,
        steps=validate_steps_json(payload.steps),
        apply=lambda frame, step: apply_single_step(frame, step, context),
        other_of=other_of,
        describe=lambda frame: describe_input(frame, file_size=read.get("bytes", 0)),
    )
    transformed, warnings, outcomes = ran.frame, ran.warnings, ran.outcomes

    schema_before = ran.source["schema"]
    schema_after = build_schema_summary(transformed)

    preview_columns = [str(column) for column in transformed.columns]
    preview_rows = json_preview_rows(transformed, limit)

    return TransformationPreviewResponse(
        preview_rows=preview_rows,
        preview_columns=preview_columns,
        row_count_before=ran.source["rows"],
        row_count_after=int(len(transformed)),
        execution_plan=_describe_plan(dataset, payload.steps, _statistics_for(db, project_id, dataset, reader),
                                      _other_datasets(db, project_id, reader),
                                      visible=list(ran.source["schema"].ordered_columns)),
        step_outcomes=[
            TransformationStepOutcome(
                index=outcome.index,
                step_type=outcome.step_type,
                rows_before=outcome.rows_before,
                rows_after=outcome.rows_after,
                columns_before=outcome.columns_before,
                columns_after=outcome.columns_after,
            )
            for outcome in outcomes
        ],
        column_count_before=len(ran.source["schema"].ordered_columns),
        column_count_after=int(len(transformed.columns)),
        schema_before=schema_before,
        schema_after=schema_after,
        warnings=warnings,
    )


def _statistics_for(db: Session, project_id: uuid.UUID, dataset, reader, view=None):
    """The dataset's statistics as this reader may see them, or None.

    Figures over rows a policy hides would say something about those rows, so
    a reader whose rows are filtered gets none, and every estimate says it is
    a guess.
    """
    from service_enterprise.policy_view import view_for
    from shared_python.statistics import from_profile

    view = view or view_for(db, project_id, dataset.id, reader)
    if view.filters_rows:
        return None
    return from_profile(view.profile(dataset.profile_json))


def _step_estimates(scan, steps: list[dict], stats, others=None) -> list[StepEstimate]:
    """Each step's expected rows: the pipeline up to it, estimated whole.

    `others(step)` hands back the other dataset a join or union reads, as a
    Scan with its statistics, so the estimate can use both sides; without it
    such a step is a stated guess.
    """
    from service_transformations.ir.estimate import estimate
    from service_transformations.ir.from_steps import compile_step

    known = {scan.source: stats}
    node = scan
    out: list[StepEstimate] = []
    for index, step in enumerate(steps):
        attempts = [step["config"]]
        other = others(step) if others is not None and step["type"] in ("join_datasets", "union_datasets") else None
        if other is not None:
            right, right_stats = other
            known[right.source] = right_stats
            attempts.insert(0, {**step["config"], "_right_node": right})
        for config in attempts:
            try:
                node = compile_step(node, step["type"], config)
                break
            except Exception:  # noqa: BLE001 - fall back to the step as an unknown
                continue
        else:
            return out
        try:
            result = estimate(node, known)
        except Exception:  # noqa: BLE001 - an estimate is a nicety; never break the preview
            return out
        last = result.steps[-1]
        out.append(StepEstimate(index=index, step_type=str(step["type"]), rows=round(result.rows, 1), how=last.how,
                                guessed=result.guessed))
    return out


def _other_datasets(db: Session, project_id: uuid.UUID, reader):
    """For a join or union step: the dataset it reads, as a Scan, with what this reader may know of it."""
    from service_transformations.ir.nodes import Scan
    from shared_python.types import UNKNOWN

    found: dict[str, object] = {}

    def lookup(step: dict):
        config = step.get("config") or {}
        raw = str(config.get("right_dataset_id") or config.get("other_dataset_id") or "")
        if raw not in found:
            found[raw] = _other(raw)
        return found[raw]

    def _other(raw: str):
        from service_enterprise.policy_view import view_for

        try:
            other = get_dataset_model_for_project(db, project_id, uuid.UUID(raw))
        except Exception:  # noqa: BLE001 - a missing dataset fails the preview itself, not here
            return None
        view = view_for(db, project_id, other.id, reader)
        names = view.visible_columns([str(name) for name in (other.schema_json or {}).get("ordered_columns", [])])
        if not names:
            return None
        return Scan(f"dataset:{other.id}", tuple((name, UNKNOWN) for name in names)), \
            _statistics_for(db, project_id, other, reader, view)

    return lookup


def _describe_plan(dataset, raw_steps, stats=None, others=None, visible=None) -> ExecutionPlanRead | None:
    """Where this pipeline's work would happen on a full run.

    Computed from the IR, which is a description rather than an execution: the
    preview itself always reads the materialised file. What this answers is
    "when this pipeline runs against its source, what will the source do?" --
    and for a stored file the honest answer is "nothing", which is exactly the
    thing worth knowing.
    """
    from service_transformations.ir.from_steps import compile_pipeline
    from service_transformations.ir.nodes import IRError, Scan
    from service_transformations.ir.planner import plan as build_plan
    from shared_python.types import UNKNOWN

    source_type = _source_type_of(dataset)
    # Steps arrive as plain dicts from the request body, and as objects from
    # code that has already validated them. Handling both is not defensiveness
    # for its own sake: the mock in the unit test was an object, the real
    # request body is a dict, and the difference only showed up in the browser.
    steps = []
    for step in raw_steps or []:
        if isinstance(step, dict):
            step_type = step.get("step_type") or step.get("type")
            config = step.get("config") or {}
        else:
            step_type = getattr(step, "step_type", None) or getattr(step, "type", None)
            config = getattr(step, "config", None) or {}
        if not isinstance(step_type, str):
            return None
        steps.append({"type": step_type, "config": config})

    # A join's columns come from the dataset it reads; with them the steps
    # after it can be described too. It stays a step that runs here.
    plan_steps = []
    for step in steps:
        other = others(step) if others is not None and step["type"] == "join_datasets" else None
        if other is not None:
            step = {"type": step["type"], "config": {**step["config"], "_right_columns": other[0].columns}}
        plan_steps.append(step)

    # Only the columns this reader may know exist: a denied one is never named, even in a plan.
    names = visible if visible is not None else (dataset.schema_json or {}).get("ordered_columns", [])
    columns = tuple((str(name), UNKNOWN) for name in names) or (("__unknown__", UNKNOWN),)

    try:
        tree = compile_pipeline(Scan(dataset.name or "source", columns), plan_steps)
        execution = build_plan(tree, source_type)
    except (IRError, ValueError, KeyError):
        # A pipeline the IR cannot describe gets no plan rather than a wrong
        # one. The steps still run; only the explanation is missing.
        return None

    return ExecutionPlanRead(
        source_type=source_type or "stored file",
        surface=execution.surface.surface.value if execution.surface else "none",
        pushed_steps=execution.pushed_count,
        local_steps=execution.local_count,
        sql=execution.sql,
        placements=[
            ExecutionStepPlacement(node=d.node, pushed=d.pushed, reason=d.reason)
            for d in execution.decisions
        ],
        note=execution.surface.note if execution.surface else "",
        rewrites=[str(applied) for applied in execution.rewrites],
        estimates=_step_estimates(Scan(dataset.name or "source", columns), plan_steps, stats, others),
    )


def _source_type_of(dataset) -> str | None:
    """The connector type behind this dataset, or None.

    Only a real, non-empty string counts. Anything else -- an unloaded
    relationship, a stub -- means "unknown", and unknown maps to a local-only
    surface, which is the safe answer: nothing is assumed to push down.
    """
    source = getattr(dataset, "source", None)
    if source is None:
        return None
    source_type = getattr(source, "source_type", None)
    if isinstance(source_type, str) and source_type.strip():
        return source_type
    return None
