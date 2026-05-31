"""MCP tool — backtest_one (sub-arc 3.4, tool 1 of 2).

Replays a single (strategy, symbol, expiry, entry_date, exit_date)
trade against the local cache. Returns the full trade outcome plus
per-leg breakdown with VWAP-vs-close fill-source classification — the
same diagnostic the dashboard's CSV-export surfaces.

Read-only contract: every loader called downstream (spot, options,
bhavcopy) runs with ``offline=True``. A cache miss raises
OfflineCacheMiss which the SDK surfaces as a tool error. The MCP
layer NEVER hits NSE.

Caveats:
  - Pre-pricing-arc caveat is NOT emitted here because backtest_one
    runs the CURRENT engine (with the gate + VWAP + units assertion).
    Whatever cache the contract files have, the engine's behavior is
    post-arc. If the operator wants the pre-arc baseline they should
    query a pre-arc sweep parquet via query_sweep / cell_summary
    instead.
  - Empty cell: if the strategy / loader can't price the trade (e.g.
    IlliquidLegError, NoLiquidStrikeError, MissingDataError), the
    error message is surfaced as ``gate_status`` and the trade-level
    outcome fields are None. Caveats name the failure mode.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from src.data.errors import MissingDataError, OfflineCacheMiss
from src.data.spot_loader import load_spot
from src.engine.pnl import classify_fill_source, price_trade
from src.mcp._models import CaveatedResponse, ToolEntry
from src.strategies.registry import STRATEGIES


# ============================================================
# Models
# ============================================================

class LegBreakdown(BaseModel):
    option_type: str
    strike: float
    side: str
    qty_lots: int
    lot_size: int
    entry_px: float | None = Field(
        ...,
        description=(
            "Raw fill price the engine chose for this leg's entry "
            "(VWAP when available, else close). Pre-slippage."
        ),
    )
    exit_px: float | None
    entry_px_realized: float | None = Field(
        ..., description="entry_px × (1 ∓ slippage_pct). Post-slippage."
    )
    exit_px_realized: float | None
    entry_volume: int | None
    exit_volume: int | None
    entry_oi: int | None
    exit_oi: int | None
    entry_turnover: float | None = Field(
        ...,
        description=(
            "Day's traded value in LAKHS of rupees (NSE convention). "
            "Used to compute VWAP via turnover × 100_000 / volume."
        ),
    )
    exit_turnover: float | None
    entry_fill_source: str = Field(
        ...,
        description=(
            "'vwap' if entry_px matches turnover × 100_000 / volume; "
            "'close' if VWAP path unavailable OR engine rejected it "
            "via the units-sanity band; 'unknown' if entry_px is "
            "missing."
        ),
    )
    exit_fill_source: str
    gross_pnl_leg: float


class BacktestOneInput(BaseModel):
    strategy: str = Field(..., description="Name from list_strategies output.")
    symbol: str
    expiry: date
    entry_date: date
    exit_date: date
    params: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional strategy-specific overrides (e.g. "
            "{'strike_offset_pct': 0.03} for a strangle). None uses "
            "the strategy's default strike rule from list_strategies."
        ),
    )


class BacktestOneOutput(CaveatedResponse):
    strategy: str
    symbol: str
    expiry: date
    entry_date: date
    exit_date: date
    spot_at_entry: float | None = Field(
        ...,
        description=(
            "Underlying close on entry_date. None if the spot loader "
            "couldn't find a value for that day."
        ),
    )
    gate_status: str = Field(
        ...,
        description=(
            "'priced' — trade priced cleanly. Otherwise the typed "
            "error class name ('IlliquidLegError', "
            "'NoLiquidStrikeError', 'MissingDataError', "
            "'OfflineCacheMiss', ...) so the consumer Claude can "
            "branch on the failure mode."
        ),
    )
    gate_detail: str | None = Field(
        ..., description="Human-readable error message when gate_status != 'priced'."
    )
    gross_pnl: float | None
    costs: float | None
    net_pnl: float | None
    margin_at_entry: float | None
    roi_pct: float | None
    hold_trading_days: int | None
    legs: list[LegBreakdown]


# ============================================================
# Helpers
# ============================================================

def _classify_fill_source(
    entry_px: float | None,
    volume: int | None,
    turnover: float | None,
    strike: float | None = None,
) -> str:
    """Backward-compat shim around the centralized
    ``src.engine.pnl.classify_fill_source``. Kept under the
    underscored name so the test module can import it as before.
    ``strike`` is required to recover the strike-corrected VWAP; legacy
    callers omitting it degrade to 'close' (honest) rather than
    mis-classifying as 'vwap'. New callers should import the public
    name from src.engine.pnl directly."""
    return classify_fill_source(entry_px, volume, turnover, strike=strike)


def _resolve_spot(symbol: str, entry_date: date) -> float | None:
    """Return the underlying close on entry_date, or None if the cache
    doesn't have it. Uses offline=True so a cache miss raises
    OfflineCacheMiss (caller catches)."""
    df = load_spot(symbol, entry_date, entry_date, offline=True)
    if df.empty:
        return None
    return float(df.iloc[0]["close"])


def _extract_legs(legs_json: str) -> list[LegBreakdown]:
    """Parse the trade's legs_json field into typed LegBreakdown
    objects with the fill-source classification populated."""
    try:
        raw_legs = json.loads(legs_json)
    except (TypeError, json.JSONDecodeError):
        return []
    out: list[LegBreakdown] = []
    for leg in raw_legs:
        out.append(LegBreakdown(
            option_type=str(leg.get("option_type", "")),
            strike=float(leg.get("strike", 0.0)),
            side=str(leg.get("side", "")),
            qty_lots=int(leg.get("qty_lots", 0)),
            lot_size=int(leg.get("lot_size", 0)),
            entry_px=leg.get("entry_px"),
            exit_px=leg.get("exit_px"),
            entry_px_realized=leg.get("entry_px_realized"),
            exit_px_realized=leg.get("exit_px_realized"),
            entry_volume=leg.get("entry_volume"),
            exit_volume=leg.get("exit_volume"),
            entry_oi=leg.get("entry_oi"),
            exit_oi=leg.get("exit_oi"),
            entry_turnover=leg.get("entry_turnover"),
            exit_turnover=leg.get("exit_turnover"),
            entry_fill_source=_classify_fill_source(
                leg.get("entry_px"),
                leg.get("entry_volume"),
                leg.get("entry_turnover"),
                strike=leg.get("strike"),
            ),
            exit_fill_source=_classify_fill_source(
                leg.get("exit_px"),
                leg.get("exit_volume"),
                leg.get("exit_turnover"),
                strike=leg.get("strike"),
            ),
            gross_pnl_leg=float(leg.get("gross_pnl", 0.0)),
        ))
    return out


def _empty_output(
    inp: BacktestOneInput,
    *,
    spot_at_entry: float | None,
    gate_status: str,
    gate_detail: str,
    caveats: list[str],
) -> BacktestOneOutput:
    return BacktestOneOutput(
        strategy=inp.strategy,
        symbol=inp.symbol,
        expiry=inp.expiry,
        entry_date=inp.entry_date,
        exit_date=inp.exit_date,
        spot_at_entry=spot_at_entry,
        gate_status=gate_status,
        gate_detail=gate_detail,
        gross_pnl=None,
        costs=None,
        net_pnl=None,
        margin_at_entry=None,
        roi_pct=None,
        hold_trading_days=None,
        legs=[],
        caveats=caveats,
    )


# ============================================================
# Tool impl
# ============================================================

def backtest_one_impl(inp: BacktestOneInput) -> BacktestOneOutput:
    if inp.strategy not in STRATEGIES:
        available = sorted(STRATEGIES.keys())
        raise ValueError(
            f"strategy {inp.strategy!r} not registered. Available: {available}"
        )
    strat = STRATEGIES[inp.strategy]

    # 1. Resolve spot for entry_date (cache-only).
    try:
        spot_at_entry = _resolve_spot(inp.symbol.upper(), inp.entry_date)
    except OfflineCacheMiss as e:
        return _empty_output(
            inp, spot_at_entry=None,
            gate_status="OfflineCacheMiss",
            gate_detail=str(e),
            caveats=[
                "Spot cache missing for entry_date. Run a prefetch for "
                "this symbol+year before retrying."
            ],
        )
    if spot_at_entry is None:
        return _empty_output(
            inp, spot_at_entry=None,
            gate_status="MissingSpot",
            gate_detail=(
                f"No spot row for {inp.symbol.upper()} on {inp.entry_date}; "
                f"entry_date may not be a trading day."
            ),
            caveats=[
                f"{inp.entry_date} returned no spot row. Verify it's a "
                f"trading day (not a weekend or NSE holiday)."
            ],
        )

    # 2. Generate trade(s) via the strategy.
    try:
        trades = strat.generate_trades(
            inp.symbol.upper(), inp.expiry, inp.entry_date, inp.exit_date,
            spot_at_entry, inp.params or {},
        )
    except MissingDataError as e:
        return _empty_output(
            inp, spot_at_entry=spot_at_entry,
            gate_status=type(e).__name__, gate_detail=str(e),
            caveats=[f"Strategy strike picking failed: {type(e).__name__}"],
        )
    except Exception as e:
        return _empty_output(
            inp, spot_at_entry=spot_at_entry,
            gate_status=type(e).__name__, gate_detail=str(e),
            caveats=[f"Strategy raised unexpectedly: {type(e).__name__}"],
        )

    if not trades:
        return _empty_output(
            inp, spot_at_entry=spot_at_entry,
            gate_status="NoTradesGenerated",
            gate_detail="strategy.generate_trades returned an empty list",
            caveats=[],
        )
    if len(trades) > 1:
        return _empty_output(
            inp, spot_at_entry=spot_at_entry,
            gate_status="MultipleTradesNotSupported",
            gate_detail=(
                f"strategy.generate_trades returned {len(trades)} trades; "
                f"backtest_one only handles single-trade strategies."
            ),
            caveats=[
                "Multi-trade strategies aren't supported in v1; use the "
                "sweep + cell_summary tools to inspect their outputs."
            ],
        )

    # 3. Price the single trade with offline=True so any cache miss
    # raises OfflineCacheMiss rather than silently hitting NSE.
    trade = trades[0]
    try:
        result = price_trade(trade, offline=True)
    except (MissingDataError, OfflineCacheMiss) as e:
        return _empty_output(
            inp, spot_at_entry=spot_at_entry,
            gate_status=type(e).__name__, gate_detail=str(e),
            caveats=[f"Pricing failed: {type(e).__name__}: {e}"],
        )

    legs = _extract_legs(result.get("legs_json", "[]"))

    return BacktestOneOutput(
        strategy=inp.strategy,
        symbol=inp.symbol.upper(),
        expiry=inp.expiry,
        entry_date=inp.entry_date,
        exit_date=inp.exit_date,
        spot_at_entry=spot_at_entry,
        gate_status="priced",
        gate_detail=None,
        gross_pnl=float(result["gross_pnl"]),
        costs=float(result["costs"]),
        net_pnl=float(result["net_pnl"]),
        margin_at_entry=float(result["margin_at_entry"]),
        roi_pct=(
            float(result["roi_pct"]) if result.get("roi_pct") is not None
            else None
        ),
        hold_trading_days=int(result["hold_trading_days"]),
        legs=legs,
        caveats=[],
    )


# ============================================================
# Registry export
# ============================================================

def register_backtest_one_tools() -> list[ToolEntry]:
    return [
        ToolEntry(
            name="backtest_one",
            description=(
                "Replay a single trade (strategy, symbol, expiry, "
                "entry_date, exit_date) against the local cache. "
                "Returns full per-leg breakdown including VWAP-vs-"
                "close fill-source classification + costs + margin + "
                "ROI. Cache-only (no NSE network calls); failures "
                "surface as ``gate_status`` rather than exceptions."
            ),
            input_model=BacktestOneInput,
            output_model=BacktestOneOutput,
            impl=backtest_one_impl,
        ),
    ]
