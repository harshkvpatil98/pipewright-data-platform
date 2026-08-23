"""Files on disk: patterns, formats, incremental discovery, and writing back."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from service_connectors.adapters.files import (
    LocalFileConnector,
    RemoteFile,
    combine,
    cursor_for,
    matches,
    newer_than,
)
from service_connectors.formats import write_bytes
from service_connectors.protocol import ConnectorError, StreamRef


@pytest.fixture()
def folder(tmp_path: Path) -> Iterator[Path]:
    frame = pd.DataFrame({"id": [1, 2], "name": ["a", "b"]})
    (tmp_path / "2026").mkdir()
    (tmp_path / "orders.csv").write_bytes(write_bytes(frame, format="csv"))
    (tmp_path / "2026" / "orders.parquet").write_bytes(write_bytes(frame, format="parquet"))
    (tmp_path / "notes.md").write_text("not data")
    yield tmp_path


def _config(folder: Path, **overrides) -> dict:
    return {"directory": str(folder), "pattern": "*", **overrides}


# ---- pure helpers ----


def test_a_glob_matches_the_filename_as_well_as_the_path():
    """So *.csv works on 2026/03/orders.csv without anyone writing **/*.csv."""
    assert matches("2026/03/orders.csv", "*.csv")
    assert matches("2026/03/orders.csv", "2026/*/orders.csv")
    assert not matches("2026/03/orders.parquet", "*.csv")


def test_no_pattern_matches_everything():
    assert matches("anything.txt", None)
    assert matches("anything.txt", "")


def test_incremental_discovery_takes_only_what_is_new():
    now = datetime.now(UTC)
    files = [
        RemoteFile("old.csv", 10, now - timedelta(days=2)),
        RemoteFile("new.csv", 10, now),
    ]
    cursor = (now - timedelta(days=1)).isoformat()
    assert [file.path for file in newer_than(files, cursor)] == ["new.csv"]


def test_no_cursor_means_read_everything():
    files = [RemoteFile("a.csv", 1, datetime.now(UTC))]
    assert newer_than(files, None) == files


def test_an_unreadable_cursor_falls_back_to_reading_everything():
    """Better a repeat than silently skipping a night's files."""
    files = [RemoteFile("a.csv", 1, datetime.now(UTC))]
    assert newer_than(files, "not-a-date") == files


def test_the_next_cursor_is_the_newest_file_read():
    now = datetime.now(UTC)
    files = [RemoteFile("a", 1, now - timedelta(hours=1)), RemoteFile("b", 1, now)]
    assert cursor_for(files) == now.isoformat()
    assert cursor_for([]) is None


def test_combining_files_records_which_one_each_row_came_from():
    """When a nightly load goes wrong, that is always the first question."""
    left = pd.DataFrame({"id": [1]})
    right = pd.DataFrame({"id": [2]})
    combined = combine([left, right], source_paths=["a.csv", "b.csv"])
    assert list(combined["_source_file"]) == ["a.csv", "b.csv"]


def test_combining_nothing_gives_an_empty_frame():
    assert combine([], source_paths=[]).empty


# ---- against real files ----


def test_test_counts_what_matches(folder: Path):
    result = LocalFileConnector().test(_config(folder, pattern="*.csv"))
    assert result.success
    assert "1 file(s)" in result.message


def test_a_pattern_matching_nothing_is_reported_but_not_an_error(folder: Path):
    result = LocalFileConnector().test(_config(folder, pattern="*.avro"))
    assert result.success
    assert "nothing matches" in result.message


def test_unreadable_formats_are_warned_about_not_hidden(folder: Path):
    result = LocalFileConnector().test(_config(folder))
    assert any("unrecognised format" in warning for warning in result.warnings)


def test_a_missing_directory_fails_the_test_clearly(tmp_path: Path):
    result = LocalFileConnector().test({"directory": str(tmp_path / "nope"), "pattern": "*"})
    assert result.success is False
    assert "does not exist" in result.message


def test_a_relative_directory_is_refused(folder: Path):
    """It would resolve against whatever the worker's cwd happens to be."""
    result = LocalFileConnector().test({"directory": "data/incoming", "pattern": "*"})
    assert result.success is False
    assert "absolute path" in result.message


def test_discovery_lists_matching_files_with_their_size(folder: Path):
    streams = LocalFileConnector().discover(_config(folder, pattern="*.csv"))
    assert [stream.name for stream in streams] == ["orders.csv"]
    assert streams[0].detail["size_bytes"] > 0


