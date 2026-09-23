"""Run a recorded run again, the same way, and say honestly how it compared.

A replay is not "run the pipeline again". It re-executes the recipe a run
recorded, against the input versions that run pinned, at the instant that run
froze -- and then compares what came out with the output version that run
published. Four answers are possible, and each is a different sentence:

* **equivalent** -- the same columns, canonical types and row multiset (or the
  same content digest, in which case nothing is even read);
* **divergent** -- it ran, and the result differs; the differences are listed;
* **incompatible** -- the engine's semantics have changed since (semantic
  version), or a recorded step no longer exists, so the original result cannot
  be reproduced. Stated, never papered over with "equivalent";
* **unavailable** -- an input version was pruned or its dataset deleted, or the
  run predates execution contexts, so there is nothing to replay against.

Every input is pinned durably (§4) before a byte is read, and released when
the replay finishes either way.
"""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion
from service_datasets.version_lifecycle import pin_version, release_pins, unavailable_reason
from service_pipeline_runs.contracts import get_pipeline_run_for_project
from service_projects.contracts import ensure_owned_project
from service_transformations.execution_context import (
    SEMANTIC_VERSION,
    ExecutionContext,
    VersionPin,
    context_from_run,
)
from service_transformations.schemas import ReplayComparison, ReplayResult
from service_transformations.validators import validate_steps_json
from shared_python.errors import ApplicationError, BadRequestError, ConflictError

REPLAYABLE_RUN_TYPES = frozenset({"dataset_transformation", "dataset_transformation_replay"})


def replayability(run) -> tuple[bool, str | None, ExecutionContext | None]:
    """Whether a run can be replayed at all, and why not when it cannot.

    Shared with the audit surface so the page can say "Replay" or the reason
    before anybody clicks.
    """
    if run.run_type not in REPLAYABLE_RUN_TYPES:
        return False, "Only transformation runs can be replayed.", None
    if run.status != "succeeded":
        return False, f"Only a succeeded run can be replayed; this one {run.status}.", None
    context = context_from_run(run.summary_json)
    if context is None:
        return (
            False,
            "This run was recorded before execution contexts existed, so its inputs and "
            "evaluation instant are unknown and it cannot be replayed deterministically.",
            None,
        )
    if context.semantic_version != SEMANTIC_VERSION:
        return (
            False,
            "The transformation engine's semantics have changed since this run "
            f"({context.semantic_version} then, {SEMANTIC_VERSION} now); its result cannot "
            "be reproduced and a replay would not be comparable.",
            context,
        )
    try:
        validate_steps_json(context.steps)
    except ApplicationError as exc:
        return False, f"A recorded step is no longer supported: {exc.detail}", context
    if not context.outputs or context.outputs[0].version_number is None:
        return False, "This run recorded no output version to compare against.", context
    return True, None, context


