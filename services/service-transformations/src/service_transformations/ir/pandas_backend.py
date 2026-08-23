"""Execute an IR tree with pandas.

One of two backends. The other emits SQL, and a differential test asserts the
two produce identical frames -- which is the only thing that makes pushdown
trustworthy, because pushdown rewrites the user's computation.
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd

from service_transformations.ir.expressions import Call, Case, Cast, Column, Expr, Literal
from service_transformations.ir.pandas_functions import HANDLERS as FUNCTION_HANDLERS
from service_transformations.ir.nodes import (
    Aggregate,
    Distinct,
    Extension,
    Filter,
    IRError,
    Join,
    Limit,
    Node,
    Project,
    Scan,
    SetOp,
    Sort,
)

#: Handlers for `Extension`, registered by the steps that need them. Keeping
#: them out here means the IR never learns what a bespoke step does.
_EXTENSIONS: dict[str, Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame]] = {}


def register_extension(
    name: str, handler: Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame]
) -> None:
    _EXTENSIONS[name] = handler


def execute(node: Node, sources: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Run the tree against named frames."""
    if isinstance(node, Scan):
        if node.source not in sources:
            raise IRError(
                f"No frame supplied for {node.source!r}. "
                f"Available: {', '.join(sorted(sources)) or 'none'}."
            )
        return sources[node.source].copy()

    if isinstance(node, Project):
        frame = execute(node.input, sources)
        out = pd.DataFrame(index=frame.index)
        for name, expr in node.projections:
            out[name] = evaluate(expr, frame)
        return out.reset_index(drop=True)

    if isinstance(node, Filter):
        frame = execute(node.input, sources)
        # Null is not true -- SQL three-valued logic, which every database uses.
        mask = _truthy(evaluate(node.predicate, frame))
        return frame[mask].reset_index(drop=True)

    if isinstance(node, Aggregate):
        return _aggregate(node, sources)

    if isinstance(node, Join):
        return _join(node, sources)

    if isinstance(node, Sort):
        frame = execute(node.input, sources)
        if frame.empty:
            return frame
        temp_names = []
        for index, key in enumerate(node.keys):
            temp = f"__sort_{index}"
            frame[temp] = evaluate(key.expr, frame)
            temp_names.append(temp)
        frame = frame.sort_values(
            by=temp_names,
            ascending=[key.direction == "asc" for key in node.keys],
            na_position="first" if node.keys[0].nulls_first else "last",
            kind="mergesort",  # stable, so equal keys keep their input order
        )
        return frame.drop(columns=temp_names).reset_index(drop=True)

    if isinstance(node, Limit):
        frame = execute(node.input, sources)
        end = None if node.count is None else node.offset + node.count
        return frame.iloc[node.offset : end].reset_index(drop=True)

    if isinstance(node, Distinct):
        frame = execute(node.input, sources)
        subset = list(node.subset) or None
        keep: Any = node.keep if node.keep in ("first", "last") else "first"
        return frame.drop_duplicates(subset=subset, keep=keep).reset_index(drop=True)

    if isinstance(node, SetOp):
        return _set_op(node, sources)

    if isinstance(node, Extension):
        frame = execute(node.input, sources)
        handler = _EXTENSIONS.get(node.name)
        if handler is None:
            raise IRError(
                f"No handler registered for extension step {node.name!r}."
            )
        return handler(frame, node.config_dict()).reset_index(drop=True)

    raise IRError(f"Cannot execute {type(node).__name__}.")


