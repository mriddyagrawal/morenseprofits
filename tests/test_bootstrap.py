"""Tests for src.analytics.bootstrap.bootstrap_ci.

Pure-function unit tests. Pin determinism (seed), edge cases (n<2 →
NaN), and rough CI-coverage on a known distribution."""
from __future__ import annotations

import numpy as np
import pytest

from src.analytics.bootstrap import bootstrap_ci


def test_basic_median_ci_returns_three_floats():
    point, lo, hi = bootstrap_ci([1, 2, 3, 4, 5], B=100, seed=0)
    assert point == 3.0  # median of 1..5
    assert lo <= point <= hi


def test_seed_makes_output_reproducible():
    """Same (values, B, seed) → byte-identical (lo, hi)."""
    a = bootstrap_ci([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], B=500, seed=42)
    b = bootstrap_ci([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], B=500, seed=42)
    assert a == b


def test_different_seed_changes_ci_bounds():
    """Different seed → different resamples → different CI bounds
    (with overwhelming probability)."""
    _, lo1, hi1 = bootstrap_ci([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], B=500, seed=1)
    _, lo2, hi2 = bootstrap_ci([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], B=500, seed=2)
    assert (lo1, hi1) != (lo2, hi2)


def test_n_less_than_2_returns_nan():
    """Bootstrap is undefined for n<2 — caller should branch on NaN."""
    p, lo, hi = bootstrap_ci([], B=100)
    assert all(np.isnan(x) for x in (p, lo, hi))
    p, lo, hi = bootstrap_ci([7.0], B=100)
    assert all(np.isnan(x) for x in (p, lo, hi))


def test_nans_are_dropped():
    """Caller may pass a Series with NaNs (missing trades). Drop them
    silently rather than propagating NaN through the resampling."""
    p, lo, hi = bootstrap_ci(
        [1.0, 2.0, float("nan"), 3.0, 4.0, 5.0, float("nan")],
        B=100, seed=0,
    )
    assert p == 3.0  # median of the 5 finite values
    assert not np.isnan(lo) and not np.isnan(hi)


def test_alpha_out_of_range_raises():
    with pytest.raises(ValueError, match="alpha must satisfy"):
        bootstrap_ci([1, 2, 3], alpha=1.5)
    with pytest.raises(ValueError, match="alpha must satisfy"):
        bootstrap_ci([1, 2, 3], alpha=-0.1)


def test_b_less_than_1_raises():
    with pytest.raises(ValueError, match="B must be"):
        bootstrap_ci([1, 2, 3], B=0)


def test_2d_input_raises():
    """Shape guard — accidentally passing a (n, 1) DataFrame column."""
    with pytest.raises(ValueError, match="values must be 1-D"):
        bootstrap_ci([[1, 2], [3, 4]])


def test_custom_statistic_accepted():
    """statistic= overrides the default (median). Sanity-check with
    mean on a symmetric distribution."""
    p, lo, hi = bootstrap_ci(
        list(range(100)), statistic=np.mean, B=200, seed=0,
    )
    # Mean of 0..99 = 49.5; CI should bracket it tightly.
    assert lo < 49.5 < hi
    assert hi - lo < 25  # rough — symmetric tight distribution


def test_ci_covers_true_median_for_normal_sample():
    """Coverage sanity check: for a sample drawn from a known
    distribution, the 95% CI should bracket the true population median
    most of the time. Single seed test — not a coverage proof, but a
    smoke that the percentile bootstrap is wired correctly."""
    rng = np.random.default_rng(0)
    sample = rng.normal(loc=10.0, scale=2.0, size=100)
    p, lo, hi = bootstrap_ci(sample, B=500, seed=0)
    # True median is 10.0 (Gaussian is symmetric); CI should bracket it.
    assert lo < 10.0 < hi
