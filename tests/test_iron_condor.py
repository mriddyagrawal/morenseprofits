"""Tests for src.strategies.iron_condor.

Load-bearing cases per the Phase-4.4.d.ii plan (reviewer-specified):

  (a) 4 legs in canonical order with correct sides — call spread first
      (inner SELL, outer BUY), then put spread (inner SELL, outer BUY).
      legs_json shape is stable for Phase-5.
  (b) outer > inner enforced; both > 0; raise ValueError otherwise.
  (c) MAX LOSS BOUNDED — for any spot at exit (including far outside
      both wings), the gross loss is capped by the wing-to-inner gap.
      Iron condor's defining property; if the kernel + strategy don't
      cooperate to produce a bounded loss, the whole premise is broken.
  (d) Margin uses spot-based notional when wired through ``sweep_one``
      (which always passes spot_at_entry per fix(p4.4.d.i)).
  (e) Sign convention: net P&L positive when spot at exit is between
      the inner strikes (the credit-collected scenario). Premium decays
      to ~zero on all 4 legs → SHORT legs profit, LONG legs lose
      slightly, but the inner credit > outer debit by construction.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data import bhavcopy_fo_loader
from src.engine.pnl import price_trade
from src.engine.slippage import SlippageModelV1
from src.strategies.base import Leg, Trade
from src.strategies.iron_condor import (
    IRON_CONDOR_MARGIN_OFFSET,
    IronCondor,
)
from src.strategies.registry import STRATEGIES
from src.strategies.short_straddle import NoLiquidStrikeError


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


def _grid_20(symbol="X", expiry="2024-01-25", lo=2400, hi=2800):
    """Dense ₹20 grid from `lo` to `hi`, both CE and PE."""
    strikes = list(range(lo, hi + 20, 20))
    return _fake_bhavcopy(
        [("OPTSTK", symbol, "CE", k, expiry) for k in strikes]
        + [("OPTSTK", symbol, "PE", k, expiry) for k in strikes]
    )


# ============================================================
# LOAD-BEARING (a): leg shape + canonical order
# ============================================================

def test_4_legs_canonical_order_and_sides(monkeypatch):
    """4 legs, in canonical order: SELL inner CE → BUY outer CE →
    SELL inner PE → BUY outer PE. Spot 2600, inner=2%, outer=5%, ₹20
    grid → call inner 2640 (target 2652), outer 2740 (target 2730 →
    nearest 2740 or 2720; 2730 - 2720 = 10 = 2740 - 2730 = 10 →
    tiebreaker picks lower = 2720). Put inner 2540 (2548), outer
    2460 (target 2470 → 2460 or 2480, tiebreaker → 2460)."""
    _patch_bhavcopy(monkeypatch, _grid_20())
    trade = IronCondor().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2600.0,
        params={"inner_offset_pct": 0.02, "outer_offset_pct": 0.05},
    )[0]
    legs = trade.legs
    assert len(legs) == 4
    # Canonical order: call spread first, then put spread
    assert legs[0].option_type == "CE" and legs[0].side == "SELL"  # inner call
    assert legs[1].option_type == "CE" and legs[1].side == "BUY"   # outer call
    assert legs[2].option_type == "PE" and legs[2].side == "SELL"  # inner put
    assert legs[3].option_type == "PE" and legs[3].side == "BUY"   # outer put
    # Strike relationships: outer wings strictly outside inner strikes
    assert legs[1].strike > legs[0].strike  # outer call > inner call
    assert legs[3].strike < legs[2].strike  # outer put  < inner put
    # All 1 lot
    assert all(leg.qty_lots == 1 for leg in legs)


def test_strategy_name_and_params_persisted(monkeypatch):
    _patch_bhavcopy(monkeypatch, _grid_20())
    trade = IronCondor().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2600.0,
        params={"inner_offset_pct": 0.02, "outer_offset_pct": 0.05},
    )[0]
    assert trade.strategy == "iron_condor"
    assert trade.params == {
        "inner_offset_pct": 0.02,
        "outer_offset_pct": 0.05,
    }


# ============================================================
# LOAD-BEARING (b): outer > inner enforced
# ============================================================

def test_outer_must_exceed_inner(monkeypatch):
    _patch_bhavcopy(monkeypatch, _grid_20())
    with pytest.raises(ValueError, match="outer_offset_pct must be"):
        IronCondor().generate_trades(
            "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
            spot_at_entry=2600.0,
            params={"inner_offset_pct": 0.05, "outer_offset_pct": 0.02},
        )


def test_outer_equal_to_inner_rejected(monkeypatch):
    """Equal inner/outer would collapse the wings to the SELL strikes
    (zero spread). Reject — that's a degenerate iron condor, not a
    silently-accepted edge case."""
    _patch_bhavcopy(monkeypatch, _grid_20())
    with pytest.raises(ValueError, match="outer_offset_pct must be"):
        IronCondor().generate_trades(
            "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
            spot_at_entry=2600.0,
            params={"inner_offset_pct": 0.03, "outer_offset_pct": 0.03},
        )


def test_zero_or_negative_offset_rejected(monkeypatch):
    _patch_bhavcopy(monkeypatch, _grid_20())
    for params in [
        {"inner_offset_pct": 0.0, "outer_offset_pct": 0.05},
        {"inner_offset_pct": 0.02, "outer_offset_pct": 0.0},
        {"inner_offset_pct": -0.01, "outer_offset_pct": 0.05},
    ]:
        with pytest.raises(ValueError, match="must be > 0"):
            IronCondor().generate_trades(
                "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
                spot_at_entry=2600.0,
                params=params,
            )


# ============================================================
# LOAD-BEARING (c): MAX LOSS BOUNDED at expiry
# ============================================================

def _option_frame(entry, exit_, entry_close, exit_close, lot=250):
    return pd.DataFrame({
        "date": pd.Series([pd.Timestamp(entry), pd.Timestamp(exit_)],
                          dtype="datetime64[us]"),
        "close": [entry_close, exit_close],
        "lot_size": pd.array([lot, lot], dtype="int64"),
    })


def _stub_load_option(per_leg: dict):
    """Synthesize strike/volume/turnover/oi columns on the minimal
    _option_frame so the post-P1.7 VWAP-or-skip engine has the data
    it needs (turnover/volume engineered so VWAP fill = close — see
    tests/test_pnl.py::_stub_load_option for the full rationale)."""
    def fake(symbol, expiry, strike, option_type, from_date, to_date,
             *, today_fn=date.today, offline=False):
        key = (float(strike), option_type)
        if key not in per_leg:
            from src.data.errors import MissingDataError
            raise MissingDataError(f"no fixture for {key}")
        df = per_leg[key].copy()
        if "strike" not in df.columns:
            df["strike"] = float(strike)
        if "volume" not in df.columns:
            df["volume"] = (df["lot_size"] * 100).astype("int64")
        if "turnover" not in df.columns:
            df["turnover"] = (
                (df["strike"] + df["close"]) * df["volume"]
            ).astype("float64")
        if "oi" not in df.columns:
            df["oi"] = pd.array([1000] * len(df), dtype="Int64")
        mask = (df["date"] >= pd.Timestamp(from_date)) & (df["date"] <= pd.Timestamp(to_date))
        return df.loc[mask].reset_index(drop=True)
    return fake


def test_max_loss_bounded_when_spot_blows_through_call_wing():
    """LOAD-BEARING: iron condor's defining property is bounded loss.
    Simulate a catastrophic upside move where spot at expiry FAR
    exceeds the outer call wing. Both call legs ITM, both put legs
    expire worthless. The kernel must produce a loss bounded by the
    wing spread.

    Setup: 1-lot iron condor with strikes 2640/2740/2560/2460, lot 250.
    Spot at exit = 3000 (way above outer call wing 2740).
      Call spread (SELL 2640, BUY 2740):
        SELL CE 2640: entry 50, exit 360 (intrinsic 3000-2640) → -310 × 250 = -77,500
        BUY  CE 2740: entry 20, exit 260 (intrinsic 3000-2740) →  +240 × 250 = +60,000
        Net call spread P&L: -77,500 + 60,000 = -17,500 (= -(2740-2640) × 250 + net credit ≈ -25,000 + credit)
      Put spread: both expire worthless
        SELL PE 2560: entry 45, exit 0 → +45 × 250 = +11,250
        BUY  PE 2460: entry 18, exit 0 → -18 × 250 = -4,500
        Net put spread P&L: +6,750
      Total gross: -17,500 + 6,750 = -10,750

    Bound check: max loss = max(call_wing_width, put_wing_width) ×
    shares − net_credit. Call wing = 100 × 250 = 25,000. Net credit
    at entry = (50 + 45 − 20 − 18) × 250 = 14,250. Max loss bound =
    25,000 - 14,250 = 10,750. The simulated loss is exactly at the
    bound (slight slippage rounding aside). Pin <= 10,750 with a
    small tolerance for arithmetic."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    legs_data = {
        (2640.0, "CE"): _option_frame(entry, exit_, 50.0, 360.0),  # SELL inner CE
        (2740.0, "CE"): _option_frame(entry, exit_, 20.0, 260.0),  # BUY  outer CE
        (2560.0, "PE"): _option_frame(entry, exit_, 45.0, 0.01),   # SELL inner PE (decayed)
        (2460.0, "PE"): _option_frame(entry, exit_, 18.0, 0.01),   # BUY  outer PE
    }
    load = _stub_load_option(legs_data)
    no_slip = SlippageModelV1(slippage_pct=0.0)

    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(
            Leg("CE", 2640, "SELL", 1),
            Leg("CE", 2740, "BUY",  1),
            Leg("PE", 2560, "SELL", 1),
            Leg("PE", 2460, "BUY",  1),
        ),
        strategy="iron_condor",
    )
    out = price_trade(trade, load_option_fn=load, slippage_model=no_slip,
                      strategy_offset_pct=IRON_CONDOR_MARGIN_OFFSET,
                      symbol_margin_pct=0.20,
                      spot_at_entry=2600.0,
                      today_fn=lambda: date(2026, 5, 24))

    # Per-leg gross sums:
    # -310 × 250 + 240 × 250 + (45 - 0.01) × 250 - (18 - 0.01) × 250
    #   = -77,500 + 60,000 + 11,247.50 - 4,497.50 = -10,750
    assert out["gross_pnl"] == pytest.approx(-10_750.0, abs=2.0)

    # Bound: call_wing × shares - net_credit = 100 × 250 − 14,250 = 10,750
    max_loss_bound = (2740 - 2640) * 250 - (50 + 45 - 20 - 18) * 250
    assert max_loss_bound == 10_750
    # Strict bound — loss may equal but not exceed
    assert out["gross_pnl"] >= -max_loss_bound - 1.0


