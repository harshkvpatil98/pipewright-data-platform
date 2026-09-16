"""The ingest spec: every decision, written down.

The analysis stage produces one of these. The user reviews it, changes what is
wrong, and only then is anything stored. Next month's file reuses it, so the
semicolon delimiter and the day-first dates do not have to be rediscovered —
and, more to the point, cannot be rediscovered *differently* because next
month's sample happened to contain a value that disambiguated something.

That last point is the reason the spec is stored rather than the inference
repeated. Inference that depends on the data is inference that changes when
the data changes: a column that read as day-first in January because one row
said `15/01` reads as ambiguous in February when no row does. A recorded
decision does not drift.

Applying a spec is the only way rows are materialised, and
:func:`apply` refuses while a blocking question is outstanding. An ambiguous
date format is not a low-confidence guess to proceed with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import lattice as pw

from service_ingestion.sniff import numbers as number_sniff
from service_ingestion.sniff.columns import EXCEL_ERRORS

#: The version of the spec format. Stored with every spec so a spec written
#: today can still be read after the shape changes -- a stored decision that
#: cannot be replayed is not a stored decision.
SPEC_VERSION = 1


@dataclass
class ColumnSpec:
    """How one column is read."""

    name: str
    #: The lattice type, as its string form: "int64", "decimal(12,2)", "date".
    type: str = "string"
    date_format: str | None = None
    decimal: str | None = None
    thousands: str | None = None
    null_tokens: list[str] = field(default_factory=list)
    #: What the column is called in the resulting dataset, when renamed.
    rename: str | None = None
    #: False drops the column entirely.
    include: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "date_format": self.date_format,
            "decimal": self.decimal,
            "thousands": self.thousands,
            "null_tokens": list(self.null_tokens),
            "rename": self.rename,
            "include": self.include,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ColumnSpec:
        return cls(
            name=str(payload["name"]),
            type=str(payload.get("type") or "string"),
            date_format=payload.get("date_format"),
            decimal=payload.get("decimal"),
            thousands=payload.get("thousands"),
            null_tokens=list(payload.get("null_tokens") or []),
            rename=payload.get("rename"),
            include=bool(payload.get("include", True)),
        )


@dataclass
class IngestSpec:
    """Everything needed to read a file the same way twice."""

    format: str
    container: str = "none"
    #: Reader options: delimiter, encoding, sheet, records_path, table…
    options: dict[str, Any] = field(default_factory=dict)
    columns: list[ColumnSpec] = field(default_factory=list)
    version: int = SPEC_VERSION
    #: What the spec was derived from, for the audit trail.
    derived_from: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "format": self.format,
            "container": self.container,
            "options": dict(self.options),
            "columns": [column.to_dict() for column in self.columns],
            "derived_from": self.derived_from,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> IngestSpec:
        version = int(payload.get("version") or SPEC_VERSION)
        if version > SPEC_VERSION:
            raise BadRequestError(
                f"This ingest spec was written by a newer version of the platform "
                f"(v{version}; this one reads v{SPEC_VERSION})."
            )
        return cls(
            format=str(payload.get("format") or "csv"),
            container=str(payload.get("container") or "none"),
            options=dict(payload.get("options") or {}),
            columns=[ColumnSpec.from_dict(item) for item in payload.get("columns") or []],
            version=version,
            derived_from=payload.get("derived_from"),
        )

    #: Keys carried in `options` for reporting only. They are aliases of a real
    #: option and must not be handed back to a reader as if they were settings.
    REPORTING_ONLY = ("sheet_name",)

    @property
    def overrides(self) -> dict[str, Any]:
        """The spec in the shape the analysis stage consumes."""
        return {
            "format": self.format,
            **{
                key: value
                for key, value in self.options.items()
                if key not in self.REPORTING_ONLY
            },
            "columns": {
                column.name: {
                    "date_format": column.date_format,
                    "decimal": column.decimal,
                    "thousands": column.thousands,
                }
                for column in self.columns
            },
        }

    def column(self, name: str) -> ColumnSpec | None:
        return next((column for column in self.columns if column.name == name), None)


def from_analysis(analysis: Any, *, derived_from: str | None = None) -> IngestSpec:
    """Turn what the sniff found into a spec the user can edit."""
    return IngestSpec(
        format=analysis.file_format,
        container=analysis.container,
        options=dict(analysis.read_options),
        columns=[
            ColumnSpec(
                name=profile.name,
                type=str(profile.pw_type),
                date_format=profile.date_format,
                decimal=(profile.number_format or {}).get("decimal"),
                thousands=(profile.number_format or {}).get("thousands"),
                null_tokens=list(profile.null_tokens),
            )
            for profile in analysis.columns
        ],
        derived_from=derived_from,
    )


def unanswered(analysis: Any) -> list[dict[str, Any]]:
    """The questions the file cannot answer, in the shape the API returns."""
    return [finding.to_dict() for finding in analysis.blocked_by]


def apply(frame: pd.DataFrame, spec: IngestSpec) -> tuple[pd.DataFrame, list[str]]:
    """Convert a frame's values according to the spec.

    Returns the converted frame and a note for every column where a value did
    not convert -- because a conversion that silently nulls the rows it could
    not read is how a total stops matching the file it came from.
    """
    out = pd.DataFrame(index=frame.index)
    notes: list[str] = []

    for column_spec in spec.columns:
        if column_spec.name not in frame.columns:
            # A column in the spec that the file no longer has is exactly what
            # a stored spec is for detecting: next month's export changed.
            notes.append(
                f"'{column_spec.name}' is in the saved spec but not in this file."
            )
            continue
        if not column_spec.include:
            continue

        series = frame[column_spec.name]
        converted, failures = _convert(series, column_spec)
        if failures:
            notes.append(
                f"'{column_spec.name}': {len(failures)} value(s) did not read as "
                f"{column_spec.type} and are null — e.g. {', '.join(failures[:3])}."
            )
        out[column_spec.rename or column_spec.name] = converted

    # Columns the file has and the spec does not: kept as text rather than
    # dropped. A new column upstream is information, not an error.
    for name in frame.columns:
        if spec.column(str(name)) is None:
            out[str(name)] = frame[name]
            notes.append(f"'{name}' is in this file but not in the saved spec; kept as text.")

    return out, notes


def _convert(series: pd.Series, column_spec: ColumnSpec) -> tuple[pd.Series, list[str]]:
    """One column's values, in the type the spec says."""
    tokens = {token.lower() for token in column_spec.null_tokens} | {""}
    text = series.astype(str)
    blank = text.str.strip().str.lower().isin(tokens | {"nan", "none"})
    errors = text.str.strip().str.upper().isin(EXCEL_ERRORS)
    usable = ~(blank | errors)

    target = column_spec.type
    failures: list[str] = []

    if target.startswith(("int", "float", "decimal")) or target in ("int64", "float64"):
        decimal = column_spec.decimal or "."
        thousands = column_spec.thousands
        parsed = text.where(usable).map(
            lambda value: (
                number_sniff.parse_number(value, decimal=decimal, thousands=thousands)
                if isinstance(value, str)
                else None
            )
        )
        failures = [
            value for value, ok, got in zip(text, usable, parsed) if ok and got is None
        ][:20]
        if target.startswith("int"):
            # A whole-number column with a null cannot be a numpy int, so the
            # nullable Int64 is used -- silently becoming a float is how ids
            # gain a `.0` and stop matching.
            return parsed.astype("Float64").astype("Int64", errors="ignore"), failures
        return parsed.astype("Float64"), failures

    if target in ("date", "timestamp") or target.startswith("timestamp"):
        fmt = column_spec.date_format
        if not fmt:
            raise BadRequestError(
                f"Column '{column_spec.name}' is typed as a date but no date format is set. "
                "Choose the format before importing."
            )
        parsed = pd.to_datetime(text.where(usable), format=fmt, errors="coerce")
        failures = [
            value for value, ok, got in zip(text, usable, parsed) if ok and pd.isna(got)
        ][:20]
        return (parsed.dt.date if target == "date" else parsed), failures

    if target == "boolean":
        from service_ingestion.sniff.columns import FALSE_TOKENS, TRUE_TOKENS

        lowered = text.str.strip().str.lower()
        parsed = lowered.map(
            lambda value: True if value in TRUE_TOKENS else (False if value in FALSE_TOKENS else None)
        ).where(usable)
        failures = [
            value for value, ok, got in zip(text, usable, parsed) if ok and got is None
        ][:20]
        return parsed.astype("boolean"), failures

    # Text, which is also where an unresolvable column lands. Null tokens still
    # become nulls: "N/A" as a string is a value people then have to filter out.
    return series.where(usable), failures


def validate(spec: IngestSpec) -> None:
    """Refuse a spec that cannot be applied, before anything is written."""
    if spec.format not in _known_formats():
        raise BadRequestError(
            f"'{spec.format}' is not a format this platform reads."
        )
    seen: set[str] = set()
    for column in spec.columns:
        name = column.rename or column.name
        if name in seen:
            raise BadRequestError(
                f"Two columns would both be called '{name}'. Rename one of them."
            )
        seen.add(name)
        if column.type in ("date", "timestamp") and not column.date_format:
            raise BadRequestError(
                f"Column '{column.name}' is typed as a date but no format is set. "
                "An ambiguous date is never assumed — choose day-first or month-first."
            )
        try:
            pw.parse(column.type)
        except Exception as exc:  # noqa: BLE001 - the message names the column
            raise BadRequestError(
                f"Column '{column.name}' has an unknown type '{column.type}'."
            ) from exc


def _known_formats() -> set[str]:
    from service_ingestion import readers

    return set(readers.READERS)
