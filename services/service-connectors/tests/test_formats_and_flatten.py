"""Formats round-tripping, and the flattening every document source shares."""

from __future__ import annotations

import gzip
import io
import zipfile

import pandas as pd
import pytest

from service_connectors.flatten import column_union, flatten_document, flatten_records
from service_connectors.formats import (
    FORMATS_BY_NAME,
    compression_for_path,
    decompress,
    format_for_path,
    read_bytes,
    write_bytes,
)
from shared_python.errors import BadRequestError

FRAME = pd.DataFrame(
    {
        "id": [1, 2, 3],
        "name": ["ann", "bo", "cy"],
        "amount": [10.5, 20.25, 30.0],
        "active": [True, False, True],
    }
)

ROUND_TRIPPABLE = ("csv", "tsv", "jsonl", "json", "parquet", "avro", "excel")


@pytest.mark.parametrize("format", ROUND_TRIPPABLE)
def test_a_frame_survives_a_round_trip(format: str):
    back = read_bytes(write_bytes(FRAME, format=format), format=format)
    assert len(back) == len(FRAME)
    assert set(back.columns) == set(FRAME.columns)


@pytest.mark.parametrize("format", ("parquet", "avro"))
def test_typed_formats_keep_their_types(format: str):
    """The reason for having them: CSV loses every type it was given."""
    back = read_bytes(write_bytes(FRAME, format=format), format=format)
    assert pd.api.types.is_integer_dtype(back["id"])
    assert pd.api.types.is_float_dtype(back["amount"])
    assert pd.api.types.is_bool_dtype(back["active"])


def test_csv_does_not_keep_its_types_which_is_the_point():
    back = read_bytes(write_bytes(FRAME, format="csv"), format="csv")
    # It guesses, and on a column of mixed-looking values it guesses wrong.
    assert back["name"].dtype == object


def test_the_format_is_read_off_the_extension_past_any_compression():
    assert format_for_path("orders.parquet") == "parquet"
    assert format_for_path("orders.csv.gz") == "csv"
    assert format_for_path("2026/03/orders.jsonl.zip") == "jsonl"
    assert format_for_path("readme.md") is None


def test_compression_is_read_off_the_extension_too():
    assert compression_for_path("a.csv.gz") == "gzip"
    assert compression_for_path("a.csv.zip") == "zip"
    assert compression_for_path("a.csv") == "none"


def test_a_gzipped_file_is_unwrapped_before_being_parsed():
    payload = gzip.compress(write_bytes(FRAME, format="csv"))
    back = read_bytes(payload, format="csv", compression="gzip")
    assert len(back) == 3


def test_a_zip_with_one_file_is_unwrapped():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("orders.csv", write_bytes(FRAME, format="csv"))
    back = read_bytes(buffer.getvalue(), format="csv", compression="zip")
    assert len(back) == 3


def test_a_zip_with_several_files_refuses_to_guess():
    """Picking one silently makes the result depend on archive ordering."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.csv", "id\n1\n")
        archive.writestr("b.csv", "id\n2\n")
    with pytest.raises(BadRequestError) as caught:
        decompress(buffer.getvalue(), "zip")
    assert "2 files" in str(caught.value.detail)


def test_an_empty_zip_is_reported():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w"):
        pass
    with pytest.raises(BadRequestError):
        decompress(buffer.getvalue(), "zip")


def test_a_file_that_is_not_gzip_says_so():
    with pytest.raises(BadRequestError) as caught:
        decompress(b"plain text", "gzip")
    assert "not valid gzip" in str(caught.value.detail)


def test_fixed_width_needs_its_widths():
    with pytest.raises(BadRequestError) as caught:
        read_bytes(b"abc", format="fixed_width")
    assert "widths" in str(caught.value.detail)


def test_fixed_width_reads_by_position():
    payload = b"001ANN  100\n002BO   200\n"
    frame = read_bytes(
        payload,
        format="fixed_width",
        options={"widths": [3, 5, 3], "names": ["id", "name", "amount"]},
    )
    assert list(frame["id"]) == [1, 2]
    assert frame["name"].str.strip().tolist() == ["ANN", "BO"]


def test_a_fixed_width_file_cannot_be_written():
    with pytest.raises(BadRequestError) as caught:
        write_bytes(FRAME, format="fixed_width")
    assert "read but not written" in str(caught.value.detail)


def test_an_unknown_format_lists_the_ones_that_exist():
    with pytest.raises(BadRequestError) as caught:
        read_bytes(b"", format="hologram")
    assert "parquet" in str(caught.value.detail)


def test_a_corrupt_file_is_reported_as_the_users_problem_to_see():
    with pytest.raises(BadRequestError) as caught:
        read_bytes(b"not a parquet file at all", format="parquet")
    assert "Could not read this Parquet file" in str(caught.value.detail)


def test_every_declared_format_says_whether_it_keeps_types():
    assert FORMATS_BY_NAME["parquet"].typed is True
    assert FORMATS_BY_NAME["csv"].typed is False


# ---- flattening ----


def test_nested_objects_become_dotted_columns():
    flat = flatten_document({"user": {"address": {"city": "Rome"}}})
    assert flat == {"user.address.city": "Rome"}


def test_arrays_become_json_rather_than_columns():
    """Exploding them either multiplies rows or invents columns from a sample."""
    flat = flatten_document({"tags": ["a", "b"]})
    assert flat == {"tags": '["a", "b"]'}


def test_an_empty_object_keeps_its_column_rather_than_vanishing():
    assert flatten_document({"meta": {}}) == {"meta": None}


def test_depth_is_capped_so_one_document_cannot_explode_the_schema():
    document: dict = {"value": 1}
    for _ in range(20):
        document = {"nested": document}
    flat = flatten_document(document)
    assert len(flat) == 1
    assert list(flat)[0].count(".") <= 6


def test_documents_with_different_shapes_produce_a_union_of_columns():
    rows = flatten_records([{"id": 1, "a": 1}, {"id": 2, "b": 2}])
    assert column_union(rows) == ["id", "a", "b"]


def test_column_order_follows_the_first_record():
    """Whoever wrote the first document chose that order deliberately."""
    rows = flatten_records([{"z": 1, "a": 2}, {"a": 3, "z": 4}])
    assert column_union(rows) == ["z", "a"]


def test_a_non_object_record_still_becomes_a_row():
    assert flatten_records(["scalar"]) == [{"value": "scalar"}]
