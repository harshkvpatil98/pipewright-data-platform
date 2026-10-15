"""Everyday searches find the tool people mean, first (E1).

Measured before E1: of 29 searches, 26 found nothing, "rank" found only
Sort and "t test" only Filter. These are those searches, answered by a
tool; the ones a built-in step or a Studio command answers (an anti join, a
group by, turning a step off) are in the Studio's own test, against this
same catalogue (`apps/web/src/features/studio/palette-search.test.ts`).
"""

from __future__ import annotations

import pytest

from service_transformations.tools import search

FIRST = {
    "running total": "window.cumulative_sum",
    "moving average": "window.moving_average",
    "previous row": "window.lag",
    "percentile": "window.percent_rank",
    "fuzzy join": "join.fuzzy",
    "random sample": "sample.random",
    "train/test split": "sample.train_test",
    "distance": "geo.distance",
    "point in polygon": "geo.point_in_polygon",
    "correlation": "stats.correlation_matrix",
    "cluster": "match.cluster",
    "one-hot": "ml.one_hot",
    "holiday": "date.is_holiday",
    "lookup": "lookup.from_dataset",
    "fill forward": "null.fill_forward",
    "interpolate": "null.interpolate_linear",
    "assert unique": "assert.unique",
    "golden record": "match.golden_record",
    "geocode": "geo.geocode",
    "unit convert": "numeric.convert_units",
    "transpose": "reshape.transpose",
    "SQL": "code.sql",
    "UUID": "key.uuid",
    "rank": "window.rank",
    "t test": "stats.t_test",
    # And searches that found the wrong tool first until E1's ranking.
    "trim": "text.trim",
    "remove duplicates": "rows.deduplicate",
    "filter formula": "rows.filter_formula",
    "title case": "text.title_case",
    "extract year from date": "date.year",
}


@pytest.mark.parametrize(("query", "expected"), sorted(FIRST.items()))
def test_an_everyday_search_finds_the_tool_first(query: str, expected: str) -> None:
    found = [spec.name for spec in search(query, limit=5)]
    assert found and found[0] == expected, f"{query!r} found {found}"


def test_a_forecast_search_offers_the_forecasts_first() -> None:
    found = [spec.name for spec in search("forecast", limit=3)]
    assert found and all(name.startswith("ml.forecast_") for name in found)


def test_a_single_letter_is_a_whole_word() -> None:
    """The "t" of "t test" once matched the start of "training", and put the train/test split first."""
    assert "sample.train_test" not in [spec.name for spec in search("t test", limit=3)]


def test_every_word_still_has_to_match() -> None:
    assert search("moving banana") == []
