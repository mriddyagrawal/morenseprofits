"""MCP tool — compare_cells (sub-arc 3.6, tool 1 of 2).

Side-by-side analysis of 2-4 cells in one sweep run. Returns each
cell's stats + the raw delta vs the first (baseline) cell + each
cell's ROI distribution (for the consumer Claude to construct its
own distribution overlay).

LOAD-BEARING constraint: NO p-values, NO "statistically significant"
language, NO statistical-test machinery anywhere in the response.

Why this constraint exists
--------------------------

With N ≈ 24 per-trade observations per cell, ~5% of identical-
distribution pairs return p<0.05 by chance. An analyst Claude
calling compare_cells across hundreds of pair-comparisons in a
session would see dozens of false-positive "significant differences"
that compound into noise-disguised-as-signal.

Same constraint pattern as the dashboard's Compare-cells mode (see
tests/test_web_e2e.py::test_compare_cells_renders_no_p_values). Both
MCP and dashboard re-emit ``MULTIPLE_COMPARISONS_CAVEAT`` verbatim
from ``src.analytics.rank`` so the consumer-facing surface is the
same string in both places.

Enforcement
-----------

A behavior test in tests/test_mcp_compare_cells.py scans the
serialized JSON output for banned regex patterns
(``\\b(?:p[-_ ]?value|statistically significant|p\\s*[<>=]\\s*0?\\.\\d+|
t-test|chi-square|mann-whitney|kolmogorov)\\b``). Any future
contributor accidentally adding statistical-test machinery to this
tool fails that test.
"""
from __future__ import annotations

import json
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
from src.analytics.rank import MULTIPLE_COMPARISONS_CAVEAT
from src.engine.results import ENGINE_VERSION, read_results, read_run_metadata
from src.mcp._models import (
    PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT,
    CaveatedResponse,
    ToolEntry,
)


# Hard cap on ROI distribution rows returned per cell. The full per-
# trade ROI list lets the consumer Claude build its own distribution
# overlay; capping at 200 keeps the JSON payload reasonable even for
# wide-sweep cells with 50+ expiries.
MAX_DISTRIBUTION_ROWS = 200


# Standard caveat surfacing the no-p-values constraint. Hardcoded
# (not loaded from a constant) because the exact phrasing here is
# part of the contract — every consumer Claude reads this verbatim.
NO_P_VALUES_CAVEAT = (
    "Raw deltas only. With N ≈ 24 per-trade observations per cell, "
    "treat differences as directional signals, NOT as definitive "
    "comparisons. No significance-test machinery; sample sizes are "
    "too small for that to be honest."
)


# ============================================================
# Models
# ============================================================

class CompareCellKey(BaseModel):
    strategy: str
    symbol: str
    entry_offset_td: int
    exit_offset_td: int


class CellComparison(BaseModel):
    cell_key: CompareCellKey
    stats: CellStatsBlock
    roi_distribution: list[float] = Field(
        ...,
        description=(
            "Per-trade ROI values for this cell, sorted ascending. "
            f"Capped at {MAX_DISTRIBUTION_ROWS} rows. **Truncation "
            "keeps the LOWEST N by ROI** (right tail dropped) — "
            "consistent with the tool's tail-risk emphasis (CVaR-5%); "
            "consumers plotting this as a histogram must NOT "
            "generalize a left-shifted shape to mean 'cell is worse "
            "than it looks'. Use cell_summary for the full per-trade "
            "list including right-tail trades."
        ),
    )


class CellDifference(BaseModel):
    """Raw deltas vs the baseline (first) cell. NO p-values, NO "significant"
    framing — just the raw signed difference."""
    other_cell_key: CompareCellKey
    delta_median_roi: float | None = Field(
        ...,
        description=(
            "other.median_roi - baseline.median_roi. Sign matches the "
            "direction other is from baseline. None when either side "
            "has n < 1."
        ),
    )
    delta_mean_roi: float | None
    delta_win_rate_pct: float | None
    delta_total_net_pnl: float | None
    delta_n_trades: int = Field(
        ..., description="other.n - baseline.n (sample-size difference)."
    )


class CompareCellsInput(BaseModel):
    run_id: str
    cell_keys: list[CompareCellKey] = Field(
        ...,
        min_length=2,
        max_length=4,
        description=(
            "2-4 cells to compare. The FIRST cell is the baseline; "
            "diff_vs_baseline contains one entry per non-first cell."
        ),
    )


class CompareCellsOutput(CaveatedResponse):
    run_id: str
    cells: list[CellComparison] = Field(
        ...,
        description=(
            "One entry per cell_key in input order. Includes stats + "
            "per-trade ROI distribution for consumer-side analysis."
        ),
    )
    diff_vs_baseline: list[CellDifference] = Field(
        ...,
        description=(
            "Raw deltas vs cells[0]. Length is len(cells) - 1 "
            "(baseline has no self-diff). Sign matches direction of "
            "the other cell from baseline."
        ),
    )


# ============================================================
# Helpers
# ============================================================

