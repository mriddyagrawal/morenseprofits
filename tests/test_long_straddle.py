"""Tests for src.strategies.long_straddle.

Two load-bearing tests:
  1. ATM selection MATCHES ShortStraddle on the same fixture
     (both pick 2600 for spot 2596.65 with strikes [2540..2660])
     — SPECS §5 is one rule, two strategies.
  2. Sign-convention mirror: short straddle gross +X ↔ long straddle
     gross -X on the same option prices, with slippage disabled.
     Confirms BUY-side P&L is the engine's mirror of SELL via
     `side_sign`. With slippage enabled, both sides eat the haircut,
     so the simple sign flip is no longer exact — pin both behaviors.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data import bhavcopy_fo_loader, cache, options_loader
from src.engine.pnl import price_trade
from src.engine.slippage import SlippageModelV1
from src.strategies.base import Leg, Trade
from src.strategies.long_straddle import LONG_STRADDLE_MARGIN_OFFSET, LongStraddle
from src.strategies.registry import STRATEGIES
from src.strategies.short_straddle import ShortStraddle


# === Helpers (mirror of test_short_straddle.py shape) ===

def _fake_bhavcopy(rows):
    return pd.DataFrame({
        "instrument": pd.array([r[0] for r in rows], dtype="string"),
        "symbol": pd.array([r[1] for r in rows], dtype="string"),
        "option_type": pd.array([r[2] for r in rows], dtype="string"),
        "strike": [float(r[3]) for r in rows],
        "expiry": pd.Series([pd.Timestamp(r[4]) for r in rows], dtype="datetime64[us]"),
    })


def _patch_bhavcopy(monkeypatch, frame):
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        lambda td, *, force_refresh=False, offline=False, **kw: frame,
    )


# ============================================================
# LOAD-BEARING #1: ATM matches ShortStraddle on same fixture
# ============================================================

def test_atm_selection_matches_short_straddle(monkeypatch):
    """SPECS §5 ATM rule is one rule serving both strategies.
    Same spot + same strike grid → same ATM."""
    frame = _fake_bhavcopy([
        ("OPTSTK", "RELIANCE", "CE", k, "2024-01-25")
        for k in (2540, 2560, 2580, 2600, 2620, 2640, 2660)
    ] + [
        ("OPTSTK", "RELIANCE", "PE", k, "2024-01-25")
        for k in (2540, 2560, 2580, 2600, 2620, 2640, 2660)
    ])
    _patch_bhavcopy(monkeypatch, frame)

    short_trade = ShortStraddle().generate_trades(
        "RELIANCE", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.65,
    )[0]
    long_trade = LongStraddle().generate_trades(
        "RELIANCE", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.65,
    )[0]
    # Same strikes — picked from same data via same rule
    assert {leg.strike for leg in short_trade.legs} == {2600}
    assert {leg.strike for leg in long_trade.legs} == {2600}


# ============================================================
# LOAD-BEARING #2: sign-convention mirror (no slippage)
# ============================================================

def _option_frame(entry, exit_, entry_close, exit_close, lot=250):
    return pd.DataFrame({
        "date": pd.Series([pd.Timestamp(entry), pd.Timestamp(exit_)],
                          dtype="datetime64[us]"),
        "close": [entry_close, exit_close],
        "lot_size": pd.array([lot, lot], dtype="int64"),
    })


def _stub_load_option(per_leg: dict):
    def fake(symbol, expiry, strike, option_type, from_date, to_date,
             *, today_fn=date.today, offline=False):
        key = (float(strike), option_type)
        if key not in per_leg:
            from src.data.errors import MissingDataError
            raise MissingDataError(f"no fixture for {key}")
        df = per_leg[key]
        mask = (df["date"] >= pd.Timestamp(from_date)) & (df["date"] <= pd.Timestamp(to_date))
        return df.loc[mask].reset_index(drop=True)
    return fake


def test_sign_mirror_short_vs_long_straddle_no_slippage(monkeypatch):
    """LOAD-BEARING: with slippage disabled, short straddle gross +X
    exactly equals -X for long straddle on the same option prices.
    Pins SPECS §3a's `side_sign` flipping sign across SELL/BUY."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    # Same fixture both ways: CE 56.50→95.00, PE 50.00→0.50.
    ce = _option_frame(entry, exit_, 56.50, 95.00)
    pe = _option_frame(entry, exit_, 50.00, 0.50)
    load = _stub_load_option({(2600.0, "CE"): ce, (2600.0, "PE"): pe})

    no_slip = SlippageModelV1(slippage_pct=0.0)

    short = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1), Leg("PE", 2600, "SELL", 1)),
        strategy="short_straddle",
    )
    long_ = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "BUY", 1), Leg("PE", 2600, "BUY", 1)),
        strategy="long_straddle",
    )
    out_s = price_trade(short, load_option_fn=load, slippage_model=no_slip,
                       today_fn=lambda: date(2026, 5, 24),
                       symbol_margin_pct=0.20)
    out_l = price_trade(long_, load_option_fn=load, slippage_model=no_slip,
                       today_fn=lambda: date(2026, 5, 24),
                       symbol_margin_pct=0.20)
    # Gross sign-mirror is exact at zero slippage
    assert out_s["gross_pnl"] == -out_l["gross_pnl"]
    # +₹2750 ↔ -₹2750
    assert out_s["gross_pnl"] == 2750.0
    assert out_l["gross_pnl"] == -2750.0


