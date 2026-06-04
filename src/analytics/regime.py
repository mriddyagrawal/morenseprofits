"""Regime gate signal + percentile rank.

PORTFOLIO_MEMOIR.md §3 (regime gate design) and §21.4 formulas F7,
F8, F9. Three pure functions, no Streamlit, no I/O coupling beyond
the spot_loader call inside ``avg_single_name_realized_vol`` (which
the caller can monkeypatch for tests).

Public API:

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
      Universe-average of per-symbol 21-trading-day annualized
      realized vol. Used as the v1 regime-gate proxy signal until
      the India VIX series accumulates 252+ trading days of cache.

Per memoir §3.5 the average of single-name realized vols is NOT
the same as portfolio realized vol (which depends on the covariance
matrix). For a regime SIGNAL "is ambient single-name turbulence
elevated?" the simple mean is correct; the function is named to
reflect that semantic exactly so a future contributor doesn't
confuse it with portfolio variance.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Iterable, Literal

import numpy as np
import pandas as pd

from src.engine import vol as _vol


# ============================================================
# Regime percentile / state — generic over signal_series
# ============================================================

# Maximum allowed fraction of NaN values in the lookback window
# before regime_percentile gives up and returns NaN. Per F5 in
# PORTFOLIO_MEMOIR.md §21.4 (time_series_ivp also uses this 10%
# rule for the same reason — a window that's mostly NaN can't
# produce a stable percentile rank).
_MAX_NAN_FRACTION = 0.10


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
          - the lookback window has < 2 observations (degenerate
            rank), OR
          - the window has > 10% NaN observations
            (insufficient data per the same threshold the IVP path
            uses; PORTFOLIO_MEMOIR.md §21.4 F5), OR
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

    window_start = max(0, idx_pos - lookback_td + 1)
    window = signal_series.iloc[window_start : idx_pos + 1]
    if len(window) < 2:
        return float("nan")
    nan_fraction = float(window.isna().sum()) / len(window)
    if nan_fraction > _MAX_NAN_FRACTION:
        return float("nan")

    today_value = window.iloc[-1]
    if pd.isna(today_value):
        return float("nan")

    # Percentile rank: fraction of window strictly LESS than today,
    # scaled to [0, 100]. Same as F5/F9 in the memoir.
    return float((window < today_value).sum()) / len(window) * 100.0


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
