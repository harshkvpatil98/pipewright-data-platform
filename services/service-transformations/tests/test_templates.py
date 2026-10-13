"""Recipe templates produce steps the engine runs, on the columns a person has."""

from __future__ import annotations

import pandas as pd
import pytest

from service_transformations.executor import apply_transformation_steps
from service_transformations.templates import (
    TEMPLATES,
    build_steps,
    get_template,
    suggest_mapping,
)
from shared_python.errors import BadRequestError, NotFoundError

CONTACTS = pd.DataFrame(
    {
        "customer_id": ["C1", "C2", "C3", "C4", "C5"],
        "name": ["asha rao", "  Ben Ode", "chen li", "Dana Smith", "Asha Rao"],
        "email": ["asha@example.com", "ben@example.com ", None, "DANA@EXAMPLE.COM", "ASHA@example.com"],
        "city": ["Pune", "Leeds ", "Austin", "Lyon", "Pune"],
    }
)
CONTACT_TYPES = {"customer_id": "string", "name": "string", "email": "string", "city": "string"}

ORDERS = pd.DataFrame(
    {
        "order_id": [1, 2, 3, 4, 5],
        "order_date": ["2026-07-01", "2026-07-15", "2026-08-02", "2026-08-20", "2026-09-01"],
        "region": ["North", "South", "North", "North", "South"],
        "amount": [100.0, 50.0, 25.5, None, 10.0],
    }
)
ORDER_TYPES = {"order_id": "int", "order_date": "string", "region": "string", "amount": "float"}


def _run(template_id: str, frame: pd.DataFrame, types: dict[str, str], mapping=None) -> pd.DataFrame:
    template = get_template(template_id)
    suggested, missing = suggest_mapping(template, list(frame.columns), types)
    assert not missing, f"{template_id} could not place {missing}"
    steps = build_steps(template_id, mapping or suggested, list(frame.columns), types)
    result, _ = apply_transformation_steps(frame, steps)
    return result


def test_clean_contacts_tidies_and_keeps_one_row_per_email() -> None:
    result = _run("clean_contacts", CONTACTS, CONTACT_TYPES)
    assert list(result["email"]) == ["asha@example.com", "ben@example.com", "dana@example.com"]
    assert list(result["name"]) == ["Asha Rao", "Ben Ode", "Dana Smith"]
    assert list(result["city"]) == ["Pune", "Leeds", "Lyon"]


def test_clean_contacts_finds_the_columns_by_name() -> None:
    mapping, missing = suggest_mapping(get_template("clean_contacts"), list(CONTACTS.columns), CONTACT_TYPES)
    assert mapping == {"email": "email", "name": "name"}
    assert missing == []


def test_monthly_totals_adds_up_each_month_and_region() -> None:
    result = _run("monthly_totals", ORDERS, ORDER_TYPES)
    rows = {(row.month, row.region): row.total_amount for row in result.itertuples()}
    assert rows[("2026-07", "North")] == 100.0
    assert rows[("2026-07", "South")] == 50.0
    assert rows[("2026-08", "North")] == 25.5  # the empty amount adds nothing
    assert list(result["month"]) == sorted(result["month"])


def test_monthly_totals_without_a_split() -> None:
    template = get_template("monthly_totals")
    mapping, _ = suggest_mapping(template, list(ORDERS.columns), ORDER_TYPES)
    mapping["group"] = None
    steps = build_steps("monthly_totals", mapping, list(ORDERS.columns), ORDER_TYPES)
    result, _ = apply_transformation_steps(ORDERS, steps)
    assert list(result["month"]) == ["2026-07", "2026-08", "2026-09"]
    assert list(result["rows"]) == [2, 2, 1]


def test_tidy_and_dedupe_compares_whole_rows_by_default() -> None:
    frame = pd.DataFrame({"a": ["x ", "x", "y"], "b": [1, 1, 2]})
    result = _run("tidy_and_dedupe", frame, {"a": "string", "b": "int"}, mapping={"keys": [], "text": []})
    assert result.to_dict("records") == [{"a": "x", "b": 1}, {"a": "y", "b": 2}]


def test_a_template_refuses_a_column_that_is_not_there() -> None:
    with pytest.raises(BadRequestError, match="not a column"):
        build_steps("clean_contacts", {"email": "mail"}, list(CONTACTS.columns), CONTACT_TYPES)


def test_a_missing_required_role_is_reported_not_guessed() -> None:
    frame_columns = ["region", "notes"]
    mapping, missing = suggest_mapping(get_template("monthly_totals"), frame_columns, {"region": "string", "notes": "string"})
    assert set(missing) == {"date", "amount"}
    with pytest.raises(BadRequestError):
        build_steps("monthly_totals", mapping, frame_columns, {})


def test_an_unknown_template_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        get_template("nope")


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda template: template.id)
def test_every_template_says_what_it_does(template) -> None:
    assert template.name and template.description
    assert all(role.label and role.description for role in template.roles)
