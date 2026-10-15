"""Window and analytic tools: values that depend on the other rows of a group.

A running total, a rank, the value before this one, a moving average. Each is
a `Window` node, so it has a type, lineage and an estimate like any tool, and
the ones whose answer cannot depend on how tied rows arrive (ranks, totals
over a whole group, running totals that take ties together) push down to a
database. The rest run here; `ir/window_functions.py` says why.

Every tool here takes the same two settings for "which rows": **within**, the
columns that divide the rows into groups (none means one group of every row),
and **order by**, the columns that put each group in order (none means the
order the rows are in). The new column lands next to the one it was made from.
"""

from __future__ import annotations

from typing import Any, Callable

from shared_python.errors import BadRequestError
from shared_python.types import FLOAT64, INT64

from service_transformations.ir.expressions import Call, Column, Expr, Literal
from service_transformations.ir.nodes import Filter, Node, Project, SortKey, Window, WindowCall, WindowFrame
from service_transformations.tools import register
from service_transformations.tools.builders import require_column, unique_name
from service_transformations.tools.spec import Accepts, Example, Param, ParamKind, ToolSpec

CATEGORY = "Window & analytic"

WITHIN = Param("within", "Within each", ParamKind.COLUMNS, required=False, default=[],
               help="Start again for each combination of these columns. Leave empty for one group of every row.")
ORDER_BY = Param("order_by", "In the order of", ParamKind.COLUMNS, required=False, default=[],
                 help="Put each group in this order first. Leave empty to keep the order the rows are in.")
DESCENDING = Param("descending", "Largest first", ParamKind.BOOLEAN, required=False, default=False)
TIES = Param("ties", "Rows that tie in the order", ParamKind.SELECT, required=False, default="each in turn",
             options=("each in turn", "together"),
             help="Each in turn counts tied rows one after another, as a spreadsheet does. Together gives "
                  "tied rows the same answer, which a database can work out too.")
ROWS = Param("rows", "Rows in the window", ParamKind.INTEGER, default=3, minimum=1, maximum=10_000,
             help="How many rows, counting this one, the value is worked out over.")

_SALES = (
    {"region": "north", "day": 1, "sales": 10.0},
    {"region": "north", "day": 2, "sales": 20.0},
    {"region": "south", "day": 1, "sales": 5.0},
    {"region": "north", "day": 3, "sales": 30.0},
    {"region": "south", "day": 2, "sales": 15.0},
)


def _columns(node: Node, names: list[str] | None, label: str) -> tuple[str, ...]:
    available = node.schema()
    missing = [name for name in names or [] if name not in available]
    if missing:
        raise BadRequestError(
            f"{label}: {', '.join(repr(m) for m in missing)} {'is' if len(missing) == 1 else 'are'} not in this "
            f"dataset. Available: {', '.join(available) or 'none'}."
        )
    return tuple(names or [])


def _order(node: Node, params: dict[str, Any], *, fallback: str | None = None) -> tuple[SortKey, ...]:
    columns = _columns(node, params.get("order_by"), "In the order of") or ((fallback,) if fallback else ())
    direction = "desc" if params.get("descending") else "asc"
    return tuple(SortKey(Column(name), direction, False) for name in columns)


def _output(node: Node, params: dict[str, Any], preferred: str) -> str:
    into = (params.get("into") or "").strip()
    if into:
        if into in node.schema():
            raise BadRequestError(f"Column {into!r} already exists. Choose another name for the new column.")
        return into
    return unique_name(node, preferred)


def _beside(node: Node, window: Node, made: dict[str, Expr], after: str | None) -> Node:
    """Every original column, with the new ones right after `after` (or at the end)."""
    projections: list[tuple[str, Expr]] = []
    for name in node.schema():
        projections.append((name, Column(name)))
        if name == after:
            projections.extend(made.items())
    if after not in node.schema():
        projections.extend(made.items())
    return Project(window, tuple(projections))


def _temp(node: Node, index: int = 0) -> str:
    return unique_name(node, f"__window_{index}")


def _window(node: Node, params: dict[str, Any], calls: list[tuple[str, WindowCall]], *,
            order: tuple[SortKey, ...] | None = None) -> Window:
    return Window(node, _columns(node, params.get("within"), "Within each"),
                  _order(node, params) if order is None else order, tuple(calls))


def _frame_for(params: dict[str, Any]) -> WindowFrame:
    return WindowFrame("peers") if params.get("ties") == "together" else WindowFrame("rows")