def test_reading_picks_the_format_from_the_extension(folder: Path):
    result = LocalFileConnector().read(_config(folder, pattern="*.parquet"))
    assert result.row_count == 2
    assert "id" in result.dataframe.columns


def test_several_files_are_read_into_one_frame(folder: Path):
    frame = pd.DataFrame({"id": [3], "name": ["c"]})
    (folder / "more.csv").write_bytes(write_bytes(frame, format="csv"))

    result = LocalFileConnector().read(_config(folder, pattern="*.csv"))
    assert result.row_count == 3
    assert set(result.dataframe["_source_file"]) == {"orders.csv", "more.csv"}


def test_reading_returns_a_cursor_to_resume_from(folder: Path):
    result = LocalFileConnector().read(_config(folder, pattern="*.csv"))
    assert result.next_cursor is not None

    # Nothing new since, so a second read finds nothing.
    again = LocalFileConnector().read(
        _config(folder, pattern="*.csv"), cursor=result.next_cursor
    )
    assert again.row_count == 0


def test_a_file_added_after_the_cursor_is_picked_up(folder: Path):
    first = LocalFileConnector().read(_config(folder, pattern="*.csv"))

    time.sleep(0.01)
    late = folder / "late.csv"
    late.write_bytes(write_bytes(pd.DataFrame({"id": [9], "name": ["z"]}), format="csv"))
    future = time.time() + 5
    os.utime(late, (future, future))

    second = LocalFileConnector().read(
        _config(folder, pattern="*.csv"), cursor=first.next_cursor
    )
    assert second.row_count == 1
    assert set(second.dataframe["_source_file"]) == {"late.csv"}


def test_an_unrecognised_format_is_skipped_with_a_warning(folder: Path):
    result = LocalFileConnector().read(_config(folder))
    assert any("notes.md" in warning for warning in result.warnings)
    assert result.row_count == 4  # the csv and the parquet, two rows each


def test_columns_can_be_read_without_loading_everything(folder: Path):
    columns = LocalFileConnector().columns(
        _config(folder), StreamRef(name="orders.csv", kind="file")
    )
    assert [column.name for column in columns] == ["id", "name"]


def test_escaping_the_directory_is_refused(folder: Path, tmp_path: Path):
    """A stream name with .. would otherwise read anything the process can see.

    The path has a readable extension on purpose: a traversal ending in
    something unrecognised is skipped for the wrong reason, and would pass this
    test without the containment check existing at all.
    """
    outside = tmp_path.parent / "secrets.csv"
    outside.write_text("id,value\n1,leaked\n")

    with pytest.raises(ConnectorError) as caught:
        LocalFileConnector().read(
            _config(folder), StreamRef(name=f"../{outside.name}", kind="file")
        )
    assert "outside the configured directory" in caught.value.message


def test_a_traversal_that_looks_unreadable_is_still_never_fetched(folder: Path):
    result = LocalFileConnector().read(
        _config(folder), StreamRef(name="../../../etc/passwd", kind="file")
    )
    assert result.row_count == 0


def test_writing_back_creates_the_file(folder: Path):
    frame = pd.DataFrame({"id": [7], "name": ["g"]})
    result = LocalFileConnector().write(
        _config(folder), StreamRef(name="out/exported.csv", kind="file"), frame
    )
    assert result.rows_written == 1
    assert (folder / "out" / "exported.csv").exists()


def test_appending_reads_and_concatenates_rather_than_appending_bytes(folder: Path):
    """Appending bytes works for CSV and corrupts a Parquet file."""
    connector = LocalFileConnector()
    frame = pd.DataFrame({"id": [1], "name": ["a"]})
    connector.write(_config(folder), StreamRef(name="log.parquet", kind="file"), frame)
    connector.write(
        _config(folder),
        StreamRef(name="log.parquet", kind="file"),
        pd.DataFrame({"id": [2], "name": ["b"]}),
        mode="append",
    )

    back = connector.read(_config(folder, pattern="log.parquet"))
    assert back.row_count == 2


def test_appending_to_nothing_creates_it_and_says_so(folder: Path):
    result = LocalFileConnector().write(
        _config(folder),
        StreamRef(name="fresh.csv", kind="file"),
        pd.DataFrame({"id": [1]}),
        mode="append",
    )
    assert any("was created" in warning for warning in result.warnings)


def test_an_unsupported_write_mode_is_refused(folder: Path):
    with pytest.raises(ConnectorError) as caught:
        LocalFileConnector().write(
            _config(folder),
            StreamRef(name="x.csv", kind="file"),
            pd.DataFrame({"id": [1]}),
            mode="upsert",
        )
    assert "upsert" in caught.value.message
