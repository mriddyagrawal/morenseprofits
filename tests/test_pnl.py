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

from src.data.errors import (
    IlliquidLegError,
    LookaheadError,
    MissingDataError,
    MissingTurnoverError,
)
from src.engine.pnl import (
    TURNOVER_SCALE_FACTOR,
    _compute_vwap,
    _pick_close_on,
    _pick_fill_price,
    _price_one_leg,
    price_trade,
)
from src.engine.slippage import SlippageModelV1
from src.strategies.base import Leg, Trade

# Many prior hand-checked tests assume zero slippage (the canonical
# values like RELIANCE Jan-2024 gross +₹2750 were computed at raw
# closes). New default is 1% slippage. Pin existing tests with this
# explicit override; a new test exercises the slippage path.
_NO_SLIPPAGE = SlippageModelV1(slippage_pct=0.0)


def _option_frame(dates_closes_lots: list[tuple[date, float, int]]) -> pd.DataFrame:
    """Build a §2.2-ish option frame with just the fields the kernel reads."""
    return pd.DataFrame({
        "date": pd.Series([pd.Timestamp(d) for d, _, _ in dates_closes_lots],
                          dtype="datetime64[us]"),
        "close": [c for _, c, _ in dates_closes_lots],
        "lot_size": pd.array([l for _, _, l in dates_closes_lots], dtype="int64"),
    })


def _stub_load_option(per_leg: dict[tuple[float, str], pd.DataFrame]):
    """Build a load_option_fn whose return depends on (strike, option_type).

    P1.7 (operator 2026-06-03) strips close-fallback from
    ``_pick_fill_price`` — every priced cell now flows through the
    VWAP path. The minimal ``_option_frame`` fixture only carries
    (date, close, lot_size), so this stub synthesizes the columns
    the engine needs:

      - ``strike`` injected from the per_leg key.
      - ``volume`` defaults to ``lot_size × 100`` (well below the
        100k liquidity bypass so fixtures still exercise the band
        check path; >0 so the IlliquidLegError gate doesn't trip).
      - ``turnover`` synthesized as ``(strike + close) × volume``
        so ``turnover / volume - strike = close``: VWAP fill ends
        up numerically equal to the close the legacy assertions
        expect, leaving the rest of the test untouched.

    Fixtures that explicitly populate volume/turnover/oi (e.g. via
    ``_option_frame_with_liquidity`` for zero-volume tests, or
    ``_option_frame_with_vwap`` for genuine VWAP-vs-close divergence
    tests) override these defaults — the injection only fills
    absent columns.
    """
    def fake(symbol, expiry, strike, option_type, from_date, to_date, *, today_fn=date.today, offline=False):
        key = (float(strike), option_type)
        if key not in per_leg:
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
    out = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE)
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
    out = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE)
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
    out = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE)
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

    def leaky_load(symbol, expiry, strike, option_type, from_date, to_date, *, today_fn=date.today, offline=False):
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
        price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE)


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
        price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE)


# ============================================================
# Liquidity gate — IlliquidLegError on entry/exit volume == 0 or
# entry oi == 0 (feat(p7.pricing.liquidity_gate))
# ============================================================

def _option_frame_with_liquidity(
    dates_closes_lots_vols_ois: list[tuple[date, float, int, int, int]],
) -> pd.DataFrame:
    """Like _option_frame but with explicit volume + oi columns so the
    liquidity-gate path is exercised. Production loaders always emit
    these per §2.3; the minimal _option_frame in the same module
    omits them so legacy tests stay backward-compatible (gate becomes
    a no-op when volume/oi columns absent)."""
    return pd.DataFrame({
        "date": pd.Series(
            [pd.Timestamp(d) for d, _, _, _, _ in dates_closes_lots_vols_ois],
            dtype="datetime64[us]",
        ),
        "close": [c for _, c, _, _, _ in dates_closes_lots_vols_ois],
        "lot_size": pd.array(
            [l for _, _, l, _, _ in dates_closes_lots_vols_ois], dtype="int64",
        ),
        "volume": pd.array(
            [v for _, _, _, v, _ in dates_closes_lots_vols_ois], dtype="int64",
        ),
        "oi": pd.array(
            [o for _, _, _, _, o in dates_closes_lots_vols_ois], dtype="Int64",
        ),
    })


def test_zero_entry_volume_raises_missing_turnover():
    """Entry day with volume=0 → MissingTurnoverError. Pre-P1.7 this
    was IlliquidLegError; under the unified spec all "no real fill
    possible" cases collapse to MissingTurnoverError."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame_with_liquidity([
        (entry, 100.0, 250, 0, 5000),    # entry: volume=0
        (exit_, 10.0, 250, 8000, 4500),
    ])
    load = _stub_load_option({(2600.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),),
        strategy="test",
    )
    with pytest.raises(MissingTurnoverError, match="volume=0"):
        price_trade(trade, load_option_fn=load,
                    today_fn=lambda: date(2026, 5, 24),
                    slippage_model=_NO_SLIPPAGE)


def test_zero_exit_volume_raises_missing_turnover():
    """Exit day with volume=0 → MissingTurnoverError (same collapse
    as entry-side under P1.7)."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame_with_liquidity([
        (entry, 100.0, 250, 8000, 5000),
        (exit_, 10.0, 250, 0, 4500),    # exit: volume=0
    ])
    load = _stub_load_option({(2600.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),),
        strategy="test",
    )
    with pytest.raises(MissingTurnoverError, match="volume=0"):
        price_trade(trade, load_option_fn=load,
                    today_fn=lambda: date(2026, 5, 24),
                    slippage_model=_NO_SLIPPAGE)


