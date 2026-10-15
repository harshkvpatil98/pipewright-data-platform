import pandas as pd

from service_ingestion.profiling import build_preview, build_profile, infer_schema


def test_profile_generation_captures_quality_metrics() -> None:
    dataframe = pd.DataFrame(
        [
            {"id": 1, "email": "a@example.com", "score": 10.0},
            {"id": 2, "email": None, "score": 15.0},
            {"id": 3, "email": "c@example.com", "score": None},
            {"id": 3, "email": "c@example.com", "score": None},
        ]
    )
    schema = infer_schema(dataframe=dataframe)
    preview = build_preview(dataframe=dataframe, limit=2)
    profile = build_profile(dataframe=dataframe, sample_limit=3, file_size_bytes=1024)

    assert schema["ordered_columns"] == ["id", "email", "score"]
    assert len(preview["rows"]) == 2
    assert profile["row_count"] == 4
    assert profile["duplicate_row_count"] == 1
    assert "score" in profile["quality_flags"]["high_null_columns"]
    # The duplicated row repeats id=3, so id is not a unique identifier here.
    assert "id" not in profile["quality_flags"]["potential_id_columns"]


def test_profile_flags_unique_column_as_potential_identifier() -> None:
    dataframe = pd.DataFrame(
        [
            {"id": 1, "email": "a@example.com"},
            {"id": 2, "email": "b@example.com"},
            {"id": 3, "email": "c@example.com"},
        ]
    )
    profile = build_profile(dataframe=dataframe, sample_limit=3, file_size_bytes=1024)

    assert profile["duplicate_row_count"] == 0
    assert "id" in profile["quality_flags"]["potential_id_columns"]


def test_sample_values_and_types_from_each_distinct_value_once():
    """The first different values in the order they appear, and the types among them, read
    without walking the column value by value (D2); the answers are what they were."""
    import datetime as dt

    import numpy as np

    rows = 30_000
    frame = pd.DataFrame({
        "region": ["west", "north", "west", "east"] * (rows // 4),
        "stamp": pd.to_datetime(["2026-01-02 03:04:05", "2026-02-03 04:05:06"] * (rows // 2)),
        "mixed": pd.Series([1, "a", 2.5, None] * (rows // 4), dtype=object),
        "numbers": pd.Series([np.int64(3), 4] * (rows // 2), dtype=object),
        "day": pd.Series([dt.date(2026, 1, 1), dt.date(2026, 1, 2)] * (rows // 2), dtype=object),
    })
    columns = {c["name"]: c for c in build_profile(dataframe=frame, sample_limit=5, file_size_bytes=0)["columns"]}
    assert columns["region"]["sample_values"] == ["west", "north", "east"]
    assert columns["stamp"]["sample_values"] == ["2026-01-02T03:04:05", "2026-02-03T04:05:06"]
    assert columns["mixed"]["mixed_type_suspected"] and columns["mixed"]["inferred_type"] == "mixed"
    assert columns["numbers"]["inferred_type"] == "mixed" and columns["numbers"]["mixed_type_suspected"]
    assert columns["day"]["inferred_type"] == "date" and not columns["day"]["mixed_type_suspected"]
