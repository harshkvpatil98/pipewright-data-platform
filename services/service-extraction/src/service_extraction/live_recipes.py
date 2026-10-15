"""Live recipes: streaming transforms on a live source's events (D1, L4).

A live recipe runs on each batch of events after it is stored:

1. *Steps* from a saved recipe, which must work row by row: a batch is a
   handful of rows, so a step that needs every row (sort, deduplicate,
   aggregate, pivot) would mean something different on each batch. Those are
   refused with the step named; a window does that job here.
2. *Look up* (the stream-table join): each event matched to a dataset's rows
   on one or more columns, chosen columns brought along, the dataset read as
   it is when the batch runs (with the policies of whoever made the live
   recipe applied, as on any path that hands rows to a person).
3. *Summarise by time* (`live.windows`), or, without a window, the events
   themselves after steps and lookup.

With a window, the state (open windows, the watermark), the last event
processed and every result the batch changed are saved in one transaction:
a batch repeated after a crash starts from the state saved with the results
before it, so no event is counted twice. The output dataset is written at
the source's save interval from the results, open windows marked "still
open". Without a window, the transformed events are appended to the output
dataset with the last event in it, also in one transaction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_extraction.live import windows as engine
from service_extraction.models import LiveRecipe, LiveRecipeResult, StreamEvent, StreamSource
from service_extraction.schemas import (
    LiveRecipeCreate,
    LiveRecipeListResponse,
    LiveRecipeRead,
    LiveRecipeResultRead,
    LiveRecipeResultsResponse,
    LiveRecipeUpdate,
)
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, NotFoundError
from shared_python.logging import get_logger
from shared_python.words import count_of

logger = get_logger(__name__)

#: Events one batch takes.
BATCH = 5_000
#: Windows an output keeps: older final ones leave the output (they stay in its
#: earlier versions), so a save never grows with every window there ever was.
KEEP_WINDOWS = timedelta(days=30)
#: Step types that work one row at a time, whatever the other rows are.
ROW_WISE_STEPS = frozenset({
    "rename_columns", "select_columns", "drop_columns", "cast_column_types", "derive_column", "filter_rows",
    "replace_values", "trim_strings", "parse_dates", "split_column", "drop_null_rows", "unpivot",
})
#: The one fill that does not look at other rows.
ROW_WISE_FILL = "constant"
OP_WORDS = {"count": "count", "sum": "sum", "average": "average", "lowest": "lowest", "highest": "highest",
            "first": "first", "last": "last"}


def _now() -> datetime:
    return datetime.now(UTC)


def _get(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, recipe_id: uuid.UUID) -> LiveRecipe:
    recipe = db.scalar(select(LiveRecipe).where(LiveRecipe.id == recipe_id, LiveRecipe.source_id == source_id,
                                                LiveRecipe.project_id == project_id))
    if recipe is None:
        raise NotFoundError("Live recipe not found.")
    return recipe


def _source(db: Session, project_id: uuid.UUID, source_id: uuid.UUID) -> StreamSource:
    source = db.scalar(select(StreamSource).where(StreamSource.id == source_id, StreamSource.project_id == project_id))
    if source is None:
        raise NotFoundError("Live feed not found.")
    return source


def _step_words(step_type: str) -> str:
    return step_type.replace("_", " ")


def step_problem(steps: list[dict[str, Any]]) -> str | None:
    """Why these steps cannot run on a batch at a time, or None when they can."""
    for index, step in enumerate(steps, start=1):
        kind = str(step.get("step_type") or step.get("type") or "")
        config = step.get("config") or {}
        if kind == "tool":
            continue  # checked against the first batch, where its columns are known
        if kind == "fill_nulls" and config.get("strategy") == ROW_WISE_FILL:
            continue
        if kind not in ROW_WISE_STEPS:
            return (f"Step {index} ({_step_words(kind)}) needs every row at once, and a live recipe sees a batch at "
                    "a time. Summarise by time instead, or keep it in a recipe that runs on the saved data.")
    return None


def _row_wise(node) -> bool:
    from service_transformations.ir.nodes import Extension, Filter, Project, Scan

    if isinstance(node, (Scan,)):
        return True
    if isinstance(node, Extension):
        return node.name in ("split_column", "unpivot") and _row_wise(node.input)
    if isinstance(node, (Project, Filter)):
        return _row_wise(node.input)
    return False


def _tool_problem(steps: list[dict[str, Any]], sample: pd.DataFrame) -> str | None:
    """A tool step's shape is known once there are columns: refuse one that is not row by row."""
    from service_transformations.executor import apply_single_step
    from service_transformations.tools.apply import build
    from service_transformations.validators import validate_steps_json

    working = sample
    for index, step in enumerate(validate_steps_json(steps), start=1):
        if step.step_type == "tool":
            node = build(working, dict(step.config or {}))
            if not _row_wise(node):
                return (f"Step {index} ({step.config.get('tool')}) needs every row at once, and a live recipe "
                        "sees a batch at a time.")
        working, _ = apply_single_step(working, step)
    return None


