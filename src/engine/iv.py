"""Forward-based Black-76 implied volatility inversion.

PORTFOLIO_MEMOIR.md §21.4 F2 + F3 (REVISED 2026-06-04). Departs from
naive spot-based Black-Scholes in two ways:

  1. **Forward-based pricing (Black-76).** Treats the underlying as
     its risk-neutral forward ``F``, not as ``spot``. The two are
     equal under Black-Scholes only when there are no dividends, no
     borrow costs, and no carry — assumptions that DON'T hold for
     Indian single-name equities (dividends are real, borrow costs
     for shorts are non-zero, carry varies). Working in forward space
     absorbs all of that automatically.

  2. **Forward extracted via put-call parity at the ATM strike.**
     Rather than estimate ``F`` from spot + interest + dividend
     forecasts (which compounds three uncertainties), read it
     directly off the options market:

         F = K_atm + (C_atm − P_atm) · e^(r·T)

     The option market is already pricing the forward; we just
     decode it.

Numerical inversion uses ``scipy.optimize.brentq`` on
``call_price(σ) − market_price = 0`` over a bracketed σ range of
[1e-4, 5.0] (i.e., 0.01% to 500% annualized vol). Bracket is wide
enough that any Indian-single-name traded option lands inside it;
narrower would risk false ``None`` returns on tail cases.

Convention for T (time to expiry): **calendar-days / 365**. Per
9690656 (memoir revision) — option pricing models assume
continuous-time calendar-day-anchored ``T``, NOT trading-day
counts. The ``vol estimator`` separately uses ``√252`` for
realized-vol annualization (that's a stats convention on returns;
it's a different number).

Public API:

  ``bs76_call_price(F, K, T, sigma, r) -> float``
  ``bs76_put_price(F, K, T, sigma, r) -> float``
      Black-76 European call / put prices, with the standard zero-T
      and zero-σ degenerate-input branches.

  ``extract_forward(call_px, put_px, K, T, r) -> float``
      Put-call parity forward extraction. Trusts that the call and
      put correspond to the same strike + expiry; caller's
      responsibility to enforce that pairing.

  ``implied_vol_call(market_px, F, K, T, r) -> float | None``
  ``implied_vol_put(market_px, F, K, T, r) -> float | None``
      Brent-root IV inversion on the call or put leg. Returns
      ``None`` (NOT NaN) on every degenerate input: invalid T or
      negative inputs, market price below intrinsic, market price
      at or above the no-arbitrage upper bound, brentq failing to
      converge. Caller checks ``is not None``.

      Returning ``None`` rather than NaN is a load-bearing API
      choice: NaN propagates silently through ``mean``, ``std``, and
      most numpy reductions, hiding the "I couldn't invert this"
      signal. ``None`` forces the caller to handle it explicitly.
"""
from __future__ import annotations

import math
import warnings

from scipy.optimize import brentq
from scipy.stats import norm


# Bracket for brentq IV search. 0.01% lower lets us catch obviously
# low-vol mispricings (numerical artifacts only); 500% upper covers
# any blow-up vol seen in Indian single-name options historically.
_IV_BRACKET_LOW = 1e-4
_IV_BRACKET_HIGH = 5.0

# brentq tolerance + iteration cap. 1e-6 is well below the precision
# we care about (we report IV to 4 decimals downstream); 64 iterations
# is far more than brentq ever needs on the bracket above — it's a
# safety cap, not a tuning knob.
_BRENTQ_XTOL = 1e-6
_BRENTQ_MAXITER = 64


def bs76_call_price(
    F: float, K: float, T: float, sigma: float, r: float,
) -> float:
    """Black-76 European call price on a forward ``F`` at strike ``K``,
    expiring in ``T`` years, with annualized volatility ``sigma`` and
    risk-free rate ``r``.

    Degenerate-input branches (T or sigma at or below zero) return
    the discounted intrinsic value — what an expired or zero-vol
    option is worth.
    """
    if T <= 0.0 or sigma <= 0.0:
        return max(0.0, math.exp(-r * T) * (F - K))
    sqrtT = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return float(math.exp(-r * T) * (F * norm.cdf(d1) - K * norm.cdf(d2)))