def _value_tool(function: str, suffix: str, *, frame: Callable[[dict], WindowFrame] | None = None,
                extra: Callable[[dict], tuple[Expr, ...]] | None = None, rank_by_column: bool = False,
                ):
    """A tool that gives each row one window value over its column."""

    def build(node: Node, params: dict[str, Any]) -> Node:
        column = require_column(node, params.get("column"))
        name = _output(node, params, f"{column}_{suffix}")
        temp = _temp(node)
        args: tuple[Expr, ...] = () if rank_by_column else (Column(column),)
        if extra:
            args += extra(params)
        order = _order(node, params, fallback=column) if rank_by_column else None
        call = WindowCall(function, args, frame(params) if frame else WindowFrame())
        window = _window(node, params, [(temp, call)], order=order)
        return _beside(node, window, {name: Column(temp)}, column)

    return build


def _declare(name: str, title: str, summary: str, build, example: Example, *, params: tuple[Param, ...] = (),
             synonyms: tuple[str, ...] = (), accepts: Accepts = Accepts.ANY, column_scoped: bool = True,
             null_answer: bool = False, local_only: bool = False, category: str = CATEGORY) -> ToolSpec:
    return register(ToolSpec(
        name=name, title=title, category=category, summary=summary, build=build, example=example,
        params=params, synonyms=synonyms, accepts=accepts, column_scoped=column_scoped,
        local_only=local_only, null_answer=null_answer, warns_lost=False,
    ))


def _example(expect: tuple, *, column: str = "sales", output: str | None = None, **params: Any) -> Example:
    return Example(rows=_SALES, params=params, expect=expect, column=column, output=output)


# ------------------------------------------------------------------ ranking


def _row_number(node: Node, params: dict[str, Any]) -> Node:
    name = _output(node, params, "row_number")
    temp = _temp(node)
    window = _window(node, params, [(temp, WindowCall("row_number"))])
    return _beside(node, window, {name: Column(temp)}, None)


_declare("window.row_number", "Row number", "Number the rows 1, 2, 3 within each group, in order.",
         _row_number, Example(rows=_SALES, params={"within": ["region"], "order_by": ["day"]},
                              expect=(1, 2, 1, 3, 2), output="row_number"),
         params=(WITHIN, ORDER_BY, DESCENDING), synonyms=("row id", "sequence", "index", "position", "number rows"),
         column_scoped=False, null_answer=True)

_RANK_PARAMS = (WITHIN, DESCENDING)
_declare("window.rank", "Rank", "Rank rows by this column, with ties sharing a rank and the next rank skipped "
         "(1, 2, 2, 4).", _value_tool("rank", "rank", rank_by_column=True),
         _example((3, 2, 2, 1, 1), within=["region"], descending=True, output="sales_rank"),
         params=_RANK_PARAMS, synonyms=("position", "standing", "order", "league table", "top"),
         accepts=Accepts.ANY, null_answer=True)
_declare("window.dense_rank", "Dense rank", "Rank rows by this column with no gaps after ties (1, 2, 2, 3).",
         _value_tool("dense_rank", "dense_rank", rank_by_column=True),
         _example((3, 2, 2, 1, 1), within=["region"], descending=True, output="sales_dense_rank"),
         params=_RANK_PARAMS, synonyms=("rank without gaps", "dense"), null_answer=True)
_declare("window.percent_rank", "Percent rank", "Where a row sits in its group, from 0 (first) to 1 (last).",
         _value_tool("percent_rank", "percent_rank", rank_by_column=True),
         _example((0.0, 0.5, 0.0, 1.0, 1.0), within=["region"], output="sales_percent_rank"),
         params=_RANK_PARAMS, synonyms=("percentile rank", "relative rank"), null_answer=True)
_declare("window.cume_dist", "Cumulative distribution", "The share of the group's rows at or before this one, "
         "from just above 0 to 1.", _value_tool("cume_dist", "cume_dist", rank_by_column=True),
         _example((1 / 3, 2 / 3, 0.5, 1.0, 1.0), within=["region"], output="sales_cume_dist"),
         params=_RANK_PARAMS, synonyms=("cdf", "cumulative share", "percentile position"), null_answer=True)
_declare("window.ntile", "Split into equal groups", "Number the rows 1 to N in order, so each number has as near "
         "an equal share of the rows as possible (quartiles, deciles).",
         _value_tool("ntile", "group", rank_by_column=True,
                     extra=lambda p: (Literal(int(p["buckets"]), INT64),)),
         _example((1, 1, 1, 2, 2), buckets=2, within=["region"], output="sales_group"),
         params=(Param("buckets", "Number of groups", ParamKind.INTEGER, default=4, minimum=1, maximum=1000),
                 WITHIN, DESCENDING),
         synonyms=("ntile", "quartile", "decile", "quintile", "bucket", "tercile"), null_answer=True)

