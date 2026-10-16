"""Join and combine tools that read another dataset (E1).

The join step does the equal-key joins (inner, left, right, full, cross, semi,
anti) and the union step adds rows. These are the rest: a join exactly as SQL
joins (E2, X3: what a converted SQL model's joins become, since the join step
matches two empty keys and merges same-named keys, as pandas does), matching
the nearest earlier row, a value inside a range, similar text, side by side
by position, and keeping the rows another dataset also has, or does not.

Each saves the other dataset as `right_dataset_id`, reads it under the
reader's policies, and runs here: none of them has an exact SQL form the
planner could prove.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.matching import DEFAULT_THRESHOLD, METHODS, best_matches, normalise
from shared_python.types import FLOAT64
from shared_python.types.lattice import UNKNOWN

from service_transformations.ir.nodes import Node
from service_transformations.tools import register
from service_transformations.tools.builders import require_column
from service_transformations.tools.local import (
    brought,
    columns_of,
    extension,
    handles,
    other_dataset,
    other_label,
    rename_brought,
    require_other_columns,
)
from service_transformations.tools.spec import EXAMPLE_DATASET, Example, Param, ParamKind, ToolSpec

CATEGORY = "Join & combine"

DATASET = Param("right_dataset_id", "Other dataset", ParamKind.DATASET)
BRING = Param("bring", "Columns to bring", ParamKind.DATASET_COLUMNS,
              help="Columns of the other dataset to add to each row.")
SUFFIX = Param("suffix", "Ending for a name already taken", ParamKind.TEXT, required=False, default="_right")


def _declare(name: str, title: str, summary: str, build, example: Example, *, params: tuple[Param, ...],
             synonyms: tuple[str, ...] = (), category: str = CATEGORY, column_scoped: bool = False,
             null_answer: bool = False, row_wise: bool = False) -> ToolSpec:
    return register(ToolSpec(
        name=name, title=title, category=category, summary=summary, build=build, example=example,
        params=params, synonyms=synonyms, column_scoped=column_scoped, local_only=True, reads_dataset=True,
        null_answer=null_answer, warns_lost=False, row_wise=row_wise,
    ))


def _settings(params: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: params.get(key) for key in ("right_dataset_id", *keys)}


# ---------------------------------------------------------------- shared


def comparable(left: pd.Series, right: pd.Series) -> tuple[pd.Series, pd.Series, str]:
    """Two columns in one kind that compares: times, numbers, or text."""
    for kind in ("time", "number"):
        if kind == "time":
            either = pd.api.types.is_datetime64_any_dtype(left) or pd.api.types.is_datetime64_any_dtype(right)
            # A side with no values at all takes the other's kind.
            sides = [_looks_like_time(side) for side in (left, right) if side.notna().any()]
            if not either and not (sides and all(sides)):
                continue
            a, b = _times(left), _times(right)
        else:
            a, b = pd.to_numeric(left, errors="coerce"), pd.to_numeric(right, errors="coerce")
        if a.notna().sum() == left.notna().sum() and b.notna().sum() == right.notna().sum():
            return a, b, kind
    as_text = lambda s: s.map(lambda v: None if pd.isna(v) else str(v))  # noqa: E731
    return as_text(left), as_text(right), "text"


def _looks_like_time(series: pd.Series) -> bool:
    present = series.dropna()
    if present.empty or pd.api.types.is_numeric_dtype(present):
        return False
    sample = present.astype(str).head(20)
    return bool(pd.to_datetime(sample, errors="coerce", format="mixed").notna().all())


def _times(series: pd.Series) -> pd.Series:
    stamps = pd.to_datetime(series, errors="coerce", format="mixed", utc=True)
    return stamps.dt.tz_localize(None)


def _keys(frame: pd.DataFrame, other: pd.DataFrame, left_on: list[str], right_on: list[str]
          ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Each pair of key columns made comparable, under the same names on both sides."""
    left_keys, right_keys = pd.DataFrame(index=frame.index), pd.DataFrame(index=other.index)
    for index, (a, b) in enumerate(zip(left_on, right_on)):
        left_keys[f"__k{index}"], right_keys[f"__k{index}"], _ = comparable(frame[a], other[b])
    return left_keys, right_keys


