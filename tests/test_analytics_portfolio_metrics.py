"""Tests for src.analytics.portfolio_metrics — F15, F16, F17, F18.

LOAD-BEARING:
  - test_calmar_uses_simple_not_geometric_annualization (memoir
    §21.4 F15 REVISED — drift detector vs CAGR)
  - test_sortino_divides_by_N_total_not_N_downside (memoir §21.4
    F17 REVISED — drift detector vs downside-only N)
  - test_sortino_squared_term_uses_target_offset (F17 REVISED
    second half — wrong at non-zero target if the offset is
    dropped)
  - test_ulcer_index_is_in_pct_units (memoir F16 scale convention)
  - test_max_drawdown_inr_is_positive_rupee_amount
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from src.analytics.portfolio import (
    cycle_pnl_series,
    drawdown_series,
    equity_curve,
)
from src.analytics.portfolio_metrics import (
    DEFAULT_PERIODS_PER_YEAR,
    ULCER_PCT_SCALE,
    calmar,
    cycle_returns,
    max_drawdown_inr,
    simple_annualized_return,
    sortino,
    ulcer_index,
)


# ============================================================
# cycle_returns
# ============================================================

def test_cycle_returns_divides_by_starting_capital():
    """Per-cycle simple return = cycle_pnl / starting_capital
    (equal-margin no-reinvest convention)."""
    pnl = pd.Series([10_000.0, -5_000.0, 20_000.0])
    r = cycle_returns(pnl, starting_capital=100_000.0)
    assert r.tolist() == pytest.approx([0.10, -0.05, 0.20])
    assert r.name == "cycle_return"


def test_cycle_returns_empty_input_returns_empty():
    assert cycle_returns(pd.Series([], dtype="float64"), 100_000.0).empty


def test_cycle_returns_rejects_non_positive_starting_capital():
    pnl = pd.Series([1000.0])
    with pytest.raises(ValueError, match="starting_capital must be > 0"):
        cycle_returns(pnl, -1.0)


def test_cycle_returns_rejects_non_series():
    with pytest.raises(TypeError, match="must be pd.Series"):
        cycle_returns([1000.0, 2000.0], 100_000.0)


# ============================================================
# F15 — simple_annualized_return + Calmar
# ============================================================

def test_simple_annualized_return_pin():
    """24-cycle book; cycle P&L flat ₹1000/cycle on ₹100k start.
    Post-2026-06-06 prepend fix:
      equity = [100k, 101k, 102k, ..., 124k] (length 25)
      n_cycles = len - 1 = 24
      total return = (124k - 100k) / 100k = 0.24
      annualized = 0.24 * (12 / 24) = 0.12 (= 12%/yr)
    Pin this hand-arithmetic so a future refactor can't drift."""
    pnl = pd.Series([1_000.0] * 24)
    eq = equity_curve(pnl, starting_capital=100_000.0)
    ann = simple_annualized_return(eq, periods_per_year=12)
    assert ann == pytest.approx(0.12, abs=1e-9)


def test_calmar_uses_simple_not_geometric_annualization():
    """LOAD-BEARING memoir F15 REVISED pin. 24-cycle (= 2-year)
    book, fixed +₹2k/cycle on ₹100k starting:
      total simple return = 48,000 / 100,000 = 0.48
      simple annualized   = 0.48 × (12/24) = 0.24
      CAGR (geometric)    = 1.48^(1/2) - 1 ≈ 0.2166
    On a multi-year span the two diverge (~2.4 pp). Drift
    detector pinned."""
    pnl = pd.Series([2_000.0] * 24)
    eq = equity_curve(pnl, starting_capital=100_000.0)
    ann = simple_annualized_return(eq)
    assert ann == pytest.approx(0.24, abs=1e-9)
    # Drift detector: simple ≠ geometric CAGR on a multi-year span.
    n_cycles = len(eq) - 1
    years = n_cycles / 12.0
    geometric = (eq.iloc[-1] / eq.iloc[0]) ** (1.0 / years) - 1.0
    assert abs(ann - geometric) > 0.02


