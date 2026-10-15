"""Statistics: describe, test, regress and decompose (E1).

A statistical tool answers with a small table (one row per variable, per
term, per lag), or adds a column to every row (an outlier flag, a fitted
value, a trend). Every answer says its **method**, its statistic, its
p-value or confidence where it has one, and in words what that means at the
level asked, following the Phase 06 rule that a result which cannot explain
itself is not shown. scipy and statsmodels do the arithmetic; nothing here
calls a language model.

These run here: none is a row-wise expression a database could be given.
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import BOOLEAN, FLOAT64, INT64, STRING, PWType

from service_transformations.ir.nodes import Node
from service_transformations.tools import register
from service_transformations.tools.builders import require_column, unique_name
from service_transformations.tools.local import columns_of, extension, handles
from service_transformations.tools.spec import Accepts, Example, Param, ParamKind, ToolSpec

CATEGORY = "Statistics"
LEVEL = Param("level", "Significance level", ParamKind.NUMBER, required=False, default=0.05, minimum=0.0001,
              maximum=0.5, help="0.05 means 5%: how unlikely a result must be by chance to count.")

_RESULT = {"test": STRING, "statistic": FLOAT64, "p_value": FLOAT64, "n": INT64, "conclusion": STRING}


def _declare(name: str, title: str, summary: str, build, example: Example, *, params: tuple[Param, ...] = (),
             synonyms: tuple[str, ...] = (), column_scoped: bool = False, accepts: Accepts = Accepts.ANY,
             adds_rows: bool = False, dynamic_columns: bool = False, null_answer: bool = True,
             category: str = CATEGORY, describes: bool | None = None) -> ToolSpec:
    return register(ToolSpec(
        name=name, title=title, category=category, summary=summary, build=build, example=example, params=params,
        synonyms=synonyms, accepts=accepts, column_scoped=column_scoped, local_only=True, adds_rows=adds_rows,
        dynamic_columns=dynamic_columns, null_answer=null_answer, warns_lost=False,
        describes=(not column_scoped) if describes is None else describes,
    ))


def _table(name: str, schema: dict[str, PWType], *, keys: tuple[str, ...] = (), columns: tuple[str, ...] = ()):
    """A tool whose answer is a table of its own: the build checks the columns named."""

    def build(node: Node, params: dict[str, Any]) -> Node:
        for key in columns:
            value = params.get(key)
            if value:
                columns_of(node, value if isinstance(value, list) else [value], "Columns")
        config = {key: params.get(key) for key in (*keys, *columns)}
        if "columns" in columns and not params.get("columns"):
            config["columns"] = [n for n, t in node.schema().items() if t.is_numeric]
        return extension(node, name, config, dict(schema))

    return build


def _numbers(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def _verdict(p: float | None, level: float, rejects: str, keeps: str) -> str:
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return "Too few values to test."
    return (f"p = {p:.3g}, below {level:g}: {rejects}" if p < level
            else f"p = {p:.3g}, not below {level:g}: {keeps}")


def _result(test: str, statistic: float | None, p: float | None, n: int, conclusion: str) -> pd.DataFrame:
    return pd.DataFrame([{"test": test, "statistic": statistic, "p_value": p, "n": n, "conclusion": conclusion}],
                        columns=list(_RESULT))


def _level(config: dict[str, Any]) -> float:
    return float(config.get("level") or 0.05)


def _quiet(fn):
    import warnings

    def run(*args, **kwargs):
        # Recorded rather than filtered: statsmodels sets its own filters while
        # it fits, which would otherwise let "failed to converge" through. The
        # tool says how good its fit is in words; these add nothing.
        with warnings.catch_warnings(record=True), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            return fn(*args, **kwargs)

    return run


# ------------------------------------------------------------------ describe

_DESCRIBE = {"column": STRING, "count": INT64, "empty": INT64, "distinct": INT64, "mean": FLOAT64, "std": FLOAT64,
             "min": STRING, "q1": FLOAT64, "median": FLOAT64, "q3": FLOAT64, "max": STRING, "commonest": STRING}


@handles("stats.describe")
@_quiet
def _describe(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for name in config.get("columns") or list(frame.columns):
        values = frame[name]
        present = values.dropna()
        numbers = pd.to_numeric(present, errors="coerce")
        numeric = len(present) > 0 and numbers.notna().all() and not pd.api.types.is_bool_dtype(present)
        common = present.astype(str).value_counts()
        rows.append({
            "column": str(name), "count": int(len(present)), "empty": int(values.isna().sum()),
            "distinct": int(present.nunique()),
            "mean": float(numbers.mean()) if numeric else None, "std": float(numbers.std()) if numeric else None,
            "min": None if present.empty else str(numbers.min() if numeric else present.astype(str).min()),
            "q1": float(numbers.quantile(0.25)) if numeric else None,
            "median": float(numbers.median()) if numeric else None,
            "q3": float(numbers.quantile(0.75)) if numeric else None,
            "max": None if present.empty else str(numbers.max() if numeric else present.astype(str).max()),
            "commonest": str(common.index[0]) if len(common) else None,
        })
    return pd.DataFrame(rows, columns=list(_DESCRIBE))


def _describe_build(node: Node, params: dict[str, Any]) -> Node:
    columns = columns_of(node, params.get("columns"), "Columns") or list(node.schema())
    return extension(node, "stats.describe", {"columns": columns}, dict(_DESCRIBE))


_declare("stats.describe", "Describe the columns", "One row per column: how many values and empty ones, how many "
         "different, and for numbers the mean, spread, lowest, quartiles, median and highest; the commonest value "
         "for every column.", _describe_build,
         Example(rows=({"v": 1}, {"v": 2}, {"v": 3}, {"v": None}), column="v", output="median", expect=(2.0,)),
         params=(Param("columns", "Columns", ParamKind.COLUMNS, required=False, default=[]),),
         synonyms=("describe", "summary statistics", "profile", "mean median", "statistics summary"))


# ----------------------------------------------------------------- matrices


def _matrix_build(kind: str):
    def build(node: Node, params: dict[str, Any]) -> Node:
        columns = columns_of(node, params.get("columns"), "Columns") or [
            name for name, type_ in node.schema().items() if type_.is_numeric or not type_.is_known]
        if len(columns) < 2:
            raise BadRequestError("Choose at least two number columns.")
        schema = {"variable": STRING, **{name: FLOAT64 for name in columns}}
        return extension(node, f"stats.{kind}_matrix", {"columns": columns, "method": params.get("method")}, schema)

    return build


def _matrix(kind: str):
    @_quiet
    def handler(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
        columns = list(config["columns"])
        numbers = frame[columns].apply(pd.to_numeric, errors="coerce")
        table = numbers.corr(method=config.get("method") or "pearson") if kind == "correlation" else numbers.cov()
        table = table.reindex(index=columns, columns=columns)
        return table.reset_index(names="variable")

    return handler


handles("stats.correlation_matrix")(_matrix("correlation"))
handles("stats.covariance_matrix")(_matrix("covariance"))
_PAIRS = ({"a": 1, "b": 2, "c": 9}, {"a": 2, "b": 4, "c": 1}, {"a": 3, "b": 6, "c": 5})
_declare("stats.correlation_matrix", "Correlation matrix", "How closely every pair of number columns moves "
         "together, from -1 to 1, by Pearson (straight-line), Spearman (rank) or Kendall's tau.",
         _matrix_build("correlation"),
         Example(rows=_PAIRS, params={"columns": ["a", "b"]}, column="a", output="b", expect=(1.0, 1.0)),
         params=(Param("columns", "Columns", ParamKind.COLUMNS, required=False, default=[]),
                 Param("method", "Method", ParamKind.SELECT, required=False, default="pearson",
                       options=("pearson", "spearman", "kendall"))),
         synonyms=("correlation matrix", "correlations", "pearson", "spearman", "corr"))
_declare("stats.covariance_matrix", "Covariance matrix", "The covariance of every pair of number columns (sample, "
         "n - 1).", _matrix_build("covariance"),
         Example(rows=_PAIRS, params={"columns": ["a", "b"]}, column="a", output="a", expect=(1.0, 2.0)),
         params=(Param("columns", "Columns", ParamKind.COLUMNS, required=False, default=[]),),
         synonyms=("covariance matrix", "covariances", "cov"))


# --------------------------------------------------------- shape of values

_HISTOGRAM = {"bin_start": FLOAT64, "bin_end": FLOAT64, "count": INT64}


@handles("stats.histogram")
@_quiet
def _histogram(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    values = _numbers(frame, config["column"])
    if values.empty:
        return pd.DataFrame(columns=list(_HISTOGRAM))
    bins = int(config.get("bins") or 10)
    counts, edges = np.histogram(values, bins=bins)
    return pd.DataFrame({"bin_start": edges[:-1], "bin_end": edges[1:], "count": counts.astype(np.int64)})


_declare("stats.histogram", "Histogram", "Count the values in equal-width bins between the lowest and highest "
         "(the last bin includes the highest).", _table("stats.histogram", _HISTOGRAM, keys=("bins",),
                                                       columns=("column",)),
         Example(rows=tuple({"v": v} for v in (1, 2, 2, 3, 4)), params={"column": "v", "bins": 3}, column="v",
                 output="count", expect=(1, 2, 2)),
         params=(Param("column", "Column", ParamKind.COLUMN),
                 Param("bins", "Bins", ParamKind.INTEGER, default=10, minimum=1, maximum=1000)),
         synonyms=("histogram", "distribution", "bins", "frequency distribution"))

_FREQUENCY = {"value": STRING, "count": INT64, "share": FLOAT64, "cumulative_share": FLOAT64}


@handles("stats.frequency")
def _frequency(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    values = frame[config["column"]].map(lambda v: "(empty)" if pd.isna(v) else str(v))
    counts = values.value_counts()
    counts = counts.sort_index(kind="stable").sort_values(ascending=False, kind="stable")
    share = counts / counts.sum() if len(counts) else counts
    return pd.DataFrame({"value": counts.index, "count": counts.to_numpy(np.int64), "share": share.to_numpy(),
                         "cumulative_share": share.cumsum().to_numpy()})


_declare("stats.frequency", "Frequency table", "How often each value appears, commonest first, with its share and "
         "the running share.", _table("stats.frequency", _FREQUENCY, columns=("column",)),
         Example(rows=({"v": "a"}, {"v": "b"}, {"v": "a"}, {"v": None}), params={"column": "v"}, column="v",
                 output="count", expect=(2, 1, 1)),
         params=(Param("column", "Column", ParamKind.COLUMN),),
         synonyms=("frequency table", "value counts", "counts", "tally", "pareto"))


# ---------------------------------------------------------------- outliers


def _outlier_build(kind: str):
    def build(node: Node, params: dict[str, Any]) -> Node:
        column = require_column(node, params.get("column"))
        into = (params.get("into") or "").strip() or unique_name(node, f"{column}_outlier")
        if into in node.schema():
            raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
        return extension(node, f"stats.outliers_{kind}", {"column": column, "into": into,
                                                          "factor": params.get("factor")},
                         {**node.schema(), into: BOOLEAN})

    return build


def _outliers(kind: str):
    @_quiet
    def handler(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
        from service_transformations.ir.pandas_backend import warn

        values = pd.to_numeric(frame[config["column"]], errors="coerce")
        present = values.dropna()
        factor = float(config.get("factor") or {"iqr": 1.5, "zscore": 3.0, "mad": 3.5}[kind])
        if present.empty:
            flags = pd.Series(np.nan, index=frame.index)
        elif kind == "iqr":
            q1, q3 = present.quantile(0.25), present.quantile(0.75)
            spread = q3 - q1
            flags = (values < q1 - factor * spread) | (values > q3 + factor * spread)
        elif kind == "zscore":
            std = present.std()
            flags = ((values - present.mean()).abs() / std > factor) if std else values * 0 > 1
        else:
            median = present.median()
            mad = (present - median).abs().median()
            # 0.6745: the median absolute deviation of a normal is 0.6745 standard deviations.
            flags = (0.6745 * (values - median).abs() / mad > factor) if mad else values * 0 > 1
        out = frame.copy()
        flags = pd.Series(flags, index=frame.index).astype("boolean")
        flags[values.isna()] = pd.NA
        out[config["into"]] = flags
        method = {"iqr": f"outside {factor:g} times the interquartile range",
                  "zscore": f"more than {factor:g} standard deviations from the mean",
                  "mad": f"a modified z-score above {factor:g} (median absolute deviation)"}[kind]
        warn(f"{int(flags.sum()):,} values of {config['column']} are outliers: {method}.")
        return out

    return handler


for _kind, _title, _summary, _factor, _syn in (
    ("iqr", "Find outliers by the middle half", "True for values more than 1.5 times the interquartile range below "
     "the lower quartile or above the upper (Tukey's fences).", 1.5, ("outliers iqr", "tukey", "box plot outliers")),
    ("zscore", "Find outliers by standard deviations", "True for values more than 3 standard deviations from the "
     "mean (suits values that are roughly normal).", 3.0, ("outliers z score", "z score outliers", "3 sigma")),
    ("mad", "Find outliers by median deviation", "True for values whose modified z-score, from the median absolute "
     "deviation, is above 3.5 (robust to the outliers themselves).", 3.5, ("outliers mad", "robust outliers",
                                                                         "median absolute deviation")),
):
    handles(f"stats.outliers_{_kind}")(_outliers(_kind))
    _declare(f"stats.outliers_{_kind}", _title, _summary, _outlier_build(_kind),
             Example(rows=tuple({"v": v} for v in (10, 11, 12, 11, 10, 12, 11, 95)), column="v", output="v_outlier",
                     expect=(False,) * 7 + (True,) if _kind != "zscore" else (False,) * 8,
                     params={} if _kind != "zscore" else {"factor": 3}),
             params=(Param("factor", "Factor", ParamKind.NUMBER, required=False, default=_factor, minimum=0),
                     Param("into", "New column", ParamKind.TEXT, required=False, default="")),
             synonyms=(*_syn, "anomalies", "outlier detection"), column_scoped=True, accepts=Accepts.NUMERIC)


def _forest_build(node: Node, params: dict[str, Any]) -> Node:
    columns = columns_of(node, params.get("columns"), "Columns") or [
        name for name, type_ in node.schema().items() if type_.is_numeric or not type_.is_known]
    if not columns:
        raise BadRequestError("Choose the number columns to look at.")
    flag = (params.get("into") or "").strip() or unique_name(node, "outlier")
    score = f"{flag}_score"
    return extension(node, "stats.outliers_isolation_forest",
                     {"columns": columns, "into": flag, "score": score, "share": params.get("share"),
                      "seed": params.get("seed")},
                     {**node.schema(), flag: BOOLEAN, score: FLOAT64})


@handles("stats.outliers_isolation_forest")
@_quiet
def _forest(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from sklearn.ensemble import IsolationForest

    from service_transformations.ir.pandas_backend import warn

    out = frame.copy()
    numbers = frame[list(config["columns"])].apply(pd.to_numeric, errors="coerce")
    usable = numbers.notna().all(axis=1)
    out[config["into"]] = pd.array([pd.NA] * len(frame), dtype="boolean")
    out[config["score"]] = np.nan
    if usable.sum() < 2:
        return out
    share = config.get("share")
    model = IsolationForest(contamination=float(share) if share else "auto", random_state=int(config.get("seed") or 1),
                            n_estimators=100)
    rows = numbers[usable].to_numpy()
    flags = model.fit_predict(rows) == -1
    scores = -model.score_samples(rows)
    out.loc[usable, config["into"]] = flags
    out.loc[usable, config["score"]] = scores
    warn(f"{int(flags.sum()):,} of {int(usable.sum()):,} rows are outliers by an isolation forest of 100 trees "
         f"(seed {int(config.get('seed') or 1)}); the score is higher the easier a row is to isolate.")
    return out


_declare("stats.outliers_isolation_forest", "Find unusual rows", "True for rows that an isolation forest separates "
         "from the rest quickly, looking at several number columns at once; a score says how unusual each is.",
         _forest_build,
         Example(rows=tuple({"a": a, "b": b} for a, b in ((1, 1), (1.1, 0.9), (0.9, 1.1), (1, 1.05), (9, 9))),
                 params={"share": 0.2}, column="a", output="outlier", expect=(False, False, False, False, True)),
         params=(Param("columns", "Columns", ParamKind.COLUMNS, required=False, default=[]),
                 Param("share", "Share expected to be unusual", ParamKind.NUMBER, required=False, minimum=0.001,
                       maximum=0.5),
                 Param("seed", "Seed", ParamKind.INTEGER, required=False, default=1, minimum=0),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("isolation forest", "anomaly detection", "multivariate outliers", "unusual rows"), describes=False)


# ------------------------------------------------------------------- tests


def _test_tool(name: str, title: str, summary: str, run: Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame],
               example: Example, params: tuple[Param, ...], synonyms: tuple[str, ...], columns: tuple[str, ...]):
    handles(name)(_quiet(run))
    keys = tuple(param.key for param in params if param.key not in columns)
    _declare(name, title, summary, _table(name, _RESULT, keys=keys, columns=columns), example,
             params=(*params, LEVEL) if "level" not in keys else params, synonyms=synonyms)


def _normality(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from scipy import stats

    values = _numbers(frame, config["column"])
    if len(values) < 3:
        return _result("Shapiro-Wilk", None, None, len(values), _verdict(None, _level(config), "", ""))
    if len(values) <= 5000:
        statistic, p = stats.shapiro(values)
        test = "Shapiro-Wilk"
    else:
        statistic, p = stats.normaltest(values)
        test = "D'Agostino-Pearson"
    return _result(test, float(statistic), float(p), len(values), _verdict(
        float(p), _level(config), "the values are unlikely to come from a normal distribution.",
        "nothing says the values are not normal."))


_GROUPS = Param("by", "Groups in", ParamKind.COLUMN, required=False,
                help="A column with two groups to compare; leave empty to compare with a value.")
_test_tool("stats.normality", "Test for a normal distribution", "Test whether the values could come from a normal "
           "distribution: Shapiro-Wilk, or D'Agostino-Pearson past 5,000 values.", _normality,
           Example(rows=tuple({"v": v} for v in (2.1, 1.9, 2.0, 2.2, 1.8, 2.05, 1.95)), params={"column": "v"},
                   column="v", output="test", expect=("Shapiro-Wilk",)),
           (Param("column", "Column", ParamKind.COLUMN),), ("normality test", "shapiro wilk", "is it normal",
                                                            "gaussian test"), ("column",))


def _two_groups(frame: pd.DataFrame, column: str, by: str) -> tuple[pd.Series, pd.Series, list[str]] | None:
    """The two groups' values, or None when the data has fewer than two (too few to test)."""
    groups = [g for g in pd.unique(frame[by].dropna())]
    if len(groups) < 2:
        return None
    if len(groups) > 2:
        raise BadRequestError(f"{by} has {len(groups)} groups; comparing two groups needs exactly two. For more, "
                              "compare means with ANOVA.")
    names = sorted(groups, key=str)
    values = pd.to_numeric(frame[column], errors="coerce")
    return values[frame[by] == names[0]].dropna(), values[frame[by] == names[1]].dropna(), [str(n) for n in names]


