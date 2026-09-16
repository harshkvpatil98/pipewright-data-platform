"""What kind of file this is, from its contents rather than its name.

The extension is a hint and nothing more. Files arrive named `.txt` that are
tab-separated, named `.csv` that are Excel workbooks (a very common mail-gateway
rename), and named `.dat` that are anything at all. Trusting the name produces
a parse failure whose message is about the wrong format entirely.

So detection is by magic bytes first, then by structure, and the extension only
breaks ties. Where they disagree, the bytes win and the disagreement is
reported — because a file that is not what it is named is usually the first
symptom of something else.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from service_ingestion.sniff.evidence import (
    Candidate,
    Certainty,
    Finding,
    certain,
    preview_bytes,
)

#: Formats the pipeline can read, and what each is called in a spec.
KNOWN = (
    "csv", "tsv", "psv", "fixed_width", "excel", "json", "jsonl", "xml",
    "parquet", "avro", "orc", "sql_dump", "yaml", "sas", "stata",
)

#: Magic bytes that settle it outright.
MAGIC: tuple[tuple[str, bytes], ...] = (
    ("parquet", b"PAR1"),
    ("avro", b"Obj\x01"),
    ("orc", b"ORC"),
    # An xlsx is a zip, so this is only reached after the container stage has
    # already declined to unwrap it -- which it does for Office files.
    ("excel", b"\xd0\xcf\x11\xe0"),  # legacy .xls compound document
    ("sas", b"\x00\x00\x00\x00\x00\x00\x00\x00\xc2\xea\x81\x60"),
)

EXTENSIONS = {
    "csv": "csv", "tsv": "tsv", "tab": "tsv", "psv": "psv", "pipe": "psv",
    "txt": "csv", "dat": "csv",
    "xlsx": "excel", "xlsm": "excel", "xls": "excel",
    "json": "json", "jsonl": "jsonl", "ndjson": "jsonl",
    "xml": "xml",
    "parquet": "parquet", "pq": "parquet",
    "avro": "avro", "orc": "orc",
    "sql": "sql_dump",
    "yaml": "yaml", "yml": "yaml",
    "sas7bdat": "sas", "dta": "stata",
}

#: Formats named in the roadmap that this deployment cannot read, and why.
#: Declared rather than omitted so the refusal names the missing piece.
UNSUPPORTED = {
    "pdf": (
        "PDF table extraction needs a layout engine (camelot or pdfplumber), which "
        "is not installed here. Export the table to CSV or Excel instead."
    ),
    "sav": (
        "SPSS files need the 'pyreadstat' package, which is not installed here. "
        "SAS and Stata files are readable."
    ),
    "ods": (
        "OpenDocument spreadsheets need the 'odfpy' package, which is not installed "
        "here. Save as .xlsx instead."
    ),
}

_SQL_DUMP = re.compile(
    r"^\s*(--|/\*|CREATE\s+TABLE|INSERT\s+INTO|DROP\s+TABLE|SET\s+\w|BEGIN;)",
    re.IGNORECASE,
)


@dataclass
class FormatResult:
    format: str
    finding: Finding

    def to_dict(self) -> dict[str, Any]:
        return {"format": self.format, "finding": self.finding.to_dict()}


def _from_extension(file_name: str) -> str | None:
    suffix = Path(file_name).suffix.lower().lstrip(".")
    if suffix in UNSUPPORTED:
        from shared_python.errors import BadRequestError

        raise BadRequestError(UNSUPPORTED[suffix])
    return EXTENSIONS.get(suffix)


def detect_format(payload: bytes, *, file_name: str = "", content_type: str = "") -> FormatResult:
    """The format, with the evidence and any name-versus-content disagreement."""
    named = _from_extension(file_name)
    head = payload[:8192]

    for name, magic in MAGIC:
        if payload.startswith(magic):
            return _settled(name, named, f"The file begins with {preview_bytes(magic, limit=8)}.")

    # An xlsx is a zip. The container stage leaves Office files alone precisely
    # so this check can happen -- and it uses the same test, rather than a
    # second weaker one that only looked at the first four kilobytes and so
    # missed any workbook with more than a couple of sheets.
    from service_ingestion.sniff.containers import is_document_zip

    if is_document_zip(payload):
        return _settled(
            "excel", named, "A zip laid out as an Office document rather than an archive."
        )

    text = head.decode("utf-8", errors="replace").lstrip("﻿").strip()
    if not text:
        return FormatResult(
            format=named or "csv",
            finding=Finding(
                stage="format",
                value=named or "csv",
                certainty=Certainty.UNCERTAIN,
                confidence=0.2,
                reason="The file is empty or unreadable; going by its name.",
            ),
        )

    if text.startswith("<?xml") or (text.startswith("<") and ">" in text[:200]):
        return _settled("xml", named, "The file opens with an XML declaration or element.")

    if _SQL_DUMP.match(text):
        return _settled(
            "sql_dump",
            named,
            "The file opens with SQL statements, so its declared schema can be read.",
        )

    if text[0] in "[{":
        first_line = text.splitlines()[0].strip()
        lines = [line for line in text.splitlines() if line.strip()][:5]
        # JSON Lines is one object per line; a single array spans many lines.
        if len(lines) > 1 and all(line.strip()[0] == "{" for line in lines):
            if _parses_each(lines):
                return _settled("jsonl", named, "Every line is a complete JSON object.")
        if _parses(text) or _parses(first_line):
            return _settled("json", named, "The file parses as a single JSON document.")
        return _settled("json", named, "The file opens with a JSON bracket.", confidence=0.7)

    # Text with separators: which one is `delimiter.py`'s question, but the
    # family is decided here so the right reader is chosen.
    candidates = [
        Candidate("csv", _separator_rate(text, ","), "comma-separated"),
        Candidate("tsv", _separator_rate(text, "\t"), "tab-separated"),
        Candidate("psv", _separator_rate(text, "|"), "pipe-separated"),
        Candidate("csv", _separator_rate(text, ";"), "semicolon-separated (still CSV)"),
    ]
    ranked = sorted(candidates, key=lambda item: item.score, reverse=True)
    if ranked[0].score > 0:
        return _settled(
            str(ranked[0].value),
            named,
            f"Delimited text: {ranked[0].reason}.",
            confidence=min(0.95, 0.6 + ranked[0].score / 2),
        )

    # No separator at all and lines of a *constant* width is what a fixed-width
    # file looks like -- the format whose columns are positions, not characters.
    #
    # One width, not "at most two". Allowing two accepts any short file whose
    # preamble happens to be a different length from its data, which is most of
    # them; the last line is allowed to differ because a file that does not end
    # in a newline leaves a short final record.
    lines = [line for line in text.splitlines() if line.strip()][:20]
    if len(lines) >= 3:
        widths = {len(line) for line in lines[:-1]}
        if len(widths) == 1 and len(lines[-1]) <= next(iter(widths)):
            return _settled(
                "fixed_width",
                named,
                f"No separator, and every line is {next(iter(widths))} characters wide.",
                confidence=0.8,
            )

    return _settled("csv", named, "Text with no recognisable structure; reading as one column.", confidence=0.4)


def _settled(
    detected: str, named: str | None, reason: str, *, confidence: float = 1.0
) -> FormatResult:
    """Combine what the bytes say with what the name says, bytes winning."""
    evidence: list[str] = []
    if named and named != detected:
        evidence.append(
            f"The file is named as {named} but its contents are {detected}. "
            "Reading it as its contents."
        )
    if confidence >= 1.0 and not evidence:
        return FormatResult(detected, certain("format", detected, reason))
    return FormatResult(
        detected,
        Finding(
            stage="format",
            value=detected,
            certainty=Certainty.CERTAIN if confidence >= 1.0 else Certainty.LIKELY,
            confidence=confidence,
            reason=reason,
            evidence=evidence,
        ),
    )


def _parses(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (ValueError, TypeError):
        return False


def _parses_each(lines: list[str]) -> bool:
    return all(_parses(line) for line in lines)


def _separator_rate(text: str, separator: str) -> float:
    """How consistently a separator divides the sample's lines."""
    lines = [line for line in text.splitlines() if line.strip()][:20]
    if len(lines) < 2:
        return 1.0 if separator in text else 0.0
    counts = [line.count(separator) for line in lines]
    if not any(counts):
        return 0.0
    # Ties break towards the *larger* count, for the same reason the header
    # detector does: a short file can have as many preamble lines as data rows,
    # and picking zero there means concluding the file has no separator at all.
    modal = max(set(counts), key=lambda value: (counts.count(value), value))
    if modal == 0:
        return 0.0
    agreeing = sum(1 for count in counts if count == modal)
    return agreeing / len(counts)