# ----------------------------------------------------------- the rows around

_OFFSET = Param("offset", "Rows back", ParamKind.INTEGER, default=1, minimum=0, maximum=100_000)
_AHEAD = Param("offset", "Rows ahead", ParamKind.INTEGER, default=1, minimum=0, maximum=100_000)

_declare("window.lag", "Value from an earlier row", "The value this many rows before, within the group (empty "
         "before the first).", _value_tool("lag", "previous", extra=lambda p: (Literal(int(p["offset"]), INT64),)),
         _example((None, 10.0, None, 20.0, 5.0), within=["region"], order_by=["day"], output="sales_previous"),
         params=(_OFFSET, WITHIN, ORDER_BY, DESCENDING),
         synonyms=("lag", "previous row", "prior value", "last value before", "shift"))
_declare("window.lead", "Value from a later row", "The value this many rows after, within the group (empty after "
         "the last).", _value_tool("lead", "next", extra=lambda p: (Literal(int(p["offset"]), INT64),)),
         _example((20.0, 30.0, 15.0, None, None), within=["region"], order_by=["day"], output="sales_next"),
         params=(_AHEAD, WITHIN, ORDER_BY, DESCENDING), synonyms=("lead", "next row", "following value", "shift"))
_declare("window.first_value", "First value in the group", "The group's first value, in order, on every row.",
         _value_tool("first_value", "first", frame=lambda p: WindowFrame(whole=True)),
         _example((10.0, 10.0, 5.0, 10.0, 5.0), within=["region"], order_by=["day"], output="sales_first"),
         params=(WITHIN, ORDER_BY, DESCENDING), synonyms=("first value", "opening value", "earliest"))
_declare("window.last_value", "Last value in the group", "The group's last value, in order, on every row.",
         _value_tool("last_value", "last", frame=lambda p: WindowFrame(whole=True)),
         _example((30.0, 30.0, 15.0, 30.0, 15.0), within=["region"], order_by=["day"], output="sales_last"),
         params=(WITHIN, ORDER_BY, DESCENDING), synonyms=("last value", "closing value", "latest"))
_declare("window.nth_value", "Nth value in the group", "The group's value at this position, in order, on every "
         "row (empty when the group is shorter).",
         _value_tool("nth_value", "nth", frame=lambda p: WindowFrame(whole=True),
                     extra=lambda p: (Literal(int(p["n"]), INT64),)),
         _example((20.0, 20.0, 15.0, 20.0, 15.0), n=2, within=["region"], order_by=["day"], output="sales_nth"),
         params=(Param("n", "Position", ParamKind.INTEGER, default=2, minimum=1, maximum=100_000),
                 WITHIN, ORDER_BY, DESCENDING), synonyms=("nth value", "second value", "value at position"))

# ------------------------------------------------------------ running values

_RUNNING = (WITHIN, ORDER_BY, DESCENDING, TIES)


def _running(function: str, suffix: str):
    return _value_tool(function, suffix, frame=_frame_for)


_declare("window.cumulative_sum", "Running total", "Add each row's value to the total so far, within the group.",
         _running("sum", "running_total"),
         _example((10.0, 30.0, 5.0, 60.0, 20.0), within=["region"], order_by=["day"], output="sales_running_total"),
         params=_RUNNING, accepts=Accepts.NUMERIC,
         synonyms=("cumulative sum", "running sum", "year to date", "cumsum", "accumulate"))
_declare("window.cumulative_product", "Running product", "Multiply each row's value into the product so far.",
         _running("product", "running_product"),
         _example((10.0, 200.0, 5.0, 6000.0, 75.0), within=["region"], order_by=["day"],
                  output="sales_running_product"),
         params=_RUNNING, accepts=Accepts.NUMERIC, synonyms=("cumulative product", "compound", "cumprod"))
_declare("window.cumulative_max", "Running highest", "The highest value so far, within the group.",
         _running("max", "running_max"),
         _example((10.0, 20.0, 5.0, 30.0, 15.0), within=["region"], order_by=["day"], output="sales_running_max"),
         params=_RUNNING, accepts=Accepts.ANY, synonyms=("cumulative max", "high water mark", "peak so far"))