# ============================================================
# LOAD-BEARING (e): credit collected when spot stays between inners
# ============================================================

def test_credit_collected_when_spot_stays_inside_inner_strikes():
    """LOAD-BEARING for sign convention: spot stays between the inner
    strikes; all 4 options decay to zero at expiry. Net P&L = net
    credit collected at entry.

    Same strikes as above, all options decay to ~0 (spot at exit
    settles AT spot=2600, between inner 2640 and 2560).
      SELL CE 2640: +50 × 250 = +12,500
      BUY  CE 2740: -20 × 250 = -5,000
      SELL PE 2560: +45 × 250 = +11,250
      BUY  PE 2460: -18 × 250 = -4,500
    Net gross = +14,250 (the entry net credit). Positive. ✓"""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    decay = {
        (2640.0, "CE"): _option_frame(entry, exit_, 50.0, 0.01),
        (2740.0, "CE"): _option_frame(entry, exit_, 20.0, 0.01),
        (2560.0, "PE"): _option_frame(entry, exit_, 45.0, 0.01),
        (2460.0, "PE"): _option_frame(entry, exit_, 18.0, 0.01),
    }
    load = _stub_load_option(decay)
    no_slip = SlippageModelV1(slippage_pct=0.0)
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(
            Leg("CE", 2640, "SELL", 1),
            Leg("CE", 2740, "BUY",  1),
            Leg("PE", 2560, "SELL", 1),
            Leg("PE", 2460, "BUY",  1),
        ),
        strategy="iron_condor",
    )
    out = price_trade(trade, load_option_fn=load, slippage_model=no_slip,
                      strategy_offset_pct=IRON_CONDOR_MARGIN_OFFSET,
                      symbol_margin_pct=0.20,
                      spot_at_entry=2600.0,
                      today_fn=lambda: date(2026, 5, 24))
    # +14,250 give or take the 0.01 floor on each leg
    assert out["gross_pnl"] == pytest.approx(14_250.0, abs=10.0)
    assert out["gross_pnl"] > 0


