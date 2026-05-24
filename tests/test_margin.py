"""Tests for src.engine.margin. Pure arithmetic — no network, no mocks.

The load-bearing test is `test_reliance_short_straddle_calibration`:
asserts ₹2,60,000 total margin for the RELIANCE 2600 short straddle —
matches the SPECS §4a calibration hand-check.
"""
from __future__ import annotations

import pytest

from src.engine.margin import MARGIN_MODEL_V1, MarginModelV1


def _leg(side, qty_lots, lot_size, entry_px, strike, exit_px=0.0):
    return {
        "side": side, "qty_lots": qty_lots, "lot_size": lot_size,
        "entry_px": entry_px, "strike": strike, "exit_px": exit_px,
    }


# ============================================================
# LOAD-BEARING: RELIANCE 2600 short straddle calibration
# ============================================================

def test_reliance_short_straddle_calibration():
    """SPECS §4a hand-check: RELIANCE 2600 short straddle, lot 250.
    SELL CE 2600: 0.20 × 2600 × 250 = ₹130,000.
    SELL PE 2600: 0.20 × 2600 × 250 = ₹130,000.
    Total = ₹260,000. Conservative vs real ~₹1.5L SPAN benefit."""
    legs = [
        _leg("SELL", 1, 250, 56.50, 2600.0),  # CE
        _leg("SELL", 1, 250, 50.00, 2600.0),  # PE
    ]
    out = MARGIN_MODEL_V1.estimate(legs)
    assert out["sell_leg_margin"] == 260_000.0
    assert out["buy_leg_premium"] == 0.0
    assert out["total"] == 260_000.0


# ============================================================
# BUY leg: margin = premium paid only
# ============================================================

def test_long_call_margin_is_premium_only():
    """BUY-side leg blocks NO additional margin — premium IS the margin.
    Long call entry ₹50 × lot 100 = ₹5,000."""
    legs = [_leg("BUY", 1, 100, 50.0, 100.0)]
    out = MARGIN_MODEL_V1.estimate(legs)
    assert out["sell_leg_margin"] == 0.0
    assert out["buy_leg_premium"] == 5_000.0
    assert out["total"] == 5_000.0


def test_long_straddle_margin_is_sum_of_premiums():
    """Long straddle = BUY CE + BUY PE. Margin = sum of both premiums.
    No SPAN block for long options."""
    legs = [
        _leg("BUY", 1, 100, 50.0, 1000.0),  # CE premium ₹50
        _leg("BUY", 1, 100, 60.0, 1000.0),  # PE premium ₹60
    ]
    out = MARGIN_MODEL_V1.estimate(legs)
    assert out["sell_leg_margin"] == 0.0
    assert out["buy_leg_premium"] == (50 + 60) * 100  # ₹11,000


# ============================================================
# SELL leg: margin = 20% × strike × shares (NOT premium-based)
# ============================================================

def test_naked_short_call_margin_independent_of_premium():
    """SELL-leg margin is based on UNDERLYING notional (strike × shares),
    NOT on the premium received. Same strike + same shares = same margin
    whether premium is ₹1 or ₹100."""
    cheap = _leg("SELL", 1, 250, 1.0, 2600.0)
    rich = _leg("SELL", 1, 250, 100.0, 2600.0)
    out_cheap = MARGIN_MODEL_V1.estimate([cheap])
    out_rich = MARGIN_MODEL_V1.estimate([rich])
    assert out_cheap["sell_leg_margin"] == out_rich["sell_leg_margin"]
    assert out_cheap["sell_leg_margin"] == 0.20 * 2600 * 250


def test_naked_short_higher_strike_blocks_more_margin():
    """Higher strike → larger underlying notional → larger margin."""
    cheap_strike = _leg("SELL", 1, 250, 50.0, 1000.0)
    rich_strike = _leg("SELL", 1, 250, 50.0, 5000.0)
    out_cheap = MARGIN_MODEL_V1.estimate([cheap_strike])
    out_rich = MARGIN_MODEL_V1.estimate([rich_strike])
    assert out_rich["sell_leg_margin"] == 5 * out_cheap["sell_leg_margin"]


