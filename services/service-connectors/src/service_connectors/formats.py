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
import re
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
    # Whether the extension is enough to choose this format unaided.
    #
    # False for the ambiguous ones. `.md` is usually a README rather than a
    # table, `.log` could be either log format, and `.txt` could be anything at
    # all -- so those have to be asked for by name. Guessing wrong here means a
    # directory scan that fails on a file nobody meant to import.
    detectable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "extensions": list(self.extensions),
            "typed": self.typed,
            "writable": self.writable,
            "detectable": self.detectable,
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
    FormatSpec("fixed_width", "Fixed width", (".txt", ".dat"), False, False, "Mainframe extracts, positioned by column widths.", detectable=False),
    # Phase 10: the object-store matrix multiplies stores by formats, so a
    # format added here is a format every store gains. Only formats the
    # installed libraries genuinely read are listed -- a format that raises
    # "needs lxml" on first use is worse than one that was never offered.
    FormatSpec("psv", "Pipe separated", (".psv", ".pipe"), False, True, "Pipe separated. Common in banking extracts."),
    FormatSpec("orc", "ORC", (".orc",), True, False, "Columnar and typed, from the Hive world."),
    FormatSpec("arrow", "Arrow / Feather", (".arrow", ".feather", ".ipc"), True, True, "Arrow's own file format. Fast and exact."),
    FormatSpec("yaml", "YAML", (".yaml", ".yml"), False, True, "A list of mappings, or one mapping per document."),
    FormatSpec("toml", "TOML", (".toml",), False, False, "Configuration, read as a single row or a named table."),
    FormatSpec("ini", "INI", (".ini", ".cfg", ".conf"), False, False, "One row per section, one column per key.", detectable=False),
    FormatSpec("markdown", "Markdown table", (".md", ".markdown"), False, True, "The first pipe table in the document.", detectable=False),
    FormatSpec("log_json", "JSON log lines", (".log",), False, False, "One JSON object per line, with unparseable lines reported.", detectable=False),
    FormatSpec("log_combined", "Web server log", (".log", ".access"), False, False, "Apache/nginx combined format, parsed into columns.", detectable=False),
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
        # Only the unambiguous ones. A `.md` file is usually a README and a
        # `.log` could be either log format, so those are chosen by name rather
        # than guessed at from a directory listing.
        if spec.detectable and extension in spec.extensions:
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
        if format == "psv":
            return pd.read_csv(io.BytesIO(payload), sep="|")
        if format == "orc":
            return pd.read_orc(io.BytesIO(payload))
        if format == "arrow":
            return pd.read_feather(io.BytesIO(payload))
        if format == "yaml":
            return _read_yaml(payload)
        if format == "toml":
            return _read_toml(payload, options)
        if format == "ini":
            return _read_ini(payload)
        if format == "markdown":
            return _read_markdown(payload)
        if format == "log_json":
            return _read_json_log(payload)
        if format == "log_combined":
            return _read_combined_log(payload)
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
    elif format == "psv":
        frame.to_csv(buffer, index=False, sep="|")
    elif format == "arrow":
        frame.to_feather(buffer)
    elif format == "yaml":
        import yaml as yaml_module

        buffer.write(
            yaml_module.safe_dump(
                frame.to_dict(orient="records"), sort_keys=False, allow_unicode=True
            ).encode("utf-8")
        )
    elif format == "markdown":
        # Written out rather than through `to_markdown`, which needs `tabulate`
        # -- a whole dependency to emit pipes and dashes, for a format whose
        # reader is already hand-written here for the same reason.
        buffer.write(_write_markdown(frame).encode("utf-8"))
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


# ---------------------------------------------------------- Phase 10 formats


def _rows_to_frame(rows: list[Any], label: str) -> pd.DataFrame:
    """A list of anything, as a table.

    A list of mappings is a table already. A list of scalars becomes a
    single-column table rather than an error, because a file of one value per
    line is a perfectly ordinary thing to be handed.
    """
    if not rows:
        return pd.DataFrame()
    if all(isinstance(row, dict) for row in rows):
        return pd.json_normalize(rows)
    if any(isinstance(row, dict) for row in rows):
        raise BadRequestError(
            f"This {label} file mixes objects and plain values, so it has no single "
            "set of columns."
        )
    return pd.DataFrame({"value": rows})


