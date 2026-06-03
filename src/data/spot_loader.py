"""Year-keyed parquet cache for NSE EOD equity OHLC.

Contract (frozen invariants — change only with a PLAN change-log entry):

1. **One parquet per (symbol, year) contains the ENTIRE year** (or, for the
   current year, every trading day up to ``today_fn()`` at fetch time).
   This rules out sparse caches: a caller asking for "Jan 2–5" and a later
   caller asking for "Jan 2–Dec 31" never see different shapes; both
   trigger one whole-year fetch the first time and 0 fetches the second.
2. **Closed years are immutable** on disk. ``force_refresh=True`` is the
   only way to re-fetch them.
3. **Current-year refetch is length-checked.** A new response with strictly
   fewer rows than the on-disk parquet is treated as a partial NSE response
   and refused — we keep what we have and warn. NSE flakiness must never
   shrink a cache.
4. Every returned frame is **sorted by date ascending** and the engine can
   trust monotonicity without re-checking. Kills the set-iteration class of
   bug at the data-layer boundary (see PLAN.md 2026-05-24 change-log).

Schema: SPECS §2.1.
"""
from __future__ import annotations

import functools
import warnings
from datetime import date
from typing import Callable

import pandas as pd

from jugaad_data.nse import stock_df

from src.data import cache
from src.data.errors import OfflineCacheMiss
from src.data.offline import effective_offline
from src.data.telemetry import warn_fetch


# Per-process LRU cache size for the year-keyed parquet read.
# 10 universe symbols × 3 years = 30 entries; 32 leaves headroom.
# Each entry is ~250 rows × 10 cols ≈ ~25KB — 8 workers × 32 × 25KB ≈ 6 MB
# worst-case across the pool. Negligible.
_LRU_MAXSIZE_YEAR = 32


# jugaad column -> SPECS §2.1 column
_RENAMES = {
    "DATE": "date",
    "SYMBOL": "symbol",
    "SERIES": "series",
    "OPEN": "open",
    "HIGH": "high",
    "LOW": "low",
    "CLOSE": "close",
    "VWAP": "vwap",
    "VOLUME": "volume",
    "PREV. CLOSE": "prev_close",
}
_SPEC_COLS = list(_RENAMES.values())


