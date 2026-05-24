"""Tests for src.engine.pnl. No network — load_option monkeypatched
or stubbed in.

The load-bearing test is `test_sign_convention_short_straddle`: SELL
legs with entry > exit must produce positive P&L. A single sign flip
in the kernel inverts every backtest by 100% silently.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data.errors import LookaheadError, MissingDataError
from src.engine.pnl import price_trade, _pick_close_on, _price_one_leg
from src.strategies.base import Leg, Trade


def _option_frame(dates_closes_lots: list[tuple[date, float, int]]) -> pd.DataFrame:
    """Build a §2.2-ish option frame with just the fields the kernel reads."""
    return pd.DataFrame({
        "date": pd.Series([pd.Timestamp(d) for d, _, _ in dates_closes_lots],
                          dtype="datetime64[us]"),
        "close": [c for _, c, _ in dates_closes_lots],
        "lot_size": pd.array([l for _, _, l in dates_closes_lots], dtype="int64"),
    })


def _stub_load_option(per_leg: dict[tuple[float, str], pd.DataFrame]):
    """Build a load_option_fn whose return depends on (strike, option_type)."""
    def fake(symbol, expiry, strike, option_type, from_date, to_date, *, today_fn=date.today):
        key = (float(strike), option_type)
        if key not in per_leg:
            raise MissingDataError(f"no fixture for {key}")
        df = per_leg[key]
        # Filter to the loader's promised window so the kernel sees
        # exactly [from_date, to_date] like the real loader.
        mask = (df["date"] >= pd.Timestamp(from_date)) & (df["date"] <= pd.Timestamp(to_date))
        return df.loc[mask].reset_index(drop=True)
    return fake


# ============================================================
# LOAD-BEARING: sign convention — short straddle on a decay scenario
# ============================================================

def test_sign_convention_short_straddle():
    """Sell CE at 100, sell PE at 100. At exit both have decayed to 10.
    Lot size 250, 1 lot each.
    Per-leg gross = (100 - 10) * (+1 SELL) * 1 * 250 = +22500.
    Two legs → total gross = +45000. If sign is flipped, this fires."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 25)
    ce_frame = _option_frame([(entry, 100.0, 250), (exit_, 10.0, 250)])
    pe_frame = _option_frame([(entry, 100.0, 250), (exit_, 10.0, 250)])
    load = _stub_load_option({(2600.0, "CE"): ce_frame, (2600.0, "PE"): pe_frame})

    trade = Trade(
        symbol="RELIANCE", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(
            Leg("CE", 2600, "SELL", 1),
            Leg("PE", 2600, "SELL", 1),
        ),
        strategy="short_straddle",
    )
    out = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24))
    assert out["gross_pnl"] == 45000.0, (
        f"short straddle premium decay must produce positive P&L; "
        f"got {out['gross_pnl']}. Sign flip?"
    )


