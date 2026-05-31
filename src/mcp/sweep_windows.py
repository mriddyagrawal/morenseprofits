"""MCP tool — sweep_windows (sub-arc 3.4, tool 2 of 2).

Replays a small grid of (entry, exit) cells across multiple expiries
against the local cache and returns aggregate stats per cell. Closes
the gap between ``backtest_one`` (single trade) and the dashboard's
heatmap (full sweep parquet) — useful when an operator wants
"replay just these few cells" without writing a sweep config.

Hard cap: ``MAX_GRID_TRADES = 500`` total trades per call. Wider
ranges than that should use the wide-sweep script + then query via
``cell_summary`` / ``heatmap``.

Read-only / cache-only contract: every leg pricing call uses
``offline=True``. Failures land in a per-cell ``skip_summary`` dict
keyed by gate_status; the consumer can read the gate breakdown to
distinguish "cell has no trades because grid empty" from "cell
skipped because every trade was illiquid".

Pre-pricing-arc caveat NOT emitted here. Same as ``backtest_one``:
this tool runs the CURRENT engine against the contract cache, so the
gate + VWAP + units assertion are always in force regardless of when
the option parquets themselves were cached. Operators who need a
pre-arc baseline (the phantom-fill-bias era of pre-94d535f data)
should query a pre-arc ``sweep_*.parquet`` via ``cell_summary`` /
``heatmap``; THOSE tools emit the phantom-fill caveat when the
queried parquet lacks the engine_version stamp.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from src.analytics.cell_stats import (
    DEFAULT_CVAR_ALPHA,
    CellStatsBlock,
    compute_cell_stats,
    empty_cell_stats_block,
)
from src.data.errors import MissingDataError, OfflineCacheMiss
from src.data.expiry_calendar import monthly_expiries
from src.data.trading_calendar import offset_trading_days
from src.mcp._models import CaveatedResponse, ToolEntry
from src.mcp.backtest_one import BacktestOneInput, backtest_one_impl


# Total-trade cap. With 5 strategies × 50 symbols × 25 expiries ×
# 45 entry × 16 exit ≈ 2.25M cells in a wide sweep, we explicitly
# don't want this tool to BE the wide sweep. 500 trades = ~16
# cells × 25 expiries each, or ~50 cells × 10 expiries. Reasonable
# upper bound for an interactive Claude-driven research session.
MAX_GRID_TRADES = 500

# Backward-compat alias for the test module's CVAR_ALPHA import.
CVAR_ALPHA = DEFAULT_CVAR_ALPHA


# ============================================================
# Models
# ============================================================

# Backward-compat alias: shared per-cell stat block centralized in
# src.analytics.cell_stats.CellStatsBlock. CellWindowStats stays as
# the name surfaced by this module's API so test imports + downstream
# consumers keep resolving.
CellWindowStats = CellStatsBlock


class CellWindowResult(BaseModel):
    entry_offset_td: int
    exit_offset_td: int
    stats: CellWindowStats
    skip_summary: dict[str, int] = Field(
        ...,
        description=(
            "Counts of gate_status values across the cell's attempted "
            "trades. 'priced' → succeeded; other keys are typed error "
            "names ('IlliquidLegError', 'OfflineCacheMiss', ...). "
            "Empty cells with all-skips surface here rather than as "
            "silent zeros."
        ),
    )


class SweepWindowsInput(BaseModel):
    strategy: str
    symbol: str
    expiry_from: date = Field(
        ..., description="Inclusive lower bound for expiry sampling."
    )
    expiry_to: date = Field(
        ..., description="Inclusive upper bound for expiry sampling."
    )
    entry_offset_min: int = Field(
        ..., ge=0, description="Inclusive lower bound for entry offset (trading days)."
    )
    entry_offset_max: int = Field(
        ..., ge=0, description="Inclusive upper bound for entry offset."
    )
    exit_offset_min: int = Field(
        ..., ge=0, description="Inclusive lower bound for exit offset."
    )
    exit_offset_max: int = Field(
        ..., ge=0, description="Inclusive upper bound for exit offset."
    )
    params: dict[str, Any] | None = None


class SweepWindowsOutput(CaveatedResponse):
    strategy: str
    symbol: str
    expiries_used: list[date]
    n_cells: int
    cells: list[CellWindowResult]
    total_trades_attempted: int
    total_trades_priced: int


# ============================================================
# Helpers
# ============================================================
#
# All three local helpers below (_bottom_alpha_mean, _empty_stats,
# _aggregate_priced_trades) now delegate to the centralized
# src.analytics.cell_stats. The shims keep the underscored names so
# the test module's existing imports keep resolving, while the real
# logic lives in one place per the chore(p8.cell_stats.centralize)
# refactor.


def _empty_stats() -> CellWindowStats:
    return empty_cell_stats_block()


def _aggregate_priced_trades(priced: list[tuple[float, float]]) -> CellWindowStats:
    """Compute the per-cell stat block from a list of (roi_pct, net_pnl)
    tuples. Empty input → empty stats."""
    if not priced:
        return empty_cell_stats_block()
    rois = np.array([p[0] for p in priced], dtype=float)
    pnls = np.array([p[1] for p in priced], dtype=float)
    return compute_cell_stats(rois=rois, pnls=pnls, cvar_alpha=CVAR_ALPHA)


# ============================================================
# Tool impl
# ============================================================

def sweep_windows_impl(inp: SweepWindowsInput) -> SweepWindowsOutput:
    if inp.expiry_from > inp.expiry_to:
        raise ValueError(
            f"expiry_from {inp.expiry_from} > expiry_to {inp.expiry_to}"
        )
    if inp.entry_offset_min > inp.entry_offset_max:
        raise ValueError(
            f"entry_offset_min ({inp.entry_offset_min}) > "
            f"entry_offset_max ({inp.entry_offset_max})"
        )
    if inp.exit_offset_min > inp.exit_offset_max:
        raise ValueError(
            f"exit_offset_min ({inp.exit_offset_min}) > "
            f"exit_offset_max ({inp.exit_offset_max})"
        )

    # 1. Resolve expiries via the cached calendar (offline).
    try:
        expiries = monthly_expiries(
            inp.symbol, inp.expiry_from, inp.expiry_to, offline=True,
        )
    except OfflineCacheMiss as e:
        return SweepWindowsOutput(
            strategy=inp.strategy, symbol=inp.symbol.upper(),
            expiries_used=[], n_cells=0, cells=[],
            total_trades_attempted=0, total_trades_priced=0,
            caveats=[
                f"Expiry calendar cache missing for {inp.symbol}: {e}. "
                f"Run prefetch for the symbol before retrying."
            ],
        )

    # 2. Build the (entry, exit) grid; cap the total trade count.
    entry_offsets = list(range(inp.entry_offset_min, inp.entry_offset_max + 1))
    exit_offsets = list(range(inp.exit_offset_min, inp.exit_offset_max + 1))
    # Only valid pairs are entry > exit (otherwise the strategy
    # enters AFTER it exits).
    valid_pairs = [
        (e, x) for e in entry_offsets for x in exit_offsets if e > x
    ]
    n_planned = len(valid_pairs) * len(expiries)

    caveats: list[str] = []
    if n_planned > MAX_GRID_TRADES:
        caveats.append(
            f"Grid would plan {n_planned} trades; capped at "
            f"{MAX_GRID_TRADES}. Tighten the ranges or use the "
            f"wide-sweep script (scripts/p7_wide_sweep.py) + query "
            f"via cell_summary / heatmap for full-grid analysis."
        )
        # Cap by taking the densest cells first (highest entry / lowest
        # exit). For our purposes, just truncate the pairs list.
        # Calculate how many full cells we can afford.
        max_cells = max(1, MAX_GRID_TRADES // max(len(expiries), 1))
        valid_pairs = valid_pairs[:max_cells]

    # 3. Loop: for each (entry, exit) cell × each expiry, call
    # backtest_one_impl. Aggregate per cell.
    cells: list[CellWindowResult] = []
    total_attempted = 0
    total_priced = 0

    for entry_off, exit_off in valid_pairs:
        priced_trades: list[tuple[float, float]] = []  # (roi_pct, net_pnl)
        skip_counts: dict[str, int] = {}
        for expiry in expiries:
            # Resolve entry / exit dates from trading-day offsets.
            try:
                entry_date = offset_trading_days(
                    expiry, entry_off, offline=True,
                )
                exit_date = offset_trading_days(
                    expiry, exit_off, offline=True,
                )
            except (ValueError, OfflineCacheMiss) as e:
                skip_counts["DateResolution"] = (
                    skip_counts.get("DateResolution", 0) + 1
                )
                total_attempted += 1
                continue
            if entry_date >= exit_date:
                # Defensive: should already be filtered by entry > exit,
                # but trading-day offsets in edge cases can produce
                # entry == exit (e.g. both on the last trading day).
                skip_counts["InvalidWindow"] = (
                    skip_counts.get("InvalidWindow", 0) + 1
                )
                total_attempted += 1
                continue

            total_attempted += 1
            bt_in = BacktestOneInput(
                strategy=inp.strategy, symbol=inp.symbol,
                expiry=expiry, entry_date=entry_date, exit_date=exit_date,
                params=inp.params,
            )
            try:
                bt_out = backtest_one_impl(bt_in)
            except Exception as e:
                skip_counts[type(e).__name__] = (
                    skip_counts.get(type(e).__name__, 0) + 1
                )
                continue

            if bt_out.gate_status == "priced":
                roi = bt_out.roi_pct if bt_out.roi_pct is not None else 0.0
                pnl = bt_out.net_pnl if bt_out.net_pnl is not None else 0.0
                priced_trades.append((float(roi), float(pnl)))
                total_priced += 1
                skip_counts["priced"] = skip_counts.get("priced", 0) + 1
            else:
                skip_counts[bt_out.gate_status] = (
                    skip_counts.get(bt_out.gate_status, 0) + 1
                )

        cells.append(CellWindowResult(
            entry_offset_td=entry_off,
            exit_offset_td=exit_off,
            stats=_aggregate_priced_trades(priced_trades),
            skip_summary=skip_counts,
        ))

    if not expiries:
        caveats.append(
            f"No expiries found for {inp.symbol} in "
            f"[{inp.expiry_from}, {inp.expiry_to}]."
        )

    return SweepWindowsOutput(
        strategy=inp.strategy,
        symbol=inp.symbol.upper(),
        expiries_used=expiries,
        n_cells=len(cells),
        cells=cells,
        total_trades_attempted=total_attempted,
        total_trades_priced=total_priced,
        caveats=caveats,
    )


# ============================================================
# Registry export
# ============================================================

def register_sweep_windows_tools() -> list[ToolEntry]:
    return [
        ToolEntry(
            name="sweep_windows",
            description=(
                "Replay a small (entry × exit) grid across N expiries "
                "against the local cache. Returns one CellWindowResult "
                "per (entry, exit) pair with stats + per-cell skip "
                f"breakdown. Hard-capped at {MAX_GRID_TRADES} total "
                "trades — wider grids should use the wide-sweep "
                "script + query via cell_summary / heatmap."
            ),
            input_model=SweepWindowsInput,
            output_model=SweepWindowsOutput,
            impl=sweep_windows_impl,
        ),
    ]