def _normalize(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    df = raw.rename(columns=_RENAMES)[_SPEC_COLS].copy()
    # Explicit "string" cast so symbol's StringDtype na_value matches series'.
    # Without this, scalar-broadcast gives na_value=nan and the explicit
    # .astype("string") below gives na_value=<NA>; dropna() on either column
    # would then use different missing-value sentinels — corner-case
    # correctness drift waiting to happen.
    df["symbol"] = pd.array([symbol.upper()] * len(df), dtype="string")
    df["series"] = df["series"].astype("string")
    for col in ("open", "high", "low", "close", "vwap", "prev_close"):
        df[col] = df[col].astype("float64")
    df["volume"] = df["volume"].astype("int64")
    # jugaad returns DATE as a naive datetime at 18:30:00 — that's
    # 00:00 IST of the *next* day (UTC+5:30). The trading date "Jan 2 2024
    # IST" is stored as "2024-01-01 18:30:00". Without correction, a filter
    # `df.date >= pd.Timestamp(date(2024,1,2))` would *exclude* the Jan 2
    # trading row. Shift by +5h30m so every row sits at midnight IST naive,
    # matching the SPECS §2.1 "trading date, naive IST, midnight" contract.
    df["date"] = pd.to_datetime(df["date"]) + pd.Timedelta(hours=5, minutes=30)
    df = df.sort_values("date").reset_index(drop=True)
    assert df["date"].is_monotonic_increasing, (
        "post-sort frame is not monotonic — internal invariant violated"
    )
    return df


def _fetch_year(symbol: str, year: int, today_fn: Callable[[], date]) -> pd.DataFrame:
    today = today_fn()
    start = date(year, 1, 1)
    end = date(year, 12, 31) if year < today.year else today
    warn_fetch("spot_loader", f"{symbol.upper()} {year}")
    with warnings.catch_warnings():
        # jugaad emits 'no explicit representation of timezones available for
        # np.datetime64' on every call; harmless and we don't need to scare
        # the user with it on every sweep. Filter is narrowed to that exact
        # message so a future jugaad upgrade can't sneak a meaningful
        # UserWarning past us.
        warnings.filterwarnings("ignore", message=r".*timezones available.*")
        raw = stock_df(symbol=symbol.upper(), from_date=start, to_date=end, series="EQ")
    return _normalize(raw, symbol)


def _load_year(
    symbol: str,
    year: int,
    *,
    force_refresh: bool,
    today_fn: Callable[[], date],
    offline: bool = False,
) -> pd.DataFrame:
    today = today_fn()
    path = cache.spot_path(symbol, year)
    is_closed = year < today.year
    has_cache = cache.exists(path)

    if has_cache and not force_refresh:
        cached = cache.read(path)
        if is_closed:
            return cached
        # Current year: refetch only if cache is stale relative to today.
        max_cached = (
            cached["date"].max().date() if not cached.empty else None
        )
        if max_cached is not None and max_cached >= today:
            return cached
        # Want to refetch — but if offline, return stale cache (don't
        # raise; cached data is still valid, just not up-to-the-minute).
        if offline:
            return cached
        fresh = _fetch_year(symbol, year, today_fn)
        # Subset check: every date currently in the cache must still be
        # present in the fresh response. Catches both the "shorter" case
        # AND the "same length but dropped a date in the middle" case —
        # length-only would silently overwrite the latter.
        cached_dates = set(cached["date"].tolist())
        fresh_dates = set(fresh["date"].tolist())
        if not cached_dates.issubset(fresh_dates):
            missing = sorted(cached_dates - fresh_dates)
            warnings.warn(
                f"partial NSE response for {symbol.upper()} {year}: fresh "
                f"fetch is missing {len(missing)} dates that exist in cache "
                f"(first 3: {[str(d) for d in missing[:3]]}). Keeping cache.",
                stacklevel=3,
            )
            return cached
        cache.write(path, fresh, overwrite=True)
        return fresh

    # Cache miss path
    if offline:
        raise OfflineCacheMiss(
            f"spot {symbol.upper()} {year} not in cache and offline mode "
            f"requested (offline=True or MORENSE_OFFLINE=1)"
        )
    fresh = _fetch_year(symbol, year, today_fn)
    # overwrite=True for multi-worker race safety (see options_loader.py
    # cache-miss block for the full reasoning).
    cache.write(path, fresh, overwrite=True)
    return fresh


@functools.lru_cache(maxsize=_LRU_MAXSIZE_YEAR)
def _load_year_cached(
    symbol: str, year: int, today_iso: str, offline: bool,
) -> pd.DataFrame:
    """Per-worker memoization of ``_load_year`` for the (overwhelmingly
    common) ``force_refresh=False`` path. Key includes ``today_iso`` so
    a date roll mid-sweep invalidates the cache for open-year entries.

    Returns the SAME DataFrame object on cache hit — ``load_spot``
    callers do ``.loc[mask].reset_index(drop=True)`` which creates a
    new frame, so the cached value is read-only in practice."""
    today = date.fromisoformat(today_iso)
    return _load_year(
        symbol, year,
        force_refresh=False,
        today_fn=lambda: today,
        offline=offline,
    )


def load_spot(
    symbol: str,
    from_date: date,
    to_date: date,
    *,
    force_refresh: bool = False,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> pd.DataFrame:
    """Return spot OHLC for ``symbol`` between ``from_date`` and ``to_date``
    inclusive. See module docstring for the four frozen invariants.

    `offline=True` (or env MORENSE_OFFLINE=1): cache miss raises
    OfflineCacheMiss; never touches network. Takes precedence over
    force_refresh.

    Hot-path memoization: ``force_refresh=False`` (the default) goes
    through ``_load_year_cached`` so repeated calls within the same
    process for the same (symbol, year) skip disk entirely after the
    first load. Sweeps that touch the same year hundreds of thousands
    of times see ~3-4 orders of magnitude fewer parquet reads.
    ``force_refresh=True`` always bypasses the cache.
    """
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} > to_date {to_date}")
    offline = effective_offline(offline)
    years = range(from_date.year, to_date.year + 1)
    if force_refresh:
        parts = [
            _load_year(symbol, y, force_refresh=True, today_fn=today_fn, offline=offline)
            for y in years
        ]
    else:
        today_iso = today_fn().isoformat()
        parts = [
            _load_year_cached(symbol, y, today_iso, offline)
            for y in years
        ]
    full = pd.concat(parts, ignore_index=True)
    # F9 (logic-review 1347b8c, 2026-06-03): cached spot parquets can
    # carry NSE T0-series rows alongside the EQ-series prints — typically
    # single-trade micro-volume rows on the SAME date (BHEL/2025 had 6
    # such dups, PNB/2025 had 8). ``_fetch_year`` passes ``series="EQ"``
    # to jugaad, but the filter doesn't always hold, AND legacy caches
    # may have been populated under a pathway that didn't filter.
    # Defense-in-depth: drop non-EQ rows at the read-time boundary so
    # downstream (engine ATM picker, realized-vol computation,
    # entry/exit_spot fetch) sees a single row per date deterministically.
    if "series" in full.columns:
        full = full[full["series"] == "EQ"].reset_index(drop=True)
    mask = (full["date"] >= pd.Timestamp(from_date)) & (
        full["date"] <= pd.Timestamp(to_date)
    )
    out = full.loc[mask].reset_index(drop=True)
    return out
