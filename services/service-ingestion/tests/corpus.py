"""A corpus of deliberately awful files.

The roadmap asks for "~60 deliberately awful real-world files", each a test.
Every case here is something that actually arrives: a bank statement with four
lines of preamble, an export where the decimal point is a comma, a CSV that is
really a zip, a date column nothing in the world can disambiguate.

They are **generated rather than checked in**. A binary fixture is opaque --
nobody can see what makes it awful without opening it in something -- whereas a
builder function is the description of the problem. It also keeps a repository
from accumulating a megabyte of sample spreadsheets.

Each case says what should happen, not just that nothing raised. `expect_rows`,
`expect_columns`, `expect_types` and `expect_values` pin the result;
`expect_blocking` names a stage that must *refuse* to guess, which is how the
"never assume an ambiguous date" requirement is tested rather than asserted.
"""

from __future__ import annotations

import gzip
import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class Case:
    """One awful file and what reading it correctly means."""

    name: str
    file_name: str
    build: Callable[[], bytes]
    #: What makes this file awful, in one line. Shown when the test fails.
    problem: str

    expect_format: str | None = None
    expect_container: str | None = None
    expect_rows: int | None = None
    expect_columns: tuple[str, ...] | None = None
    #: Column name -> the lattice type string it must end up with.
    expect_types: dict[str, str] = field(default_factory=dict)
    #: Column name -> the values that column must hold, after conversion.
    expect_values: dict[str, list[Any]] = field(default_factory=dict)
    #: A stage that must come back blocking, because the file does not say.
    expect_blocking: str | None = None
    #: A stage that must appear among the findings at all.
    expect_finding: str | None = None
    #: A substring that must appear in some finding's reason.
    expect_reason: str | None = None
    #: Set when reading the file must fail, with this in the message.
    expect_error: str | None = None
    #: Spec overrides to apply, as a user answering a question would.
    answers: dict[str, Any] = field(default_factory=dict)


def _csv(text: str, encoding: str = "utf-8") -> Callable[[], bytes]:
    return lambda: text.encode(encoding)


def _xlsx(
    frame: pd.DataFrame,
    *,
    sheet: str = "Sheet1",
    extra_sheets: dict[str, pd.DataFrame] | None = None,
    preamble: list[list[Any]] | None = None,
    merge: str | None = None,
) -> Callable[[], bytes]:
    def build() -> bytes:
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            start = len(preamble or [])
            frame.to_excel(writer, sheet_name=sheet, index=False, startrow=start)
            if preamble:
                worksheet = writer.sheets[sheet]
                for row_index, row in enumerate(preamble, start=1):
                    for column_index, value in enumerate(row, start=1):
                        worksheet.cell(row=row_index, column=column_index, value=value)
            if merge:
                writer.sheets[sheet].merge_cells(merge)
            for name, other in (extra_sheets or {}).items():
                other.to_excel(writer, sheet_name=name, index=False)
        return buffer.getvalue()

    return build


def _gzip(inner: Callable[[], bytes]) -> Callable[[], bytes]:
    return lambda: gzip.compress(inner())


def _zip(members: dict[str, Callable[[], bytes]]) -> Callable[[], bytes]:
    def build() -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, inner in members.items():
                archive.writestr(name, inner())
        return buffer.getvalue()

    return build


def _parquet(frame: pd.DataFrame) -> Callable[[], bytes]:
    def build() -> bytes:
        import pyarrow as pa
        import pyarrow.parquet as pq

        buffer = io.BytesIO()
        pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), buffer)
        return buffer.getvalue()

    return build


def _avro(records: list[dict[str, Any]], schema: dict[str, Any]) -> Callable[[], bytes]:
    def build() -> bytes:
        import fastavro

        buffer = io.BytesIO()
        fastavro.writer(buffer, schema, records)
        return buffer.getvalue()

    return build


# ---------------------------------------------------------------- the corpus

