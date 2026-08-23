"""Reading and writing the file formats data actually arrives in.

CSV is what the platform started with and it loses every type it ever had: a
column of dates comes back as strings, a column of integers comes back as
integers only if pandas guesses right. Columnar formats keep the types, and on
wide data they are a fraction of the size.

Each format is declared with what it can do rather than assumed, because they
differ in ways that matter: Parquet and Avro carry a schema, CSV and fixed-width
do not; JSONL streams line by line, Parquet does not.
"""

from __future__ import annotations

import gzip
import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from shared_python.errors import BadRequestError


@dataclass(frozen=True)
class FormatSpec:
    name: str
    label: str
    extensions: tuple[str, ...]
    # Whether the format stores column types alongside the values.
    typed: bool
    writable: bool
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "extensions": list(self.extensions),
            "typed": self.typed,
            "writable": self.writable,
            "description": self.description,
        }


FORMATS: tuple[FormatSpec, ...] = (
    FormatSpec("csv", "CSV", (".csv",), False, True, "Comma separated. Universal, and loses every type."),
    FormatSpec("tsv", "TSV", (".tsv", ".tab"), False, True, "Tab separated."),
    FormatSpec("jsonl", "JSON Lines", (".jsonl", ".ndjson"), False, True, "One JSON object per line; streams well."),
    FormatSpec("json", "JSON", (".json",), False, True, "A single array of objects."),
    FormatSpec("parquet", "Parquet", (".parquet", ".pq"), True, True, "Columnar and typed. Small on wide data."),
    FormatSpec("avro", "Avro", (".avro",), True, True, "Row-oriented and typed, with an embedded schema."),
    FormatSpec("excel", "Excel", (".xlsx", ".xlsm"), False, True, "A worksheet, read as a table."),
    FormatSpec("fixed_width", "Fixed width", (".txt", ".dat"), False, False, "Mainframe extracts, positioned by column widths."),
)

FORMATS_BY_NAME = {spec.name: spec for spec in FORMATS}

# Wrappers, not formats: the file inside still has one of the formats above.
COMPRESSIONS = ("none", "gzip", "zip")


def format_for_path(path: str) -> str | None:
    """The format a filename implies, ignoring any compression wrapper."""
    lowered = path.lower()
    for suffix in (".gz", ".gzip", ".zip"):
        if lowered.endswith(suffix):
            lowered = lowered[: -len(suffix)]
            break

    extension = Path(lowered).suffix
    for spec in FORMATS:
        if extension in spec.extensions:
            return spec.name
    return None