def test_zero_oi_prices_normally_under_p1_7():
    """Pre-P1.7: oi=0 raised IlliquidLegError on the theory that
    "no live positions = no counterparty". Under the P1.7 unified
    spec that gate is dropped — if volume>0 the contract demonstrably
    cleared trades, so the published OI=0 is at best an anomaly /
    data-quality issue, not a reason to refuse to price.

    Engine now prices the trade normally; if a future analysis wants
    to filter on OI it can do so post-hoc against the leg telemetry
    in legs_json."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame_with_liquidity([
        (entry, 100.0, 250, 8000, 0),    # entry: oi=0 — used to fire
        (exit_, 10.0, 250, 8000, 4500),
    ])
    load = _stub_load_option({(2600.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),),
        strategy="test",
    )
    # No raise — trade prices through. The stub's synthesized VWAP
    # equals close so gross_pnl matches the close-fallback value
    # that the pre-P1.7 test would have produced if the oi gate had
    # been removed.
    out = price_trade(trade, load_option_fn=load,
                      today_fn=lambda: date(2026, 5, 24),
                      slippage_model=_NO_SLIPPAGE)
    # SELL CE @ entry close=100, BUY back @ exit close=10 →
    # gross = (100 - 10) * 250 = 22500.
    assert out["gross_pnl"] == pytest.approx(22500.0, abs=1e-6)


def test_liquid_leg_prices_normally():
    """Happy path: positive volume on entry + exit, positive entry OI →
    trade prices normally. Regression guard so the gate doesn't fire on
    legitimately-traded legs."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame_with_liquidity([
        (entry, 100.0, 250, 8000, 5000),
        (exit_, 10.0, 250, 7500, 4500),
    ])
    load = _stub_load_option({(2600.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),),
        strategy="test",
    )
    out = price_trade(trade, load_option_fn=load,
                      today_fn=lambda: date(2026, 5, 24),
                      slippage_model=_NO_SLIPPAGE)
    # Short CE: SELL @100, BUY back @10 → gross = (100-10) × 250 = 22,500
    assert out["gross_pnl"] == pytest.approx(22500.0, abs=1e-6)


def test_illiquid_leg_error_is_a_missing_data_error():
    """IlliquidLegError extends MissingDataError so the sweeper's
    existing `except MissingDataError` skip-loop catches it without
    any sweeper-side changes. Pinned because flipping the inheritance
    would silently turn skipped cells into propagating exceptions.

    Under P1.7 the engine no longer raises this class (the volume=0
    and oi=0 cases collapsed into MissingTurnoverError) but the class
    is retained so historical sweep_*_skipped.parquet files carrying
    "IlliquidLegError" as a skip_reason string remain interpretable.
    The inheritance test is preserved as a back-compat anchor."""
    assert issubclass(IlliquidLegError, MissingDataError)


def test_missing_turnover_error_is_a_missing_data_error():
    """MissingTurnoverError extends MissingDataError so the sweeper's
    existing `except MissingDataError` skip-loop catches it without
    sweeper-side changes. Anti-regression on the inheritance — under
    P1.7 this class is the dominant skip_reason for cells that
    pre-fix would have used close-fallback."""
    assert issubclass(MissingTurnoverError, MissingDataError)


# ============================================================
# VWAP fill price — feat(p7.pricing.vwap_fill)
# ============================================================

def _option_frame_with_vwap(
    strike: float,
    rows: list[tuple[date, float, int, int, int, float]],
) -> pd.DataFrame:
    """Build an option frame with the ``strike`` + ``turnover`` columns
    populated so the VWAP-fill path is exercised under the strike-
    corrected formula.

    ``rows`` = list of ``(date, close, lot, volume_shares, oi, vwap_premium)``.
    For each row the fixture computes the turnover NSE would report
    under the (strike + premium) × shares convention (rupees, post-F1
    parser normalization — see pnl.TURNOVER_SCALE_FACTOR comment +
    LOGIC_REVIEW.md F1):

        turnover_rupees = (strike + vwap_premium) * volume_shares

    Tests pick the vwap_premium they want; the fixture builds the
    turnover that drives ``_pick_fill_price`` to that recovered value.
    Passing a NaN vwap_premium yields NaN turnover (exercises the
    legacy-cache fall-through-to-close path)."""
    import math
    turnovers = [
        ((strike + vwap) * v) if not math.isnan(vwap) else math.nan
        for _, _, _, v, _, vwap in rows
    ]
    n = len(rows)
    return pd.DataFrame({
        "date": pd.Series(
            [pd.Timestamp(d) for d, *_ in rows],
            dtype="datetime64[us]",
        ),
        "close": [c for _, c, *_ in rows],
        "strike": pd.array([strike] * n, dtype="float64"),
        "lot_size": pd.array([l for _, _, l, *_ in rows], dtype="int64"),
        "volume": pd.array([v for _, _, _, v, *_ in rows], dtype="int64"),
        "oi": pd.array([o for _, _, _, _, o, _ in rows], dtype="Int64"),
        "turnover": turnovers,
    })


