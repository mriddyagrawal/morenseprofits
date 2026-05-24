"""Tests for src.analytics.heatmap — Phase-5.2 pivot for the
(entry_offset, exit_offset) heatmap.

Load-bearing concerns:
  - Shape: index = entry_offset_td desc, columns = exit_offset_td desc.
    Phase-6 visualization depends on this exact orientation (T-15 at
    top, T-1 at right — the visual convention).
  - Missing cells → NaN in values (not 0) so heatmap colors don't
    falsely imply zero P&L. counts → 0 (the accurate "no trades").
  - Filter contract: strategy/symbol both optional; either narrows
    the slice; both None aggregates across.
  - Default value column is the now-exact roi_pct_annualized.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.analytics.heatmap import pivot_counts, pivot_window


def _fixture(rows):
    return pd.DataFrame(rows)


def _row(strategy="S", symbol="X", entry=15, exit_=1,
         net_pnl=0.0, roi_pct=0.0, roi_pct_annualized=0.0):
    return {
        "strategy": strategy, "symbol": symbol,
        "entry_offset_td": entry, "exit_offset_td": exit_,
        "net_pnl": net_pnl, "roi_pct": roi_pct,
        "roi_pct_annualized": roi_pct_annualized,
    }


# ============================================================
# Shape: index and column orientation
# ============================================================

def test_index_descending_entry_offset(monkeypatch):
    """T-15 entry must appear at the top of the pivot (index[0])."""
    df = pivot_window(_fixture([
        _row(entry=5, exit_=1, roi_pct_annualized=10.0),
        _row(entry=10, exit_=1, roi_pct_annualized=20.0),
        _row(entry=15, exit_=1, roi_pct_annualized=30.0),
    ]))
    # Index sorted descending → 15, 10, 5
    assert list(df.index) == [15, 10, 5]


def test_columns_descending_exit_offset():
    """Larger exit_offset (e.g., T-3, "earlier exit") at left, T-1 at right."""
    df = pivot_window(_fixture([
        _row(entry=15, exit_=1, roi_pct_annualized=10.0),
        _row(entry=15, exit_=3, roi_pct_annualized=20.0),
        _row(entry=15, exit_=5, roi_pct_annualized=30.0),
    ]))
    # Columns sorted descending → 5, 3, 1
    assert list(df.columns) == [5, 3, 1]


# ============================================================
# Cell values + missing-combo NaN
# ============================================================

def test_cell_values_are_median_by_default():
    """Three trades at (15, 1) with ROIs [10, 20, 30] → median = 20."""
    df = pivot_window(_fixture([
        _row(entry=15, exit_=1, roi_pct_annualized=10.0),
        _row(entry=15, exit_=1, roi_pct_annualized=20.0),
        _row(entry=15, exit_=1, roi_pct_annualized=30.0),
    ]))
    assert df.loc[15, 1] == 20.0


def test_missing_cells_are_nan_not_zero():
    """LOAD-BEARING: empty (entry, exit) cells must be NaN, not 0,
    so Phase-6 heatmap doesn't paint "no data" cells the same color
    as "zero return" cells."""
    df = pivot_window(_fixture([
        _row(entry=15, exit_=1, roi_pct_annualized=10.0),
        # No (10, 1) cell — only (15, 1) populated
    ]))
    # The empty cell (10, 1) shouldn't even exist in this pivot since
    # there are no entry=10 rows. Single-cell pivot.
    assert df.shape == (1, 1)

    # Now WITH a missing combo in a grid that has both axes:
    df = pivot_window(_fixture([
        _row(entry=15, exit_=1, roi_pct_annualized=10.0),
        _row(entry=10, exit_=3, roi_pct_annualized=20.0),
    ]))
    # 2x2 grid: only diagonal populated, off-diagonals NaN
    assert pd.isna(df.loc[15, 3])
    assert pd.isna(df.loc[10, 1])
    assert df.loc[15, 1] == 10.0
    assert df.loc[10, 3] == 20.0


def test_value_col_kwarg_changes_metric():
    """aggfunc=mean, value_col=net_pnl → mean net P&L pivot."""
    df = pivot_window(
        _fixture([
            _row(entry=15, exit_=1, net_pnl=100.0),
            _row(entry=15, exit_=1, net_pnl=300.0),
        ]),
        value_col="net_pnl", aggfunc="mean",
    )
    assert df.loc[15, 1] == 200.0


def test_invalid_value_col_raises():
    with pytest.raises(ValueError, match="value_col"):
        pivot_window(_fixture([_row()]), value_col="nonexistent")


# ============================================================
# Filtering by strategy / symbol
# ============================================================

def test_strategy_filter_isolates_one_strategy():
    df = pivot_window(_fixture([
        _row(strategy="short_straddle", entry=15, exit_=1, roi_pct_annualized=10.0),
        _row(strategy="iron_condor",    entry=15, exit_=1, roi_pct_annualized=99.0),
    ]), strategy="short_straddle")
    # Iron condor's 99 row should be filtered out
    assert df.loc[15, 1] == 10.0


def test_symbol_filter_isolates_one_symbol():
    df = pivot_window(_fixture([
        _row(symbol="RELIANCE", entry=15, exit_=1, roi_pct_annualized=10.0),
        _row(symbol="INFY",     entry=15, exit_=1, roi_pct_annualized=99.0),
    ]), symbol="RELIANCE")
    assert df.loc[15, 1] == 10.0


def test_no_filter_aggregates_across_both_axes():
    """Both strategy=None and symbol=None → median across everything."""
    df = pivot_window(_fixture([
        _row(strategy="S1", symbol="X", entry=15, exit_=1, roi_pct_annualized=10.0),
        _row(strategy="S2", symbol="Y", entry=15, exit_=1, roi_pct_annualized=20.0),
    ]))
    # median of [10, 20] = 15
    assert df.loc[15, 1] == 15.0


# ============================================================
# Empty / edge cases
# ============================================================

def test_filter_yielding_zero_rows_returns_empty_frame():
    df = pivot_window(_fixture([_row(strategy="S", entry=15, exit_=1)]),
                      strategy="NOT_PRESENT")
    assert df.empty


def test_empty_input_returns_empty_frame():
    """No rows → no pivot. Phase-6 UI handles the empty case."""
    df = pivot_window(pd.DataFrame({
        "strategy": pd.Series(dtype="string"),
        "symbol": pd.Series(dtype="string"),
        "entry_offset_td": pd.Series(dtype="int64"),
        "exit_offset_td": pd.Series(dtype="int64"),
        "net_pnl": pd.Series(dtype="float64"),
        "roi_pct": pd.Series(dtype="float64"),
        "roi_pct_annualized": pd.Series(dtype="float64"),
    }))
    assert df.empty


def test_missing_required_columns_raises():
    bad = pd.DataFrame({"strategy": ["x"], "symbol": ["y"]})  # missing offsets
    with pytest.raises(ValueError, match="required keys"):
        pivot_window(bad)


# ============================================================
# pivot_counts — sample sizes per cell
# ============================================================

def test_counts_pivot_returns_integer_trade_counts():
    """Each cell holds the count of trades feeding it; missing combos → 0."""
    counts = pivot_counts(_fixture([
        _row(entry=15, exit_=1),
        _row(entry=15, exit_=1),
        _row(entry=15, exit_=1),
        _row(entry=10, exit_=3),
    ]))
    assert counts.loc[15, 1] == 3
    assert counts.loc[10, 3] == 1
    assert counts.loc[15, 3] == 0  # missing combo → 0, NOT NaN
    assert counts.loc[10, 1] == 0


def test_counts_and_values_pivots_have_same_shape():
    """LOAD-BEARING for the masking pattern:
       v.where(counts >= MIN_N_FOR_RANKING) — needs identical shape."""
    rows = [
        _row(entry=15, exit_=1, roi_pct_annualized=10.0),
        _row(entry=15, exit_=1, roi_pct_annualized=20.0),
        _row(entry=10, exit_=3, roi_pct_annualized=30.0),
    ]
    v = pivot_window(_fixture(rows))
    n = pivot_counts(_fixture(rows))
    assert v.shape == n.shape
    assert list(v.index) == list(n.index)
    assert list(v.columns) == list(n.columns)


def test_min_n_masking_pattern_with_pivot_counts():
    """Document the canonical thin-sample masking pattern:
    v.where(counts >= MIN_N_FOR_RANKING) suppresses cells with too
    few trades. Phase-6 renders the masked cells as 'no data'."""
    from src.analytics.aggregate import MIN_N_FOR_RANKING
    rows = (
        # 6 trades at (15, 1) — exceeds MIN_N_FOR_RANKING
        [_row(entry=15, exit_=1, roi_pct_annualized=10.0)] * 6
        + [_row(entry=10, exit_=1, roi_pct_annualized=99.0)]  # 1 trade only
    )
    v = pivot_window(_fixture(rows))
    n = pivot_counts(_fixture(rows))
    masked = v.where(n >= MIN_N_FOR_RANKING)
    # Statistically-thick cell preserved
    assert masked.loc[15, 1] == 10.0
    # Thin cell masked to NaN
    assert pd.isna(masked.loc[10, 1])
