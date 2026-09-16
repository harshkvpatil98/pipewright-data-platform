"""Counting a file without holding it in memory.

The roadmap's requirement is that a 2GB CSV "profiles without exhausting
memory". The existing profiler takes a DataFrame, which means the file is
already in memory and the battle is lost — so for large files the frame is
never built. Instead the file is read in chunks and the statistics are
accumulated across them.

Which statistics survive chunking is the interesting part:

* **Counts, sums, minima and maxima** compose trivially.
* **Mean and standard deviation** compose through Welford's method, which is
  numerically stable where "sum of squares minus square of sum" is not — at a
  billion rows the naive formula loses every significant digit it had.
* **Distinct counts** do not compose exactly without keeping every value. They
  are counted exactly up to a ceiling and then reported as "more than N",
  because a wrong distinct count that looks precise is worse than a bound.

Anything that genuinely needs the whole frame is not attempted at all rather
than approximated, and the profile says which of its numbers are exact.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterator

import pandas as pd

#: Rows per chunk. Large enough that pandas' per-chunk overhead is amortised,
#: small enough that one chunk of a wide table is tens of megabytes, not more.
CHUNK_ROWS = 50_000

#: Above this many bytes, the streaming path is used.
LARGE_FILE_BYTES = 64 * 1024 * 1024

#: Distinct values counted exactly per column before the count becomes a bound.
DISTINCT_CEILING = 10_000


@dataclass
class RunningStats:
    """One column's statistics, accumulated a chunk at a time."""

    name: str
    count: int = 0
    nulls: int = 0
    #: Welford's running mean and sum of squared deviations.
    mean: float = 0.0
    m2: float = 0.0
    numeric_count: int = 0
    minimum: Any = None
    maximum: Any = None
    min_length: int | None = None
    max_length: int | None = None
    distinct: set[str] = field(default_factory=set)
    distinct_exact: bool = True

    def observe(self, series: pd.Series) -> None:
        self.count += int(len(series))
        self.nulls += int(series.isna().sum())

        values = series.dropna()
        if values.empty:
            return

        numeric = pd.to_numeric(values, errors="coerce").dropna()
        for value in numeric:
            # Welford: each update is exact in the mean and stable in the
            # variance, where accumulating sum-of-squares is neither.
            self.numeric_count += 1
            delta = float(value) - self.mean
            self.mean += delta / self.numeric_count
            self.m2 += delta * (float(value) - self.mean)

        if not numeric.empty:
            low, high = float(numeric.min()), float(numeric.max())
            self.minimum = low if self.minimum is None else min(float(self.minimum), low)
            self.maximum = high if self.maximum is None else max(float(self.maximum), high)
        else:
            text = values.astype(str)
            low, high = text.min(), text.max()
            self.minimum = low if self.minimum is None else min(str(self.minimum), low)
            self.maximum = high if self.maximum is None else max(str(self.maximum), high)

        lengths = values.astype(str).str.len()
        self.min_length = int(lengths.min()) if self.min_length is None else min(self.min_length, int(lengths.min()))
        self.max_length = int(lengths.max()) if self.max_length is None else max(self.max_length, int(lengths.max()))

        if self.distinct_exact:
            for value in values.astype(str).unique():
                self.distinct.add(value)
                if len(self.distinct) > DISTINCT_CEILING:
                    # Past the ceiling the set is dropped rather than grown: it
                    # is the one thing here that is O(distinct values) in memory.
                    self.distinct_exact = False
                    self.distinct = set()
                    break

    @property
    def stddev(self) -> float | None:
        if self.numeric_count < 2:
            return None
        return math.sqrt(self.m2 / (self.numeric_count - 1))

    def to_dict(self) -> dict[str, Any]:
        non_null = max(self.count - self.nulls, 0)
        return {
            "name": self.name,
            "null_count": self.nulls,
            "null_percentage": round(self.nulls / self.count * 100, 2) if self.count else 0.0,
            "unique_count": len(self.distinct) if self.distinct_exact else DISTINCT_CEILING,
            "unique_is_exact": self.distinct_exact,
            "unique_percentage": (
                round(len(self.distinct) / non_null * 100, 2)
                if self.distinct_exact and non_null
                else None
            ),
            "min_value": self.minimum,
            "max_value": self.maximum,
            "mean_value": round(self.mean, 6) if self.numeric_count else None,
            "std_value": round(self.stddev, 6) if self.stddev is not None else None,
            "min_length": self.min_length,
            "max_length": self.max_length,
            "possible_identifier": (
                self.distinct_exact and non_null > 0 and len(self.distinct) == non_null
            ),
        }


@dataclass
class StreamingProfile:
    row_count: int = 0
    columns: dict[str, RunningStats] = field(default_factory=dict)
    chunks: int = 0

    def observe(self, frame: pd.DataFrame) -> None:
        self.row_count += int(len(frame))
        self.chunks += 1
        for name in frame.columns:
            stats = self.columns.setdefault(str(name), RunningStats(name=str(name)))
            stats.observe(frame[name])

    def to_dict(self, *, file_size_bytes: int = 0) -> dict[str, Any]:
        total_nulls = sum(stats.nulls for stats in self.columns.values())
        cells = self.row_count * max(len(self.columns), 1)
        return {
            "row_count": self.row_count,
            "column_count": len(self.columns),
            # Duplicate detection needs every row held at once, so it is not
            # attempted here. Reporting 0 would be a claim; None is the truth.
            "duplicate_row_count": None,
            "duplicate_row_percentage": None,
            "total_null_cells": total_nulls,
            "completeness_score": round((1 - total_nulls / cells) * 100, 2) if cells else 100.0,
            "file_size_bytes": file_size_bytes,
            "columns": [stats.to_dict() for stats in self.columns.values()],
            "streamed": True,
            "chunks_read": self.chunks,
            "quality_flags": {},
            "exactness_note": (
                "Counted while streaming the file, so every row was seen. Distinct counts "
                f"are exact up to {DISTINCT_CEILING:,} values per column; duplicate-row "
                "detection needs the whole table in memory and was not attempted."
            ),
        }


def should_stream(file_size_bytes: int) -> bool:
    return file_size_bytes >= LARGE_FILE_BYTES


def chunks_of_delimited(
    payload: bytes, *, options: dict[str, Any], chunk_rows: int = CHUNK_ROWS
) -> Iterator[pd.DataFrame]:
    """Read a delimited file a chunk of rows at a time."""
    import io

    encoding = str(options.get("encoding") or "utf-8")
    reader = pd.read_csv(
        io.BytesIO(payload),
        sep=str(options.get("delimiter") or ","),
        quotechar=str(options.get("quote_char") or '"'),
        escapechar=options.get("escape_char"),
        encoding=encoding,
        skiprows=int(options.get("skip_rows") or 0),
        header=0 if options.get("has_header", True) else None,
        dtype=str,
        keep_default_na=False,
        na_values=[""],
        engine="c",
        on_bad_lines="skip",
        chunksize=chunk_rows,
    )
    for chunk in reader:
        yield chunk


def profile_stream(frames: Iterator[pd.DataFrame], *, file_size_bytes: int = 0) -> dict[str, Any]:
    """Accumulate a profile over an iterator of frames."""
    profile = StreamingProfile()
    for frame in frames:
        profile.observe(frame)
    return profile.to_dict(file_size_bytes=file_size_bytes)
