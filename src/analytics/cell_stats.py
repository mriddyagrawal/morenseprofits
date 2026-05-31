"""Shared per-cell stat-block computation.

A "cell" in this project is one (strategy, symbol, entry_offset_td,
exit_offset_td) intersection of a sweep grid. Most analytical tools
need the same stat block per cell:
  - n (trade count)
  - win_rate_pct
  - median_roi_pct / mean_roi_pct / std_roi_pct
  - cvar_5_roi_pct (mean of the worst-α fraction; α = 0.05 default)
  - total_net_pnl

Before centralization (reviewer grill on 96a506c → "defensible at 2
copies, fragile at 3"), this block was duplicated across:
  - src/mcp/cell_summary.py::_compute_stats  (DataFrame input)
  - src/mcp/sweep_windows.py::_aggregate_priced_trades  (tuple list input)
  - src/mcp/compare_cells.py::_compute_stats  (about to be 3rd copy)

This module is the single source of truth. The Pydantic model
``CellStatsBlock`` is shared verbatim; each consumer tool wraps it
into its own response model alongside tool-specific fields.

CVaR-α "floor at 1" semantics: ``bottom_alpha_mean`` returns the
single worst trade for cells where ``ceil(α × n) < 1`` (i.e. thin
cells). Matches the dashboard's right-pane CVaR rendering policy
and the dashboard's median/CVaR drill-down.
"""
from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field


# Default CVaR tail fraction. 5% matches the dashboard + every MCP
# tool that computes CVaR. Keep one source of truth across surfaces.
DEFAULT_CVAR_ALPHA = 0.05


class CellStatsBlock(BaseModel):
    """Per-cell stat block. Shared by every tool that summarizes a
    cell's per-trade outcomes (cell_summary, sweep_windows,
    compare_cells)."""
    n: int = Field(..., description="Trade count in the cell.")
    win_rate_pct: float | None = Field(
        ...,
        description=(
            "Fraction of trades with positive net_pnl, in percent. "
            "None when n == 0."
        ),
    )
    median_roi_pct: float | None = Field(
        ...,
        description=(
            "Median per-trade ROI. The dashboard's default rank metric."
        ),
    )
    mean_roi_pct: float | None = Field(
        ...,
        description=(
            "Mean per-trade ROI. For left-skewed short-vol P&L, mean < "
            "median is structural — the gap measures the drag from "
            "rare large losses."
        ),
    )
    std_roi_pct: float | None = Field(
        ...,
        description=(
            "Observed-sample standard deviation of per-trade ROI "
            "(ddof=0). Treated as a LOWER bound on the true population "
            "spread; bias vs ddof=1 is ~11% at n=5."
        ),
    )
    cvar_5_roi_pct: float | None = Field(
        ...,
        description=(
            "CVaR-5%: mean of the worst-α fraction of per-trade ROI "
            "in the cell. Floor-at-1 so thin cells still surface the "
            "single-worst-trade as their tail estimate. None when n == 0."
        ),
    )
    total_net_pnl: float = Field(
        ..., description="Sum of net_pnl across all trades in the cell."
    )


def bottom_alpha_mean(values: np.ndarray, alpha: float = DEFAULT_CVAR_ALPHA) -> float:
    """Mean of the worst-α fraction of ``values`` (CVaR-α tail mean).

    Floor-at-1: for tiny n where ``ceil(α × n) < 1``, the single-worst
    value IS the honest tail estimate. NaN-aware: drops non-finite
    values before sorting.

    Returns NaN if the input has zero finite values.
    """
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return float("nan")
    k = max(1, int(np.ceil(alpha * len(arr))))
    return float(np.mean(np.sort(arr)[:k]))


def empty_cell_stats_block() -> CellStatsBlock:
    """Return the empty / zero-count stat block. Used by callers that
    need to surface an empty cell uniformly (e.g. cell_summary on a
    missing cell, sweep_windows on an all-skipped cell)."""
    return CellStatsBlock(
        n=0,
        win_rate_pct=None,
        median_roi_pct=None,
        mean_roi_pct=None,
        std_roi_pct=None,
        cvar_5_roi_pct=None,
        total_net_pnl=0.0,
    )


def compute_cell_stats(
    rois: np.ndarray,
    pnls: np.ndarray,
    *,
    cvar_alpha: float = DEFAULT_CVAR_ALPHA,
) -> CellStatsBlock:
    """Compute the per-cell stat block from per-trade ROI + net P&L
    arrays.

    ``rois`` and ``pnls`` must be 1-D arrays of the same length; each
    index represents one trade. NaN handling: the stats compute over
    the supplied values as-is — caller is responsible for dropping
    NaNs if they need NaN-aware behavior (mirrors numpy's policy on
    the underlying functions: ``np.median`` propagates NaN).

    The ``cvar_alpha`` kwarg is LOCKED to ``DEFAULT_CVAR_ALPHA`` (5%).
    The field name on the returned block — ``cvar_5_roi_pct`` —
    encodes the 5% commitment, so allowing the caller to pass a
    different alpha would silently produce a stat block whose field
    name disagrees with its value. Raise loud rather than drift.
    Reviewer's latent grill on ebe7228: the previous signature
    accepted any alpha, which made the field-name contract leaky.

    Returns ``empty_cell_stats_block()`` when n == 0.
    """
    if cvar_alpha != DEFAULT_CVAR_ALPHA:
        raise ValueError(
            f"cvar_alpha={cvar_alpha} differs from DEFAULT_CVAR_ALPHA"
            f"={DEFAULT_CVAR_ALPHA}. The returned block's "
            f"``cvar_5_roi_pct`` field name encodes 5% by contract; "
            f"a non-default alpha would produce a misleadingly-named "
            f"field. If you need a different tail fraction, call "
            f"``bottom_alpha_mean`` directly (alpha-agnostic helper)."
        )
    rois = np.asarray(rois, dtype=float)
    pnls = np.asarray(pnls, dtype=float)
    if rois.shape != pnls.shape:
        raise ValueError(
            f"rois and pnls shape mismatch: {rois.shape} vs {pnls.shape}"
        )
    n = len(rois)
    if n == 0:
        return empty_cell_stats_block()
    return CellStatsBlock(
        n=n,
        win_rate_pct=float(100.0 * (pnls > 0).sum() / n),
        median_roi_pct=float(np.median(rois)),
        mean_roi_pct=float(np.mean(rois)),
        std_roi_pct=float(np.std(rois, ddof=0)) if n >= 2 else None,
        cvar_5_roi_pct=bottom_alpha_mean(rois, cvar_alpha),
        total_net_pnl=float(pnls.sum()),
    )
