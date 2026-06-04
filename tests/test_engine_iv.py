"""Tests for src.engine.iv — forward-based Black-76 IV inversion.

All tests are pure-arithmetic; no I/O, no monkeypatching. The
canonical hand-check fixture is an ATM 30-day option priced under
``σ = 0.20`` — the most common single-name short-vol target.
"""
from __future__ import annotations

import math

import pytest

from src.engine.iv import (
    bs76_call_price,
    bs76_put_price,
    extract_forward,
    implied_vol_call,
    implied_vol_put,
)


# ============================================================
# Black-76 pricing kernel — known values + degenerate inputs
# ============================================================

def test_bs76_call_price_atm_30d_20vol_pins_a_known_value():
    """Hand-check: F=K=100, T=30/365, σ=0.20, r=0.065.
    Closed-form ATM call ≈ 2.286. Pin this so a future numerical
    refactor of d1/d2 can't silently drift."""
    F, K = 100.0, 100.0
    T = 30.0 / 365.0
    sigma = 0.20
    r = 0.065
    px = bs76_call_price(F, K, T, sigma, r)
    # Hand-derived: discount=exp(-0.065*30/365)≈0.99467;
    # d1 = (0 + 0.5*0.04*T) / (0.2*sqrtT) ≈ 0.02867; d2 ≈ -0.02867;
    # N(d1)≈0.51144, N(d2)≈0.48856; call ≈ 0.99467 * (100*N(d1)-100*N(d2))
    #     ≈ 0.99467 * 2.288 ≈ 2.276.
    assert px == pytest.approx(2.276, abs=0.01)


def test_bs76_put_call_parity_holds():
    """LOAD-BEARING: C − P = e^{−r·T} · (F − K) under Black-76.
    Any d1/d2 typo would break parity loud; pin both sides."""
    F, K, T, sigma, r = 1050.0, 1000.0, 0.5, 0.30, 0.065
    c = bs76_call_price(F, K, T, sigma, r)
    p = bs76_put_price(F, K, T, sigma, r)
    parity_lhs = c - p
    parity_rhs = math.exp(-r * T) * (F - K)
    assert parity_lhs == pytest.approx(parity_rhs, abs=1e-9)


def test_bs76_call_price_at_zero_time_returns_intrinsic():
    """T = 0 → discounted intrinsic. F=110, K=100 ITM call → ₹10
    (discounting collapses at T=0)."""
    assert bs76_call_price(110.0, 100.0, 0.0, 0.20, 0.065) == 10.0


def test_bs76_call_price_at_zero_vol_returns_intrinsic():
    """σ = 0 → discounted intrinsic. ITM call ₹10 → discounted to
    ~₹9.95 at r=0.065, T=30/365."""
    px = bs76_call_price(110.0, 100.0, 30.0 / 365.0, 0.0, 0.065)
    expected = math.exp(-0.065 * 30 / 365) * 10.0
    assert px == pytest.approx(expected, abs=1e-9)


def test_bs76_put_price_at_zero_time_returns_intrinsic():
    """OTM put at expiry → 0."""
    assert bs76_put_price(110.0, 100.0, 0.0, 0.20, 0.065) == 0.0


# ============================================================
# extract_forward — put-call parity
# ============================================================

def test_extract_forward_recovers_synthetic_forward():
    """Hand-check: K=100, T=30/365, r=0.065; pick F=101.
    Then C and P from BS76, parity recovers exactly F."""
    K = 100.0
    T = 30.0 / 365.0
    r = 0.065
    F = 101.0
    sigma = 0.25
    c = bs76_call_price(F, K, T, sigma, r)
    p = bs76_put_price(F, K, T, sigma, r)
    F_recovered = extract_forward(c, p, K, T, r)
    assert F_recovered == pytest.approx(F, abs=1e-9)


def test_extract_forward_handles_F_equals_K():
    """ATM case: F=K means C = P (under Black-76 with no skew), so
    F = K + 0·e^{rT} = K. Trivial but pin it so a sign flip can't
    sneak in."""
    K = 100.0
    T = 30.0 / 365.0
    r = 0.065
    F = K
    sigma = 0.20
    c = bs76_call_price(F, K, T, sigma, r)
    p = bs76_put_price(F, K, T, sigma, r)
    F_recovered = extract_forward(c, p, K, T, r)
    assert F_recovered == pytest.approx(K, abs=1e-9)


# ============================================================
# implied_vol_call — round-trip + edge cases
# ============================================================

def test_implied_vol_call_round_trip_recovers_input_sigma():
    """LOAD-BEARING. Price under known σ, invert, recover.
    Range: σ ∈ {0.10, 0.20, 0.30, 0.50, 1.00} for an ATM 60-DTE call."""
    F, K = 100.0, 100.0
    T = 60.0 / 365.0
    r = 0.065
    for sigma in (0.10, 0.20, 0.30, 0.50, 1.00):
        px = bs76_call_price(F, K, T, sigma, r)
        recovered = implied_vol_call(px, F, K, T, r)
        assert recovered is not None
        assert recovered == pytest.approx(sigma, abs=1e-4)


