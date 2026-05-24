"""Tests for src.strategies.short_strangle.

ShortStrangle is the first strategy with a tunable param
(`strike_offset_pct`). Load-bearing cases per the Phase-4.4.b plan:

  (a) ``strike_offset_pct=0`` degenerates to ShortStraddle (both legs ATM
      at the same strike) — the strangle generalizes the straddle.
  (b) ``strike_offset_pct=0.02`` on spot 2596 with a ₹20 strike grid →
      call ≈ 2640 (nearest to 2596 × 1.02 = 2647.92), put ≈ 2540
      (nearest to 2596 × 0.98 = 2544.08). Pins the targeting arithmetic.
  (c) ``recommended_strategy_offset_pct = 0.70`` matches SPECS §4a
      calibration (OTM wings → slightly less correlated → smaller SPAN
      offset benefit than the ATM straddle's 0.60).
  (d) When the exact target strike is missing from the bhavcopy grid,
      the picker falls back to the nearest available strike — never
      crashes on a sparse strike chain.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data import bhavcopy_fo_loader
from src.strategies.base import Leg
from src.strategies.registry import STRATEGIES
from src.strategies.short_straddle import NoLiquidStrikeError, ShortStraddle
from src.strategies.short_strangle import (
    SHORT_STRANGLE_MARGIN_OFFSET,
    ShortStrangle,
)


# === Fixture helpers (mirror test_short_straddle.py shape) ===

def _fake_bhavcopy(rows: list[tuple[str, str, str, int, str]]):
    return pd.DataFrame({
        "instrument": pd.array([r[0] for r in rows], dtype="string"),
        "symbol": pd.array([r[1] for r in rows], dtype="string"),
        "option_type": pd.array([r[2] for r in rows], dtype="string"),
        "strike": [float(r[3]) for r in rows],
        "expiry": pd.Series([pd.Timestamp(r[4]) for r in rows],
                            dtype="datetime64[us]"),
    })


def _patch_bhavcopy(monkeypatch, frame: pd.DataFrame):
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        lambda td, *, force_refresh=False, offline=False, **kw: frame,
    )


def _grid_20_2540_to_2660(symbol: str = "X", expiry: str = "2024-01-25"):
    """Standard ₹20-step strike grid spanning 2540..2660 for both CE/PE.
    Used by multiple offset-targeting tests."""
    strikes = list(range(2540, 2680, 20))  # [2540, 2560, ..., 2660]
    return _fake_bhavcopy(
        [("OPTSTK", symbol, "CE", k, expiry) for k in strikes]
        + [("OPTSTK", symbol, "PE", k, expiry) for k in strikes]
    )


# ============================================================
# LOAD-BEARING (a): offset=0 → degenerates to ShortStraddle ATM
# ============================================================

def test_offset_zero_degenerates_to_short_straddle(monkeypatch):
    """``strike_offset_pct=0`` puts both targets at spot, so call_strike
    == put_strike == ATM. Must match ShortStraddle's pick on the same
    fixture — the strangle is a generalization of the straddle."""
    _patch_bhavcopy(monkeypatch, _grid_20_2540_to_2660())

    strangle = ShortStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.65,
        params={"strike_offset_pct": 0.0},
    )[0]
    straddle = ShortStraddle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.65,
    )[0]

    strangle_strikes = sorted({leg.strike for leg in strangle.legs})
    straddle_strikes = sorted({leg.strike for leg in straddle.legs})
    assert strangle_strikes == straddle_strikes == [2600]


# ============================================================
# LOAD-BEARING (b): offset=0.02 on spot 2596 → call 2640, put 2540
# ============================================================

def test_offset_2pct_picks_expected_otm_strikes(monkeypatch):
    """Spot 2596 with ₹20 grid:
      call_target = 2596 × 1.02 = 2647.92 → nearest = 2640 (|−7.92|)
      put_target  = 2596 × 0.98 = 2544.08 → nearest = 2540 (|−4.08|)
    Pin the targeting arithmetic + SPECS §5 nearest-strike rule."""
    _patch_bhavcopy(monkeypatch, _grid_20_2540_to_2660())

    trade = ShortStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.0,
        params={"strike_offset_pct": 0.02},
    )[0]

    legs_by_type = {leg.option_type: leg for leg in trade.legs}
    assert legs_by_type["CE"].strike == 2640
    assert legs_by_type["PE"].strike == 2540
    # Both SELL legs — strangle is short by construction
    assert legs_by_type["CE"].side == "SELL"
    assert legs_by_type["PE"].side == "SELL"


# ============================================================
# LOAD-BEARING (c): margin offset = 0.70 per SPECS §4a
# ============================================================

def test_margin_offset_matches_specs():
    """SPECS §4a: short_strangle's portfolio-offset benefit is 0.70 —
    a touch less than short_straddle's 0.60 because OTM wings are
    slightly less correlated than ATM legs."""
    assert SHORT_STRANGLE_MARGIN_OFFSET == 0.70
    assert ShortStrangle().recommended_strategy_offset_pct == 0.70


# ============================================================
# LOAD-BEARING (d): sparse grid → falls back to nearest available
# ============================================================

def test_unavailable_target_falls_back_to_nearest(monkeypatch):
    """Sparse strike grid — neither the exact OTM target nor anything
    on a uniform step exists. Picker must NOT crash; it falls back to
    the nearest available strike per SPECS §5 argmin rule.

    Spot 2600, offset 0.02 → call_target=2652, put_target=2548. Only
    available strikes are {2500, 2700} on each side. Nearest →
    call=2700 (|48| < |152|), put=2500 (|48| < |152|)."""
    frame = _fake_bhavcopy([
        ("OPTSTK", "X", "CE", 2500, "2024-01-25"),
        ("OPTSTK", "X", "CE", 2700, "2024-01-25"),
        ("OPTSTK", "X", "PE", 2500, "2024-01-25"),
        ("OPTSTK", "X", "PE", 2700, "2024-01-25"),
    ])
    _patch_bhavcopy(monkeypatch, frame)

    trade = ShortStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2600.0,
        params={"strike_offset_pct": 0.02},
    )[0]
    legs_by_type = {leg.option_type: leg for leg in trade.legs}
    assert legs_by_type["CE"].strike == 2700
    assert legs_by_type["PE"].strike == 2500


# ============================================================
# Trade-shape & contract pins
# ============================================================

def test_short_strangle_emits_two_sell_legs(monkeypatch):
    _patch_bhavcopy(monkeypatch, _grid_20_2540_to_2660())
    out = ShortStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.0,
    )
    legs = out[0].legs
    assert len(legs) == 2
    assert {leg.option_type for leg in legs} == {"CE", "PE"}
    assert {leg.side for leg in legs} == {"SELL"}
    assert all(leg.qty_lots == 1 for leg in legs)


def test_default_offset_is_2pct(monkeypatch):
    """No params dict → DEFAULT_STRIKE_OFFSET_PCT = 0.02. Pins the
    default so callers who pass `params=None` get the OTM 2% strangle."""
    _patch_bhavcopy(monkeypatch, _grid_20_2540_to_2660())
    trade = ShortStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.0,
        params=None,
    )[0]
    legs_by_type = {leg.option_type: leg for leg in trade.legs}
    # Same as the offset=0.02 case above
    assert legs_by_type["CE"].strike == 2640
    assert legs_by_type["PE"].strike == 2540


def test_params_json_records_offset(monkeypatch):
    """The chosen offset must be persisted in Trade.params so the sweep
    result row records what strike-grid was used. Phase-5 filters by it."""
    _patch_bhavcopy(monkeypatch, _grid_20_2540_to_2660())
    trade = ShortStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.0,
        params={"strike_offset_pct": 0.02},
    )[0]
    assert trade.params == {"strike_offset_pct": 0.02}


def test_negative_offset_rejected(monkeypatch):
    """Negative offset would flip call/put targets (call ITM, put ITM)
    — almost certainly a caller bug. Reject loudly rather than silently
    inverting the strangle."""
    _patch_bhavcopy(monkeypatch, _grid_20_2540_to_2660())
    with pytest.raises(ValueError, match="strike_offset_pct"):
        ShortStrangle().generate_trades(
            "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
            spot_at_entry=2596.0,
            params={"strike_offset_pct": -0.02},
        )


def test_no_strikes_raises_no_liquid_strike_error(monkeypatch):
    """Empty bhavcopy filter → NoLiquidStrikeError (a MissingDataError
    subclass, so the sweeper's skip-loop catches it like for straddles)."""
    frame = _fake_bhavcopy([
        ("OPTSTK", "OTHER_SYMBOL", "CE", 1000, "2024-01-25"),
    ])
    _patch_bhavcopy(monkeypatch, frame)
    with pytest.raises(NoLiquidStrikeError):
        ShortStrangle().generate_trades(
            "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
            spot_at_entry=2600.0,
            params={"strike_offset_pct": 0.02},
        )


def test_symbol_normalized_to_upper(monkeypatch):
    _patch_bhavcopy(monkeypatch, _grid_20_2540_to_2660(symbol="RELIANCE"))
    trade = ShortStrangle().generate_trades(
        "reliance", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.0,
    )[0]
    assert trade.symbol == "RELIANCE"


def test_strangle_registered():
    """The registry must include short_strangle by the canonical name."""
    assert "short_strangle" in STRATEGIES
    assert isinstance(STRATEGIES["short_strangle"], ShortStrangle)
    assert STRATEGIES["short_strangle"].name == "short_strangle"


# ============================================================
# Determinism — same inputs, same legs
# ============================================================

def test_determinism_same_inputs_same_trade(monkeypatch):
    _patch_bhavcopy(monkeypatch, _grid_20_2540_to_2660())
    a = ShortStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.0, params={"strike_offset_pct": 0.02},
    )
    b = ShortStrangle().generate_trades(
        "X", date(2024, 1, 25), date(2024, 1, 4), date(2024, 1, 24),
        spot_at_entry=2596.0, params={"strike_offset_pct": 0.02},
    )
    assert a[0].legs == b[0].legs
