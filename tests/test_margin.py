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

def test_reliance_short_straddle_calibration_tier_a_default():
    """Tier-A (default kwargs): sum of per-leg (20% × strike × shares).
    RELIANCE 2600 short straddle → ₹2.6L total. Conservative vs real
    ~₹1.5L. Pin the default behavior so the new kwargs are truly
    additive."""
    legs = [
        _leg("SELL", 1, 250, 56.50, 2600.0),
        _leg("SELL", 1, 250, 50.00, 2600.0),
    ]
    out = MARGIN_MODEL_V1.estimate(legs)
    assert out["sell_leg_margin_raw"] == 260_000.0
    assert out["sell_leg_margin"] == 260_000.0  # offset_pct defaults to 1.0
    assert out["buy_leg_premium"] == 0.0
    assert out["total"] == 260_000.0
    assert out["strategy_offset_pct"] == 1.0
    assert out["symbol_margin_pct"] == 0.20


def test_reliance_short_straddle_tier_b_with_strategy_offset():
    """Tier-B: strategy_offset_pct=0.60 for short straddle.
    sell_leg_margin_raw stays at ₹2.6L (sum of legs); sell_leg_margin
    drops to ₹2.6L × 0.6 = ₹1.56L. Total = ₹1.56L. Much closer to
    real broker ~₹1.5L block."""
    legs = [
        _leg("SELL", 1, 250, 56.50, 2600.0),
        _leg("SELL", 1, 250, 50.00, 2600.0),
    ]
    out = MARGIN_MODEL_V1.estimate(legs, strategy_offset_pct=0.60)
    assert out["sell_leg_margin_raw"] == 260_000.0
    assert out["sell_leg_margin"] == 260_000.0 * 0.60
    assert out["total"] == 156_000.0
    assert out["strategy_offset_pct"] == 0.60


def test_high_vol_symbol_blocks_more_margin():
    """Tier-B: symbol_margin_pct overrides the uniform 20%.
    ADANIENT-style high-vol → 0.25 → larger block per leg."""
    legs = [
        _leg("SELL", 1, 250, 2000.0, 2000.0),
        _leg("SELL", 1, 250, 2000.0, 2000.0),
    ]
    # Tier-A: 0.20 × 2000 × 250 × 2 = 200,000
    out_v1 = MARGIN_MODEL_V1.estimate(legs)
    assert out_v1["sell_leg_margin_raw"] == 200_000.0
    # Tier-B with high-vol override: 0.25 × 2000 × 250 × 2 = 250,000
    out_high_vol = MARGIN_MODEL_V1.estimate(legs, symbol_margin_pct=0.25)
    assert out_high_vol["sell_leg_margin_raw"] == 250_000.0


def test_tier_b_both_kwargs_combine():
    """Both strategy_offset and symbol_margin_pct apply.
    ADANIENT short strangle: 0.25 × strikes × shares × 0.70 offset."""
    legs = [
        _leg("SELL", 1, 250, 100.0, 1900.0),  # short put OTM
        _leg("SELL", 1, 250, 100.0, 2100.0),  # short call OTM
    ]
    out = MARGIN_MODEL_V1.estimate(
        legs, strategy_offset_pct=0.70, symbol_margin_pct=0.25,
    )
    expected_raw = 0.25 * (1900 + 2100) * 250  # 250,000
    assert out["sell_leg_margin_raw"] == expected_raw
    assert out["sell_leg_margin"] == expected_raw * 0.70  # 175,000
    assert out["total"] == 175_000.0


def test_offset_must_be_in_valid_range():
    legs = [_leg("SELL", 1, 250, 50.0, 2600.0)]
    with pytest.raises(ValueError, match="strategy_offset_pct"):
        MARGIN_MODEL_V1.estimate(legs, strategy_offset_pct=0.0)
    with pytest.raises(ValueError, match="strategy_offset_pct"):
        MARGIN_MODEL_V1.estimate(legs, strategy_offset_pct=1.5)
    with pytest.raises(ValueError, match="strategy_offset_pct"):
        MARGIN_MODEL_V1.estimate(legs, strategy_offset_pct=-0.5)


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


# ============================================================
# SPECS §4a caveat #1: spot_at_entry kwarg (spot-based notional)
# ============================================================

def test_default_notional_basis_is_strike_backward_compat():
    """No spot_at_entry kwarg → margin uses strike. Pins existing
    behavior so the kwarg is purely additive — every pre-existing
    test (and any external caller) keeps the same numbers."""
    legs = [_leg("SELL", 1, 250, 50.0, 2600.0)]
    out = MARGIN_MODEL_V1.estimate(legs)
    assert out["notional_basis"] == "strike"
    assert out["sell_leg_margin"] == 0.20 * 2600 * 250


def test_spot_at_entry_switches_notional_to_spot():
    """spot_at_entry=2596.65 → SELL leg uses 2596.65 × shares × pct,
    not strike × shares × pct. The notional_basis output flips to
    'spot' so consumers can audit which basis was used."""
    legs = [_leg("SELL", 1, 250, 50.0, 2600.0)]
    out = MARGIN_MODEL_V1.estimate(legs, spot_at_entry=2596.65)
    assert out["notional_basis"] == "spot"
    assert out["sell_leg_margin"] == pytest.approx(0.20 * 2596.65 * 250)
    # Strictly different from strike-based (spot != strike)
    assert out["sell_leg_margin"] != 0.20 * 2600 * 250