# ============================================================
# Defaults + contract pins
# ============================================================

def test_defaults_are_2pct_inner_5pct_outer(monkeypatch):
    _patch_bhavcopy(monkeypatch, _grid_20())
    trade = IronCondor().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2600.0,
        params=None,
    )[0]
    assert trade.params == {
        "inner_offset_pct": 0.02,
        "outer_offset_pct": 0.05,
    }


def test_margin_offset_matches_specs():
    """SPECS §4a: iron condor's portfolio-offset benefit is 0.35 —
    biggest of any v1 strategy because both spreads cap their own
    tails."""
    assert IRON_CONDOR_MARGIN_OFFSET == 0.35
    assert IronCondor().recommended_strategy_offset_pct == 0.35


def test_iron_condor_registered():
    assert "iron_condor" in STRATEGIES
    assert isinstance(STRATEGIES["iron_condor"], IronCondor)
    assert STRATEGIES["iron_condor"].name == "iron_condor"


def test_no_strikes_raises_no_liquid_strike_error(monkeypatch):
    frame = _fake_bhavcopy([
        ("OPTSTK", "OTHER", "CE", 1000, "2024-01-25"),
    ])
    _patch_bhavcopy(monkeypatch, frame)
    with pytest.raises(NoLiquidStrikeError):
        IronCondor().generate_trades(
            "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
            spot_at_entry=2600.0,
        )


