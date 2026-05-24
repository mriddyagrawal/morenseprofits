"""Tests for src.engine.costs. Pure arithmetic — no network, no mocks.

The load-bearing test is `test_reliance_jan_2024_short_straddle_hand_check`:
the reviewer hand-computed total ~₹141.78 on the canonical RELIANCE Jan-2024
short straddle (CE 56.50/95 + PE 50/0.50, lot 250). If any V1 rate drifts,
this test will fire with the exact ₹ amount the user would actually pay.
"""
from __future__ import annotations

import pytest

from src.engine.costs import COST_MODEL_V1, CostModelV1


def _leg(side, qty_lots, lot_size, entry_px, exit_px):
    return {
        "side": side, "qty_lots": qty_lots, "lot_size": lot_size,
        "entry_px": entry_px, "exit_px": exit_px,
    }


# ============================================================
# LOAD-BEARING: RELIANCE Jan-2024 short straddle hand-check
# ============================================================

def test_reliance_jan_2024_short_straddle_hand_check():
    """Same fixture the P&L kernel hand-check uses (test_pnl.py).
    CE entry 56.50, exit 95.00; PE entry 50.00, exit 0.50; lot 250; 1 lot each.

    Per SPECS §4 with COST_MODEL_V1 rates:
      Sell-side turnover (entries of both SELL legs):
        (56.50 + 50.00) × 250 = 26,625
      Buy-side turnover (exits of both SELL legs — close = BUY):
        (95.00 +  0.50) × 250 = 23,875
      Total turnover = 50,500

      Brokerage     = 4 orders × ₹20         = ₹80.00
      STT           = 26,625 × 0.000625      = ₹16.640625
      Exchange      = 50,500 × 0.000503      = ₹25.4015
      GST           = (80 + 25.4015) × 0.18  = ₹18.972270
      SEBI          = (50,500 / 1e7) × 10    = ₹0.0505
      Stamp duty    = 23,875 × 0.00003       = ₹0.71625
      ─────────────────────────────────────────────────
      Total                                  ≈ ₹141.780645
    """
    legs = [
        _leg("SELL", 1, 250, 56.50, 95.00),  # CE
        _leg("SELL", 1, 250, 50.00,  0.50),  # PE
    ]
    out = COST_MODEL_V1.total_cost(legs)
    assert out["brokerage"] == 80.0
    assert out["stt"] == pytest.approx(16.640625, abs=1e-6)
    assert out["exchange"] == pytest.approx(25.4015, abs=1e-6)
    assert out["gst"] == pytest.approx(18.972270, abs=1e-4)
    assert out["sebi"] == pytest.approx(0.0505, abs=1e-6)
    assert out["stamp_duty"] == pytest.approx(0.71625, abs=1e-6)
    assert out["total"] == pytest.approx(141.780645, abs=1e-3)


# ============================================================
# Per-component rate pins
# ============================================================

def test_brokerage_is_flat_per_order():
    """4 orders (2 legs × entry + exit) → ₹80 regardless of premium size."""
    big = [
        _leg("SELL", 1, 1, 1_000_000.0, 0.0),
        _leg("SELL", 1, 1, 0.01, 0.01),
    ]
    small = [
        _leg("SELL", 1, 1, 0.01, 0.01),
        _leg("SELL", 1, 1, 0.01, 0.01),
    ]
    assert COST_MODEL_V1.total_cost(big)["brokerage"] == 80.0
    assert COST_MODEL_V1.total_cost(small)["brokerage"] == 80.0


def test_stt_sell_side_only():
    """STT is on the SELL side of OPTIONS, period. For a single-leg
    BUY trade (long call), STT is on the exit (which is a SELL).
    For a single-leg SELL trade (naked short), STT is on the entry."""
    # Long call: BUY at 100, SELL at 150
    long_call = [_leg("BUY", 1, 100, 100.0, 150.0)]
    out_long = COST_MODEL_V1.total_cost(long_call)
    # SELL-side turnover = exit_px × shares = 150 × 100 = 15,000
    assert out_long["stt"] == pytest.approx(15000 * 0.000625, abs=1e-6)

    # Short call: SELL at 100, BUY at 50
    short_call = [_leg("SELL", 1, 100, 100.0, 50.0)]
    out_short = COST_MODEL_V1.total_cost(short_call)
    # SELL-side turnover = entry_px × shares = 100 × 100 = 10,000
    assert out_short["stt"] == pytest.approx(10000 * 0.000625, abs=1e-6)


