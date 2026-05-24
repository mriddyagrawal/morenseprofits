"""Realized volatility + symbol margin-pct estimation.

For Tier-B margin estimation (SPECS §4a). Two pure-Python functions:

  realized_vol(symbol, as_of, lookback_trading_days=126, today_fn, offline)
    → float (annualized stdev of daily log returns)

  vol_to_margin_pct(annualized_vol)
    → float in [0.10, 0.30] — maps vol to per-leg SPAN%

The volatility number is computed from our existing spot cache
(``spot_loader.load_spot``), so no NSE-live data is needed. Backtest-
reproducible: given the same spot cache, the vol number is byte-stable.

Calibration mapping (linear with bounds): ``margin_pct = clamp(0.10 +
0.40 × annualized_vol, 0.10, 0.30)``. Sample table from SPECS §4a:

| symbol    | realized vol (~6mo) | margin_pct | real broker SPAN |
|-----------|---------------------|------------|-------------------|
| HDFCBANK  | ~15%                | 0.16       | ~0.14            |
| RELIANCE  | ~22%                | 0.19       | ~0.16            |
| ADANIENT  | ~35%                | 0.24       | ~0.22            |

Bias is conservative: backtests show slightly higher margin than real,
which understates ROI in the safe direction for paper-then-live.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Callable

import numpy as np

from src.data import spot_loader, trading_calendar


def realized_vol(
    symbol: str,
    as_of: date,
    *,
    lookback_trading_days: int = 126,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> float:
    """Annualized standard deviation of daily log returns for ``symbol``
    over the trailing ``lookback_trading_days`` ending at ``as_of``.

    Uses ``offset_trading_days`` for the lookback start (avoids landing
    on a NSE holiday, same trick as the momentum classifier).

    Returns 0.0 if the symbol has fewer than ~20 rows in the window
    (insufficient data for a stable estimate — better to return zero
    than a noisy mis-estimate).
    """
    if lookback_trading_days <= 1:
        raise ValueError(
            f"lookback_trading_days must be > 1, got {lookback_trading_days}"
        )
    lookback_date = trading_calendar.offset_trading_days(
        as_of, lookback_trading_days, today_fn=today_fn, offline=offline,
    )
    df = spot_loader.load_spot(
        symbol, lookback_date, as_of, today_fn=today_fn, offline=offline,
    )
    if len(df) < 20:
        return 0.0
    closes = df["close"].astype("float64").to_numpy()
    log_returns = np.diff(np.log(closes))
    daily_std = float(np.std(log_returns, ddof=1))  # sample stdev
    return daily_std * math.sqrt(252.0)


def vol_to_margin_pct(annualized_vol: float) -> float:
    """Map annualized volatility to per-leg SPAN%, clamped [0.10, 0.30].

    Linear: ``margin_pct = 0.10 + 0.40 × annualized_vol``. The clamp
    keeps the result within realistic NSE SPAN bounds even for very
    low-vol or very high-vol stocks.

    See SPECS §4a for calibration table + rationale.
    """
    if annualized_vol < 0:
        raise ValueError(f"annualized_vol must be >= 0, got {annualized_vol}")
    raw = 0.10 + 0.40 * float(annualized_vol)
    return max(0.10, min(0.30, raw))


def symbol_margin_pct(
    symbol: str,
    as_of: date,
    *,
    lookback_trading_days: int = 126,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> float:
    """Convenience: compose ``realized_vol`` + ``vol_to_margin_pct``.

    For symbols with zero realized vol (no data), returns the floor
    (0.10) — keeps the loud-failure surface narrow."""
    vol = realized_vol(
        symbol, as_of,
        lookback_trading_days=lookback_trading_days,
        today_fn=today_fn, offline=offline,
    )
    return vol_to_margin_pct(vol)