# ------------------------------------------------------------ as SQL does

_HOW = ("inner", "left", "right", "full", "semi", "anti")
#: SQL's rule, and the one Alteryx's Join and pandas follow, for an empty key.
_EMPTY_KEYS = ("never match", "match each other")


def _brought_names(left: list[str], bring: list[str], suffix: str) -> dict[str, str]:
    """Each brought column's name here: its own, or with the ending when this dataset has it."""
    names = {name: name if name not in left else f"{name}{suffix}" for name in bring}
    taken = [out for out in names.values() if out in left]
    if taken or len(set(names.values())) < len(names):
        clash = taken[0] if taken else next(out for out in names.values() if list(names.values()).count(out) > 1)
        raise BadRequestError(f"{clash!r} would be two columns. Choose another ending for names already taken.")
    return names


def _sql_join_build(node: Node, params: dict[str, Any]) -> Node:
    on = columns_of(node, params.get("on"), "Match on")
    right_on = list(params.get("right_on") or [])
    if not on or len(on) != len(right_on):
        raise BadRequestError("Match on and their columns need the same number of columns, at least one.")
    how = params.get("how") or "inner"
    if how not in _HOW:
        raise BadRequestError(f"A join here is {', '.join(_HOW[:-1])} or {_HOW[-1]}.")
    empty_keys = params.get("empty_keys") or "never match"
    if empty_keys not in _EMPTY_KEYS:
        raise BadRequestError("Empty keys either never match or match each other.")
    # Keeping the rows that match (semi) or do not (anti) brings nothing.
    bring = [] if how in ("semi", "anti") else list(params.get("bring") or [])
    suffix = params.get("suffix") or "_right"
    names = _brought_names(list(node.schema()), bring, suffix)
    schema = {name: (type_.with_nullable(True) if how in ("right", "full") else type_)
              for name, type_ in node.schema().items()}
    schema.update({out: UNKNOWN for out in names.values()})
    config = {**_settings(params, "right_on", "suffix"), "bring": bring, "on": on, "how": how,
              "empty_keys": empty_keys}
    return extension(node, "join.sql", config, schema)


