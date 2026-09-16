"""Turning an uploaded file into a table.

This used to be three functions: try three encodings for CSV, take the first
sheet of a workbook, `json_normalize` an array. It is now a thin front door
onto the sniffing pipeline, which is where the real work happens -- but the
signature is unchanged, so every existing caller and test still holds.

What a caller gets that it did not before:

* the **evidence** for every decision, on `metadata["findings"]`, so a run log
  says *why* it read semicolons and a header on line five;
* the **spec**, on `.spec`, which is the same file read the same way next month;
* **warnings** for the things that were true but lossy -- ragged rows skipped,
  other sheets ignored, formula errors found.

A supplied spec wins over anything inferred. That is the whole point of storing
one: inference depends on the data and therefore drifts, while a decision
somebody made does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_ingestion import spec as spec_module
from service_ingestion.sniff import analyse


@dataclass(slots=True)
class ParsedTabularData:
    dataframe: pd.DataFrame
    metadata: dict[str, Any]
    #: The spec that would reproduce this read.
    spec: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def parse_tabular_file(
    *,
    file_bytes: bytes,
    file_type: str,
    file_name: str = "",
    content_type: str = "",
    ingest_spec: dict[str, Any] | None = None,
) -> ParsedTabularData:
    """Read an uploaded file, sniffing whatever the spec does not already say."""
    if not file_bytes:
        raise BadRequestError("The uploaded file is empty.")

    supplied: spec_module.IngestSpec | None = None
    if ingest_spec:
        supplied = spec_module.IngestSpec.from_dict(ingest_spec)
        spec_module.validate(supplied)

    overrides = dict(supplied.overrides) if supplied else {}
    overrides.setdefault("format", _format_hint(file_type, file_name))

    result = analyse(
        file_bytes,
        file_name=file_name or f"upload.{file_type}",
        content_type=content_type,
        overrides=overrides,
        # The whole file. This is materialisation, not a preview -- reading the
        # analysis sample here would import five thousand rows of a file with
        # a million and report success.
        limit=None,
    )

    blocking = result.blocked_by
    if blocking and supplied is None:
        # The file genuinely does not say, and nobody has answered. Refusing is
        # the requirement: a date read as the wrong month produces a table that
        # looks right and is not.
        first = blocking[0]
        raise BadRequestError(
            f"{first.reason} Analyse this file first and choose, or upload it with a "
            "saved ingest spec."
        )

    applied = supplied or spec_module.from_analysis(result, derived_from=file_name)
    frame, notes = spec_module.apply(result.frame, applied)

    metadata: dict[str, Any] = {
        "format": result.file_format,
        "container": result.container,
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "findings": [finding.to_dict() for finding in result.all_findings],
        "needs_review": [finding.stage for finding in result.needs_review],
        "spec_supplied": supplied is not None,
    }
    if result.tables:
        metadata["tables"] = result.tables
    if result.members:
        metadata["archive_members"] = [member.to_dict() for member in result.members]
    # The old contract: these keys were on the metadata and are read by the run
    # summary and its tests.
    metadata.update(
        {key: value for key, value in result.read_options.items() if value is not None}
    )

    return ParsedTabularData(
        dataframe=_normalize_dataframe(frame),
        metadata=metadata,
        spec=applied.to_dict(),
        warnings=[*result.warnings, *notes],
    )


def _format_hint(file_type: str, file_name: str) -> str | None:
    """What the upload's declared type suggests, before the bytes are read.

    A hint rather than an instruction: `detect_format` overrules it when the
    contents disagree, because a workbook renamed `.csv` is common and its
    contents are the truth.
    """
    mapped = {
        "csv": None,  # let the sniffer choose between csv/tsv/psv
        "tsv": "tsv",
        "json": None,  # json vs jsonl is decided from the contents
        "jsonl": "jsonl",
        "ndjson": "jsonl",
        "xlsx": "excel",
        "xlsm": "excel",
        "xls": "excel",
        "xml": "xml",
        "parquet": "parquet",
        "avro": "avro",
        "orc": "orc",
        "sql": "sql_dump",
        "yaml": "yaml",
        "yml": "yaml",
        "txt": None,
        "dat": None,
    }
    return mapped.get(file_type.lower())


def _normalize_dataframe(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Column names usable downstream, and pandas' NA spellings as None.

    Unchanged behaviour from before the sniffing pipeline existed: the rest of
    the platform expects `None` rather than `NaN`/`NaT`/`pd.NA` in a preview.
    """
    normalized = dataframe.copy()
    normalized.columns = [
        str(column).strip() if str(column).strip() else f"column_{index + 1}"
        for index, column in enumerate(normalized.columns)
    ]
    normalized = normalized.astype(object).where(pd.notna(normalized), None)
    return normalized