def test_spot_equals_strike_collapses_to_strike_based():
    """Sanity: when spot_at_entry exactly equals the strike, both
    bases produce the same SELL-leg margin. The fix's bias correction
    is zero at the money — which is the right shape."""
    legs = [_leg("SELL", 1, 250, 50.0, 2600.0)]
    out_strike = MARGIN_MODEL_V1.estimate(legs)
    out_spot = MARGIN_MODEL_V1.estimate(legs, spot_at_entry=2600.0)
    assert out_strike["sell_leg_margin"] == out_spot["sell_leg_margin"]
    # Only the basis label differs
    assert out_strike["notional_basis"] == "strike"
    assert out_spot["notional_basis"] == "spot"


def test_asymmetric_4_leg_structure_bias_is_significant():
    """LOAD-BEARING for caveat #1: on an asymmetric 4-leg structure
    (iron-condor-shape), strike-based margin is biased high (sum of
    4 different strikes / 4) vs spot-based (1 × spot per leg).

    Setup: spot=2600, lot=250, qty=1. Iron-condor strikes:
      SELL 2640 CE (inner call, +1.5% OTM)
      BUY  2750 CE (outer call wing, +5.8% OTM)
      SELL 2560 PE (inner put, -1.5% OTM)
      BUY  2450 PE (outer put wing, -5.8% OTM)

    Only the SELL legs contribute to sell_margin_raw. Strike-based:
      0.20 × (2640 + 2560) × 250 = ₹2,60,000.
    Spot-based:
      0.20 × (2600 + 2600) × 250 = ₹2,60,000.

    For a symmetric inner pair (2640/2560 averaging to 2600 = spot)
    the bias is ZERO. The asymmetric bias only appears when the inner
    strikes don't average to spot — e.g., a skewed entry. Test that
    too with an asymmetric inner pair."""
    spot = 2600.0
    legs_symmetric = [
        _leg("SELL", 1, 250, 30.0, 2640.0),
        _leg("BUY",  1, 250, 5.0,  2750.0),
        _leg("SELL", 1, 250, 28.0, 2560.0),
        _leg("BUY",  1, 250, 4.0,  2450.0),
    ]
    strike_out = MARGIN_MODEL_V1.estimate(legs_symmetric, strategy_offset_pct=0.35)
    spot_out = MARGIN_MODEL_V1.estimate(
        legs_symmetric, strategy_offset_pct=0.35, spot_at_entry=spot,
    )
    # Symmetric inner pair → bias is exactly zero
    assert strike_out["sell_leg_margin"] == spot_out["sell_leg_margin"]

    # Now SKEWED structure: both shorts above spot (bias side)
    legs_skewed = [
        _leg("SELL", 1, 250, 30.0, 2700.0),  # +3.8% OTM
        _leg("BUY",  1, 250, 5.0,  2800.0),
        _leg("SELL", 1, 250, 28.0, 2650.0),  # +1.9% OTM
        _leg("BUY",  1, 250, 4.0,  2500.0),
    ]
    strike_skew = MARGIN_MODEL_V1.estimate(legs_skewed, strategy_offset_pct=0.35)
    spot_skew = MARGIN_MODEL_V1.estimate(
        legs_skewed, strategy_offset_pct=0.35, spot_at_entry=spot,
    )
    # Strike-based: 0.20 × (2700 + 2650) × 250 × 0.35 = ₹93,625
    assert strike_skew["sell_leg_margin"] == pytest.approx(
        0.20 * (2700 + 2650) * 250 * 0.35, abs=1e-6,
    )
    # Spot-based: 0.20 × (2600 + 2600) × 250 × 0.35 = ₹91,000
    assert spot_skew["sell_leg_margin"] == pytest.approx(
        0.20 * (2600 + 2600) * 250 * 0.35, abs=1e-6,
    )
    # Strike-based overstates margin for above-spot shorts (the
    # direction caveat #1 predicts)
    assert strike_skew["sell_leg_margin"] > spot_skew["sell_leg_margin"]


def test_spot_at_entry_does_not_affect_buy_legs():
    """BUY-leg margin = premium paid × shares, independent of spot.
    The fix only touches SELL-leg notional. Pin so a future
    misrefactor that also rewrites BUY math is caught."""
    legs = [_leg("BUY", 1, 250, 50.0, 2600.0)]
    out_strike = MARGIN_MODEL_V1.estimate(legs)
    out_spot = MARGIN_MODEL_V1.estimate(legs, spot_at_entry=2500.0)
    assert out_strike["buy_leg_premium"] == out_spot["buy_leg_premium"]
    assert out_strike["total"] == out_spot["total"] == 50.0 * 250


def test_spot_at_entry_must_be_positive_when_provided():
    """spot_at_entry=0 or negative is meaningless; reject loudly."""
    legs = [_leg("SELL", 1, 250, 50.0, 2600.0)]
    with pytest.raises(ValueError, match="spot_at_entry"):
        MARGIN_MODEL_V1.estimate(legs, spot_at_entry=0.0)
    with pytest.raises(ValueError, match="spot_at_entry"):
        MARGIN_MODEL_V1.estimate(legs, spot_at_entry=-100.0)


def test_spot_basis_combines_with_strategy_offset_and_symbol_pct():
    """All three Tier-B kwargs compose: spot × shares × symbol_pct
    × strategy_offset. Pin one composite to catch a future refactor
    that breaks the order of operations."""
    legs = [_leg("SELL", 1, 250, 50.0, 2600.0)]
    out = MARGIN_MODEL_V1.estimate(
        legs,
        strategy_offset_pct=0.60,
        symbol_margin_pct=0.25,
        spot_at_entry=2596.65,
    )
    expected_raw = 0.25 * 2596.65 * 250
    expected_post = expected_raw * 0.60
    assert out["sell_leg_margin_raw"] == pytest.approx(expected_raw)
    assert out["sell_leg_margin"] == pytest.approx(expected_post)
    assert out["notional_basis"] == "spot"
