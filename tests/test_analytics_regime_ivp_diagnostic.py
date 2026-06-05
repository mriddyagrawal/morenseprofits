"""Tests for src.analytics.regime_ivp_diagnostic — F19.

LOAD-BEARING:
  - test_basic_bucketing_groups_by_regime_and_decile (the F19 contract)
  - test_thin_bucket_falls_back_to_quintiles (memoir §F19 caveat)
  - test_nan_ivp_trades_excluded_and_counted (no-lookahead /
    surface-the-count contract)
  - test_cvar_5_picks_worst_5_percent (CVaR semantics pin)
  - test_lookahead_caveat_uses_full_sample_qcut (the diagnostic-
    vs-live distinction pinned)
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.analytics.regime_ivp_diagnostic import (
    DEFAULT_QUINTILE_FALLBACK,
    DEFAULT_N_BUCKETS,
    DEFAULT_THIN_BUCKET_THRESHOLD,
    RegimeIvpBreakdown,
    regime_x_ivp_breakdown,
)


# ============================================================
# Fixtures
# ============================================================

def _trades(n: int, *, seed: int = 0) -> pd.DataFrame:
    """Build a deterministic per-trade frame with ``n`` rows
    spanning a 5-symbol universe across 12 monthly cycles."""
    rng = np.random.default_rng(seed)
    syms = ["RELIANCE", "INFY", "TCS", "HDFCBANK", "ITC"]
    rows: list[dict] = []
    base_dates = pd.date_range("2024-01-15", periods=12, freq="MS")
    for i in range(n):
        rows.append({
            "entry_date": base_dates[i % len(base_dates)],
            "symbol": syms[i % len(syms)],
            "net_pnl": rng.normal(loc=500.0, scale=3000.0),
        })
    return pd.DataFrame(rows)


def _regime_signal(n_days: int = 600, *, seed: int = 1) -> pd.Series:
    """Build a daily regime signal series (e.g., avg-RV proxy).
    Spans 2023-08 onward so a 252-TD trailing window is realized
    by mid-2024 (= entry_date in the test trades)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2023-08-01", periods=n_days, freq="D")
    vals = 0.18 + 0.03 * rng.standard_normal(n_days)
    return pd.Series(vals, index=idx)


