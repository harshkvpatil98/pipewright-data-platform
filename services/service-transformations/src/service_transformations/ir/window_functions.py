"""The functions a `Window` node can compute, and which of them push down.

A window function gives every row an answer that depends on other rows of its
partition: its rank, the value before it, the total so far. The catalogue is
closed for the same reason :data:`expressions.FUNCTIONS` is: each entry says
what it means once, the two backends read that, and a dialect that cannot say
exactly the same thing is told so.

**What pushes down is what cannot differ.** Rows that tie on the ordering
arrive in some order, and nothing promises a database delivers them in the
order they arrive here. A rank, a dense rank, a percent rank, a cumulative
distribution and a total over the whole partition, or over the rows up to and
including the current row's peers, come out the same whichever way ties
arrive, so they lower. A row number, a lag or lead, an ntile, a first, last or
nth value and a total over a count of rows do not: two runs over the same
data could disagree about which tied row came first. Those run here, where the
order among ties is the order the rows arrived, exactly as the `first` and
`last` aggregates already do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal as LiteralType

from shared_python.types import FLOAT64, INT64, PWType
from shared_python.types.lattice import UNKNOWN

from service_transformations.ir.expressions import _numeric_result

FrameUnit = LiteralType["peers", "rows"]

#: Dialects whose window syntax the SQL backend writes. MySQL 8 has windows but
#: MySQL 5.7 does not, and a connection does not say which it is, so MySQL keeps
#: windows local (its surface says so).
WINDOW_DIALECTS = ("postgres", "sqlite", "duckdb")


@dataclass(frozen=True)
class WindowFunction:
    name: str
    min_args: int
    max_args: int
    result: Callable[[list[PWType]], PWType]
    #: Needs an ordering to mean anything (a rank of unordered rows is noise).
    #: The rest, given no ordering, take the rows in the order they are in.
    needs_order: bool
    #: Its answer is the same however tied rows arrive, given its frame.
    #: "frame" means it depends on the frame: safe over peers or the whole
    #: partition, not over a count of rows.
    tie_safe: bool | LiteralType["frame"]
    #: Takes a frame (aggregates and value functions); ranking functions do not.
    framed: bool
    #: How each dialect writes it, with {0}, {1} for the arguments. Absent means
    #: it runs here only.
    sql: dict[str, str]
    #: The leading arguments that are columns or expressions; the rest are
    #: constants (an offset, a bucket count, a default, a smoothing span).
    value_args: int = 1


def _const(type_: PWType) -> Callable[[list[PWType]], PWType]:
    return lambda _args: type_


def _first(args: list[PWType]) -> PWType:
    return args[0].with_nullable(True) if args else UNKNOWN


def _sum(args: list[PWType]) -> PWType:
    return _numeric_result(args[:1]).with_nullable(True) if args else UNKNOWN


def _all(template: str) -> dict[str, str]:
    return {dialect: template for dialect in WINDOW_DIALECTS}


WINDOW_FUNCTIONS: dict[str, WindowFunction] = {
    # -- ranking -------------------------------------------------------------
    "row_number": WindowFunction("row_number", 0, 0, _const(INT64), False, False, False, {}, 0),
    "rank": WindowFunction("rank", 0, 0, _const(INT64), True, True, False, _all("RANK()"), 0),
    "dense_rank": WindowFunction("dense_rank", 0, 0, _const(INT64), True, True, False, _all("DENSE_RANK()"), 0),
    "percent_rank": WindowFunction(
        "percent_rank", 0, 0, _const(FLOAT64), True, True, False, _all("PERCENT_RANK()"), 0,
    ),
    "cume_dist": WindowFunction("cume_dist", 0, 0, _const(FLOAT64), True, True, False, _all("CUME_DIST()"), 0),
    "ntile": WindowFunction("ntile", 1, 1, _const(INT64), False, False, False, {}, 0),
    # -- offsets and values ---------------------------------------------------
    # (value, offset, default): the default applies past the partition's edge,
    # never to a value that is itself empty, as in SQL.
    "lag": WindowFunction("lag", 1, 3, _first, False, False, False, {}),
    "lead": WindowFunction("lead", 1, 3, _first, False, False, False, {}),
    "first_value": WindowFunction("first_value", 1, 1, _first, False, False, True, {}),
    "last_value": WindowFunction("last_value", 1, 1, _first, False, False, True, {}),
    "nth_value": WindowFunction("nth_value", 2, 2, _first, False, False, True, {}),
    # -- aggregates over a frame ---------------------------------------------
    "sum": WindowFunction("sum", 1, 1, _sum, False, "frame", True, _all("SUM({0})")),
    "avg": WindowFunction("avg", 1, 1, _const(FLOAT64), False, "frame", True, _all("AVG({0})")),
    "min": WindowFunction("min", 1, 1, _first, False, "frame", True, _all("MIN({0})")),
    "max": WindowFunction("max", 1, 1, _first, False, "frame", True, _all("MAX({0})")),
    "count": WindowFunction("count", 1, 1, _const(INT64), False, "frame", True, _all("COUNT({0})")),
    "product": WindowFunction("product", 1, 1, _const(FLOAT64), False, "frame", True, {}),
    "stddev": WindowFunction(
        "stddev", 1, 1, _const(FLOAT64), False, "frame", True,
        # SQLite has no standard deviation at all.
        {"postgres": "STDDEV_SAMP({0})", "duckdb": "STDDEV_SAMP({0})"},
    ),
    # -- here only -------------------------------------------------------------
    # (value, span): an exponentially weighted average with alpha = 2 / (span + 1).
    "ema": WindowFunction("ema", 2, 2, _const(FLOAT64), False, False, False, {}),
    # (value, other, rows): Pearson correlation over the last `rows` rows.
    "rolling_corr": WindowFunction("rolling_corr", 3, 3, _const(FLOAT64), False, False, False, {}, 2),
    # (time, gap_seconds): the session number, starting at 1, a new one after a gap.
    "session": WindowFunction("session", 2, 2, _const(INT64), True, False, False, {}),
    # (value): the last non-empty value so far, or the next one (fill down / up).
    "fill_forward": WindowFunction("fill_forward", 1, 1, _first, False, False, False, {}),
    "fill_backward": WindowFunction("fill_backward", 1, 1, _first, False, False, False, {}),
}
