"""A file Pipewright wrote reads back as it was written (E2).

Recipe results, set-aside rows, imports and live feeds are kept as CSV and
read again. Read as an upload is, they came back changed; read with
``written_spec`` every value is the one written, in the type it was held.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from service_ingestion.read_copy import parse
from service_ingestion.written import written_spec


def _round_trip(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.to_csv(index=False).encode("utf-8")
    return parse(data, file_type="csv", spec=written_spec(data, frame))


def _same(value, other) -> bool:
    if pd.isna(value) if not isinstance(value, (list, dict)) else False:
        return pd.isna(other)
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(other, pd.Timestamp):
        other = other.to_pydatetime()
    return value == other


def test_words_that_mean_no_value_in_an_upload_are_values_here() -> None:
    frame = pd.DataFrame({"region": ["unknown", "NA", "none", "null", "n/a", "-", None],
                          "amount": [-99, 0, 1, 2, 3, 4, None]})
    read = _round_trip(frame)
    assert read["region"].tolist()[:6] == ["unknown", "NA", "none", "null", "n/a", "-"]
    assert pd.isna(read["region"].tolist()[6])
    assert read["amount"].tolist()[:6] == [-99, 0, 1, 2, 3, 4]


def test_text_that_looks_like_a_number_or_a_date_stays_text() -> None:
    frame = pd.DataFrame({"code": ["7", "08", "9"], "day": ["2026-01-01", "2026-01-02", "x"],
                          "flag": ["yes", "no", "yes"]})
    read = _round_trip(frame)
    assert read.to_dict("records") == frame.to_dict("records")


def test_every_kind_of_column_comes_back_in_its_kind() -> None:
    frame = pd.DataFrame({
        "whole": [1, 2, None],
        "decimal": [1.5, 1e-05, 2.0],
        "yes_no": [True, False, None],
        "day": [date(2026, 1, 1), None, date(2026, 12, 31)],
        "moment": pd.to_datetime(["2026-01-01 10:00:00", "2026-01-01 10:00:00.5", None], format="ISO8601"),
        "text": ["a", "", "c"],
    })
    read = _round_trip(frame)
    for column in frame.columns:
        for written, back in zip(frame[column], read[column]):
            if column == "text" and written == "":
                continue  # an empty text is an empty cell in CSV: there is no telling them apart
            assert _same(written, back), (column, written, back)


def test_nothing_written_has_no_spec() -> None:
    assert written_spec(b"", pd.DataFrame()) is None


def test_an_upload_still_reads_none_and_nan_as_empty_wherever_they_are() -> None:
    """Only a file Pipewright wrote keeps them: an upload's spec lists the words its sample showed, and a
    "None" further down was empty before E2 and still is."""
    from service_ingestion.spec import ColumnSpec, IngestSpec, apply

    frame = pd.DataFrame({"amount": ["1", "2", "None", "nan"], "name": ["a", "b", "None", "nan"]})
    upload = IngestSpec(format="csv", columns=[ColumnSpec(name="amount", type="int64"), ColumnSpec(name="name")])
    read, notes = apply(frame, upload)
    assert read["amount"].tolist()[:2] == [1, 2] and read["amount"].isna().tolist()[2:] == [True, True]
    assert read["name"].isna().tolist() == [False, False, True, True]
    assert notes == []

