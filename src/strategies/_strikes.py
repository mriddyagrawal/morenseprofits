"""Shared strike-picking primitives for all v1 strategies.

Every strategy in src/strategies needs the same two ops:

  1. Read the available strike grid for (symbol, expiry, entry_date)
     from the day's bhavcopy and return them sorted ascending.
  2. Pick the strike nearest to a target value per SPECS §5
     (argmin(|K − target|), tiebreaker = lower strike).

Before this module existed each strategy reimplemented both — 4 copies
of the bhavcopy filter, 5 copies of the argmin rule. Consolidated here
so SPECS §5 lives in exactly one place and the bhavcopy schema is
referenced from one query.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from src.data import bhavcopy_fo_loader
from src.data.errors import MissingDataError


class NoLiquidStrikeError(MissingDataError):
    """No traded strikes available for the symbol/expiry on entry_date.
    Subclasses MissingDataError so sweeper's `except MissingDataError`
    skip-loop handles it uniformly."""


def load_available_strikes(
    symbol: str,
    expiry: date,
    entry_date: date,
) -> list[int]:
    """Return sorted-unique strike list for ``(symbol, OPTSTK, expiry)``
    from the entry-day bhavcopy. Raises ``NoLiquidStrikeError`` if the
    filter is empty (symbol not traded, expiry not listed, etc.) —
    the sweeper logs this and skips the cell.

    Strikes are returned as ``int`` because NSE OPTSTK strikes are
    always whole-rupee values. Casting filters out the rare 0.5/0.25
    junk that occasionally appears in malformed bhavcopy rows.
    """
    bc = bhavcopy_fo_loader.load_bhavcopy_fo(entry_date)
    mask = (
        (bc["symbol"] == symbol.upper())
        & (bc["instrument"] == "OPTSTK")
        & (bc["expiry"] == pd.Timestamp(expiry))
        & (bc["option_type"].isin(["CE", "PE"]))
    )
    strikes = sorted({int(s) for s in bc.loc[mask, "strike"].dropna().tolist()})
    if not strikes:
        raise NoLiquidStrikeError(
            f"no OPTSTK strikes for {symbol.upper()} {expiry} in bhavcopy "
            f"on {entry_date} — symbol/expiry combination not traded?"
        )
    return strikes


def pick_nearest(strikes: list[int], target: float) -> int:
    """SPECS §5: nearest strike to ``target`` with tiebreaker = lower.

    ``strikes`` MUST be a non-empty sorted-ascending list (as returned
    by ``load_available_strikes``). The ``(abs(K - target), K)`` tuple
    key gives lexicographic ordering — equidistant ties resolve to
    the lower strike by the K component.
    """
    return min(strikes, key=lambda k: (abs(k - target), k))
