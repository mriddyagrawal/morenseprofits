"""MCP tool — heatmap (sub-arc 3.3, tool 4 of 4).

Returns the 2D (entry_offset_td × exit_offset_td) heatmap grid for one
``(strategy, symbol)`` slice, with min_n masking + caveats. Wraps the
existing analytics primitives:

  - ``pivot_window`` for median / mean ROI grids
  - ``pivot_cvar``   for the CVaR-5% tail-risk grid (uses value_col="cvar_5")
  - ``pivot_counts`` for the N-by-cell matrix used to mask thin cells

The output is a flat list of cells — easier for consumer Claudes to
reason about than a nested 2D structure. Each cell carries (entry,
exit, value, n, masked). Axes are also surfaced separately so a
consumer can reconstruct the 2D shape if needed.

Caveats fire under three conditions:
  1. Pre-pricing-arc parquet → shared phantom-fill caveat.
  2. Grid > 100 cells → MULTIPLE_COMPARISONS_CAVEAT (per the consultation's
     "any heatmap covering >100 cells surfaces a caveat about pick-the-
     best-cell selection bias" framing).
  3. Every cell masked at min_n → caveat naming the threshold.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from src.analytics.heatmap import pivot_counts, pivot_cvar, pivot_window
from src.analytics.rank import MULTIPLE_COMPARISONS_CAVEAT
from src.engine.results import ENGINE_VERSION, read_results, read_run_metadata
from src.mcp._models import (
    PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT,
    CaveatedResponse,
    ToolEntry,
)


# Cell-count threshold for the multiple-comparisons caveat. Matches the
# consultation's >100 framing — picking the best cell from a 45×16
# grid is selection bias that compounds the larger the grid.
MULTIPLE_COMPARISONS_CELL_THRESHOLD = 100


# Value columns the tool supports. The first three pass through to
# ``pivot_window`` with the matching ``value_col``; "cvar_5" routes to
# ``pivot_cvar`` instead (which computes the mean of the worst-5%
# per-trade ROI per cell rather than aggregating with median/mean).
SupportedValueCol = Literal[
    "roi_pct", "roi_pct_annualized", "net_pnl", "cvar_5",
]
SupportedAggFn = Literal["median", "mean"]


# ============================================================
# Models
# ============================================================

class HeatmapCell(BaseModel):
    entry_offset_td: int
    exit_offset_td: int
    value: float | None = Field(
        ...,
        description=(
            "Cell value per the requested ``value_col`` + ``agg_fn``. "
            "None when (a) the cell has no trades, OR (b) the cell was "
            "masked because n < min_n. Inspect ``masked`` to "
            "distinguish."
        ),
    )
    n: int = Field(
        ..., description="Trade count in the cell (pre-mask)."
    )
    masked: bool = Field(
        ...,
        description=(
            "True iff n < min_n. Masked cells have value=None for the "
            "consumer's safety — the underlying point estimate is too "
            "noisy to surface."
        ),
    )


class HeatmapInput(BaseModel):
    run_id: str
    strategy: str
    symbol: str
    value_col: SupportedValueCol = Field(
        default="roi_pct",
        description=(
            "Which per-trade value to aggregate. 'roi_pct' is the "
            "default (per-trade ROI; matches the dashboard). 'cvar_5' "
            "routes to pivot_cvar — the worst-5% tail-mean per cell, "
            "useful for short-vol tail-risk drill-down."
        ),
    )
    agg_fn: SupportedAggFn = Field(
        default="median",
        description=(
            "Aggregation function: 'median' (robust, default) or "
            "'mean' (sensitive to tail; pairs well with cvar_5 for the "
            "head-vs-tail story). Ignored when value_col='cvar_5' "
            "(CVaR is its own aggregation)."
        ),
    )
    min_n: int = Field(
        default=5,
        ge=1,
        description=(
            "Cells with n < min_n are masked. Default 5 matches the "
            "dashboard. Lower thresholds surface noisier point "
            "estimates; higher thresholds shrink the visible surface "
            "but tighten the inference."
        ),
    )


class HeatmapOutput(CaveatedResponse):
    run_id: str
    strategy: str
    symbol: str
    value_col: str
    agg_fn: str
    min_n: int
    cells: list[HeatmapCell] = Field(
        ...,
        description=(
            "Flat list of every cell in the (entry × exit) grid. "
            "Sorted (entry_offset_td DESC, exit_offset_td DESC) to "
            "match the dashboard's visual orientation."
        ),
    )
    entry_offsets: list[int] = Field(
        ..., description="Axis values (sorted DESC)."
    )
    exit_offsets: list[int] = Field(
        ..., description="Axis values (sorted DESC)."
    )
    n_cells_total: int
    n_cells_visible: int = Field(
        ..., description="n_cells_total minus the masked-at-min_n count."
    )


# ============================================================
# Helpers
# ============================================================

def _compute_value_grid(
    df: pd.DataFrame,
    *,
    strategy: str,
    symbol: str,
    value_col: str,
    agg_fn: str,
) -> pd.DataFrame:
    """Dispatch to pivot_cvar for the CVaR mode; pivot_window for the
    median/mean modes. Both return the same shape (entry × exit) with
    NaN for missing cells."""
    if value_col == "cvar_5":
        return pivot_cvar(df, strategy=strategy, symbol=symbol, alpha=0.05)
    return pivot_window(
        df, strategy=strategy, symbol=symbol,
        value_col=value_col, aggfunc=agg_fn,
    )


# ============================================================
# Tool impl
# ============================================================

def heatmap_impl(inp: HeatmapInput) -> HeatmapOutput:
    df = read_results(inp.run_id)
    grid = _compute_value_grid(
        df, strategy=inp.strategy, symbol=inp.symbol,
        value_col=inp.value_col, agg_fn=inp.agg_fn,
    )
    counts = pivot_counts(df, strategy=inp.strategy, symbol=inp.symbol)

    caveats: list[str] = []

    if grid.empty or counts.empty:
        # Nothing to render — empty cell list + explicit caveat.
        caveats.append(
            f"No (entry, exit) cells found for strategy={inp.strategy!r}, "
            f"symbol={inp.symbol!r} in run {inp.run_id!r}."
        )
        return HeatmapOutput(
            run_id=inp.run_id, strategy=inp.strategy, symbol=inp.symbol,
            value_col=inp.value_col, agg_fn=inp.agg_fn, min_n=inp.min_n,
            cells=[], entry_offsets=[], exit_offsets=[],
            n_cells_total=0, n_cells_visible=0,
            caveats=caveats,
        )

    entry_offsets = [int(v) for v in grid.index]
    exit_offsets = [int(v) for v in grid.columns]
    cells: list[HeatmapCell] = []
    n_cells_total = 0
    n_cells_visible = 0

    for entry in entry_offsets:
        for exit_ in exit_offsets:
            raw_value = grid.at[entry, exit_]
            # counts pivot has the same (entry, exit) shape as the
            # value grid (both come from the same _filter slice), so
            # the KeyError branch is defensive — fires only on a
            # degenerate case where the two pivots disagree.
            try:
                n = int(counts.at[entry, exit_])
            except KeyError:
                n = 0
            n_cells_total += 1
            masked = n < inp.min_n
            if masked or pd.isna(raw_value):
                value = None
            else:
                value = float(raw_value)
                n_cells_visible += 1
            cells.append(HeatmapCell(
                entry_offset_td=entry,
                exit_offset_td=exit_,
                value=value,
                n=n,
                masked=masked,
            ))

    # Pre-arc caveat.
    stamp = read_run_metadata(inp.run_id)
    if stamp.get("engine_version") != ENGINE_VERSION:
        caveats.append(PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT)

    # Multiple-comparisons caveat — large grids invite "pick-the-
    # best-cell" selection bias.
    if n_cells_total > MULTIPLE_COMPARISONS_CELL_THRESHOLD:
        caveats.append(MULTIPLE_COMPARISONS_CAVEAT)

    # All-masked caveat — tell the consumer the min_n threshold made
    # everything invisible.
    if n_cells_visible == 0 and n_cells_total > 0:
        caveats.append(
            f"Every cell has n < min_n={inp.min_n}; nothing is visible. "
            f"Lower min_n to surface noisier estimates, or pick a "
            f"different (strategy, symbol) with more coverage."
        )

    return HeatmapOutput(
        run_id=inp.run_id,
        strategy=inp.strategy,
        symbol=inp.symbol,
        value_col=inp.value_col,
        agg_fn=inp.agg_fn,
        min_n=inp.min_n,
        cells=cells,
        entry_offsets=entry_offsets,
        exit_offsets=exit_offsets,
        n_cells_total=n_cells_total,
        n_cells_visible=n_cells_visible,
        caveats=caveats,
    )


# ============================================================
# Registry export
# ============================================================

def register_heatmap_tools() -> list[ToolEntry]:
    return [
        ToolEntry(
            name="heatmap",
            description=(
                "Return the 2D (entry × exit) heatmap grid for one "
                "(strategy, symbol) slice. Supports median/mean ROI "
                "aggregation OR CVaR-5% tail-mean per cell via "
                "value_col='cvar_5'. Cells with n<min_n are masked "
                "(value=None). Caveats surface pre-pricing-arc bias, "
                "multiple-comparisons selection bias for grids >100 "
                "cells, and all-masked-at-min_n cases."
            ),
            input_model=HeatmapInput,
            output_model=HeatmapOutput,
            impl=heatmap_impl,
        ),
    ]
