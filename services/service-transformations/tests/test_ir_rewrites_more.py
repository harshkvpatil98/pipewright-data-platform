"""Phase 22's rewrites must not change the answer either (D2, O3).

Pushdown through joins, aggregates, unions and distincts; a predicate copied
across a join's keys; a limit copied into a union; redundant sorts dropped;
constants folded; columns pruned. Each named case checks that its rule fires
(and that the ones that must not, do not), and every tree -- the named ones
and a few hundred random ones -- is run as written and as rewritten, by
pandas and by SQLite, and all four must agree value for value.
"""

from __future__ import annotations

import random
import sqlite3

import pandas as pd
import pytest

from shared_python.types import BOOLEAN, FLOAT64, INT64, STRING
from service_transformations.ir.expressions import Call, Column, Literal
from service_transformations.ir.nodes import (
    Aggregate,
    Distinct,
    Filter,
    Join,
    Limit,
    Node,
    Project,
    Scan,
    SetOp,
    Sort,
    SortKey,
)
from service_transformations.ir.pandas_backend import execute
from service_transformations.ir.rewrites import fold, rewrite
from service_transformations.ir.sql_backend import Unsupported, to_sql

ORDERS = pd.DataFrame({
    "id": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "customer_id": [1, 2, 1, 3, 2, 4, 1, 3, 5, 2],
    "region": ["eu", "us", "eu", "apac", "us", "eu", None, "apac", "us", "eu"],
    "amount": [10.0, 250.0, 300.0, 75.5, 50.0, 120.0, 40.0, None, 5.0, 60.0],
})
CUSTOMERS = pd.DataFrame({
    "id": [1, 2, 3, 4, 6],
    "name": ["ann", "bo", "cy", "di", "ed"],
    "region": ["eu", "us", "apac", None, "eu"],
    "tier": [1, 2, 2, 3, 1],
})
OTHER_ORDERS = ORDERS.assign(id=ORDERS["id"] + 100, amount=ORDERS["amount"] * 2)
SCAN_ORDERS = Scan("orders", (("id", INT64), ("customer_id", INT64), ("region", STRING), ("amount", FLOAT64)))
SCAN_CUSTOMERS = Scan("customers", (("id", INT64), ("name", STRING), ("region", STRING), ("tier", INT64)))
SCAN_OTHER = Scan("other_orders", SCAN_ORDERS.columns)
FRAMES = {"orders": ORDERS, "customers": CUSTOMERS, "other_orders": OTHER_ORDERS}
PRUNING = {"read only the columns used", "drop columns nobody reads"}


@pytest.fixture(scope="module")
def db():
    connection = sqlite3.connect(":memory:")
    for name, frame in FRAMES.items():
        frame.to_sql(name, connection, index=False)
    yield connection
    connection.close()


def _lit(value):
    return Literal(value, FLOAT64 if isinstance(value, float) else INT64 if isinstance(value, int) else STRING)


def gt(column, value):
    return Call("gt", (Column(column), _lit(value)))


def eq(column, value):
    return Call("eq", (Column(column), _lit(value)))


def join(how="inner"):
    return Join(SCAN_ORDERS, SCAN_CUSTOMERS, Call("eq", (Column("customer_id"), Column("id"))), how)


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=range(len(frame)))
    for column in frame.columns:
        values = []
        for value in frame[column].reset_index(drop=True):
            if value is None or pd.isna(value):
                values.append(None)
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                values.append(round(float(value), 6))
            else:
                values.append(str(value))
        out[str(column)] = pd.Series(values, dtype="object")
    return out


def _rows(frame: pd.DataFrame, ordered: bool) -> list[tuple]:
    rows = [tuple(r) for r in _normalise(frame).itertuples(index=False, name=None)]
    return rows if ordered else sorted(rows, key=lambda r: tuple((v is None, str(v)) for v in r))


def _agree(tree: Node, rewritten: Node, db, *, ordered: bool) -> None:
    results = {"as written / pandas": execute(tree, FRAMES), "rewritten / pandas": execute(rewritten, FRAMES)}
    for label, candidate in (("as written", tree), ("rewritten", rewritten)):
        try:
            results[f"{label} / sqlite"] = pd.read_sql_query(to_sql(candidate, "sqlite"), db)
        except Unsupported:
            continue
    reference = results["as written / pandas"]
    columns = list(tree.schema())
    for label, frame in results.items():
        assert list(frame.columns)[: len(columns)] == columns or list(frame.columns) == columns, label
        assert _rows(frame[columns], ordered) == _rows(reference[columns], ordered), label