def test_calmar_basic():
    """4 cycles: +10k, +15k, -40k, +20k on ₹100k starting.
    Post-prepend:
      equity = [100k, 110k, 125k, 85k, 105k]
      cummax = [100k, 110k, 125k, 125k, 125k]
      DD %   = [0, 0, 0, -0.32, -0.16]
      max DD = 0.32
      total return = 5,000 / 100,000 = 0.05
      annualized = 0.05 * (12 / 4) = 0.15
      Calmar = 0.15 / 0.32 ≈ 0.46875"""
    pnl = pd.Series([10_000.0, 15_000.0, -40_000.0, 20_000.0])
    eq = equity_curve(pnl, starting_capital=100_000.0)
    c = calmar(eq, periods_per_year=12)
    assert c == pytest.approx(0.15 / 0.32, abs=1e-9)


def test_calmar_inf_on_monotone_up_curve():
    """Max DD == 0 → Calmar = inf."""
    pnl = pd.Series([1_000.0] * 12)
    eq = equity_curve(pnl, starting_capital=100_000.0)
    assert calmar(eq) == float("inf")


def test_calmar_negative_when_book_loses_money():
    """Losing book → annualized return < 0 → Calmar < 0."""
    pnl = pd.Series([-2_000.0, -3_000.0, 1_000.0, -1_000.0])
    eq = equity_curve(pnl, starting_capital=100_000.0)
    c = calmar(eq, periods_per_year=12)
    assert c < 0


def test_calmar_empty_curve_returns_nan():
    eq = pd.Series([], dtype="float64")
    assert math.isnan(calmar(eq))


def test_simple_annualized_return_empty_returns_nan():
    assert math.isnan(simple_annualized_return(
        pd.Series([], dtype="float64"),
    ))


def test_simple_annualized_return_length_one_returns_nan():
    """Only the t=0 prepended row, no cycles → no return."""
    eq = pd.Series([100_000.0])
    assert math.isnan(simple_annualized_return(eq))


def test_simple_annualized_return_rejects_invalid_periods():
    pnl = pd.Series([1_000.0] * 12)
    eq = equity_curve(pnl, starting_capital=100_000.0)
    with pytest.raises(ValueError, match="periods_per_year must be > 0"):
        simple_annualized_return(eq, periods_per_year=0)


# ============================================================
# F16 — Ulcer Index
# ============================================================

def test_ulcer_index_is_in_pct_units():
    """LOAD-BEARING memoir F16 convention: Ulcer in % units.
    Equity [100, 90, 100, 90, 100] (constant 10% dips):
      cummax = [100, 100, 100, 100, 100]
      DD frac = [0, -0.10, 0, -0.10, 0]
      DD %    = [0, -10, 0, -10, 0]
      RMS²    = (0 + 100 + 0 + 100 + 0) / 5 = 40
      Ulcer   = √40 ≈ 6.32 (% units)
    """
    eq = pd.Series([100.0, 90.0, 100.0, 90.0, 100.0])
    u = ulcer_index(eq)
    assert u == pytest.approx(math.sqrt(40), abs=1e-9)


def test_ulcer_index_zero_on_monotone_up_equity():
    """No drawdown ever → Ulcer = 0 (the best possible)."""
    eq = pd.Series([100.0, 110.0, 120.0, 130.0])
    assert ulcer_index(eq) == 0.0


def test_ulcer_index_empty_returns_nan():
    """Empty input → NaN (no equity, no metric)."""
    assert math.isnan(ulcer_index(pd.Series([], dtype="float64")))


def test_ulcer_index_rejects_non_series():
    with pytest.raises(TypeError, match="must be pd.Series"):
        ulcer_index([100.0, 90.0])


# ============================================================
# F17 — Sortino (REVISED standard TDD)
# ============================================================

