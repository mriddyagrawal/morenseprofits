"""Tests for src.analytics.observations.interpret_cell_stats.

Each detector tested in isolation:
  - heavy-tail (mean >> median in both directions)
  - outlier-carry (one trade > 50% of |sum|)
  - instability (std > 3× |median|)
  - empty / degenerate inputs return [] silently"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics.observations import (
    HEAVY_TAIL_MEAN_MINUS_MEDIAN_PTS,
    INSTABILITY_STD_TO_MEDIAN_RATIO,
    OUTLIER_CARRY_PNL_SHARE,
    interpret_cell_stats,
)


def _rows(roi: list[float], pnl: list[float] | None = None) -> pd.DataFrame:
    """Build a minimal cell-rows frame."""
    if pnl is None:
        pnl = [0.0] * len(roi)
    return pd.DataFrame({"roi_pct_annualized": roi, "net_pnl": pnl})


def test_empty_frame_returns_empty():
    assert interpret_cell_stats(pd.DataFrame()) == []


def test_missing_columns_returns_empty():
    df = pd.DataFrame({"foo": [1, 2, 3]})
    assert interpret_cell_stats(df) == []


def test_single_row_returns_empty():
    """n=1 → no statistic is computable."""
    assert interpret_cell_stats(_rows([50.0], [1000.0])) == []


def test_symmetric_distribution_no_observations():
    """Sym tight distribution → no heavy-tail, no outlier, no
    instability. Should be quiet."""
    roi = [10, 12, 9, 11, 8, 13, 10, 11, 9, 12]
    pnl = [100, 120, 90, 110, 80, 130, 100, 110, 90, 120]
    out = interpret_cell_stats(_rows(roi, pnl))
    assert out == []


# ============================================================
# Heavy tail detector
# ============================================================

def test_heavy_upside_tail_fires():
    """ROIs: nine small wins (~5%), one massive (+400%) → mean way
    above median → fires."""
    roi = [5, 5, 6, 4, 5, 5, 6, 4, 5, 400]
    pnl = [100] * 9 + [10000]
    out = interpret_cell_stats(_rows(roi, pnl))
    assert any("mean > median" in s and "heavy upside tail" in s for s in out)


def test_heavy_downside_tail_fires():
    """Mirror: nine small wins, one huge loss → mean << median → fires."""
    roi = [5, 5, 6, 4, 5, 5, 6, 4, 5, -400]
    pnl = [100] * 9 + [-10000]
    out = interpret_cell_stats(_rows(roi, pnl))
    assert any("mean < median" in s and "heavy downside tail" in s for s in out)


def test_heavy_tail_threshold_just_below_does_not_fire():
    """Gap just below HEAVY_TAIL_MEAN_MINUS_MEDIAN_PTS → silent."""
    # median = 10, want mean = 10 + (threshold - 1) so gap is just under
    n = 9
    target_gap = HEAVY_TAIL_MEAN_MINUS_MEDIAN_PTS - 1
    # nine values at 10 (median=10), one outlier picked to hit
    # mean = 10 + target_gap → outlier = mean*10 - 9*10 = mean*10 - 90
    target_mean = 10.0 + target_gap
    outlier = target_mean * 10 - 90
    roi = [10.0] * 9 + [outlier]
    out = interpret_cell_stats(_rows(roi, [0.0] * 10))
    assert not any("heavy upside tail" in s or "heavy downside tail" in s for s in out)


# ============================================================
# Outlier-carry detector
# ============================================================

def test_outlier_carry_fires_on_dominant_trade():
    """One trade's |net_pnl| > 50% of |sum| → fires."""
    pnl = [100, 90, 110, 80, 70, 60, 50, 5000]  # last trade dominates
    roi = [5] * 8  # ROI flat — only outlier-carry should fire
    out = interpret_cell_stats(_rows(roi, pnl))
    assert any("one trade carries" in s for s in out)


def test_outlier_carry_silent_when_well_distributed():
    """No single trade > threshold → silent."""
    pnl = [100, 120, 90, 110, 105, 95, 85, 115]
    roi = [5] * 8
    out = interpret_cell_stats(_rows(roi, pnl))
    assert not any("one trade carries" in s for s in out)


def test_outlier_carry_silent_when_total_is_zero():
    """Defensive guard: sum=0 means share is undefined; skip the
    detector rather than divide by zero."""
    pnl = [100, -100, 50, -50, 75, -75]  # sum = 0
    roi = [5] * 6
    out = interpret_cell_stats(_rows(roi, pnl))
    # No NaN / no crash; detector silently doesn't fire.
    assert not any("one trade carries" in s for s in out)


# ============================================================
# Instability detector
# ============================================================

def test_instability_fires_on_high_std_to_median_ratio():
    """std > 3× |median| → fires."""
    rng = np.random.default_rng(0)
    # median ~5, std ~50 → ratio 10 → fires
    roi = [5, 4, 6, 5, -100, 100, -80, 90, 5, 6]
    out = interpret_cell_stats(_rows(roi))
    assert any("dispersion wildly exceeds" in s for s in out)


def test_instability_silent_on_tight_distribution():
    """Tight distribution → std small relative to median → silent."""
    roi = [9, 10, 11, 10, 10, 9, 11, 10]  # std ≈ 0.7, median 10
    out = interpret_cell_stats(_rows(roi))
    assert not any("dispersion wildly exceeds" in s for s in out)


def test_instability_silent_when_median_is_zero():
    """Defensive guard: |median| < 0.01 means we can't form the ratio
    meaningfully; skip rather than divide by zero."""
    roi = [-5, 5, -3, 3, -1, 1]  # median = 0
    out = interpret_cell_stats(_rows(roi))
    assert not any("dispersion wildly exceeds" in s for s in out)


# ============================================================
# Multiple detectors firing simultaneously
# ============================================================

def test_all_three_can_coexist():
    """A cell with heavy tail AND one carrying trade AND high std →
    all three observations present."""
    # 9 small + 1 massive ROI → heavy upside tail + instability
    # P&L: same distribution, one trade dominates → outlier-carry
    roi = [5, 5, 6, 4, 5, 5, 6, 4, 5, 400]
    pnl = [10, 10, 12, 8, 10, 10, 12, 8, 10, 5000]
    out = interpret_cell_stats(_rows(roi, pnl))
    assert len(out) == 3
    assert any("heavy upside tail" in s for s in out)
    assert any("one trade carries" in s for s in out)
    assert any("dispersion wildly exceeds" in s for s in out)