_declare("window.cumulative_min", "Running lowest", "The lowest value so far, within the group.",
         _running("min", "running_min"),
         _example((10.0, 10.0, 5.0, 10.0, 5.0), within=["region"], order_by=["day"], output="sales_running_min"),
         params=_RUNNING, accepts=Accepts.ANY, synonyms=("cumulative min", "low water mark", "lowest so far"))
_declare("window.cumulative_count", "Running count", "How many values so far, within the group.",
         _running("count", "running_count"),
         _example((1, 2, 1, 3, 2), within=["region"], order_by=["day"], output="sales_running_count"),
         params=_RUNNING, synonyms=("cumulative count", "count so far"), null_answer=True)
_declare("window.running_average", "Running average", "The average of the values so far, within the group.",
         _running("avg", "running_average"),
         _example((10.0, 15.0, 5.0, 20.0, 10.0), within=["region"], order_by=["day"],
                  output="sales_running_average"),
         params=_RUNNING, accepts=Accepts.NUMERIC,
         synonyms=("cumulative average", "running mean", "expanding mean", "average so far"))

# -------------------------------------------------------------- moving values

_MOVING = (ROWS, WITHIN, ORDER_BY, DESCENDING)


def _moving(function: str, suffix: str):
    return _value_tool(function, suffix, frame=lambda p: WindowFrame("rows", int(p["rows"]) - 1))


_declare("window.moving_average", "Moving average", "The average of this row and the rows just before it.",
         _moving("avg", "moving_average"),
         _example((10.0, 15.0, 5.0, 25.0, 10.0), rows=2, within=["region"], order_by=["day"],
                  output="sales_moving_average"),
         params=_MOVING, accepts=Accepts.NUMERIC,
         synonyms=("rolling average", "rolling mean", "sma", "trailing average", "smooth"))
_declare("window.moving_sum", "Moving total", "The total of this row and the rows just before it.",
         _moving("sum", "moving_total"),
         _example((10.0, 30.0, 5.0, 50.0, 20.0), rows=2, within=["region"], order_by=["day"],
                  output="sales_moving_total"),
         params=_MOVING, accepts=Accepts.NUMERIC, synonyms=("rolling sum", "rolling total", "trailing total"))
_declare("window.moving_max", "Moving highest", "The highest of this row and the rows just before it.",
         _moving("max", "moving_max"),
         _example((10.0, 20.0, 5.0, 30.0, 15.0), rows=2, within=["region"], order_by=["day"],
                  output="sales_moving_max"),
         params=_MOVING, accepts=Accepts.ANY, synonyms=("rolling max", "rolling highest"))
_declare("window.moving_min", "Moving lowest", "The lowest of this row and the rows just before it.",
         _moving("min", "moving_min"),
         _example((10.0, 10.0, 5.0, 20.0, 5.0), rows=2, within=["region"], order_by=["day"],
                  output="sales_moving_min"),
         params=_MOVING, accepts=Accepts.ANY, synonyms=("rolling min", "rolling lowest"))
_declare("window.rolling_stdev", "Moving standard deviation", "How spread out this row and the rows just before "
         "it are (empty with only one value).", _moving("stddev", "moving_stdev"),
         _example((None, 7.071068, None, 7.071068, 7.071068), rows=2, within=["region"], order_by=["day"],
                  output="sales_moving_stdev"),
         params=_MOVING, accepts=Accepts.NUMERIC, synonyms=("rolling standard deviation", "volatility", "rolling std"))
_declare("window.ema", "Exponential moving average", "A moving average that weighs recent rows more; the span "
         "sets how quickly older rows fade.",
         _value_tool("ema", "ema", extra=lambda p: (Literal(float(p["span"]), FLOAT64),)),
         _example((10.0, 16.666667, 5.0, 25.555556, 11.666667), span=2, within=["region"], order_by=["day"],
                  output="sales_ema"),
         params=(Param("span", "Span in rows", ParamKind.NUMBER, default=10, minimum=1, maximum=100_000),
                 WITHIN, ORDER_BY, DESCENDING),
         accepts=Accepts.NUMERIC, synonyms=("ewma", "exponentially weighted", "smoothing", "ema"))