def test_vwap_fill_used_when_turnover_present():
    """When turnover is present and units pass the band, the engine
    fills at the strike-corrected VWAP (notional/share − strike), not
    at close.

    Fixture: strike=2600, close=100, vwap_premium=98 (entry) / 20 (exit).
    Fills at 98 (entry) / 20 (exit). Cross-check the turnover the
    fixture would have produced: (2600+98)×10000 = 26,980,000 rupees
    (post-F1 parser-normalized rupees convention)."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame_with_vwap(
        strike=2600.0,
        rows=[
            (entry, 100.0, 250, 10000, 5000, 98.0),   # vwap=98 vs close=100
            (exit_,  20.0, 250,  5000, 4500, 20.0),   # vwap=20 vs close=20
        ],
    )
    load = _stub_load_option({(2600.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),),
        strategy="test",
    )
    out = price_trade(trade, load_option_fn=load,
                      today_fn=lambda: date(2026, 5, 24),
                      slippage_model=_NO_SLIPPAGE)
    # SELL @ entry VWAP=98, BUY back @ exit VWAP=20
    # gross = (98 - 20) × 250 = 19,500 (not 20,000 if close was used)
    assert out["gross_pnl"] == pytest.approx(19500.0, abs=1e-6)


def test_nan_turnover_raises_missing_turnover_under_p1_7():
    """Pre-P1.7 NaN turnover fell through to close (legacy parquet
    compatibility). Under the unified P1.7 spec there is no close
    fallback — NaN turnover means we can't compute VWAP and the
    cell is skipped honestly with MissingTurnoverError."""
    import math
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame_with_vwap(
        strike=2600.0,
        rows=[
            (entry, 100.0, 250, 10000, 5000, math.nan),
            (exit_,  20.0, 250,  5000, 4500, math.nan),
        ],
    )
    load = _stub_load_option({(2600.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),),
        strategy="test",
    )
    with pytest.raises(MissingTurnoverError, match="turnover=None"):
        price_trade(trade, load_option_fn=load,
                    today_fn=lambda: date(2026, 5, 24),
                    slippage_model=_NO_SLIPPAGE)


def test_band_reject_on_thin_contract_raises_missing_turnover():
    """Under P1.7 a band-reject (recovered VWAP outside [0.5×, 2.0×]
    of close) on a THIN contract (contracts_traded < 20 bypass)
    raises MissingTurnoverError. Pre-P1.7 this fell through to
    close — that fudged the fill with a tick-floor close print that
    misled backtest analysis (per the empirical close-fallback
    audit 2026-06-03).

    Fixture: strike=100, close=100, vwap_premium=300 → ratio 3.0
    (out of band); volume=2500 at lot=250 → 10 contracts (well
    under the 20-contract bypass)."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame_with_vwap(
        strike=100.0,
        rows=[
            (entry, 100.0, 250, 2500, 5000, 300.0),   # contracts=10 → band still applies; vwap=300 vs close=100 → out of band
            (exit_,  20.0, 250, 2500, 4500,  20.0),
        ],
    )
    load = _stub_load_option({(100.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 100, "SELL", 1),),
        strategy="test",
    )
    with pytest.raises(MissingTurnoverError, match="band reject"):
        price_trade(trade, load_option_fn=load,
                    today_fn=lambda: date(2026, 5, 24),
                    slippage_model=_NO_SLIPPAGE)


def test_band_reject_bypassed_when_contracts_above_liquidity_threshold():
    """Option C (P1.7): the VWAP-vs-close band check is BYPASSED on
    contracts with contracts_traded ≥
    _VWAP_LIQUIDITY_BYPASS_CONTRACTS (20 contracts). A liquid
    contract's VWAP integrates over many trades and is structurally
    more accurate than close even when the ratio is wide (e.g.,
    close is a tick-floor artefact while VWAP averages morning
    trades at higher prices). Anti-regression on the 20-contract
    bypass.

    Fixture: same shape as the band-reject test but with volume
    raised to 25,000 / lot=250 → 100 contracts (well above the
    20-contract bypass). Engine uses VWAP=300 instead of close=100,
    even though the ratio is 3.0."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame_with_vwap(
        strike=100.0,
        rows=[
            (entry, 100.0, 250, 25_000, 5000, 300.0),   # contracts=100 → bypasses band; vwap=300 vs close=100
            (exit_,  20.0, 250, 25_000, 4500,  20.0),
        ],
    )
    load = _stub_load_option({(100.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 100, "SELL", 1),),
        strategy="test",
    )
    out = price_trade(trade, load_option_fn=load,
                      today_fn=lambda: date(2026, 5, 24),
                      slippage_model=_NO_SLIPPAGE)
    # SELL @ VWAP=300 (band bypassed), BUY back @ VWAP=20 →
    # gross = (300 - 20) × 250 = 70,000.
    # Pre-P1.7 would have hit close=100 → (100 - 20) × 250 = 20,000.
    assert out["gross_pnl"] == pytest.approx(70000.0, abs=1e-6)


def test_recovered_premium_negative_raises_missing_turnover():
    """Pre-P1.7: deep-OTM ill-conditioning (turnover/volume - strike ≤ 0)
    fell through to close. Under the P1.7 unified spec it raises
    MissingTurnoverError — the cell is unpriceable, and a tick-floor
    close fill would systematically bias deep-OTM analysis."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    # Construct turnover (rupees, post-F1 convention) that gives
    # notional/share = strike - 1 (i.e. recovered premium would be -1).
    # Strike = 1000, volume = 10000. notional_per_share target = 999
    # → turnover = 999 × 10000 = 9_990_000 rupees.
    df = pd.DataFrame({
        "date": pd.Series([pd.Timestamp(entry), pd.Timestamp(exit_)],
                          dtype="datetime64[us]"),
        "close": [0.05, 0.05],
        "strike": pd.array([1000.0, 1000.0], dtype="float64"),
        "lot_size": pd.array([250, 250], dtype="int64"),
        "volume": pd.array([10000, 10000], dtype="int64"),
        "oi": pd.array([5000, 4500], dtype="Int64"),
        "turnover": [9_990_000.0, 9_990_000.0],   # notional/share = 999, recov_prem = -1
    })
    load = _stub_load_option({(1000.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 1000, "SELL", 1),),
        strategy="test",
    )
    with pytest.raises(MissingTurnoverError, match="VWAP premium ≤ 0"):
        price_trade(trade, load_option_fn=load,
                    today_fn=lambda: date(2026, 5, 24),
                    slippage_model=_NO_SLIPPAGE)