def replay_pipeline_run(
    db: Session,
    *,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    current_user: UserRead,
    storage_backend: Any,
    settings: Any,
) -> ReplayResult:
    from service_transformations.run import ReplayPlan, run_saved_transformation_pipeline

    ensure_owned_project(db, project_id, current_user.id)
    original = get_pipeline_run_for_project(db, project_id, run_id)
    ok, reason, context = replayability(original)
    if not ok:
        if original.run_type not in REPLAYABLE_RUN_TYPES or original.status != "succeeded":
            raise BadRequestError(reason or "This run cannot be replayed.")
        # No recorded context: there is nothing to replay against (unavailable).
        # A context the current engine cannot honour: incompatible.
        status = "unavailable" if context is None else "incompatible"
        return ReplayResult(
            status=status, reason=reason, original_run_id=original.id,
            original_output=_pin_dict(context.outputs[0]) if context and context.outputs else None,
            evaluated_at=context.evaluated_at if context else None,
            semantic_version=context.semantic_version if context else None,
        )
    assert context is not None
    if original.pipeline_id is None:
        return ReplayResult(
            status="unavailable", original_run_id=original.id,
            reason="The pipeline this run belonged to no longer exists.",
            evaluated_at=context.evaluated_at, semantic_version=context.semantic_version,
        )

    # -- pin every input durably before reading anything (§4) ---------------
    holder = uuid.uuid4()
    resolved: dict[str, DatasetVersion] = {}
    for pin in context.inputs:
        if pin.version_number is None:
            return _unavailable(
                original, context,
                f"Dataset {pin.dataset_id} had no recorded version when the run read it, "
                "so that input cannot be pinned.",
            )
        version = _find_version(db, project_id, pin)
        if version is None:
            return _unavailable(
                original, context,
                f"Version {pin.version_number} of dataset {pin.dataset_id} no longer exists "
                "(the dataset or its history was deleted).",
            )
        blocked = unavailable_reason(version)
        if blocked is not None:
            return _unavailable(original, context, blocked)
        if pin.content_hash and version.content_hash and pin.content_hash != version.content_hash:
            # The version row exists but its bytes are not what the run read --
            # a destructive erasure rewrote them. That is a different input.
            return _unavailable(
                original, context,
                f"Version {pin.version_number} of dataset {pin.dataset_id} no longer holds the "
                "bytes the run read (its content was rewritten, e.g. by a destructive erasure); "
                "the original input is gone.",
            )
        try:
            pin_version(
                db, version, holder_kind="replay", holder_id=holder,
                reason=f"replay of run {original.id}",
            )
        except ConflictError as exc:
            return _unavailable(original, context, str(exc.detail))
        resolved[pin.dataset_id] = version
    db.commit()

    base_pin = next((pin for pin in context.inputs if pin.role == "base"), None)
    if base_pin is None:
        release_pins(db, holder_kind="replay", holder_id=holder)
        db.commit()
        return _unavailable(original, context, "The run recorded no base dataset input.")
    base_version = resolved[base_pin.dataset_id]
    step_pins = [pin for pin in context.inputs if pin.role == "step"]
    plan = ReplayPlan(
        original_run_id=original.id,
        evaluated_at=context.evaluated_at,
        steps=list(context.steps),
        base_pin=base_pin,
        base_file_path=base_version.file_path,
        base_file_type=base_version.file_type or "csv",
        step_pins=step_pins,
        step_overrides={
            pin.dataset_id: (resolved[pin.dataset_id].file_path, resolved[pin.dataset_id].file_type or "csv")
            for pin in step_pins
        },
    )

    try:
        outcome = run_saved_transformation_pipeline(
            db,
            project_id=project_id,
            pipeline_id=original.pipeline_id,
            current_user=current_user,
            storage_backend=storage_backend,
            settings=settings,
            notify_on_complete=False,
            replay=plan,
        )
    except ApplicationError as exc:
        release_pins(db, holder_kind="replay", holder_id=holder)
        db.commit()
        return ReplayResult(
            status="failed", original_run_id=original.id,
            reason=f"The replay run failed: {exc.detail}",
            original_output=_pin_dict(context.outputs[0]),
            evaluated_at=context.evaluated_at, semantic_version=context.semantic_version,
        )
    finally:
        # Released either way. A crash before this line leaves the pins open,
        # which keeps data rather than losing it -- the safe direction.
        release_pins(db, holder_kind="replay", holder_id=holder)
        db.commit()

    replay_context = context_from_run(outcome.run.summary_json)
    replay_pin = replay_context.outputs[0] if replay_context and replay_context.outputs else None

    # -- compare against the output the original run published ---------------
    original_pin = context.outputs[0]
    original_version = _find_version(db, project_id, original_pin)
    if original_version is None or unavailable_reason(original_version) is not None:
        return ReplayResult(
            status="unverifiable", original_run_id=original.id, replay_run_id=outcome.run.id,
            replay_dataset_id=outcome.dataset.id,
            reason=(
                unavailable_reason(original_version)
                if original_version is not None
                else "The original run's output version no longer exists, so the replay ran but "
                     "there is nothing recorded to compare it with."
            ),
            original_output=_pin_dict(original_pin), replay_output=_pin_dict(replay_pin),
            evaluated_at=context.evaluated_at, semantic_version=context.semantic_version,
        )

    replay_version = (
        _find_version(db, project_id, replay_pin) if replay_pin is not None else None
    )
    comparison = compare_versions(
        storage_backend, original_version, replay_version,
        original_recorded_hash=original_pin.content_hash,
    )
    status = "equivalent" if comparison.equivalent else "divergent"
    return ReplayResult(
        status=status, original_run_id=original.id, replay_run_id=outcome.run.id,
        replay_dataset_id=outcome.dataset.id,
        reason=None if comparison.equivalent else "; ".join(comparison.differences) or "The results differ.",
        original_output=_pin_dict(original_pin), replay_output=_pin_dict(replay_pin),
        comparison=comparison,
        evaluated_at=context.evaluated_at, semantic_version=context.semantic_version,
    )


# ------------------------------------------------------------- comparison


