"""Deduplication and matching: the same thing written down more than once (E1).

Exact repeats are the remove-duplicates step's (keep the first or the last,
by columns). These are the rest: keep the most complete row, mark and count
repeats, and **fuzzy** matching, which uses `shared_python.matching`, the
code the Assistant's entity resolution uses, so a recipe and the Assistant
give one answer: edit distance, sound (Soundex), tokens, or shared letters,
with blocking stated.

Survivorship and golden records turn each group of matching rows into one,
choosing every column's value by a stated rule.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.matching import DEFAULT_THRESHOLD, METHODS, clusters, normalise
from shared_python.types import BOOLEAN, INT64, STRING

from service_transformations.ir.nodes import Node
from service_transformations.tools import register
from service_transformations.tools.builders import require_column, unique_name
from service_transformations.tools.local import columns_of, extension, handles
from service_transformations.tools.spec import Example, Param, ParamKind, ToolSpec

CATEGORY = "Deduplication & matching"

BY = Param("by", "Repeats share", ParamKind.COLUMNS, required=False, default=[],
           help="The columns that make two rows the same thing; leave empty for every column.")
METHOD = Param("method", "Alike by", ParamKind.SELECT, required=False, default="letters", options=METHODS,
               help="letters: shared letters in order; edits: few typing changes apart; tokens: the same words in "
                    "any order; jaro_winkler: alike from the start; sound: sounds alike (English names).")
THRESHOLD = Param("threshold", "How alike, from 0 to 1", ParamKind.NUMBER, required=False, default=DEFAULT_THRESHOLD,
                  minimum=0, maximum=1)
ENDINGS = Param("ignore_endings", "Ignore company endings (Ltd, Inc)", ParamKind.BOOLEAN, required=False,
                default=True)
RULES = ("most complete", "most recent", "most common", "longest", "first", "last")
RULE = Param("rule", "Keep each column's value from", ParamKind.SELECT, required=False, default="most complete",
             options=RULES, help="most complete: the row with fewest empty values; most recent: the latest by the "
                                 "date column; most common: the value most rows have; longest: the longest text.")
RECENT = Param("recent_by", "Most recent by", ParamKind.COLUMN, required=False,
               help="The date column that decides the most recent, for that rule.")


def _declare(name: str, title: str, summary: str, build, example: Example, *, params: tuple[Param, ...] = (),
             synonyms: tuple[str, ...] = (), column_scoped: bool = False, null_answer: bool = False) -> ToolSpec:
    return register(ToolSpec(
        name=name, title=title, category=CATEGORY, summary=summary, build=build, example=example, params=params,
        synonyms=synonyms, column_scoped=column_scoped, local_only=True, null_answer=null_answer, warns_lost=False,
    ))


def _keys(frame: pd.DataFrame, by: list[str]) -> pd.Series:
    columns = by or list(frame.columns)
    if not columns:
        return pd.Series(np.zeros(len(frame), dtype=np.int64), index=frame.index)
    return frame.groupby(columns, dropna=False, sort=False).ngroup()


def _labels(frame: pd.DataFrame, config: dict[str, Any]) -> pd.Series:
    """A group number for every row: rows whose column is alike share one; empty values are their own."""
    drop = bool(config.get("ignore_endings", True))
    values = frame[config["column"]].map(lambda v: None if pd.isna(v) else normalise(v, drop_suffixes=drop))
    numbered = clusters([v for v in values if v], method=config.get("method") or "letters",
                        threshold=_threshold(config))
    return values.map(lambda v: numbered.get(v) if v else None)


def _threshold(config: dict[str, Any]) -> float:
    value = config.get("threshold")
    return DEFAULT_THRESHOLD if value is None else float(value)


# ----------------------------------------------------------------- exact


def _complete_build(node: Node, params: dict[str, Any]) -> Node:
    return extension(node, "dedupe.keep_most_complete", {"by": columns_of(node, params.get("by"), "Repeats share")},
                     dict(node.schema()))


@handles("dedupe.keep_most_complete")
def _keep_most_complete(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    work = frame.reset_index(drop=True)
    keys = _keys(work, list(config.get("by") or []))
    filled = work.notna().sum(axis=1)
    order = pd.DataFrame({"key": keys, "filled": -filled, "row": np.arange(len(work))}).sort_values(
        ["key", "filled", "row"], kind="stable")
    keep = sorted(order.drop_duplicates("key")["row"].tolist())
    return work.iloc[keep].reset_index(drop=True)


_declare("dedupe.keep_most_complete", "Keep the most complete of repeats", "Of rows that share these columns, keep "
         "the one with the fewest empty values (the first of those that tie).", _complete_build,
         Example(rows=({"id": 1, "phone": None}, {"id": 1, "phone": "0123"}, {"id": 2, "phone": None}),
                 params={"by": ["id"]}, column="id", output="phone", expect=("0123", None)),
         params=(BY,), synonyms=("keep most complete", "best record", "dedupe keep fullest", "most filled"))


def _mark_build(kind: str):
    def build(node: Node, params: dict[str, Any]) -> Node:
        by = columns_of(node, params.get("by"), "Repeats share")
        into = (params.get("into") or "").strip() or unique_name(node, "is_repeat" if kind == "mark" else "repeats")
        if into in node.schema():
            raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
        return extension(node, f"dedupe.{kind}", {"by": by, "into": into},
                         {**node.schema(), into: BOOLEAN if kind == "mark" else INT64})

    return build


@handles("dedupe.mark")
def _mark(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy()
    keys = _keys(frame, list(config.get("by") or []))
    out[config["into"]] = keys.duplicated(keep="first").to_numpy()
    return out


@handles("dedupe.count")
def _count(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy()
    keys = _keys(frame, list(config.get("by") or []))
    out[config["into"]] = keys.map(keys.value_counts()).to_numpy().astype(np.int64) if len(frame) else []
    return out


_INTO = Param("into", "New column", ParamKind.TEXT, required=False, default="")
_declare("dedupe.mark", "Mark repeats", "Add a true or false column that is true on each row repeating an earlier "
         "one in these columns, to look at before removing.", _mark_build("mark"),
         Example(rows=({"id": 1}, {"id": 2}, {"id": 1}), params={"by": ["id"]}, column="id", output="is_repeat",
                 expect=(False, False, True)),
         params=(BY, _INTO), synonyms=("mark duplicates", "flag duplicates", "is duplicate"), null_answer=True)
_declare("dedupe.count", "Count repeats", "Add how many rows share each row's values in these columns (1 for a row "
         "seen once).", _mark_build("count"),
         Example(rows=({"id": 1}, {"id": 2}, {"id": 1}), params={"by": ["id"]}, column="id", output="repeats",
                 expect=(2, 1, 2)),
         params=(BY, _INTO), synonyms=("count duplicates", "duplicate count", "how many times"), null_answer=True)


# ----------------------------------------------------------------- fuzzy


def _fuzzy_build(name: str, *, into_type=None, suffix: str = ""):
    def build(node: Node, params: dict[str, Any]) -> Node:
        column = require_column(node, params.get("column"))
        config = {"column": column, "method": params.get("method"), "threshold": params.get("threshold"),
                  "ignore_endings": params.get("ignore_endings")}
        schema = dict(node.schema())
        if into_type is not None:
            into = (params.get("into") or "").strip() or unique_name(node, f"{column}_{suffix}")
            if into in schema and into != column:
                raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
            schema[into] = schema[column] if into == column else (into_type or STRING)
            config["into"] = into
        return extension(node, name, config, schema)

    return build


@handles("dedupe.fuzzy")
def _fuzzy_dedupe(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from service_transformations.ir.pandas_backend import warn

    labels = _labels(frame, config)
    keep = ~labels.duplicated(keep="first") | labels.isna()
    dropped = int((~keep).sum())
    if dropped:
        warn(f"{dropped:,} rows were alike an earlier row's {config['column']} and were removed "
             f"({config.get('method') or 'letters'}, at least {_threshold(config):g} alike).")
    return frame[keep.to_numpy()].reset_index(drop=True)


@handles("match.cluster")
def _cluster(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy()
    out[config["into"]] = pd.array(_labels(frame, config).tolist(), dtype="Int64")
    return out


@handles("match.canonical")
def _canonical(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    labels = _labels(frame, config)
    values = frame[config["column"]]
    chosen: dict[int, Any] = {}
    for label in labels.dropna().unique():
        members = values[labels == label].dropna().astype(str)
        counts = members.value_counts()
        top = sorted(counts[counts == counts.max()].index)
        chosen[int(label)] = top[0]
    out = frame.copy()
    out[config["into"]] = [None if pd.isna(label) else chosen[int(label)] for label in labels]
    return out


_FUZZY = (METHOD, THRESHOLD, ENDINGS)
_PEOPLE = ({"name": "Acme Ltd"}, {"name": "ACME Limited"}, {"name": "Globex"}, {"name": "Acme Ltd"})
_declare("dedupe.fuzzy", "Remove near repeats", "Remove rows whose value is alike an earlier row's (spelling "
         "mistakes, capitals, Ltd and Limited), keeping the first; the run says how many went.",
         _fuzzy_build("dedupe.fuzzy"),
         Example(rows=_PEOPLE, column="name", output="name", expect=("Acme Ltd", "Globex")),
         params=(Param("column", "Column", ParamKind.COLUMN), *_FUZZY),
         synonyms=("fuzzy dedupe", "fuzzy deduplicate", "near duplicates", "edit distance dedupe", "phonetic dedupe",
                   "token dedupe", "soundex dedupe"))
_declare("match.cluster", "Group alike values", "Number groups of values that are alike, so rows written "
         "differently share a number (empty values have none).", _fuzzy_build("match.cluster", into_type=INT64,
                                                                              suffix="group"),
         Example(rows=_PEOPLE, column="name", output="name_group", expect=(1, 1, 2, 1)),
         params=(*_FUZZY, _INTO), synonyms=("cluster similar values", "group similar", "fuzzy group", "clustering"),
         column_scoped=True)
_declare("match.canonical", "Replace alike values with one spelling", "Write every value of a group of alike values "
         "the way most rows write it (the first in order when they tie).",
         _fuzzy_build("match.canonical", into_type=STRING, suffix="standard"),
         Example(rows=_PEOPLE, params={"into": "name"}, column="name", output="name",
                 expect=("Acme Ltd", "Acme Ltd", "Globex", "Acme Ltd")),
         params=(*_FUZZY, _INTO), synonyms=("merge cluster to canonical", "canonicalise", "standard spelling",
                                            "normalise variants"), column_scoped=True)


# ----------------------------------------------------------- survivorship


def _survive(frame: pd.DataFrame, groups: pd.Series, config: dict[str, Any], skip: set[str]) -> pd.DataFrame:
    rule = config.get("rule") or "most complete"
    recent = config.get("recent_by")
    if rule == "most recent" and not recent:
        raise BadRequestError("Say which date column decides the most recent.")
    work = frame.reset_index(drop=True)
    groups = groups.reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    order = work.notna().sum(axis=1) if rule == "most complete" else None
    stamps = pd.to_datetime(work[recent], errors="coerce", format="mixed") if rule == "most recent" else None
    for label in pd.unique(groups):
        members = work[(groups == label) if not pd.isna(label) else groups.isna()]
        if pd.isna(label):
            rows.extend(members.to_dict("records"))
            continue
        chosen: dict[str, Any] = {}
        if rule in ("most complete", "most recent", "first", "last"):
            if rule == "most complete":
                best = order[members.index].sort_values(ascending=False, kind="stable").index
            elif rule == "most recent":
                best = stamps[members.index].sort_values(ascending=False, kind="stable", na_position="last").index
            else:
                best = members.index if rule == "first" else members.index[::-1]
            for name in work.columns:
                present = [work.at[i, name] for i in best if not pd.isna(work.at[i, name])]
                chosen[name] = present[0] if present else None
        else:
            for name in work.columns:
                present = members[name].dropna()
                if present.empty:
                    chosen[name] = None
                elif rule == "most common":
                    counts = present.astype(str).value_counts()
                    winner = sorted(counts[counts == counts.max()].index)[0]
                    chosen[name] = present[present.astype(str) == winner].iloc[0]
                else:  # longest
                    lengths = present.astype(str).str.len()
                    chosen[name] = present.loc[lengths.sort_values(ascending=False, kind="stable").index[0]]
        rows.append(chosen)
    return pd.DataFrame(rows, columns=list(work.columns)).infer_objects()


def _survivorship_build(node: Node, params: dict[str, Any]) -> Node:
    by = columns_of(node, params.get("by"), "One row for each")
    if not by:
        raise BadRequestError("Say which columns make rows the same thing.")
    if params.get("recent_by"):
        require_column(node, params["recent_by"])
    return extension(node, "match.survivorship", {"by": by, "rule": params.get("rule"),
                                                  "recent_by": params.get("recent_by")}, dict(node.schema()))


@handles("match.survivorship")
def _survivorship(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    groups = _keys(frame, list(config["by"]))
    return _survive(frame, groups, config, set(config["by"]))


_declare("match.survivorship", "Merge repeats into one row", "Make one row from each group of rows that share these "
         "columns, taking every column's value by a rule: from the most complete row, the most recent, the most "
         "common value, the longest, the first or the last (empty values are passed over).", _survivorship_build,
         Example(rows=({"id": 1, "email": None, "phone": "01"}, {"id": 1, "email": "a@x.com", "phone": None},
                       {"id": 2, "email": "b@x.com", "phone": "02"}),
                 params={"by": ["id"], "rule": "first"}, column="id", output="email", expect=("a@x.com", "b@x.com")),
         params=(Param("by", "One row for each", ParamKind.COLUMNS), RULE, RECENT),
         synonyms=("survivorship rules", "merge records", "consolidate", "coalesce duplicates", "collapse rows"))


def _golden_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    if params.get("recent_by"):
        require_column(node, params["recent_by"])
    into = (params.get("into") or "").strip() or unique_name(node, "record")
    schema = {**node.schema(), into: INT64}
    return extension(node, "match.golden_record", {
        "column": column, "into": into, **{key: params.get(key) for key in (
            "method", "threshold", "ignore_endings", "rule", "recent_by")}}, schema)


@handles("match.golden_record")
def _golden(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    if frame.empty:
        out = frame.copy()
        out[config["into"]] = pd.Series(dtype="Int64")
        return out
    labels = _labels(frame, config)
    merged = _survive(frame, labels, config, set())
    ids: list[Any] = []
    for label in pd.unique(labels):
        if pd.isna(label):
            ids.extend([None] * int(labels.isna().sum()))
        else:
            ids.append(int(label))
    merged[config["into"]] = pd.array(ids[: len(merged)], dtype="Int64")
    return merged


_declare("match.golden_record", "Make one record per real thing", "Group rows whose column is alike (the same "
         "matching as Remove near repeats), then make one row per group by a survivorship rule, numbered so each "
         "golden record can be traced.", _golden_build,
         Example(rows=({"name": "Acme Ltd", "city": None}, {"name": "ACME Limited", "city": "Leeds"},
                       {"name": "Globex", "city": "York"}),
                 params={"rule": "most complete"}, column="name", output="city", expect=("Leeds", "York")),
         params=(*_FUZZY, RULE, RECENT, _INTO),
         synonyms=("golden record", "master record", "single customer view", "entity resolution", "mdm"),
         column_scoped=True)
