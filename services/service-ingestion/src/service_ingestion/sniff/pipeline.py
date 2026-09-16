"""The whole sniff, in the order the roadmap lays it out.

    upload → container → format → encoding → structure
           → types → corrections → preview → confirm → materialise

This module covers everything up to *confirm*. It reads bytes and produces an
:class:`~service_ingestion.spec.IngestSpec` — a complete, explicit description
of how the file should be read — plus the evidence behind every decision in it.
Nothing is stored and nothing is materialised here.

That split is the point of the phase. A spec that can be inspected, edited and
re-applied is what makes ingestion reviewable instead of magic: the user sees
"semicolon delimiter, header on line 5, dates day-first" *before* anything
lands, changes what is wrong, and next month's file reuses the same answers.

**Blocking findings stop the pipeline.** An ambiguous date format is not a
low-confidence guess to proceed with; it is a question only the user can
answer. `AnalysisResult.blocked_by` lists them, and materialising while one is
outstanding is refused in `spec.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from service_ingestion.sniff import containers, delimiter, encoding, header
from service_ingestion.sniff.columns import ColumnProfile, profile_column
from service_ingestion.sniff.evidence import Finding, certain
from service_ingestion.sniff.formats import FormatResult, detect_format

#: Rows read for analysis. Enough to decide a delimiter and a date format,
#: bounded so analysing a 2GB file costs what analysing a 2MB one does.
ANALYSIS_ROWS = 5_000

#: Bytes read from the head of a file for format and encoding detection.
HEAD_BYTES = 1024 * 1024

#: Rows a column's type is decided from, even when the whole file is loaded.
#: Generous because the ambiguous-date scan runs over it: the single value that
#: settles a column can be anywhere, and a small sample is how that gets missed.
TYPE_SAMPLE_ROWS = 50_000


@dataclass
class AnalysisResult:
    """Everything the sniff learned, and what it still needs to be told."""

    #: The frame as it would be read, limited to `ANALYSIS_ROWS`.
    frame: pd.DataFrame
    findings: list[Finding] = field(default_factory=list)
    columns: list[ColumnProfile] = field(default_factory=list)
    #: Filled for archives: each member can become its own dataset.
    members: list[containers.Member] = field(default_factory=list)
    #: Filled where a format holds several tables — Excel sheets, SQL dumps.
    tables: list[str] = field(default_factory=list)
    container: str = "none"
    file_format: str = "csv"
    read_options: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def blocked_by(self) -> list[Finding]:
        """Questions the file cannot answer, so the user must."""
        return [finding for finding in self.all_findings if finding.blocking]

    @property
    def needs_review(self) -> list[Finding]:
        return [finding for finding in self.all_findings if finding.needs_review]

    @property
    def all_findings(self) -> list[Finding]:
        return [*self.findings, *(column.finding for column in self.columns)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "container": self.container,
            "format": self.file_format,
            "read_options": dict(self.read_options),
            "findings": [finding.to_dict() for finding in self.findings],
            "columns": [column.to_dict() for column in self.columns],
            "members": [member.to_dict() for member in self.members],
            "tables": list(self.tables),
            "warnings": list(self.warnings),
            "blocked_by": [finding.to_dict() for finding in self.blocked_by],
            "needs_review": len(self.needs_review),
            "row_count_sampled": int(len(self.frame)),
        }


def analyse(
    payload: bytes,
    *,
    file_name: str = "",
    content_type: str = "",
    #: A previously confirmed spec. Its answers win over anything inferred,
    #: which is what makes "next month's file" reuse last month's decisions.
    overrides: dict[str, Any] | None = None,
    #: How many rows to read. `ANALYSIS_ROWS` for a preview -- enough to decide
    #: a delimiter and a date format without reading two gigabytes -- and
    #: **None to read the file**, which is what materialising an upload does.
    #:
    #: There is no safe default here. Defaulting to the sample would silently
    #: truncate every import to five thousand rows, which is the worst kind of
    #: bug this phase can have: the load succeeds, the table looks right, and a
    #: quarter of the data is missing.
    limit: int | None = ANALYSIS_ROWS,
) -> AnalysisResult:
    """Read a file's bytes and work out how to read them properly."""
    from service_ingestion import readers

    from shared_python.errors import BadRequestError

    if not payload:
        raise BadRequestError("This file is empty; there is nothing to read.")

    overrides = dict(overrides or {})
    unwrapped = containers.unwrap(payload, file_name=file_name)
    body = unwrapped.payload

    detected: FormatResult = detect_format(
        body, file_name=_inner_name(file_name, unwrapped), content_type=content_type
    )
    chosen_format = str(overrides.get("format") or detected.format)

    result = AnalysisResult(
        frame=pd.DataFrame(),
        findings=[unwrapped.finding, detected.finding],
        members=list(unwrapped.members),
        container=unwrapped.container,
        file_format=chosen_format,
    )

    if unwrapped.is_archive:
        result.warnings.append(
            f"This archive holds {len(unwrapped.members)} files. Each can become its own "
            "dataset, or one dataset if their columns match. Showing the first."
        )

    reader = readers.for_format(chosen_format)
    read = reader(body, overrides=overrides, limit=limit)

    result.frame = read.frame
    result.findings.extend(read.findings)
    result.read_options = read.options
    result.tables = list(read.tables)
    result.warnings.extend(read.warnings)

    # A reader that already knows its types -- Parquet, Avro, ORC, a SQL dump's
    # CREATE TABLE -- has said so, and inferring over the top of a declared
    # schema is how a declared `decimal(12,2)` becomes a float.
    if read.declared_columns:
        result.columns = read.declared_columns
    else:
        result.columns = _profile_frame(read.frame, overrides=overrides)

    return result


