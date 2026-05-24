"""Short strangle: SELL OTM CE + SELL OTM PE on a given expiry.

The OTM cousin of the short straddle. Pays a smaller combined premium
but profits unless the underlying moves outside the strike range. A
common income strategy when implied vol > expected realized vol.

Strike selection per SPECS §5 + offset:
  - call_strike target = spot × (1 + ``strike_offset_pct``)
  - put_strike  target = spot × (1 − ``strike_offset_pct``)
  - Both picked from available bhavcopy strikes via the SPECS §5
    rule: argmin(|K − target|), tiebreaker = lower strike.

Tunable params (passed via ``params`` dict to ``generate_trades``):
  - ``strike_offset_pct`` (default 0.02 = 2% OTM). With 0.0,
    degenerates to ShortStraddle's ATM selection (both legs at spot).

Per SPECS §4a calibration: short strangle's real SPAN portfolio-offset
benefit ≈ 0.70 (a touch less than short straddle's 0.60 because OTM
wings are slightly less correlated). Class attribute set accordingly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from src.data import bhavcopy_fo_loader
from src.strategies.base import Leg, Trade
from src.strategies.short_straddle import NoLiquidStrikeError


SHORT_STRANGLE_MARGIN_OFFSET = 0.70
DEFAULT_STRIKE_OFFSET_PCT = 0.02  # 2% OTM each side


@dataclass(frozen=True)
class ShortStrangle:
    """Sell OTM CE + sell OTM PE; close at exit_date.

    Tunable: ``strike_offset_pct`` in ``params`` dict; default 0.02.
    """
    name: str = "short_strangle"
    recommended_strategy_offset_pct: float = SHORT_STRANGLE_MARGIN_OFFSET

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

        call_strike, put_strike = _pick_strangle_strikes(
            symbol, expiry, entry_date, spot_at_entry, offset,
        )
        legs = (
            Leg(option_type="CE", strike=call_strike, side="SELL", qty_lots=1),
            Leg(option_type="PE", strike=put_strike, side="SELL", qty_lots=1),
        )
        # Persist the offset in params_json so the sweep result row
        # records what strike-grid was used. Phase-5 can filter by it.
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


def _pick_strangle_strikes(
    symbol: str,
    expiry: date,
    entry_date: date,
    spot_at_entry: float,
    offset_pct: float,
) -> tuple[int, int]:
    """Return (call_strike, put_strike) for the strangle.

    Both strikes picked from the entry-day bhavcopy via the SPECS §5
    argmin(|K − target|) + lower-tiebreaker rule. If the bhavcopy has
    no strikes for this symbol/expiry, raises NoLiquidStrikeError.

    Note: when `offset_pct = 0`, both targets equal `spot_at_entry` so
    call_strike == put_strike (degenerates to the ATM straddle).
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
    call_target = spot_at_entry * (1.0 + offset_pct)
    put_target = spot_at_entry * (1.0 - offset_pct)
    # SPECS §5: tiebreaker = lower strike (already from sorted ascending +
    # tuple key (|K-target|, K) picks the lower in equidistant ties).
    call_strike = min(strikes, key=lambda k: (abs(k - call_target), k))
    put_strike = min(strikes, key=lambda k: (abs(k - put_target), k))
    return call_strike, put_strike
