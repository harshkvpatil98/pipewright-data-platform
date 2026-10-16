"""Reading back exactly what Pipewright wrote (E2).

A recipe's result, the rows a check sets aside, an import from a connection
and a live feed are kept as CSV written from a frame Pipewright held, and
read again by the next recipe, a check or a download. Read as an upload is,
with its types guessed and the words that conventionally mean "no value"
made empty, they came back changed: a fill with "unknown" was empty again,
"NA" for North America was empty, -99 was empty, and text that looked like a
number became one (found converting a dbt model in E2, X3).

``written_spec`` is the spec that reads such a file back as it was written:
each column in the type the frame held it, and only an empty cell empty.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import infer_pw_type
from shared_python.types.lattice import Kind

_WHOLE = {Kind.INT8, Kind.INT16, Kind.INT32, Kind.INT64, Kind.UINT8, Kind.UINT16, Kind.UINT32, Kind.UINT64}
_DECIMAL = {Kind.FLOAT32, Kind.FLOAT64, Kind.DECIMAL}


def written_spec(data: bytes, frame: pd.DataFrame) -> dict[str, Any] | None:
    """The spec that reads ``data``, written from ``frame``, back as ``frame`` was."""
    from service_ingestion.sniff import analyse
    from service_ingestion.sniff.pipeline import ANALYSIS_ROWS
    from service_ingestion.spec import WRITTEN_BY_PIPEWRIGHT, from_analysis, validate

    if not data.strip() or len(frame.columns) == 0:
        return None
    try:
        # The read options (delimiter, quoting, header) from a sample: the
        # types come from the frame itself.
        result = analyse(data, file_name="written.csv", content_type="text/csv", overrides={"format": "csv"},
                         limit=ANALYSIS_ROWS)
    except BadRequestError:
        return None
    spec = from_analysis(result, derived_from=WRITTEN_BY_PIPEWRIGHT)
    if len(spec.columns) != len(frame.columns):
        return None
    for column, held in zip(spec.columns, frame.columns):
        column.null_tokens = []
        column.decimal, column.thousands = ".", None
        kind = infer_pw_type(frame[held]).kind
        if kind in _WHOLE:
            column.type, column.date_format = "int64", None
        elif kind in _DECIMAL:
            column.type, column.date_format = "float64", None
        elif kind is Kind.BOOLEAN:
            column.type, column.date_format = "boolean", None
        elif kind is Kind.DATE:
            column.type, column.date_format = "date", "ISO8601"
        elif kind is Kind.TIMESTAMP:
            column.type, column.date_format = str(infer_pw_type(frame[held])), "ISO8601"
        else:
            # Text, and what a CSV can only hold as text (lists, records, an
            # empty column): exactly the characters written.
            column.type, column.date_format = "string", None
    validate(spec)
    return spec.to_dict()
