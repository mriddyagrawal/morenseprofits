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

import warnings
from datetime import date
from typing import Callable

import pandas as pd

from jugaad_data.nse import stock_df

from src.data import cache
from src.data.errors import OfflineCacheMiss
from src.data.offline import effective_offline
from src.data.telemetry import warn_fetch


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
    force_refresh."""
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} > to_date {to_date}")
    offline = effective_offline(offline)
    years = range(from_date.year, to_date.year + 1)
    parts = [
        _load_year(symbol, y, force_refresh=force_refresh, today_fn=today_fn, offline=offline)
        for y in years
    ]
    full = pd.concat(parts, ignore_index=True)
    mask = (full["date"] >= pd.Timestamp(from_date)) & (
        full["date"] <= pd.Timestamp(to_date)
    )
    out = full.loc[mask].reset_index(drop=True)
    return out
