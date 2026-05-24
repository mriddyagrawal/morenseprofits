"""Tests for src.strategies.short_straddle. No network — bhavcopy_fo_loader
monkeypatched.

The load-bearing test is `test_reliance_jan_2024_atm_picked_correctly`:
the canonical hand-check (RELIANCE Jan-25 expiry, spot 2596.65 on Jan-4)
must pick strike 2600 — same as the Phase-1 integration verify pinned.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data import bhavcopy_fo_loader
from src.strategies.base import Leg, Trade
from src.strategies.short_straddle import (
    SHORT_STRADDLE_MARGIN_OFFSET,
    NoLiquidStrikeError,
    ShortStraddle,
)


def _fake_bhavcopy(rows: list[tuple[str, str, str, int, float]]):
    """Build a synthetic SPECS §2.4 bhavcopy frame.
    Rows: (instrument, symbol, option_type, strike, expiry_iso)."""
    return pd.DataFrame({
        "instrument": pd.array([r[0] for r in rows], dtype="string"),
        "symbol": pd.array([r[1] for r in rows], dtype="string"),
        "option_type": pd.array([r[2] for r in rows], dtype="string"),
        "strike": [float(r[3]) for r in rows],
        "expiry": pd.Series([pd.Timestamp(r[4]) for r in rows],
                            dtype="datetime64[us]"),
    })


def _patch_bhavcopy(monkeypatch, frame: pd.DataFrame):
    def fake(td, *, force_refresh=False, offline=False, **kw):
        return frame
    monkeypatch.setattr(bhavcopy_fo_loader, "load_bhavcopy_fo", fake)


# ============================================================
# LOAD-BEARING: RELIANCE Jan 2024 ATM hand-check
# ============================================================

def test_reliance_jan_2024_atm_picked_correctly(monkeypatch):
    """Spot 2596.65 on Jan-4 with strikes [2580, 2600, 2620, ...] →
    nearest = 2600. Matches the Phase-1 integration verify."""
    frame = _fake_bhavcopy([
        ("OPTSTK", "RELIANCE", "CE", k, "2024-01-25")
        for k in (2540, 2560, 2580, 2600, 2620, 2640, 2660)
    ] + [
        ("OPTSTK", "RELIANCE", "PE", k, "2024-01-25")
        for k in (2540, 2560, 2580, 2600, 2620, 2640, 2660)
    ])
    _patch_bhavcopy(monkeypatch, frame)

    out = ShortStraddle().generate_trades(
        symbol="RELIANCE",
        expiry=date(2024, 1, 25),
        entry_date=date(2024, 1, 4),
        exit_date=date(2024, 1, 24),
        spot_at_entry=2596.65,
    )
    assert len(out) == 1
    trade = out[0]
    assert trade.symbol == "RELIANCE"
    assert trade.strategy == "short_straddle"
    assert trade.expiry == date(2024, 1, 25)
    assert trade.entry_date == date(2024, 1, 4)
    assert trade.exit_date == date(2024, 1, 24)
    assert trade.legs == (
        Leg("CE", 2600, "SELL", 1),
        Leg("PE", 2600, "SELL", 1),
    )


# ============================================================
# ATM tiebreaker: equidistant → lower strike (SPECS §5)
# ============================================================

def test_atm_tiebreaker_picks_lower_strike(monkeypatch):
    """Spot 2610.0 with strikes [2600, 2620] — equidistant. Must pick
    2600 per SPECS §5. A typical sign-flip-on-tiebreaker bug would
    pick 2620."""
    frame = _fake_bhavcopy([
        ("OPTSTK", "X", "CE", 2600, "2024-01-25"),
        ("OPTSTK", "X", "CE", 2620, "2024-01-25"),
        ("OPTSTK", "X", "PE", 2600, "2024-01-25"),
        ("OPTSTK", "X", "PE", 2620, "2024-01-25"),
    ])
    _patch_bhavcopy(monkeypatch, frame)

    out = ShortStraddle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2610.0,
    )
    assert out[0].legs[0].strike == 2600


def test_atm_chooses_nearest_when_clearly_closer(monkeypatch):
    """Spot 2611 → 2620 is closer (|2620-2611|=9) than 2600 (|11|).
    Pin the basic argmin to catch a "always-round-down" regression."""
    frame = _fake_bhavcopy([
        ("OPTSTK", "X", "CE", 2600, "2024-01-25"),
        ("OPTSTK", "X", "CE", 2620, "2024-01-25"),
        ("OPTSTK", "X", "PE", 2600, "2024-01-25"),
        ("OPTSTK", "X", "PE", 2620, "2024-01-25"),
    ])
    _patch_bhavcopy(monkeypatch, frame)
    out = ShortStraddle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2611.0,
    )
    assert out[0].legs[0].strike == 2620


# ============================================================
# Filtering: only this symbol's OPTSTK strikes for this expiry
# ============================================================

def test_filters_to_requested_symbol_and_expiry(monkeypatch):
    """Bhavcopy has many symbols + expiries. Strategy must filter to
    the requested combination only."""
    frame = _fake_bhavcopy([
        # Other symbol — must be ignored
        ("OPTSTK", "INFY", "CE", 1500, "2024-01-25"),
        # Wrong expiry — must be ignored
        ("OPTSTK", "X", "CE", 9999, "2024-02-29"),
        # Wrong instrument — must be ignored (futures)
        ("FUTSTK", "X", "CE", 8888, "2024-01-25"),
        # The real candidates
        ("OPTSTK", "X", "CE", 2600, "2024-01-25"),
        ("OPTSTK", "X", "PE", 2600, "2024-01-25"),
    ])
    _patch_bhavcopy(monkeypatch, frame)
    out = ShortStraddle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2611.0,
    )
    # Must pick 2600 (the only real candidate), NOT 1500/9999/8888
    assert out[0].legs[0].strike == 2600


def test_no_strikes_raises_no_liquid_strike_error(monkeypatch):
    """Empty bhavcopy filter → NoLiquidStrikeError (a MissingDataError
    subclass, so sweeper's skip-loop catches it)."""
    from src.data.errors import MissingDataError
    frame = _fake_bhavcopy([
        ("OPTSTK", "OTHER_SYMBOL", "CE", 1000, "2024-01-25"),  # not X
    ])
    _patch_bhavcopy(monkeypatch, frame)
    with pytest.raises(NoLiquidStrikeError):
        ShortStraddle().generate_trades(
            "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
            spot_at_entry=2600.0,
        )
    # Confirm class hierarchy: catchable as MissingDataError
    try:
        ShortStraddle().generate_trades(
            "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
            spot_at_entry=2600.0,
        )
    except MissingDataError:
        pass  # ✓


# ============================================================
# Trade shape pins
# ============================================================

def test_trade_has_exactly_two_sell_legs_one_ce_one_pe(monkeypatch):
    frame = _fake_bhavcopy([
        ("OPTSTK", "X", "CE", 2600, "2024-01-25"),
        ("OPTSTK", "X", "PE", 2600, "2024-01-25"),
    ])
    _patch_bhavcopy(monkeypatch, frame)
    out = ShortStraddle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2600.0,
    )
    assert len(out) == 1
    legs = out[0].legs
    assert len(legs) == 2
    types = {leg.option_type for leg in legs}
    sides = {leg.side for leg in legs}
    assert types == {"CE", "PE"}
    assert sides == {"SELL"}