def test_compute_vwap_returns_none_when_inputs_missing():
    """The independently-callable helper must return None on volume=0,
    None volume, or None turnover — caller falls through to close.
    Strike is required but its value doesn't matter when an earlier
    guard trips."""
    assert _compute_vwap(turnover=10.0, volume=0, strike=100.0) is None
    assert _compute_vwap(turnover=10.0, volume=None, strike=100.0) is None
    assert _compute_vwap(turnover=None, volume=100, strike=100.0) is None


def test_compute_vwap_recovers_premium_via_strike_subtraction():
    """Pin the formula: notional_per_share = turnover * SCALE / volume,
    recovered premium = notional_per_share − strike. Post-F1 the
    parser-layer normalization moves the units conversion out of the
    engine; SCALE = 1.0 so the formula reads cleanly as
    ``turnover / volume − strike`` with turnover in rupees.

    Worked example: strike=100, turnover=1,200,000 rupees, volume=10,000
        notional/share = 1,200,000 / 10,000 = 120
        premium_vwap   = 120 − 100 = 20

    Anti-regression for both ``TURNOVER_SCALE_FACTOR`` and the strike
    subtraction. If a future contributor drops the subtraction (the
    pre-correction bug), the recovered value here would be 120 not 20
    and this test fires. If TURNOVER_SCALE_FACTOR is bumped away from
    1.0 without the parsers being denormalized in lockstep, the
    1,200,000 input would no longer produce 20 and this test fires."""
    assert _compute_vwap(turnover=1_200_000.0, volume=10_000, strike=100.0) == pytest.approx(20.0)
    # Strike=0 → behaves like the pre-correction formula (useful for
    # synthetic tests where the caller has already absorbed the strike).
    assert _compute_vwap(turnover=1_000_000.0, volume=50_000, strike=0.0) == pytest.approx(20.0)
    assert TURNOVER_SCALE_FACTOR == 1.0


def test_f1_recovers_premium_for_reliance_2840_ce_under_rupees_convention():
    """F1 regression: anchored against the LOGIC_REVIEW.md empirical
    fixture (RELIANCE 2024-08-29 2840-CE). Pre-F1 the engine assumed
    UDiff TtlTrfVal was in lakhs (TURNOVER_SCALE_FACTOR=1e5) so a row
    with turnover=19,661,050 rupees overshot notional by ×1e5 → the
    band-reject safety valve fired → engine silently fell back to
    close on every fill (0/24,019 VWAPs across the smoke universe).

    Post-F1 (parsers normalize to rupees + SCALE=1.0):
        notional_per_share = 19,661,050 / 6,500 = 3,024.7769...
        premium_vwap       = 3,024.78 - 2,840   = 184.7769...

    Matches the empirical premium recovered by the displayed
    sweep_5f199d6984f2.parquet (~184.78). If this test regresses, F1
    has either been undone OR a future contributor has put the ×1e5
    back into pnl.py while leaving the parsers normalized — either
    way the smoke gate would diverge from api mode and the operator
    would see 100% close fallback again. Anti-regression on the
    load-bearing units invariant."""
    recovered = _compute_vwap(
        turnover=19_661_050.0, volume=6_500, strike=2840.0,
    )
    assert recovered == pytest.approx(184.7769, abs=0.001)


def test_compute_vwap_recovered_premium_negative_returns_none():
    """Deep-OTM ill-conditioning guard: when notional_per_share − strike
    goes ≤ 0, _compute_vwap returns None so the caller can fall back to
    close. Without this, the engine could book a trade at a negative
    fill price."""
    # notional/share = 99 (turnover=9.9 lakhs / 10000 vol), strike=100
    # recovered = -1 → None
    assert _compute_vwap(turnover=9.9, volume=10_000, strike=100.0) is None


def test_compute_vwap_time_decay_structural():
    """The user-suggested structural test: as DTE → 0 on an OTM call,
    premium decays toward 0, so the recovered VWAP from the formula
    must also decay toward 0 (not stay at spot). This is the
    falsifying test for the rejected "notional = spot" theory — that
    theory predicts the recovered value stays at strike regardless of
    time-decay, while the correct (strike + premium) theory predicts
    decay toward 0.

    Fixture: same OTM strike across 4 synthetic DTE points with
    premium decaying 10 → 5 → 1 → 0.05. The recovered VWAP must
    track that decay. Strike=1300, volume=10_000 each day."""
    strike = 1300.0
    # Synthetic NSE turnover for each (premium, vol) under the
    # post-F1 (strike + premium) × shares formula (rupees):
    for premium in (10.0, 5.0, 1.0, 0.05):
        turnover = (strike + premium) * 10_000
        recovered = _compute_vwap(turnover=turnover, volume=10_000, strike=strike)
        assert recovered == pytest.approx(premium, abs=1e-9), (
            f"premium={premium} should recover exactly; got {recovered}"
        )


