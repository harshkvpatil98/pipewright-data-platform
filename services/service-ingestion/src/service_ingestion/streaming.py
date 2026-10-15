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
  are counted exactly (with how many rows have each value, which gives the
  commonest values too) up to a ceiling; past it the count is estimated from
  a sample and says it is not exact, because a wrong distinct count that looks
  precise is worse than an estimate that says what it is.
* **Histograms** need every value sorted, so they come from a uniform sample
  of `SAMPLE_VALUES` per column (each value gets a random key and the lowest
  keys are kept, which composes across chunks), scaled to the rows seen.

Anything that genuinely needs the whole frame is not attempted at all rather
than approximated, and the profile says which of its numbers are exact.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterator

import numpy as np
import pandas as pd

from service_ingestion.profiling import COMMON_VALUES, HISTOGRAM_BUCKETS

#: Rows per chunk. Large enough that pandas' per-chunk overhead is amortised,
#: small enough that one chunk of a wide table is tens of megabytes, not more.
CHUNK_ROWS = 50_000

#: Above this many bytes, the streaming path is used.
LARGE_FILE_BYTES = 64 * 1024 * 1024

#: Distinct values counted exactly per column before the count becomes a bound.
DISTINCT_CEILING = 10_000


#: Values sampled per column for its histogram and, past the distinct ceiling, its commonest values.
SAMPLE_VALUES = 20_000

_RANDOM = np.random.default_rng()


