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
    MONTHLY_SUMMARY_COLUMNS,
    SUMMARY_COLUMNS,
    YEARLY_SUMMARY_COLUMNS,
    empty_monthly_summary_frame,
    empty_summary_frame,
    empty_yearly_summary_frame,
    summarize_by_month,
    summarize_by_stock_strategy,
    summarize_by_year,
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


# ============================================================
# Risk-adjusted columns — std + total_net_pnl (p5.5 prep)
# ============================================================

def test_total_net_pnl_is_sum_of_net_pnl():
    """Aggregate strategy P&L = sum across all trades in the bucket.
    Cross-checks operator's "did this make money overall?" headline."""
    df = summarize_by_stock_strategy(_fixture([
        {"strategy": "S", "symbol": "X",
         "net_pnl": 100.0, "roi_pct": 1.0, "roi_pct_annualized": 12.0},
        {"strategy": "S", "symbol": "X",
         "net_pnl": -30.0, "roi_pct": -0.3, "roi_pct_annualized": -3.6},
        {"strategy": "S", "symbol": "X",
         "net_pnl": 200.0, "roi_pct": 2.0, "roi_pct_annualized": 24.0},
    ]))
    # 100 + -30 + 200 = 270
    assert df.iloc[0]["total_net_pnl"] == 270.0


def test_std_roi_pct_computed_with_ddof_zero():
    """Sample std (pandas default ddof=1) is NaN for n=1; the aggregator
    uses population std (ddof=0) so a single-trade group gets std=0,
    not NaN. Single observation has no variation by definition.

    Three trades [1.0, 2.0, 3.0]: population variance = ((1-2)²+(2-2)²+(3-2)²)/3 = 0.6667
    → std = sqrt(0.6667) ≈ 0.8165."""
    df = summarize_by_stock_strategy(_fixture([
        {"strategy": "S", "symbol": "X",
         "net_pnl": 100.0, "roi_pct": 1.0, "roi_pct_annualized": 12.0},
        {"strategy": "S", "symbol": "X",
         "net_pnl": 200.0, "roi_pct": 2.0, "roi_pct_annualized": 24.0},
        {"strategy": "S", "symbol": "X",
         "net_pnl": 300.0, "roi_pct": 3.0, "roi_pct_annualized": 36.0},
    ]))
    assert df.iloc[0]["std_roi_pct"] == pytest.approx(0.8164965, abs=1e-6)
    # Annualized std preserves the same multiplier the means have
    assert df.iloc[0]["std_roi_pct_annualized"] == pytest.approx(9.79795, abs=1e-4)


def test_std_is_zero_for_single_trade_not_nan():
    """LOAD-BEARING for p5.5 Sharpe-like ranking: a single-trade group
    must not produce NaN std (which would break sort_values). Pin
    std=0 explicitly so a future change back to ddof=1 is caught."""
    df = summarize_by_stock_strategy(_fixture([
        {"strategy": "S", "symbol": "X",
         "net_pnl": 100.0, "roi_pct": 1.0, "roi_pct_annualized": 12.0},
    ]))
    assert df.iloc[0]["std_roi_pct"] == 0.0
    assert df.iloc[0]["std_roi_pct_annualized"] == 0.0


def test_yearly_summary_inherits_new_columns():
    """YEARLY_SUMMARY_COLUMNS extends SUMMARY_COLUMNS[2:], so std +
    total_net_pnl appear automatically."""
    assert "total_net_pnl" in YEARLY_SUMMARY_COLUMNS
    assert "std_roi_pct" in YEARLY_SUMMARY_COLUMNS
    assert "std_roi_pct_annualized" in YEARLY_SUMMARY_COLUMNS


def test_monthly_summary_inherits_new_columns():
    assert "total_net_pnl" in MONTHLY_SUMMARY_COLUMNS
    assert "std_roi_pct" in MONTHLY_SUMMARY_COLUMNS
    assert "std_roi_pct_annualized" in MONTHLY_SUMMARY_COLUMNS


# ============================================================
# summarize_by_year — Phase 5.3 trend aggregator
# ============================================================

def _yr(strategy, symbol, year, net_pnl, roi_pct, roi_pct_annualized):
    """Convenience builder — `expiry` is what drives `year`."""
    return {
        "strategy": strategy, "symbol": symbol,
        "expiry": pd.Timestamp(f"{year}-06-15"),  # mid-year placeholder
        "net_pnl": net_pnl, "roi_pct": roi_pct,
        "roi_pct_annualized": roi_pct_annualized,
    }


def test_yearly_empty_frame_has_canonical_schema():
    df = empty_yearly_summary_frame()
    assert list(df.columns) == list(YEARLY_SUMMARY_COLUMNS)
    assert len(df) == 0
    assert "year" in df.columns
    assert str(df["year"].dtype) == "int64"


def test_yearly_columns_extend_summary_with_year():
    """The yearly schema = (strategy, symbol, year) + per-row stats.
    Pin the exact column shape so a future refactor that drops 'year'
    or reorders the prefix is visible."""
    assert YEARLY_SUMMARY_COLUMNS[:3] == ("strategy", "symbol", "year")
    # Stat columns are identical to SUMMARY_COLUMNS[2:]
    assert YEARLY_SUMMARY_COLUMNS[3:] == SUMMARY_COLUMNS[2:]


