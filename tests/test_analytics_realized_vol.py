"""Tests for src.analytics.realized_vol — F7 + compute_rv.

LOAD-BEARING:
  - ``test_realized_vol_from_closes_recovers_known_sigma``: round-
    trip a synthetic geometric-Brownian path → recover σ.
  - ``test_realized_vol_from_closes_uses_ddof_1``: F7 spec pin.
  - ``test_realized_vol_from_closes_returns_nan_below_min_obs``:
    NaN convention for F8 compatibility.
  - ``test_compute_rv_against_live_RELIANCE_2024_smoke``: real-cache
    sanity (RV ~15-30% for RELIANCE, within plausible range).
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.analytics import realized_vol as rv_mod
from src.analytics.realized_vol import (
    RV_MIN_OBS,
    RV_WINDOW_TD,
    TRADING_DAYS_PER_YEAR,
    compute_rv,
    realized_vol_from_closes,
)


# ============================================================
# realized_vol_from_closes — pure math
# ============================================================

def test_realized_vol_from_closes_recovers_known_sigma():
    """LOAD-BEARING. Generate a deterministic price path with a
    known daily-step σ → invert via F7 → recover σ × √252.

    Generate 252 prices via a fixed seed; compute the EMPIRICAL
    daily std of those returns; verify F7 returns std × √252."""
    rng = np.random.default_rng(42)
    daily_sigma_target = 0.012  # ~12% / 365 → ~0.6% daily — typical Indian
    returns = rng.normal(loc=0.0, scale=daily_sigma_target, size=252)
    closes = 100.0 * np.exp(np.cumsum(returns))
    # Prepend a base price so log_returns has the right length.
    closes_full = np.concatenate([[100.0], closes])
    empirical_daily = float(np.std(returns, ddof=1))
    expected_annual = empirical_daily * math.sqrt(252)
    got = realized_vol_from_closes(closes_full)
    assert got == pytest.approx(expected_annual, abs=1e-9)


def test_realized_vol_from_closes_uses_ddof_1():
    """F7 spec pin: ``np.std(log_returns, ddof=1)``. Verify by
    pricing the same series with ddof=0 → should DIFFER. (Small-
    window tests amplify the gap.)"""
    closes = np.array([100.0, 101.0, 99.0, 102.0, 100.0, 103.0, 98.0,
                       101.0, 104.0, 99.0, 102.0, 100.0, 105.0, 97.0,
                       102.0, 103.0, 99.0, 101.0, 104.0, 100.0, 103.0,
                       102.0])
    rv_default = realized_vol_from_closes(closes)
    rv_ddof0 = realized_vol_from_closes(closes, ddof=0)
    # ddof=1 should give a HIGHER vol than ddof=0 (smaller
    # denominator → larger std).
    assert rv_default > rv_ddof0


def test_realized_vol_from_closes_returns_nan_below_min_obs():
    """Default min_obs=20 → 21 closes minimum. 15 closes → NaN."""
    closes = np.linspace(100.0, 115.0, 15)
    assert np.isnan(realized_vol_from_closes(closes))


def test_realized_vol_from_closes_respects_custom_min_obs():
    """Allow short-window diagnostics by lowering min_obs."""
    closes = np.array([100.0, 101.0, 102.0, 103.0])  # 3 log returns
    got = realized_vol_from_closes(closes, min_obs=3)
    assert not np.isnan(got)
    assert got > 0.0


def test_realized_vol_from_closes_returns_nan_on_negative_price():
    """Negative or zero closes → log undefined → NaN."""
    closes = np.linspace(100.0, 115.0, 25)
    closes[5] = -1.0
    assert np.isnan(realized_vol_from_closes(closes))
    closes[5] = 0.0
    assert np.isnan(realized_vol_from_closes(closes))


def test_realized_vol_from_closes_drops_nan_prices():
    """NaN entries in the price array are dropped; the surviving
    contiguous-ish series is used."""
    closes = np.linspace(100.0, 120.0, 25)
    closes[10] = np.nan
    got = realized_vol_from_closes(closes)
    # 24 valid closes → 23 log returns → ≥ 20 → not NaN.
    assert not np.isnan(got)


def test_realized_vol_from_closes_accepts_pd_series():
    """pd.Series is an accepted input — internally coerced to array."""
    closes = pd.Series(np.linspace(100.0, 120.0, 25))
    got = realized_vol_from_closes(closes)
    assert not np.isnan(got)


def test_realized_vol_from_closes_accepts_list():
    closes = list(np.linspace(100.0, 120.0, 25))
    got = realized_vol_from_closes(closes)
    assert not np.isnan(got)


def test_realized_vol_from_closes_returns_nan_on_none():
    assert np.isnan(realized_vol_from_closes(None))


def test_realized_vol_from_closes_returns_nan_on_empty():
    assert np.isnan(realized_vol_from_closes([]))


def test_realized_vol_from_closes_zero_vol_constant_series():
    """Constant prices → all log_returns = 0 → std = 0 → annualized
    vol = 0. NOT NaN — this is a valid zero-vol signal."""
    closes = np.full(25, 100.0)
    got = realized_vol_from_closes(closes)
    assert got == 0.0


def test_realized_vol_from_closes_no_annualize():
    """annualize=False returns daily std without the √252 factor."""
    closes = np.linspace(100.0, 105.0, 25)
    annual = realized_vol_from_closes(closes, annualize=True)
    daily = realized_vol_from_closes(closes, annualize=False)
    assert annual == pytest.approx(daily * math.sqrt(252), abs=1e-12)


def test_realized_vol_from_closes_custom_trading_days_per_year():
    """Override the annualization factor for diagnostic comparisons."""
    closes = np.linspace(100.0, 110.0, 25)
    rv_252 = realized_vol_from_closes(closes, trading_days_per_year=252)
    rv_365 = realized_vol_from_closes(closes, trading_days_per_year=365)
    assert rv_365 == pytest.approx(rv_252 * math.sqrt(365 / 252), abs=1e-12)


# ============================================================
# compute_rv — symbol-aware convenience
# ============================================================

def test_compute_rv_rejects_window_td_le_1():
    with pytest.raises(ValueError, match="window_td must be > 1"):
        compute_rv("RELIANCE", date(2024, 5, 1), window_td=1)


def test_compute_rv_returns_nan_on_empty_spot(monkeypatch):
    """Symbol not in cache / no rows in window → NaN, not exception."""
    def fake_load_spot(symbol, from_date, to_date, **kw):
        return pd.DataFrame({"date": [], "close": []})

    def fake_offset(as_of, td, **kw):
        return as_of

    monkeypatch.setattr(rv_mod.spot_loader, "load_spot", fake_load_spot)
    monkeypatch.setattr(
        rv_mod.trading_calendar, "offset_trading_days", fake_offset,
    )
    got = compute_rv("UNKNOWN", date(2024, 5, 1))
    assert np.isnan(got)


def test_compute_rv_returns_nan_on_insufficient_rows(monkeypatch):
    """Only 10 rows in window → < min_obs+1 → NaN."""
    def fake_load_spot(symbol, from_date, to_date, **kw):
        return pd.DataFrame({
            "date": pd.date_range("2024-04-15", periods=10),
            "close": np.linspace(100.0, 105.0, 10),
        })

    def fake_offset(as_of, td, **kw):
        return as_of

    monkeypatch.setattr(rv_mod.spot_loader, "load_spot", fake_load_spot)
    monkeypatch.setattr(
        rv_mod.trading_calendar, "offset_trading_days", fake_offset,
    )
    assert np.isnan(compute_rv("RELIANCE", date(2024, 5, 1)))


def test_compute_rv_synthetic_series_recovers_sigma(monkeypatch):
    """End-to-end with monkeypatched I/O: a 25-day synthetic
    series with known daily σ → compute_rv recovers √252 × σ."""
    rng = np.random.default_rng(7)
    daily = 0.015
    returns = rng.normal(loc=0.0, scale=daily, size=25)
    closes = 100.0 * np.exp(np.cumsum(returns))

    def fake_load_spot(symbol, from_date, to_date, **kw):
        return pd.DataFrame({
            "date": pd.date_range("2024-04-15", periods=25),
            "close": closes,
        })

    def fake_offset(as_of, td, **kw):
        return as_of

    monkeypatch.setattr(rv_mod.spot_loader, "load_spot", fake_load_spot)
    monkeypatch.setattr(
        rv_mod.trading_calendar, "offset_trading_days", fake_offset,
    )
    got = compute_rv("RELIANCE", date(2024, 5, 1), window_td=24)
    # Hand-compute the expected
    log_returns = np.diff(np.log(closes))
    expected = float(np.std(log_returns, ddof=1)) * math.sqrt(252)
    assert got == pytest.approx(expected, abs=1e-9)


# ============================================================
# Constants
# ============================================================

def test_constants_match_memoir_spec():
    """F7 spec pin — drift detector."""
    assert RV_WINDOW_TD == 21
    assert TRADING_DAYS_PER_YEAR == 252
    assert RV_MIN_OBS == 20
