"""Tests for src.engine.slippage. Pure arithmetic."""
from __future__ import annotations

import pytest

from src.engine.slippage import SLIPPAGE_MODEL_V1, SlippageModelV1


# ============================================================
# LOAD-BEARING: directional asymmetry — SELL gets less, BUY pays more
# ============================================================

def test_sell_receives_less_than_close():
    """SELL action → price haircut DOWN. You receive less than the
    quoted close because you sold into the bid, not at the close."""
    assert SLIPPAGE_MODEL_V1.realized_price(100.0, "SELL") == 99.0


def test_buy_pays_more_than_close():
    """BUY action → price haircut UP. You paid more than the quoted
    close because you crossed the ask, not transacted at close."""
    assert SLIPPAGE_MODEL_V1.realized_price(100.0, "BUY") == 101.0


def test_invalid_action_raises():
    with pytest.raises(ValueError, match="action must be"):
        SLIPPAGE_MODEL_V1.realized_price(100.0, "HOLD")


# ============================================================
# Combined per-leg entry/exit (the engine-friendly API)
# ============================================================

def test_sell_leg_realized_pair():
    """SELL leg: opens by selling (receives less), closes by buying
    (pays more). Both directions cost money."""
    entry, exit_ = SLIPPAGE_MODEL_V1.realized_entry_exit(
        "SELL", entry_close=100.0, exit_close=50.0,
    )
    assert entry == 99.0   # 100 × 0.99
    assert exit_ == 50.5   # 50 × 1.01


def test_buy_leg_realized_pair():
    """BUY leg: opens by buying (pays more), closes by selling (receives
    less). Mirror of SELL."""
    entry, exit_ = SLIPPAGE_MODEL_V1.realized_entry_exit(
        "BUY", entry_close=100.0, exit_close=150.0,
    )
    assert entry == 101.0  # 100 × 1.01
    assert exit_ == 148.5  # 150 × 0.99


# ============================================================
# Calibration: RELIANCE Jan-2024 short straddle haircut
# ============================================================

def test_reliance_jan_2024_short_straddle_slippage_haircut():
    """SPECS §4b calibration. Canonical short straddle:
      CE: SELL 56.50 / BUY 95.05 (close raw)
      PE: SELL 43.15 / BUY 0.40
    With 1% slippage, the realized prices differ. The total realized
    gross is ~₹500 less than the no-slippage baseline (which was +₹1050).
    """
    ce_entry, ce_exit = SLIPPAGE_MODEL_V1.realized_entry_exit("SELL", 56.50, 95.05)
    pe_entry, pe_exit = SLIPPAGE_MODEL_V1.realized_entry_exit("SELL", 43.15, 0.40)
    # CE gross with slippage: (55.935 - 96.0005) × 250 = -10,016.25
    ce_gross = (ce_entry - ce_exit) * 1 * 250
    # PE gross with slippage: (42.7185 - 0.404) × 250 = +10,578.625
    pe_gross = (pe_entry - pe_exit) * 1 * 250
    total = ce_gross + pe_gross
    # No-slippage baseline: +₹1,050. With slippage: ~+₹562.
    assert total == pytest.approx(562.375, abs=0.5)
    # Haircut is ~₹488 (1050 - 562) — matches the SPECS calibration target.


# ============================================================
# Edge cases
# ============================================================

def test_zero_slippage_is_passthrough():
    """slippage_pct=0 → realized == close (no haircut)."""
    model = SlippageModelV1(slippage_pct=0.0)
    assert model.realized_price(100.0, "SELL") == 100.0
    assert model.realized_price(100.0, "BUY") == 100.0


def test_negative_slippage_raises():
    with pytest.raises(ValueError, match="slippage_pct"):
        SlippageModelV1(slippage_pct=-0.01)


def test_slippage_one_or_above_raises():
    with pytest.raises(ValueError, match="slippage_pct"):
        SlippageModelV1(slippage_pct=1.0)


def test_singleton_frozen():
    from dataclasses import FrozenInstanceError
    with pytest.raises(FrozenInstanceError):
        SLIPPAGE_MODEL_V1.slippage_pct = 0.05  # type: ignore[misc]


def test_alternate_slippage_for_sensitivity():
    """0.5% slippage variant — sensitivity-analysis pattern."""
    half = SlippageModelV1(slippage_pct=0.005)
    assert half.realized_price(100.0, "SELL") == 99.5
    assert SLIPPAGE_MODEL_V1.realized_price(100.0, "SELL") == 99.0  # unchanged