@dataclass
class RunningStats:
    """One column's statistics, accumulated a chunk at a time."""

    name: str
    count: int = 0
    nulls: int = 0
    #: Running mean and sum of squared deviations, chunks combined by Chan's method.
    mean: float = 0.0
    m2: float = 0.0
    numeric_count: int = 0
    lowest_number: float | None = None
    highest_number: float | None = None
    lowest_text: str | None = None
    highest_text: str | None = None
    min_length: int | None = None
    max_length: int | None = None
    #: Rows per value, while there are no more than DISTINCT_CEILING values.
    counts: Counter = field(default_factory=Counter)
    distinct_exact: bool = True
    #: A uniform sample: random keys, and each value as text and as a number (NaN when not one).
    sample_keys: np.ndarray = field(default_factory=lambda: np.empty(0))
    sample_text: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=object))
    sample_numbers: np.ndarray = field(default_factory=lambda: np.empty(0))

    def observe(self, series: pd.Series) -> None:
        self.count += int(len(series))
        self.nulls += int(series.isna().sum())

        values = series.dropna()
        if values.empty:
            return
        text = values.astype(str)
        numeric = pd.to_numeric(values, errors="coerce")

        numbers = numeric.dropna().to_numpy(dtype="float64")
        if len(numbers):
            # Chan's combination of two (count, mean, M2) summaries: as stable
            # as Welford's one-value update, without a Python loop per value.
            count_b = len(numbers)
            mean_b = float(numbers.mean())
            m2_b = float(((numbers - mean_b) ** 2).sum())
            total = self.numeric_count + count_b
            delta = mean_b - self.mean
            self.mean += delta * count_b / total
            self.m2 += m2_b + delta * delta * self.numeric_count * count_b / total
            self.numeric_count = total
            low, high = float(numbers.min()), float(numbers.max())
            self.lowest_number = low if self.lowest_number is None else min(self.lowest_number, low)
            self.highest_number = high if self.highest_number is None else max(self.highest_number, high)

        low_text, high_text = text.min(), text.max()
        self.lowest_text = low_text if self.lowest_text is None else min(self.lowest_text, low_text)
        self.highest_text = high_text if self.highest_text is None else max(self.highest_text, high_text)

        lengths = text.str.len()
        self.min_length = int(lengths.min()) if self.min_length is None else min(self.min_length, int(lengths.min()))
        self.max_length = int(lengths.max()) if self.max_length is None else max(self.max_length, int(lengths.max()))

        if self.distinct_exact:
            self.counts.update(text.value_counts().to_dict())
            if len(self.counts) > DISTINCT_CEILING:
                # Past the ceiling the counts are dropped rather than grown: they
                # are the one thing here that is O(distinct values) in memory.
                self.distinct_exact = False
                self.counts = Counter()

        keys = np.concatenate([self.sample_keys, _RANDOM.random(len(text))])
        if len(keys) > SAMPLE_VALUES:
            keep = np.argpartition(keys, SAMPLE_VALUES)[:SAMPLE_VALUES]
        else:
            keep = slice(None)
        self.sample_keys = keys[keep]
        self.sample_text = np.concatenate([self.sample_text, text.to_numpy(dtype=object)])[keep]
        self.sample_numbers = np.concatenate([self.sample_numbers, numeric.to_numpy(dtype="float64")])[keep]

    @property
    def stddev(self) -> float | None:
        if self.numeric_count < 2:
            return None
        return math.sqrt(self.m2 / (self.numeric_count - 1))

    @property
    def non_null(self) -> int:
        return max(self.count - self.nulls, 0)

    def _distinct(self) -> int:
        """Exact while counted; past the ceiling, estimated from the sample.

        Chao1, bias-corrected: the values seen in the sample, plus f1²/2(f2+1)
        unseen ones, where f1 and f2 are the values seen once and twice. A
        sample where nearly every value is new says most are unseen (a key);
        one where values repeat says few are. Never more than the rows.
        """
        if self.distinct_exact:
            return len(self.counts)
        seen = pd.Series(self.sample_text).value_counts()
        once, twice = int((seen == 1).sum()), int((seen == 2).sum())
        unseen = once * (once - 1) / (2 * (twice + 1))
        return int(max(DISTINCT_CEILING + 1, min(self.non_null, len(seen) + unseen)))

    def _histogram(self) -> dict[str, Any] | None:
        # Only a column whose every value is a number: a few numbers among
        # text describe nothing a range filter would keep.
        if not self.numeric_count or self.numeric_count != self.non_null:
            return None
        sample = self.sample_numbers[~np.isnan(self.sample_numbers)]
        if len(sample) < 2:
            return None
        edges = np.unique(np.quantile(sample, np.linspace(0, 1, HISTOGRAM_BUCKETS + 1)))
        if len(edges) < 2:
            return None
        # The sample's extremes are not the column's: the true ones close the ends.
        edges[0], edges[-1] = float(self.lowest_number), float(self.highest_number)
        counts, _ = np.histogram(sample, bins=edges)
        scale = self.numeric_count / len(sample)
        return {"bounds": [float(edge) for edge in edges], "rows": [int(round(count * scale)) for count in counts]}

    def _common(self, distinct: int) -> list[dict[str, Any]]:
        if distinct >= self.non_null:
            return []
        if self.distinct_exact:
            top = self.counts.most_common(COMMON_VALUES)
            return [{"value": value, "rows": int(rows)} for value, rows in top]
        seen = pd.Series(self.sample_text).value_counts().head(COMMON_VALUES)
        scale = self.non_null / max(len(self.sample_text), 1)
        # A value seen a handful of times in the sample is noise, not common.
        return [{"value": str(value), "rows": int(round(rows * scale))} for value, rows in seen.items() if rows >= 5]

    def to_dict(self) -> dict[str, Any]:
        non_null = self.non_null
        distinct = self._distinct()
        numeric = self.numeric_count > 0
        return {
            "name": self.name,
            "null_count": self.nulls,
            "null_percentage": round(self.nulls / self.count * 100, 2) if self.count else 0.0,
            "unique_count": distinct,
            "unique_is_exact": self.distinct_exact,
            "unique_percentage": (
                round(distinct / non_null * 100, 2)
                if self.distinct_exact and non_null
                else None
            ),
            "min_value": self.lowest_number if numeric else self.lowest_text,
            "max_value": self.highest_number if numeric else self.highest_text,
            "mean_value": round(self.mean, 6) if self.numeric_count else None,
            "std_value": round(self.stddev, 6) if self.stddev is not None else None,
            "min_length": self.min_length,
            "max_length": self.max_length,
            "possible_identifier": (
                self.distinct_exact and non_null > 0 and distinct == non_null
            ),
            "histogram": self._histogram(),
            "common_values": self._common(distinct) if non_null else [],
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
                f"are exact up to {DISTINCT_CEILING:,} values per column and estimated past "
                f"that; histograms come from a sample of {SAMPLE_VALUES:,} values per column. "
                "Duplicate-row detection needs the whole table in memory and was not attempted."
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
