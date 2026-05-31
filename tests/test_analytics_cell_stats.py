"""Tests for src.analytics.cell_stats — shared per-cell stat block.

Pulled out of src/mcp/cell_summary.py + src/mcp/sweep_windows.py per
the chore(p8.cell_stats.centralize) refactor. The shared module
itself gets focused tests here; the per-tool tests (test_mcp_*.py)
continue to exercise the integrated behavior end-to-end.
"""
from __future__ import annotations

import numpy as np
import pytest

from src.analytics.cell_stats import (
    DEFAULT_CVAR_ALPHA,
    CellStatsBlock,
    bottom_alpha_mean,
    compute_cell_stats,
    empty_cell_stats_block,
)


# ============================================================
# bottom_alpha_mean
# ============================================================

def test_bottom_alpha_mean_strict_count_for_large_n():
    """n=100, α=0.05 → ceil(5) = 5 → mean of 5 smallest."""
    arr = np.arange(1, 101, dtype=float)
    assert bottom_alpha_mean(arr, alpha=0.05) == pytest.approx(3.0)


def test_bottom_alpha_mean_floors_to_one_for_tiny_n():
    """n=4, α=0.05 → ceil(0.2) = 1 → just the minimum."""
    assert bottom_alpha_mean(
        np.array([10.0, 20.0, -5.0, 15.0]), alpha=0.05
    ) == -5.0


def test_bottom_alpha_mean_drops_nans():
    """After NaN-drop: [10, 20, -5] → ceil(1.5) = 2 → mean(-5, 10) = 2.5"""
    arr = np.array([10.0, float("nan"), 20.0, -5.0])
    assert bottom_alpha_mean(arr, alpha=0.50) == pytest.approx(2.5)


def test_bottom_alpha_mean_returns_nan_on_empty():
    import math
    assert math.isnan(bottom_alpha_mean(np.array([]), alpha=0.05))


def test_bottom_alpha_mean_default_alpha_is_5_percent():
    """Pin DEFAULT_CVAR_ALPHA at 0.05 so consumer modules can rely on
    the same default across surfaces."""
    assert DEFAULT_CVAR_ALPHA == 0.05


# ============================================================
# empty_cell_stats_block
# ============================================================

def test_empty_cell_stats_block_returns_zero_n_with_none_stats():
    empty = empty_cell_stats_block()
    assert empty.n == 0
    assert empty.win_rate_pct is None
    assert empty.median_roi_pct is None
    assert empty.mean_roi_pct is None
    assert empty.std_roi_pct is None
    assert empty.cvar_5_roi_pct is None
    assert empty.total_net_pnl == 0.0


# ============================================================
# compute_cell_stats
# ============================================================

def test_compute_cell_stats_hand_derived_for_ten_trades():
    """ROIs 1..10; PnLs 100..1000. Hand-derive every field."""
    rois = np.arange(1, 11, dtype=float)
    pnls = np.arange(100, 1100, 100, dtype=float)
    out = compute_cell_stats(rois, pnls)
    assert out.n == 10
    assert out.win_rate_pct == 100.0  # all PnLs > 0
    assert out.median_roi_pct == pytest.approx(5.5)
    assert out.mean_roi_pct == pytest.approx(5.5)
    # std (ddof=0) of 1..10
    assert out.std_roi_pct == pytest.approx(float(np.std(rois, ddof=0)))
    # CVaR-5%: n=10 → ceil(0.5) = 1 → just the minimum = 1
    assert out.cvar_5_roi_pct == pytest.approx(1.0)
    # total_net_pnl = sum(100..1000) = 5500
    assert out.total_net_pnl == pytest.approx(5500.0)


def test_compute_cell_stats_empty_returns_empty_block():
    out = compute_cell_stats(
        np.array([], dtype=float), np.array([], dtype=float),
    )
    assert out.n == 0
    assert out.median_roi_pct is None


def test_compute_cell_stats_n_eq_1_has_no_std():
    """std (ddof=0) is defined for n=1, but for honesty surface we
    return None when n<2 so the consumer doesn't read a meaningless
    zero as 'tight distribution'."""
    out = compute_cell_stats(np.array([5.0]), np.array([100.0]))
    assert out.n == 1
    assert out.std_roi_pct is None


def test_compute_cell_stats_shape_mismatch_raises():
    with pytest.raises(ValueError, match="shape mismatch"):
        compute_cell_stats(np.array([1.0, 2.0]), np.array([100.0]))


def test_compute_cell_stats_mixed_winners_losers():
    """50% win rate; median and mean diverge on a slight-skew sample."""
    rois = np.array([10.0, -5.0, 15.0, -2.0, 8.0, -3.0])
    pnls = np.array([100.0, -50.0, 150.0, -20.0, 80.0, -30.0])
    out = compute_cell_stats(rois, pnls)
    assert out.n == 6
    # 3 positive PnLs out of 6
    assert out.win_rate_pct == pytest.approx(50.0)
    assert out.median_roi_pct == pytest.approx(3.0)  # median of sorted
    assert out.total_net_pnl == pytest.approx(230.0)


def test_compute_cell_stats_locks_cvar_alpha_to_default():
    """LOAD-BEARING: cvar_alpha is LOCKED to DEFAULT_CVAR_ALPHA (5%).
    The returned block's ``cvar_5_roi_pct`` field name encodes the
    5% commitment, so a non-default alpha would silently produce a
    stat block whose field name disagrees with its value. Raise loud
    rather than drift. If a caller needs a different tail fraction,
    they call ``bottom_alpha_mean`` directly (alpha-agnostic helper).
    Reviewer's latent grill on ebe7228 closes here."""
    from src.analytics.cell_stats import DEFAULT_CVAR_ALPHA
    rois = np.arange(1, 101, dtype=float)
    pnls = np.full_like(rois, 100.0)
    # Default alpha succeeds.
    out_05 = compute_cell_stats(rois, pnls, cvar_alpha=DEFAULT_CVAR_ALPHA)
    assert out_05.cvar_5_roi_pct == pytest.approx(3.0)  # mean(1..5)
    # Non-default alpha is rejected with a message naming both the
    # rejected value and the locked default.
    with pytest.raises(ValueError, match="DEFAULT_CVAR_ALPHA"):
        compute_cell_stats(rois, pnls, cvar_alpha=0.20)


def test_bottom_alpha_mean_remains_alpha_configurable():
    """Companion to the lock test above: the alpha-agnostic helper
    ``bottom_alpha_mean`` still accepts arbitrary alpha. This is
    where callers go if they need a non-5% tail fraction. Pinning
    the split so a future refactor doesn't accidentally lock both."""
    from src.analytics.cell_stats import bottom_alpha_mean
    arr = np.arange(1, 101, dtype=float)
    assert bottom_alpha_mean(arr, 0.05) == pytest.approx(3.0)   # mean(1..5)
    assert bottom_alpha_mean(arr, 0.20) == pytest.approx(10.5)  # mean(1..20)