def test_implied_vol_call_otm_round_trip():
    """5% OTM call, 30D, σ=0.25 → round-trip should be exact."""
    F, K = 100.0, 105.0
    T = 30.0 / 365.0
    r = 0.065
    sigma = 0.25
    px = bs76_call_price(F, K, T, sigma, r)
    recovered = implied_vol_call(px, F, K, T, r)
    assert recovered is not None
    assert recovered == pytest.approx(sigma, abs=1e-4)


def test_implied_vol_call_itm_round_trip():
    """5% ITM call, 30D, σ=0.20 → round-trip should be exact."""
    F, K = 105.0, 100.0
    T = 30.0 / 365.0
    r = 0.065
    sigma = 0.20
    px = bs76_call_price(F, K, T, sigma, r)
    recovered = implied_vol_call(px, F, K, T, r)
    assert recovered is not None
    assert recovered == pytest.approx(sigma, abs=1e-4)


def test_implied_vol_call_returns_none_at_zero_time():
    """T = 0 → IV undefined."""
    assert implied_vol_call(market_px=5.0, F=100.0, K=100.0, T=0.0, r=0.065) is None
    assert implied_vol_call(market_px=5.0, F=100.0, K=100.0, T=-0.01, r=0.065) is None


def test_implied_vol_call_returns_none_at_zero_or_negative_price():
    """LOAD-BEARING: ``market_px <= 0`` returns None, NOT a numerical
    NaN that would silently pollute downstream means."""
    assert implied_vol_call(market_px=0.0, F=100.0, K=100.0, T=0.1, r=0.065) is None
    assert implied_vol_call(market_px=-1.0, F=100.0, K=100.0, T=0.1, r=0.065) is None


def test_implied_vol_call_returns_none_below_intrinsic():
    """Market quote below discounted intrinsic is arbitrage. F=110, K=100,
    intrinsic discounted ≈ 9.95. Quoting at ₹9.50 → None."""
    F, K = 110.0, 100.0
    T = 30.0 / 365.0
    r = 0.065
    assert implied_vol_call(market_px=9.50, F=F, K=K, T=T, r=r) is None


def test_implied_vol_call_returns_none_above_no_arbitrage_upper():
    """Call upper bound is ``e^{-r·T}·F``. Quoting at 1.05·F would
    violate arbitrage; reject as None."""
    F = 100.0
    K = 50.0
    T = 30.0 / 365.0
    r = 0.065
    upper = math.exp(-r * T) * F
    assert implied_vol_call(market_px=upper * 1.05, F=F, K=K, T=T, r=r) is None


def test_implied_vol_call_returns_none_on_negative_F_or_K():
    """Defensive: negative forward or strike should fail loud (well,
    None — which is the loud-fail signal in this API)."""
    assert implied_vol_call(market_px=5.0, F=-100.0, K=100.0, T=0.1, r=0.065) is None
    assert implied_vol_call(market_px=5.0, F=100.0, K=-100.0, T=0.1, r=0.065) is None


# ============================================================
# implied_vol_put — same shape, parity check
# ============================================================

def test_implied_vol_put_round_trip_recovers_input_sigma():
    """LOAD-BEARING: same as call-side but on the put. Should
    converge to the same σ since the underlying vol surface is
    one-sided in our model."""
    F, K = 100.0, 100.0
    T = 60.0 / 365.0
    r = 0.065
    for sigma in (0.10, 0.20, 0.30, 0.50, 1.00):
        px = bs76_put_price(F, K, T, sigma, r)
        recovered = implied_vol_put(px, F, K, T, r)
        assert recovered is not None
        assert recovered == pytest.approx(sigma, abs=1e-4)


def test_implied_vol_put_recovers_same_sigma_as_call_under_parity():
    """LOAD-BEARING: under Black-76, the call IV and put IV for the
    same (F, K, T, r) MUST match (parity makes the call and put
    prices implied by σ consistent). Verify on a single ATM case."""
    F, K = 100.0, 100.0
    T = 60.0 / 365.0
    r = 0.065
    sigma = 0.25
    c = bs76_call_price(F, K, T, sigma, r)
    p = bs76_put_price(F, K, T, sigma, r)
    iv_c = implied_vol_call(c, F, K, T, r)
    iv_p = implied_vol_put(p, F, K, T, r)
    assert iv_c is not None and iv_p is not None
    assert iv_c == pytest.approx(iv_p, abs=1e-4)
    assert iv_c == pytest.approx(sigma, abs=1e-4)


# ============================================================
# Composed flow: parity-extract forward → invert IV
# ============================================================

def test_full_flow_parity_forward_then_iv_inversion():
    """End-to-end: observed (C, P) at K → extract F via parity →
    invert call → recover the σ the prices were generated under.

    This is the kernel of the materializer's per-(symbol, date,
    expiry) IV computation. If this passes, the materializer is
    just plumbing on top."""
    K = 1000.0
    T = 30.0 / 365.0
    r = 0.065
    F_true = 1010.0  # forward 1% above strike
    sigma_true = 0.28
    c = bs76_call_price(F_true, K, T, sigma_true, r)
    p = bs76_put_price(F_true, K, T, sigma_true, r)
    F_extracted = extract_forward(c, p, K, T, r)
    assert F_extracted == pytest.approx(F_true, abs=1e-6)
    iv = implied_vol_call(c, F_extracted, K, T, r)
    assert iv is not None
    assert iv == pytest.approx(sigma_true, abs=1e-4)
