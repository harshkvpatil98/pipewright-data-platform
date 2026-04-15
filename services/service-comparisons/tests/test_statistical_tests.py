from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from service_comparisons.statistical_tests import (
    chi_square_two_sample_distributions,
    two_proportion_z_test,
    welch_t_test,
)
from shared_python.errors import BadRequestError


def test_welch_t_detects_mean_difference() -> None:
    np.random.seed(42)
    left = pd.Series(np.random.normal(0, 1, 50))
    right = pd.Series(np.random.normal(5, 1, 50))
    out = welch_t_test(left, right)
    assert out["p_value"] is not None
    assert out["p_value"] < 0.05
    assert out["sample_size_left"] == 50


def test_welch_t_rejects_small_n() -> None:
    left = pd.Series([1.0, 2.0])
    right = pd.Series([1.0, 2.0])
    with pytest.raises(BadRequestError):
        welch_t_test(left, right)


def test_proportion_z_basic() -> None:
    left = pd.Series([1, 1, 1, 0, 0, 0, 0, 0, 0, 0])
    right = pd.Series([0, 0, 0, 0, 0, 1, 1, 1, 1, 1])
    out = two_proportion_z_test(left, right)
    assert out["p_value"] is not None
    assert out["sample_size_left"] == 10


def test_proportion_z_rejects_constant_groups() -> None:
    left = pd.Series([1] * 10)
    right = pd.Series([0] * 10)
    with pytest.raises(BadRequestError):
        two_proportion_z_test(left, right)


def test_chi_square_basic() -> None:
    left = pd.Series(["a", "a", "b", "b", "c"] * 6)
    right = pd.Series(["a", "b", "c"] * 10)
    out = chi_square_two_sample_distributions(left, right)
    assert out["category_count"] >= 3
    assert out["p_value"] is not None


def test_chi_square_too_many_categories() -> None:
    left = pd.Series([str(i) for i in range(50)])
    right = pd.Series([str(i) for i in range(50)])
    with pytest.raises(BadRequestError):
        chi_square_two_sample_distributions(left, right)