def test_yearly_groups_separately_across_years():
    """Same (strategy, symbol) across 3 different years → 3 output
    rows. The decay question depends on this row-per-year shape."""
    df = summarize_by_year(_fixture([
        _yr("short_straddle", "X", 2022, 100.0, 1.0, 12.0),
        _yr("short_straddle", "X", 2022, 200.0, 2.0, 24.0),
        _yr("short_straddle", "X", 2023, 50.0,  0.5, 6.0),
        _yr("short_straddle", "X", 2024, -100.0, -1.0, -12.0),
    ]))
    assert len(df) == 3
    assert list(df["year"]) == [2022, 2023, 2024]
    # 2022: 2 trades, both winning
    row_2022 = df[df["year"] == 2022].iloc[0]
    assert row_2022["n_trades"] == 2
    assert row_2022["n_winning"] == 2
    assert row_2022["win_rate_pct"] == 100.0
    assert row_2022["median_roi_pct_annualized"] == 18.0
    # 2024: 1 trade, losing
    row_2024 = df[df["year"] == 2024].iloc[0]
    assert row_2024["n_trades"] == 1
    assert row_2024["win_rate_pct"] == 0.0


def test_yearly_decay_visible_as_descending_median_roi():
    """Hand-crafted decay scenario: 2022 median +20%, 2023 +10%, 2024
    +5%. The Phase-6 decay plot shows median_roi_pct_annualized along
    the y-axis as year increases; it should monotonically decline here.

    This pins the typical "is the strategy decaying" use case."""
    df = summarize_by_year(_fixture([
        _yr("S", "X", 2022, 200.0, 2.0, 20.0),
        _yr("S", "X", 2023, 100.0, 1.0, 10.0),
        _yr("S", "X", 2024, 50.0,  0.5, 5.0),
    ]))
    medians = list(df.sort_values("year")["median_roi_pct_annualized"])
    assert medians == [20.0, 10.0, 5.0]
    # Strictly monotonically decreasing — the decay signal
    assert medians[0] > medians[1] > medians[2]


def test_yearly_year_derived_from_expiry_not_entry_date():
    """SPECS convention: 'year of the trade' = expiry's year. A
    December-29 expiry traded in late November still counts as the
    expiry-year, NOT the entry-year. The decay analysis is keyed to
    when the trade settled, not when it opened."""
    df = summarize_by_year(_fixture([
        {**_yr("S", "X", 2024, 100.0, 1.0, 12.0),
         "expiry": pd.Timestamp("2024-12-31")},
        {**_yr("S", "X", 2024, 200.0, 2.0, 24.0),
         "expiry": pd.Timestamp("2024-01-25")},
    ]))
    # Both belong to year 2024 — one output row.
    assert len(df) == 1
    assert df.iloc[0]["year"] == 2024
    assert df.iloc[0]["n_trades"] == 2


def test_yearly_separate_symbols_get_separate_rows():
    """Different symbols in same year → separate rows."""
    df = summarize_by_year(_fixture([
        _yr("S", "RELIANCE", 2024, 100.0, 1.0, 12.0),
        _yr("S", "INFY",     2024, 200.0, 2.0, 24.0),
    ]))
    assert len(df) == 2
    assert set(df["symbol"]) == {"RELIANCE", "INFY"}


def test_yearly_empty_input_returns_canonical_empty_frame():
    df = summarize_by_year(pd.DataFrame({
        "strategy": pd.Series(dtype="string"),
        "symbol": pd.Series(dtype="string"),
        "expiry": pd.Series(dtype="datetime64[us]"),
        "net_pnl": pd.Series(dtype="float64"),
        "roi_pct": pd.Series(dtype="float64"),
        "roi_pct_annualized": pd.Series(dtype="float64"),
    }))
    assert list(df.columns) == list(YEARLY_SUMMARY_COLUMNS)
    assert len(df) == 0


def test_yearly_missing_expiry_column_raises():
    """Year derivation needs expiry — loud error if missing."""
    bad = pd.DataFrame([{
        "strategy": "s", "symbol": "x",
        "net_pnl": 1.0, "roi_pct": 1.0, "roi_pct_annualized": 1.0,
    }])
    with pytest.raises(ValueError, match="expiry"):
        summarize_by_year(bad)


def test_yearly_sample_size_surfaced_per_year():
    """Same MIN_N_FOR_RANKING discipline: n_trades surfaced per year
    so consumers can suppress thin-sample years from a decay trend."""
    df = summarize_by_year(_fixture([
        _yr("S", "X", 2022, 100.0, 1.0, 12.0),                # N=1 for 2022
        *[_yr("S", "X", 2023, 100.0, 1.0, 12.0) for _ in range(6)],  # N=6
    ]))
    sizes = dict(zip(df["year"], df["n_trades"]))
    assert sizes == {2022: 1, 2023: 6}
    # 2022's row is INCLUDED (no silent drop) — consumer-side filter
    assert (df["n_trades"] < MIN_N_FOR_RANKING).any()


