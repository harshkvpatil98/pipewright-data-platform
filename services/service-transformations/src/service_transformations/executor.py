from __future__ import annotations

import pandas as pd

from service_transformations.schemas import TransformationStep
from service_transformations.steps import STEP_APPLY_FUNCTIONS
from service_transformations.validators import validate_steps_json
from shared_python.errors import BadRequestError


def apply_transformation_steps(
    dataframe: pd.DataFrame,
    raw_steps: list[object],
) -> tuple[pd.DataFrame, list[str]]:
    """Apply ordered steps in memory. Validates structure and each step against the working frame."""
    steps = validate_steps_json(raw_steps)
    working = dataframe.copy()
    warnings: list[str] = []

    for step in steps:
        working, step_warnings = apply_single_step(working, step)
        warnings.extend(step_warnings)

    return working, warnings


def apply_single_step(dataframe: pd.DataFrame, step: TransformationStep) -> tuple[pd.DataFrame, list[str]]:
    handler = STEP_APPLY_FUNCTIONS.get(step.step_type)
    if handler is None:
        raise BadRequestError(f'Unsupported transformation step "{step.step_type}".')
    return handler(dataframe, step.config)
