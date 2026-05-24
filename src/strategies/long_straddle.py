"""Long straddle: BUY ATM CE + BUY ATM PE on a given expiry.

The mirror of ShortStraddle. Profits when realized vol EXCEEDS the
combined premium paid (big move in EITHER direction). Loses when the
underlying drifts within the combined-premium range.

Same ATM strike selection rule as ShortStraddle (SPECS §5):
`argmin(|K - spot_at_entry|)` with tiebreaker = lower strike. Strike
grid is read from the entry-day bhavcopy.

Per SPECS §4a, long-only positions have NO SPAN portfolio-offset
benefit — you just pay the premium upfront and that IS the max loss.
So ``recommended_strategy_offset_pct = 1.0`` (no reduction).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.strategies.base import Leg, Trade
from src.strategies.short_straddle import _pick_atm_strike


# Long-only → no offset benefit; margin = sum of premium-paid per leg.
LONG_STRADDLE_MARGIN_OFFSET = 1.0


@dataclass(frozen=True)
class LongStraddle:
    """Buy ATM CE + buy ATM PE on a given expiry; close at exit_date.

    No tunable params in v1 — always 1 lot per leg.
    """
    name: str = "long_straddle"
    recommended_strategy_offset_pct: float = LONG_STRADDLE_MARGIN_OFFSET

    def generate_trades(
        self,
        symbol: str,
        expiry: date,
        entry_date: date,
        exit_date: date,
        spot_at_entry: float,
        params: dict | None = None,
    ) -> list[Trade]:
        """Return a single Trade with two BUY legs at the ATM strike.

        Available strikes are read from the entry-day bhavcopy via
        ``_pick_atm_strike`` (shared with ShortStraddle; same SPECS §5
        rule). Raises ``NoLiquidStrikeError`` if no OPTSTK rows exist
        for this symbol on entry_date.
        """
        atm = _pick_atm_strike(symbol, expiry, entry_date, spot_at_entry)
        legs = (
            Leg(option_type="CE", strike=atm, side="BUY", qty_lots=1),
            Leg(option_type="PE", strike=atm, side="BUY", qty_lots=1),
        )
        return [Trade(
            symbol=symbol.upper(),
            expiry=expiry,
            entry_date=entry_date,
            exit_date=exit_date,
            legs=legs,
            strategy=self.name,
            params=params or {},
        )]
