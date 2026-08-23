"""Expressions in the relational IR.

An expression is a tree over columns and literals. It exists separately from the
node algebra because the same expression appears in several places -- a filter
predicate, a projection, an aggregate argument, a join condition -- and each of
those should not re-invent what "upper(name) || '-' || cast(id as text)" means.

**Why a fixed catalogue.** Every ``Call`` names a function from
:data:`FUNCTIONS`, which declares its signature and how each dialect writes it.
That is the same allowlist discipline the existing ``derive_column`` evaluator
uses for safety, widened from "safe to evaluate" to "portable across engines":
a function with no lowering for a dialect is *reported*, so the planner runs it
locally instead of emitting SQL that means something subtly different.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from shared_python.types import (
    BOOLEAN,
    FLOAT32,
    FLOAT64,
    INT64,
    STRING,
    Kind,
    PWType,
    timestamp,
    widen,
)
from shared_python.types.lattice import DATE, UNKNOWN


class Expr:
    """Base class. Subclasses are frozen dataclasses so trees can be compared."""

    def type_of(self, schema: dict[str, PWType]) -> PWType:  # pragma: no cover
        raise NotImplementedError

    def columns_used(self) -> set[str]:  # pragma: no cover
        raise NotImplementedError


@dataclass(frozen=True)
class Column(Expr):
    """A reference to a column in the input."""

    name: str

    def type_of(self, schema: dict[str, PWType]) -> PWType:
        # An unknown column is UNKNOWN rather than an error here; the node layer
        # validates references, and reporting every missing name twice is noise.
        return schema.get(self.name, UNKNOWN)

    def columns_used(self) -> set[str]:
        return {self.name}

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Literal(Expr):
    """A constant. The declared type matters: NULL has to be typed to be useful."""

    value: Any
    type: PWType

    def type_of(self, schema: dict[str, PWType]) -> PWType:
        return self.type

    def columns_used(self) -> set[str]:
        return set()

    def __str__(self) -> str:
        if self.value is None:
            return "NULL"
        return repr(self.value)


@dataclass(frozen=True)
class Cast(Expr):
    """An explicit conversion. Never inserted implicitly."""

    value: Expr
    to: PWType

    def type_of(self, schema: dict[str, PWType]) -> PWType:
        return self.to

    def columns_used(self) -> set[str]:
        return self.value.columns_used()

    def __str__(self) -> str:
        return f"cast({self.value} as {self.to})"


@dataclass(frozen=True)
class Case(Expr):
    """``CASE WHEN c THEN v ... ELSE d END``.

    Kept as its own node rather than nested IF calls because every dialect
    writes it natively and because the result type is the widening of every
    branch, which is easier to state once here.
    """

    branches: tuple[tuple[Expr, Expr], ...]
    default: Expr | None = None

    def type_of(self, schema: dict[str, PWType]) -> PWType:
        result: PWType | None = None
        for _, value in self.branches:
            branch_type = value.type_of(schema)
            result = branch_type if result is None else widen(result, branch_type)
            if result is None:
                # Branches that cannot meet produce a column nobody can compute
                # with; UNKNOWN says so instead of picking one arbitrarily.
                return UNKNOWN
        if self.default is not None and result is not None:
            result = widen(result, self.default.type_of(schema)) or UNKNOWN
        return result or UNKNOWN

    def columns_used(self) -> set[str]:
        used: set[str] = set()
        for condition, value in self.branches:
            used |= condition.columns_used() | value.columns_used()
        if self.default is not None:
            used |= self.default.columns_used()
        return used

    def __str__(self) -> str:
        parts = " ".join(f"when {c} then {v}" for c, v in self.branches)
        tail = f" else {self.default}" if self.default is not None else ""
        return f"case {parts}{tail} end"


@dataclass(frozen=True)
class Call(Expr):
    """A function application. ``name`` must be in :data:`FUNCTIONS`."""

    name: str
    args: tuple[Expr, ...] = ()

    def __post_init__(self) -> None:
        if self.name not in FUNCTIONS:
            raise ValueError(
                f"Unknown function {self.name!r}. "
                f"Known: {', '.join(sorted(FUNCTIONS))}."
            )
        signature = FUNCTIONS[self.name]
        if not signature.accepts_arity(len(self.args)):
            raise ValueError(
                f"{self.name} takes {signature.arity_description()}, "
                f"got {len(self.args)}."
            )

    def type_of(self, schema: dict[str, PWType]) -> PWType:
        return FUNCTIONS[self.name].result_type(
            [arg.type_of(schema) for arg in self.args]
        )

    def columns_used(self) -> set[str]:
        used: set[str] = set()
        for arg in self.args:
            used |= arg.columns_used()
        return used

    def __str__(self) -> str:
        return f"{self.name}({', '.join(str(a) for a in self.args)})"


@dataclass(frozen=True)
class Signature:
    """What a function accepts and returns, and how each dialect writes it."""

    name: str
    min_args: int
    max_args: int | None
    #: Given the argument types, the result type.
    result: Callable[[list[PWType]], PWType]
    #: SQL template per dialect. ``None`` in a dialect means "cannot be pushed
    #: down there" -- the planner runs it locally rather than approximating.
    sql: dict[str, str] = field(default_factory=dict)
    #: True for aggregates, which may only appear in an Aggregate node.
    is_aggregate: bool = False

    def accepts_arity(self, count: int) -> bool:
        if count < self.min_args:
            return False
        return self.max_args is None or count <= self.max_args

    def arity_description(self) -> str:
        if self.max_args is None:
            return f"at least {self.min_args} argument(s)"
        if self.min_args == self.max_args:
            return f"exactly {self.min_args} argument(s)"
        return f"{self.min_args}-{self.max_args} arguments"

    def result_type(self, args: list[PWType]) -> PWType:
        return self.result(args)


def _first(args: list[PWType]) -> PWType:
    return args[0] if args else UNKNOWN


def _widest(args: list[PWType]) -> PWType:
    result: PWType | None = None
    for arg in args:
        result = arg if result is None else widen(result, arg)
        if result is None:
            return UNKNOWN
    return result or UNKNOWN


def _numeric_result(args: list[PWType]) -> PWType:
    """The type of an arithmetic result.

    Arithmetic is NOT widening. `widen` looks for a type that holds both values
    exactly, and correctly gives up on decimal-and-float because neither
    contains the other. Multiplying them is perfectly well defined, though: the
    inexact side wins, and the answer is a float. Reusing `widen` here typed
    `[amount] * [qty]` as unknown whenever the two columns differed that way.
    """
    if not args or any(arg.kind is Kind.UNKNOWN for arg in args):
        return UNKNOWN
    if not all(arg.is_numeric for arg in args):
        return UNKNOWN

    # Any float involved makes the result inexact.
    if any(arg.is_float for arg in args):
        return FLOAT64 if any(arg.kind is Kind.FLOAT64 for arg in args) else FLOAT32

    # Decimals stay exact, taking the widest shape of the operands.
    if any(arg.kind is Kind.DECIMAL for arg in args):
        widened = _widest([arg for arg in args])
        return widened if widened.kind is Kind.DECIMAL else UNKNOWN

    # All integers: the widest integer that holds both.
    return _widest(args)


def _const(type_: PWType) -> Callable[[list[PWType]], PWType]:
    return lambda _args: type_


def _define(
    name: str,
    min_args: int,
    max_args: int | None,
    result: Callable[[list[PWType]], PWType],
    sql: dict[str, str] | None = None,
    *,
    is_aggregate: bool = False,
) -> Signature:
    return Signature(name, min_args, max_args, result, sql or {}, is_aggregate)


#: ``{placeholder}`` indexes are the positional arguments.
_ALL = ("postgres", "mysql", "sqlite", "duckdb")


def _same(template: str, dialects: tuple[str, ...] = _ALL) -> dict[str, str]:
    return {dialect: template for dialect in dialects}


FUNCTIONS: dict[str, Signature] = {
    # -- comparison -------------------------------------------------------
    "eq": _define("eq", 2, 2, _const(BOOLEAN), _same("({0} = {1})")),
    "ne": _define("ne", 2, 2, _const(BOOLEAN), _same("({0} <> {1})")),
    "lt": _define("lt", 2, 2, _const(BOOLEAN), _same("({0} < {1})")),
    "le": _define("le", 2, 2, _const(BOOLEAN), _same("({0} <= {1})")),
    "gt": _define("gt", 2, 2, _const(BOOLEAN), _same("({0} > {1})")),
    "ge": _define("ge", 2, 2, _const(BOOLEAN), _same("({0} >= {1})")),
    "is_null": _define("is_null", 1, 1, _const(BOOLEAN), _same("({0} IS NULL)")),
    "is_not_null": _define(
        "is_not_null", 1, 1, _const(BOOLEAN), _same("({0} IS NOT NULL)")
    ),
    # IN is universal, but its arity is variadic so the template is a marker:
    # the SQL backend builds the list itself. Declaring it per dialect is what
    # lets `supported_in` report it as pushable.
    "in_list": _define("in_list", 2, None, _const(BOOLEAN), _same("IN")),
    "between": _define(
        "between", 3, 3, _const(BOOLEAN), _same("({0} BETWEEN {1} AND {2})")
    ),
    # -- logic ------------------------------------------------------------
    "and": _define("and", 2, None, _const(BOOLEAN), _same("({0} AND {1})")),
    "or": _define("or", 2, None, _const(BOOLEAN), _same("({0} OR {1})")),
    "not": _define("not", 1, 1, _const(BOOLEAN), _same("(NOT {0})")),
    # -- arithmetic -------------------------------------------------------
    "add": _define("add", 2, 2, _numeric_result, _same("({0} + {1})")),
    "sub": _define("sub", 2, 2, _numeric_result, _same("({0} - {1})")),
    "mul": _define("mul", 2, 2, _numeric_result, _same("({0} * {1})")),
    "div": _define("div", 2, 2, _const(FLOAT64), _same("({0} / {1})")),
    "mod": _define("mod", 2, 2, _numeric_result, _same("MOD({0}, {1})", ("postgres", "mysql", "duckdb"))),
    "neg": _define("neg", 1, 1, _first, _same("(-{0})")),
    "abs": _define("abs", 1, 1, _first, _same("ABS({0})")),
    "round": _define("round", 1, 2, _first, _same("ROUND({0}, {1})")),
    "floor": _define("floor", 1, 1, _first, _same("FLOOR({0})")),
    "ceil": _define("ceil", 1, 1, _first, _same("CEIL({0})", ("postgres", "mysql", "duckdb"))),
    # -- text -------------------------------------------------------------
    "upper": _define("upper", 1, 1, _const(STRING), _same("UPPER({0})")),
    "lower": _define("lower", 1, 1, _const(STRING), _same("LOWER({0})")),
    "trim": _define("trim", 1, 1, _const(STRING), _same("TRIM({0})")),
    "length": _define(
        "length",
        1,
        1,
        _const(INT64),
        {"postgres": "LENGTH({0})", "mysql": "CHAR_LENGTH({0})",
         "sqlite": "LENGTH({0})", "duckdb": "LENGTH({0})"},
    ),
    "concat": _define(
        "concat",
        2,
        None,
        _const(STRING),
        # SQLite has no CONCAT function; it uses the || operator.
        {"postgres": "CONCAT({0}, {1})", "mysql": "CONCAT({0}, {1})",
         "sqlite": "({0} || {1})", "duckdb": "CONCAT({0}, {1})"},
    ),
    "substring": _define("substring", 2, 3, _const(STRING), _same("SUBSTR({0}, {1}, {2})")),
    "replace": _define("replace", 3, 3, _const(STRING), _same("REPLACE({0}, {1}, {2})")),
    "coalesce": _define("coalesce", 2, None, _widest, _same("COALESCE({0}, {1})")),
    # -- temporal ---------------------------------------------------------
    "date_trunc": _define(
        "date_trunc",
        2,
        2,
        _const(timestamp()),
        # MySQL has no DATE_TRUNC; leaving it out means the planner runs it
        # locally rather than emitting something that rounds differently.
        {"postgres": "DATE_TRUNC({0}, {1})", "duckdb": "DATE_TRUNC({0}, {1})"},
    ),
    "to_date": _define("to_date", 1, 1, _const(DATE), {}),
    "year": _define(
        "year",
        1,
        1,
        _const(INT64),
        {"postgres": "EXTRACT(YEAR FROM {0})", "mysql": "YEAR({0})",
         "duckdb": "EXTRACT(YEAR FROM {0})"},
    ),
    # -- maths ------------------------------------------------------------
    "sqrt": _define("sqrt", 1, 1, _const(FLOAT64), _same("SQRT({0})")),
    "exp": _define("exp", 1, 1, _const(FLOAT64), _same("EXP({0})")),
    "ln": _define("ln", 1, 1, _const(FLOAT64), _same("LN({0})", ("postgres", "mysql", "duckdb"))),
    "log10": _define("log10", 1, 1, _const(FLOAT64), _same("LOG10({0})", ("postgres", "mysql", "duckdb"))),
    "power": _define("power", 2, 2, _const(FLOAT64), _same("POWER({0}, {1})", ("postgres", "mysql", "duckdb"))),
    "sign": _define("sign", 1, 1, _const(INT64), _same("SIGN({0})")),
    "trunc": _define("trunc", 1, 1, _first, _same("TRUNC({0})", ("postgres", "duckdb"))),
    "greatest": _define("greatest", 2, None, _widest, _same("GREATEST({0}, {1})", ("postgres", "mysql", "duckdb"))),
    "least": _define("least", 2, None, _widest, _same("LEAST({0}, {1})", ("postgres", "mysql", "duckdb"))),

    # -- text -------------------------------------------------------------
    "left": _define("left", 2, 2, _const(STRING), _same("LEFT({0}, {1})", ("postgres", "mysql", "duckdb"))),
    "right": _define("right", 2, 2, _const(STRING), _same("RIGHT({0}, {1})", ("postgres", "mysql", "duckdb"))),
    "ltrim": _define("ltrim", 1, 1, _const(STRING), _same("LTRIM({0})")),
    "rtrim": _define("rtrim", 1, 1, _const(STRING), _same("RTRIM({0})")),
    "lpad": _define("lpad", 3, 3, _const(STRING), _same("LPAD({0}, {1}, {2})", ("postgres", "mysql", "duckdb"))),
    "rpad": _define("rpad", 3, 3, _const(STRING), _same("RPAD({0}, {1}, {2})", ("postgres", "mysql", "duckdb"))),
    "position": _define("position", 2, 2, _const(INT64), {}),
    # Lowered through POSITION rather than LIKE. `x LIKE y || '%'` looks
    # simpler and is wrong: a needle containing % or _ becomes a wildcard, so
    # `starts_with(sku, "10%")` would match "10ABC" in SQL and not locally.
    # POSITION treats the needle as text, which is what these mean. The empty
    # needle agrees too -- POSITION('' IN x) is 1, and "".startswith("") is true.
    "starts_with": _define(
        "starts_with", 2, 2, _const(BOOLEAN),
        {
            "postgres": "(POSITION({1} IN {0}) = 1)",
            "duckdb": "(POSITION({1} IN {0}) = 1)",
            "mysql": "(LOCATE({1}, {0}) = 1)",
            "sqlite": "(INSTR({0}, {1}) = 1)",
        },
    ),
    "ends_with": _define(
        "ends_with", 2, 2, _const(BOOLEAN),
        {
            "postgres": "(RIGHT({0}, LENGTH({1})) = {1})",
            "duckdb": "(RIGHT({0}, LENGTH({1})) = {1})",
            "mysql": "(RIGHT({0}, CHAR_LENGTH({1})) = {1})",
        },
    ),
    "contains": _define(
        "contains", 2, 2, _const(BOOLEAN),
        {
            "postgres": "(POSITION({1} IN {0}) > 0)",
            "duckdb": "(POSITION({1} IN {0}) > 0)",
            "mysql": "(LOCATE({1}, {0}) > 0)",
            "sqlite": "(INSTR({0}, {1}) > 0)",
        },
    ),
    "reverse": _define("reverse", 1, 1, _const(STRING), _same("REVERSE({0})", ("postgres", "mysql", "duckdb"))),
    "repeat": _define("repeat", 2, 2, _const(STRING), _same("REPEAT({0}, {1})", ("postgres", "mysql", "duckdb"))),
    "initcap": _define("initcap", 1, 1, _const(STRING), _same("INITCAP({0})", ("postgres", "duckdb"))),
    # Regex: no portable dialect spelling, so these always run locally rather
    # than being lowered to LIKE, which is a different language.
    "regex_match": _define("regex_match", 2, 2, _const(BOOLEAN), {}),
    "regex_extract": _define("regex_extract", 2, 3, _const(STRING), {}),
    "regex_replace": _define("regex_replace", 3, 3, _const(STRING), {}),
    "split_part": _define("split_part", 3, 3, _const(STRING), _same("SPLIT_PART({0}, {1}, {2})", ("postgres", "duckdb"))),

    # -- temporal ---------------------------------------------------------
    "month": _define("month", 1, 1, _const(INT64),
        {"postgres": "EXTRACT(MONTH FROM {0})", "mysql": "MONTH({0})", "duckdb": "EXTRACT(MONTH FROM {0})"}),
    "day": _define("day", 1, 1, _const(INT64),
        {"postgres": "EXTRACT(DAY FROM {0})", "mysql": "DAY({0})", "duckdb": "EXTRACT(DAY FROM {0})"}),
    "hour": _define("hour", 1, 1, _const(INT64),
        {"postgres": "EXTRACT(HOUR FROM {0})", "mysql": "HOUR({0})", "duckdb": "EXTRACT(HOUR FROM {0})"}),
    "minute": _define("minute", 1, 1, _const(INT64),
        {"postgres": "EXTRACT(MINUTE FROM {0})", "mysql": "MINUTE({0})", "duckdb": "EXTRACT(MINUTE FROM {0})"}),
    "quarter": _define("quarter", 1, 1, _const(INT64),
        {"postgres": "EXTRACT(QUARTER FROM {0})", "mysql": "QUARTER({0})", "duckdb": "EXTRACT(QUARTER FROM {0})"}),
    "day_of_week": _define("day_of_week", 1, 1, _const(INT64), {}),
    "week": _define("week", 1, 1, _const(INT64), {}),
    "days_between": _define("days_between", 2, 2, _const(INT64), {}),
    "add_days": _define("add_days", 2, 2, _const(timestamp()), {}),
    "now": _define("now", 0, 0, _const(timestamp(tz_aware=True)), {}),
    "today": _define("today", 0, 0, _const(DATE), {}),

    # -- type and information ---------------------------------------------
    # No lowering for either conversion, deliberately. `CAST(1.0 AS TEXT)` is
    # "1.0" in Postgres where this renders "1", and a failed numeric cast raises
    # in SQL where this yields null. Pushing them would give a different answer
    # depending on where the query ran, which is precisely what pushdown must
    # never do.
    "to_number": _define("to_number", 1, 1, _const(FLOAT64), {}),
    "to_text": _define("to_text", 1, 1, _const(STRING), {}),
    "is_number": _define("is_number", 1, 1, _const(BOOLEAN), {}),
    "is_text": _define("is_text", 1, 1, _const(BOOLEAN), {}),
    "if_error": _define("if_error", 2, 2, _widest, {}),
    "nullif": _define("nullif", 2, 2, _first, _same("NULLIF({0}, {1})")),

    # -- aggregates -------------------------------------------------------
    "count": _define("count", 0, 1, _const(INT64), _same("COUNT({0})"), is_aggregate=True),
    "count_distinct": _define(
        "count_distinct", 1, 1, _const(INT64), _same("COUNT(DISTINCT {0})"), is_aggregate=True
    ),
    "sum": _define("sum", 1, 1, _numeric_result, _same("SUM({0})"), is_aggregate=True),
    "avg": _define("avg", 1, 1, _const(FLOAT64), _same("AVG({0})"), is_aggregate=True),
    "min": _define("min", 1, 1, _first, _same("MIN({0})"), is_aggregate=True),
    "max": _define("max", 1, 1, _first, _same("MAX({0})"), is_aggregate=True),
    "median": _define(
        "median",
        1,
        1,
        _const(FLOAT64),
        # No portable median: Postgres needs an ordered-set aggregate and MySQL
        # has none at all. Declaring nothing keeps it local and correct.
        {"duckdb": "MEDIAN({0})"},
        is_aggregate=True,
    ),
    # Order-dependent: "first" means first in the frame's current order, which
    # SQL only expresses through a window function over an explicit ORDER BY.
    # No lowering, so the planner keeps them local rather than guessing an order.
    "first": _define("first", 1, 1, _first, {}, is_aggregate=True),
    "last": _define("last", 1, 1, _first, {}, is_aggregate=True),
    "stddev": _define(
        "stddev", 1, 1, _const(FLOAT64),
        {"postgres": "STDDEV_SAMP({0})", "duckdb": "STDDEV_SAMP({0})", "mysql": "STDDEV_SAMP({0})"},
        is_aggregate=True,
    ),
    "variance": _define(
        "variance", 1, 1, _const(FLOAT64),
        {"postgres": "VAR_SAMP({0})", "duckdb": "VAR_SAMP({0})", "mysql": "VAR_SAMP({0})"},
        is_aggregate=True,
    ),
    "string_agg": _define(
        "string_agg", 1, 2, _const(STRING),
        {"postgres": "STRING_AGG({0}, {1})", "duckdb": "STRING_AGG({0}, {1})"},
        is_aggregate=True,
    ),
    "any_true": _define(
        "any_true", 1, 1, _const(BOOLEAN),
        {"postgres": "BOOL_OR({0})", "duckdb": "BOOL_OR({0})"},
        is_aggregate=True,
    ),
    "all_true": _define(
        "all_true", 1, 1, _const(BOOLEAN),
        {"postgres": "BOOL_AND({0})", "duckdb": "BOOL_AND({0})"},
        is_aggregate=True,
    ),
    "product": _define("product", 1, 1, _const(FLOAT64), {"duckdb": "PRODUCT({0})"}, is_aggregate=True),

    # ==================================================================
    # Phase 16: the functions the tool library needs.
    #
    # The rule from Phase 08 still holds and is why so many of these declare
    # no lowering: a function whose SQL would mean something *close to* the
    # local implementation is worse than one that stays local, because the
    # difference only shows up as numbers that disagree depending on where the
    # pipeline ran. Where a dialect genuinely matches, it is declared; where it
    # is nearly-but-not-quite, it is not.
    # ==================================================================

    # -- text ---------------------------------------------------------------
    "collapse_whitespace": _define("collapse_whitespace", 1, 1, _const(STRING), {}),
    "remove_accents": _define(
        "remove_accents", 1, 1, _const(STRING),
        # Postgres `unaccent` needs an extension that may not be installed, and
        # a missing-function error at run time is worse than running locally.
        {},
    ),
    "slugify": _define("slugify", 1, 1, _const(STRING), {}),
    "strip_html": _define("strip_html", 1, 1, _const(STRING), {}),
    "title_case": _define("title_case", 1, 1, _const(STRING), {}),
    "sentence_case": _define("sentence_case", 1, 1, _const(STRING), {}),
    "swap_case": _define("swap_case", 1, 1, _const(STRING), {}),
    "camel_to_words": _define("camel_to_words", 1, 1, _const(STRING), {}),
    "remove_characters": _define("remove_characters", 2, 2, _const(STRING), {}),
    "keep_characters": _define("keep_characters", 2, 2, _const(STRING), {}),
    "count_occurrences": _define("count_occurrences", 2, 2, _const(INT64), {}),
    "regex_count": _define("regex_count", 2, 2, _const(INT64), {}),
    "extract_between": _define("extract_between", 3, 3, _const(STRING), {}),
    "extract_before": _define("extract_before", 2, 2, _const(STRING), {}),
    "extract_after": _define("extract_after", 2, 2, _const(STRING), {}),
    "truncate_text": _define("truncate_text", 2, 3, _const(STRING), {}),
    "normalise_unicode": _define("normalise_unicode", 2, 2, _const(STRING), {}),
    "remove_control_characters": _define("remove_control_characters", 1, 1, _const(STRING), {}),
    "fix_mojibake": _define("fix_mojibake", 1, 1, _const(STRING), {}),
    "standardise_line_endings": _define("standardise_line_endings", 1, 1, _const(STRING), {}),
    "trim_quotes": _define("trim_quotes", 1, 1, _const(STRING), {}),
    "unescape": _define("unescape", 1, 1, _const(STRING), {}),
    "soundex": _define(
        "soundex", 1, 1, _const(STRING), {"mysql": "SOUNDEX({0})"}
    ),
    "levenshtein": _define("levenshtein", 2, 2, _const(INT64), {}),
    "similarity": _define("similarity", 2, 2, _const(FLOAT64), {}),
    "char_at": _define("char_at", 2, 2, _const(STRING), {}),
    "word_count": _define("word_count", 1, 1, _const(INT64), {}),
    "translate_characters": _define(
        "translate_characters", 3, 3, _const(STRING),
        {"postgres": "TRANSLATE({0}, {1}, {2})", "duckdb": "TRANSLATE({0}, {1}, {2})"},
    ),

    # -- numeric ------------------------------------------------------------
    "ceil_to": _define("ceil_to", 2, 2, _const(FLOAT64), {}),
    "floor_to": _define("floor_to", 2, 2, _const(FLOAT64), {}),
    "round_to": _define("round_to", 2, 2, _const(FLOAT64), {}),
    "clamp": _define("clamp", 3, 3, _first, {}),
    "log": _define("log", 2, 2, _const(FLOAT64), {}),
    "reciprocal": _define("reciprocal", 1, 1, _const(FLOAT64), {}),
    "int_div": _define("int_div", 2, 2, _const(INT64), {}),
    "is_even": _define("is_even", 1, 1, _const(BOOLEAN), {}),
    "is_odd": _define("is_odd", 1, 1, _const(BOOLEAN), {}),

    # -- date and time ------------------------------------------------------
    "second": _define("second", 1, 1, _const(INT64),
        {"postgres": "EXTRACT(SECOND FROM {0})", "mysql": "SECOND({0})", "duckdb": "EXTRACT(SECOND FROM {0})"}),
    "day_of_year": _define("day_of_year", 1, 1, _const(INT64),
        {"postgres": "EXTRACT(DOY FROM {0})", "mysql": "DAYOFYEAR({0})", "duckdb": "EXTRACT(DOY FROM {0})"}),
    "add_months": _define("add_months", 2, 2, _const(timestamp()), {}),
    "add_years": _define("add_years", 2, 2, _const(timestamp()), {}),
    "months_between": _define("months_between", 2, 2, _const(INT64), {}),
    "years_between": _define("years_between", 2, 2, _const(INT64), {}),
    "seconds_between": _define("seconds_between", 2, 2, _const(FLOAT64), {}),
    "start_of_period": _define("start_of_period", 2, 2, _const(timestamp()), {}),
    "end_of_period": _define("end_of_period", 2, 2, _const(timestamp()), {}),
    "is_weekend": _define("is_weekend", 1, 1, _const(BOOLEAN), {}),
    "business_days_between": _define("business_days_between", 2, 2, _const(INT64), {}),
    "add_business_days": _define("add_business_days", 2, 2, _const(DATE), {}),
    "fiscal_year": _define("fiscal_year", 2, 2, _const(INT64), {}),
    "fiscal_quarter": _define("fiscal_quarter", 2, 2, _const(INT64), {}),
    "age_years": _define("age_years", 1, 2, _const(INT64), {}),
    "epoch_seconds": _define("epoch_seconds", 1, 1, _const(INT64), {}),
    "from_epoch": _define("from_epoch", 1, 2, _const(timestamp()), {}),
    "format_date": _define("format_date", 2, 2, _const(STRING), {}),
    "to_timezone": _define("to_timezone", 2, 2, _const(timestamp(tz_aware=True)), {}),
    "day_name": _define("day_name", 1, 1, _const(STRING), {}),
    "month_name": _define("month_name", 1, 1, _const(STRING), {}),

    # -- type and conversion ------------------------------------------------
    "to_integer": _define("to_integer", 1, 1, _const(INT64), {}),
    "to_boolean": _define("to_boolean", 1, 1, _const(BOOLEAN), {}),
    "to_timestamp": _define("to_timestamp", 1, 2, _const(timestamp()), {}),
    "parse_number_locale": _define("parse_number_locale", 2, 2, _const(FLOAT64), {}),
    "strip_currency": _define("strip_currency", 1, 2, _const(STRING), {}),
    "detect_type": _define("detect_type", 1, 1, _const(STRING), {}),
    "parse_json_path": _define("parse_json_path", 2, 2, _const(STRING), {}),

    # -- validation ---------------------------------------------------------
    "is_email": _define("is_email", 1, 1, _const(BOOLEAN), {}),
    "is_url": _define("is_url", 1, 1, _const(BOOLEAN), {}),
    "is_date": _define("is_date", 1, 1, _const(BOOLEAN), {}),
    "is_blank": _define("is_blank", 1, 1, _const(BOOLEAN), {}),
    "in_range": _define("in_range", 3, 3, _const(BOOLEAN), {}),

    # -- encoding, hashing and privacy -------------------------------------
    # Hashes have real lowerings where the dialect's algorithm is the same
    # algorithm. SQLite has no hash functions at all, so it stays local.
    "md5": _define("md5", 1, 1, _const(STRING),
        {"postgres": "MD5({0})", "mysql": "MD5({0})", "duckdb": "MD5({0})"}),
    "sha1": _define("sha1", 1, 1, _const(STRING), {"mysql": "SHA1({0})"}),
    "sha256": _define("sha256", 1, 1, _const(STRING),
        {"postgres": "ENCODE(SHA256({0}::bytea), 'hex')", "mysql": "SHA2({0}, 256)"}),
    "sha512": _define("sha512", 1, 1, _const(STRING), {"mysql": "SHA2({0}, 512)"}),
    "hmac_sha256": _define("hmac_sha256", 2, 2, _const(STRING), {}),
    "base64_encode": _define("base64_encode", 1, 1, _const(STRING), {"mysql": "TO_BASE64({0})"}),
    "base64_decode": _define("base64_decode", 1, 1, _const(STRING), {"mysql": "FROM_BASE64({0})"}),
    "url_encode": _define("url_encode", 1, 1, _const(STRING), {}),
    "url_decode": _define("url_decode", 1, 1, _const(STRING), {}),
    "html_escape": _define("html_escape", 1, 1, _const(STRING), {}),
    "html_unescape": _define("html_unescape", 1, 1, _const(STRING), {}),
    "mask_partial": _define("mask_partial", 2, 4, _const(STRING), {}),
    "mask_full": _define("mask_full", 1, 2, _const(STRING), {}),
    "pseudonymise": _define("pseudonymise", 2, 2, _const(STRING), {}),

    # -- cleansing and standardisation --------------------------------------
    "standardise_phone": _define("standardise_phone", 2, 2, _const(STRING), {}),
    "standardise_email": _define("standardise_email", 1, 1, _const(STRING), {}),
    "standardise_url": _define("standardise_url", 1, 1, _const(STRING), {}),
    "standardise_postal_code": _define("standardise_postal_code", 2, 2, _const(STRING), {}),
    "standardise_country": _define("standardise_country", 2, 2, _const(STRING), {}),
    "normalise_boolean": _define("normalise_boolean", 1, 1, _const(BOOLEAN), {}),
    "normalise_null_tokens": _define("normalise_null_tokens", 2, 2, _const(STRING), {}),
    "name_part": _define("name_part", 2, 2, _const(STRING), {}),
    "email_domain": _define("email_domain", 1, 1, _const(STRING), {}),
    "url_part": _define("url_part", 2, 2, _const(STRING), {}),
}


AGGREGATE_NAMES = frozenset(
    name for name, signature in FUNCTIONS.items() if signature.is_aggregate
)


def is_aggregate(expr: Expr) -> bool:
    """True when the expression contains an aggregate anywhere inside it."""
    if isinstance(expr, Call):
        if FUNCTIONS[expr.name].is_aggregate:
            return True
        return any(is_aggregate(arg) for arg in expr.args)
    if isinstance(expr, Case):
        return any(
            is_aggregate(c) or is_aggregate(v) for c, v in expr.branches
        ) or (expr.default is not None and is_aggregate(expr.default))
    if isinstance(expr, Cast):
        return is_aggregate(expr.value)
    return False


def supported_in(dialect: str, expr: Expr) -> bool:
    """Whether every function in the tree has a lowering for ``dialect``.

    A dialect that cannot express something must say so; emitting approximate
    SQL is how a pushed-down query quietly returns different numbers from the
    same pipeline run locally.
    """
    if isinstance(expr, Call):
        if dialect not in FUNCTIONS[expr.name].sql:
            return False
        return all(supported_in(dialect, arg) for arg in expr.args)
    if isinstance(expr, Case):
        parts = [part for pair in expr.branches for part in pair]
        if expr.default is not None:
            parts.append(expr.default)
        return all(supported_in(dialect, part) for part in parts)
    if isinstance(expr, Cast):
        return supported_in(dialect, expr.value)
    return True