CASES: tuple[Case, ...] = (
    # ---- delimiters -----------------------------------------------------
    Case(
        "plain-csv", "orders.csv",
        _csv("id,name,amount\n1,alpha,10\n2,beta,20\n"),
        "Nothing. The baseline that must keep working.",
        expect_format="csv", expect_rows=2,
        expect_columns=("id", "name", "amount"),
        expect_types={"id": "int16", "amount": "int16"},
    ),
    Case(
        "semicolon", "export.csv",
        _csv("id;name;amount\n1;alpha;10\n2;beta;20\n"),
        "Semicolon-separated, which every European export is.",
        expect_rows=2, expect_columns=("id", "name", "amount"),
    ),
    Case(
        "tab-separated", "export.txt",
        _csv("id\tname\tamount\n1\talpha\t10\n2\tbeta\t20\n"),
        "Tab-separated and named .txt, so the extension says nothing.",
        expect_format="tsv", expect_rows=2,
    ),
    Case(
        "pipe-separated", "feed.dat",
        _csv("id|name|amount\n1|alpha|10\n2|beta|20\n"),
        "Pipe-separated, named .dat.",
        expect_format="psv", expect_rows=2,
    ),
    Case(
        "comma-inside-quotes", "names.csv",
        _csv('id,name,city\n1,"Smith, John",London\n2,"Doe, Jane",Paris\n'),
        "A comma inside a quoted field, which breaks naive delimiter counting.",
        expect_rows=2, expect_columns=("id", "name", "city"),
        expect_values={"name": ["Smith, John", "Doe, Jane"]},
    ),
    Case(
        "semicolon-with-commas-in-text", "notes.csv",
        _csv("id;note\n1;one, two, three\n2;four, five, six\n"),
        "Commas in the text outnumber the real semicolon delimiter.",
        expect_rows=2, expect_columns=("id", "note"),
    ),
    Case(
        "doubled-quotes", "quotes.csv",
        _csv('id,saying\n1,"she said ""hello"""\n2,"plain"\n'),
        'A doubled quote inside a quoted field: `""` is one literal quote.',
        expect_rows=2, expect_values={"saying": ['she said "hello"', "plain"]},
    ),
    Case(
        "embedded-newline", "multiline.csv",
        _csv('id,address\n1,"12 High St\nLondon"\n2,"9 Low Rd\nLeeds"\n'),
        "A newline inside a quoted field, so physical lines outnumber rows.",
        expect_rows=2,
    ),
    Case(
        "trailing-delimiter", "trailing.csv",
        _csv("id,name,\n1,alpha,\n2,beta,\n"),
        "Every row ends with the delimiter, which is a quirk and not a ragged row.",
        expect_rows=2,
    ),
    Case(
        "single-column", "ids.csv",
        _csv("id\n1001\n1002\n1003\n"),
        "One column and no delimiter anywhere. A real thing, not an error.",
        expect_rows=3, expect_columns=("id",),
    ),

    # ---- encodings ------------------------------------------------------
    Case(
        "utf8-bom", "bom.csv",
        lambda: b"\xef\xbb\xbfid,name\n1,alpha\n",
        "A UTF-8 byte-order mark, which becomes part of the first column name "
        "if it is not stripped.",
        expect_columns=("id", "name"), expect_rows=1,
        expect_finding="encoding",
    ),
    Case(
        "latin1", "accents.csv",
        _csv("id,city\n1,São Paulo\n2,München\n", "latin-1"),
        "Latin-1 accents, which arrive as mojibake if read as UTF-8.",
        expect_rows=2, expect_values={"city": ["São Paulo", "München"]},
    ),
    Case(
        "utf16", "utf16.csv",
        lambda: "id,name\n1,alpha\n2,beta\n".encode("utf-16"),
        "UTF-16 with a BOM: every other byte is a null.",
        expect_rows=2, expect_columns=("id", "name"),
    ),
    Case(
        "cp1252-smart-quotes", "smart.csv",
        _csv("id,note\n1,“quoted”\n", "cp1252"),
        "Windows smart quotes, which are undefined bytes in ISO-8859-1.",
        expect_rows=1,
    ),

    # ---- structure ------------------------------------------------------
    Case(
        "bank-preamble", "statement.csv",
        _csv(
            "Statement for account 0012345678\n"
            "Period: 2026-01-01 to 2026-01-31\n"
            "\n"
            "date,description,amount\n"
            "2026-01-15,Coffee,3.50\n"
            "2026-01-16,Rent,950.00\n"
        ),
        "Four lines of preamble before the header, as every bank export has.",
        expect_rows=2, expect_columns=("date", "description", "amount"),
        expect_finding="header_row",
    ),
    Case(
        "preamble-as-long-as-the-data", "short-statement.csv",
        _csv(
            "Statement for account 0012345678\n"
            "Period: 2026-02-01 to 2026-02-28\n"
            "\n"
            "date;description;amount\n"
            "2026-02-07;Coffee;12,50\n"
        ),
        "As many preamble lines as data rows, so the commonest line width is a "
        "tie. Picking the narrower one makes the preamble the table.",
        expect_rows=1, expect_columns=("date", "description", "amount"),
    ),
    Case(
        "no-header", "readings.csv",
        _csv("1,17.2,ok\n2,17.9,ok\n3,18.1,ok\n4,18.4,ok\n"),
        "No header at all. Borrowing the first data row would lose a reading.",
        expect_rows=4, expect_columns=("column_1", "column_2", "column_3"),
    ),
    Case(
        "duplicate-column-names", "joined.csv",
        _csv("id,amount,amount\n1,10,20\n"),
        "Two columns called `amount`, as a join export produces.",
        expect_rows=1, expect_columns=("id", "amount", "amount_2"),
    ),
    Case(
        "blank-column-name", "gap.csv",
        _csv("id,,amount\n1,x,10\n"),
        "A column with no name, which pandas calls `Unnamed: 1`.",
        expect_rows=1, expect_columns=("id", "column_2", "amount"),
    ),
    Case(
        "ragged-footer", "totals.csv",
        _csv("id,name,amount\n1,alpha,10\n2,beta,20\nTotal,,30,extra\n"),
        "A footer row with the wrong number of fields.",
        expect_rows=2, expect_finding="ragged_rows",
        expect_reason="do not have",
    ),
    Case(
        "blank-lines-between-rows", "spaced.csv",
        _csv("id,name\n\n1,alpha\n\n2,beta\n\n"),
        "Blank lines scattered through the file.",
        expect_rows=2,
    ),
    Case(
        "fixed-width", "ledger.txt",
        _csv(
            "ID    NAME       AMOUNT\n"
            "1     alpha         10 \n"
            "2     beta          20 \n"
        ),
        "Fixed-width columns: the boundaries are positions, not characters.",
        expect_format="fixed_width", expect_rows=2,
    ),

    # ---- numbers --------------------------------------------------------
    Case(
        "european-decimals", "de.csv",
        _csv("id;amount\n1;1.234,56\n2;89,10\n3;2.000,00\n"),
        "`1.234,56` is one thousand two hundred, not one point two.",
        expect_rows=3,
        expect_values={"amount": [1234.56, 89.10, 2000.00]},
    ),
    Case(
        "us-decimals", "us.csv",
        _csv("id,amount\n1,\"1,234.56\"\n2,\"89.10\"\n"),
        "`1,234.56` the other way round.",
        expect_rows=2, expect_values={"amount": [1234.56, 89.10]},
    ),
    Case(
        "ambiguous-thousands", "ambiguous-numbers.csv",
        _csv("id,amount\n1,1.234\n2,5.678\n"),
        "`1.234` alone is genuinely both readings and the file never says.",
        expect_blocking="number_format",
    ),
    Case(
        "accounting-negatives", "accounts.csv",
        _csv("id,amount\n1,(1234.56)\n2,89.10\n"),
        "Parentheses mean negative, which is how accounting writes it.",
        expect_rows=2, expect_values={"amount": [-1234.56, 89.10]},
    ),
    Case(
        "currency-symbols", "prices.csv",
        _csv("id,price\n1,$10.50\n2,$20.00\n"),
        "A currency symbol glued to the number.",
        expect_rows=2, expect_values={"price": [10.50, 20.00]},
    ),
    Case(
        "trailing-minus", "sap.csv",
        _csv("id,amount\n1,1234.56-\n2,89.10\n"),
        "A trailing minus sign, which is how SAP writes a negative.",
        expect_rows=2, expect_values={"amount": [-1234.56, 89.10]},
    ),
    Case(
        "integers-stay-narrow", "small.csv",
        _csv("id,n\n1,5\n2,7\n"),
        "Small whole numbers should not all become bigint.",
        expect_types={"n": "int16"},
    ),
    Case(
        "round-decimals-stay-decimal", "prices.csv",
        _csv("id,total\n1,10.0\n2,20.0\n"),
        "`10.0` is a decimal that happens to be round. Narrowing it to an "
        "integer drops the cents and an export then stores the wrong type.",
        expect_types={"total": "float64"},
        expect_values={"total": [10.0, 20.0]},
    ),
    Case(
        "money-with-cents", "money.csv",
        _csv("id,total\n1,10.00\n2,20.50\n"),
        "A price column where every value is written to two decimal places.",
        expect_types={"total": "float64"},
    ),
    Case(
        "big-integers", "large.csv",
        _csv("id,n\n1,9007199254740993\n2,3\n"),
        "An integer past 2^53, which becomes wrong if read as a float.",
        expect_types={"n": "int64"},
    ),

    # ---- dates ----------------------------------------------------------
    Case(
        "ambiguous-dates", "ambiguous-dates.csv",
        _csv("id,when\n1,03/04/2026\n2,05/06/2026\n"),
        "The killer: 3 April or 4 March, and nothing in the column decides.",
        expect_blocking="date_format",
        expect_reason="does not say",
    ),
    Case(
        "answered-ambiguous-dates", "answered-dates.csv",
        _csv("id,when\n1,03/04/2026\n2,05/06/2026\n"),
        "The same file, once somebody has answered the question.",
        answers={"columns": {"when": {"date_format": "%d/%m/%Y"}}},
        expect_types={"when": "date"},
        expect_values={"when": ["2026-04-03", "2026-06-05"]},
    ),
    Case(
        "disambiguated-by-a-late-row", "late-proof.csv",
        _csv(
            "id,when\n" + "".join(f"{i},01/02/2026\n" for i in range(1, 60)) + "60,25/02/2026\n"
        ),
        "Only row 60 has a day past the twelfth. A sample of 50 would miss it.",
        expect_types={"when": "date"},
        expect_rows=60,
    ),
    Case(
        "iso-dates", "iso.csv",
        _csv("id,when\n1,2026-04-03\n2,2026-06-05\n"),
        "ISO dates, which are never ambiguous and must not be flagged.",
        expect_types={"when": "date"},
        expect_blocking=None,
    ),
    Case(
        "dotted-european-dates", "dotted.csv",
        _csv("id,when\n1,15.01.2026\n2,03.02.2026\n"),
        "Dot-separated dates, disambiguated by the 15th.",
        expect_types={"when": "date"},
        expect_values={"when": ["2026-01-15", "2026-02-03"]},
    ),
    Case(
        "month-name-dates", "named.csv",
        _csv("id,when\n1,15 Jan 2026\n2,3 Feb 2026\n"),
        "A month name, which cannot be ambiguous.",
        expect_types={"when": "date"},
    ),
    Case(
        "timestamps", "events.csv",
        _csv("id,at\n1,2026-04-03T10:30:00\n2,2026-04-03T11:00:00\n"),
        "A date and a time, which is a timestamp and not a date.",
        expect_types={"at": "timestamp(naive)"},
    ),

    # ---- nulls and types ------------------------------------------------
    Case(
        "null-tokens", "nulls.csv",
        _csv("id,amount\n1,10\n2,N/A\n3,NULL\n4,\n"),
        "Four spellings of nothing in one column.",
        expect_rows=4,
        expect_values={"amount": [10, None, None, None]},
    ),
    Case(
        "minus-is-not-null", "minus.csv",
        _csv("id,amount\n1,-5\n2,-10\n"),
        "A lone `-` is a minus sign here, and treating it as null loses values.",
        expect_values={"amount": [-5, -10]},
    ),
    Case(
        "booleans", "flags.csv",
        _csv("id,active\n1,true\n2,false\n3,yes\n"),
        "Mixed true/false spellings.",
        expect_types={"active": "boolean"},
        expect_values={"active": [True, False, True]},
    ),
    Case(
        "zero-one-is-a-number", "binary.csv",
        _csv("id,n\n1,0\n2,1\n3,1\n"),
        "A column of only 0 and 1 is as likely a count as a flag; arithmetic wins.",
        expect_types={"n": "int16"},
    ),
    Case(
        "mostly-numeric", "mixed.csv",
        _csv("id,amount\n1,10\n2,20\n3,30\n4,40\n5,not recorded\n"),
        "One non-numeric value in a numeric column: the 0.2% that needs reporting.",
        expect_rows=5,
    ),
    Case(
        "leading-zeros", "codes.csv",
        _csv("id,postcode\n1,01234\n2,00987\n"),
        "Leading zeros, which vanish if the column becomes a number.",
        expect_values={"postcode": ["01234", "00987"]},
    ),

    # ---- containers -----------------------------------------------------
    Case(
        "gzipped-csv", "orders.csv.gz",
        _gzip(_csv("id,name\n1,alpha\n2,beta\n")),
        "A gzipped CSV, which is not a CSV until it is unwrapped.",
        expect_container="gzip", expect_rows=2,
    ),
    Case(
        "zip-one-file", "orders.zip",
        _zip({"orders.csv": _csv("id,name\n1,alpha\n")}),
        "A zip holding exactly one file, which is just that file.",
        expect_container="zip", expect_rows=1,
    ),
    Case(
        "zip-many-files", "months.zip",
        _zip({
            "2026-01.csv": _csv("id,name\n1,jan\n"),
            "2026-02.csv": _csv("id,name\n2,feb\n"),
            "__MACOSX/._2026-01.csv": lambda: b"junk",
        }),
        "Twelve monthly files in one zip, plus macOS resource-fork noise.",
        expect_container="zip", expect_reason="archive of",
    ),
    Case(
        "csv-that-is-really-a-zip", "report.csv",
        _zip({"real.csv": _csv("id,name\n1,alpha\n")}),
        "Named .csv, actually a zip. Mail gateways do this.",
        expect_container="zip", expect_rows=1,
    ),

    # ---- Excel ----------------------------------------------------------
    Case(
        "excel-plain", "book.xlsx",
        _xlsx(pd.DataFrame([{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}])),
        "A workbook, which is a zip and must not be unwrapped as one.",
        expect_format="excel", expect_rows=2,
    ),
    Case(
        "excel-many-sheets", "multi.xlsx",
        _xlsx(
            pd.DataFrame([{"id": 1}]),
            sheet="Orders",
            extra_sheets={"Returns": pd.DataFrame([{"id": 9}])},
        ),
        "Several sheets. Reading the first and ignoring the rest loses data.",
        expect_format="excel", expect_reason="sheet(s)",
    ),
    Case(
        "excel-preamble", "titled.xlsx",
        _xlsx(
            pd.DataFrame([{"id": 1, "amount": 10}, {"id": 2, "amount": 20}]),
            preamble=[["Quarterly report"], ["Generated 2026-04-01"]],
        ),
        "A title block above the table, as every finance workbook has.",
        expect_rows=2, expect_columns=("id", "amount"),
    ),
    Case(
        "excel-formula-errors", "broken.xlsx",
        _xlsx(pd.DataFrame([{"id": 1, "total": "#REF!"}, {"id": 2, "total": 5}])),
        "A formula that failed. `#REF!` is an error, not the text '#REF!'.",
        expect_rows=2, expect_finding="formula_errors",
    ),
    Case(
        "excel-merged-cells", "merged.xlsx",
        _xlsx(
            pd.DataFrame([{"region": "EU", "n": 1}, {"region": None, "n": 2}]),
            merge="A2:A3",
        ),
        "A merged cell, which reads as one value and a column of blanks.",
        expect_rows=2, expect_finding="merged_cells",
    ),

    # ---- JSON and XML ---------------------------------------------------
    Case(
        "json-array", "records.json",
        lambda: json.dumps([{"id": 1, "name": "alpha"}, {"id": 2, "name": "beta"}]).encode(),
        "A plain array of objects.",
        expect_format="json", expect_rows=2,
    ),
    Case(
        "json-lines", "events.jsonl",
        lambda: b'{"id": 1}\n{"id": 2}\n{"id": 3}\n',
        "One object per line, which is not a JSON document.",
        expect_format="jsonl", expect_rows=3,
    ),
    Case(
        "json-concatenated", "appended.json",
        lambda: b'{"id": 1}{"id": 2}{"id": 3}',
        "Documents written one after another with no separator. Not valid JSON.",
        expect_rows=3, expect_reason="one after another",
    ),
    Case(
        "json-envelope", "response.json",
        lambda: json.dumps(
            {"meta": {"page": 1}, "data": {"items": [{"id": 1}, {"id": 2}, {"id": 3}]}}
        ).encode(),
        "The records are three levels down, under `data.items`.",
        expect_rows=3, expect_finding="records_path",
    ),
    Case(
        "json-nested-objects", "nested.json",
        lambda: json.dumps([{"id": 1, "address": {"city": "Oslo"}}]).encode(),
        "A nested object, which becomes a dotted column.",
        expect_columns=("id", "address.city"),
    ),
    Case(
        "json-arrays-stay-json", "arrays.json",
        lambda: json.dumps([{"id": 1, "tags": ["a", "b"]}]).encode(),
        "An array in a cell. Exploding it would change what a row means.",
        expect_rows=1, expect_finding="nested_arrays",
    ),
    Case(
        "json-heterogeneous", "patchy.json",
        lambda: json.dumps([{"id": 1, "note": "x"}, {"id": 2}]).encode(),
        "A field only some records have, which is normal JSON and not a table.",
        expect_rows=2, expect_finding="heterogeneous_records",
    ),
    Case(
        "json-scalars", "list.json",
        lambda: json.dumps(["alpha", "beta"]).encode(),
        "An array of plain values, which is a one-column table.",
        expect_rows=2, expect_columns=("value",),
    ),
    Case(
        "xml-records", "orders.xml",
        lambda: (
            b"<orders><order id='1'><total>10</total></order>"
            b"<order id='2'><total>20</total></order></orders>"
        ),
        "Repeated elements are rows; the id lives in an attribute.",
        expect_format="xml", expect_rows=2, expect_finding="xml_attributes",
    ),
    Case(
        "xml-buried-records", "soap.xml",
        lambda: (
            b"<Envelope><Body><GetOrders><Orders>"
            b"<Order><sku>a</sku></Order><Order><sku>b</sku></Order>"
            b"</Orders></GetOrders></Body></Envelope>"
        ),
        "The record element is four levels down inside a SOAP envelope.",
        expect_rows=2, expect_finding="record_element",
    ),
    Case(
        "xml-doctype-refused", "bomb.xml",
        lambda: b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaa">]><r><i>&a;</i></r>',
        "A DOCTYPE, which is how the billion-laughs attack expands to gigabytes.",
        expect_error="DOCTYPE",
    ),

    # ---- schema-carrying formats ----------------------------------------
    Case(
        "parquet-declared-types", "data.parquet",
        _parquet(pd.DataFrame({"id": pd.Series([1, 2], dtype="int32"), "name": ["a", "b"]})),
        "Parquet states its own types. Inferring over them loses precision.",
        expect_format="parquet", expect_rows=2,
        expect_types={"id": "int32"},
        expect_finding="embedded_schema",
    ),
    Case(
        "avro-declared-types", "data.avro",
        _avro(
            [{"id": 1, "name": "a"}, {"id": 2, "name": None}],
            {
                "type": "record", "name": "R",
                "fields": [
                    {"name": "id", "type": "long"},
                    {"name": "name", "type": ["null", "string"]},
                ],
            },
        ),
        "Avro's nullable union, which is how every real Avro schema is written.",
        expect_format="avro", expect_rows=2,
        expect_types={"id": "int64"},
    ),
    Case(
        "sql-dump", "dump.sql",
        lambda: (
            b"-- MySQL dump\n"
            b"DROP TABLE IF EXISTS `orders`;\n"
            b"CREATE TABLE `orders` (\n"
            b"  `id` int NOT NULL,\n"
            b"  `total` decimal(12,2) DEFAULT NULL,\n"
            b"  `note` varchar(255),\n"
            b"  PRIMARY KEY (`id`)\n"
            b");\n"
            b"INSERT INTO `orders` VALUES (1,10.50,'it''s fine'),(2,20.00,NULL);\n"
        ),
        "A dump declares real types. Inference would call `decimal(12,2)` a float.",
        expect_format="sql_dump", expect_rows=2,
        expect_types={"total": "decimal(12,2)", "id": "int32"},
        expect_reason="Nothing in the file was executed",
    ),
    Case(
        "sql-dump-many-tables", "multi.sql",
        lambda: (
            b"CREATE TABLE a (id int);\n"
            b"INSERT INTO a VALUES (1);\n"
            b"CREATE TABLE b (id int, name text);\n"
            b"INSERT INTO b VALUES (1,'x'),(2,'y'),(3,'z');\n"
        ),
        "Several tables in one dump; each is its own dataset.",
        expect_rows=3, expect_finding="table_choice",
    ),
    Case(
        "sql-dump-semicolon-in-string", "tricky.sql",
        lambda: (
            b"CREATE TABLE t (id int, note text);\n"
            b"INSERT INTO t VALUES (1,'a;b'),(2,'c;d');\n"
        ),
        "A semicolon inside a string literal, which truncates a naive splitter.",
        expect_rows=2, expect_values={"note": ["a;b", "c;d"]},
    ),

    # ---- refusals -------------------------------------------------------
    Case(
        "empty-file", "empty.csv",
        lambda: b"",
        "An empty file. The message should say so rather than crashing.",
        expect_error="empty",
    ),
    Case(
        "header-only", "headers.csv",
        _csv("id,name,amount\n"),
        "A header and no rows, which is a real export of nothing.",
        expect_rows=0, expect_columns=("id", "name", "amount"),
    ),
)


def by_name(name: str) -> Case:
    for case in CASES:
        if case.name == name:
            return case
    raise KeyError(name)
