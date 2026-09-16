"""Parquet, Avro and ORC: formats that already know what they are.

These carry their schema inside them. Inferring types over the top of a
declared one is not merely wasteful, it is lossy: a declared `decimal(12,2)`
inferred from values becomes a float, and an amount that balanced stops
balancing. So the declared schema is taken as-is and reported as declared.

Nested types survive into the lattice as `struct` and `array` rather than being
flattened here. Flattening is a decision about what a row means, and the user
makes it in the Studio with `flatten` and `explode`, where they can see it.
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import PWType
from shared_python.types import lattice as pw

from service_ingestion.readers.base import ReadResult, declared_profile, normalise_columns
from service_ingestion.sniff.evidence import certain


def _arrow_type(field: Any) -> PWType:
    """An Arrow type in the Phase 08 lattice, nested types included."""
    import pyarrow as pa

    kind = field
    if pa.types.is_boolean(kind):
        return pw.BOOLEAN
    if pa.types.is_int8(kind) or pa.types.is_uint8(kind):
        return pw.INT16
    if pa.types.is_int16(kind) or pa.types.is_uint16(kind):
        return pw.INT16
    if pa.types.is_int32(kind) or pa.types.is_uint32(kind):
        return pw.INT32
    if pa.types.is_int64(kind) or pa.types.is_uint64(kind):
        return pw.INT64
    if pa.types.is_decimal(kind):
        return pw.decimal(kind.precision, kind.scale)
    if pa.types.is_float32(kind):
        return pw.FLOAT32
    if pa.types.is_floating(kind):
        return pw.FLOAT64
    if pa.types.is_date(kind):
        return pw.DATE
    if pa.types.is_timestamp(kind):
        return pw.timestamp(tz_aware=bool(getattr(kind, "tz", None)))
    if pa.types.is_time(kind):
        return pw.time()
    if pa.types.is_binary(kind) or pa.types.is_large_binary(kind):
        return pw.BYTES
    if pa.types.is_list(kind) or pa.types.is_large_list(kind):
        return pw.array(_arrow_type(kind.value_type))
    if pa.types.is_struct(kind):
        return pw.struct({child.name: _arrow_type(child.type) for child in kind})
    if pa.types.is_map(kind):
        return pw.mapping(_arrow_type(kind.key_type), _arrow_type(kind.item_type))
    return pw.STRING


def _from_arrow(table: Any, source: str, *, limit: int | None) -> ReadResult:
    import pyarrow as pa  # noqa: F401  - the table is already an Arrow object

    schema = table.schema
    if limit:
        table = table.slice(0, limit)

    frame = table.to_pandas(types_mapper=None)
    # Nested values arrive as numpy arrays and dicts; a frame cell holding a
    # numpy array compares unequal to itself, which breaks deduplication and
    # every equality check downstream. JSON text is stable and readable.
    import json

    import numpy as np

    for column in frame.columns:
        if frame[column].map(lambda value: isinstance(value, (list, dict, np.ndarray))).any():
            frame[column] = frame[column].map(
                lambda value: json.dumps(
                    value.tolist() if isinstance(value, np.ndarray) else value, default=str
                )
                if isinstance(value, (list, dict, np.ndarray))
                else value
            )

    declared = [
        declared_profile(
            field.name,
            _arrow_type(field.type),
            (
                f"Declared `{field.type}` in the file's own {source} schema"
                + ("" if field.nullable else ", not nullable")
                + ". Taken from the file rather than inferred from values."
            ),
        )
        for field in schema
    ]

    return ReadResult(
        frame=normalise_columns(frame),
        options={},
        findings=[
            certain(
                "embedded_schema",
                source,
                (
                    f"{source} carries its own schema: {len(schema)} column(s) with declared "
                    "types. Nothing was inferred."
                ),
                evidence=[f"{field.name}: {field.type}" for field in schema][:8],
            )
        ],
        declared_columns=declared,
    )


def read_parquet(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - pyarrow is a dependency
        raise BadRequestError("Reading Parquet needs the 'pyarrow' package.") from exc

    try:
        source = pq.ParquetFile(io.BytesIO(payload))
    except Exception as exc:  # noqa: BLE001
        raise BadRequestError(f"Could not read this as Parquet: {exc}") from exc

    # Row groups are how Parquet chunks itself, so reading the first few is how
    # a preview of a very large file costs what a small one does.
    if limit:
        batches = []
        collected = 0
        for batch in source.iter_batches(batch_size=min(limit, 10_000)):
            batches.append(batch)
            collected += batch.num_rows
            if collected >= limit:
                break
        import pyarrow as pa

        table = pa.Table.from_batches(batches, schema=source.schema_arrow) if batches else source.schema_arrow.empty_table()
    else:
        table = source.read()

    result = _from_arrow(table, "Parquet", limit=limit)
    result.findings.append(
        certain(
            "row_groups",
            source.num_row_groups,
            (
                f"{source.metadata.num_rows:,} rows in {source.num_row_groups} row group(s); "
                "a preview reads only the groups it needs."
            ),
        )
    )
    return result


def read_orc(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    try:
        import pyarrow.orc as orc
    except ImportError as exc:  # pragma: no cover
        raise BadRequestError("Reading ORC needs the 'pyarrow' package.") from exc
    try:
        table = orc.ORCFile(io.BytesIO(payload)).read()
    except Exception as exc:  # noqa: BLE001
        raise BadRequestError(f"Could not read this as ORC: {exc}") from exc
    return _from_arrow(table, "ORC", limit=limit)


def read_avro(
    payload: bytes, *, overrides: dict[str, Any] | None = None, limit: int | None = None
) -> ReadResult:
    try:
        import fastavro
    except ImportError as exc:  # pragma: no cover
        raise BadRequestError("Reading Avro needs the 'fastavro' package.") from exc

    try:
        reader = fastavro.reader(io.BytesIO(payload))
        schema = reader.writer_schema
        records = []
        for record in reader:
            records.append(record)
            if limit and len(records) >= limit:
                break
    except Exception as exc:  # noqa: BLE001
        raise BadRequestError(f"Could not read this as Avro: {exc}") from exc

    frame = normalise_columns(pd.json_normalize(records, sep="."))
    fields = (schema or {}).get("fields", []) if isinstance(schema, dict) else []
    declared = [
        declared_profile(
            str(field.get("name")),
            _avro_type(field.get("type")),
            f"Declared `{field.get('type')}` in the file's own Avro schema.",
        )
        for field in fields
        if str(field.get("name")) in set(frame.columns)
    ]

    return ReadResult(
        frame=frame,
        options={},
        findings=[
            certain(
                "embedded_schema",
                "Avro",
                f"Avro carries its own schema: {len(fields)} field(s). Nothing was inferred.",
                evidence=[f"{field.get('name')}: {field.get('type')}" for field in fields][:8],
            )
        ],
        declared_columns=declared,
    )


def _avro_type(declared: Any) -> PWType:
    """An Avro type as a lattice type.

    A union of `["null", X]` is Avro's way of saying "nullable X", which is the
    commonest shape in any real schema.
    """
    if isinstance(declared, list):
        non_null = [item for item in declared if item != "null"]
        return _avro_type(non_null[0]) if non_null else pw.STRING
    if isinstance(declared, dict):
        logical = declared.get("logicalType")
        if logical == "date":
            return pw.DATE
        if logical in ("timestamp-millis", "timestamp-micros"):
            return pw.timestamp()
        if logical == "decimal":
            return pw.decimal(int(declared.get("precision", 38)), int(declared.get("scale", 0)))
        if declared.get("type") == "array":
            return pw.array(_avro_type(declared.get("items")))
        if declared.get("type") == "record":
            return pw.struct(
                {str(field["name"]): _avro_type(field["type"]) for field in declared.get("fields", [])}
            )
        return _avro_type(declared.get("type"))
    return {
        "string": pw.STRING, "bytes": pw.BYTES, "int": pw.INT32, "long": pw.INT64,
        "float": pw.FLOAT32, "double": pw.FLOAT64, "boolean": pw.BOOLEAN, "null": pw.STRING,
    }.get(str(declared), pw.STRING)