def test_vwap_legs_json_carries_entry_turnover_and_exit_turnover():
    """Per-leg audit telemetry: the trade's legs_json must include
    entry_turnover + exit_turnover so post-hoc analysis can identify
    cells where VWAP and close diverged significantly. Confirms the
    leg-result dict surfaces them."""
    import json
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    # vwap_premium=98 → turnover = (2600+98)*10000 = 26,980,000 rupees
    # vwap_premium=20 → turnover = (2600+20)*5000 = 13,100,000 rupees
    df = _option_frame_with_vwap(
        strike=2600.0,
        rows=[
            (entry, 100.0, 250, 10000, 5000, 98.0),
            (exit_,  20.0, 250,  5000, 4500, 20.0),
        ],
    )
    load = _stub_load_option({(2600.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),),
        strategy="test",
    )
    out = price_trade(trade, load_option_fn=load,
                      today_fn=lambda: date(2026, 5, 24),
                      slippage_model=_NO_SLIPPAGE)
    legs = json.loads(out["legs_json"])
    assert len(legs) == 1
    assert legs[0]["entry_turnover"] == pytest.approx(26_980_000.0)
    assert legs[0]["exit_turnover"] == pytest.approx(13_100_000.0)


def test_gate_silent_when_volume_oi_columns_absent():
    """Backward-compat: minimal test fixtures from _option_frame
    (which omits volume + oi columns) skip the gate entirely.
    _pick_close_on returns None for missing columns; ``None == 0`` is
    False in Python, so the gate predicate is a no-op. Existing tests
    relying on this minimal fixture continue to pass without
    modification."""
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
    out = price_trade(trade, load_option_fn=load,
                      today_fn=lambda: date(2026, 5, 24),
                      slippage_model=_NO_SLIPPAGE)
    # Trade prices through despite no volume/oi telemetry — confirms
    # the gate's predicate is no-op when columns absent.
    assert out["gross_pnl"] == pytest.approx(22500.0, abs=1e-6)


def test_lot_size_change_mid_contract_skipped_as_missing_data():
    """If lot_size on entry-date row differs from exit-date row, the
    contract straddled a corporate-action ex-date (split / bonus / merger)
    — NSE adjusts F&O contracts so the same contract sees different lot
    sizes on either side. We can't price across the action without
    strike+qty ratio'ing, so skip via MissingDataError (sweeper logs
    the cell and continues). NOT a LookaheadError: data isn't bad, it's
    just unpriceable under our v1 model."""
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
    with pytest.raises(MissingDataError, match="lot_size changed"):
        price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE)


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
    out = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE)
    expected = {"symbol", "expiry", "entry_date", "exit_date", "strategy",
                "params_json", "legs_json", "gross_pnl",
                "costs", "net_pnl", "costs_breakdown_json",
                "margin_at_entry", "margin_breakdown_json", "roi_pct",
                "hold_trading_days", "roi_pct_annualized"}
    assert set(out) == expected
    # New: hold + annualization fields populated
    assert out["hold_trading_days"] > 0
    assert out["roi_pct_annualized"] is not None
    # 252 / hold_trading_days × roi_pct
    expected_ann = out["roi_pct"] * 252 / out["hold_trading_days"]
    assert out["roi_pct_annualized"] == pytest.approx(expected_ann, abs=1e-9)


def test_hold_trading_days_calendar_to_trading_conversion():
    """Pin the calendar→trading-day approximation explicitly so a future
    "let's switch to actual trading_calendar lookup" change is visible
    as a test diff, not silently shifts annualized rankings.

    20 calendar days × 252/365 = 13.8 → round to 14 trading days. (My
    own commit-message in 169c7d6 wrongly claimed "20 trading days";
    the code rounds to 14. Pin the truth.)"""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)  # 20 calendar days
    df = _option_frame([(entry, 100.0, 250), (exit_, 50.0, 250)])
    load = _stub_load_option({(2600.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),), strategy="test",
    )
    out = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24),
                      slippage_model=_NO_SLIPPAGE)
    assert out["hold_trading_days"] == 14, (
        f"20 calendar days should convert to 14 trading days, got "
        f"{out['hold_trading_days']}"
    )


def test_hold_trading_days_kwarg_overrides_calendar_approximation():
    """SPECS §4a caveat #2 fix: when the caller knows the exact
    trading-day hold (the sweeper does — entry_offset_td − exit_offset_td),
    it passes it via kwarg and the engine uses it instead of the
    252/365 calendar approximation.

    Canonical bug case caught by p4.verify: 2 calendar days
    (entry Wed, exit Fri, same week) → round(2 × 252/365) =
    round(1.38) = 1 trading day, but the real hold is 2. The 2×
    inflation in roi_pct_annualized polluted the leaderboard for
    short-window sweep cells. The fix lets the sweeper pass the
    exact count."""
    entry = date(2024, 1, 17)   # Wednesday
    exit_ = date(2024, 1, 19)   # Friday — 2 calendar days, 2 trading days
    df = _option_frame([(entry, 100.0, 250), (exit_, 50.0, 250)])
    load = _stub_load_option({(2600.0, "CE"): df})
    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),), strategy="test",
    )

    # Without kwarg → biased approximation (1 trading day)
    approx_out = price_trade(
        trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24),
        slippage_model=_NO_SLIPPAGE,
    )
    assert approx_out["hold_trading_days"] == 1  # the bug

    # With kwarg (what the sweeper passes) → exact (2 trading days)
    exact_out = price_trade(
        trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24),
        slippage_model=_NO_SLIPPAGE, hold_trading_days=2,
    )
    assert exact_out["hold_trading_days"] == 2

    # And the annualized ROI is halved (no longer 2×-inflated)
    assert exact_out["roi_pct_annualized"] == pytest.approx(
        approx_out["roi_pct_annualized"] / 2.0, abs=1e-6,
    )