def _extract_cell(df: pd.DataFrame, key: CompareCellKey) -> pd.DataFrame:
    return df[
        (df["strategy"] == key.strategy)
        & (df["symbol"] == key.symbol)
        & (df["entry_offset_td"] == key.entry_offset_td)
        & (df["exit_offset_td"] == key.exit_offset_td)
    ]


def _build_comparison(
    df: pd.DataFrame, key: CompareCellKey,
) -> tuple[CellComparison, bool]:
    """Compute stats + ROI distribution for one cell. Returns
    (CellComparison, was_truncated_flag)."""
    cell_df = _extract_cell(df, key)
    if len(cell_df) == 0:
        return (
            CellComparison(
                cell_key=key,
                stats=empty_cell_stats_block(),
                roi_distribution=[],
            ),
            False,
        )
    stats = compute_cell_stats(
        rois=cell_df["roi_pct"].to_numpy(dtype=float),
        pnls=cell_df["net_pnl"].to_numpy(dtype=float),
        cvar_alpha=DEFAULT_CVAR_ALPHA,
    )
    sorted_rois = sorted(float(v) for v in cell_df["roi_pct"].tolist())
    truncated = len(sorted_rois) > MAX_DISTRIBUTION_ROWS
    if truncated:
        sorted_rois = sorted_rois[:MAX_DISTRIBUTION_ROWS]
    return (
        CellComparison(
            cell_key=key, stats=stats, roi_distribution=sorted_rois,
        ),
        truncated,
    )


def _compute_diff(
    baseline: CellComparison, other: CellComparison,
) -> CellDifference:
    """Compute raw signed deltas vs baseline. Handles either side
    being empty (n=0) by returning None for ratio-style fields."""
    def _sub(a: float | None, b: float | None) -> float | None:
        if a is None or b is None:
            return None
        return float(a - b)
    return CellDifference(
        other_cell_key=other.cell_key,
        delta_median_roi=_sub(other.stats.median_roi_pct,
                              baseline.stats.median_roi_pct),
        delta_mean_roi=_sub(other.stats.mean_roi_pct,
                            baseline.stats.mean_roi_pct),
        delta_win_rate_pct=_sub(other.stats.win_rate_pct,
                                baseline.stats.win_rate_pct),
        delta_total_net_pnl=float(
            other.stats.total_net_pnl - baseline.stats.total_net_pnl
        ),
        delta_n_trades=int(other.stats.n - baseline.stats.n),
    )


# ============================================================
# Tool impl
# ============================================================

def compare_cells_impl(inp: CompareCellsInput) -> CompareCellsOutput:
    df = read_results(inp.run_id)

    comparisons: list[CellComparison] = []
    any_truncated = False
    for key in inp.cell_keys:
        comp, truncated = _build_comparison(df, key)
        comparisons.append(comp)
        any_truncated = any_truncated or truncated

    baseline = comparisons[0]
    diffs = [_compute_diff(baseline, other) for other in comparisons[1:]]

    caveats: list[str] = [NO_P_VALUES_CAVEAT]
    if any_truncated:
        caveats.append(
            f"At least one cell's ROI distribution was truncated to "
            f"{MAX_DISTRIBUTION_ROWS} rows (LOWEST {MAX_DISTRIBUTION_ROWS} "
            f"by ROI; right tail dropped). The lowest-N policy matches "
            f"the tool's tail-risk emphasis (consistent with the CVaR-"
            f"5% framing). Use cell_summary against the specific "
            f"cell_key for the full per-trade list — including the "
            f"dropped right-tail trades."
        )
    # Multiple-comparisons caveat — verbatim re-export from
    # src.analytics.rank, same constant the dashboard uses. The
    # framing is load-bearing whenever a consumer Claude is picking
    # winners from a comparison.
    caveats.append(MULTIPLE_COMPARISONS_CAVEAT)

    # Pre-arc caveat.
    stamp = read_run_metadata(inp.run_id)
    if stamp.get("engine_version") != ENGINE_VERSION:
        caveats.append(PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT)

    # Empty-cells caveat: if every cell has n == 0, the comparison is
    # uninformative.
    if all(c.stats.n == 0 for c in comparisons):
        caveats.append(
            "All requested cells are empty in this run. Verify the "
            "cell_keys exist via query_sweep or cell_summary."
        )

    return CompareCellsOutput(
        run_id=inp.run_id,
        cells=comparisons,
        diff_vs_baseline=diffs,
        caveats=caveats,
    )


# ============================================================
# Registry export
# ============================================================

def register_compare_cells_tools() -> list[ToolEntry]:
    return [
        ToolEntry(
            name="compare_cells",
            description=(
                "Side-by-side comparison of 2-4 cells: per-cell stats "
                "+ raw deltas vs first (baseline) cell + per-cell ROI "
                "distributions. LOAD-BEARING constraint: NO p-values "
                "or significance-test machinery (sample sizes too "
                "small for that to be honest); raw deltas are "
                "directional signals only. Same constraint pattern as "
                "the dashboard's Compare-cells mode."
            ),
            input_model=CompareCellsInput,
            output_model=CompareCellsOutput,
            impl=compare_cells_impl,
        ),
    ]
