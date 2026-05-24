"""Short straddle strategy: sell ATM CE + sell ATM PE on the same expiry.

The canonical option-selling strategy. Profits when realized vol is
LOWER than implied vol (the credit received). Loses when the underlying
moves more than the combined premium suggests.

Per SPECS §5 ATM rule: ATM = strike nearest to entry-day spot close;
tiebreaker is the lower strike. Available strikes are auto-detected by
querying the bhavcopy for the entry date and filtering to the symbol's
OPTSTK strikes for the requested expiry.

The strategy passes ``strategy_offset_pct=0.60`` to ``price_trade`` for
Tier-B margin accuracy (SPECS §4a) — short straddle's real SPAN offset
benefit. Without this, the v1 margin block would be ~73% over real.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.strategies._strikes import (
    NoLiquidStrikeError,
    load_available_strikes,
    pick_nearest,
)
from src.strategies.base import Leg, Trade


# Strategy's real-world SPAN offset benefit per SPECS §4a calibration.
# Real broker ~₹1.5L vs sum-of-naked-legs ~₹2.6L → ratio 0.58 ≈ 0.60.
SHORT_STRADDLE_MARGIN_OFFSET = 0.60


# Re-exported here so existing `from src.strategies.short_straddle
# import NoLiquidStrikeError` callers don't break — the canonical home
# is now src.strategies._strikes.
__all__ = ["SHORT_STRADDLE_MARGIN_OFFSET", "ShortStraddle", "NoLiquidStrikeError"]


@dataclass(frozen=True)
class ShortStraddle:
    """Sell ATM CE + sell ATM PE on a given expiry; close at exit_date.

    No tunable params in v1 — always 1 lot per leg. Phase 4 will add
    `qty_lots` and `strike_offset_pct` (for short strangle, etc.).

    `recommended_strategy_offset_pct` (SPECS §4a + §6c.1) is the
    real-world SPAN portfolio-offset benefit for this strategy. The
    sweeper reads this generically and forwards to
    `price_trade(strategy_offset_pct=...)` so Tier-B margin math is
    automatic — callers don't have to remember the constant.
    """
    name: str = "short_straddle"
    recommended_strategy_offset_pct: float = SHORT_STRADDLE_MARGIN_OFFSET

    def generate_trades(
        self,
        symbol: str,
        expiry: date,
        entry_date: date,
        exit_date: date,
        spot_at_entry: float,
        params: dict | None = None,
    ) -> list[Trade]:
        """Return a single Trade with two SELL legs at ATM strike.

        Available strikes are read from the entry-day bhavcopy filtered
        to ``(symbol, OPTSTK, expiry)``. ATM = argmin(|K - spot|) with
        tiebreaker = lower strike per SPECS §5.

        Raises NoLiquidStrikeError if no OPTSTK rows exist for this
        symbol on entry_date.
        """
        atm = _pick_atm_strike(symbol, expiry, entry_date, spot_at_entry)
        legs = (
            Leg(option_type="CE", strike=atm, side="SELL", qty_lots=1),
            Leg(option_type="PE", strike=atm, side="SELL", qty_lots=1),
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


def _pick_atm_strike(
    symbol: str,
    expiry: date,
    entry_date: date,
    spot_at_entry: float,
) -> int:
    """SPECS §5 ATM picker. Kept as a thin wrapper so external callers
    (LongStraddle, tests) that imported this name don't break. New
    callers should use ``_strikes.load_available_strikes`` +
    ``_strikes.pick_nearest`` directly."""
    strikes = load_available_strikes(symbol, expiry, entry_date)
    return pick_nearest(strikes, spot_at_entry)
