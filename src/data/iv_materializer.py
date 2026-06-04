"""Per-symbol 30D constant-maturity ATM IV history materializer.

PORTFOLIO_MEMOIR.md §21.3 C2-C3 (operator-locked methodology) +
§21.4 F2-F4. Composes ``engine.iv`` (Black-76 pricing + parity
forward + brentq IV inversion) over the cached bhavcopies and spot
prints to produce a per-symbol parquet:

    data/cache/iv/{SYMBOL}.parquet

The output is the input to F5 (IVP via trailing-252-TD percentile
rank-of-ranks) and F8 (regime-gated entry filter).

Pipeline per trading day ``d``:

    1. Load the F&O bhavcopy for ``d`` (already SPECS §2.4 frame).
    2. Load spot CLOSE for ``d`` (single-day fast path).
    3. For each (symbol, expiry) with DTE > 0:
         a. Restrict to ATM strike — the listed strike closest to
            spot with BOTH a non-zero CE close AND non-zero PE close
            (option-side validity filter; otherwise parity fails).
         b. Extract forward via put-call parity at K_atm.
         c. Invert Black-76 on the call leg to get σ.
            (Per-expiry IV; call leg by convention. Parity guarantees
            put leg would give the same σ.)
    4. Build the three IV series:
         - ``iv_front``           = first by DTE.
         - ``iv_cmi30_raw``       = 30D CMI, no DTE filter (Series B).
         - ``iv_cmi30_excl7``     = 30D CMI, DTE ≥ 7 (Series C; the
                                    operator-validated primary).

Series C is the methodology default per the
``scripts/research_iv_visualization.ipynb`` empirical study:
front-month IV (Series A, red line in the plots) crashes near
expiry due to theta panic, pin risk and the breakdown of the
log-normal assumption — excluding DTE < 7 eliminates that
artifact while still keeping enough expiries for the variance-
space interpolation. Series A + B are persisted alongside as
diagnostics so a future analyst can compare without re-running.

CMI variance-space interpolation (cell 13 of the prototype
notebook): pick the near-bracket expiry (DTE ≤ 30) and far-
bracket expiry (DTE > 30), linearly interpolate VARIANCE
(σ²·T-style) at T = 30, return ``√variance_30D``. When both
expiries land on the same side of 30 (only happens deep in the
tail of the option chain), use the two closest-to-30 expiries
and orient them by DTE. Two expiries are required minimum;
fewer → ``None`` (silent skip → NaN at cache boundary).

None → NaN at the cache boundary: ``engine.iv`` returns ``None``
on every degenerate / no-arbitrage input. The materializer
converts those to ``np.nan`` when writing the parquet — a
load-bearing translation so downstream analytics (IVP, RV, regime
gate) see a uniform-typed float column with NaN gaps that pandas
``rolling`` etc. handle natively.

Public API:

  ``materialize_iv_history(symbol, from_date, to_date, *, ...)
        -> pd.DataFrame``
      Build (or rebuild) the per-symbol IV history parquet for the
      given window and return it. Always recomputes — caller can
      rely on the output reflecting the latest bhavcopies + spot.

  ``load_iv_history(symbol) -> pd.DataFrame``
      Read the cached parquet, raising ``FileNotFoundError`` if
      not yet built. Cheap; for hot-path analytics consumers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable

import numpy as np
import pandas as pd

from src.data import cache
from src.data.bhavcopy_fo_loader import load_bhavcopy_fo
from src.data.errors import OfflineCacheMiss
from src.data.spot_loader import load_spot
from src.data.trading_calendar import trading_days
from src.engine.iv import (
    extract_forward,
    implied_vol_call,
)

logger = logging.getLogger(__name__)

# Indian sovereign yield proxy, locked at notebook constant for
# parity with the operator-validated research. The IV inversion is
# only weakly sensitive to r (Δσ ≈ 0.1% per 100bp drift on a 30-DTE
# ATM); a future revisit to a per-date 10Y yield is a noise-level
# improvement, not a correctness one.
RISK_FREE_RATE = 0.065

# 30 calendar days — the standard "1M" expiry distance for the
# constant-maturity index. Bracketing expiries on each side of this
# are interpolated in variance space.
TARGET_DTE = 30

# Operator-locked exclusion threshold (PORTFOLIO_MEMOIR.md §21.3 C2;
# notebook 3625f3e empirical study; user's 2026-05-31 lock-in).
# Front-month options with DTE < 7 distort IV via theta panic, pin
# risk, and Black-Scholes log-normal breakdown — exclude when
# building Series C (the methodology default).
NEAR_EXPIRY_EXCLUSION_DAYS = 7

# Canonical schema for ``data/cache/iv/{SYMBOL}.parquet``.
# Pinning here so a future contributor adding a column has to
# update one tuple, not seven assertions.
IV_HISTORY_COLUMNS: tuple[str, ...] = (
    "date",
    "iv_front",
    "iv_cmi30_raw",
    "iv_cmi30_excl7",
    "atm_strike_front",
    "n_expiries_used",
)


@dataclass(frozen=True)
class ExpiryIV:
    """ATM IV for one expiry on one trade date.

    Only ever constructed for ``iv is not None`` cases — the
    materializer filters degenerate inversions upstream. The DTE
    field is a plain ``int`` of calendar days; ``T`` is recomputed
    downstream as ``dte / 365.0`` per the engine convention.
    """
    expiry: date
    dte: int
    atm_strike: float
    iv: float


def _atm_strike(chain: pd.DataFrame, spot: float) -> float | None:
    """Pick the listed strike closest to ``spot`` with BOTH a
    non-zero CE close AND non-zero PE close — the "option-side
    validity" filter from cell 11 of the prototype notebook.

    Both legs must be present so parity can extract the forward.
    A CE-only or PE-only strike is unusable for the parity-based
    flow. A zero-close print on either leg means a stale or no-
    trade contract — also unusable.

    Returns ``None`` when no strike satisfies both gates.
    """
    ce = chain[chain["option_type"] == "CE"].set_index("strike")["close"]
    pe = chain[chain["option_type"] == "PE"].set_index("strike")["close"]
    common = ce.index.intersection(pe.index)
    if len(common) == 0:
        return None
    valid = [k for k in common if ce[k] > 0 and pe[k] > 0]
    if not valid:
        return None
    arr = np.asarray(valid, dtype=float)
    return float(arr[np.argmin(np.abs(arr - spot))])


def _iv_per_expiry(
    symbol: str,
    trade_date: date,
    spot: float,
    bhav: pd.DataFrame,
) -> list[ExpiryIV]:
    """Compute ATM IV for every available expiry of ``symbol`` on
    ``trade_date`` from the day's bhavcopy.

    Drops any expiry with ``DTE ≤ 0`` (already expired or same-day),
    no ATM strike satisfying the both-legs-non-zero gate, or a
    failed IV inversion (engine returns ``None``). Output sorted
    ascending by DTE — caller can take ``[0]`` for front-month.
    """
    if bhav.empty or "symbol" not in bhav.columns:
        return []
    sym_chain = bhav[bhav["symbol"] == symbol]
    if sym_chain.empty:
        return []
    out: list[ExpiryIV] = []
    for expiry_ts, chain in sym_chain.groupby("expiry"):
        expiry_date = pd.Timestamp(expiry_ts).date()
        dte = (expiry_date - trade_date).days
        if dte <= 0:
            continue
        T = dte / 365.0
        k_atm = _atm_strike(chain, spot)
        if k_atm is None:
            continue
        ce_row = chain[(chain["option_type"] == "CE") & (chain["strike"] == k_atm)]
        pe_row = chain[(chain["option_type"] == "PE") & (chain["strike"] == k_atm)]
        if ce_row.empty or pe_row.empty:
            continue
        c = float(ce_row["close"].iloc[0])
        p = float(pe_row["close"].iloc[0])
        F = extract_forward(c, p, k_atm, T, RISK_FREE_RATE)
        iv = implied_vol_call(c, F, k_atm, T, RISK_FREE_RATE)
        if iv is None:
            continue
        out.append(ExpiryIV(
            expiry=expiry_date, dte=dte, atm_strike=k_atm, iv=iv,
        ))
    out.sort(key=lambda e: e.dte)
    return out


def _front_month_iv(per_expiry: list[ExpiryIV]) -> float | None:
    """First-by-DTE IV — Series A (front-month). Returns ``None``
    on empty input."""
    if not per_expiry:
        return None
    return per_expiry[0].iv


def _constant_maturity_30d(
    per_expiry: list[ExpiryIV], *, exclude_lt_dte: int = 0,
) -> float | None:
    """30-calendar-day constant-maturity IV via variance-space
    linear interpolation between bracketing expiries.

    Algorithm (cell 13 of the prototype notebook):

      1. Apply DTE floor (``exclude_lt_dte``). Pass 0 for Series B
         (raw); pass ``NEAR_EXPIRY_EXCLUSION_DAYS`` for Series C.
      2. Need ≥ 2 survivors. Fewer → ``None``.
      3. If at least one DTE ≤ 30 AND one DTE > 30 → bracket the
         target: near = closest-to-30 from below, far = closest-
         to-30 from above.
      4. Otherwise (all on one side) → take the two closest-to-30
         and orient by DTE so near.dte ≤ far.dte.
      5. Variance-space lerp:

             var_30 = var_near · (far.dte − 30) / span
                    + var_far  · (30 − near.dte) / span
             σ_30   = √max(var_30, 0)

         where ``span = far.dte − near.dte``. The ``max(0)`` clamp
         protects against a degenerate extrapolation step on the
         all-one-side branch — a true negative variance would
         indicate the surface is anchored so far from 30D that the
         linear extrapolation has crossed zero, which is more an
         artifact of using a 2-point linear fit than a real
         signal. Clamp to 0 and let downstream NaN handling do
         its thing.

      6. Edge case: span == 0 (two expiries with the same DTE — a
         deeply degenerate option chain) → RMS combine.
    """
    survivors = [e for e in per_expiry if e.dte >= exclude_lt_dte]
    if len(survivors) < 2:
        return None
    near = [e for e in survivors if e.dte <= TARGET_DTE]
    far = [e for e in survivors if e.dte > TARGET_DTE]
    if near and far:
        e_near = max(near, key=lambda e: e.dte)
        e_far = min(far, key=lambda e: e.dte)
    else:
        sorted_by_dist = sorted(survivors, key=lambda e: abs(e.dte - TARGET_DTE))
        e_near, e_far = sorted_by_dist[0], sorted_by_dist[1]
        if e_near.dte > e_far.dte:
            e_near, e_far = e_far, e_near
    if e_near.dte == e_far.dte:
        # Two expiries on the same DTE — RMS combine, no
        # interpolation possible. Almost never happens in
        # practice but the all-one-side branch could occasionally
        # land on ties.
        return float(np.sqrt(0.5 * (e_near.iv ** 2 + e_far.iv ** 2)))
    var_near = e_near.iv ** 2
    var_far = e_far.iv ** 2
    span = e_far.dte - e_near.dte
    var_30 = (
        var_near * (e_far.dte - TARGET_DTE) / span
        + var_far * (TARGET_DTE - e_near.dte) / span
    )
    return float(np.sqrt(max(var_30, 0.0)))


def _compute_iv_for_day(
    symbol: str,
    trade_date: date,
    spot: float,
    bhav: pd.DataFrame,
) -> dict | None:
    """Single-day per-symbol IV record. Returns ``None`` when no
    expiry survives the per-expiry inversion (so the caller can
    skip the day cleanly); returns a dict with NaN-where-degenerate
    when at least one expiry survives but a downstream series
    can't be computed (e.g., front-month available but only 1
    survivor → CMI series both NaN)."""
    per_exp = _iv_per_expiry(symbol, trade_date, spot, bhav)
    if not per_exp:
        return None
    iv_front = _front_month_iv(per_exp)
    iv_cmi30_raw = _constant_maturity_30d(per_exp, exclude_lt_dte=0)
    iv_cmi30_excl7 = _constant_maturity_30d(
        per_exp, exclude_lt_dte=NEAR_EXPIRY_EXCLUSION_DAYS,
    )
    return {
        "date": trade_date,
        # None → NaN translation at the cache boundary so downstream
        # rolling / pct-rank reductions see a uniform float column.
        "iv_front": iv_front if iv_front is not None else np.nan,
        "iv_cmi30_raw": iv_cmi30_raw if iv_cmi30_raw is not None else np.nan,
        "iv_cmi30_excl7": iv_cmi30_excl7 if iv_cmi30_excl7 is not None else np.nan,
        "atm_strike_front": per_exp[0].atm_strike,
        "n_expiries_used": len(per_exp),
    }


def _empty_frame() -> pd.DataFrame:
    """Empty frame with the canonical schema — returned by
    ``materialize_iv_history`` when the window has zero usable days
    (e.g., bhavcopies all missing under offline mode). Schema-
    consistent so downstream code doesn't have to special-case."""
    return pd.DataFrame({
        "date": pd.Series(dtype="datetime64[us]"),
        "iv_front": pd.Series(dtype="float64"),
        "iv_cmi30_raw": pd.Series(dtype="float64"),
        "iv_cmi30_excl7": pd.Series(dtype="float64"),
        "atm_strike_front": pd.Series(dtype="float64"),
        "n_expiries_used": pd.Series(dtype="int64"),
    })