def _check_window(window: dict[str, Any] | None, group_by: list[str], measures: list[dict[str, Any]]) -> None:
    if window is None:
        if group_by or measures:
            raise BadRequestError("Grouping and measures need a time window to summarise over.")
        return
    try:
        spec(window).check()
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    if not measures:
        raise BadRequestError("A summary needs at least one measure, such as a count.")
    names = [m.get("name") for m in measures]
    if len(set(names)) != len(names):
        raise BadRequestError("Each measure needs a different name.")
    taken = {"window_start", "window_end", "events", "final", "restated", *group_by}
    for measure in measures:
        if measure.get("op") not in engine.OPS:
            raise BadRequestError(f"A measure is one of {', '.join(engine.OPS)}.")
        if measure.get("op") != "count" and not measure.get("column"):
            raise BadRequestError(f"{measure.get('name')}: name the column to {measure.get('op')}.")
        if measure.get("name") in taken:
            raise BadRequestError(f"{measure.get('name')!r} is already a column of the summary; choose another name.")


def spec(window: dict[str, Any]) -> engine.WindowSpec:
    seconds = lambda key: int(round(float(window.get(key) or 0) * 1000))  # noqa: E731
    return engine.WindowSpec(
        kind=window.get("kind") or "tumbling", size_ms=seconds("size_seconds"), advance_ms=seconds("advance_seconds"),
        gap_ms=seconds("gap_seconds"), lateness_ms=seconds("lateness_seconds"),
        late_policy="restate" if window.get("late") == "restate" else "drop",
        restate_for_ms=seconds("restate_for_seconds"),
    )


def _measures(recipe: LiveRecipe) -> tuple[engine.Measure, ...]:
    return tuple(engine.Measure(str(m["name"]), str(m["op"]), m.get("column") or None) for m in recipe.measures_json or [])


def _describe(recipe: LiveRecipe) -> str:
    """What the live recipe does, in a sentence."""
    parts: list[str] = []
    if recipe.recipe_id:
        parts.append("runs a recipe's steps")
    if recipe.lookup_json:
        parts.append("looks up a dataset")
    window = recipe.window_json
    if window:
        measures = ", ".join(f"{m['name']} ({OP_WORDS.get(m['op'], m['op'])})" for m in recipe.measures_json or [])
        by = f" by {', '.join(recipe.group_by_json)}" if recipe.group_by_json else ""
        if window.get("kind") == "session":
            span = f"sessions that end after {_duration(float(window.get('gap_seconds') or 0))} of quiet"
        elif window.get("kind") == "hopping":
            span = (f"windows of {_duration(float(window.get('size_seconds') or 0))}, a new one every "
                    f"{_duration(float(window.get('advance_seconds') or 0))}")
        elif window.get("kind") == "sliding":
            span = f"the last {_duration(float(window.get('size_seconds') or 0))} at every change"
        else:
            span = f"back-to-back windows of {_duration(float(window.get('size_seconds') or 0))}"
        parts.append(f"summarises{by} over {span}: {measures}")
    if not parts:
        return "Keeps the events as they arrive."
    sentence = ", then ".join(parts)
    return sentence[0].upper() + sentence[1:] + "."


