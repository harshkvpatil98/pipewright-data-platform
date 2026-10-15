"""What E1's local tools promise, beyond their documented examples.

The registry-wide tests (`test_tool_library.py`) hold every tool to empty,
all-empty and single-row input and run its example; these pin down the
behaviour each family is for: a check that stops a run names the rows, a
lookup never adds rows, matching gives the Assistant's answer, a token
reveals only under its key.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from shared_python.errors import BadRequestError

from service_transformations.executor import apply_transformation_steps
from service_transformations.ir.clock import frozen_clock, watching_reads
from service_transformations.steps.context import StepContext

OTHER = "00000000-0000-0000-0000-0000000000aa"


@pytest.fixture(autouse=True)
def _token_key(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())


def run(frame: pd.DataFrame, tool: str, other: pd.DataFrame | None = None, **config):
    context = StepContext(resolve_dataset=lambda _id: (other if other is not None else pd.DataFrame()).copy(),
                          describe_dataset=lambda _id: "Reference")
    if other is not None:
        config.setdefault("right_dataset_id", OTHER)
    return apply_transformation_steps(frame, [{"step_type": "tool", "config": {"tool": tool, **config}}], context)


# ------------------------------------------------------------------ checks


class TestChecks:
    ORDERS = pd.DataFrame({"id": [1, 2, 2, 4, 5, 6, 7], "qty": [1, -1, 3, -2, -5, -6, -7]})

    def test_a_failing_check_stops_the_run_and_names_the_rows(self) -> None:
        with pytest.raises(BadRequestError) as caught:
            run(self.ORDERS, "assert.in_range", column="qty", minimum=0)
        message = str(caught.value)
        assert "Check numbers are in a range: 5 rows have a qty outside 0" in message
        assert "Rows 2, 4, 5, 6 and 7." in message

    def test_more_than_five_failing_rows_say_how_many_more(self) -> None:
        frame = pd.DataFrame({"qty": [-1] * 8})
        with pytest.raises(BadRequestError, match=r"Rows 1, 2, 3, 4, 5 and 3 more\."):
            run(frame, "assert.in_range", column="qty", minimum=0)

    def test_warn_keeps_the_data_and_says_so(self) -> None:
        out, warnings = run(self.ORDERS, "assert.unique", columns=["id"], on_failure="warn")
        pd.testing.assert_frame_equal(out, self.ORDERS)
        assert any("2 rows share their id with another" in w for w in warnings)

    def test_a_whole_data_check_cannot_mark_rows(self) -> None:
        with pytest.raises(BadRequestError, match="cannot|must be one of|all the rows together"):
            run(self.ORDERS, "assert.row_count", minimum=1, on_failure="mark the rows")

    def test_row_count(self) -> None:
        with pytest.raises(BadRequestError, match="7 rows, fewer than 10"):
            run(self.ORDERS, "assert.row_count", minimum=10)

    def test_freshness_reads_the_run_s_frozen_clock_and_says_it_read_it(self) -> None:
        frame = pd.DataFrame({"at": ["2026-10-01 00:00"]})
        with frozen_clock(datetime(2026, 10, 1, 12, tzinfo=UTC)), watching_reads() as reads:
            run(frame, "assert.fresh", column="at", hours=24)
        assert reads, "a check that reads the clock must say so, or its result would be kept"
        with frozen_clock(datetime(2026, 10, 9, tzinfo=UTC)):
            with pytest.raises(BadRequestError, match="192.0 hours old, more than 24"):
                run(frame, "assert.fresh", column="at", hours=24)

    def test_referential_integrity(self) -> None:
        customers = pd.DataFrame({"id": [1, 2]})
        orders = pd.DataFrame({"customer": [1, 3, None]})
        with pytest.raises(BadRequestError, match="1 row has a customer that Reference does not have"):
            run(orders, "assert.found_in", customers, column="customer", right_on="id")

    def test_distribution_drift_is_caught(self) -> None:
        then = pd.DataFrame({"v": list(range(100))})
        now = pd.DataFrame({"v": [value + 60 for value in range(100)]})
        with pytest.raises(BadRequestError, match="Kolmogorov-Smirnov distance between them is 0.600"):
            run(now, "assert.distribution_stable", then, column="v")
        run(then, "assert.distribution_stable", then, column="v")

    def test_categories_drift_by_population_stability(self) -> None:
        then = pd.DataFrame({"c": ["a"] * 50 + ["b"] * 50})
        now = pd.DataFrame({"c": ["a"] * 95 + ["b"] * 5})
        with pytest.raises(BadRequestError, match="population stability index"):
            run(now, "assert.distribution_stable", then, column="c")

    def test_schema(self) -> None:
        frame = pd.DataFrame({"id": ["x"], "extra": [1]})
        with pytest.raises(BadRequestError, match="Name is missing; id is text, not number; extra is not expected"):
            run(frame, "assert.schema", columns=["id:number", "name"], extra_allowed=False)

    def test_marked_rows_can_be_quarantined_after(self) -> None:
        out, _ = run(self.ORDERS, "assert.in_range", column="qty", minimum=0, on_failure="mark the rows",
                     flag="bad_qty")
        assert out["bad_qty"].tolist() == [False, True, False, True, True, True, True]


# ---------------------------------------------------------------- matching


class TestMatching:
    NAMES = pd.DataFrame({"name": ["Acme Ltd", "ACME Limited", "Acme Widgets", "Globex", "Globex Corp", None]})

    def test_it_gives_the_assistants_answer(self) -> None:
        from service_intelligence.matching import find_duplicates

        report = find_duplicates(self.NAMES["name"].dropna().tolist())
        assistant_pairs = {frozenset((c.left_value, c.right_value)) for c in report.candidates}
        out, _ = run(self.NAMES, "match.cluster", column="name")
        groups = out.dropna(subset=["name"]).groupby("name_group")["name"].apply(set)
        recipe_pairs = {frozenset((a, b)) for members in groups for a in members for b in members if a < b}
        assert assistant_pairs and assistant_pairs <= recipe_pairs

    def test_fuzzy_dedupe_keeps_the_first_and_says_how_many_went(self) -> None:
        out, warnings = run(self.NAMES, "dedupe.fuzzy", column="name")
        assert out["name"].tolist()[:2] == ["Acme Ltd", "Acme Widgets"]
        assert any("were removed" in w for w in warnings)

    def test_sound_alike_by_soundex(self) -> None:
        frame = pd.DataFrame({"name": ["Robert", "Rupert", "Rubin"]})
        out, _ = run(frame, "match.cluster", column="name", method="sound", threshold=1)
        assert out["name_group"].tolist() == [1, 1, 2]

    def test_survivorship_most_recent(self) -> None:
        frame = pd.DataFrame({"id": [1, 1], "email": ["old@x", "new@x"], "seen": ["2026-01-01", "2026-06-01"]})
        out, _ = run(frame, "match.survivorship", by=["id"], rule="most recent", recent_by="seen")
        assert out["email"].tolist() == ["new@x"]

    def test_survivorship_most_recent_needs_its_column(self) -> None:
        frame = pd.DataFrame({"id": [1], "email": ["x"]})
        with pytest.raises(BadRequestError, match="which date column"):
            run(frame, "match.survivorship", by=["id"], rule="most recent")


# ----------------------------------------------------------------- lookups


class TestLookups:
    def test_a_lookup_never_adds_rows_however_many_match(self) -> None:
        orders = pd.DataFrame({"code": ["N", "N", "S"]})
        regions = pd.DataFrame({"code": ["N", "N", "S"], "region": ["North", "Again", "South"]})
        out, _ = run(orders, "lookup.from_dataset", regions, on=["code"], right_on=["code"], bring=["region"])
        assert len(out) == 3 and out["region"].tolist() == ["North", "North", "South"]

    def test_it_matches_numbers_written_differently(self) -> None:
        orders = pd.DataFrame({"code": [1, 2]})
        regions = pd.DataFrame({"code": ["1", "2"], "region": ["a", "b"]})
        out, _ = run(orders, "lookup.from_dataset", regions, on=["code"], right_on=["code"], bring=["region"])
        assert out["region"].tolist() == ["a", "b"]

    def test_a_hierarchy_with_a_loop_is_refused(self) -> None:
        tree = pd.DataFrame({"id": [1, 2], "parent": [2, 1]})
        with pytest.raises(BadRequestError, match="has a loop"):
            run(pd.DataFrame({"c": [1]}), "lookup.hierarchy", tree, column="c", right_key="id",
                right_parent="parent", what="level")

    def test_currency_rates_by_currency_and_date(self) -> None:
        rates = pd.DataFrame({"cur": ["EUR", "USD", "EUR"], "from": ["2026-01-01", "2026-01-01", "2026-03-01"],
                              "rate": [2.0, 3.0, 4.0]})
        sales = pd.DataFrame({"amount": [1, 1, 1], "cur": ["eur", "USD", "EUR"],
                              "on": ["2026-02-01", "2026-05-01", "2026-03-01"]})
        out, _ = run(sales, "lookup.currency_rate", rates, column="amount", currency="cur", date="on",
                     right_currency="cur", right_date="from", right_rate="rate")
        assert out["amount_converted"].tolist() == [2.0, 3.0, 4.0]

    def test_ipv6_and_whole_number_ranges(self) -> None:
        ranges = pd.DataFrame({"start": ["2001:db8::", 167772160], "end": ["2001:db8::ffff", 184549375],
                               "country": ["ZZ", "XX"]})
        out, _ = run(pd.DataFrame({"ip": ["2001:db8::1", "10.1.2.3"]}), "lookup.country_from_ip", ranges,
                     column="ip", right_low="start", right_high="end", bring=["country"])
        assert out["country"].tolist() == ["ZZ", "XX"]

    def test_holidays_in_the_calendar_need_a_country(self) -> None:
        with pytest.raises(BadRequestError, match="which country"):
            run(pd.DataFrame({"d": ["2026-01-01"]}), "lookup.date_dimension", column="d", parts=["is holiday"])
        out, _ = run(pd.DataFrame({"d": ["2026-01-01"]}), "lookup.date_dimension", column="d",
                     parts=["is holiday", "fiscal year"], country="GB", region="ENG")
        assert out["d_is_holiday"].tolist() == [True]
        fiscal, _ = run(pd.DataFrame({"d": ["2026-01-01"]}), "date.fiscal_year", column="d", start_month=4)
        assert out["d_fiscal_year"].tolist() == fiscal["d"].tolist()


# ------------------------------------------------------- the everyday families


class TestValues:
    def test_a_token_reveals_only_under_its_key_name(self) -> None:
        from shared_python.security.reversible_tokens import reveal

        out, _ = run(pd.DataFrame({"e": ["ana@x.com", "ana@x.com"]}), "privacy.tokenise", column="e",
                     key_name="customers")
        first, second = out["e"].tolist()
        assert first == second and first.startswith("tok_")
        assert reveal(first, "customers") == "ana@x.com"
        with pytest.raises(BadRequestError, match="does not reveal"):
            reveal(first, "suppliers")
        with pytest.raises(BadRequestError, match="does not reveal"):
            reveal(first[:-2] + ("A" if first[-2] != "A" else "B") + first[-1], "customers")

    def test_a_token_needs_the_deployment_key(self, monkeypatch) -> None:
        from shared_python.errors import MisconfiguredEnvironmentError

        monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", "")
        with pytest.raises(MisconfiguredEnvironmentError, match="APP_SECRET_ENCRYPTION_KEY"):
            run(pd.DataFrame({"e": ["x"]}), "privacy.tokenise", column="e")

    def test_temperatures_convert_through_kelvin(self) -> None:
        out, _ = run(pd.DataFrame({"t": [212.0, 32.0]}), "numeric.convert_units", column="t", from_unit="F",
                     to_unit="C")
        assert [round(v, 9) for v in out["t"]] == [100.0, 0.0]

    def test_different_kinds_of_unit_do_not_convert(self) -> None:
        with pytest.raises(BadRequestError, match="a mass and m a length"):
            run(pd.DataFrame({"t": [1]}), "numeric.convert_units", column="t", from_unit="kg", to_unit="m")

    def test_languages_by_alphabet_and_by_words(self) -> None:
        frame = pd.DataFrame({"v": ["Привіт, як справи? Їжак", "Das ist nicht der Weg, den ich wollte",
                                    "Esto es una prueba de la detección"]})
        out, _ = run(frame, "text.detect_language", column="v", confidence=True)
        assert out["v_language"].tolist() == ["uk", "de", "es"]
        assert out["v_language_confidence"].between(0, 1).all()

    def test_us_address_parts(self) -> None:
        frame = pd.DataFrame({"a": ["350 Fifth Avenue, Apt 4B, New York, NY 10118"]})
        parts = {part: run(frame, "clean.address_part", column="a", part=part)[0]["a"][0]
                 for part in ("house number", "unit", "region", "postcode")}
        assert parts == {"house number": "350", "unit": "4B", "region": "NY", "postcode": "10118"}

    def test_a_monthly_calendar(self) -> None:
        out, _ = run(pd.DataFrame({"d": ["2026-01-15", "2026-03-02"]}), "date.spine", column="d", every="month")
        assert [str(v) for v in out["date"]] == ["2026-01-01", "2026-02-01", "2026-03-01"]

    def test_missing_dates_are_filled_within_each_group(self) -> None:
        frame = pd.DataFrame({"shop": ["a", "a", "b"], "d": ["2026-01-01", "2026-01-03", "2026-01-01"],
                              "sales": [1, 2, 3]})
        out, _ = run(frame, "date.fill_missing", column="d", within=["shop"], flag="added")
        assert out[["shop", "added"]].values.tolist() == [["a", False], ["a", True], ["a", False], ["b", False]]

    def test_rounding_is_half_away_from_zero_everywhere(self) -> None:
        out, _ = run(pd.DataFrame({"v": [2.5, -2.5, 2.675, 0.125]}), "numeric.round", column="v", digits=2)
        assert out["v"].tolist() == [2.5, -2.5, 2.68, 0.13]
