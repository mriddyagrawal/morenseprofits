"""Tests for src.engine.vol. No network — spot_loader mocked.

The load-bearing test is `test_vol_to_margin_pct_calibration`: the
calibration table from SPECS §4a must hold exactly so a future tweak
to the formula is visible as a test diff.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.data import spot_loader, trading_calendar
from src.engine.vol import realized_vol, symbol_margin_pct, vol_to_margin_pct


def _patch_load_spot(monkeypatch, closes: list[float]):
    """Replace load_spot with a fake that returns a frame with the given
    closes. Dates are an arbitrary monotonic sequence; only the closes
    matter for vol."""
    n = len(closes)

    def fake(symbol, from_date, to_date, *, force_refresh=False,
             today_fn=date.today, offline=False, **kw):
        return pd.DataFrame({
            "date": pd.Series(
                pd.date_range(from_date, periods=n, freq="B"),
                dtype="datetime64[us]",
            ),
            "symbol": pd.array([symbol] * n, dtype="string"),
            "close": closes,
        })

    monkeypatch.setattr(spot_loader, "load_spot", fake)


def _patch_calendar(monkeypatch, lookback_date: date):
    def fake(anchor, n, *, today_fn=date.today, offline=False):
        return lookback_date

    monkeypatch.setattr(trading_calendar, "offset_trading_days", fake)


# ============================================================
# LOAD-BEARING: vol_to_margin_pct calibration table
# ============================================================

def test_vol_to_margin_pct_calibration():
    """SPECS §4a calibration table — three pinned points must hold."""
    # HDFCBANK ~15% vol → 0.16
    assert vol_to_margin_pct(0.15) == pytest.approx(0.16, abs=1e-9)
    # RELIANCE ~22% vol → 0.188 (linear 0.10 + 0.40 × 0.22)
    assert vol_to_margin_pct(0.22) == pytest.approx(0.188, abs=1e-9)
    # ADANIENT ~35% vol → 0.24
    assert vol_to_margin_pct(0.35) == pytest.approx(0.24, abs=1e-9)


def test_vol_to_margin_pct_clamp_low():
    """Very low vol → floor at 0.10 (NSE doesn't go below this in practice).
    Note: floor only matters at vol=0; even tiny positive vol gives raw
    > 0.10 so the clamp is vacuous on the low end."""
    assert vol_to_margin_pct(0.0) == 0.10
    # 0.10 + 0.40 × 0.005 = 0.102 > 0.10, so no clamp — pure linear.
    assert vol_to_margin_pct(0.005) == pytest.approx(0.102, abs=1e-9)


def test_vol_to_margin_pct_clamp_high():
    """Very high vol → ceiling at 0.30."""
    assert vol_to_margin_pct(0.50) == pytest.approx(0.30, abs=1e-9)
    assert vol_to_margin_pct(1.00) == pytest.approx(0.30, abs=1e-9)


def test_vol_to_margin_pct_negative_raises():
    with pytest.raises(ValueError, match="annualized_vol"):
        vol_to_margin_pct(-0.10)


# ============================================================
# realized_vol arithmetic
# ============================================================

def test_realized_vol_zero_for_flat_prices(monkeypatch):
    """Flat closes → zero log returns → zero vol."""
    _patch_calendar(monkeypatch, date(2024, 1, 2))
    _patch_load_spot(monkeypatch, [100.0] * 50)
    vol = realized_vol("X", date(2024, 7, 1), today_fn=lambda: date(2026, 5, 24))
    assert vol == 0.0


def test_realized_vol_constant_daily_return(monkeypatch):
    """Constant daily log return of 0.01 across 252 days → annualized
    vol approaches 0 (constant returns have no stdev)."""
    _patch_calendar(monkeypatch, date(2024, 1, 2))
    closes = [100.0 * (1.01 ** i) for i in range(252)]
    _patch_load_spot(monkeypatch, closes)
    vol = realized_vol("X", date(2024, 7, 1), today_fn=lambda: date(2026, 5, 24))
    # Constant daily returns → ddof=1 stdev ≈ 0 → annualized vol ≈ 0
    assert vol == pytest.approx(0.0, abs=1e-9)


def test_realized_vol_known_daily_stdev(monkeypatch):
    """Synthetic daily log returns alternating ±0.01 → daily stdev ≈ 0.01,
    annualized = 0.01 × sqrt(252) ≈ 0.1587."""
    _patch_calendar(monkeypatch, date(2024, 1, 2))
    # Alternating up/down moves of 1%
    closes = [100.0]
    for i in range(200):
        if i % 2 == 0:
            closes.append(closes[-1] * math.exp(0.01))
        else:
            closes.append(closes[-1] * math.exp(-0.01))
    _patch_load_spot(monkeypatch, closes)
    vol = realized_vol("X", date(2024, 7, 1), today_fn=lambda: date(2026, 5, 24))
    expected = 0.01 * math.sqrt(252)
    # Some sampling noise expected from ddof=1; allow 5% tolerance
    assert vol == pytest.approx(expected, rel=0.05)


def test_realized_vol_insufficient_data_returns_zero(monkeypatch):
    """<20 rows → 0.0 rather than a noisy estimate."""
    _patch_calendar(monkeypatch, date(2024, 1, 2))
    _patch_load_spot(monkeypatch, [100.0, 101.0, 102.0])
    vol = realized_vol("X", date(2024, 7, 1), today_fn=lambda: date(2026, 5, 24))
    assert vol == 0.0


def test_realized_vol_lookback_zero_or_one_raises():
    with pytest.raises(ValueError, match="lookback_trading_days"):
        realized_vol("X", date(2024, 1, 1), lookback_trading_days=1)


# ============================================================
# symbol_margin_pct composes the two
# ============================================================

def test_symbol_margin_pct_low_vol_symbol(monkeypatch):
    """Constant prices → vol=0 → margin_pct=0.10 (floor)."""
    _patch_calendar(monkeypatch, date(2024, 1, 2))
    _patch_load_spot(monkeypatch, [100.0] * 100)
    pct = symbol_margin_pct("X", date(2024, 7, 1), today_fn=lambda: date(2026, 5, 24))
    assert pct == 0.10


def test_symbol_margin_pct_synthetic_high_vol(monkeypatch):
    """Alternating ±2% moves → annual vol ~31.7% → margin_pct ~22.7%."""
    _patch_calendar(monkeypatch, date(2024, 1, 2))
    closes = [100.0]
    for i in range(200):
        if i % 2 == 0:
            closes.append(closes[-1] * math.exp(0.02))
        else:
            closes.append(closes[-1] * math.exp(-0.02))
    _patch_load_spot(monkeypatch, closes)
    pct = symbol_margin_pct("X", date(2024, 7, 1), today_fn=lambda: date(2026, 5, 24))
    # daily stdev ≈ 0.02, annualized ≈ 0.317
    # margin_pct = 0.10 + 0.40 × 0.317 = 0.227
    assert pct == pytest.approx(0.227, abs=0.02)
