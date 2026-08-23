"""Where the two IR backends are most likely to disagree.

The happy-path corpus in test_ir_differential.py proves the shape of the thing
works. This one attacks the edges: nulls in every position, empty inputs,
single rows, and the specific places pandas and SQL are known to part company --
null ordering, aggregates over all-null columns, three-valued logic, and joins
that match nothing.
"""

from __future__ import annotations

import sqlite3

import pandas as pd
import pytest

from shared_python.types import FLOAT64, INT64, STRING
from service_transformations.ir.expressions import Call, Case, Column, Literal
from service_transformations.ir.nodes import (
    Aggregate,
    Distinct,
    Filter,
    Join,
    Limit,
    Node,
    Project,
    Scan,
    Sort,
    SortKey,
)
from service_transformations.ir.pandas_backend import execute
from service_transformations.ir.sql_backend import Unsupported, to_sql

# Deliberately awkward: nulls in every column, a duplicate row, a zero.
SPARSE = pd.DataFrame(
    {
        "id": [1, 2, 3, 4, 5, 6],
        "grp": ["a", "b", None, "a", "b", None],
        "num": [10.0, None, 30.0, 10.0, 0.0, None],
        "txt": ["x", None, "z", "x", "", None],
    }
)
EMPTY = SPARSE.iloc[0:0]
SINGLE = SPARSE.iloc[[0]]
ALL_NULL = pd.DataFrame({"id": [1, 2], "grp": [None, None], "num": [None, None], "txt": [None, None]})

LOOKUP = pd.DataFrame({"grp": ["a", "zzz"], "owner": ["ana", "zed"]})

SCAN = Scan("t", (("id", INT64), ("grp", STRING), ("num", FLOAT64), ("txt", STRING)))
LOOKUP_SCAN = Scan("lk", (("grp", STRING), ("owner", STRING)))


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    """Compare values, not storage details.

    SQLite has type affinity rather than types, so an integer column can come
    back as int64 from one engine and object from the other while holding the
    same values. Dtype equality would fail on a difference nobody cares about.

    Every null becomes a real ``None``. Built element-wise rather than with
    ``.where(..., None)``, which quietly reintroduces ``np.nan`` on an object
    column -- and a comparison that passes only because two null flavours are
    conflated is not checking anything. pandas currently treats them as equal
    and warns that it will stop.
    """
    out = pd.DataFrame(index=range(len(frame)))
    for column in frame.columns:
        series = frame[column].reset_index(drop=True)
        numeric = pd.api.types.is_numeric_dtype(series) or pd.api.types.is_bool_dtype(
            series
        )
        values = []
        for value in series:
            if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
                values.append(None)
            elif numeric:
                values.append(round(float(value), 9))
            else:
                values.append(str(value))
        out[str(column)] = pd.Series(values, dtype="object")
    return out


