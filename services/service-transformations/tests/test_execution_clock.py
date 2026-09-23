"""The evaluation instant (phase-18 §3).

`now()`, `today()` and `age_years()` must read one frozen instant when a run
installs it, so a run's recorded result can be reproduced later -- and the real
clock when nothing is frozen, so a Studio preview still says today.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from service_transformations.ir.clock import evaluation_instant, frozen_clock, is_frozen
from shared_python.types import STRING
from service_transformations.ir.expressions import Call, Column, Literal
from service_transformations.ir.pandas_backend import evaluate

FRAME = pd.DataFrame({"born": pd.to_datetime(["1990-06-15", "2000-01-01", None])})
INSTANT = datetime(2031, 3, 10, 9, 30, tzinfo=UTC)


def test_nothing_is_frozen_by_default_and_the_clock_is_utc():
    assert not is_frozen()
    instant = evaluation_instant()
    assert instant.tzinfo is not None
    assert abs((datetime.now(UTC) - instant).total_seconds()) < 5


def test_a_frozen_clock_drives_now_and_today():
    with frozen_clock(INSTANT):
        assert is_frozen()
        now = evaluate(Call("now", ()), FRAME)
        today = evaluate(Call("today", ()), FRAME)
    assert list(now) == [pd.Timestamp(INSTANT)] * 3
    assert list(today) == [INSTANT.date()] * 3
    assert not is_frozen()  # reset on exit, even for the next test in this process


def test_age_years_is_measured_against_the_frozen_instant_not_the_wall_clock():
    with frozen_clock(datetime(2031, 3, 10, tzinfo=UTC)):
        early = evaluate(Call("age_years", (Column("born"),)), FRAME)
    with frozen_clock(datetime(2041, 3, 10, tzinfo=UTC)):
        late = evaluate(Call("age_years", (Column("born"),)), FRAME)
    assert list(early)[:2] == [40, 31]
    assert list(late)[:2] == [50, 41]
    assert pd.isna(list(early)[2])
    # Same instant, same answer -- the property a replay depends on.
    with frozen_clock(datetime(2031, 3, 10, tzinfo=UTC)):
        again = evaluate(Call("age_years", (Column("born"),)), FRAME)
    assert list(again)[:2] == list(early)[:2]


def test_age_years_with_an_explicit_as_of_date_ignores_every_clock():
    with frozen_clock(datetime(2099, 1, 1, tzinfo=UTC)):
        ages = evaluate(Call("age_years", (Column("born"), Literal("2020-06-14", STRING))), FRAME)
    # The day before the first birthday of the year: 29, not 30.
    assert list(ages)[:2] == [29, 20]


def test_a_naive_instant_is_taken_as_utc_and_nesting_restores_the_outer_one():
    with frozen_clock(datetime(2030, 1, 1)) as outer:
        assert outer.tzinfo is UTC
        with frozen_clock(datetime(2035, 1, 1, tzinfo=UTC)):
            assert evaluation_instant().year == 2035
        assert evaluation_instant().year == 2030
