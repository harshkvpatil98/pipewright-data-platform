from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from service_transformations.schemas import TransformationStep
from service_transformations.steps import (
    CONTEXT_STEP_APPLY_FUNCTIONS,
    STEP_APPLY_FUNCTIONS,
    StepContext,
)
from service_transformations.validators import validate_steps_json
from shared_python.errors import BadRequestError


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
    contextual = CONTEXT_STEP_APPLY_FUNCTIONS.get(step.step_type)
    if contextual is not None:
        # Multi-input steps still run without a caller-provided context; the
        # context itself raises a clear error if a dataset is actually needed.
        return contextual(dataframe, step.config, context or StepContext())

    handler = STEP_APPLY_FUNCTIONS.get(step.step_type)
    if handler is None:
        raise BadRequestError(f'Unsupported transformation step "{step.step_type}".')
    return handler(dataframe, step.config)