def materialize_iv_history(
    symbol: str,
    from_date: date,
    to_date: date,
    *,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """Build the per-symbol IV history parquet for the window
    ``[from_date, to_date]`` inclusive and return the resulting
    DataFrame. Always recomputes — does NOT incrementally append
    to an existing cache.

    The function always writes ``data/cache/iv/{symbol}.parquet``
    (overwriting any prior content) so that subsequent
    ``load_iv_history`` calls see the latest window. ``force_refresh``
    is accepted for API symmetry with the other loaders but is a
    no-op under the current "always recompute" policy; reserved for
    a future incremental-append refactor.

    On every trading day in the window:

      - Load the F&O bhavcopy (cache-or-fetch via
        ``bhavcopy_fo_loader``; respects ``offline``).
      - Load spot CLOSE (cache-or-fetch via ``spot_loader``).
      - Compute the per-expiry IV → front + raw CMI + excl-DTE<7 CMI.

    A day is silently skipped when the bhavcopy is missing under
    offline mode, the spot is missing, or no expiry survives. The
    resulting output has one row per day that produced a usable
    IV record — NOT one per trading day in the window. Downstream
    analytics handle the gaps via ``reindex`` against the trading
    calendar if needed.

    Returns the materialized DataFrame (also written to disk).
    Empty window → schema-shaped empty frame (see ``_empty_frame``).
    """
    del force_refresh  # reserved for future incremental policy.
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} > to_date {to_date}")

    days = trading_days(from_date, to_date, today_fn=today_fn, offline=offline)
    if not days:
        out = _empty_frame()
        cache.write(cache.iv_path(symbol), out, overwrite=True)
        return out

    rows: list[dict] = []
    for d in days:
        try:
            spot_df = load_spot(
                symbol, d, d, today_fn=today_fn, offline=offline,
            )
        except OfflineCacheMiss:
            logger.debug("iv_materializer: spot offline-miss %s %s", symbol, d)
            continue
        if spot_df.empty:
            continue
        try:
            bhav = load_bhavcopy_fo(d, offline=offline)
        except OfflineCacheMiss:
            logger.debug("iv_materializer: bhavcopy offline-miss %s", d)
            continue
        if bhav is None or bhav.empty:
            continue
        spot = float(spot_df["close"].iloc[0])
        rec = _compute_iv_for_day(symbol, d, spot, bhav)
        if rec is None:
            continue
        rows.append(rec)

    if not rows:
        out = _empty_frame()
    else:
        out = pd.DataFrame(rows)[list(IV_HISTORY_COLUMNS)]
        out["date"] = pd.to_datetime(out["date"]).astype("datetime64[us]")
        out["iv_front"] = out["iv_front"].astype("float64")
        out["iv_cmi30_raw"] = out["iv_cmi30_raw"].astype("float64")
        out["iv_cmi30_excl7"] = out["iv_cmi30_excl7"].astype("float64")
        out["atm_strike_front"] = out["atm_strike_front"].astype("float64")
        out["n_expiries_used"] = out["n_expiries_used"].astype("int64")
        out = out.sort_values("date").reset_index(drop=True)

    cache.write(cache.iv_path(symbol), out, overwrite=True)
    return out


def load_iv_history(symbol: str) -> pd.DataFrame:
    """Read the cached per-symbol IV history parquet.

    Raises ``FileNotFoundError`` (the standard ``cache.read`` error
    behavior) if the cache hasn't been built yet for ``symbol``.
    Downstream analytics (IVP, RV, regime gate) consume this as
    their primary input — they should treat a missing cache as a
    "materialize first" error, not a silent zero-row frame.
    """
    return cache.read(cache.iv_path(symbol))