def _sorted_rows(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.reset_index(drop=True)
    return frame.sort_values(by=list(frame.columns), na_position="last").reset_index(drop=True)


CASES: list[tuple[str, Node, dict[str, pd.DataFrame], bool]] = []


def case(name: str, tree: Node, frames: dict[str, pd.DataFrame], ordered: bool = False) -> None:
    CASES.append((name, tree, frames, ordered))


BASE = {"t": SPARSE, "lk": LOOKUP}

# -- nulls in predicates ---------------------------------------------------
case("filter_null_column", Filter(SCAN, Call("gt", (Column("num"), Literal(5.0, FLOAT64)))), BASE)
case("filter_is_null", Filter(SCAN, Call("is_null", (Column("num"),))), BASE)
case("filter_is_not_null", Filter(SCAN, Call("is_not_null", (Column("grp"),))), BASE)
case(
    "filter_not_of_null",
    Filter(SCAN, Call("not", (Call("gt", (Column("num"), Literal(5.0, FLOAT64))),))),
    BASE,
)
case(
    "filter_or_with_nulls",
    Filter(
        SCAN,
        Call(
            "or",
            (
                Call("eq", (Column("grp"), Literal("a", STRING))),
                Call("is_null", (Column("num"),)),
            ),
        ),
    ),
    BASE,
)
case("filter_matches_nothing", Filter(SCAN, Call("gt", (Column("num"), Literal(9999.0, FLOAT64)))), BASE)
case("filter_matches_everything", Filter(SCAN, Call("is_not_null", (Column("id"),))), BASE)

# -- empty and tiny inputs -------------------------------------------------
case("empty_scan", SCAN, {"t": EMPTY, "lk": LOOKUP})
case(
    "empty_aggregate_grouped",
    Aggregate(SCAN, group_by=(("grp", Column("grp")),), aggregates=(("n", Call("count", (Column("id"),))),)),
    {"t": EMPTY, "lk": LOOKUP},
)
case("single_row", Filter(SCAN, Call("eq", (Column("id"), Literal(1, INT64)))), {"t": SINGLE, "lk": LOOKUP})
case(
    "empty_project",
    Project(SCAN, (("a", Column("id")), ("b", Call("upper", (Column("txt"),))))),
    {"t": EMPTY, "lk": LOOKUP},
)

# -- aggregates over nulls -------------------------------------------------
case(
    "aggregate_null_group_key",
    Aggregate(
        SCAN,
        group_by=(("grp", Column("grp")),),
        aggregates=(("total", Call("sum", (Column("num"),))), ("n", Call("count", (Column("num"),)))),
    ),
    BASE,
)
case(
    "aggregate_all_null_column",
    Aggregate(
        SCAN,
        group_by=(("grp", Column("grp")),),
        aggregates=(("total", Call("sum", (Column("num"),))), ("biggest", Call("max", (Column("num"),)))),
    ),
    {"t": ALL_NULL, "lk": LOOKUP},
)
case(
    "count_counts_non_nulls_only",
    Aggregate(SCAN, aggregates=(("n", Call("count", (Column("num"),))),)),
    BASE,
)

# -- sorting with nulls ----------------------------------------------------
case("sort_nulls_last", Sort(SCAN, keys=(SortKey(Column("num"), "asc", nulls_first=False),)), BASE, True)
case("sort_nulls_first", Sort(SCAN, keys=(SortKey(Column("num"), "asc", nulls_first=True),)), BASE, True)
case("sort_desc_nulls_last", Sort(SCAN, keys=(SortKey(Column("num"), "desc", nulls_first=False),)), BASE, True)

# -- distinct with nulls ---------------------------------------------------
case("distinct_with_nulls", Distinct(Project(SCAN, (("grp", Column("grp")),))), BASE)
case(
    "distinct_multi_column",
    Distinct(Project(SCAN, (("grp", Column("grp")), ("num", Column("num"))))),
    BASE,
)

# -- joins that do not match ----------------------------------------------
case(
    "inner_join_null_keys_do_not_match",
    Join(SCAN, LOOKUP_SCAN, on=Call("eq", (Column("grp"), Column("grp"))), how="inner"),
    BASE,
)
case(
    "left_join_null_keys_stay_null",
    Join(SCAN, LOOKUP_SCAN, on=Call("eq", (Column("grp"), Column("grp"))), how="left"),
    BASE,
)
case(
    "join_with_no_matches_at_all",
    Join(
        SCAN,
        Scan("lk", (("grp", STRING), ("owner", STRING))),
        on=Call("eq", (Column("grp"), Column("grp"))),
        how="inner",
    ),
    {"t": SPARSE, "lk": pd.DataFrame({"grp": ["nope"], "owner": ["x"]})},
)

# -- expressions over nulls ------------------------------------------------
case(
    "coalesce_fills_nulls",
    Project(SCAN, (("id", Column("id")), ("filled", Call("coalesce", (Column("num"), Literal(-1.0, FLOAT64)))))),
    BASE,
)
case(
    "arithmetic_with_null_propagates",
    Project(SCAN, (("id", Column("id")), ("shifted", Call("add", (Column("num"), Literal(1.0, FLOAT64)))))),
    BASE,
)
case(
    "case_falls_through_on_null",
    Project(
        SCAN,
        (
            ("id", Column("id")),
            (
                "band",
                Case(
                    ((Call("gt", (Column("num"), Literal(5.0, FLOAT64))), Literal("big", STRING)),),
                    default=Literal("other", STRING),
                ),
            ),
        ),
    ),
    BASE,
)
case(
    "case_with_no_default_yields_null",
    Project(
        SCAN,
        (
            ("id", Column("id")),
            (
                "maybe",
                Case(((Call("gt", (Column("num"), Literal(5.0, FLOAT64))), Literal("big", STRING)),)),
            ),
        ),
    ),
    BASE,
)
case(
    "text_functions_on_nulls",
    Project(
        SCAN,
        (
            ("id", Column("id")),
            ("up", Call("upper", (Column("txt"),))),
            ("len", Call("length", (Column("txt"),))),
        ),
    ),
    BASE,
)
case(
    "empty_string_is_not_null",
    Filter(SCAN, Call("eq", (Column("txt"), Literal("", STRING)))),
    BASE,
)

# -- limit edges -----------------------------------------------------------
case("limit_zero", Limit(Sort(SCAN, keys=(SortKey(Column("id"), "asc"),)), count=0), BASE, True)
case("limit_beyond_end", Limit(Sort(SCAN, keys=(SortKey(Column("id"), "asc"),)), count=999), BASE, True)
case(
    "offset_beyond_end",
    Limit(Sort(SCAN, keys=(SortKey(Column("id"), "asc"),)), count=5, offset=99),
    BASE,
    True,
)



# -- every remaining expression, verified against real SQL -----------------
# These exist as much for correctness as for coverage: a function implemented
# in only one backend is a function that will disagree with the other the first
# time somebody uses it.
case(
    "comparison_operators",
    Project(
        SCAN,
        (
            ("id", Column("id")),
            ("ne", Call("ne", (Column("grp"), Literal("a", STRING)))),
            ("le", Call("le", (Column("num"), Literal(10.0, FLOAT64)))),
            ("lt", Call("lt", (Column("num"), Literal(10.0, FLOAT64)))),
            ("ge", Call("ge", (Column("num"), Literal(10.0, FLOAT64)))),
        ),
    ),
    BASE,
)
case(
    "arithmetic_operators",
    Project(
        SCAN,
        (
            ("id", Column("id")),
            ("divided", Call("div", (Column("num"), Literal(4.0, FLOAT64)))),
            ("negated", Call("neg", (Column("num"),))),
            ("absolute", Call("abs", (Call("neg", (Column("num"),)),))),
        ),
    ),
    BASE,
)
case(
    "rounding_family",
    Project(
        SCAN,
        (
            ("id", Column("id")),
            ("rounded", Call("round", (Column("num"), Literal(1, INT64)))),
            ("floored", Call("floor", (Column("num"),))),
        ),
    ),
    BASE,
)
case(
    "string_family",
    Project(
        SCAN,
        (
            ("id", Column("id")),
            ("lowered", Call("lower", (Column("grp"),))),
            ("trimmed", Call("trim", (Column("txt"),))),
            ("sub", Call("substring", (Column("grp"), Literal(1, INT64), Literal(1, INT64)))),
            ("swapped", Call("replace", (Column("grp"), Literal("a", STRING), Literal("A", STRING)))),
        ),
    ),
    BASE,
)
case(
    "coalesce_three_arguments",
    Project(
        SCAN,
        (
            ("id", Column("id")),
            (
                "first_present",
                Call("coalesce", (Column("num"), Column("id"), Literal(-1.0, FLOAT64))),
            ),
        ),
    ),
    BASE,
)
case(
    "concat_three_arguments",
    Project(
        SCAN,
        (
            ("id", Column("id")),
            (
                "joined",
                Call("concat", (Column("grp"), Literal("/", STRING), Column("txt"))),
            ),
        ),
    ),
    BASE,
)
case(
    "aggregate_family",
    Aggregate(
        SCAN,
        group_by=(("grp", Column("grp")),),
        aggregates=(
            ("smallest", Call("min", (Column("num"),))),
            ("largest", Call("max", (Column("num"),))),
            ("mean", Call("avg", (Column("num"),))),
            ("distinct_txt", Call("count_distinct", (Column("txt"),))),
        ),
    ),
    BASE,
)
case(
    "nested_and_or_not",
    Filter(
        SCAN,
        Call(
            "and",
            (
                Call("not", (Call("eq", (Column("grp"), Literal("b", STRING))),)),
                Call(
                    "or",
                    (
                        Call("gt", (Column("num"), Literal(20.0, FLOAT64))),
                        Call("is_null", (Column("num"),)),
                    ),
                ),
            ),
        ),
    ),
    BASE,
)


@pytest.mark.parametrize(
    ("name", "tree", "frames", "ordered"), CASES, ids=[c[0] for c in CASES]
)
def test_backends_agree_on_edges(
    name: str, tree: Node, frames: dict[str, pd.DataFrame], ordered: bool
) -> None:
    connection = sqlite3.connect(":memory:")
    try:
        for table, frame in frames.items():
            frame.to_sql(table, connection, index=False)

        try:
            sql = to_sql(tree, "sqlite")
        except Unsupported as exc:
            pytest.skip(f"sqlite cannot express this tree: {exc}")

        from_pandas = _normalise(execute(tree, frames))
        from_sql = _normalise(pd.read_sql_query(sql, connection))

        assert list(from_pandas.columns) == list(from_sql.columns), (
            f"{name}: columns differ\n  pandas={list(from_pandas.columns)}\n"
            f"  sql   ={list(from_sql.columns)}"
        )
        assert len(from_pandas) == len(from_sql), (
            f"{name}: row count differs -- pandas {len(from_pandas)}, sql {len(from_sql)}\n"
            f"SQL: {sql}\npandas:\n{from_pandas}\nsql:\n{from_sql}"
        )

        if not ordered:
            from_pandas = _sorted_rows(from_pandas)
            from_sql = _sorted_rows(from_sql)

        pd.testing.assert_frame_equal(
            from_pandas, from_sql, check_dtype=False, obj=f"{name}\nSQL: {sql}"
        )
    finally:
        connection.close()
