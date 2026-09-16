"""SAS and Stata files, whose labels are the point.

A statistical file carries two things a CSV does not: a **variable label**
("Respondent's annual household income before tax") and **value labels**
(`1 = "Strongly agree"`). Discarding them, which every generic reader does,
turns a survey into a table of integers whose meaning lives in a separate
codebook nobody has.

So the labels are read and kept as column metadata, and value labels are
reported so a `map_values` step can apply them if the user wants words rather
than codes — which is a transformation, not a reading decision, because the
codes are what the file says.

SPSS `.sav` needs `pyreadstat`, which is not installed here; the format
detector refuses it by name rather than letting it fail obscurely.
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_ingestion.readers.base import ReadResult, normalise_columns
from service_ingestion.sniff.evidence import Finding, certain


def read_sas(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    try:
        frame = pd.read_sas(io.BytesIO(payload), format="sas7bdat", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - any failure is "not a SAS file we can read"
        raise BadRequestError(f"Could not read this as a SAS dataset: {exc}") from exc

    if limit:
        frame = frame.head(limit)
    return ReadResult(
        frame=normalise_columns(frame),
        options={},
        findings=[
            certain(
                "format",
                "sas",
                f"A SAS dataset of {len(frame.columns)} variable(s).",
                evidence=[str(column) for column in frame.columns][:8],
            )
        ],
    )


def read_stata(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    try:
        reader = pd.io.stata.StataReader(io.BytesIO(payload))
        frame = reader.read()
        variable_labels = reader.variable_labels()
        value_labels = reader.value_labels()
    except Exception as exc:  # noqa: BLE001
        raise BadRequestError(f"Could not read this as a Stata dataset: {exc}") from exc

    if limit:
        frame = frame.head(limit)

    findings: list[Finding] = [
        certain(
            "format",
            "stata",
            f"A Stata dataset of {len(frame.columns)} variable(s).",
        )
    ]

    described = {name: label for name, label in (variable_labels or {}).items() if label}
    if described:
        findings.append(
            certain(
                "variable_labels",
                described,
                (
                    f"{len(described)} variable(s) carry a description. They are kept as "
                    "column documentation rather than discarded."
                ),
                evidence=[f"{name}: {label}" for name, label in list(described.items())[:5]],
            )
        )

    if value_labels:
        findings.append(
            certain(
                "value_labels",
                {name: len(mapping) for name, mapping in value_labels.items()},
                (
                    f"{len(value_labels)} column(s) have coded values with labels "
                    "(1 = 'Strongly agree'). The codes are what the file holds; use a "
                    "map-values step to substitute the labels."
                ),
                evidence=[
                    f"{name}: " + ", ".join(f"{code}={label}" for code, label in list(mapping.items())[:3])
                    for name, mapping in list(value_labels.items())[:4]
                ],
            )
        )

    return ReadResult(
        frame=normalise_columns(frame),
        options={},
        findings=findings,
        warnings=[],
    )
