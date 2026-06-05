"""Regime gate signal + percentile rank.

PORTFOLIO_MEMOIR.md §3 (regime gate design) and §21.4 formulas F7,
F8, F9. Pure-math kernel + two signal-loaders (v1 + v2).

The regime gate is one of three layers in the v1 risk framework
(memoir §3.7): universe-wide regime (THIS module), per-name IVP
(``analytics.ivp``), and per-name earnings (``analytics.earnings_filter``).

## Signal-source evolution (memoir §3.7)

v1 (built first): ``avg_single_name_realized_vol`` — universe-
average of per-symbol 21-TD annualized realized vol. Backward-
looking; the "ambient single-name turbulence" proxy. Available
from the spot cache alone; no separate fetch required.

v2 (Phase 9.6 this commit): ``load_india_vix_signal`` — NSE's
daily-published implied-vol index from NIFTY index options.
Forward-looking; the market's own 30-day vol forecast. Per memoir
§3.7: "India VIX IS the market-implied 30-day vol forecast. No
need to compute it from 50 stocks; it's a single number per day,
published since 2008."

``default_regime_signal`` is the canonical entry point — Phase
9.4's regime banner calls THIS, not the per-signal functions
directly. Currently routes to v2 (India VIX). On a cold cache
(no india_vix.parquet) callers can fall back to v1 by importing
``avg_single_name_realized_vol`` explicitly; this module doesn't
auto-fallback because silent fallback would mask "operator forgot
to prefetch India VIX" gaps.

## Why not bake v2's superiority in as a theorem (memoir §3.7)

Memoir documents periods (post-Mar-2020, post-Volmageddon Feb-2018
US analogues) where HIGH-VIX environments produced the BEST
short-vol returns. The market was paying you extra premium AFTER
the panic; realized vol came in LOWER than implied. The gate
would have made you sit out those cycles.

Net read: the gate trades "missed-good-cycles" for "avoided-bad-
cycles." The empirical test is whether the trade is net positive
on YOUR data. The Portfolio tab's sensitivity strip will answer
this directly. Default 75th for v1; let the operator scan
empirically. **Don't bake it in as a theorem.**

## Public API

  ``regime_percentile(signal_series, as_of, lookback_td=252) -> float``
      Trailing-window percentile rank of today's signal value vs its
      own history. Returns 0-100 or NaN on insufficient history.

  ``regime_state(signal_series, as_of, threshold_pct=75.0,
                  lookback_td=252) -> Literal["ON", "OFF"]``
      ON when the percentile is ``<= threshold_pct``; OFF otherwise.
      Default 75th percentile per PORTFOLIO_MEMOIR.md §3.1.

  ``avg_single_name_realized_vol(symbols, as_of, window_td=21,
                                  today_fn=date.today, offline=False)
                                  -> float``
      v1 SIGNAL — universe-average of per-symbol 21-TD annualized
      realized vol. v1 proxy when India VIX is unavailable (cold
      cache / pre-2008 backtest date).

  ``load_india_vix_signal(from_date, to_date, *,
                            today_fn=date.today, offline=False)
                            -> pd.Series``
      v2 SIGNAL — India VIX close series for the lookback window
      (PORTFOLIO_MEMOIR.md §3.7). Date-indexed pd.Series ready for
      ``regime_percentile`` / ``regime_state``.

  ``default_regime_signal(from_date, to_date, *,
                            today_fn=date.today, offline=False)
                            -> pd.Series``
      Canonical entry point — currently routes to v2 (India VIX).
      Phase 9.4's Portfolio banner calls this.

  ``current_regime_state(as_of, *, threshold_pct=75.0,
                           lookback_td=252, today_fn=date.today,
                           offline=False) -> Literal["ON", "OFF"]``
      Single-call convenience: loads India VIX over the trailing
      lookback window + computes regime_state. The function
      Phase 9.4 banners + cycle-entry checks invoke directly.

Per memoir §3.5 the average of single-name realized vols is NOT
the same as portfolio realized vol (which depends on the covariance
matrix). For a regime SIGNAL "is ambient single-name turbulence
elevated?" the simple mean is correct; the function is named to
reflect that semantic exactly so a future contributor doesn't
confuse it with portfolio variance.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable, Iterable, Literal

import numpy as np
import pandas as pd

from src.data import india_vix_loader
from src.engine import vol as _vol


# ============================================================
# Regime percentile / state — generic over signal_series
# ============================================================
#
# Spec-alignment note (2026-06-04, post-3fb0f05 review d8620f8):
# F5 in PORTFOLIO_MEMOIR.md §21.4 uses a non-NaN MINIMUM count
# expressed in terms of the REQUESTED lookback, not the window
# actually realized:
#
#     valid = window.dropna()
#     if len(valid) < 0.5 * lookback:    # ≥50% non-NaN floor
#         return float('nan')
#     rank = (valid < today).sum() / len(valid) * 100.0
#
# The denominator is ``len(valid)`` (NaN-dropped), not ``len(window)``.
# The floor is 50% of LOOKBACK_TD, not of the realized window. Both
# matter at the start of a series (when the window is shorter than
# the lookback) and on NaN-heavy windows.
#
# Initial 3fb0f05 used 10% NaN-fraction + len(window) denominator;
# reviewer d8620f8 flagged the citation drift (GRILL 1) + denominator
# semantic (GRILL 3) — both fixed here to match F5 exactly.


def regime_percentile(
    signal_series: pd.Series,
    as_of: date,
    lookback_td: int = 252,
) -> float:
    """Trailing-window percentile rank (0-100) of ``signal_series.loc[as_of]``
    vs the trailing ``lookback_td`` observations ending at ``as_of``.

    ``signal_series`` MUST be sorted by date ascending and indexed by
    ``date``-typed labels (or ``datetime64`` / ``Timestamp``-compatible).
    Typical inputs: India VIX close (post-v2), or the per-day output
    of ``avg_single_name_realized_vol`` (v1 proxy).

    Returns:
        float in [0.0, 100.0] when there's enough history.
        ``np.nan`` if:
          - ``as_of`` is not on (or before) any series date, OR
          - the lookback window has fewer than ``0.5 * lookback_td``
            non-NaN observations (insufficient history floor per
            F5 in PORTFOLIO_MEMOIR.md §21.4), OR
          - the value at ``as_of`` is itself NaN.

    Per F9 (PORTFOLIO_MEMOIR.md §21.4): identical formula to
    ``time_series_ivp`` — implemented inline so this module has no
    upstream dependency on the (deferred) IVP module.
    """
    if not isinstance(signal_series, pd.Series):
        raise TypeError(
            f"signal_series must be pd.Series, got {type(signal_series).__name__}"
        )
    if lookback_td < 2:
        raise ValueError(
            f"lookback_td must be >= 2 for a stable rank, got {lookback_td}"
        )
    if signal_series.empty:
        return float("nan")

    # Locate the index position of ``as_of`` (or the latest date
    # <= as_of). Series must be sorted ascending; we use the
    # right-edge insertion point − 1 so a non-trading-day as_of
    # rounds DOWN to the most recent trading day.
    ts_as_of = pd.Timestamp(as_of)
    idx_pos = signal_series.index.searchsorted(ts_as_of, side="right") - 1
    if idx_pos < 0:
        return float("nan")  # as_of predates the entire series

    today_value = signal_series.iloc[idx_pos]
    if pd.isna(today_value):
        # NaN today → can't rank. Pin per F5's load-bearing guard
        # ("don't silently rank NaN as 0th percentile"); the bug it
        # closes is real in the IVP corner case where a missing-IV
        # day would otherwise score as cheapest-vol-ever.
        return float("nan")

    window_start = max(0, idx_pos - lookback_td + 1)
    window = signal_series.iloc[window_start : idx_pos + 1]
    valid = window.dropna()
    # Insufficient-history floor: < 50% of LOOKBACK_TD (not of the
    # realized window length). At the start of a series the window
    # is short by construction; we don't want short-window early
    # periods to silently produce stable-looking ranks.
    if len(valid) < 0.5 * lookback_td:
        return float("nan")

    # Percentile rank on the dropna'd subset. Matches F5 spec
    # exactly: NaN-bearing days neither contribute to the count
    # nor to the denominator.
    return float((valid < today_value).sum()) / len(valid) * 100.0


def regime_state(
    signal_series: pd.Series,
    as_of: date,
    threshold_pct: float = 75.0,
    lookback_td: int = 252,
) -> Literal["ON", "OFF"]:
    """Binary gate: ``"ON"`` when ``regime_percentile(...) <= threshold_pct``,
    ``"OFF"`` otherwise.

    Default threshold 75 per PORTFOLIO_MEMOIR.md §3.1 (research v1
    setting; production deployments often use 90 for less-aggressive
    sit-out behavior). Insufficient-history NaN propagates as
    ``"OFF"`` — a research convention rooted in "skip when uncertain"
    risk-management bias; documented here so the convention is
    explicit, not load-bearing-by-accident.

    ON  = open positions this cycle.
    OFF = skip the cycle (regime is elevated; ambient vol is in the
          top quartile of trailing history).
    """
    if not 0.0 <= threshold_pct <= 100.0:
        raise ValueError(
            f"threshold_pct must be in [0, 100], got {threshold_pct}"
        )
    pct = regime_percentile(signal_series, as_of, lookback_td=lookback_td)
    if pd.isna(pct):
        # "Skip when uncertain" — see docstring above for the
        # research convention rationale.
        return "OFF"
    return "ON" if pct <= threshold_pct else "OFF"


# ============================================================
# Universe-average realized vol — v1 proxy signal
# ============================================================

def avg_single_name_realized_vol(
    symbols: Iterable[str],
    as_of: date,
    window_td: int = 21,
    *,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> float:
    """Universe-average of per-symbol annualized realized vol over a
    trailing ``window_td`` (default 21) trading-day window ending at
    ``as_of``.

    The v1 regime-gate proxy signal per PORTFOLIO_MEMOIR.md §3.5:
    until the India VIX cache has ≥252 trading days of history, the
    gate runs against this average. The semantic is "ambient
    single-name turbulence" undiluted by diversification — NOT
    portfolio realized vol (which depends on covariance and is a
    different number; see §3.5 for why the average is the correct
    REGIME signal even though it's not portfolio vol).

    Per F8 (PORTFOLIO_MEMOIR.md §21.4): plain mean of available
    per-symbol RVs; symbols with ``realized_vol() == 0.0`` (the
    engine.vol fallback for < 20 rows of history) are EXCLUDED from
    the mean — that fallback returns 0.0 specifically to signal
    "insufficient data," not "realized vol is zero." Aggregating zero
    fallbacks into the mean would silently understate ambient vol
    and mis-fire the gate to ON during cold-cache periods.

    Returns ``np.nan`` when:
      - The symbol set is empty, OR
      - Every symbol's realized_vol returns 0.0 (cold cache /
        no usable history), OR
      - Every symbol's realized_vol raises (caller-side / dataloader
        propagation — surfaced as NaN so the regime gate falls
        back to its "skip when uncertain" OFF default).
    """
    if window_td <= 1:
        raise ValueError(f"window_td must be > 1, got {window_td}")
    symbols_list = list(symbols)
    if not symbols_list:
        return float("nan")

    values: list[float] = []
    for sym in symbols_list:
        try:
            rv = _vol.realized_vol(
                sym, as_of,
                lookback_trading_days=window_td,
                today_fn=today_fn,
                offline=offline,
            )
        except Exception:
            # Per-symbol propagation failure (missing cache,
            # delisted, etc.) doesn't kill the gate signal —
            # we just drop that symbol from the average.
            continue
        if rv > 0.0:
            values.append(rv)

    if not values:
        return float("nan")
    return float(np.mean(values))


# ============================================================
# v2 signal — India VIX (memoir §3.7)
# ============================================================
#
# The forward-looking implied-vol regime signal. Phase 9.6
# wire-in. Per memoir §3.7:
#
#   "India VIX is NSE's daily-published implied-vol index based
#    on NIFTY index options. It IS the market-implied 30-day vol
#    forecast. No need to compute it from 50 stocks; it's a
#    single number per day, published since 2008."
#
# Cache layout: ``data/cache/india_vix.parquet`` (Phase 9.0
# loader output). Columns: date, india_vix_open, india_vix_high,
# india_vix_low, india_vix_close, india_vix_prev_close.
#
# The signal column is ``india_vix_close`` per memoir convention
# — the EOD settled value.

# Backfill cushion when converting a TD-counted lookback to
# calendar days. 252 TD ≈ 365 calendar days; +30 cushion absorbs
# weekends + holidays + the occasional NSE close-day so the
# loaded window always covers the requested trailing TDs.
_TD_TO_CALENDAR_RATIO = 365 / 252
_LOOKBACK_CALENDAR_CUSHION_DAYS = 30


def load_india_vix_signal(
    from_date: date,
    to_date: date,
    *,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> pd.Series:
    """Return India VIX close series over ``[from_date, to_date]``
    as the v2 regime signal.

    Loads via ``src.data.india_vix_loader.load_india_vix`` (cache-
    first; networks-on-miss unless ``offline=True``) and projects
    the ``india_vix_close`` column to a date-indexed pd.Series
    ready for ``regime_percentile`` / ``regime_state``.

    Args:
        from_date / to_date: inclusive window. Caller typically
            passes ``as_of - cushion`` to ``as_of`` so the
            trailing percentile rank has 252 TDs of history.
        today_fn / offline: forwarded to the loader. Offline mode
            raises ``OfflineCacheMiss`` if any part of the
            requested window is not cached.

    Returns:
        ``pd.Series`` named ``"india_vix_close"`` indexed by
        ``date`` (datetime64[us]) ascending. Empty series if the
        loader returns an empty frame.

    NaN handling: the loader returns no NaN rows by construction
    (cache rejects them). A non-trading-day ``as_of`` rounds
    DOWN to the most recent EOD print via the kernel's
    ``Series.index.searchsorted(..., side="right") - 1``.
    """
    df = india_vix_loader.load_india_vix(
        from_date, to_date,
        today_fn=today_fn, offline=offline,
    )
    if df.empty:
        return pd.Series(
            [], dtype="float64",
            index=pd.DatetimeIndex([], name="date"),
            name="india_vix_close",
        )
    out = (
        df.sort_values("date")
          .set_index("date")["india_vix_close"]
          .astype("float64")
    )
    out.name = "india_vix_close"
    return out


def default_regime_signal(
    from_date: date,
    to_date: date,
    *,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> pd.Series:
    """Canonical regime-signal entry point (currently v2 = India VIX).

    Phase 9.4's Portfolio banner + cycle-entry check call THIS,
    not the per-signal functions directly. The indirection lets
    future swaps (e.g., regime gate v3 = something better than
    India VIX) land as a one-line change here.

    No auto-fallback to v1 on cold cache — silent fallback would
    mask "operator forgot to prefetch India VIX" gaps. Callers
    that need a v1 fallback import ``avg_single_name_realized_vol``
    explicitly + handle the cold case.

    Args / Returns: same as ``load_india_vix_signal``.
    """
    return load_india_vix_signal(
        from_date, to_date,
        today_fn=today_fn, offline=offline,
    )


def current_regime_state(
    as_of: date,
    *,
    threshold_pct: float = 75.0,
    lookback_td: int = 252,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> Literal["ON", "OFF"]:
    """Single-call convenience: load India VIX + compute regime_state.

    The function Phase 9.4 banners + cycle-entry checks invoke
    directly. Loads enough trailing calendar days to realize the
    full ``lookback_td`` TD window (TD→calendar conversion uses
    ratio 365/252 + a 30-day cushion for weekends/holidays/closures).

    Args:
        as_of: trading date to compute the regime state for.
        threshold_pct: ON when percentile ≤ this. Default 75 per
            memoir §3.1 (also the value pinned by the operator-
            tunable sensitivity strip on the Portfolio tab).
        lookback_td: trailing window in trading days. Default 252.
        today_fn / offline: forwarded to the loader.

    Returns:
        ``"ON"`` (cycle opens) or ``"OFF"`` (skip the cycle).
        NaN percentile → ``"OFF"`` per memoir §21.4 F9
        skip-when-uncertain convention.
    """
    backfill_days = int(
        lookback_td * _TD_TO_CALENDAR_RATIO
    ) + _LOOKBACK_CALENDAR_CUSHION_DAYS
    from_date = as_of - timedelta(days=backfill_days)
    signal = default_regime_signal(
        from_date, as_of,
        today_fn=today_fn, offline=offline,
    )
    return regime_state(
        signal, as_of,
        threshold_pct=threshold_pct,
        lookback_td=lookback_td,
    )