def _aggregate(node: Aggregate, sources: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frame = execute(node.input, sources)

    keys: list[str] = []
    working = pd.DataFrame(index=frame.index)
    for name, expr in node.group_by:
        working[name] = evaluate(expr, frame)
        keys.append(name)

    # Materialise each aggregate's argument so `sum(a * b)` works, not just
    # `sum(a)`.
    specs: list[tuple[str, str, str]] = []
    for index, (name, expr) in enumerate(node.aggregates):
        assert isinstance(expr, Call)
        temp = f"__agg_{index}"
        working[temp] = (
            evaluate(expr.args[0], frame)
            if expr.args
            else pd.Series(1, index=frame.index)
        )
        specs.append((name, expr.name, temp))

    if not keys:
        row = {name: _apply_aggregate(func, working[temp]) for name, func, temp in specs}
        return pd.DataFrame([row])

    if working.empty:
        # groupby on an empty frame yields no groups, and reset_index() then has
        # no key columns to restore -- so the result lost its grouping columns
        # entirely. SQL returns zero rows with the full column list.
        return pd.DataFrame({name: pd.Series(dtype="object") for name in
                             [*keys, *[name for name, _, _ in specs]]})

    grouped = working.groupby(keys, dropna=False, sort=True)
    out = pd.DataFrame()
    for name, func, temp in specs:
        out[name] = _aggregate_series(grouped[temp], func)
    out = out.reset_index()
    return out[[*keys, *[name for name, _, _ in specs]]]


_AGGREGATE_METHODS = {
    "sum": "sum",
    "avg": "mean",
    "min": "min",
    "max": "max",
    "median": "median",
    "count": "count",
    "count_distinct": "nunique",
    "stddev": "std",
    "first": "first",
    "last": "last",
}


def _aggregate_series(grouped, func: str):
    method = _AGGREGATE_METHODS.get(func)
    if method is None:
        raise IRError(f"No pandas implementation for aggregate {func!r}.")
    if func == "sum":
        # `min_count=1` because pandas sums an all-null group to 0 while SQL
        # returns NULL. Without it, a group with no data reports a total of
        # zero, which reads as a real answer rather than an absent one.
        return grouped.sum(min_count=1)
    return getattr(grouped, method)()


def _apply_aggregate(func: str, series: pd.Series):
    method = _AGGREGATE_METHODS.get(func)
    if method is None:
        raise IRError(f"No pandas implementation for aggregate {func!r}.")
    if func == "sum":
        return series.sum(min_count=1)
    return getattr(series, method)()


def _join(node: Join, sources: dict[str, pd.DataFrame]) -> pd.DataFrame:
    left = execute(node.left, sources)
    right = execute(node.right, sources)

    if node.how == "cross":
        return left.merge(right, how="cross")

    keys = _equi_keys(node.on)
    if keys is None:
        raise IRError(
            "Only equality join conditions are supported so far; "
            f"got {node.on}."
        )
    left_keys = [left_name for left_name, _ in keys]
    right_keys = [right_name for _, right_name in keys]

    if node.how in ("semi", "anti"):
        marker = right[right_keys].drop_duplicates()
        merged = left.merge(
            marker, how="left", left_on=left_keys, right_on=right_keys,
            indicator=True, suffixes=("", "__probe"),
        )
        wanted = "both" if node.how == "semi" else "left_only"
        kept = merged[merged["_merge"] == wanted]
        return kept[left.columns].reset_index(drop=True)

    # Rename the overlap explicitly rather than relying on merge's suffixes.
    # Merging on two columns with the SAME name collapses them into one, so
    # pandas produced `region` where Join.schema() -- and therefore the SQL
    # backend, lineage, and every node above -- declared `region` and
    # `region_right`. Found by the differential test.
    overlap = set(left.columns) & set(right.columns)
    left_renames = {c: f"{c}{node.left_suffix}" for c in overlap if node.left_suffix}
    right_renames = {c: f"{c}{node.right_suffix}" for c in overlap}
    left_side = left.rename(columns=left_renames)
    right_side = right.rename(columns=right_renames)

    merged = left_side.merge(
        right_side,
        how=node.how,
        left_on=[left_renames.get(k, k) for k in left_keys],
        right_on=[right_renames.get(k, k) for k in right_keys],
    ).reset_index(drop=True)

    # Emit exactly the declared schema, in its declared order.
    return merged[list(node.schema().keys())]


def _equi_keys(on: Expr | None) -> list[tuple[str, str]] | None:
    """Read `a = b AND c = d` into column pairs, or None if it is not that shape."""
    if on is None:
        return None
    if isinstance(on, Call) and on.name == "and":
        collected: list[tuple[str, str]] = []
        for arg in on.args:
            nested = _equi_keys(arg)
            if nested is None:
                return None
            collected.extend(nested)
        return collected
    if isinstance(on, Call) and on.name == "eq":
        left, right = on.args
        if isinstance(left, Column) and isinstance(right, Column):
            return [(left.name, right.name)]
    return None


def _set_op(node: SetOp, sources: dict[str, pd.DataFrame]) -> pd.DataFrame:
    left = execute(node.left, sources)
    right = execute(node.right, sources)
    right = right.rename(columns=dict(zip(right.columns, left.columns)))

    if node.kind == "union_all":
        return pd.concat([left, right], ignore_index=True)
    if node.kind == "union":
        return pd.concat([left, right], ignore_index=True).drop_duplicates().reset_index(
            drop=True
        )
    if node.kind == "intersect":
        return left.merge(right.drop_duplicates(), how="inner").drop_duplicates().reset_index(
            drop=True
        )
    if node.kind == "except":
        merged = left.merge(
            right.drop_duplicates(), how="left", indicator=True
        )
        return (
            merged[merged["_merge"] == "left_only"][left.columns]
            .drop_duplicates()
            .reset_index(drop=True)
        )
    raise IRError(f"Unknown set operation {node.kind!r}.")


# -- expressions ----------------------------------------------------------

_COMPARISONS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
}

