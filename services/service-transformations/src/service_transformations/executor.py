"""Run transformation steps -- through the relational IR, and only through it.

Phase 08 built the IR and proved, step by step, that it means exactly what the
original per-step handlers meant (``test_ir_from_steps.py``). Both executors
then ran side by side until the cutover was made deliberately; this module is
that cutover (P9). Every step now becomes an IR node over a ``Scan`` of the
working frame and the pandas backend executes it. There is one executor, and
the differential suite keeps the original handlers as the oracle it is
measured against.

What the algebra does not model stays runnable as an ``Extension`` whose
handler is the original step function: ``split_column``, ``pivot`` and
``unpivot`` (reshapes that produce columns from data) and ``join_datasets`` /
``union_datasets`` (whose suffix, right-column selection, cartesian guard and
column strategies are richer than a bare ``Join``/``SetOp``). They never push
down, and they say so in the plan; they are not approximated as something
close-but-different.

Warnings the original handlers produced still reach the person: Extension
handlers report through ``pandas_backend.warn``, and for native steps the
executor derives the one warning that matters generically -- a column that
gained empty values on the way through a step that kept every row.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types.inference import infer_pw_type

from service_transformations.ir import pandas_backend
from service_transformations.ir.from_steps import compile_step
from service_transformations.ir.nodes import Extension, IRError, Scan
from service_transformations.schemas import TransformationStep
from service_transformations.steps import (
    CONTEXT_STEP_APPLY_FUNCTIONS,
    STEP_APPLY_FUNCTIONS,
    StepContext,
)
from service_transformations.validators import validate_steps_json

#: The name the working frame is bound to inside the IR tree.
WORKING = "__working__"

#: Steps that ALWAYS run as Extensions backed by their original handler. Other
#: steps fall back to an Extension only for the configurations the compiler
#: does not model (a legacy `expression` on derive_column, a mean fill), and
#: every original handler is registered so that fallback is always runnable.
EXTENSION_BACKED: frozenset[str] = frozenset(
    {"split_column", "pivot", "unpivot", "join_datasets", "union_datasets"}
)

# The StepContext for the step being executed, so a join/union Extension can
# reach the sibling dataset it needs. A contextvar rather than a parameter
# because the backend's extension signature is `(frame, config)` on purpose:
# the IR never learns what a bespoke step needs.
_ACTIVE_CONTEXT: ContextVar[StepContext | None] = ContextVar(
    "pipewright_step_context", default=None
)


def _register_extension_handlers() -> None:
    """Install the original step functions as Extension handlers, once."""

    def single(step_type: str):
        original = STEP_APPLY_FUNCTIONS[step_type]

        def run(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
            result, warnings = original(frame, config)
            for message in warnings:
                pandas_backend.warn(message)
            return result

        return run

    def contextual(step_type: str):
        original = CONTEXT_STEP_APPLY_FUNCTIONS[step_type]

        def run(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
            context = _ACTIVE_CONTEXT.get() or StepContext()
            result, warnings = original(frame, config, context)
            for message in warnings:
                pandas_backend.warn(message)
            return result

        return run

    for step_type in STEP_APPLY_FUNCTIONS:
        if step_type != "tool":  # tools build their own IR; never an Extension by name
            pandas_backend.register_extension(step_type, single(step_type))
    for step_type in CONTEXT_STEP_APPLY_FUNCTIONS:
        pandas_backend.register_extension(step_type, contextual(step_type))


_register_extension_handlers()


@dataclass(frozen=True)
class StepOutcome:
    """What one step did to the frame.

    Collected during the single pass that already happens, so the Studio can
    show "12,400 -> 9,881, -2,519" beside each step without re-running the
    pipeline once per prefix. A step whose effect is invisible is a step nobody
    can debug.
    """

    index: int
    step_type: str
    rows_before: int
    rows_after: int
    columns_before: int
    columns_after: int

    @property
    def row_delta(self) -> int:
        return self.rows_after - self.rows_before

    @property
    def column_delta(self) -> int:
        return self.columns_after - self.columns_before


def scan_of(frame: pd.DataFrame, source: str = WORKING) -> Scan:
    """A `Scan` describing the frame, typed from its contents."""
    return Scan(
        source=source,
        columns=tuple((str(name), infer_pw_type(frame[name])) for name in frame.columns),
    )


def apply_transformation_steps(
    dataframe: pd.DataFrame,
    raw_steps: list[object],
    context: StepContext | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Apply ordered steps in memory. Validates structure and each step against the working frame."""
    working, warnings, _ = apply_transformation_steps_with_outcomes(
        dataframe, raw_steps, context
    )
    return working, warnings


def apply_transformation_steps_with_outcomes(
    dataframe: pd.DataFrame,
    raw_steps: list[object],
    context: StepContext | None = None,
) -> tuple[pd.DataFrame, list[str], list[StepOutcome]]:
    """As above, and report what each step did on the way through."""
    steps = validate_steps_json(raw_steps)
    working = dataframe.copy()
    warnings: list[str] = []
    outcomes: list[StepOutcome] = []

    for index, step in enumerate(steps):
        rows_before = int(len(working))
        columns_before = int(len(working.columns))
        working, step_warnings = apply_single_step(working, step, context)
        warnings.extend(step_warnings)
        outcomes.append(
            StepOutcome(
                index=index,
                step_type=step.step_type,
                rows_before=rows_before,
                rows_after=int(len(working)),
                columns_before=columns_before,
                columns_after=int(len(working.columns)),
            )
        )

    return working, warnings, outcomes