def _duration(seconds: float) -> str:
    if seconds >= 3600 and seconds % 3600 == 0:
        return count_of(int(seconds // 3600), "hour")
    if seconds >= 60 and seconds % 60 == 0:
        return count_of(int(seconds // 60), "minute")
    return count_of(int(seconds), "second")


def _read(db: Session, recipe: LiveRecipe) -> LiveRecipeRead:
    from service_datasets.models import Dataset

    open_windows = int(db.scalar(select(func.count()).select_from(LiveRecipeResult).where(
        LiveRecipeResult.live_recipe_id == recipe.id, LiveRecipeResult.final.is_(False))) or 0)
    state = recipe.state_json or {}
    output = db.get(Dataset, recipe.output_dataset_id) if recipe.output_dataset_id else None
    watermark = state.get("wm")
    return LiveRecipeRead(
        id=recipe.id, source_id=recipe.source_id, name=recipe.name, recipe_id=recipe.recipe_id,
        lookup=recipe.lookup_json, window=recipe.window_json, group_by=list(recipe.group_by_json or []),
        measures=list(recipe.measures_json or []), output_dataset_id=recipe.output_dataset_id,
        output_dataset_name=output.name if output is not None else None, status=recipe.status,
        last_error=recipe.last_error, processed_seq=recipe.processed_seq, events_in=recipe.events_in,
        late_dropped=recipe.late_dropped, late_restated=recipe.late_restated, without_time=recipe.without_time,
        unmatched=recipe.unmatched, open_windows=open_windows,
        complete_up_to=datetime.fromtimestamp(watermark / 1000, tz=UTC) if watermark is not None else None,
        description=_describe(recipe), last_processed_at=recipe.last_processed_at, last_saved_at=recipe.last_saved_at,
        created_at=recipe.created_at, updated_at=recipe.updated_at,
    )


# ------------------------------------------------------------------ CRUD


def list_recipes(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, current_user: UserRead) -> LiveRecipeListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    source = _source(db, project_id, source_id)
    recipes = db.scalars(select(LiveRecipe).where(LiveRecipe.source_id == source.id).order_by(LiveRecipe.created_at)).all()
    return LiveRecipeListResponse(items=[_read(db, r) for r in recipes])


def _validate(db: Session, project_id: uuid.UUID, recipe_id: uuid.UUID | None, lookup: dict[str, Any] | None,
              window: dict[str, Any] | None, group_by: list[str], measures: list[dict[str, Any]]) -> None:
    if recipe_id is not None:
        from service_transformations.models import TransformationPipeline

        recipe = db.scalar(select(TransformationPipeline).where(
            TransformationPipeline.id == recipe_id, TransformationPipeline.project_id == project_id))
        if recipe is None:
            raise NotFoundError("Recipe not found in this project.")
        problem = step_problem(list(recipe.steps_json or []))
        if problem:
            raise BadRequestError(problem)
    if lookup is not None:
        from service_datasets.service import get_dataset_model_for_project

        get_dataset_model_for_project(db, project_id, uuid.UUID(str(lookup["dataset_id"])))
        if not lookup.get("on"):
            raise BadRequestError("Say which event column matches which dataset column.")
        if not lookup.get("columns"):
            raise BadRequestError("Choose at least one column to bring from the dataset.")
    _check_window(window, group_by, measures)


def create_recipe(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, payload: LiveRecipeCreate,
                  current_user: UserRead) -> LiveRecipeRead:
    ensure_owned_project(db, project_id, current_user.id)
    source = _source(db, project_id, source_id)
    lookup = payload.lookup.model_dump(mode="json") if payload.lookup else None
    window = payload.window.model_dump(mode="json") if payload.window else None
    measures = [m.model_dump(mode="json") for m in payload.measures]
    _validate(db, project_id, payload.recipe_id, lookup, window, payload.group_by, measures)
    recipe = LiveRecipe(
        project_id=project_id, source_id=source.id, name=payload.name.strip(), recipe_id=payload.recipe_id,
        lookup_json=lookup, window_json=window, group_by_json=list(payload.group_by), measures_json=measures,
        state_json={}, created_by_user_id=current_user.id,
        # A live recipe starts with the events still kept, so it has something to show at once.
        processed_seq=_oldest_kept(db, source) - 1, saved_seq=_oldest_kept(db, source) - 1,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    return _read(db, recipe)


def _oldest_kept(db: Session, source: StreamSource) -> int:
    oldest = db.scalar(select(func.min(StreamEvent.seq)).where(StreamEvent.source_id == source.id))
    return int(oldest) if oldest is not None else int(source.events_count or 0) + 1


def update_recipe(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, recipe_id: uuid.UUID,
                  payload: LiveRecipeUpdate, current_user: UserRead) -> LiveRecipeRead:
    """Rename, pause or resume. A change to what it computes starts it again
    from the events still kept, because old results would mean something else."""
    ensure_owned_project(db, project_id, current_user.id)
    recipe = _get(db, project_id, source_id, recipe_id)
    if payload.name is not None:
        recipe.name = payload.name.strip()
    if payload.status is not None:
        recipe.status = payload.status
        if payload.status == "active":
            recipe.last_error = None
    if payload.recipe_id is not None or payload.lookup is not None or payload.window is not None \
            or payload.group_by is not None or payload.measures is not None or payload.clear_lookup or payload.clear_recipe:
        recipe_ref = None if payload.clear_recipe else (payload.recipe_id or recipe.recipe_id)
        lookup = None if payload.clear_lookup else (payload.lookup.model_dump(mode="json") if payload.lookup else recipe.lookup_json)
        window = payload.window.model_dump(mode="json") if payload.window else recipe.window_json
        group_by = list(payload.group_by) if payload.group_by is not None else list(recipe.group_by_json or [])
        measures = [m.model_dump(mode="json") for m in payload.measures] if payload.measures is not None \
            else list(recipe.measures_json or [])
        _validate(db, project_id, recipe_ref, lookup, window, group_by, measures)
        recipe.recipe_id, recipe.lookup_json, recipe.window_json = recipe_ref, lookup, window
        recipe.group_by_json, recipe.measures_json = group_by, measures
        _start_again(db, recipe)
    db.commit()
    db.refresh(recipe)
    return _read(db, recipe)


def _start_again(db: Session, recipe: LiveRecipe) -> None:
    source = db.get(StreamSource, recipe.source_id)
    db.execute(sa_delete(LiveRecipeResult).where(LiveRecipeResult.live_recipe_id == recipe.id))
    first = _oldest_kept(db, source) - 1 if source is not None else 0
    recipe.state_json = {}
    recipe.processed_seq = first
    recipe.saved_seq = first
    for counter in ("late_dropped", "late_restated", "without_time", "unmatched", "events_in"):
        setattr(recipe, counter, 0)
    recipe.status = "active"
    recipe.last_error = None
    recipe.results_changed_at = _now()


def start_recipe_again(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, recipe_id: uuid.UUID,
                       current_user: UserRead) -> LiveRecipeRead:
    ensure_owned_project(db, project_id, current_user.id)
    recipe = _get(db, project_id, source_id, recipe_id)
    _start_again(db, recipe)
    db.commit()
    db.refresh(recipe)
    return _read(db, recipe)


def delete_recipe(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, recipe_id: uuid.UUID,
                  current_user: UserRead) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    recipe = _get(db, project_id, source_id, recipe_id)
    db.execute(sa_delete(LiveRecipeResult).where(LiveRecipeResult.live_recipe_id == recipe.id))
    db.delete(recipe)  # its output dataset stays, as it was
    db.commit()


def recipe_results(db: Session, project_id: uuid.UUID, source_id: uuid.UUID, recipe_id: uuid.UUID,
                   current_user: UserRead, *, limit: int = 200) -> LiveRecipeResultsResponse:
    """The latest windows, newest first, open ones included."""
    ensure_owned_project(db, project_id, current_user.id)
    recipe = _get(db, project_id, source_id, recipe_id)
    rows = db.scalars(select(LiveRecipeResult).where(LiveRecipeResult.live_recipe_id == recipe.id)
                      .order_by(LiveRecipeResult.window_end.desc(), LiveRecipeResult.group_key).limit(limit)).all()
    return LiveRecipeResultsResponse(
        recipe=_read(db, recipe),
        group_by=list(recipe.group_by_json or []),
        measures=[m["name"] for m in recipe.measures_json or []],
        items=[LiveRecipeResultRead(window_start=r.window_start, window_end=r.window_end, group=list(r.group_json or []),
                                    values=dict(r.values_json or {}), events=r.events, final=r.final,
                                    restated=r.restated) for r in rows],
    )


# --------------------------------------------------------------- processing


class _Context:
    """What one pass reads once: the recipe's steps and its lookup's rows."""

    def __init__(self, db: Session, source: StreamSource, storage_backend, settings) -> None:
        self.db, self.source, self.storage, self.settings = db, source, storage_backend, settings
        self._lookups: dict[tuple[str, str], pd.DataFrame] = {}

    def steps(self, recipe: LiveRecipe) -> list[dict[str, Any]]:
        if recipe.recipe_id is None:
            return []
        from service_transformations.models import TransformationPipeline

        found = self.db.get(TransformationPipeline, recipe.recipe_id)
        if found is None:
            raise BadRequestError("The recipe whose steps this live recipe runs has been deleted.")
        return list(found.steps_json or [])

    def lookup_rows(self, recipe: LiveRecipe) -> pd.DataFrame:
        from service_datasets.service import get_dataset_model_for_project
        from service_enterprise.policy_view import Reader, narrow_frame
        from service_extraction.streams import _actor
        from service_ingestion.read_copy import frame_of

        lookup = recipe.lookup_json or {}
        dataset = get_dataset_model_for_project(self.db, recipe.project_id, uuid.UUID(str(lookup["dataset_id"])))
        key = (str(dataset.id), str(dataset.file_path))
        if key not in self._lookups:
            if not dataset.file_path:
                raise BadRequestError(f"{dataset.name} has no data to look up yet.")
            payload = self.storage.read_bytes(dataset.file_path)
            frame = frame_of(self.storage, dataset.file_path, payload, file_type=dataset.file_type or "csv",
                             spec=dataset.ingest_spec_json)
            maker = _actor(self.db, self.source)
            if recipe.created_by_user_id:
                from service_auth.models import User

                user = self.db.get(User, recipe.created_by_user_id)
                if user is not None and user.is_active:
                    maker = UserRead.model_validate(user)
            reader = Reader.for_user(self.db, recipe.project_id, maker)
            self._lookups[key] = narrow_frame(self.db, recipe.project_id, dataset.id, reader, frame)
        return self._lookups[key]


def _transform(context: _Context, recipe: LiveRecipe, events: list[StreamEvent]) -> pd.DataFrame:
    """A batch of events after the recipe's steps and its lookup."""
    from service_extraction.streams import events_frame, typed
    from service_transformations.executor import apply_transformation_steps

    frame = typed(events_frame(context.source, events))
    steps = context.steps(recipe)
    if steps:
        problem = step_problem(steps) or _tool_problem(steps, frame.head(20))
        if problem:
            raise BadRequestError(problem)
        frame, _ = apply_transformation_steps(frame, steps)
    if recipe.lookup_json:
        frame = _look_up(context, recipe, frame)
    return frame.reset_index(drop=True)


def _look_up(context: _Context, recipe: LiveRecipe, frame: pd.DataFrame) -> pd.DataFrame:
    from service_extraction.streams import _key_text

    lookup = recipe.lookup_json or {}
    pairs = [(str(p["event"]), str(p["dataset"])) for p in lookup.get("on") or []]
    rows = context.lookup_rows(recipe)
    wanted = [str(c) for c in lookup.get("columns") or []]
    missing = [c for c, _ in pairs if c not in frame.columns]
    if missing:
        raise BadRequestError(f"The events have no column {', '.join(missing)} to look up by.")
    missing = [d for _, d in pairs if d not in rows.columns] + [c for c in wanted if c not in rows.columns]
    if missing:
        raise BadRequestError(f"The lookup dataset has no column {', '.join(missing)} (it may be hidden from you).")
    keys = [f"__key_{i}" for i in range(len(pairs))]
    right = rows[[d for _, d in pairs] + [c for c in wanted if c not in {d for _, d in pairs}]].copy()
    for name, (_, column) in zip(keys, pairs, strict=True):
        right[name] = right[column].map(_key_text)
    # The first matching row, as a lookup should: never more rows than events.
    right = right.drop_duplicates(subset=keys, keep="first")
    renamed = {c: (c if c not in frame.columns else f"{c}_looked_up") for c in wanted}
    right = right[keys + wanted].rename(columns=renamed)
    left = frame.copy()
    for name, (column, _) in zip(keys, pairs, strict=True):
        left[name] = left[column].map(_key_text)
    merged = left.merge(right, on=keys, how="left", indicator="__matched")
    matched = merged["__matched"] == "both"
    recipe.unmatched = int(recipe.unmatched or 0) + int((~matched).sum())
    if not lookup.get("keep_unmatched", True):
        merged = merged[matched]
    return merged.drop(columns=keys + ["__matched"])


def _times(series: pd.Series) -> pd.Series:
    """Event times as whole milliseconds since 1970, or NA where unreadable.
    Numbers are seconds since 1970, or milliseconds when that large."""
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        numbers = pd.to_numeric(series, errors="coerce")
        scale = numbers.where(numbers.abs() < 1e11, numbers / 1000)
        return (scale * 1000).round().astype("Int64")
    parsed = pd.to_datetime(series, utc=True, errors="coerce", format="mixed")
    out = pd.Series(pd.NA, index=series.index, dtype="Int64")
    ok = parsed.notna()
    out[ok] = (parsed[ok].astype("int64") // 1_000_000).astype("int64")
    return out


def _plain(value: Any) -> Any:
    from service_extraction.live.base import plain

    if value is None or (isinstance(value, float) and value != value):
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()  # numpy scalars
    if value is pd.NA or value is pd.NaT:
        return None
    return plain(value)


def _upsert(db: Session, recipe: LiveRecipe, outcome: engine.Outcome) -> None:
    for start, end, gkey in outcome.removed:
        db.execute(sa_delete(LiveRecipeResult).where(
            LiveRecipeResult.live_recipe_id == recipe.id, LiveRecipeResult.group_key == gkey,
            LiveRecipeResult.window_start == _when(start), LiveRecipeResult.window_end == _when(end)))
    now = _now()
    for row in outcome.rows:
        existing = db.scalar(select(LiveRecipeResult).where(
            LiveRecipeResult.live_recipe_id == recipe.id, LiveRecipeResult.group_key == row.group_key,
            LiveRecipeResult.window_start == _when(row.start_ms), LiveRecipeResult.window_end == _when(row.end_ms)))
        values = {k: _plain(v) for k, v in row.values.items()}
        if existing is None:
            db.add(LiveRecipeResult(
                live_recipe_id=recipe.id, window_start=_when(row.start_ms), window_end=_when(row.end_ms),
                group_key=row.group_key, group_json=[_plain(g) for g in row.group], values_json=values,
                events=row.events, final=row.final, restated=row.restated, updated_at=now))
        else:
            existing.values_json = values
            existing.events = row.events
            existing.final = row.final
            existing.restated = int(existing.restated or 0) + row.restated
            existing.updated_at = now
    db.flush()


def _when(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def process_recipe(db: Session, context: _Context, recipe: LiveRecipe, *, budget_batches: int = 10) -> int:
    """Run the live recipe over the events it has not seen yet, a batch per transaction."""
    if not recipe.window_json:
        return 0  # without a window, the output is made when the source saves
    measures = _measures(recipe)
    window = spec(recipe.window_json)
    group_by = list(recipe.group_by_json or [])
    time_column = (recipe.window_json or {}).get("time_column") or "received_at"
    done = 0
    for _ in range(budget_batches):
        events = list(db.scalars(select(StreamEvent).where(
            StreamEvent.source_id == recipe.source_id, StreamEvent.seq > recipe.processed_seq)
            .order_by(StreamEvent.seq).limit(BATCH)).all())
        if not events:
            break
        frame = _transform(context, recipe, events)
        last_seq = events[-1].seq
        batch: list[engine.Event] = []
        if not frame.empty:
            needed = [time_column, *group_by] + [m.column for m in measures if m.column]
            missing = sorted({c for c in needed if c not in frame.columns})
            if missing:
                raise BadRequestError(f"The events have no column {', '.join(missing)}.")
            times = _times(frame[time_column])
            recipe.without_time = int(recipe.without_time or 0) + int(times.isna().sum())
            columns = list(dict.fromkeys(m.column for m in measures if m.column))
            seqs = frame["seq"] if "seq" in frame.columns else pd.Series(range(len(frame)))
            for index in frame.index[times.notna()]:
                batch.append(engine.Event(
                    time_ms=int(times[index]),
                    group=tuple(_plain(frame.at[index, g]) for g in group_by),
                    values={c: _plain(frame.at[index, c]) for c in columns},
                    seq=int(seqs[index]),
                ))
        outcome = engine.process(recipe.state_json or {}, batch, window, measures)
        _upsert(db, recipe, outcome)
        recipe.state_json = outcome.state
        recipe.processed_seq = last_seq
        recipe.events_in = int(recipe.events_in or 0) + len(batch)
        recipe.late_dropped = int(recipe.late_dropped or 0) + outcome.late_dropped
        recipe.late_restated = int(recipe.late_restated or 0) + outcome.late_restated
        recipe.last_processed_at = _now()
        if outcome.rows or outcome.removed:
            recipe.results_changed_at = _now()
        db.commit()  # the state, the results and the position together
        done += len(events)
        if len(events) < BATCH:
            break
    return done


def process_source(db: Session, source: StreamSource, *, storage_backend, settings) -> int:
    """Every active live recipe of the source; one that fails is stopped with
    the reason and the others go on."""
    context = _Context(db, source, storage_backend, settings)
    total = 0
    for recipe_id in db.scalars(select(LiveRecipe.id).where(
            LiveRecipe.source_id == source.id, LiveRecipe.status == "active")).all():
        recipe = db.get(LiveRecipe, recipe_id)
        try:
            total += process_recipe(db, context, recipe)
        except Exception as exc:  # noqa: BLE001 - recorded on the live recipe
            db.rollback()
            _stop(db, recipe_id, exc)
    return total


def _stop(db: Session, recipe_id: uuid.UUID, exc: Exception) -> None:
    recipe = db.get(LiveRecipe, recipe_id)
    if recipe is None:
        return
    recipe.status = "failed"
    recipe.last_error = (str(getattr(exc, "detail", "")) or f"{exc.__class__.__name__}: {exc}")[:1000]
    db.commit()
    logger.warning("live_recipe_stopped recipe_id=%s error=%s", recipe_id, recipe.last_error)


# ------------------------------------------------------------------ saving


def has_unsaved(db: Session, source: StreamSource) -> bool:
    for recipe in db.scalars(select(LiveRecipe).where(LiveRecipe.source_id == source.id, LiveRecipe.status == "active")).all():
        if recipe.window_json:
            changed, saved = recipe.results_changed_at, recipe.last_saved_at
            if changed is not None and (saved is None or _aware(changed) > _aware(saved)):
                return True
        elif int(source.events_count or 0) > int(recipe.saved_seq or 0):
            return True
    return False


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def results_frame(db: Session, recipe: LiveRecipe) -> pd.DataFrame:
    group_by = list(recipe.group_by_json or [])
    names = [m["name"] for m in recipe.measures_json or []]
    rows = db.scalars(select(LiveRecipeResult).where(LiveRecipeResult.live_recipe_id == recipe.id)
                      .order_by(LiveRecipeResult.window_start, LiveRecipeResult.window_end,
                                LiveRecipeResult.group_key)).all()
    records = []
    for row in rows:
        record: dict[str, Any] = {"window_start": _aware(row.window_start).isoformat(),
                                  "window_end": _aware(row.window_end).isoformat()}
        for name, value in zip(group_by, list(row.group_json or []) + [None] * len(group_by), strict=False):
            record[name] = value
        for name in names:
            record[name] = (row.values_json or {}).get(name)
        record.update({"events": row.events, "final": bool(row.final), "restated": int(row.restated or 0)})
        records.append(record)
    columns = ["window_start", "window_end", *group_by, *names, "events", "final", "restated"]
    return pd.DataFrame.from_records(records, columns=columns)


def save_outputs(db: Session, source: StreamSource, *, storage_backend, settings) -> int:
    """Write each live recipe's output dataset; returns how many were written."""
    from service_extraction.streams import _append_csv, _previous_text, publish_frame

    written = 0
    context = _Context(db, source, storage_backend, settings)
    upto = int(source.events_count or 0)
    for recipe_id in db.scalars(select(LiveRecipe.id).where(
            LiveRecipe.source_id == source.id, LiveRecipe.status == "active")).all():
        recipe = db.get(LiveRecipe, recipe_id)
        try:
            name = f"{recipe.name} (live)"
            if recipe.window_json:
                old = db.execute(sa_delete(LiveRecipeResult).where(
                    LiveRecipeResult.live_recipe_id == recipe.id, LiveRecipeResult.final.is_(True),
                    LiveRecipeResult.window_end < _now() - KEEP_WINDOWS)).rowcount
                if old:
                    recipe.results_changed_at = _now()
                changed, saved = recipe.results_changed_at, recipe.last_saved_at
                if changed is None or (saved is not None and _aware(changed) <= _aware(saved)):
                    continue
                dataset = publish_frame(db, source, dataset_id=recipe.output_dataset_id, name=name,
                                        frame=results_frame(db, recipe), storage_backend=storage_backend,
                                        settings=settings, source_name=f"{source.name}: {recipe.name}")
            else:
                events = list(db.scalars(select(StreamEvent).where(
                    StreamEvent.source_id == source.id, StreamEvent.seq > recipe.saved_seq, StreamEvent.seq <= upto)
                    .order_by(StreamEvent.seq)).all())
                if not events:
                    continue
                frame = _transform(context, recipe, events)
                from service_datasets.service import get_dataset_model_for_project

                current = get_dataset_model_for_project(db, source.project_id, recipe.output_dataset_id) \
                    if recipe.output_dataset_id else None
                data = _append_csv(_previous_text(storage_backend, current), frame)
                dataset = publish_frame(db, source, dataset_id=recipe.output_dataset_id, name=name, csv_bytes=data,
                                        storage_backend=storage_backend, settings=settings,
                                        source_name=f"{source.name}: {recipe.name}")
                recipe.saved_seq = upto
                recipe.events_in = int(recipe.events_in or 0) + len(events)
            recipe.output_dataset_id = dataset.id
            recipe.last_saved_at = _now()
            db.commit()
            written += 1
        except Exception as exc:  # noqa: BLE001 - recorded on the live recipe
            db.rollback()
            _stop(db, recipe_id, exc)
    return written