def test_stamp_duty_buy_side_only():
    """Stamp duty is on the BUY side ONLY. A pure-SELL short call's
    stamp duty applies to the exit (close=BUY). A pure-BUY long call's
    stamp duty applies to the entry (open=BUY)."""
    # Short call: SELL at 100, BUY at 50 — stamp on exit_px
    short_call = [_leg("SELL", 1, 100, 100.0, 50.0)]
    out_short = COST_MODEL_V1.total_cost(short_call)
    assert out_short["stamp_duty"] == pytest.approx(5000 * 0.00003, abs=1e-8)

    # Long call: BUY at 100, SELL at 150 — stamp on entry_px
    long_call = [_leg("BUY", 1, 100, 100.0, 150.0)]
    out_long = COST_MODEL_V1.total_cost(long_call)
    assert out_long["stamp_duty"] == pytest.approx(10000 * 0.00003, abs=1e-8)


def test_exchange_fee_both_sides():
    """Exchange transaction fee applies to entry AND exit turnover."""
    legs = [_leg("SELL", 1, 100, 100.0, 50.0)]
    out = COST_MODEL_V1.total_cost(legs)
    total_turnover = (100.0 + 50.0) * 100
    assert out["exchange"] == pytest.approx(total_turnover * 0.000503, abs=1e-8)


def test_gst_only_on_brokerage_and_exchange():
    """GST 18% applies to (brokerage + exchange), NOT to STT / stamp /
    SEBI. Per real-world Indian tax rules."""
    legs = [_leg("SELL", 1, 100, 100.0, 50.0)]
    out = COST_MODEL_V1.total_cost(legs)
    expected_gst = (out["brokerage"] + out["exchange"]) * 0.18
    assert out["gst"] == pytest.approx(expected_gst, abs=1e-8)


def test_total_sums_to_components():
    """Total must equal the sum of components exactly. Catches a
    typo where a component is computed but excluded from the sum."""
    legs = [
        _leg("SELL", 1, 250, 56.50, 95.00),
        _leg("SELL", 1, 250, 50.00, 0.50),
    ]
    out = COST_MODEL_V1.total_cost(legs)
    components = (out["brokerage"] + out["stt"] + out["exchange"]
                  + out["gst"] + out["sebi"] + out["stamp_duty"])
    assert out["total"] == pytest.approx(components, abs=1e-9)


# ============================================================
# Scaling
# ============================================================

def test_costs_scale_with_qty_lots_proportionally():
    """3 lots of the same leg → 3× the turnover-scaled costs.
    Brokerage stays flat (still 2 orders), so cost-per-lot drops with size."""
    one = [_leg("SELL", 1, 250, 100.0, 50.0)]
    three = [_leg("SELL", 3, 250, 100.0, 50.0)]
    o1 = COST_MODEL_V1.total_cost(one)
    o3 = COST_MODEL_V1.total_cost(three)
    # Brokerage IDENTICAL (2 orders either way)
    assert o3["brokerage"] == o1["brokerage"]
    # Turnover-scaled components 3×
    for k in ("stt", "exchange", "sebi", "stamp_duty"):
        assert o3[k] == pytest.approx(3 * o1[k], abs=1e-8)


# ============================================================
# Edge cases
# ============================================================

def test_empty_legs_raises():
    with pytest.raises(ValueError, match="no legs"):
        COST_MODEL_V1.total_cost([])


def test_invalid_side_raises():
    legs = [_leg("HOLD", 1, 100, 10.0, 10.0)]
    with pytest.raises(ValueError, match="SELL or BUY"):
        COST_MODEL_V1.total_cost(legs)


def test_frozen_singleton_immutable():
    """COST_MODEL_V1 is a frozen dataclass instance — can't be mutated
    even via `.brokerage_per_order = 1000`. Backtests in different
    parts of the codebase MUST see identical rates."""
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        COST_MODEL_V1.brokerage_per_order = 1000  # type: ignore[misc]


def test_v2_can_be_constructed_without_mutating_v1():
    """Sensitivity analysis: build a separate cost-model instance with
    different rates; V1 unaffected."""
    v2 = CostModelV1(brokerage_per_order=0.0, stt_sell_options_pct=0.0)
    legs = [_leg("SELL", 1, 250, 100.0, 50.0)]
    out_v1 = COST_MODEL_V1.total_cost(legs)
    out_v2 = v2.total_cost(legs)
    assert out_v2["brokerage"] == 0.0
    assert out_v1["brokerage"] == 40.0  # 2 orders (1 leg × entry+exit) × ₹20 unchanged
    assert out_v2["stt"] == 0.0
    assert out_v1["stt"] > 0  # unchanged
