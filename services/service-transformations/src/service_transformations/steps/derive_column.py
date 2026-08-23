from __future__ import annotations

from typing import Any

import pandas as pd

from service_transformations.expressions import evaluate_expression
from service_transformations.steps.common import ensure_config_keys
from shared_python.errors import BadRequestError


def validate_derive_column(
    dataframe: pd.DataFrame, config: dict[str, Any]
) -> tuple[str, str, bool]:
    """Validate a derived column, written in either language.

    Two spellings are supported on purpose:

    ``expression``
        The original Python-ish syntax, ``round(price * quantity, 2)``. Every
        saved pipeline uses it, so it keeps working exactly as before.
    ``formula``
        Spreadsheet syntax, ``=ROUND([price] * [quantity], 2)``. Parses into an
        IR expression, which means it gets type inference, lineage and pushdown.

    Exactly one must be present. Guessing which language a string is written in
    would eventually guess wrong, and silently compute something else.
    """
    config = ensure_config_keys(
        config,
        required={"target_column"},
        optional={"expression", "formula", "overwrite"},
    )

    target = config["target_column"]
    if not isinstance(target, str) or not target.strip():
        raise BadRequestError("config.target_column must be a non-empty string.")
    target = target.strip()

    has_expression = isinstance(config.get("expression"), str) and config["expression"].strip()
    has_formula = isinstance(config.get("formula"), str) and config["formula"].strip()

    if has_expression and has_formula:
        raise BadRequestError(
            "Give either config.expression or config.formula, not both -- "
            "they are different languages and only one can be the answer."
        )
    if not has_expression and not has_formula:
        raise BadRequestError(
            "config.formula (spreadsheet syntax) or config.expression "
            "(the original syntax) is required."
        )

    if has_formula:
        overwrite_formula = config.get("overwrite", False)
        if not isinstance(overwrite_formula, bool):
            raise BadRequestError("config.overwrite must be a boolean.")
        if target in dataframe.columns and not overwrite_formula:
            raise BadRequestError(
                f"Column '{target}' already exists. Set config.overwrite to true to replace it."
            )
        # Parsing here surfaces a typo at validation time rather than on row
        # four million.
        _parse(config["formula"], dataframe)
        return target, config["formula"], overwrite_formula

    expression = config["expression"]

    overwrite = config.get("overwrite", False)
    if not isinstance(overwrite, bool):
        raise BadRequestError("config.overwrite must be a boolean.")

    if target in dataframe.columns and not overwrite:
        raise BadRequestError(
            f"Column '{target}' already exists. Set config.overwrite to true to replace it."
        )

    # Evaluating here surfaces unknown columns and bad syntax at validation time.
    evaluate_expression(dataframe, expression)
    return target, expression, overwrite


def _parse(formula: str, dataframe: pd.DataFrame):
    from service_transformations.formula.parser import parse_formula

    return parse_formula(formula, columns=[str(c) for c in dataframe.columns])


def apply_derive_column(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    target, source, _ = validate_derive_column(dataframe, config)
    warnings: list[str] = []

    if isinstance(config.get("formula"), str) and config["formula"].strip():
        return _apply_formula(dataframe, target, config["formula"])

    expression = source
    result, referenced = evaluate_expression(dataframe, expression)
    working = dataframe.copy()
    working[target] = result

    if not referenced:
        warnings.append(f"Expression for '{target}' references no columns, so every row gets the same value.")
    null_count = int(result.isna().sum())
    if null_count and null_count == len(result) and len(result) > 0:
        warnings.append(f"Expression for '{target}' produced only null values.")

    return working, warnings


def _apply_formula(
    dataframe: pd.DataFrame, target: str, formula: str
) -> tuple[pd.DataFrame, list[str]]:
    """Evaluate a spreadsheet formula into a new column.

    A row that cannot be computed becomes null and is counted, rather than
    failing the run. Excel would put ``#VALUE!`` in the cell, but a text
    sentinel in a numeric column poisons every later sum -- so the value is
    null, and the count is reported where somebody will see it.
    """
    from service_transformations.ir.pandas_backend import evaluate

    expression = _parse(formula, dataframe)
    working = dataframe.copy()
    result = evaluate(expression, working)
    working[target] = result

    warnings: list[str] = []
    referenced = expression.columns_used()
    if not referenced:
        warnings.append(
            f"The formula for '{target}' references no columns, so every row gets the same value."
        )

    if referenced and len(result) > 0:
        # A row that had values going in but no value coming out is a row the
        # formula could not compute -- the number worth reporting.
        inputs_present = working[list(referenced)].notna().all(axis=1)
        eligible = int(inputs_present.sum())
        unresolved = int((inputs_present & result.isna()).sum())
        if unresolved:
            # Counted against the rows that HAD values, not against every row.
            # Saying "the other 1 were fine" when that row's input was empty is
            # not a smaller version of the truth, it is a different claim.
            warnings.append(
                f"The formula for '{target}' could not be computed for "
                f"{unresolved:,} of the {eligible:,} row(s) that had values; "
                "those are null."
            )
        elif eligible == 0:
            warnings.append(
                f"Every row is missing a value the formula for '{target}' needs, "
                "so the whole column is null."
            )

    if len(result) > 0 and int(result.isna().sum()) == len(result) and not warnings:
        warnings.append(f"The formula for '{target}' produced only null values.")

    return working, warnings