def _t_test(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from scipy import stats

    if config.get("by"):
        found = _two_groups(frame, config["column"], config["by"])
        if found is None:
            return _result("Welch's two-sample t-test", None, None, 0, "Needs two groups with values.")
        first, second, names = found
        statistic, p = stats.ttest_ind(first, second, equal_var=False)
        return _result("Welch's two-sample t-test", float(statistic), float(p), len(first) + len(second), _verdict(
            float(p), _level(config), f"the mean of {config['column']} differs between {names[0]} and {names[1]}.",
            f"no difference in mean between {names[0]} and {names[1]} is shown."))
    values = _numbers(frame, config["column"])
    target = float(config.get("value") or 0)
    statistic, p = stats.ttest_1samp(values, target) if len(values) > 1 else (np.nan, np.nan)
    return _result("one-sample t-test", float(statistic), float(p), len(values), _verdict(
        float(p), _level(config), f"the mean differs from {target:g}.", f"no difference from {target:g} is shown."))


_test_tool("stats.t_test", "Compare means (t-test)", "Test whether the mean differs from a value (one-sample), or "
           "between two groups (Welch's two-sample, not assuming equal spreads).", _t_test,
           Example(rows=tuple({"v": v, "g": g} for v, g in ((5, "a"), (6, "a"), (7, "a"), (15, "b"), (16, "b"),
                                                          (17, "b"))),
                   params={"column": "v", "by": "g"}, column="v", output="test",
                   expect=("Welch's two-sample t-test",)),
           (Param("column", "Column", ParamKind.COLUMN), _GROUPS,
            Param("value", "Or compare with", ParamKind.NUMBER, required=False, default=0)),
           ("t test", "ttest", "compare means", "student t", "welch", "significance test"), ("column", "by"))


def _paired(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from scipy import stats

    pair = frame[[config["column"], config["other"]]].apply(pd.to_numeric, errors="coerce").dropna()
    statistic, p = stats.ttest_rel(pair.iloc[:, 0], pair.iloc[:, 1]) if len(pair) > 1 else (np.nan, np.nan)
    return _result("paired t-test", float(statistic), float(p), len(pair), _verdict(
        float(p), _level(config), f"{config['column']} and {config['other']} differ on average.",
        "no average difference between them is shown."))


_test_tool("stats.paired_t_test", "Compare before and after (paired t-test)", "Test whether two columns measured on the "
           "same rows (before and after) differ on average.", _paired,
           Example(rows=tuple({"before": b, "after": a} for b, a in ((10, 12), (11, 14), (9, 11), (12, 15))),
                   params={"column": "before", "other": "after"}, column="before", output="test",
                   expect=("paired t-test",)),
           (Param("column", "Column", ParamKind.COLUMN), Param("other", "Paired with", ParamKind.COLUMN)),
           ("paired t test", "before after", "dependent t test", "repeated measures"), ("column", "other"))


def _anova(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from scipy import stats

    values = pd.to_numeric(frame[config["column"]], errors="coerce")
    groups = [values[frame[config["by"]] == g].dropna() for g in pd.unique(frame[config["by"]].dropna())]
    groups = [g for g in groups if len(g)]
    if len(groups) < 2:
        return _result("one-way ANOVA", None, None, int(values.notna().sum()), "Needs at least two groups.")
    statistic, p = stats.f_oneway(*groups)
    return _result("one-way ANOVA", float(statistic), float(p), sum(len(g) for g in groups), _verdict(
        float(p), _level(config), f"the mean of {config['column']} is not the same in every group.",
        "no difference in mean between the groups is shown."))


_test_tool("stats.anova", "Compare means of several groups (ANOVA)", "Test whether the mean is the same in every group "
           "(one-way analysis of variance).", _anova,
           Example(rows=tuple({"v": v, "g": g} for v, g in ((1, "a"), (2, "a"), (5, "b"), (6, "b"), (9, "c"),
                                                          (10, "c"))),
                   params={"column": "v", "by": "g"}, column="v", output="test", expect=("one-way ANOVA",)),
           (Param("column", "Column", ParamKind.COLUMN), Param("by", "Groups in", ParamKind.COLUMN)),
           ("anova", "f test", "analysis of variance", "compare groups"), ("column", "by"))


def _chi_square(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from scipy import stats

    table = pd.crosstab(frame[config["column"]], frame[config["other"]])
    if table.shape[0] < 2 or table.shape[1] < 2:
        return _result("chi-square test of independence", None, None, int(table.values.sum()),
                       "Needs at least two values in each column.")
    statistic, p, _, _ = stats.chi2_contingency(table)
    return _result("chi-square test of independence", float(statistic), float(p), int(table.values.sum()), _verdict(
        float(p), _level(config), f"{config['column']} and {config['other']} are related.",
        "no relation between them is shown."))


_test_tool("stats.chi_square", "Test whether two categories are related (chi-square)", "Test whether two columns of "
           "categories are independent, or one tells you something about the other.", _chi_square,
           Example(rows=tuple({"a": a, "b": b} for a, b in (("x", "p"), ("x", "p"), ("y", "q"), ("y", "q"),
                                                          ("x", "q"), ("y", "p"))),
                   params={"column": "a", "other": "b"}, column="a", output="test",
                   expect=("chi-square test of independence",)),
           (Param("column", "Column", ParamKind.COLUMN), Param("other", "And", ParamKind.COLUMN)),
           ("chi square", "chi2", "independence test", "contingency test"), ("column", "other"))


def _mann_whitney(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from scipy import stats

    found = _two_groups(frame, config["column"], config["by"])
    if found is None:
        return _result("Mann-Whitney U", None, None, 0, "Needs two groups with values.")
    first, second, names = found
    statistic, p = stats.mannwhitneyu(first, second, alternative="two-sided") if len(first) and len(second) \
        else (np.nan, np.nan)
    return _result("Mann-Whitney U", float(statistic), float(p), len(first) + len(second), _verdict(
        float(p), _level(config), f"{config['column']} tends to be larger in one of {names[0]} and {names[1]}.",
        "neither group is shown to be larger."))


_test_tool("stats.mann_whitney", "Compare two groups without assuming normal (Mann-Whitney)", "Test whether values in one "
           "group tend to be larger than in the other, by ranks.", _mann_whitney,
           Example(rows=tuple({"v": v, "g": g} for v, g in ((1, "a"), (2, "a"), (3, "a"), (7, "b"), (8, "b"),
                                                          (9, "b"))),
                   params={"column": "v", "by": "g"}, column="v", output="test", expect=("Mann-Whitney U",)),
           (Param("column", "Column", ParamKind.COLUMN), Param("by", "Groups in", ParamKind.COLUMN)),
           ("mann whitney", "wilcoxon rank sum", "u test", "non parametric"), ("column", "by"))


def _ks(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from scipy import stats

    if config.get("by"):
        found = _two_groups(frame, config["column"], config["by"])
        if found is None:
            return _result("two-sample Kolmogorov-Smirnov", None, None, 0, "Needs two groups with values.")
        first, second, names = found
        statistic, p = stats.ks_2samp(first, second)
        return _result("two-sample Kolmogorov-Smirnov", float(statistic), float(p), len(first) + len(second),
                       _verdict(float(p), _level(config), f"{names[0]} and {names[1]} are distributed differently.",
                                "no difference in distribution is shown."))
    values = _numbers(frame, config["column"])
    if len(values) < 2:
        return _result("Kolmogorov-Smirnov against a normal", None, None, len(values), "Too few values to test.")
    statistic, p = stats.kstest(values, "norm", args=(values.mean(), values.std()))
    return _result("Kolmogorov-Smirnov against a normal", float(statistic), float(p), len(values), _verdict(
        float(p), _level(config), "the values are not distributed like a normal with their mean and spread.",
        "nothing says they are not."))


_test_tool("stats.ks_test", "Compare distributions (Kolmogorov-Smirnov)", "Test whether two groups are distributed "
           "alike, or one column like a normal distribution with its own mean and spread.", _ks,
           Example(rows=tuple({"v": v, "g": g} for v, g in ((1, "a"), (2, "a"), (3, "a"), (7, "b"), (8, "b"),
                                                          (9, "b"))),
                   params={"column": "v", "by": "g"}, column="v", output="test",
                   expect=("two-sample Kolmogorov-Smirnov",)),
           (Param("column", "Column", ParamKind.COLUMN), _GROUPS),
           ("kolmogorov smirnov", "ks test", "compare distributions", "goodness of fit"), ("column", "by"))


# ------------------------------------------------------------- regression

_COEFFICIENTS = {"term": STRING, "estimate": FLOAT64, "std_error": FLOAT64, "statistic": FLOAT64,
                 "p_value": FLOAT64, "conclusion": STRING}


def _design(frame: pd.DataFrame, target: str, features: list[str]) -> tuple[pd.Series, pd.DataFrame]:
    data = frame[[target, *features]].apply(pd.to_numeric, errors="coerce").dropna()
    return data[target], data[features]


def _regression(logistic: bool):
    @_quiet
    def handler(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
        import statsmodels.api as sm

        features = list(config["features"])
        y, x = _design(frame, config["target"], features)
        if logistic:
            y = y.astype(float)
            if set(y.unique()) - {0.0, 1.0}:
                raise BadRequestError(f"A logistic regression needs {config['target']} to be 0 or 1 (or true or false).")
        if len(y) <= len(features) + 1:
            return pd.DataFrame(columns=list(_COEFFICIENTS))
        model = (sm.Logit(y, sm.add_constant(x, has_constant="add")).fit(disp=0) if logistic
                 else sm.OLS(y, sm.add_constant(x, has_constant="add")).fit())
        level = _level(config)
        rows = []
        for term in model.params.index:
            p = float(model.pvalues[term])
            label = "intercept" if term == "const" else term
            effect = ("changes the odds of the outcome" if logistic else f"moves {config['target']}")
            rows.append({"term": label, "estimate": float(model.params[term]), "std_error": float(model.bse[term]),
                         "statistic": float(model.tvalues[term]), "p_value": p,
                         "conclusion": (f"{label} {effect} (p {p:.3g} < {level:g})" if p < level and term != "const"
                                        else f"not shown to matter (p {p:.3g})" if term != "const" else "")})
        fit = (f"pseudo R² {model.prsquared:.3f}" if logistic else f"R² {model.rsquared:.3f}")
        rows.append({"term": "fit", "estimate": float(model.prsquared if logistic else model.rsquared),
                     "std_error": None, "statistic": None, "p_value": None,
                     "conclusion": f"{fit} over {int(model.nobs):,} rows ({'logistic' if logistic else 'least squares'})"})
        return pd.DataFrame(rows, columns=list(_COEFFICIENTS))

    return handler


def _regression_build(name: str, *, many: bool):
    def build(node: Node, params: dict[str, Any]) -> Node:
        target = require_column(node, params.get("target"))
        features = columns_of(node, params.get("features") if many else [params.get("feature")], "Explained by")
        if not features or any(not f for f in features):
            raise BadRequestError("Choose the columns that explain it.")
        return extension(node, name, {"target": target, "features": features, "level": params.get("level")},
                         dict(_COEFFICIENTS))

    return build


handles("stats.linear_regression")(_regression(False))
handles("stats.multiple_regression")(_regression(False))
handles("stats.logistic_regression")(_regression(True))
_LINE = tuple({"x": x, "y": 2 * x + 1 + e} for x, e in ((1, 0.1), (2, -0.1), (3, 0.05), (4, 0.0), (5, -0.05)))
_declare("stats.linear_regression", "Fit a straight line", "How one number column moves with another: the "
         "intercept and slope by least squares, their standard errors and p-values, and R².",
         _regression_build("stats.linear_regression", many=False),
         Example(rows=_LINE, params={"target": "y", "feature": "x"}, column="x", output="term",
                 expect=("intercept", "x", "fit")),
         params=(Param("target", "Explain", ParamKind.COLUMN), Param("feature", "By", ParamKind.COLUMN), LEVEL),
         synonyms=("linear regression", "line of best fit", "trend line", "slope", "ols"))
_declare("stats.multiple_regression", "Fit several columns at once", "How one number column moves with several "
         "others together (ordinary least squares), with each one's estimate, standard error and p-value.",
         _regression_build("stats.multiple_regression", many=True),
         Example(rows=tuple({"y": 2 * a + 3 * b, "a": a, "b": b} for a, b in ((1, 2), (2, 1), (3, 5), (4, 3),
                                                                              (5, 4), (6, 1))),
                 params={"target": "y", "features": ["a", "b"]}, column="y", output="term",
                 expect=("intercept", "a", "b", "fit")),
         params=(Param("target", "Explain", ParamKind.COLUMN), Param("features", "By", ParamKind.COLUMNS), LEVEL),
         synonyms=("multiple regression", "multivariate regression", "ols", "drivers"))
_declare("stats.logistic_regression", "Fit a yes-or-no outcome", "How several columns change the odds of a 0-or-1 "
         "outcome (logistic regression by maximum likelihood), with each one's estimate and p-value.",
         _regression_build("stats.logistic_regression", many=True),
         Example(rows=tuple({"won": w, "x": x} for x, w in ((1, 0), (2, 0), (3, 1), (4, 0), (5, 1), (6, 1), (7, 1),
                                                            (2.5, 1), (3.5, 0))),
                 params={"target": "won", "features": ["x"]}, column="x", output="term",
                 expect=("intercept", "x", "fit")),
         params=(Param("target", "Outcome (0 or 1)", ParamKind.COLUMN), Param("features", "By", ParamKind.COLUMNS),
                 LEVEL),
         synonyms=("logistic regression", "logit", "classification model", "odds ratio"))


def _residuals_build(node: Node, params: dict[str, Any]) -> Node:
    target = require_column(node, params.get("target"))
    features = columns_of(node, params.get("features"), "Explained by")
    if not features:
        raise BadRequestError("Choose the columns that explain it.")
    fitted, residual = unique_name(node, f"{target}_fitted"), unique_name(node, f"{target}_residual")
    return extension(node, "stats.residuals", {"target": target, "features": features, "fitted": fitted,
                                               "residual": residual},
                     {**node.schema(), fitted: FLOAT64, residual: FLOAT64})


@handles("stats.residuals")
@_quiet
def _residuals(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    y, x = _design(frame, config["target"], list(config["features"]))
    out = frame.copy()
    out[config["fitted"]] = np.nan
    out[config["residual"]] = np.nan
    if len(y) > len(x.columns) + 1:
        design = np.column_stack([np.ones(len(x)), x.to_numpy()])
        coefficients, *_ = np.linalg.lstsq(design, y.to_numpy(), rcond=None)
        fitted = design @ coefficients
        out.loc[y.index, config["fitted"]] = fitted
        out.loc[y.index, config["residual"]] = y.to_numpy() - fitted
    return out


_declare("stats.residuals", "Add fitted values and residuals", "Fit the column by least squares on others and add, "
         "on every row, the fitted value and the residual (what the fit misses), to look for what it does not "
         "explain.", _residuals_build,
         Example(rows=tuple({"y": y, "x": x} for x, y in ((1, 2), (2, 4), (3, 7))),
                 params={"target": "y", "features": ["x"]}, column="y", output="y_residual",
                 expect=(0.166667, -0.333333, 0.166667)),
         params=(Param("target", "Explain", ParamKind.COLUMN), Param("features", "By", ParamKind.COLUMNS)),
         synonyms=("residual analysis", "residuals", "fitted values", "prediction error"), describes=False)


# ------------------------------------------------------- intervals and sizes

_INTERVAL = {"group": STRING, "n": INT64, "mean": FLOAT64, "lower": FLOAT64, "upper": FLOAT64, "conclusion": STRING}


@handles("stats.confidence_interval")
@_quiet
def _interval(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from scipy import stats

    confidence = float(config.get("confidence") or 0.95)
    by = config.get("by")
    groups = [(None, frame)] if not by else [(key, part) for key, part in frame.groupby(by, dropna=False, sort=True)]
    rows = []
    for key, part in groups:
        values = _numbers(part, config["column"])
        n = len(values)
        mean = float(values.mean()) if n else None
        if n > 1:
            margin = float(stats.t.ppf((1 + confidence) / 2, n - 1) * values.std() / math.sqrt(n))
            lower, upper = mean - margin, mean + margin
            words = f"{confidence:.0%} confident the mean is between {lower:,.4g} and {upper:,.4g}"
        else:
            lower = upper = None
            words = "Needs at least two values."
        rows.append({"group": None if key is None or (not isinstance(key, str) and pd.isna(key)) else str(key),
                     "n": n, "mean": mean, "lower": lower, "upper": upper, "conclusion": words})
    return pd.DataFrame(rows, columns=list(_INTERVAL))


_declare("stats.confidence_interval", "Confidence interval for the mean", "The range the true mean is likely in, "
         "by Student's t, overall or for each group.",
         _table("stats.confidence_interval", _INTERVAL, keys=("confidence",), columns=("column", "by")),
         Example(rows=tuple({"v": v} for v in (10, 12, 11, 13, 9)), params={"column": "v"}, column="v", output="mean",
                 expect=(11.0,)),
         params=(Param("column", "Column", ParamKind.COLUMN), Param("by", "For each", ParamKind.COLUMN, required=False),
                 Param("confidence", "Confidence", ParamKind.NUMBER, required=False, default=0.95, minimum=0.5,
                       maximum=0.999)),
         synonyms=("confidence interval", "margin of error", "error bars", "ci"))

_SIZE = {"sample_size": INT64, "conclusion": STRING}


@handles("stats.sample_size")
def _sample_size(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from scipy import stats

    confidence = float(config.get("confidence") or 0.95)
    margin = float(config.get("margin") or 0.05)
    share = float(config.get("share") if config.get("share") is not None else 0.5)
    z = float(stats.norm.ppf((1 + confidence) / 2))
    n = z * z * share * (1 - share) / (margin * margin)
    population = config.get("population")
    if population:
        n = n / (1 + (n - 1) / float(population))
    size = int(math.ceil(n))
    return pd.DataFrame([{"sample_size": size, "conclusion": (
        f"{size:,} answers give {confidence:.0%} confidence of being within {margin:.1%} of the true share"
        + (f" in a population of {int(population):,}" if population else ""))}], columns=list(_SIZE))


def _size_build(node: Node, params: dict[str, Any]) -> Node:
    return extension(node, "stats.sample_size", {key: params.get(key) for key in ("confidence", "margin", "share",
                                                                                   "population")}, dict(_SIZE))


_declare("stats.sample_size", "How many to sample", "How many responses a survey needs for a margin of error at a "
         "confidence, for a share near the one expected (0.5 when unknown), optionally in a finite population. "
         "Uses no data.", _size_build,
         Example(rows=({"x": 1},), params={"confidence": 0.95, "margin": 0.05}, column="x", output="sample_size",
                 expect=(385,)),
         params=(Param("confidence", "Confidence", ParamKind.NUMBER, default=0.95, minimum=0.5, maximum=0.999),
                 Param("margin", "Margin of error", ParamKind.NUMBER, default=0.05, minimum=0.001, maximum=0.5),
                 Param("share", "Expected share", ParamKind.NUMBER, required=False, default=0.5, minimum=0.001,
                       maximum=0.999),
                 Param("population", "Population", ParamKind.INTEGER, required=False, minimum=1)),
         synonyms=("sample size calculator", "survey size", "how many respondents", "power"), adds_rows=True)


# ------------------------------------------------------------ over time


def _ordered(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    order = config.get("order_by")
    work = frame.reset_index(drop=True)
    if order:
        key = pd.to_datetime(work[order], errors="coerce", format="mixed") if not pd.api.types.is_numeric_dtype(
            work[order]) else work[order]
        work = work.assign(__order=key).sort_values("__order", kind="stable").drop(columns="__order")
    return work


def _decompose_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    if params.get("order_by"):
        require_column(node, params["order_by"])
    names = {part: unique_name(node, f"{column}_{part}") for part in ("trend", "seasonal", "residual")}
    return extension(node, "stats.seasonal_decompose", {"column": column, "order_by": params.get("order_by"),
                                                        "period": params.get("period"), "model": params.get("model"),
                                                        "names": [names[p] for p in ("trend", "seasonal", "residual")]},
                     {**node.schema(), **{name: FLOAT64 for name in names.values()}})


@handles("stats.seasonal_decompose")
@_quiet
def _decompose(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from statsmodels.tsa.seasonal import seasonal_decompose

    work = _ordered(frame, config)
    out = frame.copy()
    for name in config["names"]:
        out[name] = np.nan
    values = pd.to_numeric(work[config["column"]], errors="coerce")
    period = int(config.get("period") or 7)
    usable = values.dropna()
    if len(usable) < 2 * period:
        return out
    result = seasonal_decompose(usable.to_numpy(), model=config.get("model") or "additive", period=period,
                                extrapolate_trend="freq")
    original = work.index[usable.index] if work.index.equals(pd.RangeIndex(len(work))) else usable.index
    positions = frame.reset_index(drop=True).index
    _ = positions
    for name, part in zip(config["names"], (result.trend, result.seasonal, result.resid)):
        placed = pd.Series(part, index=usable.index)
        out.loc[original, name] = placed.to_numpy()
    return out


_declare("stats.seasonal_decompose", "Split into trend and season", "Separate a series, in time order, into its "
         "trend (a centred moving average), its repeating seasonal pattern of the period given, and what is left "
         "(classical decomposition, additive or multiplicative).", _decompose_build,
         Example(rows=tuple({"t": i, "v": 10 + i + (3 if i % 2 else -3)} for i in range(8)),
                 params={"order_by": "t", "period": 2}, column="v", output="v_seasonal",
                 expect=(-3.0, 3.0, -3.0, 3.0, -3.0, 3.0, -3.0, 3.0)),
         params=(Param("order_by", "In the order of", ParamKind.COLUMN, required=False),
                 Param("period", "Season length in rows", ParamKind.INTEGER, default=7, minimum=2, maximum=10_000),
                 Param("model", "Season", ParamKind.SELECT, required=False, default="additive",
                       options=("additive", "multiplicative"))),
         synonyms=("seasonal decompose", "seasonality", "trend", "stl", "decomposition"), column_scoped=True,
         accepts=Accepts.NUMERIC)

_ACF = {"lag": INT64, "autocorrelation": FLOAT64, "lower": FLOAT64, "upper": FLOAT64, "conclusion": STRING}


@handles("stats.autocorrelation")
@_quiet
def _autocorrelation(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from statsmodels.tsa.stattools import acf

    values = pd.to_numeric(_ordered(frame, config)[config["column"]], errors="coerce").dropna()
    lags = int(config.get("lags") or 10)
    if len(values) < 3:
        return pd.DataFrame(columns=list(_ACF))
    lags = min(lags, len(values) - 1)
    found = acf(values.to_numpy(), nlags=lags, fft=False)
    bound = 1.96 / math.sqrt(len(values))
    rows = [{"lag": lag, "autocorrelation": float(found[lag]), "lower": -bound, "upper": bound,
             "conclusion": "beyond chance" if abs(found[lag]) > bound else "within chance"}
            for lag in range(1, lags + 1)]
    return pd.DataFrame(rows, columns=list(_ACF))


_declare("stats.autocorrelation", "Autocorrelation by lag", "How much a series, in time order, resembles itself "
         "this many rows earlier, for each lag, with the 95% band chance alone stays inside.",
         _table("stats.autocorrelation", _ACF, keys=("lags",), columns=("column", "order_by")),
         Example(rows=tuple({"v": v} for v in (1, 3, 1, 3, 1, 3, 1, 3)), params={"column": "v", "lags": 2},
                 column="v", output="lag", expect=(1, 2)),
         params=(Param("column", "Column", ParamKind.COLUMN), Param("order_by", "In the order of", ParamKind.COLUMN,
                                                                     required=False),
                 Param("lags", "Lags", ParamKind.INTEGER, default=10, minimum=1, maximum=1000)),
         synonyms=("autocorrelation", "acf", "serial correlation", "lag correlation"))

_TREND = {"test": STRING, "tau": FLOAT64, "p_value": FLOAT64, "slope_per_row": FLOAT64, "n": INT64,
          "conclusion": STRING}


@handles("stats.trend_test")
@_quiet
def _trend(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from scipy import stats

    values = pd.to_numeric(_ordered(frame, config)[config["column"]], errors="coerce").dropna().to_numpy()
    n = len(values)
    if n < 3:
        return pd.DataFrame([{"test": "Mann-Kendall", "tau": None, "p_value": None, "slope_per_row": None, "n": n,
                              "conclusion": "Too few values to test."}], columns=list(_TREND))
    tau, p = stats.kendalltau(np.arange(n), values)
    slopes = [(values[j] - values[i]) / (j - i) for i in range(n) for j in range(i + 1, min(n, i + 200))]
    slope = float(np.median(slopes))
    level = _level(config)
    direction = "rising" if tau > 0 else "falling"
    words = (f"a {direction} trend (p = {p:.3g} < {level:g}); about {slope:,.4g} a row (Sen's slope)" if p < level
             else f"no trend is shown (p = {p:.3g})")
    return pd.DataFrame([{"test": "Mann-Kendall", "tau": float(tau), "p_value": float(p), "slope_per_row": slope,
                          "n": n, "conclusion": words}], columns=list(_TREND))


_declare("stats.trend_test", "Test for a trend", "Is a series, in time order, rising or falling beyond chance? "
         "The Mann-Kendall test, with Sen's slope for how fast.",
         _table("stats.trend_test", _TREND, keys=("level",), columns=("column", "order_by")),
         Example(rows=tuple({"v": v} for v in (1, 2, 4, 3, 5, 6, 8, 7, 9)), params={"column": "v"}, column="v",
                 output="test", expect=("Mann-Kendall",)),
         params=(Param("column", "Column", ParamKind.COLUMN), Param("order_by", "In the order of", ParamKind.COLUMN,
                                                                     required=False), LEVEL),
         synonyms=("trend test", "mann kendall", "is it increasing", "sen slope"))


def _changes_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    if params.get("order_by"):
        require_column(node, params["order_by"])
    into = (params.get("into") or "").strip() or unique_name(node, f"{column}_segment")
    return extension(node, "stats.changepoints", {"column": column, "order_by": params.get("order_by"), "into": into,
                                                  "most": params.get("most")}, {**node.schema(), into: INT64})


@handles("stats.changepoints")
@_quiet
def _changes(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from service_transformations.ir.pandas_backend import warn

    work = _ordered(frame, config)
    values = pd.to_numeric(work[config["column"]], errors="coerce")
    present = values.dropna()
    data = present.to_numpy(dtype=float)
    most = int(config.get("most") or 5)
    cuts: list[int] = []

    def cost(segment: np.ndarray) -> float:
        return float(((segment - segment.mean()) ** 2).sum()) if len(segment) else 0.0

    # Binary segmentation on the mean, each split kept only when it lowers the
    # cost by more than a BIC penalty: 2 x variance x log(n).
    spread = float(np.var(data)) if len(data) > 1 else 0.0
    penalty = 2 * max(spread, 1e-12) * math.log(max(len(data), 2))
    pending = [(0, len(data))]
    while pending and len(cuts) < most:
        start, end = pending.pop()
        segment = data[start:end]
        if len(segment) < 4:
            continue
        whole = cost(segment)
        best, where = 0.0, None
        for split in range(2, len(segment) - 1):
            gain = whole - cost(segment[:split]) - cost(segment[split:])
            if gain > best:
                best, where = gain, split
        if where is not None and best > penalty:
            cuts.append(start + where)
            pending += [(start, start + where), (start + where, end)]
    cuts.sort()
    numbers = np.searchsorted(cuts, np.arange(len(data)), side="right") + 1
    out = frame.copy()
    segments = pd.Series(pd.NA, index=work.index, dtype="Int64")
    segments.loc[present.index] = numbers
    out[config["into"]] = segments.reindex(frame.reset_index(drop=True).index).to_numpy() \
        if not config.get("order_by") else segments.sort_index().to_numpy()
    warn(f"Found {len(cuts):,} change points in the mean of {config['column']} (binary segmentation, BIC penalty).")
    return out


_declare("stats.changepoints", "Find where the level changes", "Number the stretches of a series, in time order, "
         "between points where its average shifts (binary segmentation with a penalty so noise does not count), "
         "1 for the first stretch.", _changes_build,
         Example(rows=tuple({"v": v} for v in (1, 1.1, 0.9, 1, 5, 5.1, 4.9, 5)), column="v", output="v_segment",
                 expect=(1, 1, 1, 1, 2, 2, 2, 2)),
         params=(Param("order_by", "In the order of", ParamKind.COLUMN, required=False),
                 Param("most", "Most change points", ParamKind.INTEGER, required=False, default=5, minimum=1,
                       maximum=100),
                 Param("into", "New column", ParamKind.TEXT, required=False, default="")),
         synonyms=("changepoint detection", "change point", "level shift", "regime change", "break detection"),
         column_scoped=True, accepts=Accepts.NUMERIC)

_FITS = {"distribution": STRING, "parameters": STRING, "log_likelihood": FLOAT64, "aic": FLOAT64,
         "ks_statistic": FLOAT64, "p_value": FLOAT64, "conclusion": STRING}


@handles("stats.distribution_fit")
@_quiet
def _fit(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from scipy import stats

    values = _numbers(frame, config["column"]).to_numpy(dtype=float)
    if len(values) < 5:
        return pd.DataFrame(columns=list(_FITS))
    candidates = {"normal": stats.norm, "uniform": stats.uniform, "exponential": stats.expon}
    if (values > 0).all():
        candidates.update({"lognormal": stats.lognorm, "gamma": stats.gamma, "weibull": stats.weibull_min})
    rows = []
    for name, family in candidates.items():
        try:
            parameters = family.fit(values, floc=0) if name in ("lognormal", "gamma", "weibull") else family.fit(values)
        except Exception:  # noqa: BLE001 - a family that will not fit is left out, not reported as a fit
            continue
        log_likelihood = float(np.sum(family.logpdf(values, *parameters)))
        if not np.isfinite(log_likelihood):
            continue
        free = len(parameters) - (1 if name in ("lognormal", "gamma", "weibull") else 0)
        statistic, p = stats.kstest(values, family.cdf, args=parameters)
        rows.append({"distribution": name, "parameters": ", ".join(f"{v:.4g}" for v in parameters),
                     "log_likelihood": log_likelihood, "aic": 2 * free - 2 * log_likelihood,
                     "ks_statistic": float(statistic), "p_value": float(p), "conclusion": ""})
    rows.sort(key=lambda row: row["aic"])
    if rows:
        rows[0]["conclusion"] = "fits best (lowest AIC)"
    return pd.DataFrame(rows, columns=list(_FITS))


_declare("stats.distribution_fit", "Fit a distribution", "Which of the normal, uniform, exponential and (for "
         "positive values) lognormal, gamma and Weibull distributions describes the values best, by maximum "
         "likelihood, ranked by AIC, each with a Kolmogorov-Smirnov check.",
         _table("stats.distribution_fit", _FITS, columns=("column",)),
         Example(rows=tuple({"v": v} for v in (1.0, 1.1, 1.3, 1.6, 2.0, 2.6, 3.5, 5.0, 7.1, 10.4)),
                 params={"column": "v"}, column="v", output="conclusion",
                 note="One row per distribution that fits, best (lowest AIC) first."),
         params=(Param("column", "Column", ParamKind.COLUMN),),
         synonyms=("distribution fit", "fit distribution", "which distribution", "maximum likelihood", "aic"))
