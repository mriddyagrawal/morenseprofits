"""Full F&O universe enumeration from cached bhavcopies.

Phase 10.1 work per PORTFOLIO_MEMOIR.md §11 walk-back + PLAN.md
Phase 10.1: "widens to ~180-220 names for honest survivorship-
free analysis."

The curated 50-symbol blue-chip universe (
``scripts.prefetch_universe._build_default_symbols``) is a
survivor-biased subset of the NIFTY-50 + 2 industrials. The full
F&O OPTSTK universe is what NSE actually listed in the date
range — including delisted / merged names from 2023-24 that the
blue-chip list silently excludes.

## How it works

For each cached bhavcopy in ``[from_date, to_date]``:
  - Load the SPECS §2.4 frame.
  - Filter to ``instrument == "OPTSTK"`` (single-stock options;
    OPTIDX out of scope per Phase 11).
  - Extract the distinct ``symbol`` column.

Union across all days; return the sorted list. Bhavcopies that
fail to load (offline cache gap, holiday, etc.) are skipped —
the helper degrades to "whatever cache we have."

## Why not just NSE's published F&O list?

NSE publishes "F&O bhavcopy" eligibility lists periodically, but
those are SURVIVOR-biased on the date they were published —
delisted-by-then names are absent even though they DID trade
historically. The bhavcopy enumeration is the honest source-of-
truth: what symbols ACTUALLY had OPTSTK rows on any given day.

## Public API

  ``enumerate_fo_universe(from_date, to_date, *, today_fn=date.today,
                            offline=True) -> list[str]``
      Scan the cached bhavcopies in ``[from_date, to_date]``,
      return sorted distinct OPTSTK symbols. Empty list if
      cache is cold.

  ``OPTSTK_INSTRUMENT = "OPTSTK"`` — the constant used to filter.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from src.data import bhavcopy_fo_loader, trading_calendar
from src.data.errors import OfflineCacheMiss


# Single-stock options only — index options (OPTIDX) out of
# scope through Phase 11.
OPTSTK_INSTRUMENT = "OPTSTK"


def enumerate_fo_universe(
    from_date: date,
    to_date: date,
    *,
    today_fn: Callable[[], date] = date.today,
    offline: bool = True,
) -> list[str]:
    """Return the sorted list of distinct OPTSTK symbols that appear
    in any cached bhavcopy in ``[from_date, to_date]``.

    Default ``offline=True`` so this is a pure-cache read; the
    helper is meant to be run after the bhavcopy prefetch step
    has populated ``data/cache/bhavcopy_fo/*.parquet``.

    Days that fail to load (OfflineCacheMiss on a gap, weekend
    rolled into the trading_calendar list, etc.) are skipped
    silently. Honest semantic: "what's in the cache" — not "what
    NSE actually published." The operator can re-run the
    bhavcopy prefetch first to close any gaps.

    Args:
        from_date / to_date: inclusive window. ``from_date`` >
            ``to_date`` raises ValueError.
        today_fn / offline: forwarded to the bhavcopy + calendar
            loaders. offline=True (default) means no network
            calls; cache-misses degrade to empty days.

    Returns:
        Sorted list of distinct symbols. Empty list when the
        cache covers no trading days in window or every day
        fails to load.
    """
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} > to_date {to_date}")
    try:
        days = trading_calendar.trading_days(
            from_date, to_date,
            today_fn=today_fn, offline=offline,
        )
    except Exception:
        # Cold trading-calendar cache — best-effort fall through
        # to "no days," which yields an empty universe. Operator
        # sees the empty list and runs the bhavcopy prefetch.
        return []

    seen: set[str] = set()
    for d in days:
        try:
            df = bhavcopy_fo_loader.load_bhavcopy_fo(d, offline=offline)
        except OfflineCacheMiss:
            continue
        except Exception:
            # Defensive: don't let a single corrupt parquet kill
            # the whole enumeration.
            continue
        if df is None or df.empty:
            continue
        if "instrument" not in df.columns or "symbol" not in df.columns:
            continue
        sub = df[df["instrument"] == OPTSTK_INSTRUMENT]
        if sub.empty:
            continue
        # Coerce to plain str — bhavcopy parsers may use
        # StringDtype which isn't natively hashable into a set.
        seen.update(s for s in sub["symbol"].astype(str).unique())
    return sorted(seen)