def test_sortino_divides_by_N_total_not_N_downside():
    """LOAD-BEARING memoir F17 REVISED pin (drift detector vs
    the original downside-only-N bug).

    Returns [0.10, 0.20, -0.10, 0.30, -0.05]:
      mean = 0.09; excess (target=0) = 0.09
      annualized excess = 0.09 × 12 = 1.08
      downside (clipped) = [0, 0, -0.10, 0, -0.05]
      squared           = [0, 0, 0.01, 0, 0.0025]
      mean over N=5     = 0.0125 / 5 = 0.0025
      TDD = √(0.0025 × 12) = √0.03 ≈ 0.1732
      Sortino = 1.08 / 0.1732 ≈ 6.2354

    If denominator were N_downside (=2):
      mean would be 0.0125/2 = 0.00625;
      TDD = √(0.00625 × 12) = √0.075 ≈ 0.2739
      Sortino_wrong = 1.08 / 0.2739 ≈ 3.943

    Test pins the CORRECT (N_total) version."""
    r = pd.Series([0.10, 0.20, -0.10, 0.30, -0.05])
    s = sortino(r, target=0.0, periods_per_year=12)
    expected = (0.09 * 12) / math.sqrt(0.0025 * 12)
    assert s == pytest.approx(expected, abs=1e-9)


def test_sortino_squared_term_uses_target_offset():
    """LOAD-BEARING memoir F17 REVISED second half.
    With target=0.01 (1% per cycle minimum acceptable):
      r = [0.05, -0.02, 0.03, -0.01, 0.02]
      excess = (mean - target) × periods
             = (0.014 - 0.01) × 12 = 0.048
      (r - target) clipped to ≤ 0:
             = [0, -0.03, 0, -0.02, 0]
      squared = [0, 0.0009, 0, 0.0004, 0]
      mean / N=5 = 0.00026
      TDD = √(0.00026 × 12) ≈ 0.0559
      Sortino = 0.048 / 0.0559 ≈ 0.859

    If squared term were (r alone) — the F17 original-bug
    version — at non-zero target it would compute (0.02)² for
    r=-0.01 (negative-but-≥-target after offset, but pre-offset
    code might handle differently). Confirm shape: test runs the
    REVISED formula end-to-end on a known target."""
    r = pd.Series([0.05, -0.02, 0.03, -0.01, 0.02])
    s = sortino(r, target=0.01, periods_per_year=12)
    excess = (0.014 - 0.01) * 12
    tdd = math.sqrt(((0 + 0.0009 + 0 + 0.0004 + 0) / 5) * 12)
    assert s == pytest.approx(excess / tdd, abs=1e-9)


def test_sortino_inf_when_no_downside():
    """All returns ≥ target → TDD = 0 → Sortino = inf."""
    r = pd.Series([0.10, 0.20, 0.05, 0.15])
    assert sortino(r, target=0.0) == float("inf")


def test_sortino_empty_returns_nan():
    assert math.isnan(sortino(pd.Series([], dtype="float64")))


def test_sortino_higher_is_better():
    """Two books with same mean return; one has a fatter
    left-tail. The fatter-tail one should have LOWER Sortino."""
    smooth = pd.Series([0.02, 0.02, 0.02, 0.02, 0.02, 0.02])
    rough = pd.Series([0.05, 0.05, 0.05, -0.05, -0.05, 0.07])
    # Same mean (0.02), different variance shape.
    assert sortino(smooth) > sortino(rough)


def test_sortino_rejects_non_series():
    with pytest.raises(TypeError, match="must be pd.Series"):
        sortino([0.01, -0.02])


# ============================================================
# F18 — Max DD ₹
# ============================================================

def test_max_drawdown_inr_is_positive_rupee_amount():
    """abs(drawdown_series.min()) → positive number.
    Equity [100, 120, 80, 90, 130] → DD [0, 0, -40, -30, 0] →
    max DD ₹ = 40 (POSITIVE)."""
    eq = pd.Series([100.0, 120.0, 80.0, 90.0, 130.0])
    assert max_drawdown_inr(eq) == 40.0


def test_max_drawdown_inr_zero_on_monotone_up_equity():
    """No drawdown → 0 (NOT NaN — operator-facing card)."""
    eq = pd.Series([100.0, 110.0, 120.0])
    assert max_drawdown_inr(eq) == 0.0


