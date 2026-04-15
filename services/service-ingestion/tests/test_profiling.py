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
    assert "id" in profile["quality_flags"]["potential_id_columns"]
