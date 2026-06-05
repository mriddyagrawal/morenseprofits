"""Options liquidity score for portfolio candidate selection.

PORTFOLIO_MEMOIR.md §21.3 row C10 + §21.4 F11. The liquidity gate
runs BEFORE the IVP rank in the candidate-selection pipeline per
memoir §11 (universe filter) so:

  1. The IVP rank doesn't waste compute on names that wouldn't
     pass the liquidity floor anyway.
  2. The "X candidates dropped" surface in the Portfolio banner
     can attribute drops to the right gate.

Memoir English description: "trailing 21-day AVERAGE contracts
traded" per (symbol, as_of). The memoir's code sketch reads
``sub['contracts'].mean()`` against a row-per-(strike,type,day)
frame — that's a per-ROW mean ("how thick is each contract on
average"), not a per-DAY mean.

**Choice (documented deviation from the sketch):** implement
``per-day total contracts → mean across days``, NOT the
per-row mean. Rationale:

  - "Average contracts traded" in plain English maps to "average
    daily total" (a standard liquidity ranking metric).
  - The per-row mean depends on how distributed the trading is
    across the option chain (a name with one fat ATM strike + 99
    skinny OTM strikes scores LOW per-row), which is the wrong
    direction for a liquidity floor.
  - Per-day total maps to ranking conventions used elsewhere in
    the codebase (e.g., F7 vol uses per-day return std too).

The memoir's English description and the code sketch disagree;
we follow the English (which matches the operator's intent per
memoir §11.b "we want the most-traded symbols"). The choice is
called out loudly here so the reviewer can challenge if I'm
wrong.

Scope filter: only OPTSTK rows count. Per memoir §11.b the
portfolio universe is single-stock options; index options
(OPTIDX) are out of scope through Phase 11.

Public API:

  ``liquidity_score(bhavcopy_window_df, symbol, as_of, *,
                     lookback_td=21) -> float``
      Pure F11 kernel on a pre-built multi-day bhavcopy frame
      (caller's responsibility to provide a frame covering at
      least the lookback window). Returns mean-of-daily-totals
      or ``np.nan`` if the symbol has no rows in window.

  ``compute_liquidity_score(symbol, as_of, *, lookback_td=21,
                              today_fn, offline) -> float``
      Symbol-aware convenience: walks the trading calendar back
      ``lookback_td`` days, loads each day's bhavcopy from
      cache, computes the score for ONE symbol. Returns NaN on
      cold cache / unlisted symbol.

  ``compute_liquidity_scores(symbols, as_of, *, lookback_td=21,
                               today_fn, offline) -> dict[str, float]``
      Universe-batch optimization: loads each day's bhavcopy ONCE,
      then groups by symbol. O(days) bhavcopy loads instead of
      O(symbols × days). Returns ``{symbol: score}`` for every
      input symbol (NaN for unlisted).

  ``top_n_by_liquidity(symbols, as_of, *, n, lookback_td=21,
                         today_fn, offline) -> list[str]``
      Descending sort by score, NaN dropped, ties broken by
      symbol-name ASC (deterministic — same SPECS §6c.3 contract
      as ``top_n_by_ivp``).
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from typing import Callable

import numpy as np
import pandas as pd

from src.data import trading_calendar
from src.data.bhavcopy_fo_loader import load_bhavcopy_fo
from src.data.errors import OfflineCacheMiss

logger = logging.getLogger(__name__)

# Lookback window: 21 trading days (≈ 1 month). Memoir F11 default.
# Memoir §11.b notes this is independent of the IVP lookback (252)
# — liquidity is a faster-moving signal that responds to recent
# corporate-action / news flow, not multi-quarter mean reversion.
LIQUIDITY_LOOKBACK_TD = 21

# Single-stock options only — index options out of scope through
# Phase 11 per memoir §1 non-goals.
LIQUIDITY_INSTRUMENT = "OPTSTK"

# Insufficient-history floor: < 50% of LOOKBACK_TD non-zero days
# → NaN. Same convention as F5 IVP + F8 RV; if a symbol has options
# trading on fewer than ~10 of the last 21 sessions, the rank is
# too noisy to use.
LIQUIDITY_MIN_VALID_FRACTION = 0.5


# ============================================================
# F11 pure kernel
# ============================================================

def liquidity_score(
    bhavcopy_window_df: pd.DataFrame,
    symbol: str,
    as_of: date,
    *,
    lookback_td: int = LIQUIDITY_LOOKBACK_TD,
) -> float:
    """Mean of per-day total OPTSTK contracts for ``symbol`` over
    the trailing ``lookback_td`` rows ending at ``as_of``.

    F11 pure kernel — caller provides the multi-day bhavcopy frame
    (CONCATENATED across days; same SPECS §2.4 schema as a single-
    day bhavcopy). The function:

      1. Filters to ``symbol`` AND ``instrument == 'OPTSTK'``.
      2. Sums ``contracts`` per ``trade_date`` (across all strikes,
         option_types, expiries).
      3. Means those per-day totals.

    Args:
        bhavcopy_window_df: SPECS §2.4-shaped multi-day frame.
            Caller is responsible for assembling rows from the
            ``[as_of - lookback_td_calendar, as_of]`` window;
            no internal filtering by trade_date happens here
            (the caller would be slicing twice).
        symbol: NSE ticker (case-insensitive; uppercased internally).
        as_of: documented for signature symmetry with the other
            F-series functions; not used in the math (caller
            already sliced by date).
        lookback_td: floor parameter only — controls the
            ``MIN_VALID_FRACTION`` NaN gate.

    Returns:
        Mean of per-day total contracts (``float``) or ``np.nan``
        when:
          - the frame is empty / missing required columns, OR
          - ``symbol`` has zero matching rows in the frame, OR
          - the symbol has rows on fewer than
            ``LIQUIDITY_MIN_VALID_FRACTION × lookback_td`` distinct
            trade dates (insufficient sampling).

    Per-day total NOT per-row mean: the memoir's code sketch used
    ``sub['contracts'].mean()`` against per-(strike,type,day) rows
    — see module docstring for why this deviates.
    """
    del as_of  # signature symmetry; the math is on the pre-sliced frame.
    if bhavcopy_window_df is None or bhavcopy_window_df.empty:
        return float("nan")
    required = {"symbol", "instrument", "contracts", "trade_date"}
    missing = required - set(bhavcopy_window_df.columns)
    if missing:
        raise ValueError(
            f"bhavcopy_window_df missing required columns: "
            f"{sorted(missing)}; got {list(bhavcopy_window_df.columns)}"
        )

    sym = symbol.upper()
    sub = bhavcopy_window_df[
        (bhavcopy_window_df["symbol"] == sym)
        & (bhavcopy_window_df["instrument"] == LIQUIDITY_INSTRUMENT)
    ]
    if sub.empty:
        return float("nan")

    per_day_total = sub.groupby("trade_date", sort=False)["contracts"].sum()
    if len(per_day_total) < LIQUIDITY_MIN_VALID_FRACTION * lookback_td:
        return float("nan")
    return float(per_day_total.mean())


# ============================================================
# Symbol-aware convenience
# ============================================================

def _load_bhavcopy_window(
    as_of: date,
    *,
    lookback_td: int,
    today_fn: Callable[[], date],
    offline: bool,
) -> pd.DataFrame:
    """Walk the trading calendar back ``lookback_td`` days from
    ``as_of`` inclusive and concatenate the per-day bhavcopy
    frames. Days that raise ``OfflineCacheMiss`` are skipped with
    a debug log — see the materializer for the same pattern.

    Returns an empty frame if no day in the window has cache.
    """
    lookback_start = trading_calendar.offset_trading_days(
        as_of, lookback_td, today_fn=today_fn, offline=offline,
    )
    days = trading_calendar.trading_days(
        lookback_start, as_of, today_fn=today_fn, offline=offline,
    )
    parts: list[pd.DataFrame] = []
    for d in days:
        try:
            df = load_bhavcopy_fo(d, offline=offline)
        except OfflineCacheMiss:
            logger.debug("liquidity: bhavcopy offline-miss %s", d)
            continue
        if df is None or df.empty:
            continue
        parts.append(df)
    if not parts:
        return pd.DataFrame(
            columns=["symbol", "instrument", "contracts", "trade_date"]
        )
    return pd.concat(parts, ignore_index=True)


def compute_liquidity_score(
    symbol: str,
    as_of: date,
    *,
    lookback_td: int = LIQUIDITY_LOOKBACK_TD,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> float:
    """Single-symbol F11 convenience — loads the trailing-21-TD
    bhavcopy window and runs ``liquidity_score``.

    For batch-rank-the-universe queries use
    ``compute_liquidity_scores`` instead — it loads each day's
    bhavcopy ONCE then groups by symbol, vs this function which
    reloads the window per call.
    """
    window = _load_bhavcopy_window(
        as_of, lookback_td=lookback_td,
        today_fn=today_fn, offline=offline,
    )
    if window.empty:
        return float("nan")
    return liquidity_score(window, symbol, as_of, lookback_td=lookback_td)


def compute_liquidity_scores(
    symbols: Iterable[str],
    as_of: date,
    *,
    lookback_td: int = LIQUIDITY_LOOKBACK_TD,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> dict[str, float]:
    """Universe-batch F11: load the bhavcopy window ONCE, then
    compute ``liquidity_score`` for every input symbol.

    Returns ``{symbol: score}`` with ``np.nan`` for symbols that
    don't appear in the window's OPTSTK rows.

    Hot-path optimization for candidate-selection: a 50-symbol
    universe goes from ~1050 bhavcopy reads (50 × 21) to ~21
    bhavcopy reads. Bhavcopy reads are already cached by year
    via the loader's LRU, but the concat is still per-call so
    sharing the assembled window matters.
    """
    sym_list = [s.upper() for s in symbols]
    if not sym_list:
        return {}
    window = _load_bhavcopy_window(
        as_of, lookback_td=lookback_td,
        today_fn=today_fn, offline=offline,
    )
    if window.empty:
        return {s: float("nan") for s in sym_list}
    return {
        s: liquidity_score(window, s, as_of, lookback_td=lookback_td)
        for s in sym_list
    }


def top_n_by_liquidity(
    symbols: Iterable[str],
    as_of: date,
    *,
    n: int = 10,
    lookback_td: int = LIQUIDITY_LOOKBACK_TD,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> list[str]:
    """Top-``n`` most-liquid symbols on ``as_of`` per F11.

    NaN scores (cold cache, unlisted, insufficient sampling)
    EXCLUDED from the rank — same convention as
    ``analytics.ivp.top_n_by_ivp``. Tie-break by symbol-name
    ASCENDING for SPECS §6c.3 byte-identical determinism.

    Returns up to ``n`` symbols; fewer if the universe has fewer
    than ``n`` symbols with valid (non-NaN) scores.
    """
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    scores = compute_liquidity_scores(
        symbols, as_of,
        lookback_td=lookback_td,
        today_fn=today_fn,
        offline=offline,
    )
    valid: list[tuple[str, float]] = [
        (sym, sc) for sym, sc in scores.items() if not np.isnan(sc)
    ]
    # Same tie-break as top_n_by_ivp: symbol ASC primary, score DESC
    # secondary (stable sort applies primary last).
    valid.sort(key=lambda kv: kv[0])
    valid.sort(key=lambda kv: kv[1], reverse=True)
    return [s for s, _ in valid[:n]]
