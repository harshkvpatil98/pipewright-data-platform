"""Checks inside a recipe: assertions about the data at this step (E1).

A check passes the data through unchanged and, when it does not hold, does
what it was told: **stop** the run with a message naming the rows (the
default: a recipe that delivers wrong data is worse than one that stops),
**warn** and carry on, or, for checks about single rows, **mark** them in a
true or false column to filter or quarantine later. A dataset's own checks
and contract (C1) still run when it is stored; these are for what a recipe
assumes at a given step.
"""

from __future__ import annotations

import re
from typing import Any, Callable

import numpy as np
import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import BOOLEAN
from shared_python.words import count_of, listing

from service_transformations.ir.clock import evaluation_instant
from service_transformations.ir.nodes import Node
from service_transformations.ir.pandas_backend import warn
from service_transformations.tools import register
from service_transformations.tools.local import columns_of, extension, handles, other_dataset, other_label
from service_transformations.tools.spec import EXAMPLE_DATASET, Example, Param, ParamKind, ToolSpec

CATEGORY = "Validation"
WHEN = Param("on_failure", "When it does not hold", ParamKind.SELECT, required=False, default="stop the run",
             options=("stop the run", "warn", "mark the rows"),
             help="Mark adds a true or false column saying which rows fail, for checks about single rows.")
WHEN_WHOLE = Param("on_failure", "When it does not hold", ParamKind.SELECT, required=False, default="stop the run",
                   options=("stop the run", "warn"))
EXAMPLES_SHOWN = 5

#: (failing rows as a boolean mask, or None for a check about the whole data; a sentence when it fails)
Outcome = tuple[np.ndarray | None, str | None]


class CheckFailed(BadRequestError):
    """A recipe's check did not hold and was told to stop the run."""


def _declare(name: str, title: str, summary: str, check: Callable[[pd.DataFrame, dict[str, Any]], Outcome],
             example: Example, *, params: tuple[Param, ...], synonyms: tuple[str, ...] = (), rows: bool = True,
             reads_dataset: bool = False, columns_key: str | None = "columns") -> ToolSpec:
    def build(node: Node, settings: dict[str, Any]) -> Node:
        if columns_key and settings.get(columns_key) is not None:
            names = settings[columns_key] if isinstance(settings[columns_key], list) else [settings[columns_key]]
            columns_of(node, names, "Check")
        when = settings.get("on_failure") or "stop the run"
        flag = None
        schema = dict(node.schema())
        if when == "mark the rows":
            if not rows:
                raise BadRequestError("This check is about all the rows together, so it can stop the run or warn.")
            flag = (settings.get("flag") or "").strip() or f"fails_{name.split('.')[-1]}"
            if flag in schema:
                raise BadRequestError(f"Column {flag!r} already exists. Name the marking column.")
            schema[flag] = BOOLEAN
        config = {key: value for key, value in settings.items() if key != "into"}
        return extension(node, name, {**config, "flag": flag, "title": title}, schema)

    def handler(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
        failing, sentence = check(frame, config)
        when = config.get("on_failure") or "stop the run"
        out = frame.copy()
        if config.get("flag"):
            out[config["flag"]] = failing if failing is not None else np.zeros(len(frame), dtype=bool)
            return out
        if sentence:
            if failing is not None and failing.any():
                positions = np.flatnonzero(failing)[:EXAMPLES_SHOWN] + 1
                sentence += f" Rows {listing([f'{p:,}' for p in positions])}" + (
                    " and more." if failing.sum() > EXAMPLES_SHOWN else ".")
            message = f"{config.get('title') or name}: {sentence}"
            if when == "stop the run":
                raise CheckFailed(message)
            warn(message)
        return out

    handles(name)(handler)
    params_all = (*params, WHEN if rows else WHEN_WHOLE)
    if rows:
        params_all += (Param("flag", "Marking column", ParamKind.TEXT, required=False, default=""),)
    return register(ToolSpec(
        name=name, title=title, category=CATEGORY, summary=summary, build=build, example=example,
        params=params_all, synonyms=synonyms, column_scoped=False, local_only=True, null_answer=True,
        warns_lost=False, row_wise=rows, reads_dataset=reads_dataset,
    ))


def _either(items: list[str]) -> str:
    """"a, b or c": the alternatives a check names."""
    items = [str(item) for item in items]
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} or {items[-1]}"


_SINGULAR = {"have": "has", "are": "is", "do": "does", "go": "goes", "share": "shares"}