# ============================================================
# summarize_by_month — Phase 5.4 seasonality aggregator
# ============================================================

def _mo(strategy, symbol, year, month, net_pnl, roi_pct, roi_pct_annualized):
    """Convenience builder — expiry on day 15 of (year, month)."""
    return {
        "strategy": strategy, "symbol": symbol,
        "expiry": pd.Timestamp(f"{year}-{month:02d}-15"),
        "net_pnl": net_pnl, "roi_pct": roi_pct,
        "roi_pct_annualized": roi_pct_annualized,
    }


def test_monthly_empty_frame_has_canonical_schema():
    df = empty_monthly_summary_frame()
    assert list(df.columns) == list(MONTHLY_SUMMARY_COLUMNS)
    assert len(df) == 0
    assert "month" in df.columns
    assert str(df["month"].dtype) == "int64"


def test_monthly_columns_extend_summary_with_month():
    assert MONTHLY_SUMMARY_COLUMNS[:3] == ("strategy", "symbol", "month")
    assert MONTHLY_SUMMARY_COLUMNS[3:] == SUMMARY_COLUMNS[2:]


def test_monthly_aggregates_across_years_within_same_month():
    """LOAD-BEARING: Jan-2022 + Jan-2023 + Jan-2024 all fold into the
    same ``month=1`` row. Seasonality is the orthogonal question to
    decay — decay holds the month fixed, seasonality folds across years."""
    df = summarize_by_month(_fixture([
        _mo("S", "X", 2022, 1, 100.0, 1.0, 12.0),
        _mo("S", "X", 2023, 1, 200.0, 2.0, 24.0),
        _mo("S", "X", 2024, 1, 300.0, 3.0, 36.0),
        _mo("S", "X", 2024, 7, 50.0, 0.5, 6.0),
    ]))
    # 2 rows: month=1 (3 trades) and month=7 (1 trade)
    assert len(df) == 2
    jan = df[df["month"] == 1].iloc[0]
    assert jan["n_trades"] == 3
    assert jan["median_roi_pct_annualized"] == 24.0  # median of [12, 24, 36]
    jul = df[df["month"] == 7].iloc[0]
    assert jul["n_trades"] == 1


def test_monthly_pins_seasonality_shape():
    """Hand-crafted seasonality: Q1 strong, Q3 weak — a Phase-6 bar
    chart of median_roi_pct_annualized by month will show this clearly."""
    rows = []
    # Q1 = jan, feb, mar — strong months
    for m in (1, 2, 3):
        rows.append(_mo("S", "X", 2024, m, 100.0, 1.0, 12.0))
    # Q3 = jul, aug, sep — weak months
    for m in (7, 8, 9):
        rows.append(_mo("S", "X", 2024, m, -50.0, -0.5, -6.0))
    df = summarize_by_month(_fixture(rows))
    assert len(df) == 6
    strong = df[df["month"].isin([1, 2, 3])]["median_roi_pct_annualized"]
    weak = df[df["month"].isin([7, 8, 9])]["median_roi_pct_annualized"]
    assert all(v == 12.0 for v in strong)
    assert all(v == -6.0 for v in weak)


def test_monthly_month_derived_from_expiry():
    """Expiry month, not entry_date month — same convention as
    summarize_by_year."""
    df = summarize_by_month(_fixture([
        # Two trades, expiry months 1 and 12 of 2024
        {**_mo("S", "X", 2024, 1, 100.0, 1.0, 12.0)},
        {**_mo("S", "X", 2024, 12, 200.0, 2.0, 24.0)},
    ]))
    assert set(df["month"]) == {1, 12}


def test_monthly_empty_input_returns_canonical_empty_frame():
    df = summarize_by_month(pd.DataFrame({
        "strategy": pd.Series(dtype="string"),
        "symbol": pd.Series(dtype="string"),
        "expiry": pd.Series(dtype="datetime64[us]"),
        "net_pnl": pd.Series(dtype="float64"),
        "roi_pct": pd.Series(dtype="float64"),
        "roi_pct_annualized": pd.Series(dtype="float64"),
    }))
    assert list(df.columns) == list(MONTHLY_SUMMARY_COLUMNS)
    assert len(df) == 0


def test_monthly_missing_expiry_raises():
    bad = pd.DataFrame([{
        "strategy": "s", "symbol": "x",
        "net_pnl": 1.0, "roi_pct": 1.0, "roi_pct_annualized": 1.0,
    }])
    with pytest.raises(ValueError, match="expiry"):
        summarize_by_month(bad)


def test_monthly_sort_order_ascending_by_month():
    """Months 1..12 ascending — natural reading order. Phase-6 bar
    charts depend on this for a left-to-right time axis."""
    df = summarize_by_month(_fixture([
        _mo("S", "X", 2024, 12, 1.0, 0.1, 1.0),
        _mo("S", "X", 2024, 1,  1.0, 0.1, 1.0),
        _mo("S", "X", 2024, 7,  1.0, 0.1, 1.0),
    ]))
    assert list(df["month"]) == [1, 7, 12]


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