def test_symbol_normalized_to_upper(monkeypatch):
    _patch_bhavcopy(monkeypatch, _grid_20(symbol="RELIANCE"))
    trade = IronCondor().generate_trades(
        "reliance", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2600.0,
    )[0]
    assert trade.symbol == "RELIANCE"


def test_determinism_same_inputs_same_legs(monkeypatch):
    _patch_bhavcopy(monkeypatch, _grid_20())
    a = IronCondor().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2600.0,
    )
    b = IronCondor().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2600.0,
    )
    assert a[0].legs == b[0].legs


# ============================================================
# LOAD-BEARING (d): sweep_one wires spot-based margin through
# ============================================================

def test_sweep_one_iron_condor_uses_spot_based_margin(monkeypatch, tmp_path):
    """Iron condor is the asymmetric-4-leg case where caveat #1 first
    bites. sweep_one must pass spot_at_entry to price_trade so the
    margin model picks spot-based notional automatically."""
    import json
    from src.data import bhavcopy_fo_loader, cache, options_loader, spot_loader, trading_calendar
    from src.engine import sweeper as sweeper_mod
    from src.engine.sweeper import sweep_one

    entry_date = date(2024, 1, 4)
    exit_date = date(2024, 1, 24)

    def fake_offset(anchor, n, *, today_fn=date.today, offline=False):
        return entry_date if n == 15 else exit_date
    monkeypatch.setattr(trading_calendar, "offset_trading_days", fake_offset)

    def fake_load_spot(symbol, from_date, to_date, *, today_fn=date.today, offline=False):
        # F10: engine reads vwap for math; inject close=vwap for this test
        # so the iron-condor strike picks stay numerically anchored.
        return pd.DataFrame({
            "date": pd.Series([pd.Timestamp(from_date)], dtype="datetime64[us]"),
            "close": [2596.65],
            "vwap": [2596.65],
        })
    monkeypatch.setattr(spot_loader, "load_spot", fake_load_spot)

    bc_frame = _grid_20(symbol="RELIANCE", lo=2400, hi=2800)
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        lambda td, *, force_refresh=False, offline=False, **kw: bc_frame,
    )

    def fake_load_option(symbol, expiry, strike, option_type, from_date, to_date,
                         *, today_fn=date.today, offline=False):
        # Include strike/volume/turnover/oi so the post-P1.7
        # VWAP-or-skip engine prices fills equal to close.
        closes = [30.0, 5.0]
        vol = 25_000
        return pd.DataFrame({
            "date": pd.Series(
                [pd.Timestamp(from_date), pd.Timestamp(to_date)],
                dtype="datetime64[us]",
            ),
            "close": closes,
            "lot_size": pd.array([250, 250], dtype="int64"),
            "strike": pd.array([float(strike), float(strike)], dtype="float64"),
            "volume": pd.array([vol, vol], dtype="int64"),
            "turnover": [(strike + c) * vol for c in closes],
            "oi": pd.array([1000, 1000], dtype="Int64"),
        })
    monkeypatch.setattr(options_loader, "load_option", fake_load_option)
    # Both modules import RESULTS_DIR independently from src.config —
    # patch both to prevent leaks into the real data/results/ dir.
    monkeypatch.setattr(sweeper_mod, "RESULTS_DIR", tmp_path)
    from src.engine import results as results_mod
    monkeypatch.setattr(results_mod, "RESULTS_DIR", tmp_path)
    cache.CACHE_DIR = tmp_path

    out = sweep_one(
        "iron_condor", "RELIANCE", date(2024, 1, 25),
        entry_offset_td=15, exit_offset_td=1,
        today_fn=lambda: date(2026, 5, 24),
    )
    assert out is not None
    breakdown = json.loads(out["margin_breakdown_json"])
    # The whole point of plumbing: sweep_one always passes spot_at_entry
    assert breakdown["notional_basis"] == "spot"
    # And it applied the strategy's 0.35 offset
    assert breakdown["strategy_offset_pct"] == 0.35