def _read_yaml(payload: bytes) -> pd.DataFrame:
    import yaml as yaml_module

    documents = [
        document
        for document in yaml_module.safe_load_all(payload.decode("utf-8"))
        if document is not None
    ]
    if len(documents) == 1 and isinstance(documents[0], list):
        return _rows_to_frame(documents[0], "YAML")
    if len(documents) == 1 and isinstance(documents[0], dict):
        return pd.json_normalize([documents[0]])
    return _rows_to_frame(documents, "YAML")


def _read_toml(payload: bytes, options: dict[str, Any]) -> pd.DataFrame:
    import tomllib

    document = tomllib.loads(payload.decode("utf-8"))
    table = options.get("table")
    if table:
        section = document.get(str(table))
        if section is None:
            raise BadRequestError(
                f"This file has no [{table}] section. Sections: {', '.join(document) or 'none'}."
            )
        document = section
    if isinstance(document, list):
        return _rows_to_frame(document, "TOML")
    return pd.json_normalize([document])


def _read_ini(payload: bytes) -> pd.DataFrame:
    import configparser

    parser = configparser.ConfigParser()
    parser.read_string(payload.decode("utf-8"))
    rows = [
        {"section": name, **dict(parser[name])}
        for name in parser.sections()
    ]
    if parser.defaults():
        rows.insert(0, {"section": "DEFAULT", **dict(parser.defaults())})
    return pd.DataFrame(rows)


_MARKDOWN_SEPARATOR = re.compile(r"^\s*\|?[\s:-]*-[\s:|-]*\|?\s*$")


def _read_markdown(payload: bytes) -> pd.DataFrame:
    """The first pipe table in a Markdown document.

    Written out rather than handed to a Markdown library: the whole grammar is
    "split on pipes, skip the dashes", and a library would be a dependency for
    twenty lines.
    """
    lines = [line for line in payload.decode("utf-8").splitlines() if line.strip()]
    header: list[str] | None = None
    rows: list[list[str]] = []

    for line in lines:
        if "|" not in line:
            if header is not None:
                break  # The table ended.
            continue
        if _MARKDOWN_SEPARATOR.match(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
        else:
            rows.append(cells)

    if header is None:
        raise BadRequestError("This file has no Markdown table in it.")
    width = len(header)
    padded = [row[:width] + [""] * max(0, width - len(row)) for row in rows]
    return pd.DataFrame(padded, columns=header)


def _read_json_log(payload: bytes) -> pd.DataFrame:
    """JSON lines, tolerant of the lines that are not.

    A log is not a data file: it has restart banners and truncated final lines.
    Refusing the whole file because of one is not useful; reporting how many
    were skipped is.
    """
    import json

    rows: list[dict[str, Any]] = []
    skipped = 0
    for line in payload.decode("utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            skipped += 1
            continue
        rows.append(parsed if isinstance(parsed, dict) else {"value": parsed})

    frame = pd.json_normalize(rows) if rows else pd.DataFrame()
    if skipped:
        frame.attrs["warnings"] = [
            f"{skipped:,} line(s) were not JSON and were skipped."
        ]
    return frame


_COMBINED_LOG = re.compile(
    r'^(?P<host>\S+) \S+ (?P<user>\S+) \[(?P<time>[^\]]+)\] '
    r'"(?P<method>\S+) (?P<path>\S*) ?(?P<protocol>[^"]*)" '
    r'(?P<status>\d{3}) (?P<bytes>\S+)'
    r'(?: "(?P<referrer>[^"]*)" "(?P<agent>[^"]*)")?'
)


def _read_combined_log(payload: bytes) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    skipped = 0
    for line in payload.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        match = _COMBINED_LOG.match(line)
        if match is None:
            skipped += 1
            continue
        row = match.groupdict()
        row["status"] = int(row["status"])
        row["bytes"] = int(row["bytes"]) if str(row["bytes"]).isdigit() else None
        rows.append(row)

    frame = pd.DataFrame(rows)
    if skipped:
        frame.attrs["warnings"] = [
            f"{skipped:,} line(s) did not match the combined log format and were skipped."
        ]
    return frame


def _write_markdown(frame: pd.DataFrame) -> str:
    columns = [str(name) for name in frame.columns]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for row in frame.itertuples(index=False):
        cells = ["" if value is None or pd.isna(value) else str(value) for value in row]
        # A pipe inside a cell would end the cell; escaping is what every
        # Markdown renderer expects here.
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
    return "\n".join(lines) + "\n"
