"""Long strangle: BUY OTM CE + BUY OTM PE on a given expiry.

The mirror of ShortStrangle. Profits when realized vol clears the
combined premium paid AND the move breaks through either OTM wing.
Loses when the underlying drifts between the wings.

Same OTM strike selection rule as ShortStrangle:
  - call_strike target = spot × (1 + ``strike_offset_pct``)
  - put_strike  target = spot × (1 − ``strike_offset_pct``)
  - Both picked from available bhavcopy strikes via the shared SPECS §5
    helpers in ``_strikes``.

Per SPECS §4a, long-only positions have NO SPAN portfolio-offset
benefit — premium paid IS the max loss. So
``recommended_strategy_offset_pct = 1.0`` (no reduction).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.strategies._strikes import load_available_strikes, pick_nearest
from src.strategies.base import Leg, Trade
from src.strategies.short_strangle import DEFAULT_STRIKE_OFFSET_PCT


# Long-only → no offset benefit; margin = sum of premium-paid per leg.
LONG_STRANGLE_MARGIN_OFFSET = 1.0


@dataclass(frozen=True)
class LongStrangle:
    """Buy OTM CE + buy OTM PE; close at exit_date.

    Tunable: ``strike_offset_pct`` in ``params`` dict; default 0.02.
    """
    name: str = "long_strangle"
    recommended_strategy_offset_pct: float = LONG_STRANGLE_MARGIN_OFFSET

    def generate_trades(
        self,
        symbol: str,
        expiry: date,
        entry_date: date,
        exit_date: date,
        spot_at_entry: float,
        params: dict | None = None,
    ) -> list[Trade]:
        params = params or {}
        offset = float(params.get("strike_offset_pct", DEFAULT_STRIKE_OFFSET_PCT))
        if offset < 0:
            raise ValueError(
                f"strike_offset_pct must be >= 0, got {offset!r}"
            )

        strikes = load_available_strikes(symbol, expiry, entry_date)
        call_strike = pick_nearest(strikes, spot_at_entry * (1.0 + offset))
        put_strike = pick_nearest(strikes, spot_at_entry * (1.0 - offset))
        legs = (
            Leg(option_type="CE", strike=call_strike, side="BUY", qty_lots=1),
            Leg(option_type="PE", strike=put_strike, side="BUY", qty_lots=1),
        )
        out_params = {"strike_offset_pct": offset}
        return [Trade(
            symbol=symbol.upper(),
            expiry=expiry,
            entry_date=entry_date,
            exit_date=exit_date,
            legs=legs,
            strategy=self.name,
            params=out_params,
        )]
