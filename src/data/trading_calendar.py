"""NSE trading-day calendar — single source of truth for date arithmetic.

Bootstrapped from the spot price series of ``src.config.CALENDAR_SYMBOL``
(RELIANCE) per SPECS §6 — if NSE recorded a closing price on date D, then
D was a trading day, full stop. This avoids maintaining a separate
holidays-database that could drift out of sync with what NSE actually did
(e.g. unusual Saturday special sessions like 2024-01-20, or last-minute
holiday additions).

`jugaad_data.holidays` is used in tests as a CROSS-CHECK only — any date
returned by ``trading_days`` that's also in ``holidays(year)`` would be a
bug somewhere upstream.

API:
    trading_days(from_date, to_date) -> list[date]
    offset_trading_days(anchor, n) -> date

Semantics for ``offset_trading_days`` pinned in SPECS §3 — see docstring
of the function itself for the rules.

Perf #2 (2026-06-04): the per-call ``load_spot``+filter pattern was
dominating the sweep profile (398s cumtime on 227k calls = ~28% of
the 1445s single-process profile). Replaced with a wide-range cached
tuple of trading days and bisect lookups:

  - ``_full_calendar_cached``: one ``load_spot`` per (earliest_iso,
    today_iso, offline) tuple per worker — typically once per process.
  - ``trading_days``: bisect_left + bisect_right slice on the cached
    tuple (O(log N)) instead of per-call ``load_spot`` filter (O(N)).
  - ``offset_trading_days``: bisect_right + index arithmetic on the
    cached tuple. Drops the prior buffer-doubling loop on the fast
    path.

A buffer-doubling slow-path (``_offset_trading_days_slow``) is kept as a
fallback for anchors / lookbacks that fall outside the cached 10-year
window — typically a synthetic test fixture, not a production code path.
"""
from __future__ import annotations

import bisect
import functools
from datetime import date, timedelta
from typing import Callable

from src.config import CALENDAR_SYMBOL
from src.data import spot_loader
from src.data.offline import effective_offline


# Initial calendar-day buffer when searching backwards. n=N trading days
# needs at minimum ceil(N * 7/5) calendar days; the constants give a safe
# fixed buffer plus a 2:1 multiplier on n.
_INITIAL_BUFFER_DAYS = 60
_BUFFER_MULTIPLIER = 2
_BUFFER_HEADROOM = 14
_MAX_BUFFER_DAYS = 1500  # beyond this we give up — NSE history isn't that deep

# How many calendar years back from ``today_fn`` to cache when building
# ``_full_calendar_cached``. 10 years covers every sweep workload + a
# margin for historical analysis. Tuning this UP costs ~250 dates of
# python-object memory per added year (negligible); tuning DOWN risks
# falling into the slow-path for valid production queries.
_CALENDAR_HISTORY_YEARS = 10

# LRU cap for ``_full_calendar_cached``. The cache key is (earliest_iso,
# today_iso, offline) — within a single process, those vary only by a
# date roll (typically a single key per process for the lifetime of a
# sweep). 4 covers normal use + edge cases like test fixtures running
# back-to-back with different today_fns.
_LRU_MAXSIZE_CALENDAR = 4


@functools.lru_cache(maxsize=_LRU_MAXSIZE_CALENDAR)
def _full_calendar_cached(
    earliest_iso: str, today_iso: str, offline: bool,
) -> tuple[date, ...]:
    """Sorted tuple of NSE trading days from ``earliest_iso`` (inclusive)
    to ``today_iso`` (inclusive). Memoized per-worker.

    The cache populates with ONE ``load_spot`` call for the
    ``CALENDAR_SYMBOL`` over the requested range. Subsequent
    ``trading_days`` / ``offset_trading_days`` calls bisect this tuple
    instead of re-reading + re-filtering the spot frame.

    Key includes ``today_iso`` so a date roll mid-process invalidates
    the cache for the current-year tail (matches the
    ``_load_year_cached`` semantics in ``spot_loader``).

    Returns an empty tuple when the spot frame is empty (e.g., the
    synthetic ``_patch_load_spot`` test fixture for an empty fixture)
    — downstream consumers must tolerate that and fall back to the
    slow path."""
    earliest = date.fromisoformat(earliest_iso)
    today = date.fromisoformat(today_iso)
    df = spot_loader.load_spot(
        CALENDAR_SYMBOL, earliest, today,
        today_fn=lambda: today,
        offline=offline,
    )
    if df.empty:
        return ()
    return tuple(sorted(df["date"].dt.date.unique().tolist()))


def _get_cached_calendar(
    today_fn: Callable[[], date], offline: bool,
) -> tuple[date, ...]:
    """Resolve the wide cached calendar for ``today_fn``'s frame.
    Centralized so both ``trading_days`` and ``offset_trading_days``
    share one cache key."""
    today = today_fn()
    earliest = date(today.year - _CALENDAR_HISTORY_YEARS, 1, 1)
    return _full_calendar_cached(
        earliest.isoformat(), today.isoformat(), offline,
    )