# ============================================================
# Mixed strategies (covered call, iron condor)
# ============================================================

def test_covered_call_style_long_buy_plus_short_sell():
    """One BUY + one SELL leg → total = buy premium + sell SPAN block.
    Conservative — real SPAN gives credit for the hedge."""
    legs = [
        _leg("BUY", 1, 100, 5.0, 1000.0),    # premium ₹5
        _leg("SELL", 1, 100, 3.0, 1100.0),   # SPAN on strike 1100
    ]
    out = MARGIN_MODEL_V1.estimate(legs)
    expected_buy = 5.0 * 100
    expected_sell = 0.20 * 1100 * 100
    assert out["buy_leg_premium"] == expected_buy
    assert out["sell_leg_margin"] == expected_sell
    assert out["total"] == expected_buy + expected_sell


def test_iron_condor_style_two_buys_two_sells():
    """4-leg iron condor: 2 BUY (wings) + 2 SELL (body).
    Total = sum of both buy premiums + sum of both sell SPAN blocks."""
    legs = [
        _leg("SELL", 1, 100, 10.0, 1050.0),   # short call
        _leg("BUY",  1, 100,  3.0, 1100.0),   # long call wing
        _leg("SELL", 1, 100, 10.0,  950.0),   # short put
        _leg("BUY",  1, 100,  3.0,  900.0),   # long put wing
    ]
    out = MARGIN_MODEL_V1.estimate(legs)
    expected_buy = (3 + 3) * 100
    expected_sell = 0.20 * (1050 + 950) * 100
    assert out["buy_leg_premium"] == expected_buy
    assert out["sell_leg_margin"] == expected_sell
    assert out["total"] == expected_buy + expected_sell


# ============================================================
# Scaling
# ============================================================

def test_margin_scales_with_qty_lots():
    """3 lots → 3× the margin (both SELL and BUY components)."""
    one = [_leg("SELL", 1, 250, 50.0, 2600.0)]
    three = [_leg("SELL", 3, 250, 50.0, 2600.0)]
    o1 = MARGIN_MODEL_V1.estimate(one)
    o3 = MARGIN_MODEL_V1.estimate(three)
    assert o3["total"] == 3 * o1["total"]


# ============================================================
# Edge cases
# ============================================================

def test_empty_legs_raises():
    with pytest.raises(ValueError, match="no legs"):
        MARGIN_MODEL_V1.estimate([])


def test_invalid_side_raises():
    legs = [_leg("HOLD", 1, 100, 10.0, 100.0)]
    with pytest.raises(ValueError, match="SELL or BUY"):
        MARGIN_MODEL_V1.estimate(legs)


# ============================================================
# Singleton immutability + sensitivity-analysis pattern
# ============================================================

def test_singleton_frozen():
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        MARGIN_MODEL_V1.span_plus_exposure_pct = 0.50  # type: ignore[misc]


def test_alternate_span_pct_for_sensitivity():
    """Phase-5 sensitivity: build a 30% SPAN model to test how the
    rankings shift if margin is more conservative. V1 unchanged."""
    aggressive = MarginModelV1(span_plus_exposure_pct=0.30)
    legs = [_leg("SELL", 1, 250, 50.0, 2600.0)]
    out_v1 = MARGIN_MODEL_V1.estimate(legs)
    out_agg = aggressive.estimate(legs)
    assert out_v1["sell_leg_margin"] == 0.20 * 2600 * 250
    assert out_agg["sell_leg_margin"] == 0.30 * 2600 * 250
    # 30/20 = 1.5x
    assert out_agg["total"] == pytest.approx(1.5 * out_v1["total"], abs=1e-9)