def test_reliance_jan_2024_full_pipeline_gross_costs_net_margin_roi():
    """LOAD-BEARING for the full financial picture: all THREE layers
    tied together on the canonical RELIANCE Jan-2024 short straddle.

    Expected from prior hand-checks:
      gross_pnl  = +₹2,750     (P&L kernel)
      costs      = ~₹141.78    (COST_MODEL_V1, SPECS §4)
      net_pnl    = ~₹2,608.22
      margin     = ₹2,60,000   (MARGIN_MODEL_V1, SPECS §4a; 2 × 0.20 × 2600 × 250)
      roi_pct    = ~+1.00 %    (net_pnl / margin × 100)
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
    # Explicit symbol_margin_pct=0.20 pins the Tier-A baseline behavior
    # for this assertion; the new auto-vol path is tested separately
    # in test_auto_vol_resolves_symbol_margin_pct below.
    out = price_trade(
        trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24),
        symbol_margin_pct=0.20, slippage_model=_NO_SLIPPAGE,
    )
    assert out["gross_pnl"] == 2750.0
    assert out["costs"] == pytest.approx(141.780645, abs=1e-3)
    assert out["net_pnl"] == pytest.approx(2608.219, abs=1e-3)
    assert out["margin_at_entry"] == 260_000.0  # 2 × 0.20 × 2600 × 250
    assert out["roi_pct"] == pytest.approx(100 * 2608.219 / 260_000.0, abs=1e-3)


def test_auto_vol_resolves_symbol_margin_pct_when_kwarg_absent(monkeypatch):
    """When symbol_margin_pct is NOT passed, price_trade auto-computes
    it from the symbol's realized vol. Pin the resolution path."""
    # pnl.py imports the function as `_symbol_margin_pct`; patch at the
    # call site, not at src.engine.vol.
    from src.engine import pnl as pnl_mod
    monkeypatch.setattr(pnl_mod, "_symbol_margin_pct", lambda *a, **kw: 0.17)

    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    df = _option_frame([(entry, 100.0, 250), (exit_, 50.0, 250)])
    load = _stub_load_option({(2600.0, "CE"): df})
    trade = Trade(
        symbol="RELIANCE", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),), strategy="test",
    )
    # No symbol_margin_pct kwarg → engine auto-computes (via the mocked
    # vol module = 0.17). Margin = 0.17 × 2600 × 250 = 110500.
    out = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE)
    assert out["margin_at_entry"] == pytest.approx(0.17 * 2600 * 250, abs=1e-6)


def test_spot_at_entry_flows_through_to_margin_basis():
    """SPECS §4a caveat #1: price_trade plumbs spot_at_entry to
    MarginModelV1.estimate. Same trade priced once with strike-based
    (no kwarg) and once with spot-based (with kwarg, spot != strike).
    Margin should differ predictably; the margin_breakdown_json should
    record `notional_basis`.

    Setup: SELL 2700 CE on spot=2596.65 (deep OTM, biggest bias).
    Strike-based: 0.20 × 2700 × 250 = ₹1,35,000.
    Spot-based:   0.20 × 2596.65 × 250 = ₹1,29,832.50.
    Strike overstates by ~₹5,167."""
    import json
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    ce = _option_frame([(entry, 30.0, 250), (exit_, 5.0, 250)])
    load = _stub_load_option({(2700.0, "CE"): ce})
    trade = Trade(
        symbol="RELIANCE", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2700, "SELL", 1),),
        strategy="naked_short_call",
    )
    common = dict(
        load_option_fn=load, today_fn=lambda: date(2026, 5, 24),
        slippage_model=_NO_SLIPPAGE, symbol_margin_pct=0.20,
    )
    strike_based = price_trade(trade, **common)
    spot_based = price_trade(trade, spot_at_entry=2596.65, **common)

    assert strike_based["margin_at_entry"] == pytest.approx(0.20 * 2700 * 250)
    assert spot_based["margin_at_entry"] == pytest.approx(0.20 * 2596.65 * 250)
    assert strike_based["margin_at_entry"] > spot_based["margin_at_entry"]

    # margin_breakdown_json records which basis was used (auditable
    # in the parquet by Phase-5 / debugging).
    strike_bd = json.loads(strike_based["margin_breakdown_json"])
    spot_bd = json.loads(spot_based["margin_breakdown_json"])
    assert strike_bd["notional_basis"] == "strike"
    assert spot_bd["notional_basis"] == "spot"