def compare_versions(
    storage_backend: Any,
    original: DatasetVersion,
    replay: DatasetVersion | None,
    *,
    original_recorded_hash: str | None = None,
) -> ReplayComparison:
    """Result equivalence, defined (§3): same ordered column list, same
    canonical type per column, same row multiset with nulls equal to nulls and
    every value compared in its text rendering. Ordering of rows is NOT part
    of it -- a recipe with no sort has no promised order. Identical digests
    short-circuit; nothing is read."""
    if replay is None:
        return ReplayComparison(
            method="no replay output version was recorded",
            columns_equal=False, types_equal=False, rows_equal=False,
            differences=["the replay published no version"],
        )
    if original.content_hash and original.content_hash == replay.content_hash:
        if original_recorded_hash and original_recorded_hash != original.content_hash:
            # The stored original was rewritten since the run (erasure); its
            # digest matching the replay would be a coincidence, not proof.
            pass
        else:
            return ReplayComparison(
                method="content digests are equal; the artifacts were not read",
                columns_equal=True, types_equal=True, rows_equal=True,
                rows_original=original.row_count, rows_replay=replay.row_count,
            )

    from service_ingestion.parsers import parse_tabular_file

    before = parse_tabular_file(
        file_bytes=storage_backend.read_bytes(original.file_path), file_type=original.file_type or "csv"
    ).dataframe
    after = parse_tabular_file(
        file_bytes=storage_backend.read_bytes(replay.file_path), file_type=replay.file_type or "csv"
    ).dataframe

    differences: list[str] = []
    columns_equal = list(before.columns) == list(after.columns)
    if not columns_equal:
        added = [c for c in after.columns if c not in before.columns]
        removed = [c for c in before.columns if c not in after.columns]
        if added:
            differences.append(f"columns only in the replay: {', '.join(map(str, added))}")
        if removed:
            differences.append(f"columns only in the original: {', '.join(map(str, removed))}")
        if not added and not removed:
            differences.append("the columns are the same set in a different order")

    types_equal = True
    original_types = _column_types(original.schema_json)
    replay_types = _column_types(replay.schema_json)
    for name, kind in original_types.items():
        other = replay_types.get(name)
        if other is not None and other != kind:
            types_equal = False
            differences.append(f"type of {name}: {kind} in the original, {other} in the replay")

    shared = [c for c in before.columns if c in after.columns]
    left = _row_multiset(before[shared])
    right = _row_multiset(after[shared])
    only_left = sum((left - right).values())
    only_right = sum((right - left).values())
    rows_equal = only_left == 0 and only_right == 0 and len(before) == len(after)
    if not rows_equal:
        differences.append(
            f"rows differ: {only_left} only in the original, {only_right} only in the replay "
            f"({len(before)} vs {len(after)} rows)"
        )

    return ReplayComparison(
        method="columns, canonical types and the row multiset were compared; values as text, null equal to null, order ignored",
        columns_equal=columns_equal, types_equal=types_equal, rows_equal=rows_equal,
        rows_original=int(len(before)), rows_replay=int(len(after)),
        differences=differences,
    )


def _column_types(schema_json: dict[str, Any] | None) -> dict[str, str]:
    columns = (schema_json or {}).get("columns") or []
    out: dict[str, str] = {}
    for column in columns:
        if isinstance(column, dict) and column.get("name") is not None:
            kind = column.get("canonical_type") or column.get("inferred_type") or ""
            out[str(column["name"])] = str(kind)
    return out


def _row_multiset(frame: pd.DataFrame) -> Counter:
    def cell(value: Any) -> str | None:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return str(value)

    return Counter(tuple(cell(v) for v in row) for row in frame.itertuples(index=False, name=None))


# --------------------------------------------------------------- helpers


def _find_version(db: Session, project_id: uuid.UUID, pin: VersionPin) -> DatasetVersion | None:
    if pin.version_number is None:
        return None
    try:
        dataset_id = uuid.UUID(pin.dataset_id)
    except ValueError:
        return None
    return db.scalar(
        select(DatasetVersion)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(
            Dataset.project_id == project_id,
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.version_number == pin.version_number,
        )
    )


def _pin_dict(pin: VersionPin | None) -> dict[str, Any] | None:
    return pin.to_dict() if pin is not None else None


def _unavailable(run, context: ExecutionContext, reason: str) -> ReplayResult:
    return ReplayResult(
        status="unavailable", original_run_id=run.id, reason=reason,
        original_output=_pin_dict(context.outputs[0]) if context.outputs else None,
        evaluated_at=context.evaluated_at, semantic_version=context.semantic_version,
    )
