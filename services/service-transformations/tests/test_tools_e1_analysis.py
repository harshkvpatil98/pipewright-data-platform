"""Statistics, machine learning, sampling and places: known answers (E1).

Each family is checked against an answer worked out another way (a textbook
value, scipy called directly, a published distance), and for the seeded
ones, that the same seed gives the same rows and another seed other rows.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from service_transformations.executor import apply_transformation_steps
from service_transformations.steps.context import StepContext

OTHER = "00000000-0000-0000-0000-0000000000bb"


def run(frame: pd.DataFrame, tool: str, reference: pd.DataFrame | None = None, **config):
    other = reference
    context = StepContext(resolve_dataset=lambda _id: (other if other is not None else pd.DataFrame()).copy())
    if other is not None:
        config.setdefault("right_dataset_id", OTHER)
    return apply_transformation_steps(frame, [{"step_type": "tool", "config": {"tool": tool, **config}}], context)


RNG = np.random.default_rng(7)
NORMAL = pd.DataFrame({"v": RNG.normal(10, 2, 200), "g": ["a", "b"] * 100})


class TestStatistics:
    def test_a_t_test_gives_scipys_answer_and_says_what_it_means(self) -> None:
        from scipy import stats

        frame = pd.DataFrame({"v": [5.1, 4.9, 5.0, 5.3, 4.8], "g": ["x"] * 5})
        out, _ = run(frame, "stats.t_test", column="v", value=4)
        expected = stats.ttest_1samp(frame["v"], 4)
        assert out["p_value"][0] == pytest.approx(expected.pvalue)
        assert out["conclusion"][0].startswith("p = ") and "the mean differs from 4" in out["conclusion"][0]

    def test_welch_when_groups_differ(self) -> None:
        out, _ = run(pd.DataFrame({"v": [1, 2, 3, 30, 31, 32], "g": list("aaabbb")}), "stats.t_test", column="v",
                     by="g")
        assert out["p_value"][0] < 0.001

    def test_more_than_two_groups_point_to_anova(self) -> None:
        from shared_python.errors import BadRequestError

        with pytest.raises(BadRequestError, match="compare means with ANOVA"):
            run(pd.DataFrame({"v": [1, 2, 3], "g": list("abc")}), "stats.t_test", column="v", by="g")

    def test_normal_values_pass_a_normality_test(self) -> None:
        out, _ = run(NORMAL, "stats.normality", column="v")
        assert out["test"][0] == "Shapiro-Wilk" and out["p_value"][0] > 0.05
        assert "nothing says the values are not normal" in out["conclusion"][0]

    def test_chi_square_of_related_columns(self) -> None:
        frame = pd.DataFrame({"a": ["x"] * 40 + ["y"] * 40, "b": ["p"] * 35 + ["q"] * 5 + ["p"] * 5 + ["q"] * 35})
        out, _ = run(frame, "stats.chi_square", column="a", other="b")
        assert out["p_value"][0] < 0.001 and "are related" in out["conclusion"][0]

    def test_a_straight_line_is_found(self) -> None:
        frame = pd.DataFrame({"x": range(10), "y": [3 * x + 2 for x in range(10)]})
        out, _ = run(frame, "stats.linear_regression", target="y", feature="x")
        terms = dict(zip(out["term"], out["estimate"]))
        assert terms["intercept"] == pytest.approx(2) and terms["x"] == pytest.approx(3)
        assert terms["fit"] == pytest.approx(1.0)

    def test_describe(self) -> None:
        out, _ = run(pd.DataFrame({"v": [1, 2, 3, None], "c": ["a", "a", "b", "c"]}), "stats.describe")
        number = out[out["column"] == "v"].iloc[0]
        assert (number["count"], number["empty"], number["median"]) == (3, 1, 2.0)
        assert out[out["column"] == "c"].iloc[0]["commonest"] == "a"

    def test_a_trend_and_its_slope(self) -> None:
        out, _ = run(pd.DataFrame({"v": [2 * i + (i % 3) for i in range(30)]}), "stats.trend_test", column="v")
        assert out["slope_per_row"][0] == pytest.approx(2.0, abs=0.2) and "rising" in out["conclusion"][0]

    def test_change_points(self) -> None:
        values = [1.0] * 10 + [8.0] * 10 + [3.0] * 10
        out, warnings = run(pd.DataFrame({"v": values}), "stats.changepoints", column="v")
        assert out["v_segment"].tolist() == [1] * 10 + [2] * 10 + [3] * 10
        assert any("2 change points" in w for w in warnings)

    def test_the_best_fitting_distribution(self) -> None:
        frame = pd.DataFrame({"v": np.random.default_rng(3).exponential(2.0, 400)})
        out, _ = run(frame, "stats.distribution_fit", column="v")
        assert out["distribution"][0] in ("exponential", "gamma", "weibull")
        assert out["conclusion"][0] == "fits best (lowest AIC)"

    def test_sample_size_textbook(self) -> None:
        out, _ = run(pd.DataFrame({"x": [1]}), "stats.sample_size", confidence=0.95, margin=0.03)
        assert out["sample_size"][0] == 1068  # 1.96² × 0.25 / 0.03²

    def test_iqr_outliers(self) -> None:
        out, warnings = run(pd.DataFrame({"v": [10, 11, 12, 11, 10, 12, 11, 95, None]}), "stats.outliers_iqr",
                            column="v")
        assert out["v_outlier"].tolist()[:8] == [False] * 7 + [True] and pd.isna(out["v_outlier"].iloc[8])
        assert any("interquartile range" in w for w in warnings)


class TestMachineLearning:
    BLOBS = pd.DataFrame({"x": [1, 1.2, 0.8, 9, 9.2, 8.8, 1.1, 9.1], "y": [1, 0.9, 1.1, 9, 9.1, 8.9, 1, 9]})

    def test_kmeans_is_the_same_every_run_and_says_how_well_it_separated(self) -> None:
        first, warnings = run(self.BLOBS, "ml.kmeans", k=2, seed=4)
        second, _ = run(self.BLOBS, "ml.kmeans", k=2, seed=4)
        assert first["cluster"].tolist() == second["cluster"].tolist() == [1, 1, 1, 2, 2, 2, 1, 2]
        assert any("silhouette" in w for w in warnings)

    def test_pca_keeps_the_variation_and_says_how_much(self) -> None:
        frame = pd.DataFrame({"a": range(20), "b": [2 * v + 1 for v in range(20)]})
        out, warnings = run(frame, "ml.pca", components=1)
        assert any("100% together" in w for w in warnings)
        assert out["component_1"].is_monotonic_increasing

    def test_a_classifier_learns_from_labelled_rows_and_reports_accuracy(self) -> None:
        labels = ["small"] * 10 + ["big"] * 10 + [None, None]
        size = list(np.linspace(1, 2, 10)) + list(np.linspace(8, 9, 10)) + [1.5, 8.5]
        out, warnings = run(pd.DataFrame({"size": size, "kind": labels}), "ml.decision_tree", target="kind",
                            columns=["size"])
        assert out["kind_predicted"].tolist()[-2:] == ["small", "big"]
        assert any("cross-validated accuracy 100%" in w and "relies most on size" in w for w in warnings)

    def test_a_forecast_continues_a_trend_with_an_interval(self) -> None:
        months = pd.DataFrame({"m": pd.date_range("2025-01-01", periods=24, freq="MS"),
                               "sales": [100 + 5 * i for i in range(24)]})
        out, warnings = run(months, "ml.forecast_trend_season", column="sales", time="m", periods=3)
        future = out[out["is_forecast"]]
        assert future["sales"].round(6).tolist() == [220.0, 225.0, 230.0]
        assert str(future["m"].iloc[0])[:10] == "2027-01-01"
        assert any("mean absolute percentage error 0.0%" in w for w in warnings)

    def test_holt_winters_with_a_season(self) -> None:
        season = [10, 20, 30, 20] * 6
        months = pd.DataFrame({"t": range(24), "v": [s + i for i, s in enumerate(season)]})
        out, _ = run(months, "ml.forecast_smoothing", column="v", time="t", periods=4, period=4)
        assert out["is_forecast"].sum() == 4 and out[out["is_forecast"]]["t"].tolist() == [24.0, 25.0, 26.0, 27.0]

    def test_one_hot(self) -> None:
        out, _ = run(pd.DataFrame({"c": ["red", "blue", None]}), "ml.one_hot", column="c", drop=True)
        assert list(out.columns) == ["c_blue", "c_red"] and out["c_red"].tolist()[:2] == [1, 0]

    def test_knn_fills_from_alike_rows(self) -> None:
        frame = pd.DataFrame({"a": [1.0, 1.1, 9.0, 9.1, 1.05], "b": [10.0, 10.0, 90.0, 90.0, None]})
        out, _ = run(frame, "ml.impute_knn", neighbours=2)
        assert out["b"].iloc[4] == pytest.approx(10.0)


class TestSampling:
    FRAME = pd.DataFrame({"n": range(1, 101), "g": ["a"] * 80 + ["b"] * 20})

    def test_the_same_seed_gives_the_same_rows_and_another_seed_others(self) -> None:
        one, _ = run(self.FRAME, "sample.random", share=0.1, seed=1)
        again, _ = run(self.FRAME, "sample.random", share=0.1, seed=1)
        other, _ = run(self.FRAME, "sample.random", share=0.1, seed=2)
        assert one["n"].tolist() == again["n"].tolist() != other["n"].tolist()
        assert len(one) == 10 and one["n"].is_monotonic_increasing

    def test_stratified_keeps_each_groups_share(self) -> None:
        out, _ = run(self.FRAME, "sample.stratified", by="g", share=0.25)
        assert out["g"].value_counts().to_dict() == {"a": 20, "b": 5}

    def test_balanced(self) -> None:
        out, _ = run(self.FRAME, "sample.balanced", by="g")
        assert out["g"].value_counts().to_dict() == {"a": 20, "b": 20}

    def test_train_test_keeps_the_share_within_each_group(self) -> None:
        out, _ = run(self.FRAME, "sample.train_test", test_share=0.2, by="g")
        counts = out.groupby(["g", "split"]).size().to_dict()
        assert counts == {("a", "test"): 16, ("a", "train"): 64, ("b", "test"): 4, ("b", "train"): 16}

    def test_reservoir_keeps_exactly_n(self) -> None:
        out, _ = run(self.FRAME, "sample.reservoir", count=7, seed=3)
        assert len(out) == 7 and out["n"].is_monotonic_increasing


class TestPlaces:
    def test_vincenty_matches_the_published_flinders_peak_to_buninyong_distance(self) -> None:
        # Vincenty (1975) and Geoscience Australia's worked example: 54,972.271 m.
        frame = pd.DataFrame({"lat": [-(37 + 57 / 60 + 3.72030 / 3600)], "lon": [144 + 25 / 60 + 29.52440 / 3600],
                              "lat2": [-(37 + 39 / 60 + 10.15610 / 3600)], "lon2": [143 + 55 / 60 + 35.38390 / 3600]})
        out, _ = run(frame, "geo.distance", lat="lat", lon="lon", lat2="lat2", lon2="lon2", method="ellipsoid",
                     unit="metres")
        assert out["distance"][0] == pytest.approx(54_972.271, abs=0.01)

    def test_haversine_is_within_half_a_percent_of_the_ellipsoid(self) -> None:
        frame = pd.DataFrame({"lat": [51.5074], "lon": [-0.1278], "lat2": [40.7128], "lon2": [-74.0060]})
        sphere, _ = run(frame, "geo.distance", lat="lat", lon="lon", lat2="lat2", lon2="lon2")
        ellipsoid, _ = run(frame, "geo.distance", lat="lat", lon="lon", lat2="lat2", lon2="lon2", method="ellipsoid")
        assert abs(sphere["distance"][0] / ellipsoid["distance"][0] - 1) < 0.005

    def test_a_buffer_is_its_distance_from_the_point_all_round(self) -> None:
        from shapely import wkt

        from service_transformations.tools.catalogue.geo import vincenty

        out, _ = run(pd.DataFrame({"s": ["POINT (-0.1278 51.5074)"]}), "geo.buffer", column="s", metres=1000)
        ring = wkt.loads(out["s"][0]).exterior.coords
        distances = [vincenty(51.5074, -0.1278, lat, lon) for lon, lat in ring]
        assert all(abs(d - 1000) < 5 for d in distances)

    def test_geohash_round_trip(self) -> None:
        from service_transformations.tools.catalogue.geo import geohash, ungeohash

        lat, lon = ungeohash(geohash(51.5074, -0.1278, 9))
        assert abs(lat - 51.5074) < 1e-4 and abs(lon + 0.1278) < 1e-4

    def test_area_of_a_degree_square_at_the_equator(self) -> None:
        out, _ = run(pd.DataFrame({"s": ["POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"]}), "geo.area", column="s",
                     unit="square kilometres")
        assert out["s"][0] == pytest.approx(12_364, rel=0.002)  # 111.195 km on each side

    def test_the_nearest_store(self) -> None:
        stores = pd.DataFrame({"name": ["Edinburgh", "Bristol"], "la": [55.95, 51.45], "lo": [-3.19, -2.59]})
        out, _ = run(pd.DataFrame({"lat": [55.86], "lon": [-4.25]}), "geo.nearest", stores, lat="lat", lon="lon",
                     right_lat="la", right_lon="lo", bring=["name"])
        assert out["name"][0] == "Edinburgh" and 60 < out["distance_km"][0] < 70

    def test_haversine_with_a_point_at_the_antipode_stays_in_range(self) -> None:
        frame = pd.DataFrame({"lat": [0.0], "lon": [0.0], "lat2": [0.0], "lon2": [180.0]})
        out, _ = run(frame, "geo.distance", lat="lat", lon="lon", lat2="lat2", lon2="lon2", unit="metres")
        assert out["distance"][0] == pytest.approx(math.pi * 6_371_008.8)