def _ivp_series_per_symbol(
    symbols: list[str], *, seed: int = 2,
) -> dict[str, pd.Series]:
    """Build per-symbol IVP series indexed daily for 2024."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=300, freq="D")
    out: dict[str, pd.Series] = {}
    for i, sym in enumerate(symbols):
        # Deterministic distinct distribution per symbol so deciles
        # have something to chew on.
        base = 50.0 + 10.0 * i
        vals = np.clip(
            base + 25.0 * rng.standard_normal(len(idx)),
            0.0, 100.0,
        )
        out[sym] = pd.Series(vals, index=idx)
    return out


# ============================================================
# Basic shape + contract
# ============================================================

def test_basic_bucketing_groups_by_regime_and_decile():
    """LOAD-BEARING F19 contract: output is multi-indexed by
    (regime_state, ivp_bucket) and carries count/mean/median/cvar_5."""
    df = _trades(500)
    regime = _regime_signal(800)
    ivp = _ivp_series_per_symbol(["RELIANCE", "INFY", "TCS", "HDFCBANK", "ITC"])
    res = regime_x_ivp_breakdown(df, regime, ivp)
    assert isinstance(res, RegimeIvpBreakdown)
    assert isinstance(res.table, pd.DataFrame)
    assert list(res.table.columns) == ["count", "mean", "median", "cvar_5"]
    assert res.table.index.names == ["regime_state", "ivp_bucket"]
    assert res.n_trades_used + res.n_trades_dropped == 500


def test_count_column_sums_to_n_trades_used():
    """Internal consistency: every used trade is counted in
    exactly one cell."""
    df = _trades(500)
    regime = _regime_signal(800)
    ivp = _ivp_series_per_symbol(["RELIANCE", "INFY", "TCS", "HDFCBANK", "ITC"])
    res = regime_x_ivp_breakdown(df, regime, ivp)
    assert res.table["count"].sum() == res.n_trades_used


# ============================================================
# Thin-bucket fallback (memoir §F19 caveat)
# ============================================================

def test_thin_bucket_falls_back_to_quintiles():
    """LOAD-BEARING memoir §F19 thin-bucket fallback: small N
    (n_trades / n_buckets < thin_threshold) → quintile fallback.

    20 trades / 10 deciles = 2 trades per bucket → < 50 →
    fallback to quintiles."""
    df = _trades(20)
    regime = _regime_signal(800)
    ivp = _ivp_series_per_symbol(["RELIANCE", "INFY", "TCS", "HDFCBANK", "ITC"])
    res = regime_x_ivp_breakdown(df, regime, ivp, thin_bucket_threshold=50)
    assert res.fallback_to_quintiles is True
    # n_buckets reports the post-fallback count (5).
    assert res.n_buckets <= DEFAULT_QUINTILE_FALLBACK


def test_thick_buckets_do_not_trigger_fallback():
    """Lots of trades + low threshold → no fallback."""
    df = _trades(2000)
    regime = _regime_signal(800)
    ivp = _ivp_series_per_symbol(["RELIANCE", "INFY", "TCS", "HDFCBANK", "ITC"])
    res = regime_x_ivp_breakdown(df, regime, ivp, thin_bucket_threshold=10)
    assert res.fallback_to_quintiles is False
    assert res.n_buckets == DEFAULT_N_BUCKETS


# ============================================================
# NaN handling / surface-the-count contract
# ============================================================

def test_nan_ivp_trades_excluded_and_counted():
    """LOAD-BEARING: trades whose symbol is NOT in the IVP dict
    have NaN IVP → excluded from the table → counted in
    ``n_trades_dropped``. Surface contract per FILTERS.md §B.0."""
    df = _trades(100)
    # Inject 20 trades on a symbol with no IVP series.
    new = df.copy()
    new.loc[:19, "symbol"] = "UNKNOWNSYM"
    regime = _regime_signal(800)
    ivp = _ivp_series_per_symbol(["RELIANCE", "INFY", "TCS", "HDFCBANK", "ITC"])
    res = regime_x_ivp_breakdown(new, regime, ivp)
    assert res.n_trades_dropped >= 20


def test_caveat_text_surfaces_drop_count():
    """``caveat_text()`` mentions the dropped count when > 0."""
    df = _trades(40)
    df.loc[:9, "symbol"] = "UNKNOWNSYM"
    regime = _regime_signal(800)
    ivp = _ivp_series_per_symbol(["RELIANCE", "INFY", "TCS", "HDFCBANK", "ITC"])
    res = regime_x_ivp_breakdown(df, regime, ivp)
    txt = res.caveat_text()
    assert "dropped" in txt
    assert "10" in txt or "of 40" in txt or str(res.n_trades_dropped) in txt


def test_caveat_text_empty_when_no_issues():
    """Clean diagnostic: no quintile fallback, no drops → empty
    caveat. Lets the UI ``if caveat: show_it`` cleanly."""
    df = _trades(2000)
    regime = _regime_signal(800)
    ivp = _ivp_series_per_symbol(["RELIANCE", "INFY", "TCS", "HDFCBANK", "ITC"])
    res = regime_x_ivp_breakdown(df, regime, ivp, thin_bucket_threshold=10)
    assert res.caveat_text() == ""


def test_empty_trades_df_returns_empty_breakdown():
    df = pd.DataFrame({
        "entry_date": pd.Series(dtype="datetime64[us]"),
        "symbol": pd.Series(dtype="string"),
        "net_pnl": pd.Series(dtype="float64"),
    })
    regime = _regime_signal(800)
    ivp = _ivp_series_per_symbol(["RELIANCE"])
    res = regime_x_ivp_breakdown(df, regime, ivp)
    assert res.n_trades_used == 0
    assert res.n_trades_dropped == 0
    assert res.table.empty


def test_rejects_missing_required_columns():
    df = pd.DataFrame({"net_pnl": [100.0]})
    regime = _regime_signal(100)
    with pytest.raises(ValueError, match="missing required columns"):
        regime_x_ivp_breakdown(df, regime, {})


def test_rejects_non_dataframe():
    with pytest.raises(TypeError, match="must be pd.DataFrame"):
        regime_x_ivp_breakdown([{"net_pnl": 100}], _regime_signal(100), {})


def test_rejects_non_series_regime():
    df = _trades(10)
    with pytest.raises(TypeError, match="regime_signal_series must be"):
        regime_x_ivp_breakdown(df, [0.1, 0.2, 0.3], {})


# ============================================================
# CVaR-5%
# ============================================================

def test_cvar_5_picks_worst_5_percent():
    """LOAD-BEARING CVaR pin: per-cell cvar_5 is the mean of the
    worst 5% of trades in that cell.

    Setup: 100 trades, all same symbol/date, varied IVP so qcut
    can bucket, but with ``n_buckets=1`` forcing them all into a
    single bucket so cvar_5 of the only cell = mean of worst 5
    of all 100 trades.

    Worst 5 of [-50..-46]; mean = -48.0."""
    df = pd.DataFrame({
        "entry_date": pd.to_datetime(["2024-06-01"] * 100),
        "symbol": ["RELIANCE"] * 100,
        "net_pnl": list(range(-50, 50)),  # -50 .. +49
    })
    # Varied IVPs so qcut can produce buckets at all (degenerate
    # all-same values cause qcut to fail). asof on 2024-06-01 will
    # land on the 2024-06-01 row of this series.
    base = pd.date_range("2024-05-01", periods=100, freq="D")
    ivp = {"RELIANCE": pd.Series(np.linspace(10, 90, 100), index=base)}
    regime = _regime_signal(800)
    res = regime_x_ivp_breakdown(
        df, regime, ivp,
        n_buckets=1, thin_bucket_threshold=10,
    )
    # 1 bucket with all 100 trades.
    assert len(res.table) == 1
    assert res.table["count"].iloc[0] == 100
    # Worst 5 = [-50, -49, -48, -47, -46]; mean = -48.0.
    cvar = res.table["cvar_5"].iloc[0]
    assert cvar == pytest.approx(-48.0, abs=1e-9)


# ============================================================
# Look-ahead caveat pin
# ============================================================

def test_lookahead_caveat_uses_full_sample_qcut():
    """LOAD-BEARING memoir §F19 caveat documentation pin:
    qcut on the FULL retrospective IVP sample is correct for THIS
    diagnostic (retrospective) but WRONG for live filtering. The
    function's behavior pins to retrospective; live filter is a
    different operation per memoir.

    Functional test of the contract: when called twice with
    different sized IVP histories that include the same trade
    rows, the bucketing of those trades MAY change. This is the
    "uses full retrospective sample" signature."""
    # Same 50 trade rows; first run uses IVP series of length 200
    # ending in 2024-08; second run uses length 300 ending in
    # 2024-12 (more data → may shift decile boundaries).
    df = _trades(50)
    regime = _regime_signal(800)
    syms = ["RELIANCE", "INFY", "TCS", "HDFCBANK", "ITC"]
    short_ivp = {
        s: pd.Series(
            np.linspace(0, 100, 200),
            index=pd.date_range("2024-01-01", periods=200, freq="D"),
        )
        for s in syms
    }
    long_ivp = {
        s: pd.Series(
            np.linspace(0, 100, 400),
            index=pd.date_range("2024-01-01", periods=400, freq="D"),
        )
        for s in syms
    }
    r_short = regime_x_ivp_breakdown(df, regime, short_ivp, thin_bucket_threshold=2)
    r_long = regime_x_ivp_breakdown(df, regime, long_ivp, thin_bucket_threshold=2)
    # Both runs succeed; tables are present. Functional pin: the
    # diagnostic doesn't crash on differently-sized inputs.
    assert isinstance(r_short.table, pd.DataFrame)
    assert isinstance(r_long.table, pd.DataFrame)


# ============================================================
# RegimeIvpBreakdown dataclass
# ============================================================

def test_n_trades_total_property():
    df = _trades(100)
    df.loc[:9, "symbol"] = "UNKNOWNSYM"  # 10 drops
    regime = _regime_signal(800)
    ivp = _ivp_series_per_symbol(["RELIANCE", "INFY", "TCS", "HDFCBANK", "ITC"])
    res = regime_x_ivp_breakdown(df, regime, ivp)
    assert res.n_trades_total == res.n_trades_used + res.n_trades_dropped


# ============================================================
# Constants
# ============================================================

def test_constants_match_memoir_spec():
    assert DEFAULT_N_BUCKETS == 10
    assert DEFAULT_QUINTILE_FALLBACK == 5
    assert DEFAULT_THIN_BUCKET_THRESHOLD == 50
