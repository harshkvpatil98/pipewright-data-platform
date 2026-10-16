"""Join as SQL does: the same rows as a SQL database gives (E2, X3).

What a converted SQL model's joins become, so it is held to SQLite, a real
SQL engine, for every kind of join: an empty key matches nothing (the join
step, like pandas, matches two empty keys), and both sides' key columns stay.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from shared_python.errors import BadRequestError

from service_transformations.executor import apply_transformation_steps
from service_transformations.steps.context import StepContext

ORDERS = pd.DataFrame({"order_id": [1, 2, 3, 4, 5], "customer_id": [10, 20, None, 10, 40],
                       "amount": [5.0, 7.5, 1.0, 2.0, 9.0]})
CUSTOMERS = pd.DataFrame({"customer_id": [10, 20, None, 30], "name": ["Ann", "Bo", "Nobody", "Cy"],
                          "amount": [100, 200, 300, 400]})


def _join(how: str, frame: pd.DataFrame = ORDERS, **extra) -> pd.DataFrame:
    context = StepContext(resolve_dataset=lambda _id: CUSTOMERS.copy(), describe_dataset=lambda _id: "Customers")
    config = {"tool": "join.sql", "right_dataset_id": "00000000-0000-0000-0000-0000000000aa", "how": how,
              "on": ["customer_id"], "right_on": ["customer_id"], "bring": ["customer_id", "name", "amount"],
              "suffix": "_c", **extra}
    return apply_transformation_steps(frame, [{"step_type": "tool", "config": config}], context)[0]


def _sqlite(how: str) -> pd.DataFrame:
    connection = sqlite3.connect(":memory:")
    ORDERS.to_sql("o", connection, index=False)
    CUSTOMERS.to_sql("c", connection, index=False)
    join = {"inner": "JOIN", "left": "LEFT JOIN", "right": "RIGHT JOIN", "full": "FULL JOIN"}[how]
    return pd.read_sql(f"SELECT o.order_id, o.customer_id, o.amount, c.customer_id AS customer_id_c, c.name, "
                       f"c.amount AS amount_c FROM o {join} c ON o.customer_id = c.customer_id", connection)


def _rows(frame: pd.DataFrame) -> list[tuple]:
    def value(v):
        return None if pd.isna(v) else float(v) if isinstance(v, (int, float)) else v

    return sorted((tuple(value(v) for v in row) for row in frame.itertuples(index=False)), key=repr)


@pytest.mark.parametrize("how", ["inner", "left", "right", "full"])
def test_every_join_gives_what_sqlite_gives(how: str) -> None:
    if how in ("right", "full") and sqlite3.sqlite_version_info < (3, 39):
        pytest.skip("SQLite before 3.39 has no RIGHT or FULL JOIN to compare with")
    ours = _join(how)
    assert list(ours.columns) == ["order_id", "customer_id", "amount", "customer_id_c", "name", "amount_c"]
    assert _rows(ours) == _rows(_sqlite(how))


def test_an_empty_key_matches_nothing_where_the_join_step_matches_it() -> None:
    ours = _join("left")
    assert ours.loc[ours["order_id"] == 3, "name"].isna().all()
    context = StepContext(resolve_dataset=lambda _id: CUSTOMERS.copy(), describe_dataset=lambda _id: "Customers")
    step = apply_transformation_steps(ORDERS, [{"step_type": "join_datasets", "config": {
        "right_dataset_id": "00000000-0000-0000-0000-0000000000aa", "left_on": ["customer_id"],
        "right_on": ["customer_id"], "how": "left"}}], context)[0]
    assert step.loc[step["order_id"] == 3, "name"].tolist() == ["Nobody"]


def test_a_name_taken_twice_is_refused() -> None:
    with pytest.raises(BadRequestError, match="two columns"):
        _join("inner", frame=ORDERS.assign(amount_c=1), bring=["amount"])


def test_empty_keys_can_match_each_other_as_alteryx_s_join_does() -> None:
    ours = _join("inner", empty_keys="match each other")
    assert ours.loc[ours["order_id"] == 3, "name"].tolist() == ["Nobody"]
    assert len(ours) == len(_join("inner")) + 1


@pytest.mark.parametrize(("empty_keys", "kept"), [("never match", [3, 5]), ("match each other", [5])])
def test_anti_keeps_the_rows_with_no_match_and_semi_the_rest(empty_keys: str, kept: list[int]) -> None:
    anti = _join("anti", empty_keys=empty_keys, bring=[])
    assert sorted(anti["order_id"]) == kept and list(anti.columns) == list(ORDERS.columns)
    semi = _join("semi", empty_keys=empty_keys, bring=[])
    assert sorted(semi["order_id"]) == sorted(set(ORDERS["order_id"]) - set(kept))
