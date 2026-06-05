"""Tests for src.analytics.portfolio — F12, F13, F14 (+ DD%).

Pure-math tests on synthetic frames; no parquet I/O.

LOAD-BEARING:
  - test_cycle_pnl_sums_per_expiry (the F12 contract)
  - test_equity_curve_is_additive_not_geometric (memoir §7 sizing
    convention; geometric would compound and give different
    numbers)
  - test_drawdown_series_zero_at_new_highs (cummax behavior pin)
  - test_drawdown_pct_handles_zero_running_max (defensive
    divide-by-zero — ill-formed input shouldn't propagate inf)
  - test_equity_curve_then_drawdown_round_trip (composed flow:
    F12 → F13 → F14 on a known P&L stream → known DD)
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from src.analytics.portfolio import (
    DEFAULT_EXPIRY_COL,
    DEFAULT_PNL_COL,
    cycle_pnl_series,
    drawdown_pct_series,
    drawdown_series,
    equity_curve,
)


# ============================================================
# Fixtures
# ============================================================

def _trades(rows: list[tuple]) -> pd.DataFrame:
    """Build a per-trade frame with (expiry_str, symbol, net_pnl)
    tuples. Matches the sweep parquet column subset the aggregator
    reads."""
    return pd.DataFrame({
        "expiry": pd.to_datetime([r[0] for r in rows]),
        "symbol": [r[1] for r in rows],
        "net_pnl": [r[2] for r in rows],
    })


# ============================================================
# F12 — cycle_pnl_series
# ============================================================

def test_cycle_pnl_sums_per_expiry():
    """LOAD-BEARING F12 contract: per-expiry P&L sum across the
    5 symbols in a cycle."""
    df = _trades([
        ("2024-04-25", "RELIANCE", 5000.0),
        ("2024-04-25", "INFY",     3000.0),
        ("2024-04-25", "TCS",      -1000.0),
        ("2024-05-30", "RELIANCE", 2000.0),
        ("2024-05-30", "INFY",     -500.0),
    ])
    series = cycle_pnl_series(df)
    assert list(series.index) == [
        pd.Timestamp("2024-04-25"), pd.Timestamp("2024-05-30"),
    ]
    assert series.iloc[0] == pytest.approx(7000.0)
    assert series.iloc[1] == pytest.approx(1500.0)
    assert series.name == "cycle_pnl"


def test_cycle_pnl_sorts_by_expiry_ascending():
    """Output index is ascending regardless of input row order."""
    df = _trades([
        ("2024-05-30", "RELIANCE", 1000.0),
        ("2024-04-25", "INFY",     2000.0),
        ("2024-06-27", "TCS",      3000.0),
    ])
    series = cycle_pnl_series(df)
    assert list(series.index) == [
        pd.Timestamp("2024-04-25"),
        pd.Timestamp("2024-05-30"),
        pd.Timestamp("2024-06-27"),
    ]


def test_cycle_pnl_empty_frame_returns_empty_series():
    """Cold-portfolio edge case: no trades after filtering →
    empty series, NOT exception. Downstream equity_curve handles."""
    df = pd.DataFrame({
        "expiry": pd.Series(dtype="datetime64[us]"),
        "symbol": pd.Series(dtype="string"),
        "net_pnl": pd.Series(dtype="float64"),
    })
    series = cycle_pnl_series(df)
    assert series.empty
    assert series.dtype == np.float64


def test_cycle_pnl_none_returns_empty_series():
    """None defensive: no exception."""
    series = cycle_pnl_series(None)
    assert series.empty


def test_cycle_pnl_rejects_missing_columns():
    """Loud failure on schema mismatch — beats silent KeyError
    from downstream Series access."""
    df = pd.DataFrame({"net_pnl": [100.0]})
    with pytest.raises(ValueError, match="missing required columns"):
        cycle_pnl_series(df)


def test_cycle_pnl_rejects_non_dataframe():
    with pytest.raises(TypeError, match="must be pd.DataFrame"):
        cycle_pnl_series([{"expiry": "2024-04-25", "net_pnl": 100.0}])


def test_cycle_pnl_respects_custom_columns():
    """Override columns for diagnostic / cost-attribution use:
    sum gross_pnl instead of net_pnl."""
    df = pd.DataFrame({
        "expiry_dt": pd.to_datetime(["2024-04-25", "2024-04-25"]),
        "gross_pnl": [5000.0, 3000.0],
    })
    series = cycle_pnl_series(
        df, expiry_col="expiry_dt", pnl_col="gross_pnl",
    )
    assert series.iloc[0] == 8000.0


def test_cycle_pnl_does_not_dedup_duplicate_rows():
    """Per the docstring contract: the function does NOT dedup.
    Two identical (expiry, symbol) rows DOUBLE-COUNT. Caller
    must pre-filter to one row per (symbol, expiry). Pin this
    behavior so a future contributor doesn't accidentally
    introduce silent dedup."""
    df = _trades([
        ("2024-04-25", "RELIANCE", 5000.0),
        ("2024-04-25", "RELIANCE", 5000.0),  # duplicate
    ])
    series = cycle_pnl_series(df)
    assert series.iloc[0] == 10000.0


# ============================================================
# F13 — equity_curve (additive, NOT geometric)
# ============================================================

def test_equity_curve_is_additive_not_geometric():
    """LOAD-BEARING memoir §7 sizing convention pin: equal-margin
    no-reinvest → additive cumsum. Cycle P&L [1000, 2000, 3000]
    on starting=100000:
      Additive:  101000, 103000, 106000
      Geometric (compounded): 101000 → 103020 → 106110.6 (~2k drift)
    Test pins the additive path explicitly."""
    pnl = pd.Series(
        [1000.0, 2000.0, 3000.0],
        index=pd.to_datetime(["2024-04-25", "2024-05-30", "2024-06-27"]),
    )
    eq = equity_curve(pnl, starting_capital=100_000.0)
    assert eq.tolist() == [101_000.0, 103_000.0, 106_000.0]
    assert eq.name == "equity"


def test_equity_curve_preserves_index():
    """Output index matches input — downstream metrics align
    drawdown to the same expiry dates."""
    idx = pd.to_datetime(["2024-04-25", "2024-05-30", "2024-06-27"])
    pnl = pd.Series([100.0, 200.0, 300.0], index=idx)
    eq = equity_curve(pnl, starting_capital=10_000.0)
    assert list(eq.index) == list(idx)


def test_equity_curve_handles_losses():
    """Negative cycles drag equity below starting — no clamping."""
    pnl = pd.Series([5000.0, -8000.0, -3000.0])
    eq = equity_curve(pnl, starting_capital=100_000.0)
    assert eq.tolist() == [105_000.0, 97_000.0, 94_000.0]


def test_equity_curve_empty_input_returns_empty():
    pnl = pd.Series([], dtype="float64")
    eq = equity_curve(pnl, starting_capital=100_000.0)
    assert eq.empty


def test_equity_curve_rejects_non_positive_starting_capital():
    """Zero or negative starting capital is a programmer error."""
    pnl = pd.Series([1000.0])
    with pytest.raises(ValueError, match="starting_capital must be > 0"):
        equity_curve(pnl, starting_capital=0.0)
    with pytest.raises(ValueError, match="starting_capital must be > 0"):
        equity_curve(pnl, starting_capital=-1.0)


def test_equity_curve_rejects_non_series():
    with pytest.raises(TypeError, match="must be pd.Series"):
        equity_curve([1000.0, 2000.0], starting_capital=100_000.0)


# ============================================================
# F14 — drawdown_series (₹)
# ============================================================

def test_drawdown_series_zero_at_new_highs():
    """LOAD-BEARING F14 cummax pin: every cycle that sets a new
    high equity has DD = 0. Monotone-increasing equity → DD all
    zeros."""
    eq = pd.Series([100.0, 110.0, 125.0, 140.0])
    dd = drawdown_series(eq)
    assert dd.tolist() == [0.0, 0.0, 0.0, 0.0]
    assert dd.name == "drawdown_inr"


def test_drawdown_series_negative_underwater():
    """Equity [100, 120, 80, 90, 130] → cummax [100, 120, 120,
    120, 130] → DD [0, 0, -40, -30, 0]. Peak-to-trough max DD =
    ₹40 (at cycle 3)."""
    eq = pd.Series([100.0, 120.0, 80.0, 90.0, 130.0])
    dd = drawdown_series(eq)
    assert dd.tolist() == [0.0, 0.0, -40.0, -30.0, 0.0]
    # Peak-to-trough = abs(min).
    assert abs(dd.min()) == 40.0


def test_drawdown_series_constant_equity_is_zero():
    eq = pd.Series([100.0, 100.0, 100.0])
    dd = drawdown_series(eq)
    assert dd.tolist() == [0.0, 0.0, 0.0]


def test_drawdown_series_monotone_decreasing():
    """Equity [100, 90, 80, 70] → cummax stays at 100 → DD
    [0, -10, -20, -30]. New-high is the first cycle only."""
    eq = pd.Series([100.0, 90.0, 80.0, 70.0])
    dd = drawdown_series(eq)
    assert dd.tolist() == [0.0, -10.0, -20.0, -30.0]


def test_drawdown_series_empty_input_returns_empty():
    dd = drawdown_series(pd.Series([], dtype="float64"))
    assert dd.empty
    assert dd.name == "drawdown_inr"


def test_drawdown_series_rejects_non_series():
    with pytest.raises(TypeError):
        drawdown_series([100.0, 120.0])


# ============================================================
# drawdown_pct_series (companion %)
# ============================================================

def test_drawdown_pct_series_basic():
    """Same shape as DD₹, divided by running max.
    Equity [100, 120, 60] → cummax [100, 120, 120] →
    DD ₹ [0, 0, -60] → DD % [0, 0, -0.5]."""
    eq = pd.Series([100.0, 120.0, 60.0])
    pct = drawdown_pct_series(eq)
    assert pct.iloc[0] == 0.0
    assert pct.iloc[1] == 0.0
    assert pct.iloc[2] == pytest.approx(-0.5)


def test_drawdown_pct_in_minus_one_zero_band():
    """Sign convention check: pct values always in [-1, 0]."""
    eq = pd.Series([100.0, 80.0, 50.0, 10.0])
    pct = drawdown_pct_series(eq)
    assert (pct <= 0).all()
    assert (pct >= -1).all()


def test_drawdown_pct_handles_zero_running_max():
    """LOAD-BEARING defensive: equity_curve normally rejects
    starting_capital<=0, but if someone hand-builds a series
    with a leading 0 (e.g., a synthetic test fixture), pct
    should be 0 there, NOT inf or NaN."""
    eq = pd.Series([0.0, 0.0, 100.0, 50.0])
    pct = drawdown_pct_series(eq)
    # Positions where running_max == 0 → pct = 0 (defensive).
    assert pct.iloc[0] == 0.0
    assert pct.iloc[1] == 0.0
    # Once running_max becomes positive, math kicks in normally.
    assert pct.iloc[2] == 0.0
    assert pct.iloc[3] == pytest.approx(-0.5)


def test_drawdown_pct_empty_input_returns_empty():
    pct = drawdown_pct_series(pd.Series([], dtype="float64"))
    assert pct.empty


# ============================================================
# Composed flow — F12 → F13 → F14
# ============================================================

def test_equity_curve_then_drawdown_round_trip():
    """LOAD-BEARING end-to-end pin: a hand-checked 4-cycle
    portfolio.

    Cycles:
      2024-04-25:   5 syms,  +₹10,000  net cycle
      2024-05-30:   5 syms,  +₹15,000
      2024-06-27:   5 syms,  -₹40,000   (worst cycle)
      2024-07-25:   5 syms,  +₹20,000

    Starting ₹100,000:
      cycle_pnl =        [10k,    15k,    -40k,   20k]
      equity   =         [110k,   125k,   85k,    105k]
      cummax   =         [110k,   125k,   125k,   125k]
      drawdown ₹ =       [0,     0,      -40k,    -20k]
      drawdown % =       [0,     0,      -0.32,   -0.16]
      max DD ₹ =         ₹40,000
      max DD % =         32%
    """
    pnl_rows = []
    for sym_i in range(5):
        pnl_rows.append(("2024-04-25", f"SYM{sym_i}", 10000.0 / 5))
        pnl_rows.append(("2024-05-30", f"SYM{sym_i}", 15000.0 / 5))
        pnl_rows.append(("2024-06-27", f"SYM{sym_i}", -40000.0 / 5))
        pnl_rows.append(("2024-07-25", f"SYM{sym_i}", 20000.0 / 5))
    df = _trades(pnl_rows)

    pnl = cycle_pnl_series(df)
    assert pnl.tolist() == pytest.approx([10000.0, 15000.0, -40000.0, 20000.0])

    eq = equity_curve(pnl, starting_capital=100_000.0)
    assert eq.tolist() == pytest.approx(
        [110_000.0, 125_000.0, 85_000.0, 105_000.0]
    )

    dd_inr = drawdown_series(eq)
    assert dd_inr.tolist() == pytest.approx(
        [0.0, 0.0, -40_000.0, -20_000.0]
    )
    assert abs(dd_inr.min()) == pytest.approx(40_000.0)

    dd_pct = drawdown_pct_series(eq)
    # cycle 3 underwater = -40k / 125k = -0.32
    # cycle 4 underwater = -20k / 125k = -0.16
    assert dd_pct.tolist() == pytest.approx(
        [0.0, 0.0, -0.32, -0.16], abs=1e-9
    )
    assert abs(dd_pct.min()) == pytest.approx(0.32)


# ============================================================
# Constants pin
# ============================================================

def test_constants_match_sweep_schema():
    """If the sweep parquet schema renames these columns, every
    analytics module that reads them needs to update. Drift detector."""
    assert DEFAULT_EXPIRY_COL == "expiry"
    assert DEFAULT_PNL_COL == "net_pnl"
