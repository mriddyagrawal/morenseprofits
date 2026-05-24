"""Tests for src.strategies.long_strangle.

Load-bearing pair (mirror of test_long_straddle.py):
  1. OTM selection MATCHES ShortStrangle on the same fixture (one
     targeting rule, two strategies — the long is the mirror).
  2. Sign-convention mirror: short strangle gross +X ↔ long strangle
     gross -X on the same option prices, with slippage disabled.
     Pins SPECS §3a's `side_sign` flipping sign across SELL/BUY for
     the OTM-wing case.

Plus the standard contract pins (two BUY legs, margin offset = 1.0,
registry membership).
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data import bhavcopy_fo_loader
from src.engine.pnl import price_trade
from src.engine.slippage import SlippageModelV1
from src.strategies.base import Leg, Trade
from src.strategies.long_strangle import LONG_STRANGLE_MARGIN_OFFSET, LongStrangle
from src.strategies.registry import STRATEGIES
from src.strategies.short_strangle import ShortStrangle


# === Fixture helpers ===

def _fake_bhavcopy(rows):
    return pd.DataFrame({
        "instrument": pd.array([r[0] for r in rows], dtype="string"),
        "symbol": pd.array([r[1] for r in rows], dtype="string"),
        "option_type": pd.array([r[2] for r in rows], dtype="string"),
        "strike": [float(r[3]) for r in rows],
        "expiry": pd.Series([pd.Timestamp(r[4]) for r in rows],
                            dtype="datetime64[us]"),
    })


def _patch_bhavcopy(monkeypatch, frame):
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        lambda td, *, force_refresh=False, offline=False, **kw: frame,
    )


def _grid_20(symbol="X", expiry="2024-01-25"):
    strikes = list(range(2540, 2680, 20))
    return _fake_bhavcopy(
        [("OPTSTK", symbol, "CE", k, expiry) for k in strikes]
        + [("OPTSTK", symbol, "PE", k, expiry) for k in strikes]
    )


# ============================================================
# LOAD-BEARING #1: OTM selection matches ShortStrangle
# ============================================================

def test_otm_selection_matches_short_strangle(monkeypatch):
    """Same targeting rule + same strike grid → same picks. The long
    strangle generalizes nothing new about strike selection; it just
    flips the side. Mirror of the LongStraddle ATM-match test."""
    _patch_bhavcopy(monkeypatch, _grid_20())

    short = ShortStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.0, params={"strike_offset_pct": 0.02},
    )[0]
    long_ = LongStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.0, params={"strike_offset_pct": 0.02},
    )[0]

    short_strikes = sorted({leg.strike for leg in short.legs})
    long_strikes = sorted({leg.strike for leg in long_.legs})
    assert short_strikes == long_strikes == [2540, 2640]


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


def test_sign_mirror_short_vs_long_strangle_no_slippage(monkeypatch):
    """LOAD-BEARING: with slippage off, short strangle gross +X exactly
    equals -X for long strangle on the same option prices. Same trick
    as LongStraddle's mirror test but for the OTM-wing case."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    # CE 2640: 25.00 → 60.00 (call wins big). PE 2540: 30.00 → 1.00.
    ce = _option_frame(entry, exit_, 25.00, 60.00)
    pe = _option_frame(entry, exit_, 30.00, 1.00)
    load = _stub_load_option({(2640.0, "CE"): ce, (2540.0, "PE"): pe})

    no_slip = SlippageModelV1(slippage_pct=0.0)

    short = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2640, "SELL", 1), Leg("PE", 2540, "SELL", 1)),
        strategy="short_strangle",
    )
    long_ = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2640, "BUY", 1), Leg("PE", 2540, "BUY", 1)),
        strategy="long_strangle",
    )
    out_s = price_trade(short, load_option_fn=load, slippage_model=no_slip,
                       today_fn=lambda: date(2026, 5, 24),
                       symbol_margin_pct=0.20)
    out_l = price_trade(long_, load_option_fn=load, slippage_model=no_slip,
                       today_fn=lambda: date(2026, 5, 24),
                       symbol_margin_pct=0.20)
    # Gross sign-mirror is exact at zero slippage
    assert out_s["gross_pnl"] == -out_l["gross_pnl"]
    # Sanity: short should LOSE here because CE went from 25→60 (a 35
    # loss × 250 = -8750), PE went 30→1 (+29 × 250 = +7250).
    # Short gross = -8750 + 7250 = -1500. Long gross = +1500.
    assert out_s["gross_pnl"] == -1500.0
    assert out_l["gross_pnl"] == 1500.0


# ============================================================
# Strategy contract pins
# ============================================================

def test_long_strangle_emits_two_buy_legs(monkeypatch):
    _patch_bhavcopy(monkeypatch, _grid_20())
    out = LongStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.0,
    )
    legs = out[0].legs
    assert len(legs) == 2
    assert {leg.option_type for leg in legs} == {"CE", "PE"}
    assert {leg.side for leg in legs} == {"BUY"}
    assert all(leg.qty_lots == 1 for leg in legs)


def test_long_strangle_margin_offset_is_1_0():
    """SPECS §4a: long-only has no SPAN portfolio offset."""
    assert LONG_STRANGLE_MARGIN_OFFSET == 1.0
    assert LongStrangle().recommended_strategy_offset_pct == 1.0


def test_long_strangle_registered():
    assert "long_strangle" in STRATEGIES
    assert isinstance(STRATEGIES["long_strangle"], LongStrangle)
    assert STRATEGIES["long_strangle"].name == "long_strangle"


def test_default_offset_is_2pct(monkeypatch):
    """No params dict → DEFAULT_STRIKE_OFFSET_PCT = 0.02."""
    _patch_bhavcopy(monkeypatch, _grid_20())
    trade = LongStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.0,
        params=None,
    )[0]
    legs_by_type = {leg.option_type: leg for leg in trade.legs}
    assert legs_by_type["CE"].strike == 2640
    assert legs_by_type["PE"].strike == 2540


def test_negative_offset_rejected(monkeypatch):
    """Mirror of ShortStrangle's negative-offset rejection."""
    _patch_bhavcopy(monkeypatch, _grid_20())
    with pytest.raises(ValueError, match="strike_offset_pct"):
        LongStrangle().generate_trades(
            "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
            spot_at_entry=2596.0,
            params={"strike_offset_pct": -0.02},
        )


def test_offset_zero_degenerates_to_long_straddle(monkeypatch):
    """offset=0 → both BUY legs land at ATM. (We don't import
    LongStraddle here to keep the test focused on LongStrangle's
    own behavior — just pin the strike collapse.)"""
    _patch_bhavcopy(monkeypatch, _grid_20())
    trade = LongStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.65,
        params={"strike_offset_pct": 0.0},
    )[0]
    strikes = sorted({leg.strike for leg in trade.legs})
    assert strikes == [2600]  # ATM only


def test_params_json_records_offset(monkeypatch):
    _patch_bhavcopy(monkeypatch, _grid_20())
    trade = LongStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.0,
        params={"strike_offset_pct": 0.02},
    )[0]
    assert trade.params == {"strike_offset_pct": 0.02}
