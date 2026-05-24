"""Momentum classifier — tercile split on trailing-return.

Splits a stock universe into bullish / neutral / non_bullish by their
trailing-126-trading-day return as of a given date. See SPECS §6b.2 for
the contract; the three load-bearing decisions are encoded in code:

1. Lookback in **trading days** (126 ≈ 6×21), routed through
   ``trading_calendar.offset_trading_days(as_of, 126)`` to dodge the
   "lookback date falls on a NSE holiday" divide-by-zero trap.
2. **Top-heavy tercile**: bullish=ceil(n/3), non_bullish=floor(n/3),
   neutral=middle remainder. For n=40 → 14/13/13. Ties on returns
   broken by symbol name ascending. Output lists alphabetical.
3. **Delisted symbols** (MissingDataError from load_spot) → dropped
   with a warning, classifier continues. OfflineCacheMiss is NOT
   swallowed and propagates per SPECS §6a.
"""
from __future__ import annotations

import math
import warnings
from datetime import date
from typing import Callable

import pandas as pd

from src.data import spot_loader, trading_calendar
from src.data.errors import MissingDataError
from src.data.offline import effective_offline


def _trailing_return(
    symbol: str,
    as_of: date,
    lookback_date: date,
    *,
    today_fn: Callable[[], date],
    offline: bool,
) -> float | None:
    """Returns (close_as_of - close_lookback) / close_lookback, or None
    if data is unusable. MissingDataError → None + warning. Other
    errors propagate."""
    try:
        df = spot_loader.load_spot(
            symbol, lookback_date, as_of, today_fn=today_fn, offline=offline,
        )
    except MissingDataError as e:
        warnings.warn(
            f"momentum classifier dropping {symbol}: load_spot raised "
            f"MissingDataError ({e}). Likely delisted or renamed.",
            stacklevel=3,
        )
        return None
    if df.empty:
        warnings.warn(
            f"momentum classifier dropping {symbol}: no spot rows in "
            f"[{lookback_date}, {as_of}].",
            stacklevel=3,
        )
        return None

    # Pick the first row >= lookback_date for denominator, last row
    # <= as_of for numerator. Frame is sorted ascending per spot_loader
    # invariant so just take .iloc[0] / .iloc[-1].
    denom_close = float(df.iloc[0]["close"])
    numer_close = float(df.iloc[-1]["close"])
    if denom_close == 0.0:
        warnings.warn(
            f"momentum classifier dropping {symbol}: lookback close is 0 "
            f"(corrupt spot data on {df.iloc[0]['date']}).",
            stacklevel=3,
        )
        return None
    return (numer_close - denom_close) / denom_close


def classify_momentum(
    as_of: date,
    universe: list[str],
    *,
    lookback_trading_days: int = 126,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> dict[str, list[str]]:
    """Tercile-classify ``universe`` by trailing return at ``as_of``.

    Returns ``{"bullish": [...], "neutral": [...], "non_bullish": [...]}``
    with each list alphabetically sorted. See SPECS §6b.2.
    """
    if not universe:
        return {"bullish": [], "neutral": [], "non_bullish": []}
    if lookback_trading_days <= 0:
        raise ValueError(
            f"lookback_trading_days must be > 0, got {lookback_trading_days}"
        )
    offline = effective_offline(offline)

    lookback_date = trading_calendar.offset_trading_days(
        as_of, lookback_trading_days, today_fn=today_fn, offline=offline,
    )

    # Score every symbol; drop None (delisted / no-data) with warning.
    scored: list[tuple[float, str]] = []
    for symbol in universe:
        r = _trailing_return(
            symbol, as_of, lookback_date,
            today_fn=today_fn, offline=offline,
        )
        if r is not None:
            scored.append((r, symbol))

    # Sort by (return desc, symbol asc) — tie-break per SPECS §6b.2.
    scored.sort(key=lambda rs: (-rs[0], rs[1]))

    n = len(scored)
    n_bullish = math.ceil(n / 3)
    n_non_bullish = math.floor(n / 3)
    n_neutral = n - n_bullish - n_non_bullish

    bullish_syms = [s for _, s in scored[:n_bullish]]
    neutral_syms = [s for _, s in scored[n_bullish : n_bullish + n_neutral]]
    non_bullish_syms = [s for _, s in scored[n_bullish + n_neutral:]]

    return {
        "bullish": sorted(bullish_syms),
        "neutral": sorted(neutral_syms),
        "non_bullish": sorted(non_bullish_syms),
    }
