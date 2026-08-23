from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from service_extraction.incremental import (
    WATERMARK_PARAM,
    build_incremental_query,
    compute_watermark,
    merge_frames,
)
from shared_python.errors import BadRequestError


def test_first_incremental_run_has_no_predicate() -> None:
    sql, params = build_incremental_query(
        "postgresql", base_query="SELECT * FROM orders", cursor_column="updated_at", watermark=None
    )
    assert "WHERE" not in sql
    assert 'ORDER BY "updated_at"' in sql
    assert params == {}


def test_incremental_query_binds_watermark_as_parameter() -> None:
    sql, params = build_incremental_query(
        "postgresql",
        base_query="SELECT * FROM orders",
        cursor_column="updated_at",
        watermark="2026-01-01T00:00:00",
    )
    assert f'WHERE "updated_at" > :{WATERMARK_PARAM}' in sql
    assert params == {WATERMARK_PARAM: "2026-01-01T00:00:00"}


def test_incremental_query_quotes_cursor_for_mysql() -> None:
    sql, _ = build_incremental_query(
        "mysql", base_query="SELECT * FROM orders", cursor_column="updated_at", watermark="1"
    )
    assert "`updated_at`" in sql


def test_incremental_query_rejects_missing_cursor() -> None:
    with pytest.raises(BadRequestError, match="cursor column"):
        build_incremental_query("postgresql", base_query="SELECT 1", cursor_column="", watermark=None)


def test_compute_watermark_serialises_timestamps() -> None:
    frame = pd.DataFrame({"updated_at": [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC)]})
    assert compute_watermark(frame, "updated_at").startswith("2026-03-01")


def test_compute_watermark_handles_integers() -> None:
    frame = pd.DataFrame({"id": [3, 9, 5]})
    assert compute_watermark(frame, "id") == "9"


def test_compute_watermark_ignores_nulls_and_empty() -> None:
    assert compute_watermark(pd.DataFrame({"id": []}), "id") is None
    assert compute_watermark(pd.DataFrame({"id": [None, None]}), "id") is None
    assert compute_watermark(pd.DataFrame({"other": [1]}), "id") is None


def test_full_refresh_replaces_existing_rows() -> None:
    existing = pd.DataFrame({"id": [1, 2, 3], "v": ["a", "b", "c"]})
    incoming = pd.DataFrame({"id": [9], "v": ["z"]})
    result = merge_frames(existing, incoming, load_mode="full_refresh", primary_key_columns=["id"])
    assert result.dataframe["id"].tolist() == [9]
    assert result.rows_before == 3


def test_append_keeps_existing_and_adds_new() -> None:
    existing = pd.DataFrame({"id": [1, 2], "v": ["a", "b"]})
    incoming = pd.DataFrame({"id": [3], "v": ["c"]})
    result = merge_frames(existing, incoming, load_mode="incremental_append", primary_key_columns=None)
    assert result.dataframe["id"].tolist() == [1, 2, 3]
    assert result.rows_added == 1
    assert result.rows_updated == 0


def test_merge_upserts_on_primary_key() -> None:
    existing = pd.DataFrame({"id": [1, 2], "v": ["a", "b"]})
    incoming = pd.DataFrame({"id": [2, 3], "v": ["B", "c"]})
    result = merge_frames(existing, incoming, load_mode="incremental_merge", primary_key_columns=["id"])

    merged = result.dataframe.sort_values("id").reset_index(drop=True)
    assert merged["id"].tolist() == [1, 2, 3]
    # The restated row replaces the stored version rather than duplicating it.
    assert merged.loc[merged["id"] == 2, "v"].item() == "B"
    assert result.rows_updated == 1
    assert result.rows_added == 1


def test_merge_deduplicates_within_a_batch_keeping_last() -> None:
    existing = pd.DataFrame({"id": [1], "v": ["a"]})
    incoming = pd.DataFrame({"id": [2, 2], "v": ["first", "second"]})
    result = merge_frames(existing, incoming, load_mode="incremental_merge", primary_key_columns=["id"])

    merged = result.dataframe.sort_values("id").reset_index(drop=True)
    assert merged.loc[merged["id"] == 2, "v"].item() == "second"
    assert any("duplicate" in warning for warning in result.warnings)


def test_merge_supports_composite_keys() -> None:
    existing = pd.DataFrame({"region": ["eu", "us"], "id": [1, 1], "v": ["a", "b"]})
    incoming = pd.DataFrame({"region": ["us"], "id": [1], "v": ["B"]})
    result = merge_frames(existing, incoming, load_mode="incremental_merge", primary_key_columns=["region", "id"])

    merged = result.dataframe.sort_values(["region", "id"]).reset_index(drop=True)
    assert len(merged) == 2
    assert merged.loc[merged["region"] == "us", "v"].item() == "B"
    assert merged.loc[merged["region"] == "eu", "v"].item() == "a"


def test_merge_requires_primary_key() -> None:
    with pytest.raises(BadRequestError, match="primary key"):
        merge_frames(
            pd.DataFrame({"id": [1]}),
            pd.DataFrame({"id": [2]}),
            load_mode="incremental_merge",
            primary_key_columns=[],
        )


def test_merge_rejects_key_missing_from_batch() -> None:
    with pytest.raises(BadRequestError, match="not present in the extracted data"):
        merge_frames(
            pd.DataFrame({"id": [1], "v": ["a"]}),
            pd.DataFrame({"other": [2]}),
            load_mode="incremental_merge",
            primary_key_columns=["id"],
        )


def test_empty_batch_leaves_dataset_untouched() -> None:
    existing = pd.DataFrame({"id": [1, 2]})
    result = merge_frames(existing, pd.DataFrame(), load_mode="incremental_append", primary_key_columns=None)
    assert result.dataframe["id"].tolist() == [1, 2]
    assert result.rows_added == 0
