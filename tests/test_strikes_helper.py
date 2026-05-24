"""Tests for src.strategies._strikes — the SPECS §5 picker that all 5
v1 strategies depend on.

If this module breaks, every strategy breaks in the same way. So pin
its two ops directly here in addition to the per-strategy tests that
exercise it transitively.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data import bhavcopy_fo_loader
from src.data.errors import MissingDataError
from src.strategies._strikes import (
    NoLiquidStrikeError,
    load_available_strikes,
    pick_nearest,
)


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


# ============================================================
# load_available_strikes — filtering + sorting + dedup
# ============================================================

def test_load_returns_sorted_unique_ints(monkeypatch):
    """Strikes returned ascending, deduplicated, cast to int (the
    canonical NSE OPTSTK type)."""
    frame = _fake_bhavcopy([
        # Out-of-order, with duplicates (CE + PE on same strike count once)
        ("OPTSTK", "RELIANCE", "CE", 2600, "2024-01-25"),
        ("OPTSTK", "RELIANCE", "PE", 2600, "2024-01-25"),
        ("OPTSTK", "RELIANCE", "CE", 2540, "2024-01-25"),
        ("OPTSTK", "RELIANCE", "CE", 2660, "2024-01-25"),
        ("OPTSTK", "RELIANCE", "PE", 2580, "2024-01-25"),
    ])
    _patch_bhavcopy(monkeypatch, frame)
    out = load_available_strikes("RELIANCE", date(2024, 1, 25), date(2024, 1, 4))
    assert out == [2540, 2580, 2600, 2660]
    assert all(isinstance(k, int) for k in out)


def test_load_filters_by_symbol_expiry_instrument(monkeypatch):
    """Bhavcopy holds rows for many symbols/expiries; load must return
    only the requested combination."""
    frame = _fake_bhavcopy([
        ("OPTSTK", "INFY", "CE", 1500, "2024-01-25"),       # wrong symbol
        ("OPTSTK", "X", "CE", 9999, "2024-02-29"),          # wrong expiry
        ("FUTSTK", "X", "CE", 8888, "2024-01-25"),          # wrong instrument
        ("OPTIDX", "X", "CE", 7777, "2024-01-25"),          # OPTIDX not OPTSTK
        ("OPTSTK", "X", "CE", 2600, "2024-01-25"),          # ← only this
        ("OPTSTK", "X", "PE", 2620, "2024-01-25"),          # ← and this
    ])
    _patch_bhavcopy(monkeypatch, frame)
    out = load_available_strikes("X", date(2024, 1, 25), date(2024, 1, 4))
    assert out == [2600, 2620]


def test_load_case_insensitive_symbol(monkeypatch):
    """Strategies receive symbol from user code in any case; loader
    uppercases internally to match bhavcopy convention."""
    frame = _fake_bhavcopy([
        ("OPTSTK", "RELIANCE", "CE", 2600, "2024-01-25"),
    ])
    _patch_bhavcopy(monkeypatch, frame)
    out = load_available_strikes("reliance", date(2024, 1, 25), date(2024, 1, 4))
    assert out == [2600]


def test_load_raises_no_liquid_strike_error_on_empty(monkeypatch):
    """Empty filter result → NoLiquidStrikeError. Tested both that the
    error fires and that it's catchable as MissingDataError (so the
    sweeper's skip-loop handles it)."""
    frame = _fake_bhavcopy([
        ("OPTSTK", "OTHER_SYMBOL", "CE", 1000, "2024-01-25"),
    ])
    _patch_bhavcopy(monkeypatch, frame)
    with pytest.raises(NoLiquidStrikeError):
        load_available_strikes("X", date(2024, 1, 25), date(2024, 1, 4))
    # Catchable as MissingDataError
    try:
        load_available_strikes("X", date(2024, 1, 25), date(2024, 1, 4))
    except MissingDataError:
        pass


# ============================================================
# pick_nearest — SPECS §5 argmin + lower-tiebreaker
# ============================================================

def test_pick_nearest_basic_argmin():
    """Target 2611 between 2600 and 2620 → 2620 is closer (|9| vs |11|)."""
    assert pick_nearest([2600, 2620], 2611.0) == 2620


def test_pick_nearest_tiebreaker_picks_lower():
    """SPECS §5: equidistant → lower strike. Target 2610 sits exactly
    between 2600 and 2620; must return 2600. A naive `min()` without
    the tuple key could pick 2620 depending on iteration order."""
    assert pick_nearest([2600, 2620], 2610.0) == 2600


def test_pick_nearest_target_above_all_strikes():
    """Target way above the grid → highest strike."""
    assert pick_nearest([2500, 2600, 2700], 5000.0) == 2700


def test_pick_nearest_target_below_all_strikes():
    """Target way below the grid → lowest strike."""
    assert pick_nearest([2500, 2600, 2700], 100.0) == 2500


def test_pick_nearest_target_exactly_on_strike():
    """Target == strike → that strike (zero distance, no tiebreaker)."""
    assert pick_nearest([2500, 2600, 2700], 2600.0) == 2600


def test_pick_nearest_single_strike():
    """Degenerate single-strike grid → that strike, regardless of target."""
    assert pick_nearest([2600], 1000.0) == 2600
    assert pick_nearest([2600], 5000.0) == 2600


# ============================================================
# Error hierarchy
# ============================================================

def test_no_liquid_strike_error_is_missing_data_subclass():
    """Sweeper's _SKIPPABLE_ERRORS = (MissingDataError, ...) must catch
    this. Pin the hierarchy explicitly."""
    assert issubclass(NoLiquidStrikeError, MissingDataError)