def test_strategy_offset_pct_flows_through_to_margin():
    """Strategy classes pass their real-world offset; price_trade
    forwards it. Short straddle 0.60 → margin drops by 40%."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    ce = _option_frame([(entry, 100.0, 250), (exit_, 10.0, 250)])
    pe = _option_frame([(entry, 100.0, 250), (exit_, 10.0, 250)])
    load = _stub_load_option({(2600.0, "CE"): ce, (2600.0, "PE"): pe})
    trade = Trade(
        symbol="RELIANCE", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1), Leg("PE", 2600, "SELL", 1)),
        strategy="short_straddle",
    )
    # Pin symbol_margin_pct=0.20 to isolate the strategy_offset effect.
    no_offset = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE,
                            symbol_margin_pct=0.20)
    with_offset = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE,
                              symbol_margin_pct=0.20, strategy_offset_pct=0.60)
    assert no_offset["margin_at_entry"] == 260_000.0
    assert with_offset["margin_at_entry"] == pytest.approx(260_000.0 * 0.60, abs=1e-6)
    # ROI improves correspondingly (same net, lower margin)
    assert with_offset["roi_pct"] > no_offset["roi_pct"]


def test_cost_model_is_injectable_for_sensitivity():
    """Zero-brokerage variant returns smaller costs; doesn't affect
    the default singleton — pin the dependency-injection contract."""
    from src.engine.costs import CostModelV1
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
    out_default = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE)
    zero_brokerage = CostModelV1(brokerage_per_order=0.0)
    out_zero = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE,
                           cost_model=zero_brokerage)
    # Zero-brokerage saves exactly 2 orders × ₹20 = ₹40 (single-leg trade)
    # plus the 18% GST that would have applied to that brokerage = ₹7.20
    assert out_default["costs"] - out_zero["costs"] == pytest.approx(40 + 40*0.18, abs=1e-6)
    # net_pnl moves by the same delta
    assert out_zero["net_pnl"] - out_default["net_pnl"] == pytest.approx(40 + 40*0.18, abs=1e-6)


# ============================================================
# qty_lots > 1 scales linearly
# ============================================================

def test_default_slippage_applied_asymmetrically():
    """LOAD-BEARING for the asymmetric-conservatism direction. Default
    slippage_pct=0.01 makes SELL entries receive less + BUY exits pay
    more. For a short straddle this REDUCES gross P&L regardless of
    direction; for losers it makes the loss bigger; for winners it
    makes the win smaller — the asymmetric conservatism the user asked
    for.

    Canonical hand-check using RELIANCE Jan-2024 fixture:
      CE: SELL 56.50/BUY 95.00 → realized SELL 55.935, BUY 95.95
          gross = (55.935 - 95.95) × 250 = -10003.75
      PE: SELL 50.00/BUY 0.50 → realized SELL 49.50, BUY 0.505
          gross = (49.50 - 0.505) × 250 = +12248.75
      Total gross (with 1% slippage) = +2245.0
      vs +2750.0 without slippage → ₹505 haircut.
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
    # Default slippage_pct=0.01 — see SPECS §4b for the formula
    assert out["gross_pnl"] == pytest.approx(2245.0, abs=0.5), (
        f"slippage haircut wrong; got {out['gross_pnl']}"
    )
    # legs_json carries both raw + realized prices
    import json
    legs = json.loads(out["legs_json"])
    ce_leg = next(l for l in legs if l["option_type"] == "CE")
    assert ce_leg["entry_px"] == 56.50  # raw
    assert ce_leg["entry_px_realized"] == pytest.approx(55.935, abs=1e-6)
    assert ce_leg["exit_px"] == 95.00
    assert ce_leg["exit_px_realized"] == pytest.approx(95.95, abs=1e-6)