def _rolling_correlation(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    other = require_column(node, params.get("other"))
    name = _output(node, params, f"{column}_{other}_correlation")
    temp = _temp(node)
    call = WindowCall("rolling_corr", (Column(column), Column(other), Literal(int(params["rows"]), INT64)))
    return _beside(node, _window(node, params, [(temp, call)]), {name: Column(temp)}, column)


_declare("window.rolling_correlation", "Moving correlation", "How closely this column moves with another over "
         "the last rows: 1 together, -1 opposite, 0 unrelated.", _rolling_correlation,
         Example(rows=({"a": 1.0, "b": 2.0}, {"a": 2.0, "b": 4.0}, {"a": 3.0, "b": 5.0}, {"a": 4.0, "b": 3.0}),
                 params={"other": "b", "rows": 3}, column="a", output="a_b_correlation",
                 expect=(None, 1.0, 0.981981, -0.5)),
         params=(Param("other", "With column", ParamKind.COLUMN), ROWS, WITHIN, ORDER_BY, DESCENDING),
         accepts=Accepts.NUMERIC, synonyms=("rolling correlation", "moving correlation", "co-movement"))


def _session(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    name = _output(node, params, "session")
    temp = _temp(node)
    gap = float(params["gap_minutes"]) * 60
    call = WindowCall("session", (Column(column), Literal(gap, FLOAT64)))
    order = (SortKey(Column(column), "asc", False),)
    return _beside(node, _window(node, params, [(temp, call)], order=order), {name: Column(temp)}, column)


_declare("window.session", "Number the sessions", "Group events into sessions: a new session starts after a "
         "gap longer than this many minutes, counted 1, 2, 3 within each group.", _session,
         Example(rows=({"user": "a", "at": "2026-01-01 09:00"}, {"user": "a", "at": "2026-01-01 09:10"},
                       {"user": "a", "at": "2026-01-01 11:00"}, {"user": "b", "at": "2026-01-01 09:05"}),
                 params={"gap_minutes": 30, "within": ["user"]}, column="at", output="session",
                 expect=(1, 1, 2, 1)),
         params=(Param("gap_minutes", "Gap that ends a session, in minutes", ParamKind.NUMBER, default=30,
                       minimum=0), WITHIN),
         accepts=Accepts.ANY, synonyms=("sessionise", "sessionize", "visits", "session window", "activity gap"))

# --------------------------------------------------- values against the group


def _against(kind: str, suffix: str):
    def build(node: Node, params: dict[str, Any]) -> Node:
        column = require_column(node, params.get("column"))
        name = _output(node, params, f"{column}_{suffix}")
        value = Column(column)
        whole = WindowFrame(whole=True)
        if kind in ("difference", "percent_change"):
            temp = _temp(node)
            window = _window(node, params, [(temp, WindowCall("lag", (value,)))])
            previous = Column(temp)
            made = (Call("sub", (value, previous)) if kind == "difference"
                    else Call("div", (Call("sub", (value, previous)), Call("nullif", (previous, Literal(0, INT64))))))
            return _beside(node, window, {name: made}, column)
        if kind == "percent_of_total":
            total = _temp(node)
            window = Window(node, _columns(node, params.get("within"), "Within each"), (),
                            ((total, WindowCall("sum", (value,), whole)),))
            made = Call("mul", (Call("div", (value, Call("nullif", (Column(total), Literal(0, INT64))))),
                                Literal(100, INT64)))
            return _beside(node, window, {name: made}, column)
        low, high = _temp(node, 0), _temp(node, 1)
        if kind == "normalise":
            window = Window(node, _columns(node, params.get("within"), "Within each"), (), (
                (low, WindowCall("min", (value,), whole)), (high, WindowCall("max", (value,), whole))))
            spread = Call("nullif", (Call("sub", (Column(high), Column(low))), Literal(0, INT64)))
            return _beside(node, window, {name: Call("div", (Call("sub", (value, Column(low))), spread))}, column)
        # z-score
        window = Window(node, _columns(node, params.get("within"), "Within each"), (), (
            (low, WindowCall("avg", (value,), whole)), (high, WindowCall("stddev", (value,), whole))))
        made = Call("div", (Call("sub", (value, Column(low))), Call("nullif", (Column(high), Literal(0, INT64)))))
        return _beside(node, window, {name: made}, column)

    return build


_declare("window.difference", "Difference from the row before", "This row's value minus the one before it in the "
         "group (empty for the first).", _against("difference", "change"),
         _example((None, 10.0, None, 10.0, 10.0), within=["region"], order_by=["day"], output="sales_change"),
         params=(WITHIN, ORDER_BY, DESCENDING), accepts=Accepts.NUMERIC,
         synonyms=("difference", "delta", "change", "diff", "increase"))
_declare("window.percent_change", "Percent change from the row before", "How much this row's value changed from "
         "the one before, as a share of it (0.5 is half as much again).", _against("percent_change", "pct_change"),
         _example((None, 1.0, None, 0.5, 2.0), within=["region"], order_by=["day"], output="sales_pct_change"),
         params=(WITHIN, ORDER_BY, DESCENDING), accepts=Accepts.NUMERIC,
         synonyms=("percent change", "growth", "pct change", "rate of change", "relative change"))
_declare("window.percent_of_total", "Percent of the group's total", "This row's value as a percentage of its "
         "group's total.", _against("percent_of_total", "pct_of_total"),
         _example((100 / 6, 200 / 6, 25.0, 50.0, 75.0), within=["region"], output="sales_pct_of_total"),
         params=(WITHIN,), accepts=Accepts.NUMERIC,
         synonyms=("percent of total", "share of total", "proportion", "contribution", "mix"))
_declare("window.normalise", "Scale from 0 to 1", "Rescale so the group's lowest value is 0 and its highest 1 "
         "(empty when every value is the same).", _against("normalise", "scaled"),
         _example((0.0, 0.5, 0.0, 1.0, 1.0), within=["region"], output="sales_scaled"),
         params=(WITHIN,), accepts=Accepts.NUMERIC,
         synonyms=("normalise", "normalize", "min max scale", "0 to 1", "rescale to range"))
_declare("window.z_score", "Standard score", "How many standard deviations a value is from its group's average "
         "(a z-score).", _against("z_score", "z_score"),
         _example((-1.0, 0.0, -0.707107, 1.0, 0.707107), within=["region"], output="sales_z_score"),
         params=(WITHIN,), accepts=Accepts.NUMERIC,
         synonyms=("z score", "standardise", "standardize", "standard score", "zscore"))


def _top_per_group(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("by"))
    count = int(params["count"])
    temp = _temp(node)
    function = "rank" if params.get("ties") == "keep every tie" else "row_number"
    order = (SortKey(Column(column), "asc" if params.get("smallest") else "desc", False),)
    window = _window(node, params, [(temp, WindowCall(function))], order=order)
    kept = Filter(window, Call("le", (Column(temp), Literal(count, INT64))))
    return Project(kept, tuple((name, Column(name)) for name in node.schema()))


_declare("window.top_n_per_group", "Keep the top rows of each group", "Keep the rows with the highest (or lowest) "
         "values of a column within each group.", _top_per_group,
         Example(rows=_SALES, params={"by": "sales", "count": 1, "within": ["region"]}, column="region",
                 output="sales", expect=(30.0, 15.0)),
         params=(Param("by", "By column", ParamKind.COLUMN), Param("count", "Rows per group", ParamKind.INTEGER,
                 default=3, minimum=1, maximum=1_000_000), WITHIN,
                 Param("smallest", "Smallest instead", ParamKind.BOOLEAN, required=False, default=False),
                 Param("ties", "When rows tie", ParamKind.SELECT, required=False, default="keep exactly that many",
                       options=("keep exactly that many", "keep every tie"))),
         synonyms=("top n per group", "best per group", "highest per category", "top 3"), column_scoped=False)

# ------------------------------------------------------------ filling gaps


_declare("null.fill_forward", "Fill down", "Fill an empty value with the last value above it in the group "
         "(merged cells, sparse readings).", _value_tool("fill_forward", "filled"),
         Example(rows=({"g": "a", "v": 1.0}, {"g": "a", "v": None}, {"g": "b", "v": None}, {"g": "a", "v": 3.0}),
                 params={"within": ["g"], "into": "v_filled"}, column="v", output="v_filled",
                 expect=(1.0, 1.0, None, 3.0)),
         params=(WITHIN, ORDER_BY, DESCENDING), category="Missing data",
         synonyms=("fill forward", "fill down", "carry forward", "last observation carried forward", "ffill",
                   "merged cells"))
_declare("null.fill_backward", "Fill up", "Fill an empty value with the next value below it in the group.",
         _value_tool("fill_backward", "filled"),
         Example(rows=({"g": "a", "v": None}, {"g": "a", "v": 2.0}, {"g": "b", "v": None}, {"g": "a", "v": 3.0}),
                 params={"within": ["g"], "into": "v_filled"}, column="v", output="v_filled",
                 expect=(2.0, 2.0, None, 3.0)),
         params=(WITHIN, ORDER_BY, DESCENDING), category="Missing data",
         synonyms=("fill backward", "fill up", "back fill", "bfill", "next observation carried backward"))
