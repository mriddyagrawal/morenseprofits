"""MCP tools — time-series (3 tools, sub-arc 3.2).

  - get_spot_series(symbol, from, to)           : daily spot OHLCV
  - get_option_series(symbol, expiry, strike,   : per-contract OHLC + telemetry
        option_type, from?, to?)
  - get_options_chain(symbol, on_date, expiry?) : bhavcopy snapshot

All three respect the read-only contract: force ``offline=True`` on
every underlying loader, so a cache miss raises OfflineCacheMiss
(surfaced to the consumer as a tool error) rather than silently
hitting NSE.

Caveats philosophy here: time-series tools return raw rows, not
aggregates, so the caveats are typically empty. The ONE exception:
``get_option_series`` flags pre-pricing-arc parquets when the
``turnover`` column is absent or universally NaN — consumers can't
reconstruct VWAP without it and must fall back to ``close`` for
fill-price reasoning. That's the load-bearing caveat for this
sub-arc.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from src.data.bhavcopy_fo_loader import load_bhavcopy_fo
from src.data.options_loader import load_option
from src.data.spot_loader import load_spot
from src.mcp._models import CaveatedResponse, ToolEntry


# Hard cap on returned-row count per tool call. Keeps a runaway
# multi-year query from blowing the MCP transport / Claude context.
# Operator can paginate via narrower from_date/to_date windows.
MAX_ROWS_PER_RESPONSE = 10_000


# ============================================================
# get_spot_series
# ============================================================

class SpotRow(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int | None = None


class GetSpotSeriesInput(BaseModel):
    symbol: str = Field(..., description="NSE symbol; uppercased internally.")
    from_date: date = Field(..., description="Inclusive lower bound.")
    to_date: date = Field(..., description="Inclusive upper bound.")


class GetSpotSeriesOutput(CaveatedResponse):
    symbol: str
    rows: list[SpotRow]
    n_rows: int = Field(
        ..., description="len(rows). Pre-computed so the consumer doesn't have to count."
    )


def _truncate_rows(rows: list[dict], n_truncated: int = 0) -> tuple[list[dict], list[str]]:
    """Cap rows at MAX_ROWS_PER_RESPONSE; return (truncated_rows, caveats).
    Adds an explicit caveat when truncation fires so consumer Claudes
    don't silently get a partial frame and treat it as complete."""
    caveats: list[str] = []
    if len(rows) > MAX_ROWS_PER_RESPONSE:
        n_dropped = len(rows) - MAX_ROWS_PER_RESPONSE
        rows = rows[:MAX_ROWS_PER_RESPONSE]
        caveats.append(
            f"Response truncated to {MAX_ROWS_PER_RESPONSE} rows; "
            f"{n_dropped} additional rows dropped. Narrow the date "
            f"window or filter to retrieve the rest."
        )
    return rows, caveats


def get_spot_series_impl(inp: GetSpotSeriesInput) -> GetSpotSeriesOutput:
    df = load_spot(inp.symbol, inp.from_date, inp.to_date, offline=True)
    # Normalize to list[dict] for Pydantic-friendly construction.
    df_records = df.to_dict(orient="records")
    rows_raw: list[dict] = []
    for r in df_records:
        rows_raw.append({
            "date": r["date"].date() if isinstance(r.get("date"), pd.Timestamp) else r["date"],
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": int(r["volume"]) if pd.notna(r.get("volume")) else None,
        })
    rows_capped, caveats = _truncate_rows(rows_raw)
    return GetSpotSeriesOutput(
        symbol=inp.symbol.upper(),
        rows=[SpotRow(**r) for r in rows_capped],
        n_rows=len(rows_capped),
        caveats=caveats,
    )


# ============================================================
# get_option_series
# ============================================================