def test_sign_convention_long_straddle_loses_on_decay():
    """Same prices, BUY side: gross = -45000. Pins the BUY=-1 sign."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 25)
    ce_frame = _option_frame([(entry, 100.0, 250), (exit_, 10.0, 250)])
    pe_frame = _option_frame([(entry, 100.0, 250), (exit_, 10.0, 250)])
    load = _stub_load_option({(2600.0, "CE"): ce_frame, (2600.0, "PE"): pe_frame})

    trade = Trade(
        symbol="RELIANCE", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(
            Leg("CE", 2600, "BUY", 1),
            Leg("PE", 2600, "BUY", 1),
        ),
        strategy="long_straddle",
    )
    out = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24))
    assert out["gross_pnl"] == -45000.0


# ============================================================
# Hand-checked RELIANCE Jan-2024 short straddle (Phase 1 integration)
# ============================================================

def test_reliance_jan_2024_atm_short_straddle_hand_check():
    """Anchored on the Phase-1 integration verify (commit 2518c50):
    RELIANCE Jan-25 expiry 2600 CE on Jan-4 entry → close 56.50.
    Made-up matching PE close 50 for the hand-check. Exit Jan-24
    (one day before expiry) with CE 95, PE 0.50 (typical post-rally).
    Lot 250.
       CE: (56.50 - 95.00) * 1 * 1 * 250 = -9625
       PE: (50.00 -  0.50) * 1 * 1 * 250 = +12375
       Total gross = +2750
    """
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    ce = _option_frame([(entry, 56.50, 250), (exit_, 95.00, 250)])
    pe = _option_frame([(entry, 50.00, 250), (exit_, 0.50, 250)])
    load = _stub_load_option({(2600.0, "CE"): ce, (2600.0, "PE"): pe})

    trade = Trade(
        symbol="RELIANCE", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(
            Leg("CE", 2600, "SELL", 1),
            Leg("PE", 2600, "SELL", 1),
        ),
        strategy="short_straddle",
    )
    out = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24))
    assert out["gross_pnl"] == 2750.0
    assert out["symbol"] == "RELIANCE"
    assert out["expiry"] == date(2024, 1, 25)
    assert out["entry_date"] == entry
    assert out["exit_date"] == exit_
    assert out["strategy"] == "short_straddle"


# ============================================================
# LOAD-BEARING: no-look-ahead — frame with post-exit rows raises
# ============================================================

def test_lookahead_rejected():
    """If load_option (incorrectly) returns rows past exit_date, the
    kernel must raise LookaheadError rather than silently include them.
    Pins SPECS §3b — engine-layer enforcement of PLAN §4 rule #1."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    past_exit = date(2024, 1, 25)
    # Return a frame with a row past exit_date — that's a loader bug
    # which the kernel must catch loudly. (We bypass the loader's
    # window filter in the stub so the offending row makes it through.)
    leaky_frame = _option_frame([
        (entry, 100.0, 250), (exit_, 10.0, 250), (past_exit, 5.0, 250),
    ])

    def leaky_load(symbol, expiry, strike, option_type, from_date, to_date, *, today_fn=date.today):
        return leaky_frame  # NO filter — returns the leaky row

    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 100, "SELL", 1),),
        strategy="test",
    )
    with pytest.raises(LookaheadError, match="past exit_date"):
        price_trade(trade, load_option_fn=leaky_load, today_fn=lambda: date(2026, 5, 24))


def test_missing_data_at_entry_raises():
    """Empty frame at entry_date → MissingDataError, NOT silent zero."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    # Frame has only an exit-date row — missing entry
    df = _option_frame([(exit_, 10.0, 250)])
    load = _stub_load_option({(2600.0, "CE"): df})

    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),),
        strategy="test",
    )
    with pytest.raises(MissingDataError, match="no traded row on"):
        price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24))


def test_missing_data_at_exit_raises():
    """Empty frame at exit_date → MissingDataError. No silent
    interpolation."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame([(entry, 100.0, 250)])
    load = _stub_load_option({(2600.0, "CE"): df})

    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),),
        strategy="test",
    )
    with pytest.raises(MissingDataError, match="no traded row on"):
        price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24))


def test_lot_size_change_mid_contract_rejected():
    """If lot_size on entry-date row differs from exit-date row,
    refuse to silently pick one. NSE changes lot sizes between
    contracts but never mid-contract; if we see drift, it's data
    corruption."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame([(entry, 100.0, 250), (exit_, 10.0, 500)])
    load = _stub_load_option({(2600.0, "CE"): df})

    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),),
        strategy="test",
    )
    with pytest.raises(LookaheadError, match="lot_size changed"):
        price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24))


def test_returned_schema_matches_results_2_5_subset():
    """Pin the keys the kernel emits — downstream sweeper assumes
    these exist."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame([(entry, 100.0, 250), (exit_, 10.0, 250)])
    load = _stub_load_option({(2600.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),),
        strategy="test",
    )
    out = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24))
    expected = {"symbol", "expiry", "entry_date", "exit_date", "strategy",
                "params_json", "legs_json", "gross_pnl"}
    assert set(out) == expected


# ============================================================
# qty_lots > 1 scales linearly
# ============================================================

def test_qty_lots_scales_linearly():
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame([(entry, 100.0, 250), (exit_, 10.0, 250)])
    load = _stub_load_option({(2600.0, "CE"): df})

    # 1 lot
    t1 = Trade(symbol="X", expiry=date(2024, 1, 25), entry_date=entry, exit_date=exit_,
               legs=(Leg("CE", 2600, "SELL", 1),), strategy="test")
    # 3 lots — same leg
    t3 = Trade(symbol="X", expiry=date(2024, 1, 25), entry_date=entry, exit_date=exit_,
               legs=(Leg("CE", 2600, "SELL", 3),), strategy="test")
    o1 = price_trade(t1, load_option_fn=load, today_fn=lambda: date(2026, 5, 24))
    o3 = price_trade(t3, load_option_fn=load, today_fn=lambda: date(2026, 5, 24))
    assert o3["gross_pnl"] == 3 * o1["gross_pnl"]
