"""Sampling and splitting: keep part of the rows, or label which part each is in (E1).

Every random choice takes a seed, so the same rows come out every run (and
in a replay) until the seed is changed; a different seed is a different
sample. A sample keeps the rows in their order. The top rows of each group
is a window tool; splitting a dataset into one recipe per value is in the
Studio's recipe menu.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import INT64, STRING

from service_transformations.ir.nodes import Node
from service_transformations.tools import register
from service_transformations.tools.builders import unique_name
from service_transformations.tools.local import columns_of, extension, handles
from service_transformations.tools.spec import Example, Param, ParamKind, ToolSpec

CATEGORY = "Sampling & splitting"
SEED = Param("seed", "Seed", ParamKind.INTEGER, required=False, default=1, minimum=0)
SHARE = Param("share", "Share of rows", ParamKind.NUMBER, required=False, minimum=0, maximum=1,
              help="From 0 to 1 (0.1 is a tenth). Give this or a number of rows.")
COUNT = Param("count", "Or this many rows", ParamKind.INTEGER, required=False, minimum=0)
_TEN = tuple({"n": n, "g": "a" if n <= 6 else "b"} for n in range(1, 11))


def _declare(name: str, title: str, summary: str, build, example: Example, *, params: tuple[Param, ...] = (),
             synonyms: tuple[str, ...] = (), null_answer: bool = True) -> ToolSpec:
    return register(ToolSpec(
        name=name, title=title, category=CATEGORY, summary=summary, build=build, example=example, params=params,
        synonyms=synonyms, column_scoped=False, local_only=True, null_answer=null_answer, warns_lost=False,
    ))


def _keep(name: str, keys: tuple[str, ...], columns: tuple[str, ...] = ()):
    def build(node: Node, params: dict[str, Any]) -> Node:
        for key in columns:
            value = params.get(key)
            if value:
                columns_of(node, value if isinstance(value, list) else [value], "Column")
        return extension(node, name, {key: params.get(key) for key in (*keys, *columns)}, dict(node.schema()))

    return build


def _label(name: str, keys: tuple[str, ...], default: str, columns: tuple[str, ...] = ()):
    def build(node: Node, params: dict[str, Any]) -> Node:
        for key in columns:
            value = params.get(key)
            if value:
                columns_of(node, value if isinstance(value, list) else [value], "Column")
        into = (params.get("into") or "").strip() or unique_name(node, default)
        if into in node.schema():
            raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
        kind = INT64 if name == "sample.split_into_parts" else STRING
        return extension(node, name, {**{key: params.get(key) for key in (*keys, *columns)}, "into": into},
                         {**node.schema(), into: kind})

    return build


def _size(rows: int, config: dict[str, Any]) -> int:
    if config.get("count") is not None and config.get("count") != "":
        return min(int(config["count"]), rows)
    if config.get("share") is None or config.get("share") == "":
        raise BadRequestError("Give a share of rows or a number of rows.")
    return int(round(float(config["share"]) * rows))


def _rng(config: dict[str, Any]) -> np.random.Generator:
    return np.random.default_rng(int(config.get("seed") or 1))


def _in_order(frame: pd.DataFrame, positions) -> pd.DataFrame:
    return frame.iloc[sorted(int(p) for p in positions)].reset_index(drop=True)


@handles("sample.random")
def _random(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    size = _size(len(frame), config)
    return _in_order(frame, _rng(config).choice(len(frame), size=size, replace=False))


_declare("sample.random", "Random sample", "Keep a random share (or number) of the rows, the same ones every run "
         "for the same seed.", _keep("sample.random", ("share", "count", "seed")),
         Example(rows=_TEN, params={"count": 3}, column="n", output="n", expect=(4, 5, 8)),
         params=(SHARE, COUNT, SEED), synonyms=("random sample", "sample", "subset", "random rows"))


@handles("sample.stratified")
def _stratified(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rng = _rng(config)
    keep: list[int] = []
    for _, part in frame.reset_index(drop=True).groupby(config["by"], dropna=False, sort=True):
        size = _size(len(part), config)
        keep.extend(part.index[rng.choice(len(part), size=size, replace=False)])
    return _in_order(frame, keep)


_declare("sample.stratified", "Sample each group alike", "Keep the same share (or number) of rows from every group, "
         "so small groups are not lost from the sample.", _keep("sample.stratified", ("share", "count", "seed"),
                                                               ("by",)),
         Example(rows=_TEN, params={"by": "g", "share": 0.5}, column="n", output="n", expect=(2, 3, 5, 7, 10)),
         params=(Param("by", "Groups in", ParamKind.COLUMN), SHARE, COUNT, SEED),
         synonyms=("stratified sample", "stratify", "proportional sample", "sample by group"))


@handles("sample.systematic")
def _systematic(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    step = int(config.get("every") or 10)
    start = int(config.get("start") or 1)
    return frame.iloc[start - 1::step].reset_index(drop=True)


_declare("sample.systematic", "Every nth row", "Keep every nth row, starting from a given row.",
         _keep("sample.systematic", ("every", "start")),
         Example(rows=_TEN, params={"every": 3, "start": 2}, column="n", output="n", expect=(2, 5, 8)),
         params=(Param("every", "Every", ParamKind.INTEGER, default=10, minimum=1),
                 Param("start", "Starting at row", ParamKind.INTEGER, required=False, default=1, minimum=1)),
         synonyms=("systematic sample", "every nth row", "every other row", "interval sample"))


@handles("sample.cluster")
def _cluster(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    groups = sorted(frame[config["by"]].dropna().astype(str).unique())
    take = min(int(config.get("groups") or 1), len(groups))
    chosen = set(_rng(config).choice(groups, size=take, replace=False)) if groups else set()
    return frame[frame[config["by"]].astype(str).isin(chosen) & frame[config["by"]].notna()].reset_index(drop=True)


_declare("sample.cluster", "Sample whole groups", "Choose some groups at random and keep all their rows (cluster "
         "sampling: a few shops, every sale in each).", _keep("sample.cluster", ("groups", "seed"), ("by",)),
         Example(rows=_TEN, params={"by": "g", "groups": 1}, column="n", output="n", expect=(1, 2, 3, 4, 5, 6)),
         params=(Param("by", "Groups in", ParamKind.COLUMN),
                 Param("groups", "Groups to keep", ParamKind.INTEGER, default=1, minimum=1), SEED),
         synonyms=("cluster sample", "sample groups", "random groups"))


@handles("sample.reservoir")
def _reservoir(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    size = int(config.get("count") or 0)
    rng = _rng(config)
    kept: list[int] = []
    # Algorithm R: one pass, each row kept with the chance a sample of this size gives it.
    for position in range(len(frame)):
        if position < size:
            kept.append(position)
        else:
            slot = int(rng.integers(0, position + 1))
            if slot < size:
                kept[slot] = position
    return _in_order(frame, kept)


_declare("sample.reservoir", "Sample a fixed number in one pass", "Keep exactly this many rows, each row as likely "
         "as any other, in one pass over the data (reservoir sampling, for when the total is not known first).",
         _keep("sample.reservoir", ("count", "seed")),
         Example(rows=_TEN, params={"count": 3}, column="n", output="n", expect=(5, 8, 9)),
         params=(Param("count", "Rows", ParamKind.INTEGER, default=100, minimum=0), SEED),
         synonyms=("reservoir sample", "fixed size sample", "streaming sample", "algorithm r"))


@handles("sample.balanced")
def _balanced(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rng = _rng(config)
    work = frame.reset_index(drop=True)
    groups = [part for _, part in work.groupby(config["by"], dropna=True, sort=True)]
    if not groups:
        return work.iloc[0:0]
    size = min(len(part) for part in groups)
    keep: list[int] = []
    for part in groups:
        keep.extend(part.index[rng.choice(len(part), size=size, replace=False)])
    return _in_order(work, keep)


_declare("sample.balanced", "Balance the groups", "Keep the same number of rows of every value of a column, as many "
         "as the smallest group has (for a model that would otherwise learn the commonest answer).",
         _keep("sample.balanced", ("seed",), ("by",)),
         Example(rows=_TEN, params={"by": "g"}, column="n", output="n", expect=(2, 3, 4, 6, 7, 8, 9, 10)),
         params=(Param("by", "Balance", ParamKind.COLUMN), SEED),
         synonyms=("balanced sample", "undersample", "class balance", "equal groups"))


# ------------------------------------------------------------------- labels


@handles("sample.train_test")
def _train_test(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    share = float(config.get("test_share") if config.get("test_share") is not None else 0.2)
    rng = _rng(config)
    labels = np.array(["train"] * len(frame), dtype=object)
    work = frame.reset_index(drop=True)
    groups = ([part.index for _, part in work.groupby(config["by"], dropna=False, sort=True)]
              if config.get("by") else [work.index])
    for index in groups:
        size = int(round(share * len(index)))
        labels[rng.choice(np.asarray(index), size=size, replace=False)] = "test"
    out = frame.copy()
    out[config["into"]] = labels
    return out


_declare("sample.train_test", "Split into training and test rows", "Label each row train or test at random, a share "
         "in test, optionally the same share within each value of a column (stratified).",
         _label("sample.train_test", ("test_share", "seed"), "split", ("by",)),
         Example(rows=_TEN[:5], params={"test_share": 0.4}, column="n", output="split",
                 expect=("train", "test", "test", "train", "train")),
         params=(Param("test_share", "Share for testing", ParamKind.NUMBER, default=0.2, minimum=0, maximum=1),
                 Param("by", "Keep the share in each", ParamKind.COLUMN, required=False), SEED,
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("train test split", "holdout", "validation split", "split data"))


@handles("sample.time_split")
def _time_split(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    stamps = pd.to_datetime(frame[config["column"]], errors="coerce", format="mixed")
    if config.get("cutoff"):
        cutoff = pd.to_datetime(config["cutoff"], errors="coerce")
        if pd.isna(cutoff):
            raise BadRequestError(f"{config['cutoff']!r} is not a date.")
    else:
        share = float(config.get("test_share") if config.get("test_share") is not None else 0.2)
        cutoff = stamps.quantile(1 - share) if stamps.notna().any() else None
    labels = [None if pd.isna(stamp) or cutoff is None else ("test" if stamp > cutoff else "train") for stamp in stamps]
    out = frame.copy()
    out[config["into"]] = labels
    return out


_declare("sample.time_split", "Split by time", "Label rows after a date (or the latest share of them) test and the "
         "rest train, so a model is judged on data from after what it learnt from.",
         _label("sample.time_split", ("cutoff", "test_share"), "split", ("column",)),
         Example(rows=tuple({"d": f"2026-01-0{i}"} for i in range(1, 6)), params={"column": "d",
                                                                              "cutoff": "2026-01-03"},
                 column="d", output="split", expect=("train", "train", "train", "test", "test")),
         params=(Param("column", "Date column", ParamKind.COLUMN),
                 Param("cutoff", "After", ParamKind.TEXT, required=False, default="", placeholder="2026-06-30"),
                 Param("test_share", "Or the latest share", ParamKind.NUMBER, required=False, default=0.2, minimum=0,
                       maximum=1),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("time based split", "temporal split", "out of time", "backtest split"))


@handles("sample.split_by_condition")
def _by_condition(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from service_transformations.formula.parser import parse_formula
    from service_transformations.ir.pandas_backend import evaluate

    holds = evaluate(parse_formula(config["formula"], columns=[str(c) for c in frame.columns]), frame)
    matched = holds.astype("boolean").fillna(False).astype(bool)
    out = frame.copy()
    out[config["into"]] = np.where(matched, config.get("then") or "yes", config.get("otherwise") or "no")
    return out


_declare("sample.split_by_condition", "Label rows by a condition", "Label each row by whether a formula holds for "
         "it, with words of your choosing (big and small orders), to filter or deliver each part separately.",
         _label("sample.split_by_condition", ("formula", "then", "otherwise"), "part"),
         Example(rows=({"amount": 5}, {"amount": 50}), params={"formula": "[amount] > 10", "then": "big",
                                                              "otherwise": "small"},
                 column="amount", output="part", expect=("small", "big")),
         params=(Param("formula", "Condition", ParamKind.TEXT, placeholder="[amount] > 100"),
                 Param("then", "When it holds", ParamKind.TEXT, required=False, default="yes"),
                 Param("otherwise", "Otherwise", ParamKind.TEXT, required=False, default="no"),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("split by condition", "partition by rule", "label rows", "segment by rule"))


@handles("sample.split_into_parts")
def _parts(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    parts = int(config.get("parts") or 2)
    rows = len(frame)
    if (config.get("how") or "in order") == "in turn":
        labels = np.arange(rows) % parts + 1
    else:
        size = math.ceil(rows / parts) if rows else 1
        labels = np.arange(rows) // size + 1
    out = frame.copy()
    out[config["into"]] = labels.astype(np.int64)
    return out


_declare("sample.split_into_parts", "Number the rows into parts", "Number each row 1 to N to split the data into N "
         "parts: in order (the first rows are part 1) or in turn (1, 2, 3, 1, 2, 3).",
         _label("sample.split_into_parts", ("parts", "how"), "part"),
         Example(rows=_TEN[:6], params={"parts": 3, "how": "in turn"}, column="n", output="part",
                 expect=(1, 2, 3, 1, 2, 3)),
         params=(Param("parts", "Parts", ParamKind.INTEGER, default=2, minimum=1, maximum=10_000),
                 Param("how", "Rows go", ParamKind.SELECT, required=False, default="in order",
                       options=("in order", "in turn")),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("split into n parts", "chunks", "batches", "partition rows", "round robin"))