class OptionRow(BaseModel):
    date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = Field(
        default=None,
        description=(
            "Day's closing trade price. None on settlement-only rows "
            "where NSE publishes settle_price but no close trade "
            "happened (rare; typically zero-volume contracts near "
            "expiry). Pre-fix(661b1ff #1) this was required and "
            "raised on NaN."
        ),
    )
    ltp: float | None = None
    settle_price: float | None = None
    lot_size: int
    volume: int
    oi: int | None = None
    turnover: float | None = Field(
        default=None,
        description=(
            "Total traded value in rupees (post-F1 parser "
            "normalization — see pnl.TURNOVER_SCALE_FACTOR comment "
            "and LOGIC_REVIEW.md F1; pre-F1 this was carried in lakhs "
            "and the engine multiplied by 1e5). Combined with "
            "``volume`` yields per-row notional-per-share: "
            "``turnover / volume``. NaN on legacy parquets "
            "cached before the p7.pricing_arc — the response carries "
            "a caveat in that case."
        ),
    )


class GetOptionSeriesInput(BaseModel):
    symbol: str
    expiry: date
    strike: float
    option_type: Literal["CE", "PE"]
    from_date: date | None = Field(
        default=None,
        description=(
            "Inclusive lower bound. If None, defaults to expiry - 120 "
            "days (the contract's typical full lifetime)."
        ),
    )
    to_date: date | None = Field(
        default=None,
        description=(
            "Inclusive upper bound. If None, defaults to expiry."
        ),
    )


class GetOptionSeriesOutput(CaveatedResponse):
    symbol: str
    expiry: date
    strike: float
    option_type: str
    rows: list[OptionRow]
    n_rows: int


def get_option_series_impl(inp: GetOptionSeriesInput) -> GetOptionSeriesOutput:
    from datetime import timedelta
    f = inp.from_date or (inp.expiry - timedelta(days=120))
    t = inp.to_date or inp.expiry
    df = load_option(
        inp.symbol, inp.expiry, inp.strike, inp.option_type,
        f, t, offline=True,
    )
    records = df.to_dict(orient="records")
    rows: list[dict] = []
    turnover_all_nan = True
    turnover_present = "turnover" in df.columns
    for r in records:
        turnover_val = None
        if turnover_present and pd.notna(r.get("turnover")):
            turnover_val = float(r["turnover"])
            turnover_all_nan = False
        rows.append({
            "date": r["date"].date() if isinstance(r.get("date"), pd.Timestamp) else r["date"],
            "open": float(r["open"]) if pd.notna(r.get("open")) else None,
            "high": float(r["high"]) if pd.notna(r.get("high")) else None,
            "low": float(r["low"]) if pd.notna(r.get("low")) else None,
            "close": float(r["close"]) if pd.notna(r.get("close")) else None,
            "ltp": float(r["ltp"]) if pd.notna(r.get("ltp")) else None,
            "settle_price": float(r["settle_price"]) if pd.notna(r.get("settle_price")) else None,
            "lot_size": int(r["lot_size"]),
            "volume": int(r["volume"]),
            "oi": int(r["oi"]) if pd.notna(r.get("oi")) else None,
            "turnover": turnover_val,
        })
    capped, caveats = _truncate_rows(rows)
    if not turnover_present or (turnover_all_nan and len(rows) > 0):
        caveats.append(
            "Contract was cached before the p7.pricing_arc turnover "
            "ingest landed; ``turnover`` is unavailable so VWAP cannot "
            "be reconstructed. Engine fill-price for any cell touching "
            "this contract falls back to ``close``."
        )
    return GetOptionSeriesOutput(
        symbol=inp.symbol.upper(),
        expiry=inp.expiry,
        strike=inp.strike,
        option_type=inp.option_type,
        rows=[OptionRow(**r) for r in capped],
        n_rows=len(capped),
        caveats=caveats,
    )


# ============================================================
# get_options_chain
# ============================================================

class ChainRow(BaseModel):
    strike: float
    option_type: str
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = Field(
        default=None,
        description=(
            "Day's closing trade price for this strike. None when the "
            "bhavcopy row has no close (rare; zero-volume strikes that "
            "NSE publishes for completeness)."
        ),
    )
    settle_price: float | None = None
    contracts: int | None = Field(
        default=None,
        description="Number of contracts traded that day (bhavcopy field).",
    )
    oi: int | None = None