def test_max_drawdown_inr_empty_returns_zero():
    """Empty equity → 0 (NOT NaN — keeps the headline card
    rendering cleanly when there are no trades yet)."""
    assert max_drawdown_inr(pd.Series([], dtype="float64")) == 0.0


def test_max_drawdown_inr_rejects_non_series():
    with pytest.raises(TypeError, match="must be pd.Series"):
        max_drawdown_inr([100.0, 80.0])


# ============================================================
# Composed flow — full Phase 9.3 stack on real-shape data
# ============================================================

def test_full_metrics_stack_on_known_portfolio():
    """LOAD-BEARING end-to-end (post-prepend fix): F12 → F13 → F14
    → F15-F18 on a hand-checked 6-cycle portfolio.

    5 symbols per cycle; cycle P&L sums:
      [+₹6k, -₹3k, +₹10k, -₹15k, +₹8k, +₹4k]
    starting ₹100k.
      equity (prepend) = [100k, 106k, 103k, 113k, 98k, 106k, 110k]
      cummax           = [100k, 106k, 106k, 113k, 113k, 113k, 113k]
      DD ₹             = [0, 0, -3k, 0, -15k, -7k, -3k]
      DD %             = [0, 0, -0.0283, 0, -0.1327, -0.0619, -0.0265]
      max DD ₹ = 15,000
      max DD % ≈ 0.1327 (≈ 13.27%)

      total return = (110k - 100k) / 100k = 0.10
      n_cycles     = 6
      annualized   = 0.10 × (12 / 6) = 0.20 (20%/yr)
      Calmar       = 0.20 / 0.1327 ≈ 1.5073"""
    pnl_rows = []
    cycle_pnls = [6_000, -3_000, 10_000, -15_000, 8_000, 4_000]
    cycle_dates = [
        "2024-04-25", "2024-05-30", "2024-06-27",
        "2024-07-25", "2024-08-29", "2024-09-26",
    ]
    for date_str, cp in zip(cycle_dates, cycle_pnls):
        for sym_i in range(5):
            pnl_rows.append({
                "expiry": pd.Timestamp(date_str),
                "symbol": f"SYM{sym_i}",
                "net_pnl": cp / 5.0,
            })
    trades = pd.DataFrame(pnl_rows)

    pnl = cycle_pnl_series(trades)
    eq = equity_curve(pnl, starting_capital=100_000.0)

    # Metrics
    ann = simple_annualized_return(eq, periods_per_year=12)
    assert ann == pytest.approx(0.20, abs=1e-9)

    c = calmar(eq, periods_per_year=12)
    expected_calmar = 0.20 / (15_000 / 113_000)
    assert c == pytest.approx(expected_calmar, abs=1e-6)

    max_dd_inr = max_drawdown_inr(eq)
    assert max_dd_inr == 15_000.0

    u = ulcer_index(eq)
    # DD% = [0, 0, -0.0283, 0, -0.1327, -0.0619, -0.0265]
    # Scaled to %: [0, 0, -2.83, 0, -13.27, -6.19, -2.65]
    # RMS = √( sum_of_sq / 7 ) ≈ √(229.49/7) ≈ √32.78 ≈ 5.725
    assert 5.0 < u < 6.5

    r = cycle_returns(pnl, 100_000.0)
    s = sortino(r, target=0.0, periods_per_year=12)
    # Cycle returns: [0.06, -0.03, 0.10, -0.15, 0.08, 0.04]; mean = 0.0167
    # Excess annualized = 0.0167 × 12 = 0.20
    # Downside clipped: [0, -0.03, 0, -0.15, 0, 0]
    # Squared:          [0, 0.0009, 0, 0.0225, 0, 0]
    # mean over N=6 = 0.0039
    # TDD = √(0.0039 × 12) ≈ 0.2163
    # Sortino ≈ 0.20 / 0.2163 ≈ 0.925
    assert 0.7 < s < 1.2  # ballpark


# ============================================================
# Constants
# ============================================================

def test_constants_match_memoir_spec():
    assert DEFAULT_PERIODS_PER_YEAR == 12  # monthly cycles per §5
    assert ULCER_PCT_SCALE == 100.0  # memoir F16 unit convention
