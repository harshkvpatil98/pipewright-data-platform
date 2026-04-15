from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from shared_python.errors import BadRequestError

MIN_PER_GROUP_T = 3
MIN_PER_GROUP_PROP = 5
MAX_CHI_CATEGORIES = 30
ALPHA = 0.05


def _interpret_p(p: float | None) -> str:
    if p is None or np.isnan(p):
        return "A p-value could not be computed for this test."
    if p < ALPHA:
        return f"The difference is statistically significant at the {ALPHA} level (p={p:.4g}). This is association only, not proof of causation."
    return f"No statistically significant difference was detected at the {ALPHA} level (p={p:.4g})."


def welch_t_test(left: pd.Series, right: pd.Series) -> dict[str, Any]:
    l_num = pd.to_numeric(left, errors="coerce")
    r_num = pd.to_numeric(right, errors="coerce")
    coerced_note = (left.notna().sum() > l_num.notna().sum()) or (right.notna().sum() > r_num.notna().sum())
    lw = l_num.dropna()
    rw = r_num.dropna()

    if len(lw) < MIN_PER_GROUP_T or len(rw) < MIN_PER_GROUP_T:
        raise BadRequestError(
            f"Welch t-test requires at least {MIN_PER_GROUP_T} non-null numeric values per dataset after coercion."
        )

    t_stat, p_two = stats.ttest_ind(lw, rw, equal_var=False)
    t_stat_f = float(t_stat) if not (isinstance(t_stat, float) and np.isnan(t_stat)) else None
    p_val = float(p_two) if p_two is not None and not np.isnan(p_two) else None

    warnings: list[str] = ["Null values were excluded before testing."]
    if coerced_note:
        warnings.append("Values were coerced to numeric; values that could not be coerced were treated as null.")

    assumptions = [
        "Welch's t-test does not assume equal variances.",
        "Approximate normality of means is more reliable with larger samples.",
    ]

    return {
        "statistic": t_stat_f,
        "p_value": p_val,
        "left_mean": float(lw.mean()),
        "right_mean": float(rw.mean()),
        "sample_size_left": int(len(lw)),
        "sample_size_right": int(len(rw)),
        "effect_summary": f"Left mean {lw.mean():.6g}, right mean {rw.mean():.6g}.",
        "assumptions_notes": assumptions,
        "warnings": warnings,
        "interpretation": _interpret_p(p_val),
    }


def _normalize_binary(series: pd.Series) -> pd.Series:
    def cell(v: Any) -> float | np.floating:
        if pd.isna(v):
            return np.nan
        if isinstance(v, bool):
            return 1.0 if v else 0.0
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if v == 1:
                return 1.0
            if v == 0:
                return 0.0
        s = str(v).strip().lower()
        if s in {"true", "yes", "y", "1"}:
            return 1.0
        if s in {"false", "no", "n", "0"}:
            return 0.0
        return np.nan

    out = series.map(cell)
    return out


def two_proportion_z_test(left: pd.Series, right: pd.Series) -> dict[str, Any]:
    lb = _normalize_binary(left)
    rb = _normalize_binary(right)
    lw = lb.dropna()
    rw = rb.dropna()

    warnings: list[str] = [
        "Null values were excluded before testing.",
        "Binary values were normalized from boolean, 0/1, or yes/no forms.",
    ]

    if len(lw) < MIN_PER_GROUP_PROP or len(rw) < MIN_PER_GROUP_PROP:
        raise BadRequestError(
            f"Two-proportion z-test requires at least {MIN_PER_GROUP_PROP} non-null binary values per dataset."
        )

    x1 = float(lw.sum())
    n1 = float(len(lw))
    x2 = float(rw.sum())
    n2 = float(len(rw))

    if x1 in (0, n1) and x2 in (0, n2):
        raise BadRequestError("Both groups are constant (all 0 or all 1); proportion comparison is undefined.")

    p1 = x1 / n1
    p2 = x2 / n2
    se = np.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    if se == 0 or np.isnan(se):
        raise BadRequestError("Standard error is zero; cannot compute two-proportion z-test.")

    z = (p1 - p2) / se
    p_val = float(2 * (1 - stats.norm.cdf(abs(z))))

    assumptions = [
        "Two-sample z-test for proportions with unpooled standard error.",
        "Normal approximation is more reliable with larger sample sizes.",
    ]

    return {
        "statistic": float(z),
        "p_value": p_val,
        "left_proportion": float(p1),
        "right_proportion": float(p2),
        "sample_size_left": int(n1),
        "sample_size_right": int(n2),
        "effect_summary": f"Left proportion {p1:.4f} ({int(x1)}/{int(n1)}), right proportion {p2:.4f} ({int(x2)}/{int(n2)}).",
        "assumptions_notes": assumptions,
        "warnings": warnings,
        "interpretation": _interpret_p(p_val),
    }


def chi_square_two_sample_distributions(left: pd.Series, right: pd.Series) -> dict[str, Any]:
    ls = left.dropna().map(lambda x: str(x).strip() if x is not None and not pd.isna(x) else np.nan).dropna()
    rs = right.dropna().map(lambda x: str(x).strip() if x is not None and not pd.isna(x) else np.nan).dropna()

    warnings: list[str] = ["Null values were excluded before testing."]

    if len(ls) < MIN_PER_GROUP_PROP or len(rs) < MIN_PER_GROUP_PROP:
        raise BadRequestError(
            f"Chi-square test requires at least {MIN_PER_GROUP_PROP} non-null values per dataset."
        )

    cats = sorted(pd.unique(pd.concat([ls, rs], ignore_index=True)), key=str)
    if len(cats) > MAX_CHI_CATEGORIES:
        raise BadRequestError(
            f"Too many distinct categories ({len(cats)}); maximum supported is {MAX_CHI_CATEGORIES} for this endpoint."
        )
    if len(cats) < 2:
        raise BadRequestError("Chi-square test requires at least two distinct categories after excluding nulls.")

    counts_l = ls.value_counts().reindex(cats, fill_value=0)
    counts_r = rs.value_counts().reindex(cats, fill_value=0)
    observed = np.array([counts_l.values, counts_r.values], dtype=float)

    chi2, p, dof, expected = stats.chi2_contingency(observed)
    if np.any(expected < 1):
        warnings.append("Some expected cell counts are below 1; chi-square approximation may be unreliable.")

    assumptions = [
        "Chi-square test on a 2×k contingency table (two datasets × category counts).",
        "Assumes independent observations and adequate expected counts where possible.",
    ]

    p_val = float(p) if not np.isnan(p) else None
    interp = _interpret_p(p_val)
    if p_val is not None and p_val < ALPHA:
        interp = (
            "The categorical distribution differs significantly between the two datasets at the "
            f"{ALPHA} level (p={p_val:.4g}). This describes association, not causation."
        )
    elif p_val is not None:
        interp = (
            f"No statistically significant difference in category distributions at the {ALPHA} level "
            f"(p={p_val:.4g})."
        )

    return {
        "statistic": float(chi2),
        "p_value": p_val,
        "category_count": int(len(cats)),
        "sample_size_left": int(len(ls)),
        "sample_size_right": int(len(rs)),
        "effect_summary": f"Compared {len(cats)} categories across the two datasets.",
        "assumptions_notes": assumptions,
        "warnings": warnings,
        "interpretation": interp,
    }