def bs76_put_price(
    F: float, K: float, T: float, sigma: float, r: float,
) -> float:
    """Black-76 European put price. Mirror of ``bs76_call_price`` with
    the standard put symmetry; same degenerate-input branches."""
    if T <= 0.0 or sigma <= 0.0:
        return max(0.0, math.exp(-r * T) * (K - F))
    sqrtT = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * sqrtT)
    d2 = d1 - sigma * sqrtT
    return float(
        math.exp(-r * T) * (K * norm.cdf(-d2) - F * norm.cdf(-d1))
    )


def extract_forward(
    call_px: float, put_px: float, K: float, T: float, r: float,
) -> float:
    """Synthetic forward via put-call parity at strike ``K``::

        F = K + (C − P) · e^{r·T}

    The option market is pricing the forward — we just decode it.
    Bypasses the need to estimate dividend yield + carry separately.
    Caller must ensure ``call_px`` and ``put_px`` correspond to the
    same strike + expiry on the same trade day.
    """
    return float(K + (call_px - put_px) * math.exp(r * T))


def _solve_iv(
    market_px: float, F: float, K: float, T: float, r: float,
    *, side: str,
) -> float | None:
    """Shared brentq inversion path for call / put. Internal — callers
    use ``implied_vol_call`` / ``implied_vol_put``.

    Returns ``None`` on every degenerate / no-arbitrage condition;
    caller doesn't need to know which branch fired."""
    if T <= 0.0 or market_px <= 0.0 or F <= 0.0 or K <= 0.0:
        return None
    discount = math.exp(-r * T)
    # No-arbitrage bounds — different on each side.
    if side == "call":
        intrinsic = max(0.0, discount * (F - K))
        upper = discount * F
        price_fn = bs76_call_price
    else:
        intrinsic = max(0.0, discount * (K - F))
        upper = discount * K
        price_fn = bs76_put_price
    if market_px <= intrinsic + 1e-8:
        # No time value beyond intrinsic — IV is undefined (0?
        # infinity? depends on which side you take). Loud-fail by
        # returning None so the caller treats this contract as
        # unbacktestable, NOT 0.
        return None
    if market_px >= upper - 1e-8:
        # Above the no-arbitrage cap — input data is corrupt or the
        # contract is mispriced for a reason BS can't capture.
        return None

    def err(sigma: float) -> float:
        return price_fn(F, K, T, sigma, r) - market_px

    # Brentq's RuntimeWarning on degenerate-bracket cases is noisy
    # and not actionable — we already gate via the upper/intrinsic
    # bounds above, so anything brentq objects to here is genuinely
    # unsolvable. Silence narrowly.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return float(brentq(
                err,
                _IV_BRACKET_LOW, _IV_BRACKET_HIGH,
                xtol=_BRENTQ_XTOL, maxiter=_BRENTQ_MAXITER,
            ))
    except (ValueError, RuntimeError):
        return None


def implied_vol_call(
    market_px: float, F: float, K: float, T: float, r: float,
) -> float | None:
    """Invert ``bs76_call_price(F, K, T, σ, r) = market_px`` for σ.

    Returns the implied vol in [0, ∞), or ``None`` when:
      - ``T <= 0`` (already expired or invalid).
      - ``market_px`` or ``F`` or ``K`` <= 0 (degenerate input).
      - ``market_px`` <= discounted intrinsic ``e^{-r·T}·(F−K)``
        (no time value — IV is undefined).
      - ``market_px`` >= discounted upper bound ``e^{-r·T}·F``
        (above the no-arbitrage cap — corrupt input).
      - brentq fails to converge within 64 iterations on [1e-4, 5.0].
    """
    return _solve_iv(market_px, F, K, T, r, side="call")


def implied_vol_put(
    market_px: float, F: float, K: float, T: float, r: float,
) -> float | None:
    """Invert ``bs76_put_price(F, K, T, σ, r) = market_px`` for σ.

    Same ``None``-on-degenerate-input policy as
    ``implied_vol_call``; bounds checked against put-side intrinsic
    and ``e^{-r·T}·K`` upper.
    """
    return _solve_iv(market_px, F, K, T, r, side="put")