def test_slippage_zero_disables():
    """slippage_model with 0% pct → realized == raw close → matches the
    original (no-slippage) hand-checks. Pins the toggle path."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 24)
    ce = _option_frame([(entry, 56.50, 250), (exit_, 95.00, 250)])
    pe = _option_frame([(entry, 50.00, 250), (exit_, 0.50, 250)])
    load = _stub_load_option({(2600.0, "CE"): ce, (2600.0, "PE"): pe})
    trade = Trade(
        symbol="RELIANCE", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1), Leg("PE", 2600, "SELL", 1)),
        strategy="short_straddle",
    )
    out = price_trade(trade, load_option_fn=load, today_fn=lambda: date(2026, 5, 24),
                      slippage_model=_NO_SLIPPAGE)
    assert out["gross_pnl"] == 2750.0  # original hand-check value


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
    o1 = price_trade(t1, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE)
    o3 = price_trade(t3, load_option_fn=load, today_fn=lambda: date(2026, 5, 24), slippage_model=_NO_SLIPPAGE)
    assert o3["gross_pnl"] == 3 * o1["gross_pnl"]


# ============================================================
# LOAD-BEARING: offline propagation through price_trade → load_option
# ============================================================
def test_offline_flag_propagates_to_load_option():
    """Regression for the cache_only bug: sweep_one was passing
    ``offline=True`` to spot/trading_calendar but ``price_trade`` did
    NOT forward it to ``load_option``. Workers in cache_only mode still
    hit NSE for option contracts → throttled wide sweeps. Pin the
    propagation here so a future refactor can't silently drop it.

    The stub asserts it received ``offline=True``; if price_trade omits
    it the assertion fails loud at test time, not at run time."""
    entry = date(2024, 1, 4)
    exit_ = date(2024, 1, 25)
    captured = {}

    # Inline-stub the columns the post-P1.7 _pick_fill_price requires
    # (strike/volume/turnover/oi). Without these the engine raises
    # MissingTurnoverError before the assertion gets to inspect what
    # offline value was captured.
    def watching_load(symbol, expiry, strike, option_type, from_date, to_date, *, today_fn, offline=False):
        captured["offline"] = offline
        df = _option_frame([(entry, 100.0, 250), (exit_, 10.0, 250)]).copy()
        df["strike"] = float(strike)
        df["volume"] = (df["lot_size"] * 100).astype("int64")
        df["turnover"] = ((df["strike"] + df["close"]) * df["volume"]).astype("float64")
        df["oi"] = pd.array([1000] * len(df), dtype="Int64")
        return df

    trade = Trade(
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=entry, exit_date=exit_,
        legs=(Leg("CE", 2600, "SELL", 1),),
        strategy="test",
    )
    price_trade(
        trade, load_option_fn=watching_load,
        today_fn=lambda: date(2026, 5, 24),
        slippage_model=_NO_SLIPPAGE,
        offline=True,
    )
    assert captured["offline"] is True, (
        "price_trade must propagate offline=True to load_option_fn — "
        "without this, cache_only=True sweeps still let workers hit NSE"
    )


# ============================================================
# classify_fill_source — centralized fill-source audit helper
# (chore(p8.fill_audit.centralize): pulled out of dashboard +
# backtest_one duplicates per c3545cc reviewer grills #1+#2)
# ============================================================

def test_classify_fill_source_vwap_match_atm_price():
    """₹100 ATM-ish premium, exact VWAP match → 'vwap'. Under the
    post-F1 (rupees) convention the synthetic turnover encodes
    (strike + premium) × shares directly, so for strike=2500,
    premium=100, volume=10_000 → turnover = 2600 × 10_000 = 26,000,000
    rupees."""
    from src.engine.pnl import classify_fill_source
    # recovered = 26,000,000 / 10,000 - 2500 = 2600 - 2500 = 100
    assert classify_fill_source(100.0, 10_000, 26_000_000.0, strike=2500.0) == "vwap"


def test_classify_fill_source_vwap_match_with_turnover_precision_noise():
    """Real turnover values are quantised at the rupee scale; tiny
    rounding deltas shouldn't break the 'vwap' classification. A
    computed recovered-premium of 100.005 vs entry_px=100.00 should
    still classify as 'vwap' — the centralized tolerance is generous
    enough to absorb the quantisation noise."""
    from src.engine.pnl import classify_fill_source
    # turnover = 26,000,050 → notional/share = 2600.005,
    # recovered = 2600.005 - 2500 = 100.005
    assert classify_fill_source(100.0, 10_000, 26_000_050.0, strike=2500.0) == "vwap"


def test_classify_fill_source_vwap_match_deep_otm():
    """LOAD-BEARING per c3545cc reviewer grill #3 (carry-over from
    6ab4866 grill #2): deep-OTM contracts (₹0.05 premium) shouldn't
    fail-match on turnover quantisation. The absolute tolerance floor
    (~₹0.001) is what carries this — relative tolerance alone at 0.1%
    would demand byte-perfect agreement on ₹0.05 which turnover precision
    can't deliver.

    Post-F1 (rupees): strike=2500, premium=0.05, volume=100_000;
    turnover = 2500.05 × 100_000 = 250,005,000 rupees. Perturb
    turnover by 10 rupees → notional/share = 2500.0510, recovered =
    0.0510. Tolerance absorbs the 0.001 absolute delta."""
    from src.engine.pnl import classify_fill_source
    assert classify_fill_source(0.05, 100_000, 250_005_100.0, strike=2500.0) == "vwap"


def test_classify_fill_source_close_when_turnover_absent():
    from src.engine.pnl import classify_fill_source
    assert classify_fill_source(100.0, 1000, None, strike=2500.0) == "close"
    assert classify_fill_source(100.0, 1000, float("nan"), strike=2500.0) == "close"


def test_classify_fill_source_close_when_volume_zero():
    from src.engine.pnl import classify_fill_source
    assert classify_fill_source(100.0, 0, 10.0, strike=2500.0) == "close"


def test_classify_fill_source_close_when_strike_absent():
    """Strike is required to recover the correct VWAP. When telemetry
    callers haven't been updated to pass strike (None default), the
    classifier degrades to 'close' rather than guessing — false 'vwap'
    classification is worse than honest 'close' here."""
    from src.engine.pnl import classify_fill_source
    assert classify_fill_source(100.0, 10_000, 260.0, strike=None) == "close"


def test_classify_fill_source_close_when_diverges_outside_tolerance():
    """Engine had VWAP available (turnover + volume + strike present)
    but the recorded entry_px diverges from the implied — engine fell
    back to close, probably via the band-reject safety valve. ``close``."""
    from src.engine.pnl import classify_fill_source
    # recovered = 26,000,000 / 10,000 - 2500 = 100; entry_px = 50 → 50% off
    assert classify_fill_source(50.0, 10_000, 26_000_000.0, strike=2500.0) == "close"


def test_classify_fill_source_close_when_recovered_premium_nonpositive():
    """Deep-OTM ill-conditioning: when the recovered premium goes ≤ 0,
    the engine would have fallen back to close. Mirror that in
    classify_fill_source — don't pretend it was a VWAP fill."""
    from src.engine.pnl import classify_fill_source
    # notional/share = 99 (turnover=9.9, vol=10_000), strike=100 →
    # recovered = -1 → close
    assert classify_fill_source(0.05, 10_000, 9.9, strike=100.0) == "close"


def test_classify_fill_source_unknown_on_nan_or_none():
    from src.engine.pnl import classify_fill_source
    assert classify_fill_source(None, 1000, 5.0, strike=100.0) == "unknown"
    assert classify_fill_source(float("nan"), 1000, 5.0, strike=100.0) == "unknown"
