"""One reader per format, each handling that format's specific hard part.

A reader takes bytes and the decisions already made about them, and returns a
frame plus what it learned on the way. It never guesses silently: anything it
had to decide comes back as a `Finding`, and anything it *could not* decide
comes back blocking.

Two rules hold across all of them:

* **A declared schema beats an inferred one.** Parquet, Avro, ORC and a SQL
  dump's `CREATE TABLE` all state their types. Inferring over the top of that
  is how `decimal(12,2)` becomes a float and an amount stops balancing.
* **Nothing in a file is ever executed.** A `.sql` dump is parsed, never run --
  it arrives from outside and `DROP DATABASE` is a statement like any other.
"""

from __future__ import annotations

from typing import Callable

from shared_python.errors import BadRequestError

from service_ingestion.readers.base import ReadResult
from service_ingestion.readers.columnar import read_avro, read_orc, read_parquet
from service_ingestion.readers.delimited import read_delimited, read_fixed_width
from service_ingestion.readers.excel import read_excel
from service_ingestion.readers.json_reader import read_json, read_jsonl, read_yaml
from service_ingestion.readers.sql_dump import read_sql_dump
from service_ingestion.readers.statistical import read_sas, read_stata
from service_ingestion.readers.xml_reader import read_xml

Reader = Callable[..., ReadResult]

READERS: dict[str, Reader] = {
    "csv": read_delimited,
    "tsv": read_delimited,
    "psv": read_delimited,
    "fixed_width": read_fixed_width,
    "excel": read_excel,
    "json": read_json,
    "jsonl": read_jsonl,
    "yaml": read_yaml,
    "xml": read_xml,
    "parquet": read_parquet,
    "avro": read_avro,
    "orc": read_orc,
    "sql_dump": read_sql_dump,
    "sas": read_sas,
    "stata": read_stata,
}


def for_format(name: str) -> Reader:
    reader = READERS.get(name)
    if reader is None:
        raise BadRequestError(
            f"'{name}' is not a format this platform reads. "
            f"Supported: {', '.join(sorted(READERS))}."
        )
    return reader


__all__ = ["READERS", "ReadResult", "Reader", "for_format"]