@handles("join.sql")
def _sql_join(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from service_transformations.ir import pandas_backend
    from service_transformations.ir.expressions import Call, Column
    from service_transformations.ir.nodes import IRError, Join, Scan

    other = other_dataset(config)
    on, right_on, bring = list(config["on"]), list(config["right_on"]), list(config.get("bring") or [])
    require_other_columns(other, [*right_on, *bring], "Join as SQL does", config)
    left = frame.reset_index(drop=True)
    names = _brought_names(list(left.columns), bring, config.get("suffix") or "_right")
    # The other side's keys under names nothing else has, so they never clash
    # and never stay: SQL keeps both sides' columns, here the brought ones.
    marker = "__join_key"
    while any(str(column).startswith(marker) for column in [*left.columns, *names.values()]):
        marker += "_"
    probe, right = left.copy(), pd.DataFrame(index=other.reset_index(drop=True).index)
    left_keys, right_keys = [], []
    matching = (config.get("empty_keys") or "never match") == "match each other"
    for index, (a, b) in enumerate(zip(on, right_on)):
        # Each pair compared in one kind (times, numbers or text), as the other joins here do.
        mine, theirs, kind = comparable(left[a].reset_index(drop=True), other[b].reset_index(drop=True))
        if matching:
            # Two empty keys equal each other: match on "is it empty" and on the
            # value with every empty one filled the same way.
            filler = {"number": 0, "time": pd.Timestamp(0)}.get(kind, "")
            probe[f"{marker}e{index}"], right[f"{marker}f{index}"] = mine.isna().to_numpy(), theirs.isna().to_numpy()
            left_keys.append(f"{marker}e{index}")
            right_keys.append(f"{marker}f{index}")
            mine, theirs = mine.where(mine.notna(), filler), theirs.where(theirs.notna(), filler)
        probe[f"{marker}l{index}"], right[f"{marker}r{index}"] = mine.to_numpy(), theirs.to_numpy()
        left_keys.append(f"{marker}l{index}")
        right_keys.append(f"{marker}r{index}")
    right = right.reset_index(drop=True)
    for name, out in names.items():
        right[out] = other[name].to_numpy()
    condition = [Call("eq", (Column(a), Column(b))) for a, b in zip(left_keys, right_keys)]
    # The IR's join is SQL's: an empty key matches nothing, on either side.
    tree = Join(Scan("left", tuple((str(c), UNKNOWN) for c in probe.columns)),
                Scan("right", tuple((str(c), UNKNOWN) for c in right.columns)),
                on=condition[0] if len(condition) == 1 else Call("and", tuple(condition)), how=config["how"])
    try:
        joined = pandas_backend.execute(tree, {"left": probe, "right": right})
    except (ValueError, IRError) as exc:
        raise BadRequestError(f"Those columns cannot be matched: {exc}") from exc
    return joined.drop(columns=[c for c in [*left_keys, *right_keys] if c in joined.columns])


_CUSTOMERS = ({"id": 1, "name": "Ann"}, {"id": 2, "name": "Bo"}, {"id": None, "name": "Nobody"})
_declare("join.sql", "Join as SQL does", "Bring the columns of every row of the other dataset whose key columns "
         "equal this row's, exactly as a SQL join: inner, left, right or full, or keep only the rows that match "
         "(semi) or do not (anti). An empty key matches nothing, even another empty key, unless asked to match "
         "each other (as Alteryx's Join does), and the other side's key columns stay as columns of their own.",
         _sql_join_build,
         Example(rows=({"customer": 1}, {"customer": 3}, {"customer": None}),
                 params={"right_dataset_id": EXAMPLE_DATASET, "how": "left", "on": ["customer"],
                         "right_on": ["id"], "bring": ["name"]},
                 column="customer", output="name", expect=("Ann", None, None), other=_CUSTOMERS),
         params=(DATASET, Param("how", "Join", ParamKind.SELECT, required=False, default="inner", options=_HOW),
                 Param("on", "Match on", ParamKind.COLUMNS),
                 Param("right_on", "Their columns", ParamKind.DATASET_COLUMNS),
                 Param("bring", "Columns to bring", ParamKind.DATASET_COLUMNS, required=False, default=[],
                       help="Columns of the other dataset to add to each row; none for semi and anti."),
                 Param("empty_keys", "Empty keys", ParamKind.SELECT, required=False, default="never match",
                       options=_EMPTY_KEYS), SUFFIX),
         synonyms=("sql join", "standard join", "ansi join", "join with nulls", "left outer join", "full outer join"))


# ------------------------------------------------------------------ as of


def _as_of_build(node: Node, params: dict[str, Any]) -> Node:
    require_column(node, params.get("on"))
    by = columns_of(node, params.get("by"), "Match first on")
    right_by = list(params.get("right_by") or [])
    if len(by) != len(right_by):
        raise BadRequestError("Match first on and its columns in the other dataset need the same number of columns.")
    bring = list(params["bring"])
    config = _settings(params, "on", "right_on", "by", "right_by", "direction", "tolerance", "bring", "suffix")
    return extension(node, "join.as_of", config, brought(node, bring, suffix=params.get("suffix") or "_right"))


@handles("join.as_of")
def _as_of(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    other = other_dataset(config)
    on, right_on = config["on"], config["right_on"]
    by, right_by, bring = list(config.get("by") or []), list(config.get("right_by") or []), list(config["bring"])
    require_other_columns(other, [right_on, *right_by, *bring], "Join as of", config)
    left = frame.reset_index(drop=True)
    left_key, right_key, kind = comparable(left[on], other[right_on])
    if kind == "text":
        raise BadRequestError(f"Joining as of needs dates or numbers to compare; {on!r} and {right_on!r} are text.")
    left_by, right_by_keys = _keys(left, other, by, right_by)
    probe = left_by.assign(__key=left_key, __row=np.arange(len(left)))
    table = right_by_keys.assign(__key=right_key)
    for index, name in enumerate(bring):
        table[f"__bring{index}"] = other[name].to_numpy()
    probe = probe[probe["__key"].notna() & probe.drop(columns=["__key", "__row"]).notna().all(axis=1)]
    table = table[table["__key"].notna() & table.drop(columns=["__key"]).iloc[:, :len(by)].notna().all(axis=1)]
    tolerance = config.get("tolerance")
    if tolerance is not None and tolerance != "":
        tolerance = pd.Timedelta(days=float(tolerance)) if kind == "time" else float(tolerance)
    else:
        tolerance = None
    direction = {"earlier": "backward", "later": "forward", "nearest": "nearest"}[config.get("direction") or "earlier"]
    keys = [f"__k{i}" for i in range(len(by))]
    if len(probe) and len(table):
        if kind == "number":
            probe["__key"] = probe["__key"].astype(float)
            table["__key"] = table["__key"].astype(float)
        matched = pd.merge_asof(probe.sort_values("__key", kind="stable"), table.sort_values("__key", kind="stable"),
                                on="__key", by=keys or None, direction=direction, tolerance=tolerance,
                                allow_exact_matches=True)
    else:
        matched = probe.assign(**{f"__bring{i}": None for i in range(len(bring))})
    out = left.copy()
    suffix = config.get("suffix") or "_right"
    placed = matched.set_index("__row")
    for index, name in enumerate(bring):
        column = placed[f"__bring{index}"] if f"__bring{index}" in placed else pd.Series(dtype=object)
        out[name if name not in left.columns else f"{name}{suffix}"] = column.reindex(np.arange(len(left))).to_numpy()
    return out


_PRICES = ({"at": "2026-01-01", "rate": 1.10}, {"at": "2026-01-05", "rate": 1.20}, {"at": "2026-01-09", "rate": 1.15})
_declare("join.as_of", "Join to the nearest earlier row", "Bring columns from the other dataset's row that comes "
         "just before (or after, or nearest) this row's date or number, optionally matching other columns first: "
         "the exchange rate in force on the day, the price at the time of the order.", _as_of_build,
         Example(rows=({"day": "2026-01-03", "amount": 10.0}, {"day": "2026-01-05", "amount": 20.0},
                       {"day": "2025-12-30", "amount": 5.0}),
                 params={"right_dataset_id": EXAMPLE_DATASET, "on": "day", "right_on": "at", "bring": ["rate"]},
                 column="day", output="rate", expect=(1.10, 1.20, None), other=_PRICES),
         params=(DATASET, Param("on", "This dataset's date or number", ParamKind.COLUMN),
                 Param("right_on", "The other dataset's date or number", ParamKind.DATASET_COLUMN), BRING,
                 Param("direction", "Which row", ParamKind.SELECT, required=False, default="earlier",
                       options=("earlier", "later", "nearest")),
                 Param("tolerance", "At most this far (days for dates)", ParamKind.NUMBER, required=False,
                       minimum=0),
                 Param("by", "Match first on", ParamKind.COLUMNS, required=False, default=[]),
                 Param("right_by", "Their columns to match", ParamKind.DATASET_COLUMNS, required=False, default=[]),
                 SUFFIX),
         synonyms=("as of join", "asof", "point in time join", "temporal join", "nearest earlier",
                   "rate in force", "effective date", "slowly changing"), row_wise=True)


# ------------------------------------------------------------------ range


def _range_build(node: Node, params: dict[str, Any]) -> Node:
    require_column(node, params.get("value"))
    bring = list(params["bring"])
    config = _settings(params, "value", "right_low", "right_high", "bring", "matches", "unmatched", "suffix")
    schema = brought(node, bring, suffix=params.get("suffix") or "_right")
    return extension(node, "join.range", config, schema)


@handles("join.range")
def _range(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    other = other_dataset(config)
    value, low, high, bring = config["value"], config["right_low"], config["right_high"], list(config["bring"])
    require_other_columns(other, [low, high, *bring], "Join where a value is in a range", config)
    left = frame.reset_index(drop=True)
    values, lows, kind = comparable(left[value], other[low])
    _, highs, kind_high = comparable(left[value], other[high])
    if kind == "text" or kind_high == "text":
        raise BadRequestError("A range join compares dates or numbers.")
    ranges = pd.DataFrame({"low": lows.to_numpy(), "high": highs.to_numpy(), "row": np.arange(len(other))})
    ranges = ranges[ranges["low"].notna() & ranges["high"].notna() & (ranges["low"] <= ranges["high"])]
    ranges = ranges.sort_values(["low", "high", "row"], kind="stable").reset_index(drop=True)
    every = (config.get("matches") or "every match") == "every match"
    pairs: list[tuple[int, int]] = []
    present = values.notna().to_numpy()
    lo, hi, rows = ranges["low"].to_numpy(), ranges["high"].to_numpy(), ranges["row"].to_numpy()
    overlapping = bool(len(ranges) > 1 and (hi[:-1] >= lo[1:]).any())
    data = values.to_numpy()
    if not overlapping:
        # Ranges one after another: the only candidate is the last that starts at or before the value.
        at = np.searchsorted(lo, data[present], side="right") - 1
        for left_row, index in zip(np.flatnonzero(present), at):
            if index >= 0 and data[left_row] <= hi[index]:
                pairs.append((left_row, int(rows[index])))
    else:
        unique = pd.unique(data[present])
        if len(unique) * len(ranges) > 50_000_000:
            raise BadRequestError(
                f"{other_label(config)} has overlapping ranges and there are {len(unique):,} different values to "
                "place, too many to compare here. Make the ranges not overlap, or narrow this dataset first.")
        found: dict[Any, list[int]] = {}
        for item in unique:
            hits = np.flatnonzero((lo <= item) & (hi >= item))
            found[item] = [int(rows[h]) for h in (hits if every else hits[:1])]
        for left_row in np.flatnonzero(present):
            for right_row in found.get(data[left_row], []):
                pairs.append((left_row, right_row))
    matched = pd.DataFrame(pairs, columns=["__left", "__right"])
    keep_unmatched = (config.get("unmatched") or "keep") == "keep"
    suffix = config.get("suffix") or "_right"
    extra = other.iloc[matched["__right"].to_numpy()][bring].reset_index(drop=True) if len(matched) else \
        pd.DataFrame(columns=bring)
    joined = left.iloc[matched["__left"].to_numpy()].reset_index(drop=True)
    joined = pd.concat([joined, rename_brought(extra, left, bring, suffix)], axis=1)
    joined["__order"] = matched["__left"].to_numpy()
    if keep_unmatched:
        missing = sorted(set(range(len(left))) - set(matched["__left"].tolist()))
        rest = left.iloc[missing].reset_index(drop=True)
        rest["__order"] = missing
        joined = pd.concat([joined, rest], ignore_index=True)
    joined = joined.sort_values("__order", kind="stable").drop(columns="__order").reset_index(drop=True)
    return joined[[*left.columns, *[name if name not in left.columns else f"{name}{suffix}" for name in bring]]]


_BANDS = ({"from": 0, "to": 17, "band": "child"}, {"from": 18, "to": 64, "band": "adult"},
          {"from": 65, "to": 130, "band": "senior"})
_declare("join.range", "Join where a value is in a range", "Bring columns from the other dataset's rows whose "
         "range (from a low to a high column, both included) holds this row's value: a price band, an age group, "
         "a fiscal period, a block of IP addresses.", _range_build,
         Example(rows=({"age": 9}, {"age": 40}, {"age": 70}, {"age": None}),
                 params={"right_dataset_id": EXAMPLE_DATASET, "value": "age", "right_low": "from",
                         "right_high": "to", "bring": ["band"]},
                 column="age", output="band", expect=("child", "adult", "senior", None), other=_BANDS),
         params=(DATASET, Param("value", "This dataset's value", ParamKind.COLUMN),
                 Param("right_low", "Their range starts at", ParamKind.DATASET_COLUMN),
                 Param("right_high", "Their range ends at", ParamKind.DATASET_COLUMN), BRING,
                 Param("matches", "When several ranges hold it", ParamKind.SELECT, required=False,
                       default="every match", options=("every match", "first match")),
                 Param("unmatched", "Rows in no range", ParamKind.SELECT, required=False, default="keep",
                       options=("keep", "drop")), SUFFIX),
         synonyms=("range join", "between join", "band", "bucket lookup", "interval join", "ip range"),
         row_wise=True)


# ------------------------------------------------------------------ fuzzy

METHOD = Param("method", "Alike by", ParamKind.SELECT, required=False, default="letters", options=METHODS,
               help="letters: shared letters in order; edits: few typing changes apart; tokens: the same words in "
                    "any order; jaro_winkler: alike from the start; sound: sounds alike (English names).")
THRESHOLD = Param("threshold", "How alike, from 0 to 1", ParamKind.NUMBER, required=False,
                  default=DEFAULT_THRESHOLD, minimum=0, maximum=1)
SUFFIXES = Param("ignore_endings", "Ignore company endings (Ltd, Inc)", ParamKind.BOOLEAN, required=False,
                 default=True)


def _fuzzy_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    bring = list(params["bring"])
    score = params.get("score_column") or f"{column}_match_score"
    config = {**_settings(params, "right_on", "bring", "method", "threshold", "ignore_endings", "unmatched",
                          "suffix"), "column": column, "score_column": score}
    return extension(node, "join.fuzzy", config,
                     brought(node, bring, suffix=params.get("suffix") or "_right", extra={score: FLOAT64}))


@handles("join.fuzzy")
def _fuzzy(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    other = other_dataset(config)
    column, right_on, bring = config["column"], config["right_on"], list(config["bring"])
    require_other_columns(other, [right_on, *bring], "Join on similar text", config)
    drop = bool(config.get("ignore_endings", True))
    left = frame.reset_index(drop=True)
    left_norm = left[column].map(lambda v: None if pd.isna(v) else normalise(v, drop_suffixes=drop))
    right_norm = other[right_on].map(lambda v: None if pd.isna(v) else normalise(v, drop_suffixes=drop))
    first_row: dict[str, int] = {}
    for position, value in enumerate(right_norm):
        if value and value not in first_row:
            first_row[value] = position
    matches = best_matches([v for v in left_norm.dropna()], first_row.keys(),
                           method=config.get("method") or "letters",
                           threshold=float(config.get("threshold") if config.get("threshold") is not None
                                           else DEFAULT_THRESHOLD))
    rows = [first_row[matches[v][0]] if isinstance(v, str) and v in matches else None for v in left_norm]
    scores = [round(matches[v][1], 6) if isinstance(v, str) and v in matches else None for v in left_norm]
    out = left.copy()
    suffix = config.get("suffix") or "_right"
    for name in bring:
        source = other[name].to_numpy(dtype=object)
        out[name if name not in left.columns else f"{name}{suffix}"] = [None if r is None else source[r] for r in rows]
    out[config["score_column"]] = pd.Series(scores, dtype="float64")
    if (config.get("unmatched") or "keep") == "drop":
        out = out[out[config["score_column"]].notna()].reset_index(drop=True)
    return out


_COMPANIES = ({"company": "Acme Limited", "id": 1}, {"company": "Globex Corporation", "id": 2})
_declare("join.fuzzy", "Join on similar text", "Bring columns from the other dataset's row whose text is most "
         "alike, at or above how alike you ask, with the score of the match: names typed differently, spelling "
         "mistakes, words in another order. The same matching the Assistant uses to find duplicates.",
         _fuzzy_build,
         Example(rows=({"customer": "ACME Ltd"}, {"customer": "Globex Corp."}, {"customer": "Initech"}),
                 params={"right_dataset_id": EXAMPLE_DATASET, "right_on": "company", "bring": ["id"]},
                 column="customer", output="id", expect=(1, 2, None), other=_COMPANIES),
         params=(DATASET, Param("right_on", "Their text column", ParamKind.DATASET_COLUMN), BRING, METHOD,
                 THRESHOLD, SUFFIXES,
                 Param("unmatched", "Rows that match nothing", ParamKind.SELECT, required=False, default="keep",
                       options=("keep", "drop")),
                 Param("score_column", "Name of the score column", ParamKind.TEXT, required=False), SUFFIX),
         synonyms=("fuzzy join", "fuzzy match", "approximate join", "similar names", "fuzzy merge", "match names"),
         column_scoped=True, row_wise=True)


# --------------------------------------------------------------- position


def _position_build(node: Node, params: dict[str, Any]) -> Node:
    bring = list(params["bring"])
    return extension(node, "combine.merge_by_position", _settings(params, "bring", "suffix"),
                     brought(node, bring, suffix=params.get("suffix") or "_right"))


@handles("combine.merge_by_position")
def _by_position(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from service_transformations.ir.pandas_backend import warn

    other = other_dataset(config)
    bring = list(config["bring"])
    require_other_columns(other, bring, "Put columns side by side", config)
    left = frame.reset_index(drop=True)
    right = other[bring].reset_index(drop=True)
    if len(right) > len(left):
        warn(f"{other_label(config)} has {len(right) - len(left):,} more rows than this dataset; they were left out.")
    elif len(right) < len(left):
        warn(f"{other_label(config)} has {len(left) - len(right):,} fewer rows than this dataset; those rows are empty.")
    rows = len(left)
    out = left.copy()
    suffix = config.get("suffix") or "_right"
    for name in bring:
        out[name if name not in left.columns else f"{name}{suffix}"] = right[name].reindex(range(rows)).to_numpy()
    return out


_declare("combine.merge_by_position", "Put columns side by side", "Add the other dataset's columns row by row: "
         "its first row beside this one's first, and so on, as pasting columns next to each other does. This "
         "dataset keeps its rows; the run says when the other is longer or shorter.",
         _position_build,
         Example(rows=({"name": "a"}, {"name": "b"}), params={"right_dataset_id": EXAMPLE_DATASET,
                                                               "bring": ["score"]},
                 column="name", output="score", expect=(10, 20), other=({"score": 10}, {"score": 20})),
         params=(DATASET, BRING, SUFFIX),
         synonyms=("merge by position", "side by side", "paste columns", "zip", "horizontal concat", "cbind"))


# ------------------------------------------------------------------- sets


def _set_build(kind: str):
    def build(node: Node, params: dict[str, Any]) -> Node:
        on = columns_of(node, params.get("on"), "Compare on")
        return extension(node, kind, {**_settings(params, "repeats"), "on": on}, dict(node.schema()))

    return build


def _set_handler(keep_matches: bool):
    def handler(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
        other = other_dataset(config)
        left = frame.reset_index(drop=True)
        on = list(config.get("on") or left.columns)
        require_other_columns(other, on, "Compare on", config)
        left_keys, right_keys = _keys(left, other, on, on)
        # As in SQL's INTERSECT and EXCEPT, two empty values are the same here.
        marker = right_keys.astype(object).where(right_keys.notna(), "__empty__").drop_duplicates()
        probe = left_keys.astype(object).where(left_keys.notna(), "__empty__")
        found = probe.merge(marker.assign(__found=True), how="left", on=list(probe.columns))["__found"]
        kept = left[found.notna().to_numpy() == keep_matches]
        if (config.get("repeats") or "remove") == "remove":
            kept = kept.loc[~probe.loc[kept.index].duplicated()]
        return kept.reset_index(drop=True)

    return handler


handles("combine.intersect")(_set_handler(True))
handles("combine.except")(_set_handler(False))

_REPEATS = Param("repeats", "Repeated rows", ParamKind.SELECT, required=False, default="remove",
                 options=("remove", "keep"), help="Remove gives each row once, as SQL's INTERSECT and EXCEPT do.")
_ON = Param("on", "Compare on", ParamKind.COLUMNS, required=False, default=[],
            help="Leave empty to compare every column; the other dataset must have them.")
_declare("combine.intersect", "Keep rows the other dataset also has", "Keep the rows whose values (in every "
         "column, or the ones chosen) the other dataset has too (INTERSECT).", _set_build("combine.intersect"),
         Example(rows=({"id": 1}, {"id": 2}, {"id": 3}, {"id": 2}), params={"right_dataset_id": EXAMPLE_DATASET},
                 column="id", output="id", expect=(2, 3), other=({"id": 2}, {"id": 3}, {"id": 4})),
         params=(DATASET, _ON, _REPEATS), synonyms=("intersect", "in both", "common rows", "overlap"))
_declare("combine.except", "Keep rows the other dataset does not have", "Keep the rows whose values (in every "
         "column, or the ones chosen) the other dataset does not have (EXCEPT).", _set_build("combine.except"),
         Example(rows=({"id": 1}, {"id": 2}, {"id": 1}), params={"right_dataset_id": EXAMPLE_DATASET},
                 column="id", output="id", expect=(1,), other=({"id": 2},)),
         params=(DATASET, _ON, _REPEATS), synonyms=("except", "minus", "difference", "not in", "missing from"))
