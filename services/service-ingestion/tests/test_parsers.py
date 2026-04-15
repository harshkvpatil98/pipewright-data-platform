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


def test_parse_csv_with_latin_1_fallback() -> None:
    parsed = parse_tabular_file(
        file_bytes="name,city\nalpha,São Paulo\n".encode("latin-1"),
        file_type="csv",
    )
    assert parsed.dataframe.iloc[0].to_dict()["city"] == "São Paulo"
    assert parsed.metadata["encoding"] == "latin-1"


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


def test_parse_json_rejects_non_object_arrays() -> None:
    with pytest.raises(BadRequestError):
        parse_tabular_file(file_bytes=json.dumps(["alpha", "beta"]).encode("utf-8"), file_type="json")


def _build_test_xlsx() -> bytes:
    buffer = io.BytesIO()
    dataframe = pd.DataFrame([{"name": "alpha", "amount": 10}, {"name": "beta", "amount": 20}])
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        dataframe.to_excel(writer, sheet_name="Orders", index=False)
    return buffer.getvalue()