CASES: list[tuple[str, Node, bool, list[str]]] = [
    ("a filter on the left side goes below an inner join, and across its key",
     Filter(join(), gt("customer_id", 1)), False,
     ["filter below join", "filter copied across a join"]),
    ("a filter on the right side goes below an inner join",
     Filter(join(), eq("name", "bo")), False, ["filter below join"]),
    ("a filter reading both sides stays above",
     Filter(join(), Call("eq", (Column("region"), Column("region_right")))), False, []),
    ("a filter on the padded side of a left join stays above",
     Filter(join("left"), eq("name", "bo")), False, []),
    ("a filter on the kept side of a left join goes below, and across",
     Filter(join("left"), gt("customer_id", 2)), False,
     ["filter below join", "filter copied across a join"]),
    ("a filter on an anti join's left goes below, and across",
     Filter(Join(SCAN_ORDERS, SCAN_CUSTOMERS, Call("eq", (Column("customer_id"), Column("id"))), "anti"), gt("customer_id", 2)), False,
     ["filter below join", "filter copied across a join"]),
    ("a filter on the right of a full join stays above",
     Filter(join("full"), eq("name", "bo")), False, []),
    ("a filter on grouping keys goes below an aggregate",
     Filter(Aggregate(SCAN_ORDERS, (("region", Column("region")),), (("total", Call("sum", (Column("amount"),))),)),
            eq("region", "eu")), False, ["filter below aggregate"]),
    ("a filter on a measure stays above an aggregate",
     Filter(Aggregate(SCAN_ORDERS, (("region", Column("region")),), (("total", Call("sum", (Column("amount"),))),)),
            gt("total", 100.0)), False, []),
    ("a filter goes into both sides of a union",
     Filter(SetOp(SCAN_ORDERS, SCAN_OTHER, "union_all"), gt("amount", 50.0)), False, ["filter into both sides of a union"]),
    ("a filter on identity columns goes below a distinct",
     Filter(Distinct(Sort(SCAN_ORDERS, (SortKey(Column("id")),)), ("region",), "first"), eq("region", "eu")), True,
     ["filter below distinct", "filter below sort"]),
    ("a filter on other columns stays above a distinct",
     Filter(Distinct(Sort(SCAN_ORDERS, (SortKey(Column("id")),)), ("region",), "first"), gt("amount", 50.0)), True, []),
    ("a limit is copied into both sides of a union",
     Limit(SetOp(SCAN_ORDERS, SCAN_OTHER, "union_all"), 3, 1), True, ["limit into both sides of a union"]),
    ("a sort under a sort that orders by more is dropped",
     Sort(Sort(SCAN_ORDERS, (SortKey(Column("region")),)), (SortKey(Column("region")), SortKey(Column("id")))), True,
     ["drop a redundant sort"]),
    ("a sort under a sort that orders differently stays",
     Sort(Sort(SCAN_ORDERS, (SortKey(Column("id")),)), (SortKey(Column("region")),)), True, []),
    ("a sort under an aggregate is dropped",
     Aggregate(Sort(SCAN_ORDERS, (SortKey(Column("amount"), "desc"),)), (("region", Column("region")),),
               (("n", Call("count", (Column("id"),))),)), False, ["drop a redundant sort"]),
    ("a sort under an aggregate that takes the first value stays",
     Aggregate(Sort(SCAN_ORDERS, (SortKey(Column("amount"), "desc"),)), (("region", Column("region")),),
               (("top", Call("first", (Column("id"),))),)), False, []),
    ("constants are folded and a filter that keeps every row is dropped",
     Filter(SCAN_ORDERS, Call("or", (Call("gt", (_lit(3), _lit(2))), gt("amount", 10.0)))), True,
     ["drop a filter that keeps every row"]),
    ("whole-number arithmetic is folded",
     Filter(SCAN_ORDERS, Call("gt", (Column("id"), Call("mul", (_lit(2), _lit(3)))))), True, ["fold constants"]),
    ("decimals are not folded",
     Filter(SCAN_ORDERS, Call("gt", (Column("amount"), Call("add", (_lit(0.1), _lit(0.2)))))), True, []),
]


