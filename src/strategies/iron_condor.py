"""Iron Condor: short inner OTM straddle + long outer OTM straddle.

Four legs in canonical order:
  1. SELL inner-OTM CE  (near-OTM call, ~2% above spot)
  2. BUY  outer-OTM CE  (far-OTM call wing, ~5% above spot)
  3. SELL inner-OTM PE  (near-OTM put,  ~2% below spot)
  4. BUY  outer-OTM PE  (far-OTM put wing,  ~5% below spot)

Profits when the underlying stays between the inner strikes through
expiry (collect the net credit). Losses are bounded on both sides by
the long wings — max loss = (outer − inner) × shares − net credit.
The defining property of iron condor: capital-efficient because both
spreads cap each other's tail risk.

Strike selection per SPECS §5 + offsets:
  - inner_call target = spot × (1 + ``inner_offset_pct``)
  - outer_call target = spot × (1 + ``outer_offset_pct``)
  - inner_put  target = spot × (1 − ``inner_offset_pct``)
  - outer_put  target = spot × (1 − ``outer_offset_pct``)

Each target picked from the entry-day bhavcopy via argmin(|K − target|)
with tiebreaker = lower strike. The 4 strikes don't have to be
equidistant once the bhavcopy grid is sparse — that's expected and
correct (real iron condors trade against the available strike chain).

Tunable params (passed via ``params`` dict to ``generate_trades``):
  - ``inner_offset_pct`` (default 0.02 = 2% OTM each side for SELL legs)
  - ``outer_offset_pct`` (default 0.05 = 5% OTM each side for BUY wings)
  - Both must be > 0 and ``outer_offset_pct > inner_offset_pct``.

Per SPECS §4a calibration: iron condor's real SPAN portfolio-offset
benefit ≈ 0.35 — biggest offset of any v1 strategy because BOTH the
call spread AND the put spread cap their own tail, dramatically
reducing the broker's worst-case capital block.

Note: SPECS §4a caveat #1 (spot-vs-strike margin basis) is most
visible on iron condor — 4 strikes flank spot at 4 different distances.
The sweeper passes ``spot_at_entry`` to the margin model so the
notional basis is spot-based by default; see fix(p4.4.d.i).
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


IRON_CONDOR_MARGIN_OFFSET = 0.35
DEFAULT_INNER_OFFSET_PCT = 0.02
DEFAULT_OUTER_OFFSET_PCT = 0.05


@dataclass(frozen=True)
class IronCondor:
    """4-leg iron condor: SELL inner straddle, BUY outer straddle.

    Tunable: ``inner_offset_pct`` + ``outer_offset_pct`` via ``params``.
    Both default to 0.02 / 0.05 (a "wide" condor — collects modest
    credit, max loss bounded by the 3% wing-to-inner gap).
    """
    name: str = "iron_condor"
    recommended_strategy_offset_pct: float = IRON_CONDOR_MARGIN_OFFSET

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
        inner = float(params.get("inner_offset_pct", DEFAULT_INNER_OFFSET_PCT))
        outer = float(params.get("outer_offset_pct", DEFAULT_OUTER_OFFSET_PCT))
        if inner <= 0 or outer <= 0:
            raise ValueError(
                f"inner_offset_pct and outer_offset_pct must be > 0, "
                f"got inner={inner!r}, outer={outer!r}"
            )
        if outer <= inner:
            raise ValueError(
                f"outer_offset_pct must be > inner_offset_pct, "
                f"got outer={outer!r}, inner={inner!r}"
            )

        inner_call, outer_call, inner_put, outer_put = _pick_condor_strikes(
            symbol, expiry, entry_date, spot_at_entry, inner, outer,
        )
        # Canonical leg order: call spread first (inner SELL, outer BUY),
        # then put spread (inner SELL, outer BUY). Deterministic so the
        # legs_json column has a stable shape Phase-5 can rely on.
        legs = (
            Leg(option_type="CE", strike=inner_call, side="SELL", qty_lots=1),
            Leg(option_type="CE", strike=outer_call, side="BUY",  qty_lots=1),
            Leg(option_type="PE", strike=inner_put,  side="SELL", qty_lots=1),
            Leg(option_type="PE", strike=outer_put,  side="BUY",  qty_lots=1),
        )
        out_params = {
            "inner_offset_pct": inner,
            "outer_offset_pct": outer,
        }
        return [Trade(
            symbol=symbol.upper(),
            expiry=expiry,
            entry_date=entry_date,
            exit_date=exit_date,
            legs=legs,
            strategy=self.name,
            params=out_params,
        )]


def _pick_condor_strikes(
    symbol: str,
    expiry: date,
    entry_date: date,
    spot_at_entry: float,
    inner_offset_pct: float,
    outer_offset_pct: float,
) -> tuple[int, int, int, int]:
    """Return (inner_call, outer_call, inner_put, outer_put) via the
    shared SPECS §5 picker. Duplicates allowed if the grid is sparse
    (e.g., inner_call == outer_call when only one strike exists above
    spot — silent collapse to a degenerate call spread)."""
    strikes = load_available_strikes(symbol, expiry, entry_date)
    inner_call = pick_nearest(strikes, spot_at_entry * (1.0 + inner_offset_pct))
    outer_call = pick_nearest(strikes, spot_at_entry * (1.0 + outer_offset_pct))
    inner_put = pick_nearest(strikes, spot_at_entry * (1.0 - inner_offset_pct))
    outer_put = pick_nearest(strikes, spot_at_entry * (1.0 - outer_offset_pct))
    return inner_call, outer_call, inner_put, outer_put