def apply_single_step(
    dataframe: pd.DataFrame,
    step: TransformationStep,
    context: StepContext | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Run one step through the IR and return the frame and its warnings."""
    step_type = step.step_type
    if step_type not in STEP_APPLY_FUNCTIONS and step_type not in CONTEXT_STEP_APPLY_FUNCTIONS:
        raise BadRequestError(f'Unsupported transformation step "{step_type}".')

    config = dict(step.config or {})
    if step_type == "tool":
        # Already the IR path -- a tool builds its own node over a Scan of the
        # frame and the backend runs it -- with tool-aware warnings ("could not
        # read 3 value(s) as a number") that a generic pass would flatten.
        from service_transformations.tools.apply import apply_tool

        return apply_tool(dataframe, config)

    # The original handlers validated a step's config against the frame before
    # doing anything, and their messages name the field that is wrong
    # ("config.columns must be a non-empty list"). The IR compiler reports an
    # unknown column too, but less kindly, so the validators keep the first
    # word -- they are pure functions over (frame, config) and cost nothing.
    _validate_against_frame(dataframe, step_type, config)

    scan = scan_of(dataframe)
    try:
        node = compile_step(scan, step_type, config)
    except IRError as exc:
        raise BadRequestError(str(exc)) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise BadRequestError(
            f'Step "{step_type}" could not be prepared: {exc}'
        ) from exc

    token = _ACTIVE_CONTEXT.set(context)
    try:
        with pandas_backend.warnings_scope() as warnings:
            try:
                result = pandas_backend.execute(node, {WORKING: dataframe})
            except IRError as exc:
                raise BadRequestError(str(exc)) from exc
            except re.error as exc:
                raise BadRequestError(f"That pattern will not compile -- {exc}.") from exc
            except KeyError as exc:
                raise BadRequestError(
                    f'Step "{step_type}" refers to a column that does not exist: {exc}.'
                ) from exc
    finally:
        _ACTIVE_CONTEXT.reset(token)

    result = result.reset_index(drop=True)
    if not isinstance(node, Extension):
        # An Extension ran the original handler, which already said what it
        # had to say; a native node gets the two generic warnings that matter:
        # data lost inside a column, and a step that left nothing at all.
        warnings.extend(_introduced_nulls(dataframe, result))
        if len(dataframe) > 0 and len(result) == 0:
            warnings.append(f"Step '{step_type}' left no rows.")
    return result, warnings


def _step_validators() -> dict[str, Any]:
    """The original per-step validators, by step type. Imported lazily: the
    step modules import the IR, which imports siblings of this module."""
    from service_transformations.steps import (
        aggregate, cast_column_types, derive_column, drop_columns, drop_null_rows,
        fill_nulls, filter_rows, join_datasets, limit_rows, parse_dates, pivot,
        remove_duplicates, rename_columns, replace_values, select_columns, sort_rows,
        split_column, trim_strings, union_datasets, unpivot,
    )

    return {
        "aggregate": aggregate.validate_aggregate,
        "cast_column_types": cast_column_types.validate_cast_column_types,
        "derive_column": derive_column.validate_derive_column,
        "drop_columns": drop_columns.validate_drop_columns,
        "drop_null_rows": drop_null_rows.validate_drop_null_rows,
        "fill_nulls": fill_nulls.validate_fill_nulls,
        "filter_rows": filter_rows.validate_filter_rows,
        "join_datasets": join_datasets.validate_join_datasets,
        "limit_rows": limit_rows.validate_limit_rows,
        "parse_dates": parse_dates.validate_parse_dates,
        "pivot": pivot.validate_pivot,
        "remove_duplicates": remove_duplicates.validate_remove_duplicates,
        "rename_columns": rename_columns.validate_rename_columns,
        "replace_values": replace_values.validate_replace_values,
        "select_columns": select_columns.validate_select_columns,
        "sort_rows": sort_rows.validate_sort_rows,
        "split_column": split_column.validate_split_column,
        "trim_strings": trim_strings.validate_trim_strings,
        "union_datasets": union_datasets.validate_union_datasets,
        "unpivot": unpivot.validate_unpivot,
    }


_VALIDATORS: dict[str, Any] | None = None


def _validate_against_frame(frame: pd.DataFrame, step_type: str, config: dict[str, Any]) -> None:
    """Run the step's own validator, when it has one, for its error messages."""
    global _VALIDATORS
    if _VALIDATORS is None:
        _VALIDATORS = _step_validators()
    validator = _VALIDATORS.get(step_type)
    if validator is None:
        return
    try:
        validator(frame, config)
    except TypeError:
        # A validator that takes the config alone (the union step's does).
        validator(config)


def _introduced_nulls(before: pd.DataFrame, after: pd.DataFrame) -> list[str]:
    """The generic data-quality warning: a step that kept every row but left
    more empty cells behind in a column it did not create. This is what a lossy
    cast, an unparseable date or a formula that could not compute looks like
    from the outside, and it is reported the same way whichever step did it."""
    if len(before) != len(after) or len(after) == 0:
        return []
    messages: list[str] = []
    for column in after.columns:
        if column not in before.columns:
            continue
        gained = int(after[column].isna().sum()) - int(before[column].isna().sum())
        if gained > 0:
            messages.append(
                f"Column '{column}' has {gained} more empty value(s) after this step "
                f"({int(after[column].isna().sum())} of {len(after)} rows are empty now)."
            )
    return messages