def compression_for_path(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith((".gz", ".gzip")):
        return "gzip"
    if lowered.endswith(".zip"):
        return "zip"
    return "none"


def decompress(data: bytes, compression: str) -> bytes:
    """Unwrap a compressed payload, leaving the format inside untouched."""
    if compression in ("none", None, ""):
        return data
    if compression == "gzip":
        try:
            return gzip.decompress(data)
        except OSError as exc:
            raise BadRequestError(f"This file is not valid gzip: {exc}.") from exc
    if compression == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/")]
            if not names:
                raise BadRequestError("This zip archive is empty.")
            if len(names) > 1:
                # Picking one silently would make the result depend on archive
                # ordering, which nobody can see from the outside.
                raise BadRequestError(
                    f"This zip holds {len(names)} files; extract the one you want first."
                )
            return archive.read(names[0])
    raise BadRequestError(f"Unknown compression '{compression}'.")


def read_bytes(
    data: bytes,
    *,
    format: str,
    compression: str = "none",
    options: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Turn a file's bytes into a frame."""
    spec = FORMATS_BY_NAME.get(format)
    if spec is None:
        raise BadRequestError(
            f"Unknown format '{format}'. Supported: {', '.join(FORMATS_BY_NAME)}."
        )

    payload = decompress(data, compression)
    options = options or {}

    try:
        if format in ("csv", "tsv"):
            separator = "\t" if format == "tsv" else options.get("delimiter", ",")
            return pd.read_csv(io.BytesIO(payload), sep=separator)
        if format == "jsonl":
            return pd.read_json(io.BytesIO(payload), lines=True)
        if format == "json":
            return pd.read_json(io.BytesIO(payload))
        if format == "parquet":
            return pd.read_parquet(io.BytesIO(payload))
        if format == "avro":
            return _read_avro(payload)
        if format == "excel":
            return pd.read_excel(io.BytesIO(payload), sheet_name=options.get("sheet", 0))
        if format == "fixed_width":
            return _read_fixed_width(payload, options)
    except BadRequestError:
        raise
    except Exception as exc:  # noqa: BLE001 - a malformed file is the user's problem to see
        raise BadRequestError(f"Could not read this {spec.label} file: {exc}") from exc

    raise BadRequestError(f"'{format}' cannot be read.")


def _read_avro(payload: bytes) -> pd.DataFrame:
    try:
        import fastavro
    except ImportError as exc:  # pragma: no cover - declared as a dependency
        raise BadRequestError("Avro support needs the 'fastavro' package.") from exc

    reader = fastavro.reader(io.BytesIO(payload))
    return pd.DataFrame(list(reader))


def _read_fixed_width(payload: bytes, options: dict[str, Any]) -> pd.DataFrame:
    widths = options.get("widths")
    if not isinstance(widths, list) or not widths:
        raise BadRequestError(
            "A fixed-width file needs 'widths': the character count of each column."
        )
    try:
        widths = [int(width) for width in widths]
    except (TypeError, ValueError) as exc:
        raise BadRequestError("Every entry in 'widths' must be a whole number.") from exc
    if any(width <= 0 for width in widths):
        raise BadRequestError("Every entry in 'widths' must be greater than zero.")

    names = options.get("names")
    return pd.read_fwf(
        io.BytesIO(payload),
        widths=widths,
        names=names if isinstance(names, list) and names else None,
        header=None if names else "infer",
    )


def write_bytes(
    frame: pd.DataFrame, *, format: str, options: dict[str, Any] | None = None
) -> bytes:
    """Serialise a frame, for export and for reverse ETL."""
    spec = FORMATS_BY_NAME.get(format)
    if spec is None:
        raise BadRequestError(f"Unknown format '{format}'.")
    if not spec.writable:
        raise BadRequestError(f"{spec.label} files can be read but not written.")

    options = options or {}
    buffer = io.BytesIO()

    if format in ("csv", "tsv"):
        separator = "\t" if format == "tsv" else options.get("delimiter", ",")
        frame.to_csv(buffer, index=False, sep=separator)
    elif format == "jsonl":
        buffer.write(frame.to_json(orient="records", lines=True).encode())
    elif format == "json":
        buffer.write(frame.to_json(orient="records").encode())
    elif format == "parquet":
        frame.to_parquet(buffer, index=False)
    elif format == "avro":
        _write_avro(frame, buffer)
    elif format == "excel":
        frame.to_excel(buffer, index=False)
    else:  # pragma: no cover - guarded by the writable check above
        raise BadRequestError(f"'{format}' cannot be written.")

    return buffer.getvalue()


def _write_avro(frame: pd.DataFrame, buffer: BinaryIO) -> None:
    import fastavro

    schema = {
        "type": "record",
        "name": "Row",
        "fields": [
            {"name": str(column), "type": ["null", _avro_type(frame[column])]}
            for column in frame.columns
        ],
    }
    records = json.loads(frame.to_json(orient="records"))
    fastavro.writer(buffer, schema, records)


def _avro_type(series: pd.Series) -> str:
    from pandas.api.types import is_bool_dtype, is_float_dtype, is_integer_dtype

    if is_bool_dtype(series):
        return "boolean"
    if is_integer_dtype(series):
        return "long"
    if is_float_dtype(series):
        return "double"
    return "string"
