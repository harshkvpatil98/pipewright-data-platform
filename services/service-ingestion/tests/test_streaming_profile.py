"""A large file's profile, counted a chunk at a time (D2, O1).

Files of 64 MB and more are profiled by streaming them, so their profile
must say what the in-memory one says wherever it can: the same counts,
spread and commonest values, and a histogram good enough to estimate
from. Where it cannot be exact (distinct values past the ceiling), it
says so and estimates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from service_ingestion import streaming
from service_ingestion.profiling import build_profile
from shared_python.statistics import from_profile

RNG = np.random.default_rng(22)
N = 8_000


@pytest.fixture(autouse=True)
def _same_sample_every_run(monkeypatch) -> None:
    monkeypatch.setattr(streaming, "_RANDOM", np.random.default_rng(5))


def _frame(rows: int = N) -> pd.DataFrame:
    amount = RNG.gamma(2.0, 40.0, rows).round(2)
    frame = pd.DataFrame({
        "order_id": np.arange(rows),
        "customer_id": RNG.integers(0, rows // 3, rows),
        "region": RNG.choice(["eu", "us", "apac", "latam"], rows, p=[0.5, 0.3, 0.15, 0.05]),
        "amount": amount,
    })
    frame.loc[RNG.choice(rows, rows // 20, replace=False), "amount"] = np.nan
    return frame


def _chunks(frame: pd.DataFrame, size: int = 1_000):
    # As `chunks_of_delimited` reads a CSV: every value text, an empty cell missing. (The two
    # profiles round the mean and spread to different places, hence the tolerance below.)
    text = frame.astype(object).where(frame.notna(), None).astype(str).where(frame.notna(), None)
    for start in range(0, len(text), size):
        yield text.iloc[start:start + size]


def _by_name(profile: dict) -> dict[str, dict]:
    return {column["name"]: column for column in profile["columns"]}


def test_a_streamed_profile_says_what_the_whole_frame_says() -> None:
    frame = _frame()
    whole = _by_name(build_profile(dataframe=frame, sample_limit=5, file_size_bytes=0))
    streamed = _by_name(streaming.profile_stream(_chunks(frame)))
    for name in ("order_id", "customer_id", "region", "amount"):
        a, b = whole[name], streamed[name]
        assert b["null_count"] == a["null_count"]
        assert b["unique_count"] == a["unique_count"] and b["unique_is_exact"]
        if a["mean_value"] is not None:
            assert b["mean_value"] == pytest.approx(a["mean_value"], abs=1e-3)
            assert b["std_value"] == pytest.approx(a["std_value"], abs=1e-3)
            assert b["min_value"] == pytest.approx(a["min_value"])
            assert b["max_value"] == pytest.approx(a["max_value"])
    assert streamed["region"]["common_values"] == whole["region"]["common_values"]
    assert streamed["order_id"]["common_values"] == []  # every value differs: none is common
    # Fewer rows than the sample holds: the histogram is the whole frame's.
    assert streamed["amount"]["histogram"] == whole["amount"]["histogram"]
    assert streamed["region"]["histogram"] is None


def test_past_the_distinct_ceiling_the_count_is_an_estimate_that_says_so(monkeypatch) -> None:
    monkeypatch.setattr(streaming, "DISTINCT_CEILING", 500)
    monkeypatch.setattr(streaming, "SAMPLE_VALUES", 4_000)
    frame = _frame(60_000)
    streamed = _by_name(streaming.profile_stream(_chunks(frame, 5_000)))
    key = streamed["order_id"]
    assert not key["unique_is_exact"] and key["unique_percentage"] is None
    assert key["unique_count"] == pytest.approx(60_000, rel=0.1)
    # A column whose values repeat a few times each: about 20,000 of them.
    truth = frame["customer_id"].nunique()
    assert streamed["customer_id"]["unique_count"] == pytest.approx(truth, rel=0.1)
    assert streamed["region"]["unique_is_exact"] and streamed["region"]["unique_count"] == 4
    # The histogram is from a sample, scaled: its rows add up to the values seen.
    histogram = streamed["amount"]["histogram"]
    assert sum(histogram["rows"]) == pytest.approx(frame["amount"].notna().sum(), rel=0.01)
    assert histogram["bounds"][0] == frame["amount"].min() and histogram["bounds"][-1] == frame["amount"].max()


def test_estimates_from_a_streamed_profile_land_near_the_truth(monkeypatch) -> None:
    from shared_python.types import FLOAT64, INT64, STRING
    from service_transformations.ir.estimate import estimate
    from service_transformations.ir.expressions import Call, Column, Literal
    from service_transformations.ir.nodes import Filter, Scan

    monkeypatch.setattr(streaming, "SAMPLE_VALUES", 5_000)
    frame = _frame(80_000)
    stats = from_profile(streaming.profile_stream(_chunks(frame, 10_000)))
    assert stats.columns["amount"].kind == "number"
    scan = Scan("orders", (("order_id", INT64), ("customer_id", INT64), ("region", STRING), ("amount", FLOAT64)))
    for predicate, truth in (
        (Call("lt", (Column("amount"), Literal(60.0, FLOAT64))), int((frame["amount"] < 60).sum())),
        (Call("eq", (Column("region"), Literal("apac", STRING))), int((frame["region"] == "apac").sum())),
    ):
        assert estimate(Filter(scan, predicate), {"orders": stats}).rows == pytest.approx(truth, rel=0.05)


def test_a_column_that_is_text_in_one_chunk_and_numbers_in_another() -> None:
    """It used to compare a number with a text minimum and stop the profile with a ValueError."""
    chunks = [pd.DataFrame({"code": ["A1", "B2"]}), pd.DataFrame({"code": ["123", "45"]})]
    streamed = _by_name(streaming.profile_stream(iter(chunks)))["code"]
    whole = _by_name(build_profile(dataframe=pd.concat(chunks), sample_limit=5, file_size_bytes=0))["code"]
    assert (streamed["min_value"], streamed["max_value"]) == (whole["min_value"], whole["max_value"]) == (45, 123)
    assert streamed["histogram"] is None  # not every value is a number
    assert streamed["unique_count"] == 4