_ARITHMETIC = {
    "add": lambda a, b: a + b,
    "sub": lambda a, b: a - b,
    "mul": lambda a, b: a * b,
    "div": lambda a, b: a / b,
    "mod": lambda a, b: a % b,
}


def _three_valued(result: pd.Series, *operands: pd.Series) -> pd.Series:
    """Give a comparison SQL's null semantics.

    pandas evaluates `NaN > 5` to False; SQL evaluates `NULL > 5` to NULL. The
    difference is invisible until a NOT is applied -- `NOT (NULL > 5)` is NULL
    in SQL and so excludes the row, but False negated is True and so keeps it.
    A differential test caught pandas returning three rows where SQL returned
    one.

    Nullable `boolean` dtype then gives Kleene AND/OR/NOT for free, matching
    every database.
    """
    out = result.astype("boolean")
    unknown = operands[0].isna()
    for operand in operands[1:]:
        unknown = unknown | operand.isna()
    out[unknown] = pd.NA
    return out


def _truthy(series: pd.Series) -> pd.Series:
    """Collapse three-valued logic to two at a boundary that must decide.

    WHERE and CASE both treat NULL as not-true, so this is where the unknown
    becomes a definite no -- and nowhere earlier.
    """
    return series.astype("boolean").fillna(False).astype(bool)


def evaluate(expr: Expr, frame: pd.DataFrame) -> pd.Series:
    """Evaluate an expression over a frame, vectorised."""
    if isinstance(expr, Column):
        if expr.name not in frame.columns:
            raise IRError(f"Column {expr.name!r} is not in the frame.")
        return frame[expr.name]

    if isinstance(expr, Literal):
        return pd.Series([expr.value] * len(frame), index=frame.index)

    if isinstance(expr, Cast):
        return _cast(evaluate(expr.value, frame), expr.to)

    if isinstance(expr, Case):
        result = (
            evaluate(expr.default, frame)
            if expr.default is not None
            else pd.Series([None] * len(frame), index=frame.index)
        )
        # Later branches must not overwrite earlier ones, so apply in reverse.
        for condition, value in reversed(expr.branches):
            mask = _truthy(evaluate(condition, frame))
            result = result.where(~mask, evaluate(value, frame))
        return result

    if isinstance(expr, Call):
        return _call(expr, frame)

    raise IRError(f"Cannot evaluate {type(expr).__name__}.")


