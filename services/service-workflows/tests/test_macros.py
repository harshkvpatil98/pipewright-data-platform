from __future__ import annotations

from datetime import UTC, datetime

import pytest

from service_workflows.macros import (
    MacroContext,
    contains_macro,
    describe,
    render,
    resolve_config,
    resolve_token,
)
from shared_python.errors import BadRequestError

LOGICAL = datetime(2026, 3, 3, 14, 30, tzinfo=UTC)
EXECUTED = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)


@pytest.fixture()
def context() -> MacroContext:
    return MacroContext(
        logical_date=LOGICAL,
        run_started_at=EXECUTED,
        workflow_name="Nightly invoices",
        parameters={"region": "eu", "batch": 7},
    )


# ------------------------------------------------------------- simple tokens


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("ds", "2026-03-03"),
        ("run_date", "2026-03-03"),
        ("yesterday", "2026-03-02"),
        ("tomorrow", "2026-03-04"),
        ("ds_nodash", "20260303"),
        ("year", "2026"),
        ("month", "03"),
        ("day", "03"),
        ("hour", "14"),
        ("month_start", "2026-03-01"),
        ("workflow_name", "Nightly invoices"),
    ],
)
def test_simple_tokens_resolve(context: MacroContext, token: str, expected: str) -> None:
    assert resolve_token(token, context) == expected


def test_whitespace_inside_braces_is_tolerated(context: MacroContext) -> None:
    assert render("{{ds}} {{  ds  }}", context) == "2026-03-03 2026-03-03"


def test_logical_date_is_not_the_execution_time(context: MacroContext) -> None:
    """A backfill for March resolves to March even though it runs in August."""
    assert render("{{ ds }}", context) == "2026-03-03"
    assert render("{{ executed_at }}", context).startswith("2026-08-20")


# ------------------------------------------------------------------ offsets


def test_ds_sub_goes_back(context: MacroContext) -> None:
    assert resolve_token("ds_sub(7)", context) == "2026-02-24"


def test_ds_add_goes_forward(context: MacroContext) -> None:
    assert resolve_token("ds_add(2)", context) == "2026-03-05"


def test_offset_crosses_a_month_boundary(context: MacroContext) -> None:
    assert resolve_token("ds_sub(3)", context) == "2026-02-28"


def test_offset_tolerates_spacing(context: MacroContext) -> None:
    assert resolve_token("ds_add( 1 )", context) == "2026-03-04"


def test_negative_argument_reverses_direction(context: MacroContext) -> None:
    assert resolve_token("ds_add(-1)", context) == "2026-03-02"


# ---------------------------------------------------------------- parameters


def test_parameters_resolve(context: MacroContext) -> None:
    assert render("region={{ params.region }} batch={{ params.batch }}", context) == "region=eu batch=7"


def test_missing_parameter_names_what_is_available(context: MacroContext) -> None:
    with pytest.raises(BadRequestError, match="batch, region"):
        resolve_token("params.missing", context)


# --------------------------------------------------------------- unknown macros


def test_unknown_macro_is_rejected_rather_than_passed_through(context: MacroContext) -> None:
    """A typo in a table name must not silently create the wrong table."""
    with pytest.raises(BadRequestError, match="Unknown macro"):
        render("orders_{{ dss }}", context)


def test_rejection_lists_the_available_macros(context: MacroContext) -> None:
    with pytest.raises(BadRequestError, match="ds_add"):
        resolve_token("nope", context)


# ------------------------------------------------------------ config rendering


def test_strings_nested_in_config_are_resolved(context: MacroContext) -> None:
    config = {
        "table_name": "orders_{{ ds_nodash }}",
        "message": "Loaded {{ yesterday }}",
        "nested": {"path": "s3://bucket/{{ year }}/{{ month }}"},
        "list": ["{{ ds }}", "static"],
    }
    resolved = resolve_config(config, context)

    assert resolved["table_name"] == "orders_20260303"
    assert resolved["message"] == "Loaded 2026-03-02"
    assert resolved["nested"]["path"] == "s3://bucket/2026/03"
    assert resolved["list"] == ["2026-03-03", "static"]


def test_non_string_values_keep_their_type(context: MacroContext) -> None:
    """Rendering must not turn a number or boolean into a string."""
    config = {"max_rows": 500, "quarantine": True, "cursor": None}
    resolved = resolve_config(config, context)

    assert resolved["max_rows"] == 500
    assert resolved["quarantine"] is True
    assert resolved["cursor"] is None


def test_config_without_macros_is_unchanged(context: MacroContext) -> None:
    config = {"table_name": "orders", "write_mode": "replace"}
    assert resolve_config(config, context) == config


# ------------------------------------------------------------------ detection


def test_contains_macro_finds_nested_references() -> None:
    assert contains_macro({"a": {"b": ["{{ ds }}"]}}) is True
    assert contains_macro({"a": {"b": ["plain"]}}) is False
    assert contains_macro(42) is False


# -------------------------------------------------------------------- context


def test_manual_run_without_a_slot_uses_now() -> None:
    now = datetime(2026, 5, 5, 8, 0, tzinfo=UTC)
    context = MacroContext.for_run(logical_date=None, now=now)
    assert render("{{ ds }}", context) == "2026-05-05"


def test_naive_logical_date_is_treated_as_utc() -> None:
    context = MacroContext.for_run(logical_date=datetime(2026, 1, 2, 3, 0))
    assert render("{{ ds }}", context) == "2026-01-02"


def test_describe_lists_resolved_values(context: MacroContext) -> None:
    resolved = describe(context)
    assert resolved["ds"] == "2026-03-03"
    assert resolved["yesterday"] == "2026-03-02"
