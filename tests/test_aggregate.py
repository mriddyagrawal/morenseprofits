"""Tests for src.analytics.aggregate — Phase 5.1 per-stock × strategy
summary stats from the sweep parquet.

Load-bearing concerns:
  - Schema fidelity: SUMMARY_COLUMNS in canonical order; empty frame
    has the same schema (Phase-6 UI's groupby on zero-row sweeps
    doesn't KeyError).
  - Statistical honesty: n_trades surfaced on every row; MIN_N_FOR_RANKING
    pinned so consumers know the conventional cutoff (no silent drop).
  - Aggregation correctness: hand-derived numbers on a tiny fixture.
  - Determinism: sort by (strategy, symbol) ascending.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.analytics.aggregate import (
    MIN_N_FOR_RANKING,
    SUMMARY_COLUMNS,
    empty_summary_frame,
    summarize_by_stock_strategy,
)


def _fixture(rows):
    """Build a minimal results-frame-shape DataFrame with just the
    columns the aggregator reads."""
    return pd.DataFrame(rows)


# ============================================================
# Schema fidelity
# ============================================================

def test_empty_summary_frame_has_canonical_schema():
    df = empty_summary_frame()
    assert list(df.columns) == list(SUMMARY_COLUMNS)
    assert len(df) == 0


def test_empty_input_yields_empty_canonical_frame():
    """Zero-row results in → zero-row out with canonical schema.
    Lets Phase-6 .groupby('strategy') on an empty sweep not KeyError."""
    df = summarize_by_stock_strategy(pd.DataFrame({
        "strategy": pd.Series(dtype="string"),
        "symbol": pd.Series(dtype="string"),
        "net_pnl": pd.Series(dtype="float64"),
        "roi_pct": pd.Series(dtype="float64"),
        "roi_pct_annualized": pd.Series(dtype="float64"),
    }))
    assert list(df.columns) == list(SUMMARY_COLUMNS)
    assert len(df) == 0


def test_output_columns_in_canonical_order():
    """Non-empty input → same column order. Phase-6 UI may render
    these columns directly; order must be stable."""
    df = summarize_by_stock_strategy(_fixture([
        {"strategy": "short_straddle", "symbol": "X",
         "net_pnl": 100.0, "roi_pct": 1.0, "roi_pct_annualized": 12.0},
    ]))
    assert list(df.columns) == list(SUMMARY_COLUMNS)


def test_missing_required_columns_raises():
    bad = pd.DataFrame({"strategy": ["x"], "symbol": ["y"]})  # missing pnl/roi
    with pytest.raises(ValueError, match="missing required columns"):
        summarize_by_stock_strategy(bad)


# ============================================================
# Aggregation correctness — hand-derived fixture
# ============================================================

def test_two_strategies_two_symbols_aggregated_correctly():
    """Hand-derive a small fixture to pin every aggregate column.

    Setup:
      short_straddle × RELIANCE: 3 trades — net [100, -50, 200]
        n=3, n_winning=2 (only -50 loses), win_rate=66.67%
        mean_net=83.33, median_net=100
        roi_pct = [1.0, -0.5, 2.0] → mean 0.83, median 1.0
        roi_pct_annualized = [12.0, -6.0, 24.0] → mean 10.0, median 12.0
        worst_roi=-0.5, best_roi=2.0

      long_straddle × INFY: 1 trade — net [50]
        n=1, win_rate=100, worst=best=mean=median=0.5/6.0/0.5
    """
    df = summarize_by_stock_strategy(_fixture([
        {"strategy": "short_straddle", "symbol": "RELIANCE",
         "net_pnl": 100.0, "roi_pct": 1.0, "roi_pct_annualized": 12.0},
        {"strategy": "short_straddle", "symbol": "RELIANCE",
         "net_pnl": -50.0, "roi_pct": -0.5, "roi_pct_annualized": -6.0},
        {"strategy": "short_straddle", "symbol": "RELIANCE",
         "net_pnl": 200.0, "roi_pct": 2.0, "roi_pct_annualized": 24.0},
        {"strategy": "long_straddle", "symbol": "INFY",
         "net_pnl": 50.0, "roi_pct": 0.5, "roi_pct_annualized": 6.0},
    ]))

    assert len(df) == 2
    # Sorted by (strategy, symbol) → long_straddle first, then short_straddle
    assert df.iloc[0]["strategy"] == "long_straddle"
    assert df.iloc[0]["symbol"] == "INFY"
    assert df.iloc[0]["n_trades"] == 1
    assert df.iloc[0]["n_winning"] == 1
    assert df.iloc[0]["win_rate_pct"] == 100.0

    short = df.iloc[1]
    assert short["strategy"] == "short_straddle"
    assert short["symbol"] == "RELIANCE"
    assert short["n_trades"] == 3
    assert short["n_winning"] == 2
    assert short["win_rate_pct"] == pytest.approx(200.0 / 3.0)
    assert short["mean_net_pnl"] == pytest.approx(250.0 / 3.0)
    assert short["median_net_pnl"] == 100.0
    assert short["mean_roi_pct"] == pytest.approx(2.5 / 3.0)
    assert short["median_roi_pct"] == 1.0
    assert short["mean_roi_pct_annualized"] == pytest.approx(30.0 / 3.0)
    assert short["median_roi_pct_annualized"] == 12.0
    assert short["worst_roi_pct"] == -0.5
    assert short["best_roi_pct"] == 2.0


# ============================================================
# Sample-N transparency
# ============================================================

def test_n_trades_surfaced_for_all_rows_including_small_samples():
    """n_trades MUST be present on every row even when small. The
    aggregator does NOT silently drop small samples — consumers can
    filter via ``n_trades >= MIN_N_FOR_RANKING``. Honesty over
    convenience: user explicitly wanted to see sample sizes."""
    df = summarize_by_stock_strategy(_fixture([
        {"strategy": "short_straddle", "symbol": "X",
         "net_pnl": 1.0, "roi_pct": 0.1, "roi_pct_annualized": 1.0},
    ]))
    assert len(df) == 1
    assert df.iloc[0]["n_trades"] == 1  # NOT dropped
    # Convention: MIN_N_FOR_RANKING is the consumer-side cutoff
    assert df.iloc[0]["n_trades"] < MIN_N_FOR_RANKING


def test_min_n_for_ranking_is_5():
    """5 is the convention pinned. A change to the constant should
    show as a test diff so the threshold is intentional, not silent."""
    assert MIN_N_FOR_RANKING == 5


# ============================================================
# Determinism
# ============================================================

def test_same_input_same_output(monkeypatch):
    """Same rows in any order → same aggregated output. Sort by
    (strategy, symbol) drives the determinism."""
    rows_a = [
        {"strategy": "A", "symbol": "Y",
         "net_pnl": 1.0, "roi_pct": 0.1, "roi_pct_annualized": 1.0},
        {"strategy": "B", "symbol": "X",
         "net_pnl": 2.0, "roi_pct": 0.2, "roi_pct_annualized": 2.0},
        {"strategy": "A", "symbol": "X",
         "net_pnl": 3.0, "roi_pct": 0.3, "roi_pct_annualized": 3.0},
    ]
    rows_b = list(reversed(rows_a))  # different input order
    df_a = summarize_by_stock_strategy(_fixture(rows_a))
    df_b = summarize_by_stock_strategy(_fixture(rows_b))
    pd.testing.assert_frame_equal(df_a, df_b)
    # And the sort key is consistent
    assert list(zip(df_a["strategy"], df_a["symbol"])) == [
        ("A", "X"), ("A", "Y"), ("B", "X"),
    ]


# ============================================================
# Edge cases
# ============================================================

def test_zero_win_rate_when_all_lose():
    df = summarize_by_stock_strategy(_fixture([
        {"strategy": "S", "symbol": "X",
         "net_pnl": -10.0, "roi_pct": -0.1, "roi_pct_annualized": -1.0},
        {"strategy": "S", "symbol": "X",
         "net_pnl": -20.0, "roi_pct": -0.2, "roi_pct_annualized": -2.0},
    ]))
    assert df.iloc[0]["n_winning"] == 0
    assert df.iloc[0]["win_rate_pct"] == 0.0
    assert df.iloc[0]["worst_roi_pct"] == -0.2
    assert df.iloc[0]["best_roi_pct"] == -0.1


def test_perfect_win_rate_when_all_win():
    df = summarize_by_stock_strategy(_fixture([
        {"strategy": "S", "symbol": "X",
         "net_pnl": 10.0, "roi_pct": 0.1, "roi_pct_annualized": 1.0},
        {"strategy": "S", "symbol": "X",
         "net_pnl": 20.0, "roi_pct": 0.2, "roi_pct_annualized": 2.0},
    ]))
    assert df.iloc[0]["n_winning"] == 2
    assert df.iloc[0]["win_rate_pct"] == 100.0


def test_zero_net_pnl_does_not_count_as_winning():
    """net_pnl > 0 is winning; exactly zero (rare, but possible after
    slippage exactly offsets) counts as a loss/breakeven, NOT a win.
    Pin so a future ``>= 0`` typo would be caught."""
    df = summarize_by_stock_strategy(_fixture([
        {"strategy": "S", "symbol": "X",
         "net_pnl": 0.0, "roi_pct": 0.0, "roi_pct_annualized": 0.0},
        {"strategy": "S", "symbol": "X",
         "net_pnl": 100.0, "roi_pct": 1.0, "roi_pct_annualized": 12.0},
    ]))
    assert df.iloc[0]["n_winning"] == 1  # only the +100
    assert df.iloc[0]["win_rate_pct"] == 50.0