def _rows(failing: np.ndarray, what: str) -> Outcome:
    count = int(failing.sum())
    if count == 1:
        # "1 row has", not "1 row have".
        verb, _, rest = what.partition(" ")
        what = f"{_SINGULAR.get(verb, verb)} {rest.replace('their ', 'its ', 1)}".strip()
    return failing, (f"{count_of(count, 'row')} {what}." if count else None)


def _mark(name: str, rows_: tuple[dict[str, Any], ...], params: dict[str, Any], expect: tuple, *,
          other: tuple[dict[str, Any], ...] = ()) -> Example:
    return Example(rows=rows_, params={**params, "on_failure": "mark the rows", "flag": "bad"}, output="bad",
                   expect=expect, other=other, note=f"With on_failure set to mark the rows; {name}.")


_COLUMN = Param("column", "Column", ParamKind.COLUMN)
_COLUMNS = Param("columns", "Columns", ParamKind.COLUMNS)


# ------------------------------------------------------------- one row at a time


def _not_empty(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    columns = list(config["columns"])
    empty = frame[columns].isna() | frame[columns].map(lambda v: isinstance(v, str) and not v.strip())
    return _rows(empty.any(axis=1).to_numpy(), f"have an empty {_either(columns)}")


_declare("assert.not_empty", "Check nothing is empty", "Every row has a value in these columns.", _not_empty,
         _mark("the second has no email", ({"email": "a@x.com"}, {"email": " "}), {"columns": ["email"]},
               (False, True)),
         params=(_COLUMNS,), synonyms=("assert not null", "required", "not empty", "mandatory", "no blanks"))


def _in_set(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    allowed = {str(v) for v in config["values"]}
    values = frame[config["column"]]
    outside = values.notna() & ~values.map(lambda v: str(v) in allowed)
    return _rows(outside.to_numpy(), f"have a {config['column']} not in {_either(sorted(allowed))}")


_declare("assert.in_set", "Check values are from a list", "Every value of the column is one of these (empty "
         "values pass; check them with Check nothing is empty).", _in_set,
         _mark("purple is not allowed", ({"colour": "red"}, {"colour": "purple"}, {"colour": None}),
               {"column": "colour", "values": ["red", "green"]}, (False, True, False)),
         params=(_COLUMN, Param("values", "Allowed values", ParamKind.LIST)),
         synonyms=("assert in set", "allowed values", "accepted values", "enum check"), columns_key="column")


def _in_range(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    values = pd.to_numeric(frame[config["column"]], errors="coerce")
    low, high = config.get("minimum"), config.get("maximum")
    outside = pd.Series(False, index=frame.index)
    if low is not None:
        outside |= values < float(low)
    if high is not None:
        outside |= values > float(high)
    outside |= frame[config["column"]].notna() & values.isna()
    bounds = " to ".join(f"{bound:g}" for bound in (low, high) if bound is not None) or "any"
    return _rows(outside.to_numpy(), f"have a {config['column']} outside {bounds} (or not a number)")


_declare("assert.in_range", "Check numbers are in a range", "Every value is a number at least the lowest and at "
         "most the highest given.", _in_range,
         _mark("a negative price", ({"price": 3}, {"price": -1}), {"column": "price", "minimum": 0}, (False, True)),
         params=(_COLUMN, Param("minimum", "Lowest", ParamKind.NUMBER, required=False),
                 Param("maximum", "Highest", ParamKind.NUMBER, required=False)),
         synonyms=("assert range", "between", "bounds", "min max check"), columns_key="column")


def _matches(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    try:
        pattern = re.compile(config["pattern"])
    except re.error as exc:
        raise BadRequestError(f"That pattern will not compile: {exc}.") from None
    values = frame[config["column"]]
    failing = values.notna() & ~values.map(lambda v: bool(pattern.fullmatch(str(v))))
    return _rows(failing.to_numpy(), f"have a {config['column']} that does not match {config['pattern']}")


_declare("assert.matches", "Check values match a pattern", "Every value matches a regular expression in full.",
         _matches,
         _mark("a code too short", ({"code": "AB12"}, {"code": "A1"}), {"column": "code", "pattern": r"[A-Z]{2}\d{2}"},
               (False, True)),
         params=(_COLUMN, Param("pattern", "Pattern", ParamKind.TEXT)),
         synonyms=("assert regex", "pattern check", "format check", "matches"), columns_key="column")

_READS = {
    "a number": lambda s: pd.to_numeric(s, errors="coerce"),
    "a whole number": lambda s: pd.to_numeric(s, errors="coerce").where(lambda v: v == v.round()),
    "a date": lambda s: pd.to_datetime(s, errors="coerce", format="mixed"),
    "true or false": lambda s: s.map(lambda v: True if str(v).strip().lower() in
                                     ("true", "false", "yes", "no", "1", "0", "y", "n", "t", "f") else None),
}


def _of_type(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    values = frame[config["column"]]
    read = _READS[config.get("type") or "a number"](values)
    failing = values.notna() & pd.Series(read, index=values.index).isna()
    return _rows(failing.to_numpy(), f"have a {config['column']} that is not {config.get('type') or 'a number'}")


_declare("assert.type", "Check values are of a type", "Every value reads as a number, a whole number, a date or "
         "true or false.", _of_type,
         _mark("seven is a word", ({"qty": "3"}, {"qty": "seven"}), {"column": "qty", "type": "a number"},
               (False, True)),
         params=(_COLUMN, Param("type", "Should be", ParamKind.SELECT, default="a number", options=tuple(_READS))),
         synonyms=("assert type", "type check", "is numeric", "data type check"), columns_key="column")


def _formula(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    from service_transformations.formula.parser import parse_formula
    from service_transformations.ir.pandas_backend import evaluate

    expression = parse_formula(config["formula"], columns=[str(c) for c in frame.columns])
    holds = evaluate(expression, frame)
    failing = ~holds.astype("boolean").fillna(False).astype(bool)
    return _rows(failing.to_numpy(), f"do not satisfy {config['formula']}")


_declare("assert.formula", "Check a formula holds", "Every row satisfies a formula that is true or false, such as "
         "[shipped] >= [ordered]; a row where it is empty fails.", _formula,
         _mark("shipped before it was ordered", ({"ordered": 3, "shipped": 4}, {"ordered": 5, "shipped": 2}),
               {"formula": "[shipped] >= [ordered]"}, (False, True)),
         params=(Param("formula", "Formula", ParamKind.TEXT, placeholder="[shipped] >= [ordered]"),),
         synonyms=("custom assertion", "assert formula", "rule", "business rule", "invariant"), columns_key=None)


def _found_in(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    from service_transformations.tools.catalogue.combine import comparable

    other = other_dataset(config)
    if config["right_on"] not in other.columns:
        raise BadRequestError(f"{other_label(config)} has no {config['right_on']!r}.")
    mine, theirs, _ = comparable(frame[config["column"]], other[config["right_on"]])
    known = set(theirs.dropna().tolist())
    failing = mine.notna() & ~mine.map(lambda v: v in known)
    return _rows(failing.to_numpy(), f"have a {config['column']} that {other_label(config)} does not have")


_declare("assert.found_in", "Check every key exists elsewhere", "Every value of the column appears in another "
         "dataset's column (each order's customer is a known customer): referential integrity.", _found_in,
         _mark("customer 9 is unknown", ({"customer": 1}, {"customer": 9}),
               {"column": "customer", "right_dataset_id": EXAMPLE_DATASET, "right_on": "id"}, (False, True),
               other=({"id": 1}, {"id": 2})),
         params=(_COLUMN, Param("right_dataset_id", "Other dataset", ParamKind.DATASET),
                 Param("right_on", "Its column", ParamKind.DATASET_COLUMN)),
         synonyms=("referential integrity", "foreign key check", "assert exists", "orphan rows", "lookup check"),
         reads_dataset=True, columns_key="column")


# ------------------------------------------------------------- all the rows


def _unique(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    columns = list(config.get("columns") or frame.columns)
    repeated = frame.duplicated(subset=columns, keep=False).to_numpy() if len(frame) else np.zeros(0, dtype=bool)
    what = f"share their {listing(columns)} with another" if config.get("columns") else "are repeated in full"
    return _rows(repeated, what)


_declare("assert.unique", "Check values are unique", "No two rows have the same values in these columns (a key).",
         _unique,
         _mark("two rows share id 2", ({"id": 1}, {"id": 2}, {"id": 2}), {"columns": ["id"]}, (False, True, True)),
         params=(_COLUMNS,), synonyms=("assert unique", "primary key", "unique key", "no duplicate keys"))
_declare("assert.no_duplicates", "Check no row is repeated", "No two rows are the same in every column.", _unique,
         _mark("the last row repeats the first", ({"a": 1, "b": "x"}, {"a": 2, "b": "x"}, {"a": 1, "b": "x"}), {},
               (True, False, True)),
         params=(), synonyms=("assert no duplicates", "duplicate rows", "distinct rows check"), columns_key=None)


def _row_count(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    rows, low, high = len(frame), config.get("minimum"), config.get("maximum")
    if low is not None and rows < int(low):
        return None, f"{count_of(rows, 'row')}, fewer than {int(low):,}."
    if high is not None and rows > int(high):
        return None, f"{count_of(rows, 'row')}, more than {int(high):,}."
    return None, None


_declare("assert.row_count", "Check the number of rows", "There are at least, or at most, this many rows (an "
         "import that brought nothing; a join that multiplied).", _row_count,
         Example(rows=({"a": 1}, {"a": 2}), params={"minimum": 1, "maximum": 10}, output="a", expect=(1, 2),
                 note="Passes: 2 rows is between 1 and 10."),
         params=(Param("minimum", "At least", ParamKind.INTEGER, required=False, minimum=0),
                 Param("maximum", "At most", ParamKind.INTEGER, required=False, minimum=0)),
         synonyms=("assert row count", "row count", "volume check", "not empty dataset"), rows=False,
         columns_key=None)


def _increasing(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    values = frame[config["column"]]
    numbers = pd.to_numeric(values, errors="coerce")
    if numbers.notna().sum() < values.notna().sum():
        numbers = pd.to_datetime(values, errors="coerce", format="mixed")
    present = numbers.dropna()
    steps = present.diff().iloc[1:]
    zero = pd.Timedelta(0) if pd.api.types.is_datetime64_any_dtype(present) else 0
    bad = steps <= zero if config.get("strictly") else steps < zero
    failing = np.zeros(len(frame), dtype=bool)
    failing[[frame.index.get_loc(i) for i in bad[bad].index]] = True
    what = "go down" if not config.get("strictly") else "do not go up"
    return _rows(failing, f"{what} from the row before in {config['column']}")


_declare("assert.increasing", "Check values only go up", "Each value of the column is at least the one before it "
         "(or, strictly, more): a sequence, a running total, timestamps in order.", _increasing,
         _mark("the third goes back", ({"t": 1}, {"t": 2}, {"t": 1}), {"column": "t"}, (False, False, True)),
         params=(_COLUMN, Param("strictly", "Strictly", ParamKind.BOOLEAN, required=False, default=False)),
         synonyms=("assert monotonic", "increasing", "in order", "sorted check", "sequence check"),
         columns_key="column")


def _sum_equals(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    total = float(pd.to_numeric(frame[config["column"]], errors="coerce").sum())
    expected, tolerance = float(config["expected"]), float(config.get("tolerance") or 0)
    if abs(total - expected) > tolerance:
        return None, f"{config['column']} adds up to {total:,.6g}, not {expected:,.6g}."
    return None, None


_declare("assert.sum_equals", "Check a total", "The column adds up to this, within a tolerance (shares add to "
         "100, debits equal credits).", _sum_equals,
         Example(rows=({"share": 60}, {"share": 40}), params={"column": "share", "expected": 100}, output="share",
                 expect=(60, 40), note="Passes: 60 and 40 add to 100."),
         params=(_COLUMN, Param("expected", "Should add up to", ParamKind.NUMBER),
                 Param("tolerance", "Within", ParamKind.NUMBER, required=False, default=0, minimum=0)),
         synonyms=("assert sum", "total check", "reconcile", "balance check", "control total"), rows=False,
         columns_key="column")


def _fresh(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    stamps = pd.to_datetime(frame[config["column"]], errors="coerce", format="mixed", utc=True)
    newest = stamps.max()
    now = pd.Timestamp(evaluation_instant())
    hours = float(config["hours"])
    if pd.isna(newest):
        return None, f"{config['column']} has no dates, so how fresh the data is cannot be told."
    age = (now - newest).total_seconds() / 3600
    if age > hours:
        return None, f"the newest {config['column']} is {age:,.1f} hours old, more than {hours:g}."
    return None, None


_declare("assert.fresh", "Check the data is recent", "The newest date or time in the column is no older than "
         "this many hours when the recipe runs (a replay checks against the moment of the run it repeats).",
         _fresh,
         Example(rows=({"at": "2200-01-01"},), params={"column": "at", "hours": 24}, output="at",
                 expect=("2200-01-01",), note="Passes: the newest value is not old."),
         params=(_COLUMN, Param("hours", "At most this many hours old", ParamKind.NUMBER, default=24, minimum=0)),
         synonyms=("assert freshness", "freshness", "stale data", "latest date check", "sla"), rows=False,
         columns_key="column")


def _schema(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    from shared_python.types.inference import infer_pw_type

    wanted: dict[str, str | None] = {}
    for line in config["columns"]:
        name, _, kind = str(line).partition(":")
        wanted[name.strip()] = kind.strip().lower() or None
    problems = []
    missing = [name for name in wanted if name not in frame.columns]
    if missing:
        problems.append(f"{listing(missing)} {'is' if len(missing) == 1 else 'are'} missing")
    for name, kind in wanted.items():
        if kind and name in frame.columns and len(frame):
            actual = infer_pw_type(frame[name])
            family = ("number" if actual.is_numeric else "date" if actual.is_temporal else
                      "true or false" if actual.kind.value == "boolean" else "text")
            if kind not in (family, actual.kind.value):
                problems.append(f"{name} is {family}, not {kind}")
    if not config.get("extra_allowed", True):
        extra = [name for name in frame.columns if name not in wanted]
        if extra:
            problems.append(f"{listing([str(e) for e in extra])} {'is' if len(extra) == 1 else 'are'} not expected")
    return None, ("; ".join(problems) + ".").capitalize() if problems else None


_declare("assert.schema", "Check the columns", "The data has these columns (each optionally with a type, as "
         "name:number, name:date, name:text, name:true or false), and, if asked, no others.", _schema,
         Example(rows=({"id": 1, "name": "a"},), params={"columns": ["id:number", "name"]}, output="id",
                 expect=(1,), note="Passes: id is a number and name is there."),
         params=(Param("columns", "Expected columns", ParamKind.LIST, placeholder="id:number\nname:text"),
                 Param("extra_allowed", "Other columns are fine", ParamKind.BOOLEAN, required=False, default=True)),
         synonyms=("assert schema", "schema check", "expected columns", "column check", "schema snapshot"),
         rows=False, columns_key=None)


def _stable(frame: pd.DataFrame, config: dict[str, Any]) -> Outcome:
    from scipy import stats

    other = other_dataset(config)
    column, theirs_name = config["column"], config.get("right_on") or config["column"]
    if theirs_name not in other.columns:
        raise BadRequestError(f"{other_label(config)} has no {theirs_name!r}.")
    mine, theirs = frame[column].dropna(), other[theirs_name].dropna()
    if mine.empty or theirs.empty:
        return None, None
    numbers = pd.to_numeric(mine, errors="coerce").dropna()
    reference = pd.to_numeric(theirs, errors="coerce").dropna()
    limit = float(config.get("threshold") or 0.2)
    if len(numbers) == len(mine) and len(reference) == len(theirs):
        statistic = float(stats.ks_2samp(numbers, reference).statistic)
        measure = f"the Kolmogorov-Smirnov distance between them is {statistic:.3f}"
    else:
        # Population stability index over the categories both have.
        shares_now = mine.astype(str).value_counts(normalize=True)
        shares_then = theirs.astype(str).value_counts(normalize=True)
        keys = shares_now.index.union(shares_then.index)
        now = shares_now.reindex(keys, fill_value=0) + 1e-6
        then = shares_then.reindex(keys, fill_value=0) + 1e-6
        statistic = float(((now - then) * np.log(now / then)).sum())
        measure = f"the population stability index is {statistic:.3f}"
    if statistic > limit:
        return None, f"{column} is not distributed as in {other_label(config)}: {measure}, more than {limit:g}."
    return None, None


_declare("assert.distribution_stable", "Check values look as they did", "The column's values are distributed as "
         "in another dataset, such as this recipe's own output from the run before: by the Kolmogorov-Smirnov "
         "distance for numbers and the population stability index for categories, below a threshold.", _stable,
         Example(rows=({"v": 1}, {"v": 2}, {"v": 3}), params={"column": "v", "right_dataset_id": EXAMPLE_DATASET},
                 output="v", expect=(1, 2, 3), other=({"v": 1}, {"v": 2}, {"v": 3}),
                 note="Passes: the same values as the dataset compared with."),
         params=(_COLUMN, Param("right_dataset_id", "Compared with", ParamKind.DATASET),
                 Param("right_on", "Its column", ParamKind.DATASET_COLUMN, required=False),
                 Param("threshold", "Largest change allowed", ParamKind.NUMBER, required=False, default=0.2,
                       minimum=0)),
         synonyms=("assert distribution", "drift check", "distribution stable", "psi", "ks test"), rows=False,
         reads_dataset=True, columns_key="column")
