"""One type vocabulary across surfaces.

The review found a column that read as one type on the import screen and a
different type in Studio. The cause was two code paths inferring types
independently. This pins the contract that fixes it: the ingestion schema (what
the dataset page and every stored record show) and the transformation schema
summary (what Studio's inspector shows) describe the same frame with the same
canonical vocabulary.
"""

from __future__ import annotations

import pandas as pd

from service_ingestion.profiling import infer_schema
from service_transformations.tabular import build_schema_summary


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": [1001, 1002, 1003],
            "region": ["North", "South", "East"],
            "amount": [120.50, 89.99, 240.00],
            "ordered_on": pd.to_datetime(["2026-08-01", "2026-08-02", "2026-08-03"]),
        }
    )


def test_ingestion_schema_now_carries_a_canonical_type() -> None:
    schema = infer_schema(dataframe=_frame())
    for column in schema["columns"]:
        assert "canonical_type" in column, column["name"]
        assert column["canonical_type"], column["name"]


def test_the_import_path_and_studio_path_agree_column_for_column() -> None:
    frame = _frame()
    ingestion = {c["name"]: c["canonical_type"] for c in infer_schema(dataframe=frame)["columns"]}
    studio_cols = build_schema_summary(frame).columns
    studio = {
        (c["name"] if isinstance(c, dict) else c.name): (
            c["canonical_type"] if isinstance(c, dict) else c.canonical_type
        )
        for c in studio_cols
    }

    assert ingestion.keys() == studio.keys()
    for name in ingestion:
        assert ingestion[name] == studio[name], (
            f"{name}: import says {ingestion[name]!r}, Studio says {studio[name]!r} — "
            "the two surfaces would disagree, which is the bug this guards."
        )


def test_older_rows_without_canonical_type_still_have_the_legacy_field() -> None:
    # Backward compatibility: rows written before canonical_type existed keep
    # inferred_type, and the frontend falls back to it. New rows carry both.
    schema = infer_schema(dataframe=_frame())
    for column in schema["columns"]:
        assert "inferred_type" in column


def test_a_spaced_phone_number_is_text_not_a_number() -> None:
    """"+44 113 496 1037" was read as 441134961037: spaces stripped as grouping."""
    from service_ingestion.sniff.numbers import looks_numeric, parse_number

    for phone in ("+44 113 496 1037", "+1 512 555 1074", "020 7946 0958", "12 34 56 78"):
        assert not looks_numeric(phone), phone
        assert parse_number(phone, decimal=".", thousands=None) is None, phone


def test_space_grouped_thousands_still_read_as_numbers() -> None:
    from service_ingestion.sniff.numbers import looks_numeric, parse_number

    assert looks_numeric("1 234 567")
    assert parse_number("1 234 567", decimal=".", thousands=None) == 1234567
    assert parse_number("12 345,50", decimal=",", thousands=None) == 12345.5
    assert parse_number("-1 000", decimal=".", thousands=None) == -1000