def _clear_calendar_cache_for_test() -> None:
    """Test-only: drop the memoized calendar so a monkeypatched
    ``spot_loader.load_spot`` fixture doesn't leak across tests
    within the same process.

    Production code never calls this — the calendar cache is one-shot
    per process by design (a date roll triggers natural invalidation
    via the ``today_iso`` key)."""
    _full_calendar_cached.cache_clear()


def trading_days(
    from_date: date,
    to_date: date,
    *,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> list[date]:
    """Return sorted unique trading days in ``[from_date, to_date]``
    inclusive. Bootstrapped from ``load_spot(CALENDAR_SYMBOL, ...)``.

    `offline=True` (or env MORENSE_OFFLINE=1): cache miss raises
    OfflineCacheMiss via the underlying load_spot.

    Perf #2 (2026-06-04): fast path bisects a wide cached calendar
    (~10 years of trading days). Out-of-cache-range queries fall back
    to a fresh ``load_spot`` call — same semantics as the pre-perf-#2
    path."""
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} > to_date {to_date}")
    offline = effective_offline(offline)
    full = _get_cached_calendar(today_fn, offline)
    # Fast path: requested window lies within the cached range.
    if full and from_date >= full[0]:
        lo = bisect.bisect_left(full, from_date)
        hi = bisect.bisect_right(full, to_date)
        return list(full[lo:hi])
    # Out-of-range fallback (rare — typically a test fixture asking
    # for dates earlier than the cached floor).
    df = spot_loader.load_spot(
        CALENDAR_SYMBOL, from_date, to_date,
        today_fn=today_fn, offline=offline,
    )
    return sorted(df["date"].dt.date.unique().tolist())


def offset_trading_days(
    anchor: date,
    n: int,
    *,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> date:
    """Return the date that is ``n`` trading days BEFORE ``anchor`` (n>=0).

    Rules (pinned in SPECS §3):
      * ``n=0`` and ``anchor`` is a trading day → returns ``anchor``.
      * ``n=0`` and ``anchor`` is NOT a trading day → returns the most
        recent trading day strictly before ``anchor`` (round-down).
      * ``n=1`` → one trading day before anchor (regardless of whether
        anchor itself is a trading day).
      * ``n < 0`` → ValueError.
      * Insufficient NSE history → ValueError.

    Perf #2 (2026-06-04): fast path bisects the cached calendar tuple
    and does index arithmetic for the offset. Buffer-doubling slow
    path retained as a fallback for synthetic test fixtures whose
    history is shorter than the cached window."""
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")

    offline = effective_offline(offline)
    full = _get_cached_calendar(today_fn, offline)
    # Fast path: anchor + n+1 entries fit within the cached tuple.
    if full and anchor >= full[0]:
        # Index of the latest trading day <= anchor.
        idx = bisect.bisect_right(full, anchor) - 1
        if idx >= 0:
            target_idx = idx - n
            if target_idx >= 0:
                return full[target_idx]
            # Falls through to the slow path — cached tuple doesn't
            # have enough history before anchor. Slow path will raise
            # ValueError if true insufficient history.
    return _offset_trading_days_slow(
        anchor, n, today_fn=today_fn, offline=offline,
    )


def _offset_trading_days_slow(
    anchor: date,
    n: int,
    *,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> date:
    """Buffer-doubling fallback (preserves the pre-perf-#2 semantics).

    Used when the cached calendar's range doesn't cover ``anchor`` (or
    doesn't have ``n`` trading days before ``anchor``) — typically a
    synthetic test fixture, occasionally a deep-history production
    query that exceeds the 10-year cache window. Calls ``load_spot``
    directly so it doesn't re-enter the cached path on each iteration.
    """
    buffer_days = max(n * _BUFFER_MULTIPLIER + _BUFFER_HEADROOM, _INITIAL_BUFFER_DAYS)
    while True:
        start = anchor - timedelta(days=buffer_days)
        end = min(anchor, today_fn())
        df = spot_loader.load_spot(
            CALENDAR_SYMBOL, start, end,
            today_fn=today_fn, offline=offline,
        )
        days = sorted(df["date"].dt.date.unique().tolist())
        days_le = [d for d in days if d <= anchor]
        if len(days_le) >= n + 1:
            return days_le[-(n + 1)]
        if buffer_days >= _MAX_BUFFER_DAYS:
            raise ValueError(
                f"cannot find {n} trading days before {anchor} within "
                f"{buffer_days} calendar days of history; NSE data via "
                f"jugaad doesn't go that far back, or the request is bogus"
            )
        buffer_days *= 2
