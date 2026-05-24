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
"""
from __future__ import annotations

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
    OfflineCacheMiss via the underlying load_spot."""
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} > to_date {to_date}")
    offline = effective_offline(offline)
    df = spot_loader.load_spot(
        CALENDAR_SYMBOL, from_date, to_date, today_fn=today_fn, offline=offline,
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
    """
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")

    offline = effective_offline(offline)
    buffer_days = max(n * _BUFFER_MULTIPLIER + _BUFFER_HEADROOM, _INITIAL_BUFFER_DAYS)
    while True:
        start = anchor - timedelta(days=buffer_days)
        # Cap end at today_fn — load_spot won't return data past today.
        end = min(anchor, today_fn())
        days = trading_days(start, end, today_fn=today_fn, offline=offline)
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
