"""21-day annualized realized volatility (F7) + symbol-aware
convenience wrapper.

PORTFOLIO_MEMOIR.md §21.3 row C6 + §21.4 F7. The canonical
close-to-close annualized RV formula:

    log_returns = log(closes[1:] / closes[:-1])
    daily_std   = std(log_returns, ddof=1)         # sample std
    annual_vol  = daily_std × sqrt(252)

This module factors the F7 PURE MATH out of ``src.engine.vol`` —
the latter couples spot_loader I/O with the math under a 126-TD
default (its margin-estimation use case per SPECS §4a). For the
portfolio analytics layer (regime gate v1 proxy + IVP-of-RV
diagnostics) we need:

  1. A pure function on a close-price array — testable on synthetic
     paths, no spot cache dependency.
  2. A symbol-aware convenience with the F7 default lookback of
     21 trading days (memoir-pinned, NOT 126).

The two coexist with the existing ``engine.vol`` paths:

  - ``engine.vol.realized_vol(symbol, as_of, lookback_trading_days=126)``
    — Tier-B margin estimation (SPECS §4a). 126-TD default, returns
    0.0 on insufficient data (signals "missing" to the margin
    calibrator which clamps to a vol floor anyway).

  - ``analytics.realized_vol.realized_vol_from_closes(closes)``
    — F7 pure function. Returns ``np.nan`` on insufficient data so
    F8 (universe-mean) can filter cleanly.

  - ``analytics.realized_vol.compute_rv(symbol, as_of, window_td=21)``
    — F7 convenience. 21-TD default, returns NaN on insufficient
    data. The IVP-of-RV / regime-gate-v1 callers use this.

The existing ``analytics.regime.avg_single_name_realized_vol``
(F8 implementation) currently calls ``engine.vol.realized_vol`` +
filters ``rv == 0.0`` as "missing". That code stays untouched in
this commit (its 0.0-filter idiom is documented and load-bearing
for sub-quarter cold-cache periods); a future commit can migrate
it to the NaN-native ``compute_rv`` path once the upstream cache
state is more stable.

Public API:

  ``realized_vol_from_closes(closes, *, annualize=True, ddof=1,
                              trading_days_per_year=252,
                              min_obs=20) -> float``
      F7 pure-math kernel. Operates on a sequence of close prices
      (np.ndarray, pd.Series, or list). Returns annualized RV or
      ``np.nan`` on insufficient / degenerate input.

  ``compute_rv(symbol, as_of, *, window_td=21, today_fn, offline)
                -> float``
      Symbol-aware convenience: loads ``window_td + 1`` trading
      days of spot via spot_loader (the ``+1`` so we have
      ``window_td`` log returns), calls ``realized_vol_from_closes``.
      Returns NaN on cold cache or symbol-not-listed; raises
      ``OfflineCacheMiss`` only if the spot cache is genuinely
      missing under ``offline=True``.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date
from typing import Callable

import numpy as np
import pandas as pd

from src.data import spot_loader, trading_calendar
from src.data.errors import OfflineCacheMiss


# ============================================================
# Constants — memoir-pinned defaults
# ============================================================

# F7 lookback: 21 trading days → needs 22 close prints → 21 log
# returns. Memoir §21.4 F7 + §21.3 row C6 (regime gate v1 proxy).
RV_WINDOW_TD = 21

# Annualization factor: √252 (trading days per year) per F7. The
# `252` here is a TRADING-day count, distinct from the IV pricing
# convention's `365` calendar-day denominator — those are two
# different clocks running on two different quantities (annualization
# of a daily-returns series vs. continuous-time discounting). Don't
# conflate; the F2 + F7 memoir entries both call this out explicitly.
TRADING_DAYS_PER_YEAR = 252

# Minimum log-return observations to compute a stable RV. 20 matches
# the engine.vol convention (carried for cross-module consistency);
# < 20 obs returns NaN. F7 spec assumes ~21 log returns.
RV_MIN_OBS = 20


# ============================================================
# F7 — pure-math kernel
# ============================================================

def realized_vol_from_closes(
    closes: Sequence[float] | np.ndarray | pd.Series,
    *,
    annualize: bool = True,
    ddof: int = 1,
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
    min_obs: int = RV_MIN_OBS,
) -> float:
    """Annualized close-to-close log-return standard deviation.

    F7 in PORTFOLIO_MEMOIR.md §21.4:

        log_returns = log(closes[1:] / closes[:-1])
        daily_std   = std(log_returns, ddof=1)
        return daily_std × sqrt(252)

    Args:
        closes: sequence of close prices (≥ ``min_obs + 1`` to
            produce ``min_obs`` log returns). NaN entries are
            dropped; non-positive entries make the log step
            undefined and force a NaN return.
        annualize: if False, return daily-step std without the
            ``sqrt(trading_days_per_year)`` factor. Useful for
            sub-window aggregation diagnostics.
        ddof: degrees-of-freedom for ``np.std``. F7 specifies
            ``ddof=1`` (sample std) per memoir — small windows
            of ~21 observations make the population-vs-sample
            difference ~2.5%, non-negligible for downstream
            ranks. Pinned default.
        trading_days_per_year: annualization factor. Defaults
            to 252 per F7. Override for diagnostic purposes only.
        min_obs: minimum LOG-RETURN observations required (i.e.,
            ``len(closes) − 1`` after NaN-drop). Defaults to 20
            for cross-module consistency with engine.vol's
            insufficient-data threshold.

    Returns:
        Annualized RV (``float``) or ``np.nan`` when:
          - ``closes`` is None / empty, OR
          - fewer than ``min_obs + 1`` valid (non-NaN) prices, OR
          - any valid price is ≤ 0 (log undefined).

    NaN convention (load-bearing): F8 ("universe-mean RV") expects
    NaN as the "missing" sentinel so it can filter cleanly. The
    legacy ``engine.vol.realized_vol`` returns 0.0 instead — that's
    its margin-estimation contract, NOT a contradiction; the regime
    F8 path filters ``rv == 0.0`` explicitly to compensate. New
    callers should use this NaN-native function.
    """
    if closes is None:
        return float("nan")
    arr = np.asarray(closes, dtype=float).ravel()
    # Drop NaN entries — leaves a contiguous price series for
    # diff/log. (A NaN-bearing price-series WITHIN the window is
    # an oddity for daily-close data; this is defensive.)
    arr = arr[~np.isnan(arr)]
    if len(arr) < min_obs + 1:
        return float("nan")
    if (arr <= 0.0).any():
        # log of zero or negative is undefined; corrupt input.
        return float("nan")

    log_returns = np.diff(np.log(arr))
    daily_std = float(np.std(log_returns, ddof=ddof))
    if not annualize:
        return daily_std
    return daily_std * math.sqrt(trading_days_per_year)


# ============================================================
# Symbol-aware convenience — F7 + spot_loader
# ============================================================

def compute_rv(
    symbol: str,
    as_of: date,
    *,
    window_td: int = RV_WINDOW_TD,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> float:
    """21-day annualized RV for ``symbol`` ending at ``as_of``.

    Loads the trailing ``window_td + 1`` trading-day closes (so we
    get ``window_td`` log returns) and applies
    ``realized_vol_from_closes`` with the F7 defaults.

    The ``+ 1`` extra calendar-day on the start: ``offset_trading_days``
    is the canonical "step back N trading days" helper from
    ``trading_calendar`` — same trick used by ``engine.vol`` to land
    on a real trading day rather than a NSE holiday.

    Args:
        symbol: NSE ticker.
        as_of: trade date to compute RV for.
        window_td: trailing trading-day window. Defaults to 21
            (memoir F7).
        today_fn / offline: standard data-loader plumbing.

    Returns:
        Annualized RV in [0, ∞) or ``np.nan`` when:
          - the spot cache has fewer than ``window_td + 1`` rows
            for ``symbol`` in the lookback window, OR
          - the symbol is not in the cache (load_spot returns empty), OR
          - any close in the loaded window is ≤ 0 (corrupt cache).

    Raises ``OfflineCacheMiss`` only if the spot cache is genuinely
    absent under ``offline=True``; that's a hard error worth
    surfacing rather than masking as NaN.
    """
    if window_td <= 1:
        raise ValueError(f"window_td must be > 1, got {window_td}")

    # Step back window_td trading days from as_of to anchor the
    # lookback start on a real trading day.
    lookback_date = trading_calendar.offset_trading_days(
        as_of, window_td, today_fn=today_fn, offline=offline,
    )
    try:
        df = spot_loader.load_spot(
            symbol, lookback_date, as_of,
            today_fn=today_fn, offline=offline,
        )
    except OfflineCacheMiss:
        # Re-raise — caller asked for offline and the cache is
        # genuinely missing this symbol/range. That's a pipeline
        # gap, not a NaN-worthy "insufficient data" case.
        raise
    if df.empty:
        return float("nan")
    closes = df["close"].astype("float64").to_numpy()
    return realized_vol_from_closes(
        closes,
        annualize=True,
        ddof=1,
        trading_days_per_year=TRADING_DAYS_PER_YEAR,
        min_obs=RV_MIN_OBS,
    )