def test_slippage_hurts_both_winning_and_losing_strategies(monkeypatch):
    """LOAD-BEARING for asymmetric conservatism math.

    Slippage doesn't shrink magnitude — it always moves gross TOWARD
    MORE NEGATIVE. A winning trade's win shrinks; a losing trade's
    loss grows. Both pay slippage absolute-equal but the relative
    impact is asymmetric across the win/loss boundary.

    Canonical fixture:
      Short straddle is the WINNING side → gross +2750 (clean) →
        +2245 (with slippage). Win shrunk by ~₹505.
      Long straddle is the LOSING side → gross -2750 (clean) →
        -3255 (with slippage). Loss grew by ~₹505.

    NEITHER side's slipped gross is a clean negation of the other —
    the sign-mirror that holds at zero slippage breaks here. Both
    grosses are LESS THAN their no-slippage values (signed).
    """
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    ce = _option_frame(entry, exit_, 56.50, 95.00)
    pe = _option_frame(entry, exit_, 50.00, 0.50)
    load = _stub_load_option({(2600.0, "CE"): ce, (2600.0, "PE"): pe})

    short = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1), Leg("PE", 2600, "SELL", 1)),
        strategy="short_straddle",
    )
    long_ = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "BUY", 1), Leg("PE", 2600, "BUY", 1)),
        strategy="long_straddle",
    )
    out_s = price_trade(short, load_option_fn=load,
                       today_fn=lambda: date(2026, 5, 24),
                       symbol_margin_pct=0.20)
    out_l = price_trade(long_, load_option_fn=load,
                       today_fn=lambda: date(2026, 5, 24),
                       symbol_margin_pct=0.20)
    # Sign-mirror BROKEN: out_s + out_l != 0 (would be exact mirror).
    assert out_s["gross_pnl"] + out_l["gross_pnl"] != 0
    # Pinned values: short shrinks +2750→+2245, long worsens -2750→-3255
    assert out_s["gross_pnl"] == pytest.approx(2245.0, abs=1.0)
    assert out_l["gross_pnl"] == pytest.approx(-3255.0, abs=1.0)
    # Both grosses dropped (toward more negative) from the no-slippage baseline
    assert out_s["gross_pnl"] < 2750.0    # smaller win
    assert out_l["gross_pnl"] < -2750.0   # bigger loss (more negative)


# ============================================================
# Strategy contract pins
# ============================================================

def test_long_straddle_emits_two_buy_legs(monkeypatch):
    frame = _fake_bhavcopy([
        ("OPTSTK", "X", "CE", 2600, "2024-01-25"),
        ("OPTSTK", "X", "PE", 2600, "2024-01-25"),
    ])
    _patch_bhavcopy(monkeypatch, frame)
    out = LongStraddle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2600.0,
    )
    legs = out[0].legs
    assert len(legs) == 2
    assert {leg.option_type for leg in legs} == {"CE", "PE"}
    assert {leg.side for leg in legs} == {"BUY"}


def test_long_straddle_margin_offset_is_1_0():
    """SPECS §4a: long-only has no SPAN portfolio offset."""
    assert LONG_STRADDLE_MARGIN_OFFSET == 1.0
    assert LongStraddle().recommended_strategy_offset_pct == 1.0


def test_long_straddle_registered():
    assert "long_straddle" in STRATEGIES
    assert isinstance(STRATEGIES["long_straddle"], LongStraddle)
    assert STRATEGIES["long_straddle"].name == "long_straddle"
