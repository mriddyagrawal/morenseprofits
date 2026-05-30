"""MCP tools — universe & calendar (3 tools, sub-arc 3.1).

  - list_universe(as_of?)                : 50 NSE blue-chip symbols
  - expiries_for(symbol, from, to)       : monthly expiries from cache
  - list_strategies()                    : registered strategies + specs

All three respect the read-only contract: zero writes, zero NSE
network calls. ``expiries_for`` forces ``offline=True`` on the
underlying ``monthly_expiries`` so a cache miss raises
OfflineCacheMiss (surfaced to the consumer as an error) rather than
silently fetching from NSE.

The caveats-contract from the consultation: every response inherits
from ``CaveatedResponse`` so the ``caveats`` field is schema-
enforced. The list_universe + list_strategies caveats always include
the survivorship-bias and strategy-snapshot framings; expiries_for
returns an empty caveats list (no aggregation, raw data lookup).
"""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from src.data.errors import OfflineCacheMiss
from src.data.expiry_calendar import monthly_expiries
from src.mcp._models import CaveatedResponse, ToolEntry
from src.strategies.registry import STRATEGIES
from src.universe.blue_chip import blue_chip


# ============================================================
# list_universe
# ============================================================

class ListUniverseInput(BaseModel):
    as_of: date | None = Field(
        default=None,
        description=(
            "Date to query the universe as-of. Currently v1 returns "
            "the same mid-2024 snapshot regardless of ``as_of`` (see "
            "caveats); the parameter is here so future point-in-time "
            "membership lookups can replace the impl without breaking "
            "the contract."
        ),
    )


class ListUniverseOutput(CaveatedResponse):
    blue_chip: list[str] = Field(
        ...,
        description=(
            "48 NIFTY-50-derived large-cap NSE symbols. Sorted "
            "alphabetically for determinism."
        ),
    )
    extras: list[str] = Field(
        ...,
        description=(
            "Operator-requested additions outside the blue-chip 48 "
            "(PNB + BHEL — public-sector industrials)."
        ),
    )
    total: int = Field(..., description="len(blue_chip) + len(extras)")


def list_universe_impl(inp: ListUniverseInput) -> ListUniverseOutput:
    chips = blue_chip(inp.as_of or date.today())
    extras = ["PNB", "BHEL"]
    caveats = [
        # Survivorship-bias caveat per SPECS §6b.3 — ALWAYS present
        # because v1 ignores as_of and returns the same snapshot.
        "Mid-2024 NIFTY-50 snapshot; backtests against pre-2024 data "
        "have classic survivorship bias (stocks dropped from the "
        "index before 2024 are absent, so historical returns look "
        "better than reality).",
        "v1 ignores as_of and returns the same snapshot regardless "
        "of date. Point-in-time membership is a Phase-7 backlog item.",
    ]
    return ListUniverseOutput(
        blue_chip=chips,
        extras=extras,
        total=len(chips) + len(extras),
        caveats=caveats,
    )


# ============================================================
# expiries_for
# ============================================================

class ExpiriesForInput(BaseModel):
    symbol: str = Field(
        ...,
        description=(
            "NSE trading symbol (uppercase, no exchange suffix). "
            "Examples: 'RELIANCE', 'BAJAJ-AUTO' (with hyphen), 'M&M'."
        ),
    )
    from_date: date = Field(..., description="Inclusive lower bound.")
    to_date: date = Field(..., description="Inclusive upper bound.")


class ExpiriesForOutput(CaveatedResponse):
    symbol: str
    expiries: list[date] = Field(
        ...,
        description=(
            "Sorted-unique OPTSTK monthly expiry dates whose "
            "``expiry_date`` falls in [from_date, to_date]."
        ),
    )


def expiries_for_impl(inp: ExpiriesForInput) -> ExpiriesForOutput:
    # ``offline=True`` so a cache miss raises OfflineCacheMiss rather
    # than silently fetching from NSE. The MCP tool's read-only
    # contract precludes any network activity; the SDK surfaces the
    # raised error to the consumer as a tool-error response.
    exps = monthly_expiries(
        inp.symbol, inp.from_date, inp.to_date, offline=True,
    )
    return ExpiriesForOutput(
        symbol=inp.symbol.upper(),
        expiries=exps,
        caveats=[],  # raw data lookup; no aggregate to caveat
    )


# ============================================================
# list_strategies
# ============================================================

class StrategySpec(BaseModel):
    name: str
    strike_rule: str = Field(
        ...,
        description=(
            "Human-readable description of how the strategy picks "
            "strikes (e.g. 'ATM — nearest listed strike to entry-"
            "day spot close')."
        ),
    )
    recommended_strategy_offset_pct: float = Field(
        ...,
        description=(
            "Tier-B margin offset (SPECS §4a). The fraction of spot "
            "notional used as the margin reference for this strategy."
        ),
    )


class ListStrategiesInput(BaseModel):
    """list_strategies takes no arguments. Pydantic still requires a
    declared model for the input-schema generation."""


class ListStrategiesOutput(CaveatedResponse):
    strategies: list[StrategySpec]


def list_strategies_impl(inp: ListStrategiesInput) -> ListStrategiesOutput:
    specs: list[StrategySpec] = []
    for name in sorted(STRATEGIES.keys()):
        strat = STRATEGIES[name]
        specs.append(
            StrategySpec(
                name=name,
                strike_rule=strat.display_strike_rule(),
                recommended_strategy_offset_pct=float(
                    strat.recommended_strategy_offset_pct
                ),
            )
        )
    caveats = [
        "Strategies are frozen at code level; v1 does not support "
        "operator-defined strategies via the MCP API.",
        "``recommended_strategy_offset_pct`` is the Tier-B margin "
        "shortcut. Real NSE SPAN margins can differ; SPECS §4a covers "
        "the calibration table.",
    ]
    return ListStrategiesOutput(strategies=specs, caveats=caveats)


# ============================================================
# Registry export
# ============================================================

def register_universe_tools() -> list[ToolEntry]:
    """Return the 3 tool entries for this sub-arc. Called from
    ``src.mcp.server.build_server`` to assemble the full tool set."""
    return [
        ToolEntry(
            name="list_universe",
            description=(
                "Return the 50-symbol NSE backtest universe (48 "
                "blue chips + PNB + BHEL). Includes survivorship-"
                "bias caveat — mid-2024 NIFTY-50 snapshot is the "
                "underlying source."
            ),
            input_model=ListUniverseInput,
            output_model=ListUniverseOutput,
            impl=list_universe_impl,
        ),
        ToolEntry(
            name="expiries_for",
            description=(
                "List monthly OPTSTK expiry dates for ``symbol`` in "
                "the [from_date, to_date] range. Reads the local "
                "expiry-calendar cache; raises if the cache is cold "
                "for the requested window."
            ),
            input_model=ExpiriesForInput,
            output_model=ExpiriesForOutput,
            impl=expiries_for_impl,
        ),
        ToolEntry(
            name="list_strategies",
            description=(
                "Return registered strategies + their strike rules "
                "and Tier-B margin offsets. The v1 registry has 5 "
                "short-vol-focused strategies; ``backtest_one`` and "
                "``sweep_windows`` accept names from this list."
            ),
            input_model=ListStrategiesInput,
            output_model=ListStrategiesOutput,
            impl=list_strategies_impl,
        ),
    ]
