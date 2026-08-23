from __future__ import annotations

from typing import Any

import pandas as pd

from service_transformations.steps.common import ensure_columns_exist, ensure_config_keys, require_string_list
from shared_python.errors import BadRequestError


def validate_unpivot(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[list[str], list[str], str, str]:
    config = ensure_config_keys(
        config,
        required={"id_columns"},
        optional={"value_columns", "variable_column_name", "value_column_name"},
    )

    id_columns = require_string_list(config["id_columns"], field_name="config.id_columns", allow_empty=True)
    ensure_columns_exist(dataframe, id_columns, field_name="config.id_columns")

    value_columns = require_string_list(
        config.get("value_columns", []), field_name="config.value_columns", allow_empty=True
    )
    if value_columns:
        ensure_columns_exist(dataframe, value_columns, field_name="config.value_columns")
        overlap = sorted(set(value_columns) & set(id_columns))
        if overlap:
            raise BadRequestError(f"Column(s) appear in both id_columns and value_columns: {', '.join(overlap)}.")
    else:
        # Default to "everything that is not an identifier".
        value_columns = [str(column) for column in dataframe.columns if str(column) not in id_columns]
        if not value_columns:
            raise BadRequestError("There are no value columns left to unpivot.")

    variable_name = config.get("variable_column_name", "variable")
    value_name = config.get("value_column_name", "value")
    for label, name in (("variable_column_name", variable_name), ("value_column_name", value_name)):
        if not isinstance(name, str) or not name.strip():
            raise BadRequestError(f"config.{label} must be a non-empty string.")

    variable_name, value_name = variable_name.strip(), value_name.strip()
    if variable_name == value_name:
        raise BadRequestError("variable_column_name and value_column_name must differ.")
    collisions = sorted({variable_name, value_name} & set(id_columns))
    if collisions:
        raise BadRequestError(f"Output name(s) collide with id_columns: {', '.join(collisions)}.")

    return id_columns, value_columns, variable_name, value_name


def apply_unpivot(dataframe: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    id_columns, value_columns, variable_name, value_name = validate_unpivot(dataframe, config)

    melted = dataframe.melt(
        id_vars=id_columns,
        value_vars=value_columns,
        var_name=variable_name,
        value_name=value_name,
    )
    return melted.reset_index(drop=True), []
