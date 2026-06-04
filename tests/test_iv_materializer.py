"""Tests for src.data.iv_materializer.

All tests use synthetic bhavcopy + spot frames; no dependency on
the live cache. The composed end-to-end tests monkeypatch
``load_bhavcopy_fo``, ``load_spot``, and ``trading_days`` so the
materializer runs entirely in-memory.

LOAD-BEARING tests:
  - ``test_compute_iv_for_day_round_trip_recovers_input_sigma`` —
    the whole point. Price synthetic options under a known σ, run
    the materializer, recover σ.
  - ``test_constant_maturity_30d_excl7_drops_near_expiry`` — pins
    the operator-locked methodology default.
  - ``test_materialize_writes_parquet_with_canonical_schema`` —
    the cache-boundary contract.
  - ``test_materialize_none_to_nan_at_cache_boundary`` — what the
    reviewer asked for in c79e1ce's deferred grill.
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data import cache, iv_materializer
from src.data.iv_materializer import (
    ExpiryIV,
    IV_HISTORY_COLUMNS,
    NEAR_EXPIRY_EXCLUSION_DAYS,
    RISK_FREE_RATE,
    TARGET_DTE,
    _atm_strike,
    _compute_iv_for_day,
    _constant_maturity_30d,
    _front_month_iv,
    _iv_per_expiry,
    load_iv_history,
    materialize_iv_history,
)
from src.engine.iv import bs76_call_price, bs76_put_price


# ============================================================
# Fixtures
# ============================================================

def _redirect_cache(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache._reset_root_memo()


def _make_chain_row(
    symbol: str,
    expiry: date,
    strike: float,
    option_type: str,
    close: float,
    trade_date: date,
) -> dict:
    """One bhavcopy row with the SPECS §2.4 schema columns the
    materializer touches. Extra fields kept minimal — the
    materializer reads symbol / expiry / strike / option_type /
    close only."""
    return {
        "symbol": symbol,
        "expiry": pd.Timestamp(expiry),
        "strike": float(strike),
        "option_type": option_type,
        "close": float(close),
    }


def _synthetic_chain(
    symbol: str,
    trade_date: date,
    expiries_with_sigma: list[tuple[date, float]],
    spot: float,
    *,
    strikes_around: int = 5,
    strike_step: float = 10.0,
    forward_eq_spot: bool = True,
) -> pd.DataFrame:
    """Build a synthetic bhavcopy frame: one symbol, N expiries,
    each with a band of strikes priced under a known σ via Black-76.

    With ``forward_eq_spot=True`` the forward is fixed at spot
    (zero carry / zero dividend) — keeps the parity-extracted F
    equal to spot, so the materializer's extracted forward matches
    the analytical one and the IV inversion recovers σ exactly.
    """
    rows: list[dict] = []
    atm = round(spot / strike_step) * strike_step
    strikes = [
        atm + (i - strikes_around // 2) * strike_step
        for i in range(strikes_around)
    ]
    F = spot if forward_eq_spot else spot * 1.005
    for expiry, sigma in expiries_with_sigma:
        dte = (expiry - trade_date).days
        if dte <= 0:
            continue
        T = dte / 365.0
        for k in strikes:
            c_px = bs76_call_price(F, k, T, sigma, RISK_FREE_RATE)
            p_px = bs76_put_price(F, k, T, sigma, RISK_FREE_RATE)
            rows.append(_make_chain_row(symbol, expiry, k, "CE", c_px, trade_date))
            rows.append(_make_chain_row(symbol, expiry, k, "PE", p_px, trade_date))
    return pd.DataFrame(rows)


# ============================================================
# _atm_strike — closest-strike + both-legs-non-zero gate
# ============================================================

def test_atm_strike_picks_closest_to_spot_when_all_legs_non_zero():
    """Spot ₹107, strikes [100, 105, 110, 115] — ATM = 105
    (closest below) vs 110 (closest above); abs diff = 2 < 3 → 105."""
    chain = pd.DataFrame([
        {"strike": k, "option_type": ot, "close": 5.0}
        for k in (100.0, 105.0, 110.0, 115.0) for ot in ("CE", "PE")
    ])
    assert _atm_strike(chain, spot=107.0) == 105.0


def test_atm_strike_returns_none_when_no_common_strikes():
    """Only CE rows present → no PE intersection → None.
    Catches the case where a malformed chain skips one leg."""
    chain = pd.DataFrame([
        {"strike": k, "option_type": "CE", "close": 5.0}
        for k in (100.0, 105.0, 110.0)
    ])
    assert _atm_strike(chain, spot=105.0) is None


def test_atm_strike_skips_strike_with_zero_close_on_either_leg():
    """ATM=110 by distance, but PE close=0 → skip, fall back to 100
    (the other strike with both legs non-zero)."""
    chain = pd.DataFrame([
        {"strike": 100.0, "option_type": "CE", "close": 8.0},
        {"strike": 100.0, "option_type": "PE", "close": 3.0},
        {"strike": 110.0, "option_type": "CE", "close": 4.0},
        {"strike": 110.0, "option_type": "PE", "close": 0.0},
    ])
    assert _atm_strike(chain, spot=108.0) == 100.0


def test_atm_strike_returns_none_when_all_strikes_have_zero_leg():
    chain = pd.DataFrame([
        {"strike": 100.0, "option_type": "CE", "close": 0.0},
        {"strike": 100.0, "option_type": "PE", "close": 0.0},
    ])
    assert _atm_strike(chain, spot=100.0) is None


# ============================================================
# _front_month_iv
# ============================================================

def test_front_month_iv_returns_first_by_dte():
    """Per-expiry list is already DTE-sorted ascending."""
    per_exp = [
        ExpiryIV(expiry=date(2024, 5, 30), dte=10, atm_strike=100.0, iv=0.20),
        ExpiryIV(expiry=date(2024, 6, 27), dte=38, atm_strike=100.0, iv=0.25),
    ]
    assert _front_month_iv(per_exp) == 0.20


def test_front_month_iv_returns_none_on_empty():
    assert _front_month_iv([]) is None


# ============================================================
# _constant_maturity_30d — interpolation
# ============================================================

def test_constant_maturity_30d_brackets_target_dte_in_variance_space():
    """LOAD-BEARING. Two expiries at 10 and 60 DTE — TARGET_DTE=30
    sits in the middle (linearly proportional). Variance interp:
    var_30 = var_10 · (60-30)/50 + var_60 · (30-10)/50
           = 0.04·0.6 + 0.16·0.4 = 0.024 + 0.064 = 0.088
    σ_30   = √0.088 ≈ 0.2966."""
    per_exp = [
        ExpiryIV(expiry=date(2024, 5, 30), dte=10, atm_strike=100.0, iv=0.20),
        ExpiryIV(expiry=date(2024, 6, 27), dte=60, atm_strike=100.0, iv=0.40),
    ]
    cmi = _constant_maturity_30d(per_exp, exclude_lt_dte=0)
    assert cmi == pytest.approx(math.sqrt(0.088), abs=1e-9)


def test_constant_maturity_30d_returns_none_when_fewer_than_two_survivors():
    """Single expiry → CMI undefined."""
    per_exp = [
        ExpiryIV(expiry=date(2024, 5, 30), dte=15, atm_strike=100.0, iv=0.20),
    ]
    assert _constant_maturity_30d(per_exp, exclude_lt_dte=0) is None


def test_constant_maturity_30d_all_far_extrapolates_to_closest_pair():
    """Both expiries past 30 DTE (60 and 90); fallback orders by DTE
    ascending and lerp/extrapolates. σ_60 = 0.30, σ_90 = 0.20.
    var_30 = var_60 · (90-30)/30 + var_90 · (30-60)/30
           = 0.09·2 + 0.04·(-1) = 0.18 - 0.04 = 0.14
    σ_30 = √0.14 ≈ 0.3742."""
    per_exp = [
        ExpiryIV(expiry=date(2024, 7, 1), dte=60, atm_strike=100.0, iv=0.30),
        ExpiryIV(expiry=date(2024, 8, 1), dte=90, atm_strike=100.0, iv=0.20),
    ]
    cmi = _constant_maturity_30d(per_exp, exclude_lt_dte=0)
    assert cmi == pytest.approx(math.sqrt(0.14), abs=1e-9)


def test_constant_maturity_30d_clamps_negative_extrapolation_to_zero():
    """Pathological extrapolation case: both expiries far past 30,
    extrapolating IV² linearly produces a negative variance. Clamp
    to 0 (σ_30 → 0) per the explicit guard in the implementation —
    prevents downstream NaN poisoning."""
    # σ_50 = 1.00 → var=1.00; σ_60 = 0.10 → var=0.01.
    # Extrapolate to DTE=30: span=10, var_50·(60-30)/10 + var_60·(30-50)/10
    #   = 1.00·3 + 0.01·(-2) = 3.00 - 0.02 = 2.98 — actually positive here.
    # Make it negative: σ_50=0.10 (var=0.01), σ_60=2.00 (var=4.0).
    # var_30 = 0.01·3 + 4.0·(-2) = 0.03 - 8.0 = -7.97 → clamp to 0.
    per_exp = [
        ExpiryIV(expiry=date(2024, 7, 1), dte=50, atm_strike=100.0, iv=0.10),
        ExpiryIV(expiry=date(2024, 7, 10), dte=60, atm_strike=100.0, iv=2.00),
    ]
    cmi = _constant_maturity_30d(per_exp, exclude_lt_dte=0)
    assert cmi == 0.0


def test_constant_maturity_30d_applies_dte_floor():
    """Excl7 filter drops the DTE=3 survivor; remaining two
    (DTE=15 + DTE=45) bracket 30 DTE."""
    per_exp = [
        ExpiryIV(expiry=date(2024, 5, 24), dte=3, atm_strike=100.0, iv=0.50),
        ExpiryIV(expiry=date(2024, 6, 5), dte=15, atm_strike=100.0, iv=0.20),
        ExpiryIV(expiry=date(2024, 7, 5), dte=45, atm_strike=100.0, iv=0.30),
    ]
    cmi_raw = _constant_maturity_30d(per_exp, exclude_lt_dte=0)
    cmi_excl = _constant_maturity_30d(per_exp, exclude_lt_dte=NEAR_EXPIRY_EXCLUSION_DAYS)
    # raw uses DTE=15 + DTE=45; excl7 also uses DTE=15 + DTE=45 (DTE=3
    # was the only one filtered) → SAME bracket.
    assert cmi_raw == pytest.approx(cmi_excl, abs=1e-9)
    # Hand-check the math: var_15=0.04, var_45=0.09; span=30.
    # var_30 = 0.04·(45-30)/30 + 0.09·(30-15)/30 = 0.02 + 0.045 = 0.065.
    assert cmi_raw == pytest.approx(math.sqrt(0.065), abs=1e-9)


def test_constant_maturity_30d_excl7_drops_near_expiry():
    """LOAD-BEARING for the operator-locked methodology default.
    With ONE near-expiry survivor (DTE=3) and ONE far survivor
    (DTE=40), raw CMI bracket-interpolates between them. With
    excl7 the near drops → only 1 survivor → CMI = None."""
    per_exp = [
        ExpiryIV(expiry=date(2024, 5, 24), dte=3, atm_strike=100.0, iv=0.50),
        ExpiryIV(expiry=date(2024, 6, 30), dte=40, atm_strike=100.0, iv=0.20),
    ]
    cmi_raw = _constant_maturity_30d(per_exp, exclude_lt_dte=0)
    cmi_excl = _constant_maturity_30d(per_exp, exclude_lt_dte=NEAR_EXPIRY_EXCLUSION_DAYS)
    assert cmi_raw is not None
    assert cmi_excl is None


def test_constant_maturity_30d_rms_combines_on_tie_dte():
    """Degenerate same-DTE case: σ₁=0.20, σ₂=0.40 →
    √(0.5·(0.04 + 0.16)) = √0.10 ≈ 0.3162."""
    per_exp = [
        ExpiryIV(expiry=date(2024, 6, 1), dte=20, atm_strike=100.0, iv=0.20),
        ExpiryIV(expiry=date(2024, 6, 2), dte=20, atm_strike=100.0, iv=0.40),
    ]
    cmi = _constant_maturity_30d(per_exp, exclude_lt_dte=0)
    assert cmi == pytest.approx(math.sqrt(0.10), abs=1e-9)


# ============================================================
# _iv_per_expiry — composed parity + inversion
# ============================================================

def test_iv_per_expiry_recovers_sigma_under_known_pricing():
    """LOAD-BEARING. Price synthetic options under σ=0.25, parity-
    extract forward (which equals spot under our zero-carry
    synthetic), invert → recover 0.25."""
    trade_date = date(2024, 5, 1)
    expiry = date(2024, 5, 30)
    spot = 1000.0
    bhav = _synthetic_chain(
        "RELIANCE", trade_date,
        [(expiry, 0.25)],
        spot=spot,
    )
    per_exp = _iv_per_expiry("RELIANCE", trade_date, spot, bhav)
    assert len(per_exp) == 1
    assert per_exp[0].dte == (expiry - trade_date).days
    assert per_exp[0].iv == pytest.approx(0.25, abs=1e-4)


def test_iv_per_expiry_skips_expired_and_returns_dte_sorted():
    """DTE ≤ 0 expiries dropped; remaining sorted ascending."""
    trade_date = date(2024, 5, 1)
    spot = 1000.0
    bhav = _synthetic_chain(
        "RELIANCE", trade_date,
        [
            (date(2024, 4, 25), 0.20),  # expired DTE=-6 → skip
            (date(2024, 6, 27), 0.25),
            (date(2024, 5, 30), 0.30),
        ],
        spot=spot,
    )
    per_exp = _iv_per_expiry("RELIANCE", trade_date, spot, bhav)
    assert [e.dte for e in per_exp] == [29, 57]
    assert per_exp[0].iv == pytest.approx(0.30, abs=1e-4)
    assert per_exp[1].iv == pytest.approx(0.25, abs=1e-4)


def test_iv_per_expiry_returns_empty_for_unknown_symbol():
    """Bhavcopy carries the universe; querying for a non-listed
    symbol is silent-empty, NOT an error."""
    trade_date = date(2024, 5, 1)
    bhav = _synthetic_chain(
        "RELIANCE", trade_date, [(date(2024, 5, 30), 0.25)], spot=1000.0,
    )
    assert _iv_per_expiry("INFY", trade_date, 1500.0, bhav) == []


def test_iv_per_expiry_skips_expiry_with_no_atm_strike():
    """Build a chain where one expiry has all PE legs at 0 close
    (no valid ATM) but another expiry is well-formed. Only the
    well-formed one survives."""
    trade_date = date(2024, 5, 1)
    expiry_a = date(2024, 5, 30)
    expiry_b = date(2024, 6, 27)
    spot = 1000.0
    bhav = _synthetic_chain(
        "RELIANCE", trade_date,
        [(expiry_a, 0.25), (expiry_b, 0.30)],
        spot=spot,
    )
    # Wipe all PE closes for expiry_a.
    mask = (bhav["expiry"] == pd.Timestamp(expiry_a)) & (bhav["option_type"] == "PE")
    bhav.loc[mask, "close"] = 0.0
    per_exp = _iv_per_expiry("RELIANCE", trade_date, spot, bhav)
    assert len(per_exp) == 1
    assert per_exp[0].expiry == expiry_b


# ============================================================
# _compute_iv_for_day
# ============================================================

def test_compute_iv_for_day_round_trip_recovers_input_sigma():
    """LOAD-BEARING. Two expiries bracketing 30 DTE, both priced at
    σ=0.25 → all three IV series should land at 0.25."""
    trade_date = date(2024, 5, 1)
    spot = 1000.0
    bhav = _synthetic_chain(
        "RELIANCE", trade_date,
        [(date(2024, 5, 16), 0.25), (date(2024, 6, 27), 0.25)],
        spot=spot,
    )
    rec = _compute_iv_for_day("RELIANCE", trade_date, spot, bhav)
    assert rec is not None
    assert rec["iv_front"] == pytest.approx(0.25, abs=1e-4)
    assert rec["iv_cmi30_raw"] == pytest.approx(0.25, abs=1e-4)
    assert rec["iv_cmi30_excl7"] == pytest.approx(0.25, abs=1e-4)
    assert rec["n_expiries_used"] == 2


def test_compute_iv_for_day_one_expiry_front_only_cmi_nan():
    """Single expiry → iv_front populated, both CMI series NaN
    (need ≥ 2 expiries). Tests the None → NaN translation at the
    boundary for a partial-population case."""
    trade_date = date(2024, 5, 1)
    spot = 1000.0
    bhav = _synthetic_chain(
        "RELIANCE", trade_date,
        [(date(2024, 5, 30), 0.25)],
        spot=spot,
    )
    rec = _compute_iv_for_day("RELIANCE", trade_date, spot, bhav)
    assert rec is not None
    assert rec["iv_front"] == pytest.approx(0.25, abs=1e-4)
    assert np.isnan(rec["iv_cmi30_raw"])
    assert np.isnan(rec["iv_cmi30_excl7"])
    assert rec["n_expiries_used"] == 1


def test_compute_iv_for_day_returns_none_when_no_expiry_survives():
    """All expiries expired → no per_exp records → None.
    Caller skips the day cleanly without writing a NaN row."""
    trade_date = date(2024, 5, 1)
    bhav = _synthetic_chain(
        "RELIANCE", trade_date,
        [(date(2024, 4, 25), 0.25)],  # already expired
        spot=1000.0,
    )
    assert _compute_iv_for_day("RELIANCE", trade_date, 1000.0, bhav) is None


# ============================================================
# materialize_iv_history — end-to-end with monkeypatched loaders
# ============================================================

def _patch_loaders(
    monkeypatch,
    *,
    days: list[date],
    spots: dict[date, float],
    bhavs: dict[date, pd.DataFrame],
):
    """Stub the three I/O loaders the materializer calls so the
    test exercises the composed pipeline in-memory."""

    def fake_trading_days(from_date, to_date, *, today_fn=None, offline=False):
        return [d for d in days if from_date <= d <= to_date]

    def fake_load_spot(symbol, from_date, to_date, *,
                       force_refresh=False, today_fn=None, offline=False):
        if from_date != to_date:
            raise AssertionError("materializer should single-day query")
        sp = spots.get(from_date)
        if sp is None:
            return pd.DataFrame({"date": [], "close": []})
        return pd.DataFrame({
            "date": [pd.Timestamp(from_date)],
            "close": [sp],
        })

    def fake_load_bhavcopy(trade_date, *, force_refresh=False, offline=False):
        return bhavs.get(trade_date, pd.DataFrame())

    monkeypatch.setattr(iv_materializer, "trading_days", fake_trading_days)
    monkeypatch.setattr(iv_materializer, "load_spot", fake_load_spot)
    monkeypatch.setattr(iv_materializer, "load_bhavcopy_fo", fake_load_bhavcopy)


def test_materialize_writes_parquet_with_canonical_schema(monkeypatch, tmp_path):
    """LOAD-BEARING cache-boundary contract: parquet columns +
    dtypes pinned. Downstream analytics rely on this."""
    _redirect_cache(monkeypatch, tmp_path)
    trade_date = date(2024, 5, 1)
    spot = 1000.0
    bhav = _synthetic_chain(
        "RELIANCE", trade_date,
        [(date(2024, 5, 16), 0.25), (date(2024, 6, 27), 0.25)],
        spot=spot,
    )
    _patch_loaders(monkeypatch,
                   days=[trade_date],
                   spots={trade_date: spot},
                   bhavs={trade_date: bhav})
    out = materialize_iv_history("RELIANCE", trade_date, trade_date)
    assert list(out.columns) == list(IV_HISTORY_COLUMNS)
    assert str(out["date"].dtype).startswith("datetime64")
    assert out["iv_front"].dtype == np.float64
    assert out["iv_cmi30_raw"].dtype == np.float64
    assert out["iv_cmi30_excl7"].dtype == np.float64
    assert out["atm_strike_front"].dtype == np.float64
    assert out["n_expiries_used"].dtype == np.int64

    # Parquet was actually written.
    cache_path = cache.iv_path("RELIANCE")
    assert cache_path.is_file()

    # Round-trip via load_iv_history.
    loaded = load_iv_history("RELIANCE")
    pd.testing.assert_frame_equal(out, loaded)


def test_materialize_recovers_sigma_end_to_end(monkeypatch, tmp_path):
    """LOAD-BEARING. Single-day end-to-end: price → materialize →
    recover σ from the parquet."""
    _redirect_cache(monkeypatch, tmp_path)
    trade_date = date(2024, 5, 1)
    spot = 2500.0
    bhav = _synthetic_chain(
        "RELIANCE", trade_date,
        [(date(2024, 5, 16), 0.28), (date(2024, 6, 27), 0.28)],
        spot=spot,
        strike_step=25.0,
    )
    _patch_loaders(monkeypatch,
                   days=[trade_date],
                   spots={trade_date: spot},
                   bhavs={trade_date: bhav})
    out = materialize_iv_history("RELIANCE", trade_date, trade_date)
    assert len(out) == 1
    assert out["iv_front"].iloc[0] == pytest.approx(0.28, abs=1e-4)
    assert out["iv_cmi30_excl7"].iloc[0] == pytest.approx(0.28, abs=1e-4)


def test_materialize_multi_day_sorts_by_date_ascending(monkeypatch, tmp_path):
    """Multi-day window; output index is sorted regardless of
    days iteration order."""
    _redirect_cache(monkeypatch, tmp_path)
    d1 = date(2024, 5, 1)
    d2 = date(2024, 5, 2)
    d3 = date(2024, 5, 3)
    spot = 1000.0
    bhav_factory = lambda td, sigma: _synthetic_chain(
        "RELIANCE", td,
        [(date(2024, 5, 30), sigma), (date(2024, 6, 27), sigma)],
        spot=spot,
    )
    _patch_loaders(monkeypatch,
                   days=[d3, d1, d2],  # intentionally unsorted
                   spots={d1: spot, d2: spot, d3: spot},
                   bhavs={d1: bhav_factory(d1, 0.20),
                          d2: bhav_factory(d2, 0.22),
                          d3: bhav_factory(d3, 0.24)})
    out = materialize_iv_history("RELIANCE", d1, d3)
    assert list(out["date"].dt.date) == [d1, d2, d3]
    assert out["iv_front"].iloc[0] == pytest.approx(0.20, abs=1e-4)
    assert out["iv_front"].iloc[1] == pytest.approx(0.22, abs=1e-4)
    assert out["iv_front"].iloc[2] == pytest.approx(0.24, abs=1e-4)


def test_materialize_skips_days_with_missing_spot(monkeypatch, tmp_path):
    """No spot for day 2 → silently skip. Output has 2 rows, not 3."""
    _redirect_cache(monkeypatch, tmp_path)
    d1, d2, d3 = date(2024, 5, 1), date(2024, 5, 2), date(2024, 5, 3)
    spot = 1000.0
    bhav_factory = lambda td: _synthetic_chain(
        "RELIANCE", td,
        [(date(2024, 5, 30), 0.25), (date(2024, 6, 27), 0.25)],
        spot=spot,
    )
    _patch_loaders(monkeypatch,
                   days=[d1, d2, d3],
                   spots={d1: spot, d3: spot},  # d2 missing
                   bhavs={d1: bhav_factory(d1), d2: bhav_factory(d2), d3: bhav_factory(d3)})
    out = materialize_iv_history("RELIANCE", d1, d3)
    assert len(out) == 2
    assert list(out["date"].dt.date) == [d1, d3]


def test_materialize_skips_days_with_empty_bhavcopy(monkeypatch, tmp_path):
    """Missing bhavcopy → silently skip."""
    _redirect_cache(monkeypatch, tmp_path)
    d1, d2 = date(2024, 5, 1), date(2024, 5, 2)
    spot = 1000.0
    bhav = _synthetic_chain(
        "RELIANCE", d1,
        [(date(2024, 5, 30), 0.25), (date(2024, 6, 27), 0.25)],
        spot=spot,
    )
    _patch_loaders(monkeypatch,
                   days=[d1, d2],
                   spots={d1: spot, d2: spot},
                   bhavs={d1: bhav})  # d2 missing
    out = materialize_iv_history("RELIANCE", d1, d2)
    assert len(out) == 1
    assert out["date"].iloc[0] == pd.Timestamp(d1)


def test_materialize_none_to_nan_at_cache_boundary(monkeypatch, tmp_path):
    """Reviewer's deferred grill from c79e1ce. One-expiry day →
    front-month succeeds but CMI series can't be computed (need ≥
    2 expiries). Parquet must carry NaN, NOT some sentinel like
    None or -1.0. Read-back via parquet must round-trip the NaN."""
    _redirect_cache(monkeypatch, tmp_path)
    trade_date = date(2024, 5, 1)
    spot = 1000.0
    bhav = _synthetic_chain(
        "RELIANCE", trade_date,
        [(date(2024, 5, 30), 0.25)],  # ONE expiry only
        spot=spot,
    )
    _patch_loaders(monkeypatch,
                   days=[trade_date],
                   spots={trade_date: spot},
                   bhavs={trade_date: bhav})
    out = materialize_iv_history("RELIANCE", trade_date, trade_date)
    assert len(out) == 1
    assert out["iv_front"].iloc[0] == pytest.approx(0.25, abs=1e-4)
    assert np.isnan(out["iv_cmi30_raw"].iloc[0])
    assert np.isnan(out["iv_cmi30_excl7"].iloc[0])

    # And round-trip through parquet.
    loaded = load_iv_history("RELIANCE")
    assert np.isnan(loaded["iv_cmi30_raw"].iloc[0])
    assert np.isnan(loaded["iv_cmi30_excl7"].iloc[0])


def test_materialize_excl7_methodology_default_drops_near_expiry_day(
    monkeypatch, tmp_path,
):
    """LOAD-BEARING for the operator-locked methodology default.
    On a day with one near (DTE=3) + one far (DTE=40) expiry:
      - iv_cmi30_raw      = interpolated between the two (defined)
      - iv_cmi30_excl7    = NaN (DTE=3 dropped → only 1 survivor)
    This is the empirical artifact the user locked excl7 for."""
    _redirect_cache(monkeypatch, tmp_path)
    trade_date = date(2024, 5, 1)
    spot = 1000.0
    near_expiry = trade_date.replace(day=4)   # DTE=3
    far_expiry = date(2024, 6, 10)            # DTE=40
    bhav = _synthetic_chain(
        "RELIANCE", trade_date,
        [(near_expiry, 0.50), (far_expiry, 0.20)],
        spot=spot,
    )
    _patch_loaders(monkeypatch,
                   days=[trade_date],
                   spots={trade_date: spot},
                   bhavs={trade_date: bhav})
    out = materialize_iv_history("RELIANCE", trade_date, trade_date)
    assert not np.isnan(out["iv_cmi30_raw"].iloc[0])
    assert np.isnan(out["iv_cmi30_excl7"].iloc[0])


def test_materialize_empty_window_writes_schema_only_parquet(monkeypatch, tmp_path):
    """``trading_days`` returns [] → empty schema-shaped parquet
    written. Downstream code reads it without special-casing."""
    _redirect_cache(monkeypatch, tmp_path)
    _patch_loaders(monkeypatch, days=[], spots={}, bhavs={})
    out = materialize_iv_history("RELIANCE", date(2099, 1, 1), date(2099, 1, 2))
    assert len(out) == 0
    assert list(out.columns) == list(IV_HISTORY_COLUMNS)
    loaded = load_iv_history("RELIANCE")
    assert len(loaded) == 0
    assert list(loaded.columns) == list(IV_HISTORY_COLUMNS)


def test_materialize_rejects_inverted_window():
    """from > to is a programmer error — fail loudly."""
    with pytest.raises(ValueError, match="from_date.*to_date"):
        materialize_iv_history(
            "RELIANCE", date(2024, 5, 2), date(2024, 5, 1),
        )


def test_materialize_offline_cache_miss_silently_skips_day(monkeypatch, tmp_path):
    """``offline=True`` + spot cache miss → skip day, don't raise.
    The materializer is a batch tool; a single missing day
    shouldn't abort the run."""
    _redirect_cache(monkeypatch, tmp_path)
    from src.data.errors import OfflineCacheMiss
    d1 = date(2024, 5, 1)
    spot = 1000.0
    bhav = _synthetic_chain(
        "RELIANCE", d1,
        [(date(2024, 5, 30), 0.25), (date(2024, 6, 27), 0.25)],
        spot=spot,
    )

    def fake_trading_days(from_date, to_date, *, today_fn=None, offline=False):
        return [d1]

    def fake_load_spot(symbol, from_date, to_date, *,
                       force_refresh=False, today_fn=None, offline=False):
        raise OfflineCacheMiss(f"spot {from_date}")

    def fake_load_bhavcopy(trade_date, *, force_refresh=False, offline=False):
        return bhav

    monkeypatch.setattr(iv_materializer, "trading_days", fake_trading_days)
    monkeypatch.setattr(iv_materializer, "load_spot", fake_load_spot)
    monkeypatch.setattr(iv_materializer, "load_bhavcopy_fo", fake_load_bhavcopy)

    out = materialize_iv_history("RELIANCE", d1, d1, offline=True)
    assert len(out) == 0


def test_load_iv_history_raises_when_cache_missing(monkeypatch, tmp_path):
    """Downstream analytics should see a hard error, not silent empty,
    when asked for a symbol that hasn't been materialized."""
    _redirect_cache(monkeypatch, tmp_path)
    with pytest.raises(FileNotFoundError):
        load_iv_history("UNKNOWNSYM")


# ============================================================
# Constants — pin the operator-validated values
# ============================================================

def test_constants_match_operator_locked_values():
    """PORTFOLIO_MEMOIR.md §21.3 + notebook 3625f3e. If any of these
    change without a memoir revision, that's a load-bearing drift."""
    assert RISK_FREE_RATE == 0.065
    assert TARGET_DTE == 30
    assert NEAR_EXPIRY_EXCLUSION_DAYS == 7