def _call(expr: Call, frame: pd.DataFrame) -> pd.Series:
    name = expr.name
    args = [evaluate(arg, frame) for arg in expr.args]

    if name in _COMPARISONS:
        return _three_valued(_COMPARISONS[name](args[0], args[1]), args[0], args[1])
    if name in _ARITHMETIC:
        return _ARITHMETIC[name](args[0], args[1])
    if name == "and":
        result = _as_boolean(args[0], name)
        for arg in args[1:]:
            result = result & _as_boolean(arg, name)
        return result
    if name == "or":
        result = _as_boolean(args[0], name)
        for arg in args[1:]:
            result = result | _as_boolean(arg, name)
        return result
    if name == "not":
        return ~_as_boolean(args[0], name)
    # These coerce first. A numeric column that is entirely null arrives as
    # object dtype -- which is the normal state of an optional column in a
    # sparse file -- and `.abs()` and `.round()` raise on object rather than
    # returning nulls. Coercing keeps "all null in, all null out" true.
    if name == "neg":
        return -_numeric(args[0])
    if name == "abs":
        return _numeric(args[0]).abs()
    if name == "round":
        digits = int(expr.args[1].value) if len(expr.args) > 1 else 0  # type: ignore[union-attr]
        return _numeric(args[0]).round(digits)
    if name == "floor":
        return _numeric(args[0]).apply(lambda v: None if pd.isna(v) else int(v // 1))
    if name == "ceil":
        return _numeric(args[0]).apply(lambda v: None if pd.isna(v) else -int(-v // 1))
    if name == "is_null":
        return args[0].isna().astype("boolean")
    if name == "is_not_null":
        return args[0].notna().astype("boolean")
    if name == "between":
        low = _three_valued(args[0] >= args[1], args[0], args[1])
        high = _three_valued(args[0] <= args[2], args[0], args[2])
        return low & high
    if name == "in_list":
        values = [a.value for a in expr.args[1:]]  # type: ignore[union-attr]
        return _three_valued(args[0].isin(values), args[0])
    if name == "upper":
        return args[0].astype("string").str.upper()
    if name == "lower":
        return args[0].astype("string").str.lower()
    if name == "trim":
        return args[0].astype("string").str.strip()
    if name == "length":
        return args[0].astype("string").str.len()
    if name == "concat":
        result = args[0].astype("string")
        for arg in args[1:]:
            result = result + arg.astype("string")
        return result
    if name == "substring":
        start = int(expr.args[1].value)  # type: ignore[union-attr]
        count = int(expr.args[2].value) if len(expr.args) > 2 else None  # type: ignore[union-attr]
        # SQL SUBSTR is 1-based; Python is 0-based.
        begin = max(start - 1, 0)
        end = None if count is None else begin + count
        return args[0].astype("string").str[begin:end]
    if name == "replace":
        return args[0].astype("string").str.replace(
            str(expr.args[1].value), str(expr.args[2].value), regex=False  # type: ignore[union-attr]
        )
    if name == "coalesce":
        result = args[0]
        for arg in args[1:]:
            # `where` rather than `fillna`: fillna on an object column silently
            # downcasts the result, which pandas has deprecated and which would
            # change a column's type as a side effect of filling a blank.
            result = result.where(result.notna(), arg)
        return result
    if name == "year":
        return pd.to_datetime(args[0], errors="coerce", format="mixed").dt.year
    if name == "to_date":
        # `errors="coerce"` is the difference between "row 40,000 is empty" and
        # "the run failed". Without `format="mixed"` pandas infers a format from
        # the first value and then raises on the second one that differs.
        return pd.to_datetime(args[0], errors="coerce", format="mixed").dt.date
    if name == "date_trunc":
        unit = str(expr.args[0].value)  # type: ignore[union-attr]
        return pd.to_datetime(args[1], errors="coerce", format="mixed").dt.floor(
            {"day": "D", "hour": "h", "minute": "min", "second": "s"}[unit]
        )

    # -- maths ------------------------------------------------------------
    if name == "sqrt":
        return _numeric(args[0]).pow(0.5)
    if name == "exp":
        import numpy as np

        return pd.Series(np.exp(_numeric(args[0])), index=frame.index)
    if name in ("ln", "log10"):
        import numpy as np

        values = _numeric(args[0])
        # Zero and negatives have no logarithm; NaN rather than -inf keeps the
        # column numeric and the failure visible as a null.
        with np.errstate(divide="ignore", invalid="ignore"):
            out = np.log(values) if name == "ln" else np.log10(values)
        return pd.Series(out, index=frame.index).replace([np.inf, -np.inf], pd.NA)
    if name == "power":
        return _numeric(args[0]).pow(_numeric(args[1]))
    if name == "sign":
        import numpy as np

        return pd.Series(np.sign(_numeric(args[0])), index=frame.index)
    if name == "trunc":
        return _numeric(args[0]).apply(lambda v: None if pd.isna(v) else int(v))
    if name == "greatest":
        result = _numeric(args[0])
        for arg in args[1:]:
            result = result.combine(_numeric(arg), lambda a, b: max(a, b) if pd.notna(a) and pd.notna(b) else None)
        return result
    if name == "least":
        result = _numeric(args[0])
        for arg in args[1:]:
            result = result.combine(_numeric(arg), lambda a, b: min(a, b) if pd.notna(a) and pd.notna(b) else None)
        return result

    # -- text -------------------------------------------------------------
    if name == "left":
        count = int(expr.args[1].value)  # type: ignore[union-attr]
        return args[0].astype("string").str[:count]
    if name == "right":
        count = int(expr.args[1].value)  # type: ignore[union-attr]
        return args[0].astype("string").str[-count:] if count > 0 else args[0].astype("string").str[:0]
    if name == "ltrim":
        return args[0].astype("string").str.lstrip()
    if name == "rtrim":
        return args[0].astype("string").str.rstrip()
    if name in ("lpad", "rpad"):
        width = int(expr.args[1].value)  # type: ignore[union-attr]
        fill = str(expr.args[2].value)  # type: ignore[union-attr]
        side = "left" if name == "lpad" else "right"
        return args[0].astype("string").str.pad(width, side=side, fillchar=fill or " ")
    if name == "position":
        needle = str(expr.args[1].value)  # type: ignore[union-attr]
        # 1-based like SQL and every spreadsheet; 0 means not found.
        return args[0].astype("string").str.find(needle).add(1)
    if name == "starts_with":
        return args[0].astype("string").str.startswith(str(expr.args[1].value), na=None)  # type: ignore[union-attr]
    if name == "ends_with":
        return args[0].astype("string").str.endswith(str(expr.args[1].value), na=None)  # type: ignore[union-attr]
    if name == "contains":
        return args[0].astype("string").str.contains(str(expr.args[1].value), regex=False, na=None)  # type: ignore[union-attr]
    if name == "reverse":
        return args[0].astype("string").apply(lambda v: None if pd.isna(v) else v[::-1])
    if name == "repeat":
        times = int(expr.args[1].value)  # type: ignore[union-attr]
        return args[0].astype("string").str.repeat(max(0, times))
    if name == "initcap":
        return args[0].astype("string").str.title()
    if name == "regex_match":
        return args[0].astype("string").str.match(str(expr.args[1].value), na=None)  # type: ignore[union-attr]
    if name == "regex_extract":
        group = int(expr.args[2].value) if len(expr.args) > 2 else 1  # type: ignore[union-attr]
        # Always expand and select: `expand=False` silently returns a DataFrame
        # when the pattern has more than one capture group, and everything
        # downstream then receives the wrong shape.
        extracted = args[0].astype("string").str.extract(
            str(expr.args[1].value), expand=True  # type: ignore[union-attr]
        )
        if group < 1 or group > extracted.shape[1]:
            raise IRError(
                f"regex_extract asked for group {group}, but the pattern has "
                f"{extracted.shape[1]} capture group(s)."
            )
        return extracted.iloc[:, group - 1]
    if name == "regex_replace":
        return args[0].astype("string").str.replace(
            str(expr.args[1].value), str(expr.args[2].value), regex=True  # type: ignore[union-attr]
        )
    if name == "split_part":
        sep = str(expr.args[1].value)  # type: ignore[union-attr]
        index = int(expr.args[2].value)  # type: ignore[union-attr]
        return args[0].astype("string").apply(
            lambda v: None if pd.isna(v) else (v.split(sep)[index - 1] if 0 < index <= len(v.split(sep)) else None)
        )

    # -- temporal ---------------------------------------------------------
    if name in ("month", "day", "hour", "minute", "quarter"):
        parsed = pd.to_datetime(args[0], errors="coerce", format="mixed")
        return getattr(parsed.dt, name)
    if name == "day_of_week":
        # ISO: Monday is 1. Stated because every system numbers this differently
        # and a report that is off by one day is very hard to spot.
        return pd.to_datetime(args[0], errors="coerce", format="mixed").dt.dayofweek.add(1)
    if name == "week":
        return pd.to_datetime(args[0], errors="coerce", format="mixed").dt.isocalendar().week.astype("Int64")
    if name == "days_between":
        left = pd.to_datetime(args[0], errors="coerce", format="mixed")
        right = pd.to_datetime(args[1], errors="coerce")
        return (right - left).dt.days
    if name == "add_days":
        days = pd.to_numeric(args[1], errors="coerce")
        return pd.to_datetime(args[0], errors="coerce", format="mixed") + pd.to_timedelta(days, unit="D")
    if name == "now":
        return pd.Series([pd.Timestamp.now(tz="UTC")] * len(frame), index=frame.index)
    if name == "today":
        return pd.Series([pd.Timestamp.now().date()] * len(frame), index=frame.index)

    # -- type and information ---------------------------------------------
    if name == "to_number":
        return pd.to_numeric(args[0], errors="coerce")
    if name == "to_text":
        return _render_text(args[0])
    if name == "is_number":
        return pd.to_numeric(args[0], errors="coerce").notna().astype("boolean")
    if name == "is_text":
        return args[0].apply(lambda v: isinstance(v, str)).astype("boolean")
    if name == "if_error":
        # An unparseable value becomes the fallback rather than failing the run.
        return args[0].where(args[0].notna(), args[1])
    if name == "nullif":
        return args[0].where(args[0] != args[1])

    # The Phase 16 catalogue lives in its own table: it is a few hundred
    # scalar behaviours, and inlining them here would bury the parts of this
    # module that are actually subtle.
    handler = FUNCTION_HANDLERS.get(name)
    if handler is not None:
        return handler(args, expr)

    raise IRError(f"No pandas implementation for {name!r}.")


def _as_boolean(series: pd.Series, function: str) -> pd.Series:
    """Coerce to nullable boolean, or say plainly why it cannot be done.

    Without this, `not(some_text_column)` surfaced as pandas' "Need to pass
    bool-like values", which tells the person who wrote the formula nothing.
    """
    try:
        return series.astype("boolean")
    except (TypeError, ValueError) as exc:
        raise IRError(
            f"{function}() needs a true/false value, but this column holds "
            f"{series.dtype} values. Compare it first, for example "
            f"`{function}(column > 0)`."
        ) from exc


def _render_text(series: pd.Series) -> pd.Series:
    """Render values as text the way a person would write them.

    A null turns an integer column into float64, so a plain `astype("string")`
    renders 10 as "10.0". Integral values lose the decimal.
    """
    if pd.api.types.is_float_dtype(series):
        return series.apply(
            lambda value: None
            if pd.isna(value)
            else (str(int(value)) if float(value).is_integer() else str(value))
        ).astype("string")
    return series.astype("string")


def _numeric(series: pd.Series) -> pd.Series:
    """Coerce to numbers, turning anything unparseable into a null."""
    return pd.to_numeric(series, errors="coerce")


def _cast(series: pd.Series, to) -> pd.Series:
    from shared_python.types import Kind

    if to.kind is Kind.STRING:
        return series.astype("string")
    if to.is_integer:
        return pd.to_numeric(series, errors="coerce").astype("Int64")
    if to.is_float:
        return pd.to_numeric(series, errors="coerce").astype("float64")
    if to.kind is Kind.BOOLEAN:
        return series.astype("boolean")
    if to.kind is Kind.TIMESTAMP:
        return pd.to_datetime(series, errors="coerce", utc=to.tz_aware)
    if to.kind is Kind.DECIMAL:
        from decimal import Decimal

        return series.apply(lambda v: None if pd.isna(v) else Decimal(str(v)))
    return series
