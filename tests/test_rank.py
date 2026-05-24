"""Tests for src.analytics.rank — Phase-5.5 leaderboard.

Load-bearing concerns:
  - Rank column is 1-indexed and dense (no gaps).
  - Sort by configurable metric, descending by default.
  - min_n filter suppresses thin samples (statistical honesty); the
    suppressed rows do NOT appear in the output (vs aggregate which
    surfaces them — different layers, different contracts).
  - Tiebreaker: (strategy, symbol) lex, so identical metrics rank
    deterministically.
  - top_n truncates after ranking.
  - MULTIPLE_COMPARISONS_CAVEAT is pinned as a real constant Phase-6
    can render verbatim.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.analytics.aggregate import (
    MIN_N_FOR_RANKING,
    summarize_by_stock_strategy,
)
from src.analytics.rank import (
    DEFAULT_RANK_METRIC,
    MULTIPLE_COMPARISONS_CAVEAT,
    rank_strategies,
)


def _trade(strategy, symbol, net_pnl=100.0, roi_pct=1.0, roi_pct_annualized=12.0):
    return {
        "strategy": strategy, "symbol": symbol,
        "net_pnl": net_pnl, "roi_pct": roi_pct,
        "roi_pct_annualized": roi_pct_annualized,
    }


def _summary_from(rows):
    """Helper: aggregate raw trades → summary frame → input to ranker."""
    return summarize_by_stock_strategy(pd.DataFrame(rows))


# ============================================================
# Basic ranking shape
# ============================================================

def test_rank_column_is_1_indexed_dense():
    rows = []
    # 3 (strategy, symbol) pairs with different annualized ROIs.
    # Pad with 6+ trades each so min_n=5 doesn't suppress.
    for strat, annualized in [("A", 30.0), ("B", 10.0), ("C", 20.0)]:
        for _ in range(6):
            rows.append(_trade(strat, "X",
                               roi_pct_annualized=annualized))
    out = rank_strategies(_summary_from(rows))
    assert "rank" in out.columns
    assert list(out["rank"]) == [1, 2, 3]


def test_descending_by_default_higher_is_better():
    """Highest median_roi_pct_annualized → rank 1."""
    rows = [
        _trade("A", "X", roi_pct_annualized=10.0),
        _trade("B", "X", roi_pct_annualized=50.0),
        _trade("C", "X", roi_pct_annualized=30.0),
    ] * 6  # min_n satisfaction
    out = rank_strategies(_summary_from(rows), min_n=0)
    # Note: descending by median_roi_pct_annualized
    # B (50) → rank 1, C (30) → rank 2, A (10) → rank 3
    assert out.iloc[0]["strategy"] == "B"
    assert out.iloc[1]["strategy"] == "C"
    assert out.iloc[2]["strategy"] == "A"


def test_ascending_flips_to_worst_first():
    """For 'what should I AVOID' use case."""
    rows = [
        _trade("A", "X", roi_pct_annualized=10.0),
        _trade("B", "X", roi_pct_annualized=50.0),
        _trade("C", "X", roi_pct_annualized=30.0),
    ] * 6
    out = rank_strategies(_summary_from(rows), ascending=True, min_n=0)
    # Ascending → A (10) first
    assert out.iloc[0]["strategy"] == "A"
    assert out.iloc[2]["strategy"] == "B"


def test_by_kwarg_selects_metric():
    """Default = median_roi_pct_annualized. Specifying ``by`` picks
    a different metric (e.g., win_rate_pct, or total_net_pnl)."""
    rows = []
    # Strategy A: 6 trades, all small wins
    for _ in range(6):
        rows.append(_trade("A", "X", net_pnl=10.0, roi_pct=0.1, roi_pct_annualized=1.2))
    # Strategy B: 6 trades, all huge but barely profitable
    for _ in range(6):
        rows.append(_trade("B", "X", net_pnl=10_000.0, roi_pct=0.05, roi_pct_annualized=0.6))
    # By default (annualized ROI): A wins (1.2 > 0.6)
    by_roi = rank_strategies(_summary_from(rows))
    assert by_roi.iloc[0]["strategy"] == "A"
    # By total_net_pnl: B wins (60000 > 60)
    by_pnl = rank_strategies(_summary_from(rows), by="total_net_pnl")
    assert by_pnl.iloc[0]["strategy"] == "B"


# ============================================================
# min_n thin-sample suppression
# ============================================================

def test_min_n_suppresses_thin_samples_from_output():
    """Rows with n_trades < min_n do NOT appear in the ranker output.
    Different from aggregate layer which surfaces them — the ranker
    is the consumer-side filter."""
    rows = (
        # A: 6 trades (passes min_n=5)
        [_trade("A", "X", roi_pct_annualized=10.0)] * 6
        # B: 2 trades (FAILS min_n=5)
        + [_trade("B", "X", roi_pct_annualized=100.0)] * 2
    )
    out = rank_strategies(_summary_from(rows))
    # B has the higher metric but is suppressed
    assert "B" not in out["strategy"].tolist()
    assert "A" in out["strategy"].tolist()


def test_min_n_zero_disables_suppression():
    """``min_n=0`` includes every row regardless of n_trades."""
    rows = [_trade("S", "X", roi_pct_annualized=10.0)]  # n=1
    out = rank_strategies(_summary_from(rows), min_n=0)
    assert len(out) == 1


def test_min_n_default_is_5():
    """Pin the default convention. Same MIN_N_FOR_RANKING as
    aggregate.py."""
    rows = [_trade("S", "X")] * 4  # n=4, just below the threshold
    out = rank_strategies(_summary_from(rows))
    assert len(out) == 0
    rows = [_trade("S", "X")] * 5  # n=5, exactly at threshold
    out = rank_strategies(_summary_from(rows))
    assert len(out) == 1


# ============================================================
# Tiebreaker determinism
# ============================================================

def test_tiebreaker_by_strategy_then_symbol():
    """Identical metric values → (strategy, symbol) lex order. Pins
    determinism across re-runs / input shuffles."""
    rows = []
    # Two pairs with identical annualized ROI (= 10)
    for strat, sym in [("Z", "X"), ("A", "Y"), ("A", "X")]:
        for _ in range(6):
            rows.append(_trade(strat, sym, roi_pct_annualized=10.0))
    out = rank_strategies(_summary_from(rows))
    # All have same median; lex tiebreaker by (strategy, symbol)
    # (A, X), (A, Y), (Z, X)
    assert list(zip(out["strategy"], out["symbol"])) == [
        ("A", "X"), ("A", "Y"), ("Z", "X"),
    ]


# ============================================================
# top_n truncation
# ============================================================

def test_top_n_truncates_after_ranking():
    rows = []
    for strat, roi in [("A", 30.0), ("B", 10.0), ("C", 20.0), ("D", 40.0)]:
        for _ in range(6):
            rows.append(_trade(strat, "X", roi_pct_annualized=roi))
    out = rank_strategies(_summary_from(rows), top_n=2)
    assert len(out) == 2
    # Top 2 by annualized ROI: D (40), A (30)
    assert list(out["strategy"]) == ["D", "A"]


def test_top_n_zero_returns_empty():
    rows = [_trade("S", "X")] * 6
    out = rank_strategies(_summary_from(rows), top_n=0)
    assert len(out) == 0


def test_top_n_larger_than_population_returns_all():
    rows = [_trade("S", "X")] * 6
    out = rank_strategies(_summary_from(rows), top_n=99)
    assert len(out) == 1


# ============================================================
# Validation
# ============================================================

def test_missing_n_trades_raises():
    bad = pd.DataFrame({"strategy": ["s"], "median_roi_pct_annualized": [1.0]})
    with pytest.raises(ValueError, match="n_trades"):
        rank_strategies(bad)


def test_unknown_by_metric_raises():
    rows = [_trade("S", "X")] * 6
    with pytest.raises(ValueError, match="rank metric"):
        rank_strategies(_summary_from(rows), by="nonexistent_column")


def test_negative_min_n_raises():
    with pytest.raises(ValueError, match="min_n"):
        rank_strategies(_summary_from([_trade("S", "X")] * 6), min_n=-1)


def test_negative_top_n_raises():
    with pytest.raises(ValueError, match="top_n"):
        rank_strategies(_summary_from([_trade("S", "X")] * 6), top_n=-1)


# ============================================================
# Empty / edge cases
# ============================================================

def test_empty_input_returns_empty_with_rank_column():
    """Empty summary in → empty ranked frame out (no KeyError on
    downstream `.iloc[0]` style code; consumer should check len)."""
    empty = pd.DataFrame({
        "strategy": pd.Series(dtype="string"),
        "symbol": pd.Series(dtype="string"),
        "n_trades": pd.Series(dtype="int64"),
        "median_roi_pct_annualized": pd.Series(dtype="float64"),
    })
    out = rank_strategies(empty)
    assert "rank" in out.columns
    assert len(out) == 0


# ============================================================
# Multiple-comparisons caveat
# ============================================================

def test_multiple_comparisons_caveat_is_real_string():
    """Pin the caveat as a non-empty string Phase-6 UI can render
    verbatim. Catch a future refactor that accidentally clears it."""
    assert isinstance(MULTIPLE_COMPARISONS_CAVEAT, str)
    assert len(MULTIPLE_COMPARISONS_CAVEAT) > 100
    assert "selection bias" in MULTIPLE_COMPARISONS_CAVEAT.lower()


def test_default_rank_metric_is_annualized_median():
    """Phase-6 default ranking surface uses this. Pin the choice so a
    change to a different default (e.g. mean) is intentional and
    visible as a test diff."""
    assert DEFAULT_RANK_METRIC == "median_roi_pct_annualized"
