from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.service import get_dataset_model_for_project
from service_ingestion.parsers import parse_tabular_file
from service_projects.contracts import ensure_owned_project
from service_transformations.dataset_access import build_step_context
from service_transformations.executor import apply_transformation_steps_with_outcomes
from service_transformations.schemas import (
    ExecutionPlanRead,
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
        raise BadRequestError("Dataset has no stored file artifact to preview.")

    try:
        file_bytes = storage_backend.read_bytes(dataset.file_path)
    except FileNotFoundError as exc:
        raise NotFoundError(
            "This dataset's stored file is missing. The dataset record still exists, so re-uploading the file restores it."
        ) from exc
    except OSError as exc:
        raise BadRequestError(f"Unable to read dataset file: {exc}") from exc

    parsed = parse_tabular_file(file_bytes=file_bytes, file_type=dataset.file_type)
    source_frame = parsed.dataframe.copy()

    limit = getattr(settings, "preview_row_limit", 50) if settings is not None else 50
    if not isinstance(limit, int) or limit < 1:
        limit = 50

    # Join/union steps read sibling datasets, scoped to this project.
    context = build_step_context(
        db,
        project_id=project_id,
        storage_backend=storage_backend,
        max_bytes=getattr(settings, "max_upload_size_bytes", None) if settings is not None else None,
    )
    transformed, warnings, outcomes = apply_transformation_steps_with_outcomes(
        source_frame, payload.steps, context
    )

    schema_before = build_schema_summary(source_frame)
    schema_after = build_schema_summary(transformed)

    preview_columns = [str(column) for column in transformed.columns]
    preview_rows = json_preview_rows(transformed, limit)

    return TransformationPreviewResponse(
        preview_rows=preview_rows,
        preview_columns=preview_columns,
        row_count_before=int(len(source_frame)),
        row_count_after=int(len(transformed)),
        execution_plan=_describe_plan(dataset, payload.steps),
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
        column_count_before=int(len(source_frame.columns)),
        column_count_after=int(len(transformed.columns)),
        schema_before=schema_before,
        schema_after=schema_after,
        warnings=warnings,
    )


def _describe_plan(dataset, raw_steps) -> ExecutionPlanRead | None:
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

    columns = tuple(
        (str(name), UNKNOWN) for name in (dataset.schema_json or {}).get("ordered_columns", [])
    ) or (("__unknown__", UNKNOWN),)

    try:
        tree = compile_pipeline(Scan(dataset.name or "source", columns), steps)
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