def _profile_frame(
    frame: pd.DataFrame, *, overrides: dict[str, Any] | None = None
) -> list[ColumnProfile]:
    """Type every column, honouring anything the user has already decided."""
    by_column = (overrides or {}).get("columns") or {}
    profiles: list[ColumnProfile] = []
    # Typed from the head of the frame rather than all of it. A column's type
    # does not change after ten thousand rows, and the date detector's whole-
    # column scan for a disambiguating value runs over this same sample --
    # which is the one place that matters, and is why the sample is generous.
    sample = frame.head(TYPE_SAMPLE_ROWS)
    for name in frame.columns:
        settled = by_column.get(str(name)) or {}
        profile = profile_column(str(name), sample[name].tolist())
        if settled.get("date_format"):
            profile = _apply_date_override(profile, str(settled["date_format"]))
        if settled.get("decimal"):
            profile = _apply_number_override(profile, settled)
        profiles.append(profile)
    return profiles


def _apply_date_override(profile: ColumnProfile, fmt: str) -> ColumnProfile:
    """The user answered the ambiguous-date question; record that they did."""
    from shared_python.types import lattice as pw

    from service_ingestion.sniff import dates
    from service_ingestion.sniff.evidence import Certainty

    profile.date_format = fmt
    profile.pw_type = pw.DATE if "%H" not in fmt else pw.timestamp()
    profile.finding = Finding(
        stage="date_format",
        value=fmt,
        certainty=Certainty.CERTAIN,
        confidence=1.0,
        reason=f"Set to {dates._describe(fmt)} by the person importing this file.",
        evidence=profile.finding.evidence,
    )
    return profile


def _apply_number_override(profile: ColumnProfile, settled: dict[str, Any]) -> ColumnProfile:
    from shared_python.types import lattice as pw

    from service_ingestion.sniff.evidence import Certainty

    decimal = str(settled["decimal"])
    thousands = settled.get("thousands")
    profile.number_format = {
        "decimal": decimal,
        "thousands": thousands,
        "accounting_negatives": bool((profile.number_format or {}).get("accounting_negatives")),
    }
    if profile.pw_type == pw.STRING:
        profile.pw_type = pw.FLOAT64
    profile.finding = Finding(
        stage="number_format",
        value=decimal,
        certainty=Certainty.CERTAIN,
        confidence=1.0,
        reason=(
            f"Set by the person importing this file: '{decimal}' is the decimal point"
            + (f" and '{thousands}' groups thousands" if thousands else "")
            + "."
        ),
        evidence=profile.finding.evidence,
    )
    return profile


def _inner_name(file_name: str, unwrapped: containers.Unwrapped) -> str:
    """The name to judge the format by, once the wrapper is off.

    `orders.csv.gz` is a CSV; judging it by the outer name finds `.gz`, which
    has already been dealt with and says nothing about what is inside.
    """
    if unwrapped.members:
        return unwrapped.members[0].name
    lowered = file_name.lower()
    for suffix in (".gz", ".bz2", ".xz", ".zip", ".tar"):
        if lowered.endswith(suffix):
            return file_name[: -len(suffix)]
    return file_name


def text_of(payload: bytes) -> tuple[str, Finding]:
    """Decode a payload for the text-based detectors, with its evidence."""
    result = encoding.detect(payload[:HEAD_BYTES] if len(payload) > HEAD_BYTES else payload)
    if len(payload) > HEAD_BYTES:
        # The sample settled the encoding; the whole file is decoded with it.
        return payload.decode(result.encoding, errors="replace"), result.finding
    return result.text, result.finding


def structure_of(text: str, *, overrides: dict[str, Any] | None = None):
    """Delimiter, quoting and header row, honouring anything already decided."""
    overrides = dict(overrides or {})
    dialect = delimiter.detect(text)
    if overrides.get("delimiter"):
        chosen = str(overrides["delimiter"])
        dialect.delimiter = chosen
        dialect.finding = certain(
            "delimiter", chosen, "Set by the person importing this file."
        )

    layout = header.detect(text, delimiter=dialect.delimiter, quote=dialect.quote_char)
    if overrides.get("skip_rows") is not None:
        rows = int(overrides["skip_rows"])
        layout.skip_rows = rows
        layout.has_header = bool(overrides.get("has_header", True))
        layout.finding = certain(
            "header_row",
            rows,
            f"Header set to line {rows + 1} by the person importing this file.",
        )
    return dialect, layout