@pytest.mark.parametrize(("name", "tree", "ordered", "expected"), CASES, ids=[c[0] for c in CASES])
def test_each_rewrite_fires_where_it_should_and_keeps_the_answer(name, tree, ordered, expected, db):
    rewritten, applied = rewrite(tree)
    assert [a.rule for a in applied if a.rule not in PRUNING] == expected, [str(a) for a in applied]
    _agree(tree, rewritten, db, ordered=ordered)


def test_a_scan_reads_only_the_columns_used():
    tree = Project(Filter(join(), gt("amount", 50.0)), (("name", Column("name")), ("amount", Column("amount"))))
    rewritten, applied = rewrite(tree)
    sql = to_sql(rewritten, "postgres")
    # `id` stays on the left too: both sides have one, and dropping the left's
    # would rename the right's from "id_right" to "id" under what reads it.
    assert 'SELECT "id", "customer_id", "amount" FROM "orders"' in sql
    assert 'SELECT "id", "name" FROM "customers"' in sql
    assert '"region"' not in sql and '"tier"' not in sql
    assert sum(1 for a in applied if a.rule == "read only the columns used") == 2


def test_the_baseline_query_selects_two_columns_not_forty():
    """The D2 baseline: a recipe keeping 2 of 40 columns pushed all 40."""
    from service_transformations.ir.from_steps import compile_pipeline
    from service_transformations.ir.planner import plan

    columns = tuple((name, STRING) for name in ["order_id", "status", "amount", *[f"extra_{i}" for i in range(37)]])
    tree = compile_pipeline(Scan("orders", columns), [
        {"type": "filter_rows", "config": {"conditions": [{"column": "status", "operator": "equals", "value": "paid"}]}},
        {"type": "select_columns", "config": {"columns": ["order_id", "amount"]}},
    ])
    sql = plan(tree, "postgresql").sql
    assert 'SELECT "order_id", "status", "amount" FROM "orders"' in sql
    assert "extra_" not in sql


def test_folding_follows_three_valued_logic():
    x = gt("amount", 1.0)
    true, false = Literal(True, BOOLEAN), Literal(False, BOOLEAN)
    assert fold(Call("and", (x, false))) == false  # false even when x is null
    assert fold(Call("and", (true, x))) == x
    assert fold(Call("or", (x, true))) == true
    assert fold(Call("or", (false, x))) == x
    assert fold(Call("not", (Call("not", (x,)),))) == x
    assert fold(Call("eq", (_lit(2), _lit(2.0)))) == Call("eq", (_lit(2), _lit(2.0)))  # kinds differ: left alone
    assert fold(Call("add", (_lit(2**62), _lit(2**62)))) == Call("add", (_lit(2**62), _lit(2**62)))  # past 64 bits


def test_rewriting_twice_changes_nothing_more():
    for _, tree, _, _ in CASES:
        once, _ = rewrite(tree)
        twice, again = rewrite(once)
        assert again == [] and twice == once


# ------------------------------------------------------------ random trees


def _random_predicate(rng: random.Random, schema: dict) -> Call:
    numeric = [n for n, t in schema.items() if t in (INT64, FLOAT64)]
    text = [n for n, t in schema.items() if t == STRING]
    parts = []
    for _ in range(rng.randint(1, 3)):
        if numeric and (not text or rng.random() < 0.6):
            column = rng.choice(numeric)
            value = rng.choice([1, 2, 3, 5]) if schema[column] == INT64 else rng.choice([10.0, 50.0, 100.0])
            parts.append(Call(rng.choice(["gt", "le", "eq", "ne"]), (Column(column), _lit(value))))
        else:
            parts.append(Call("eq", (Column(rng.choice(text)), _lit(rng.choice(["eu", "us", "bo", "ann"])))))
    out = parts[0]
    for part in parts[1:]:
        out = Call(rng.choice(["and", "and", "or"]), (out, part))
    return out