def test_symbol_normalized_to_upper(monkeypatch):
    frame = _fake_bhavcopy([
        ("OPTSTK", "RELIANCE", "CE", 2600, "2024-01-25"),
        ("OPTSTK", "RELIANCE", "PE", 2600, "2024-01-25"),
    ])
    _patch_bhavcopy(monkeypatch, frame)
    out = ShortStraddle().generate_trades(
        "reliance", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.65,
    )
    assert out[0].symbol == "RELIANCE"


# ============================================================
# Margin-offset constant matches SPECS §4a calibration
# ============================================================

def test_margin_offset_matches_specs():
    """SPECS §4a calibration: short straddle real-broker SPAN benefit
    is ~60% of sum-of-naked-legs. The constant must equal 0.60 so
    when callers pass `strategy_offset_pct=SHORT_STRADDLE_MARGIN_OFFSET`
    they get the right number."""
    assert SHORT_STRADDLE_MARGIN_OFFSET == 0.60


# ============================================================
# Determinism
# ============================================================

def test_determinism_same_inputs_same_trade(monkeypatch):
    """Two calls with identical inputs return Trades with == legs."""
    frame = _fake_bhavcopy([
        ("OPTSTK", "X", "CE", k, "2024-01-25") for k in (2580, 2600, 2620)
    ] + [
        ("OPTSTK", "X", "PE", k, "2024-01-25") for k in (2580, 2600, 2620)
    ])
    _patch_bhavcopy(monkeypatch, frame)
    a = ShortStraddle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24), 2596.0
    )
    b = ShortStraddle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24), 2596.0
    )
    assert a[0].legs == b[0].legs
