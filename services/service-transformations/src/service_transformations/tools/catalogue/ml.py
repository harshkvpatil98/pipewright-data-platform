"""Machine learning: cluster, reduce, forecast, impute, classify, encode (E1).

**Where the model lives: in the step.** A model is fitted on the step's input
every time the step runs, with a fixed seed, so a run and its replay give the
same answer; nothing is stored between runs and nothing leaves the
deployment. Every tool says how good its result is, in the run's messages:
a silhouette for clusters, the variance explained by components, a
cross-validated accuracy for a classifier, a backtest error and intervals
for a forecast. scikit-learn and statsmodels do the fitting; no language
model is called.
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.types import BOOLEAN, FLOAT64, INT64, JSON as JSON_TYPE, STRING

from service_transformations.ir.nodes import Node
from service_transformations.ir.pandas_backend import warn
from service_transformations.tools import register
from service_transformations.tools.builders import require_column, unique_name
from service_transformations.tools.local import columns_of, extension, handles
from service_transformations.tools.spec import Accepts, Example, Param, ParamKind, ToolSpec

CATEGORY = "Machine learning"
SEED = Param("seed", "Seed", ParamKind.INTEGER, required=False, default=1, minimum=0)
FEATURES = Param("columns", "Columns", ParamKind.COLUMNS, required=False, default=[],
                 help="Number columns to use; leave empty for every number column.")
SCALE = Param("scale", "Put columns on one scale first", ParamKind.BOOLEAN, required=False, default=True)
MAX_ROWS = 200_000


def _declare(name: str, title: str, summary: str, build, example: Example, *, params: tuple[Param, ...] = (),
             synonyms: tuple[str, ...] = (), column_scoped: bool = False, adds_rows: bool = False,
             dynamic_columns: bool = False, null_answer: bool = True, accepts: Accepts = Accepts.ANY,
             describes: bool = False) -> ToolSpec:
    return register(ToolSpec(
        name=name, title=title, category=CATEGORY, summary=summary, build=build, example=example, params=params,
        synonyms=synonyms, column_scoped=column_scoped, local_only=True, adds_rows=adds_rows,
        dynamic_columns=dynamic_columns, null_answer=null_answer, warns_lost=False, accepts=accepts,
        describes=describes,
    ))


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


def _features(node: Node, params: dict[str, Any]) -> list[str]:
    columns = columns_of(node, params.get("columns"), "Columns") or [
        name for name, type_ in node.schema().items() if type_.is_numeric or not type_.is_known]
    if not columns:
        raise BadRequestError("Choose the number columns to use.")
    return columns


def _matrix(frame: pd.DataFrame, columns: list[str], scale: bool) -> tuple[np.ndarray, pd.Series]:
    if len(frame) > MAX_ROWS:
        raise BadRequestError(f"This works on up to {MAX_ROWS:,} rows; sample or filter first.")
    numbers = frame[columns].apply(pd.to_numeric, errors="coerce")
    usable = numbers.notna().all(axis=1)
    data = numbers[usable].to_numpy(dtype=float)
    if scale and len(data):
        spread = data.std(axis=0)
        data = (data - data.mean(axis=0)) / np.where(spread == 0, 1, spread)
    return data, usable


def _new(node: Node, preferred: str, params: dict[str, Any]) -> str:
    into = (params.get("into") or "").strip() or unique_name(node, preferred)
    if into in node.schema():
        raise BadRequestError(f"Column {into!r} already exists. Choose another name.")
    return into


_INTO = Param("into", "New column", ParamKind.TEXT, required=False, default="")
_BLOBS = tuple({"x": x, "y": y} for x, y in ((1, 1), (1.2, 0.9), (0.8, 1.1), (8, 8), (8.2, 7.9), (7.9, 8.1)))


# --------------------------------------------------------------- clustering


def _cluster_build(name: str):
    def build(node: Node, params: dict[str, Any]) -> Node:
        columns = _features(node, params)
        into = _new(node, "cluster", params)
        keys = ("k", "seed", "scale", "linkage", "distance", "neighbours")
        return extension(node, name, {"columns": columns, "into": into, **{k: params.get(k) for k in keys}},
                         {**node.schema(), into: INT64})

    return build


def _place_clusters(frame: pd.DataFrame, usable: pd.Series, labels: np.ndarray, into: str) -> pd.DataFrame:
    out = frame.copy()
    series = pd.Series(pd.NA, index=frame.index, dtype="Int64")
    if len(labels):
        # Number clusters 1, 2, 3 in the order their first row appears, so the
        # same rows always give the same numbers.
        order: dict[int, int] = {}
        for label in labels:
            if label >= 0 and label not in order:
                order[label] = len(order) + 1
        series.loc[usable[usable].index] = [order.get(label, pd.NA) for label in labels]
    out[into] = series
    return out


def _silhouette(data: np.ndarray, labels: np.ndarray) -> str:
    from sklearn.metrics import silhouette_score

    kept = labels >= 0
    if len(set(labels[kept])) < 2 or kept.sum() < 3:
        return "too few clusters for a silhouette"
    return f"silhouette {silhouette_score(data[kept], labels[kept]):.2f} (1 is well separated, 0 overlapping)"


@handles("ml.kmeans")
@_quiet
def _kmeans(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from sklearn.cluster import KMeans

    data, usable = _matrix(frame, list(config["columns"]), bool(config.get("scale", True)))
    k = int(config.get("k") or 3)
    if len(data) < k:
        return _place_clusters(frame, usable, np.array([], dtype=int), config["into"])
    labels = KMeans(n_clusters=k, n_init=10, random_state=int(config.get("seed") or 1)).fit_predict(data)
    warn(f"k-means with {k} clusters (seed {int(config.get('seed') or 1)}): {_silhouette(data, labels)}.")
    return _place_clusters(frame, usable, labels, config["into"])


_K = Param("k", "Clusters", ParamKind.INTEGER, default=3, minimum=2, maximum=500)
_declare("ml.kmeans", "Group rows by k-means", "Put rows into k clusters of rows alike in the number columns "
         "chosen; the run gives the silhouette (how well separated they are).", _cluster_build("ml.kmeans"),
         Example(rows=_BLOBS, params={"k": 2}, column="x", output="cluster", expect=(1, 1, 1, 2, 2, 2)),
         params=(FEATURES, _K, SCALE, SEED, _INTO),
         synonyms=("k means", "kmeans", "clustering", "segmentation", "segment customers"))


@handles("ml.hierarchical")
@_quiet
def _hierarchical(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from sklearn.cluster import AgglomerativeClustering

    data, usable = _matrix(frame, list(config["columns"]), bool(config.get("scale", True)))
    if len(data) > 20_000:
        raise BadRequestError("Hierarchical clustering compares every pair of rows; it works on up to 20,000.")
    k = int(config.get("k") or 3)
    if len(data) < k:
        return _place_clusters(frame, usable, np.array([], dtype=int), config["into"])
    linkage = config.get("linkage") or "ward"
    labels = AgglomerativeClustering(n_clusters=k, linkage=linkage).fit_predict(data)
    warn(f"Hierarchical clustering ({linkage} linkage) into {k}: {_silhouette(data, labels)}.")
    return _place_clusters(frame, usable, labels, config["into"])


_declare("ml.hierarchical", "Group rows by merging nearest", "Build clusters by merging the nearest rows and groups "
         "step by step (agglomerative), cut at k clusters.", _cluster_build("ml.hierarchical"),
         Example(rows=_BLOBS, params={"k": 2}, column="x", output="cluster", expect=(1, 1, 1, 2, 2, 2)),
         params=(FEATURES, _K, Param("linkage", "Linkage", ParamKind.SELECT, required=False, default="ward",
                                     options=("ward", "average", "complete", "single")), SCALE, _INTO),
         synonyms=("hierarchical clustering", "agglomerative", "dendrogram", "linkage"))


@handles("ml.dbscan")
@_quiet
def _dbscan(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from sklearn.cluster import DBSCAN

    data, usable = _matrix(frame, list(config["columns"]), bool(config.get("scale", True)))
    if not len(data):
        return _place_clusters(frame, usable, np.array([], dtype=int), config["into"])
    labels = DBSCAN(eps=float(config.get("distance") or 0.5), min_samples=int(config.get("neighbours") or 5)).fit_predict(data)
    noise = int((labels == -1).sum())
    warn(f"Density clustering found {len(set(labels) - {-1}):,} clusters; {noise:,} rows are in none (left empty).")
    return _place_clusters(frame, usable, labels, config["into"])


_declare("ml.dbscan", "Group rows by density", "Find clusters of any shape as crowded regions (DBSCAN); rows in "
         "no crowd are left without a cluster.", _cluster_build("ml.dbscan"),
         Example(rows=(*_BLOBS, {"x": 30, "y": -30}), params={"distance": 0.8, "neighbours": 2}, column="x",
                 output="cluster", expect=(1, 1, 1, 2, 2, 2, None)),
         params=(FEATURES, Param("distance", "Neighbourhood size", ParamKind.NUMBER, default=0.5, minimum=0.0001),
                 Param("neighbours", "Rows to make a crowd", ParamKind.INTEGER, default=5, minimum=1), SCALE, _INTO),
         synonyms=("dbscan", "density clustering", "noise detection"))


# --------------------------------------------------------------------- PCA


def _pca_build(node: Node, params: dict[str, Any]) -> Node:
    columns = _features(node, params)
    count = int(params.get("components") or 2)
    if count > len(columns):
        raise BadRequestError(f"There are only {len(columns)} columns, so at most {len(columns)} components.")
    names = [unique_name(node, f"component_{i}") for i in range(1, count + 1)]
    return extension(node, "ml.pca", {"columns": columns, "names": names, "scale": params.get("scale")},
                     {**node.schema(), **{name: FLOAT64 for name in names}})


@handles("ml.pca")
@_quiet
def _pca(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from sklearn.decomposition import PCA

    names = list(config["names"])
    data, usable = _matrix(frame, list(config["columns"]), bool(config.get("scale", True)))
    out = frame.copy()
    for name in names:
        out[name] = np.nan
    if len(data) < 2:
        return out
    model = PCA(n_components=len(names), svd_solver="full")
    projected = model.fit_transform(data)
    # Signs are arbitrary; fix each so its largest weight is positive, so runs agree.
    signs = np.sign(model.components_[np.arange(len(names)), np.abs(model.components_).argmax(axis=1)])
    projected = projected * signs
    for index, name in enumerate(names):
        out.loc[usable, name] = projected[:, index]
    explained = ", ".join(f"{share:.0%}" for share in model.explained_variance_ratio_)
    warn(f"Principal components explain {explained} of the variation ({model.explained_variance_ratio_.sum():.0%} "
         "together).")
    return out


_declare("ml.pca", "Reduce to principal components", "Replace many correlated number columns with a few components "
         "that keep most of their variation (PCA); the run says how much each keeps.", _pca_build,
         Example(rows=tuple({"a": a, "b": 2 * a} for a in (1, 2, 3, 4)), params={"components": 1}, column="a",
                 output="component_1", expect=(-1.897367, -0.632456, 0.632456, 1.897367)),
         params=(FEATURES, Param("components", "Components", ParamKind.INTEGER, default=2, minimum=1, maximum=100),
                 SCALE),
         synonyms=("pca", "principal component analysis", "dimensionality reduction", "reduce dimensions"))


def _anomaly_build(node: Node, params: dict[str, Any]) -> Node:
    columns = _features(node, params)
    into = _new(node, "anomaly_score", params)
    return extension(node, "ml.anomaly_score", {"columns": columns, "into": into, "seed": params.get("seed")},
                     {**node.schema(), into: FLOAT64})


@handles("ml.anomaly_score")
@_quiet
def _anomaly(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from sklearn.ensemble import IsolationForest

    data, usable = _matrix(frame, list(config["columns"]), False)
    out = frame.copy()
    out[config["into"]] = np.nan
    if len(data) < 2:
        return out
    model = IsolationForest(random_state=int(config.get("seed") or 1)).fit(data)
    raw = -model.score_samples(data)
    low, high = raw.min(), raw.max()
    out.loc[usable, config["into"]] = (raw - low) / (high - low) if high > low else 0.0
    warn("Anomaly scores from an isolation forest, from 0 (most ordinary row) to 1 (most unusual).")
    return out


_declare("ml.anomaly_score", "Score how unusual each row is", "A score from 0 (the most ordinary row) to 1 (the "
         "most unusual) from an isolation forest over the number columns.", _anomaly_build,
         Example(rows=(*_BLOBS[:3], {"x": 9, "y": -9}), column="x", output="anomaly_score",
                 note="The last row, far from the others, scores 1."),
         params=(FEATURES, SEED, _INTO), synonyms=("anomaly score", "anomaly detection", "outlier score", "novelty"))


# ---------------------------------------------------------------- forecasts


def _forecast_build(name: str):
    def build(node: Node, params: dict[str, Any]) -> Node:
        column = require_column(node, params.get("column"))
        time = require_column(node, params.get("time"))
        extra = {f"{column}_lower": FLOAT64, f"{column}_upper": FLOAT64, "is_forecast": BOOLEAN}
        for key in extra:
            if key in node.schema():
                raise BadRequestError(f"Column {key!r} already exists; rename it first.")
        keys = ("periods", "period", "trend", "season", "order", "confidence", "every")
        return extension(node, name, {"column": column, "time": time, **{k: params.get(k) for k in keys}},
                         {**node.schema(), **extra})

    return build


def _series(frame: pd.DataFrame, config: dict[str, Any]) -> tuple[pd.Series, str | None, pd.Series]:
    raw = frame[config["time"]]
    # A number column is periods (1, 2, 3), never nanoseconds since 1970.
    numeric_time = pd.api.types.is_numeric_dtype(raw) and not pd.api.types.is_bool_dtype(raw)
    order = raw if numeric_time else pd.to_datetime(raw, errors="coerce", format="mixed")
    values = pd.to_numeric(frame[config["column"]], errors="coerce")
    data = pd.DataFrame({"t": order, "v": values}).dropna().sort_values("t", kind="stable")
    frequency = None
    if not numeric_time and len(data) >= 3:
        frequency = pd.infer_freq(pd.DatetimeIndex(data["t"])) or None
    return data["v"].reset_index(drop=True), frequency, data["t"].reset_index(drop=True)


def _future(times: pd.Series, frequency: str | None, periods: int, every: str | None) -> list[Any]:
    if pd.api.types.is_datetime64_any_dtype(times):
        step = {"day": "D", "week": "W", "month": "MS", "quarter": "QS", "year": "YS"}.get(every or "") or frequency
        if step is None:
            gaps = times.diff().dropna()
            step = gaps.median() if len(gaps) else pd.Timedelta(days=1)
        return list(pd.date_range(times.iloc[-1], periods=periods + 1, freq=step)[1:])
    gap = float(times.diff().dropna().median()) if len(times) > 1 else 1.0
    return [float(times.iloc[-1]) + gap * (i + 1) for i in range(periods)]


def _attach(frame: pd.DataFrame, config: dict[str, Any], fitted: np.ndarray | None, future: list[Any],
            forecast: np.ndarray, lower: np.ndarray, upper: np.ndarray, how: str, backtest: str) -> pd.DataFrame:
    column = config["column"]
    out = frame.copy()
    out[f"{column}_lower"] = np.nan
    out[f"{column}_upper"] = np.nan
    out["is_forecast"] = False
    rows = pd.DataFrame({config["time"]: future, column: forecast, f"{column}_lower": lower,
                         f"{column}_upper": upper, "is_forecast": True})
    out = pd.concat([out, rows], ignore_index=True)
    out["is_forecast"] = out["is_forecast"].astype(bool)
    warn(f"Forecast {len(future):,} periods ahead by {how}; {backtest}. The lower and upper columns are a "
         f"{float(config.get('confidence') or 0.95):.0%} interval.")
    return out[[*frame.columns, f"{column}_lower", f"{column}_upper", "is_forecast"]]


def _backtest(values: pd.Series, fit) -> str:
    held = max(1, min(len(values) // 5, 12))
    if len(values) - held < 4:
        return "too short a history to backtest"
    try:
        predicted = fit(values.iloc[:-held], held)
    except Exception:  # noqa: BLE001 - a backtest that cannot fit is reported, not raised
        return "the backtest could not fit"
    actual = values.iloc[-held:].to_numpy()
    error = np.abs((actual - predicted) / np.where(actual == 0, np.nan, actual))
    mape = float(np.nanmean(error)) if np.isfinite(error).any() else float("nan")
    return f"backtest on the last {held:,} values: mean absolute percentage error {mape:.1%}"


def _forecast(kind: str):
    @_quiet
    def handler(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
        from scipy import stats

        values, frequency, times = _series(frame, config)
        periods = int(config.get("periods") or 6)
        confidence = float(config.get("confidence") or 0.95)
        z = float(stats.norm.ppf((1 + confidence) / 2))
        if len(values) < 4:
            # Too short a history: the rows come back with the forecast's
            # columns empty, and the run says why.
            out = frame.copy()
            for name in (f"{config['column']}_lower", f"{config['column']}_upper"):
                out[name] = np.nan
            out["is_forecast"] = False
            warn(f"A forecast needs at least 4 values of {config['column']} in time order; there are {len(values)}.")
            return out
        period = int(config.get("period") or 0)

        if kind == "arima":
            from statsmodels.tsa.arima.model import ARIMA

            order = tuple(int(part) for part in str(config.get("order") or "1,1,1").split(","))
            if len(order) != 3:
                raise BadRequestError("Write the ARIMA order as p,d,q, such as 1,1,1.")

            def fit(history, steps):
                return ARIMA(history.to_numpy(), order=order).fit().forecast(steps)

            model = ARIMA(values.to_numpy(), order=order).fit()
            predicted = model.get_forecast(periods)
            mean = predicted.predicted_mean
            interval = predicted.conf_int(alpha=1 - confidence)
            lower, upper = interval[:, 0], interval[:, 1]
            how = f"ARIMA{order} (AIC {model.aic:,.1f})"
        elif kind == "smoothing":
            from statsmodels.tsa.holtwinters import ExponentialSmoothing

            trend = None if (config.get("trend") or "add") == "none" else "add"
            season = None if not period or (config.get("season") or "add") == "none" else (config.get("season") or "add")

            def build_model(history):
                use_season = season if season and len(history) >= 2 * period else None
                return ExponentialSmoothing(history.to_numpy(), trend=trend, seasonal=use_season,
                                            seasonal_periods=period if use_season else None).fit()

            def fit(history, steps):
                return build_model(history).forecast(steps)

            model = build_model(values)
            mean = model.forecast(periods)
            spread = float(np.std(values.to_numpy() - model.fittedvalues, ddof=1))
            lower, upper = mean - z * spread * np.sqrt(np.arange(1, periods + 1)), mean + z * spread * np.sqrt(
                np.arange(1, periods + 1))
            how = f"exponential smoothing (Holt-Winters; trend {trend or 'none'}, season {season or 'none'})"
        else:
            def design(index: np.ndarray, length: int) -> np.ndarray:
                columns = [np.ones_like(index, dtype=float), index.astype(float)]
                if period:
                    for harmonic in (1, 2):
                        angle = 2 * math.pi * harmonic * index / period
                        columns += [np.sin(angle), np.cos(angle)]
                return np.column_stack(columns)

            def fit(history, steps):
                index = np.arange(len(history))
                weights, *_ = np.linalg.lstsq(design(index, len(history)), history.to_numpy(), rcond=None)
                return design(np.arange(len(history), len(history) + steps), steps) @ weights

            index = np.arange(len(values))
            weights, *_ = np.linalg.lstsq(design(index, len(values)), values.to_numpy(), rcond=None)
            mean = design(np.arange(len(values), len(values) + periods), periods) @ weights
            residual = values.to_numpy() - design(index, len(values)) @ weights
            spread = float(np.std(residual, ddof=min(len(residual) - 1, 1)))
            lower, upper = mean - z * spread, mean + z * spread
            how = ("a straight-line trend" + (f" plus a season of {period} with two harmonics" if period else "")
                   + " by least squares")
        future = _future(times, frequency, periods, config.get("every"))
        return _attach(frame, config, None, future, np.asarray(mean, dtype=float), np.asarray(lower, dtype=float),
                       np.asarray(upper, dtype=float), how, _backtest(values, fit))

    return handler


_FORECAST = (Param("time", "Time column", ParamKind.COLUMN),
             Param("periods", "Periods ahead", ParamKind.INTEGER, default=6, minimum=1, maximum=10_000),
             Param("confidence", "Interval", ParamKind.NUMBER, required=False, default=0.95, minimum=0.5,
                   maximum=0.999),
             Param("every", "Step between periods", ParamKind.SELECT, required=False, default="",
                   options=("", "day", "week", "month", "quarter", "year"),
                   help="Leave empty to take it from the data."))
_MONTHS = tuple({"month": f"2026-{m:02d}-01", "sales": 100 + 10 * m} for m in range(1, 9))
for _name, _title, _summary, _extra, _syn in (
    ("arima", "Forecast with ARIMA", "Forecast the next periods of a series with an ARIMA model of the order "
     "given (p,d,q), with an interval from the model.",
     (Param("order", "Order p,d,q", ParamKind.TEXT, required=False, default="1,1,1"),),
     ("arima", "forecast arima", "time series forecast", "box jenkins")),
    ("smoothing", "Forecast with exponential smoothing", "Forecast with Holt-Winters exponential smoothing: a "
     "level, a trend and (given its length) a season.",
     (Param("trend", "Trend", ParamKind.SELECT, required=False, default="add", options=("add", "none")),
      Param("season", "Season", ParamKind.SELECT, required=False, default="add", options=("add", "mul", "none")),
      Param("period", "Season length in rows", ParamKind.INTEGER, required=False, default=0, minimum=0)),
     ("exponential smoothing", "holt winters", "ets", "forecast smoothing")),
    ("trend_season", "Forecast a trend and a season", "Forecast with a straight-line trend plus a repeating season "
     "(sines and cosines of its length), fitted by least squares: the additive model Prophet popularised, "
     "without its changepoints.",
     (Param("period", "Season length in rows", ParamKind.INTEGER, required=False, default=0, minimum=0),),
     ("prophet", "prophet style", "trend and seasonality", "forecast trend")),
):
    handles(f"ml.forecast_{_name}")(_forecast(_name))
    _declare(f"ml.forecast_{_name}", _title, _summary, _forecast_build(f"ml.forecast_{_name}"),
             Example(rows=_MONTHS, params={"time": "month", "periods": 2}, column="sales", output="is_forecast",
                     expect=(False,) * 8 + (True, True)),
             params=(*_FORECAST, *_extra), synonyms=(*_syn, "forecast", "predict future", "projection"),
             column_scoped=True, adds_rows=False, accepts=Accepts.NUMERIC)


# ------------------------------------------------------------------- impute


def _impute_build(name: str):
    def build(node: Node, params: dict[str, Any]) -> Node:
        columns = _features(node, params)
        return extension(node, name, {"columns": columns, "neighbours": params.get("neighbours"),
                                      "seed": params.get("seed")}, dict(node.schema()))

    return build


def _impute(kind: str):
    @_quiet
    def handler(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
        columns = list(config["columns"])
        numbers = frame[columns].apply(pd.to_numeric, errors="coerce")
        out = frame.copy()
        if numbers.notna().sum().min() == 0 or len(frame) < 2:
            return out
        if kind == "knn":
            from sklearn.impute import KNNImputer

            filled = KNNImputer(n_neighbors=int(config.get("neighbours") or 5)).fit_transform(numbers)
            how = f"the average of the {int(config.get('neighbours') or 5)} most alike rows"
        else:
            from sklearn.experimental import enable_iterative_imputer  # noqa: F401
            from sklearn.impute import IterativeImputer

            filled = IterativeImputer(random_state=int(config.get("seed") or 1), max_iter=10).fit_transform(numbers)
            how = "a regression on the other columns, repeated until it settles"
        gaps = int(numbers.isna().sum().sum())
        for index, name in enumerate(columns):
            out[name] = filled[:, index]
        warn(f"Filled {gaps:,} empty values from {how}.")
        return out

    return handler


handles("ml.impute_knn")(_impute("knn"))
handles("ml.impute_iterative")(_impute("iterative"))
_GAPS = ({"a": 1.0, "b": 2.0}, {"a": 2.0, "b": 4.0}, {"a": 3.0, "b": None}, {"a": 4.0, "b": 8.0})
_declare("ml.impute_knn", "Fill gaps from alike rows", "Fill an empty number with the average of the rows most "
         "alike in the other columns (k nearest neighbours).", _impute_build("ml.impute_knn"),
         Example(rows=_GAPS, params={"neighbours": 2}, column="a", output="b", expect=(2.0, 4.0, 6.0, 8.0)),
         params=(FEATURES, Param("neighbours", "Rows to average", ParamKind.INTEGER, default=5, minimum=1)),
         synonyms=("knn impute", "nearest neighbour imputation", "fill missing knn"))
_declare("ml.impute_iterative", "Fill gaps by regression", "Fill empty numbers by predicting each column from the "
         "others, round after round until the answers settle (iterative imputation).",
         _impute_build("ml.impute_iterative"),
         Example(rows=_GAPS, column="a", output="b", note="The empty b is predicted from a, about 6."),
         params=(FEATURES, SEED), synonyms=("iterative impute", "mice", "regression imputation"))


# ------------------------------------------------------------- classifiers


def _classify_build(name: str):
    def build(node: Node, params: dict[str, Any]) -> Node:
        target = require_column(node, params.get("target"))
        features = columns_of(node, params.get("columns"), "Using") or [
            n for n, t in node.schema().items() if (t.is_numeric or not t.is_known) and n != target]
        if not features:
            raise BadRequestError("Choose the columns to predict from.")
        predicted = _new(node, f"{target}_predicted", params)
        confidence = unique_name(node, f"{predicted}_confidence")
        return extension(node, name, {"target": target, "columns": features, "into": predicted,
                                      "confidence": confidence, "depth": params.get("depth"),
                                      "seed": params.get("seed")},
                         {**node.schema(), predicted: STRING, confidence: FLOAT64})

    return build


def _classify(kind: str):
    @_quiet
    def handler(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
        from sklearn.model_selection import cross_val_score

        features = list(config["columns"])
        x = frame[features].apply(pd.to_numeric, errors="coerce")
        labels = frame[config["target"]].map(lambda v: None if pd.isna(v) else str(v))
        known = labels.notna() & x.notna().all(axis=1)
        usable = x.notna().all(axis=1)
        out = frame.copy()
        out[config["into"]] = None
        out[config["confidence"]] = np.nan
        if known.sum() < 2 or labels[known].nunique() < 2:
            return out
        if kind == "naive_bayes":
            from sklearn.naive_bayes import GaussianNB

            model = GaussianNB()
            how = "Gaussian naive Bayes"
        else:
            from sklearn.tree import DecisionTreeClassifier

            model = DecisionTreeClassifier(max_depth=int(config.get("depth") or 4),
                                           random_state=int(config.get("seed") or 1))
            how = f"a decision tree of depth at most {int(config.get('depth') or 4)}"
        model.fit(x[known], labels[known])
        out.loc[usable, config["into"]] = model.predict(x[usable])
        out.loc[usable, config["confidence"]] = model.predict_proba(x[usable]).max(axis=1)
        folds = min(5, int(labels[known].value_counts().min()))
        if folds >= 2:
            accuracy = cross_val_score(model, x[known], labels[known], cv=folds).mean()
            score = f"cross-validated accuracy {accuracy:.0%} over {folds} folds"
        else:
            score = "too few rows of each label to cross-validate"
        extra = ""
        if kind == "decision_tree":
            ranked = sorted(zip(features, model.feature_importances_), key=lambda pair: -pair[1])
            extra = "; it relies most on " + ", ".join(f"{name} ({share:.0%})" for name, share in ranked[:3])
        warn(f"Predicted {config['target']} for {int(usable.sum()):,} rows by {how}, learnt from the "
             f"{int(known.sum()):,} that have it: {score}{extra}.")
        return out

    return handler


handles("ml.naive_bayes")(_classify("naive_bayes"))
handles("ml.decision_tree")(_classify("decision_tree"))
_LABELLED = tuple({"size": s, "weight": w, "kind": k} for s, w, k in (
    (1, 1, "small"), (1.2, 1.1, "small"), (0.9, 1, "small"), (5, 5, "big"), (5.5, 4.8, "big"), (4.9, 5.2, "big"),
    (1.1, 0.9, None), (5.1, 5, None)))
_TARGET = Param("target", "Predict", ParamKind.COLUMN, help="Rows that have it teach the model; every row is predicted.")
_USING = Param("columns", "Using", ParamKind.COLUMNS, required=False, default=[])
_declare("ml.naive_bayes", "Predict a label (naive Bayes)", "Learn a label from the rows that have it, using number "
         "columns, and predict it for every row, with how sure (Gaussian naive Bayes); the run gives the "
         "cross-validated accuracy.", _classify_build("ml.naive_bayes"),
         Example(rows=_LABELLED, params={"target": "kind", "columns": ["size", "weight"]}, column="size",
                 output="kind_predicted", expect=("small",) * 3 + ("big",) * 3 + ("small", "big")),
         params=(_TARGET, _USING, _INTO), synonyms=("naive bayes", "classify", "classification", "predict category"))
_declare("ml.decision_tree", "Predict a label (decision tree)", "Learn a label from the rows that have it with a "
         "decision tree of limited depth, predict it for every row, and say which columns it relies on.",
         _classify_build("ml.decision_tree"),
         Example(rows=_LABELLED, params={"target": "kind", "columns": ["size", "weight"]}, column="size",
                 output="kind_predicted", expect=("small",) * 3 + ("big",) * 3 + ("small", "big")),
         params=(_TARGET, _USING, Param("depth", "Most levels", ParamKind.INTEGER, required=False, default=4,
                                        minimum=1, maximum=30), SEED, _INTO),
         synonyms=("decision tree", "classification tree", "cart", "predict label"))

_IMPORTANCE = {"feature": STRING, "importance": FLOAT64, "method": STRING}


@handles("ml.feature_importance")
@_quiet
def _importance(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    from sklearn.inspection import permutation_importance

    features = list(config["columns"])
    data = frame[[config["target"], *features]].copy()
    data[features] = data[features].apply(pd.to_numeric, errors="coerce")
    data = data.dropna()
    if len(data) < 5:
        return pd.DataFrame(columns=list(_IMPORTANCE))
    target = data[config["target"]]
    numeric = pd.to_numeric(target, errors="coerce").notna().all() and target.nunique() > 10
    seed = int(config.get("seed") or 1)
    model = (RandomForestRegressor if numeric else RandomForestClassifier)(n_estimators=100, random_state=seed)
    y = pd.to_numeric(target) if numeric else target.astype(str)
    model.fit(data[features], y)
    result = permutation_importance(model, data[features], y, n_repeats=5, random_state=seed)
    rows = [{"feature": name, "importance": float(score),
             "method": f"permutation importance of a random forest {'regressor' if numeric else 'classifier'}"}
            for name, score in zip(features, result.importances_mean)]
    rows.sort(key=lambda row: -row["importance"])
    return pd.DataFrame(rows, columns=list(_IMPORTANCE))


def _importance_build(node: Node, params: dict[str, Any]) -> Node:
    target = require_column(node, params.get("target"))
    features = columns_of(node, params.get("columns"), "Using") or [
        n for n, t in node.schema().items() if (t.is_numeric or not t.is_known) and n != target]
    if not features:
        raise BadRequestError("Choose the columns to weigh.")
    return extension(node, "ml.feature_importance", {"target": target, "columns": features, "seed": params.get("seed")},
                     dict(_IMPORTANCE))


_declare("ml.feature_importance", "Which columns matter most", "How much each column helps predict another: how "
         "much worse a random forest does when that column is shuffled (permutation importance).", _importance_build,
         Example(rows=tuple({"y": 3 * a, "a": a, "noise": (a * 7) % 5} for a in range(12)),
                 params={"target": "y", "columns": ["a", "noise"]}, column="y", output="feature",
                 expect=("a", "noise")),
         params=(Param("target", "Predict", ParamKind.COLUMN), _USING, SEED),
         synonyms=("feature importance", "drivers", "what matters", "variable importance", "key drivers"),
         describes=True)


# ---------------------------------------------------------------- encoders


def _one_hot_build(node: Node, params: dict[str, Any]) -> Node:
    column = require_column(node, params.get("column"))
    return extension(node, "ml.one_hot", {"column": column, "most": params.get("most"),
                                          "drop": params.get("drop")}, None)


@handles("ml.one_hot")
def _one_hot(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    column = config["column"]
    values = frame[column].map(lambda v: None if pd.isna(v) else str(v))
    distinct = sorted(values.dropna().unique())
    most = int(config.get("most") or 100)
    if len(distinct) > most:
        raise BadRequestError(f"{column} has {len(distinct):,} different values, more than {most:,} columns.")
    out = frame.drop(columns=[column]) if config.get("drop") else frame.copy()
    for value in distinct:
        name = f"{column}_{value}"
        out[name if name not in out.columns else f"{name}_2"] = (values == value).astype(np.int64).where(
            values.notna()).astype("Int64")
    return out


_declare("ml.one_hot", "One column per value (one-hot)", "Turn a column of categories into one 0-or-1 column for "
         "each value, for a model that needs numbers.", _one_hot_build,
         Example(rows=({"c": "red"}, {"c": "blue"}, {"c": "red"}), column="c", output="c_red", expect=(1, 0, 1)),
         params=(Param("most", "At most this many columns", ParamKind.INTEGER, required=False, default=100, minimum=1),
                 Param("drop", "Drop the original", ParamKind.BOOLEAN, required=False, default=False)),
         synonyms=("one hot encode", "dummy variables", "indicator columns", "get dummies"), column_scoped=True,
         dynamic_columns=True)


def _ordinal(series: pd.Series, config: dict[str, Any]) -> list[Any]:
    order = [str(item) for item in config.get("order") or []]
    distinct = order or sorted({str(v) for v in series.dropna()})
    codes = {value: index for index, value in enumerate(distinct, start=1)}
    return [None if pd.isna(v) else codes.get(str(v)) for v in series]


def _target_encode(frame: pd.DataFrame, config: dict[str, Any]) -> list[Any]:
    target = pd.to_numeric(frame[config["target"]], errors="coerce")
    categories = frame[config["column"]].map(lambda v: None if pd.isna(v) else str(v))
    overall = target.mean()
    weight = float(config.get("smoothing") if config.get("smoothing") is not None else 10)
    stats_ = pd.DataFrame({"c": categories, "t": target}).dropna().groupby("c")["t"].agg(["mean", "count"])
    smoothed = (stats_["mean"] * stats_["count"] + overall * weight) / (stats_["count"] + weight)
    return [None if c is None else float(smoothed.get(c, overall)) for c in categories]


from service_transformations.tools.local import column_extension  # noqa: E402

_declare("ml.ordinal", "Number the categories", "Give each category a number: in the order you list, or "
         "alphabetical (for a model that needs numbers and an order that means something).",
         column_extension("ml.ordinal", INT64, _ordinal, keys=("order",)),
         Example(rows=({"size": "M"}, {"size": "S"}, {"size": "L"}), params={"order": ["S", "M", "L"]}, column="size",
                 output="size", expect=(2, 1, 3)),
         params=(Param("order", "In order", ParamKind.LIST, required=False, default=[]),),
         synonyms=("ordinal encode", "label encode", "category codes", "rank categories"), column_scoped=True)


def _target_build(node: Node, params: dict[str, Any]) -> Node:
    require_column(node, params.get("target"))
    return column_extension("ml.target_encode", FLOAT64, _target_encode, keys=("target", "smoothing"),
                            frame_aware=True)(node, params)


_declare("ml.target_encode", "Replace categories with their average outcome", "Replace each category with the "
         "average of a target column for it, pulled towards the overall average when it has few rows (smoothing), "
         "for a model that needs numbers.", _target_build,
         Example(rows=({"c": "a", "y": 1}, {"c": "a", "y": 3}, {"c": "b", "y": 10}), params={"target": "y",
                                                                                         "smoothing": 0},
                 column="c", output="c", expect=(2.0, 2.0, 10.0)),
         params=(Param("target", "Outcome", ParamKind.COLUMN),
                 Param("smoothing", "Smoothing", ParamKind.NUMBER, required=False, default=10, minimum=0)),
         synonyms=("target encode", "mean encoding", "likelihood encoding"), column_scoped=True)


def _tfidf(series: pd.Series, config: dict[str, Any]) -> list[Any]:
    from sklearn.feature_extraction.text import TfidfVectorizer

    present = series.dropna().astype(str)
    out: list[Any] = [None] * len(series)
    if present.empty or not present.str.strip().astype(bool).any():
        return out
    vectoriser = TfidfVectorizer(max_features=5000)
    try:
        weights = vectoriser.fit_transform(present)
    except ValueError:  # every value was only stop words or punctuation
        return out
    terms = np.array(vectoriser.get_feature_names_out())
    top = int(config.get("terms") or 5)
    positions = {index: position for position, index in enumerate(present.index)}
    for index, position in positions.items():
        row = weights[position].toarray().ravel()
        best = row.argsort()[::-1][:top]
        found = {str(terms[i]): round(float(row[i]), 4) for i in best if row[i] > 0}
        out[series.index.get_loc(index)] = json.dumps(found)
    return out


_declare("ml.tfidf", "Key words of each text (TF-IDF)", "For each text, the words that set it apart from the rest "
         "(term frequency times inverse document frequency), as a JSON object of word to weight.",
         column_extension("ml.tfidf", JSON_TYPE, _tfidf, keys=("terms",)),
         Example(rows=({"t": "red apple"}, {"t": "green apple"}), params={"terms": 1}, column="t", output="t",
                 expect=('{"red": 0.8148}', '{"green": 0.8148}')),
         params=(Param("terms", "Words per text", ParamKind.INTEGER, default=5, minimum=1, maximum=100),),
         synonyms=("tfidf", "tf idf", "text vectorise", "keywords", "bag of words"), column_scoped=True,
         accepts=Accepts.TEXTUAL)

_SIMILAR = {"row": INT64, "other_row": INT64, "similarity": FLOAT64}


@handles("ml.similarity_matrix")
@_quiet
def _similarity(frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from sklearn.metrics.pairwise import cosine_similarity

    if len(frame) > 5000:
        raise BadRequestError("A similarity table compares every pair; it works on up to 5,000 rows.")
    columns = list(config["columns"])
    if len(columns) == 1 and not pd.api.types.is_numeric_dtype(frame[columns[0]]):
        from sklearn.feature_extraction.text import TfidfVectorizer

        texts = frame[columns[0]].fillna("").astype(str)
        if not texts.str.strip().astype(bool).any():
            return pd.DataFrame(columns=list(_SIMILAR))
        matrix = cosine_similarity(TfidfVectorizer().fit_transform(texts))
    else:
        numbers = frame[columns].apply(pd.to_numeric, errors="coerce").fillna(0).to_numpy()
        if not len(numbers):
            return pd.DataFrame(columns=list(_SIMILAR))
        matrix = cosine_similarity(numbers)
    top = int(config.get("top") or 3)
    rows = []
    for i in range(len(matrix)):
        others = [j for j in np.argsort(-matrix[i], kind="stable") if j != i][:top]
        rows.extend({"row": i + 1, "other_row": int(j) + 1, "similarity": float(matrix[i, j])} for j in others)
    return pd.DataFrame(rows, columns=list(_SIMILAR))


def _similarity_build(node: Node, params: dict[str, Any]) -> Node:
    columns = columns_of(node, params.get("columns"), "Columns")
    if not columns:
        raise BadRequestError("Choose a text column, or the number columns to compare.")
    return extension(node, "ml.similarity_matrix", {"columns": columns, "top": params.get("top")}, dict(_SIMILAR))


_declare("ml.similarity_matrix", "Most alike rows", "For each row, the rows most alike it by cosine similarity: of "
         "number columns, or of one text column's words (TF-IDF). Rows are counted from 1.", _similarity_build,
         Example(rows=({"t": "red apple"}, {"t": "red apples"}, {"t": "blue sky"}), params={"columns": ["t"],
                                                                                         "top": 1},
                 column="t", output="other_row", expect=(2, 1, 1)),
         params=(Param("columns", "Columns", ParamKind.COLUMNS),
                 Param("top", "Most alike per row", ParamKind.INTEGER, default=3, minimum=1, maximum=100)),
         synonyms=("similarity matrix", "cosine similarity", "similar items", "nearest rows", "recommend"),
         describes=True)