class GetOptionsChainInput(BaseModel):
    symbol: str
    on_date: date = Field(..., description="Trading date for the snapshot.")
    expiry: date | None = Field(
        default=None,
        description=(
            "Optional filter: only return rows for this contract "
            "expiry. If None, returns all expiries traded on "
            "``on_date``."
        ),
    )


class GetOptionsChainOutput(CaveatedResponse):
    symbol: str
    on_date: date
    expiry_filter: date | None
    rows: list[ChainRow]
    n_rows: int


def get_options_chain_impl(inp: GetOptionsChainInput) -> GetOptionsChainOutput:
    bc = load_bhavcopy_fo(inp.on_date, offline=True)
    mask = (
        (bc["symbol"] == inp.symbol.upper())
        & (bc["instrument"] == "OPTSTK")
        & (bc["option_type"].isin(["CE", "PE"]))
    )
    if inp.expiry is not None:
        mask = mask & (bc["expiry"] == pd.Timestamp(inp.expiry))
    sub = bc.loc[mask].sort_values(["strike", "option_type"])
    rows: list[dict] = []
    for _, r in sub.iterrows():
        rows.append({
            "strike": float(r["strike"]),
            "option_type": str(r["option_type"]),
            "open": float(r["open"]) if pd.notna(r.get("open")) else None,
            "high": float(r["high"]) if pd.notna(r.get("high")) else None,
            "low": float(r["low"]) if pd.notna(r.get("low")) else None,
            "close": float(r["close"]) if pd.notna(r.get("close")) else None,
            "settle_price": float(r["settle_price"]) if pd.notna(r.get("settle_price")) else None,
            "contracts": int(r["contracts"]) if pd.notna(r.get("contracts")) else None,
            "oi": int(r["oi"]) if pd.notna(r.get("oi")) else None,
        })
    # Truncate to MAX_ROWS_PER_RESPONSE for consistency with the two
    # other tools in this sub-arc (fix(661b1ff #2): chain previously
    # had no cap — a heavy symbol's full multi-expiry chain could
    # blow past the consumer Claude's context budget).
    capped, caveats = _truncate_rows(rows)
    return GetOptionsChainOutput(
        symbol=inp.symbol.upper(),
        on_date=inp.on_date,
        expiry_filter=inp.expiry,
        rows=[ChainRow(**r) for r in capped],
        n_rows=len(capped),
        caveats=caveats,
    )


# ============================================================
# Registry export
# ============================================================

def register_spot_options_tools() -> list[ToolEntry]:
    """Return the 3 tool entries for the time-series sub-arc."""
    return [
        ToolEntry(
            name="get_spot_series",
            description=(
                "Return daily spot OHLCV for ``symbol`` in the "
                "[from_date, to_date] window from the local cache. "
                "Reads parquet directly; never hits NSE. Capped at "
                f"{MAX_ROWS_PER_RESPONSE} rows."
            ),
            input_model=GetSpotSeriesInput,
            output_model=GetSpotSeriesOutput,
            impl=get_spot_series_impl,
        ),
        ToolEntry(
            name="get_option_series",
            description=(
                "Return per-contract OHLC + lot_size + volume + oi + "
                "turnover for an option contract. ``from_date`` and "
                "``to_date`` default to (expiry - 120 days) and expiry "
                "respectively when omitted. Carries an explicit caveat "
                "when ``turnover`` is unavailable (pre-pricing-arc "
                "cache) so consumers can't accidentally compute VWAP "
                "from incomplete data."
            ),
            input_model=GetOptionSeriesInput,
            output_model=GetOptionSeriesOutput,
            impl=get_option_series_impl,
        ),
        ToolEntry(
            name="get_options_chain",
            description=(
                "Return the OPTSTK rows from a bhavcopy snapshot for "
                "``symbol`` on ``on_date``, optionally filtered to a "
                "single ``expiry``. One row per (strike, CE/PE)."
            ),
            input_model=GetOptionsChainInput,
            output_model=GetOptionsChainOutput,
            impl=get_options_chain_impl,
        ),
    ]