def _random_tree(rng: random.Random, depth: int) -> tuple[Node, bool]:
    """A tree over the two tables, and whether its row order is defined."""
    if depth == 0:
        return rng.choice([SCAN_ORDERS, SCAN_CUSTOMERS, SCAN_OTHER]), False
    child, ordered = _random_tree(rng, depth - 1)
    schema = child.schema()
    choice = rng.choice(["filter", "filter", "sort", "limit", "project", "join", "aggregate", "union", "distinct"])
    if choice == "filter":
        return Filter(child, _random_predicate(rng, schema)), ordered
    if choice == "sort":
        names = list(schema)
        keys = tuple(SortKey(Column(n), rng.choice(["asc", "desc"])) for n in rng.sample(names, rng.randint(1, min(2, len(names)))))
        # Every column as a final key, so ties cannot make two right answers differ.
        keys += tuple(SortKey(Column(n)) for n in names if n not in {k.expr.name for k in keys})
        return Sort(child, keys), True
    if choice == "limit" and ordered:
        return Limit(child, rng.randint(1, 4), rng.randint(0, 2)), True
    if choice == "project":
        kept = rng.sample(list(schema), rng.randint(1, len(schema)))
        return Project(child, tuple((n, Column(n)) for n in kept)), ordered
    if choice == "join" and set(schema) == set(SCAN_ORDERS.schema()):
        filtered = Filter(SCAN_CUSTOMERS, _random_predicate(rng, SCAN_CUSTOMERS.schema())) if rng.random() < 0.5 else SCAN_CUSTOMERS
        return Join(child, filtered, Call("eq", (Column("customer_id"), Column("id"))),
                    rng.choice(["inner", "left", "semi", "anti"])), False
    if choice == "aggregate" and "region" in schema and "amount" in schema:
        # SQL does not order a GROUP BY's rows (pandas does), so its answer is a set.
        return Aggregate(child, (("region", Column("region")),),
                         (("total", Call("sum", (Column("amount"),))), ("n", Call("count", (Column("amount"),))))), False
    if choice == "union" and list(schema.items()) == list(SCAN_ORDERS.schema().items()):
        return SetOp(child, Filter(SCAN_OTHER, _random_predicate(rng, SCAN_OTHER.schema())), "union_all"), False
    if choice == "distinct" and "region" in schema:
        return Distinct(child, ("region",), "first"), False
    return Filter(child, _random_predicate(rng, schema)), ordered


@pytest.mark.parametrize("seed", range(300))
def test_random_trees_keep_their_answer(seed, db):
    rng = random.Random(seed)
    tree, ordered = _random_tree(rng, rng.randint(1, 4))
    rewritten, _ = rewrite(tree)
    # A distinct keeping the "first" of each group is only defined over a defined order.
    if any(isinstance(n, Distinct) for n in tree.walk()) and not ordered:
        _agree_as_sets(tree, rewritten)
        return
    _agree(tree, rewritten, db, ordered=ordered)


def _agree_as_sets(tree: Node, rewritten: Node) -> None:
    a, b = execute(tree, FRAMES), execute(rewritten, FRAMES)
    columns = list(tree.schema())
    assert len(a) == len(b)
    assert _rows(a[columns], False) == _rows(b[columns], False)


def test_pruning_keeps_a_name_both_sides_share_while_either_needs_it():
    """Seed 533 of the random trees: the left dropped `id`, the right's `id` lost
    its suffix, and the projection above asked for an `id_right` that was gone."""
    tree = Project(join(), (("amount", Column("amount")), ("id_right", Column("id_right"))))
    rewritten, _ = rewrite(tree)
    assert "id_right" in rewritten.input.schema()


def test_a_limit_over_a_sort_is_one_select():
    """Seed 424: SQLite dropped a subquery's ORDER BY under an aggregate, so the
    limit kept the wrong rows. The sort and its limit are now one SELECT."""
    sql = to_sql(Limit(Sort(SCAN_ORDERS, (SortKey(Column("amount"), "desc"),)), 2), "sqlite")
    assert sql.endswith('ORDER BY "amount" DESC NULLS LAST LIMIT 2')
    assert to_sql(Limit(SCAN_ORDERS, None, 3), "mysql").endswith("LIMIT 18446744073709551615 OFFSET 3")


def test_a_part_named_twice_is_computed_once(monkeypatch):
    """IF(amount * 2 > 100, amount * 2, 0): the product is worked out once per node."""
    from service_transformations.ir import pandas_backend

    calls = {"mul": 0}
    original = pandas_backend._ARITHMETIC["mul"]

    def counting(a, b):
        calls["mul"] += 1
        return original(a, b)

    monkeypatch.setitem(pandas_backend._ARITHMETIC, "mul", counting)
    doubled = Call("mul", (Column("amount"), _lit(2.0)))
    tree = Project(SCAN_ORDERS, (
        ("big", Call("gt", (doubled, _lit(100.0)))),
        ("doubled", doubled),
        ("again", Call("add", (doubled, _lit(1.0)))),
    ))
    out = execute(tree, FRAMES)
    assert calls["mul"] == 1
    assert out["again"].tolist()[:2] == [21.0, 501.0]
