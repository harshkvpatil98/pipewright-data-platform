from __future__ import annotations

import io
import json

import pandas as pd
import pytest

from service_ingestion.parsers import parse_tabular_file
from shared_python.errors import BadRequestError


def test_parse_csv() -> None:
    parsed = parse_tabular_file(
        file_bytes=b"name,amount\nalpha,10\nbeta,20\n",
        file_type="csv",
    )
    assert list(parsed.dataframe.columns) == ["name", "amount"]
    assert parsed.dataframe.iloc[0].to_dict()["name"] == "alpha"
    assert parsed.metadata["encoding"] == "utf-8"


def test_parse_csv_with_a_single_byte_encoding() -> None:
    """The characters are what matter, not which of the compatible names won.

    cp1252, iso-8859-15 and latin-1 differ on a handful of code points and
    agree on `ã`. The sniffer reports the one it scored highest and records
    that the alternatives read these bytes identically, so asserting a
    particular name would be asserting a tie-break rather than a result.
    """
    parsed = parse_tabular_file(
        file_bytes="name,city\nalpha,São Paulo\n".encode("latin-1"),
        file_type="csv",
    )
    assert parsed.dataframe.iloc[0].to_dict()["city"] == "São Paulo"
    assert parsed.metadata["encoding"] in {"cp1252", "iso-8859-15", "latin-1"}


def test_parse_json() -> None:
    payload = json.dumps([{"name": "alpha", "amount": 10}, {"name": "beta", "amount": 20}]).encode("utf-8")
    parsed = parse_tabular_file(file_bytes=payload, file_type="json")
    assert list(parsed.dataframe.columns) == ["name", "amount"]
    assert len(parsed.dataframe.index) == 2


def test_parse_json_normalizes_nested_objects() -> None:
    payload = json.dumps([{"name": "alpha", "address": {"country": "US"}}]).encode("utf-8")
    parsed = parse_tabular_file(file_bytes=payload, file_type="json")
    assert list(parsed.dataframe.columns) == ["name", "address.country"]


def test_parse_xlsx() -> None:
    parsed = parse_tabular_file(file_bytes=_build_test_xlsx(), file_type="xlsx")
    assert list(parsed.dataframe.columns) == ["name", "amount"]
    assert len(parsed.dataframe.index) == 2
    assert parsed.dataframe.iloc[0].to_dict()["name"] == "alpha"
    assert parsed.metadata["sheet_name"] == "Orders"


def test_parse_json_reads_an_array_of_scalars_as_one_column() -> None:
    """A list of values is a one-column table, and refusing it helped nobody.

    This used to raise. An array of scalars is a perfectly ordinary thing to
    export -- a list of ids, a list of postcodes -- and the reader now says
    what it did rather than declining the file.
    """
    parsed = parse_tabular_file(
        file_bytes=json.dumps(["alpha", "beta"]).encode("utf-8"), file_type="json"
    )
    assert list(parsed.dataframe.columns) == ["value"]
    assert parsed.dataframe["value"].tolist() == ["alpha", "beta"]
    assert any(
        finding["stage"] == "json_shape" and "non-object" in finding["reason"]
        for finding in parsed.metadata["findings"]
    )


def test_parse_json_still_refuses_a_file_that_is_not_json() -> None:
    with pytest.raises(BadRequestError):
        parse_tabular_file(file_bytes=b"{not json at all", file_type="json")


def _build_test_xlsx() -> bytes:
    buffer = io.BytesIO()
    dataframe = pd.DataFrame([{"name": "alpha", "amount": 10}, {"name": "beta", "amount": 20}])
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name="Orders", index=False)
    return buffer.getvalue()
