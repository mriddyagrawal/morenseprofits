"""MCP tool — cell_summary (sub-arc 3.3, tool 3 of 4).

The analyst's heaviest single-cell drill-down: pin one
(strategy, symbol, entry_offset_td, exit_offset_td) cell in a sweep
parquet and return its full statistical picture in a single tool
call:

  - stats: n, win_rate, median/mean/std ROI, CVaR-5%, total net P&L
  - bootstrap_ci: percentile-bootstrap 95% CI on median ROI (B=1000,
    seed=0) using the existing src.analytics.bootstrap implementation
  - per_trade: per-expiry trade list with entry/exit dates + P&L +
    ROI (heavy ``legs_json`` / ``costs_breakdown_json`` blobs omitted
    by default — consumer can use ``query_sweep`` for full payload)
  - observations: auto-detected structural observations via
    ``src.analytics.observations.interpret_cell_stats`` (heavy-tail /
    outlier-carry / instability)
  - caveats: pre-pricing-arc framing when applicable + min-N framing
    when the cell is below the conventional MIN_N_FOR_RANKING

Reviewer's Q3 + Q4 fully exercised: schema-level CaveatedResponse
enforcement (Q4 first half), behavior tests for every caveat-trigger
condition (Q4 second half), and this is one of the top-4 tools per
the consultation so it gets snapshot-pinned schemas (Q3).
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from src.analytics.aggregate import MIN_N_FOR_RANKING
from src.analytics.bootstrap import bootstrap_ci
from src.analytics.observations import interpret_cell_stats
from src.engine.results import ENGINE_VERSION, read_results, read_run_metadata
from src.mcp._models import (
    PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT,
    CaveatedResponse,
    ToolEntry,
)


# CVaR tail fraction. 5% matches the dashboard's right-pane CVaR
# rendering — keep one source of truth across surfaces.
CVAR_ALPHA = 0.05

# Bootstrap parameters for the median-ROI CI. Hoisted to constants
# (rather than hardcoded inside _compute_bootstrap_ci + the method
# string) per reviewer Grill #3 on 3264f37: the method string was a
# silent-lie risk if the actual ``bootstrap_ci(...)`` call ever
# diverged from the hardcoded "B=1000, seed=0" string. Now there's
# one source of truth and the method string is constructed from it.
BOOTSTRAP_B = 1000
BOOTSTRAP_SEED = 0
BOOTSTRAP_ALPHA = 0.05
BOOTSTRAP_METHOD = (
    f"percentile bootstrap, B={BOOTSTRAP_B}, seed={BOOTSTRAP_SEED}, "
    f"alpha={BOOTSTRAP_ALPHA}"
)

# Per-trade list cap. Typical cells have ~24 trades; worst-case wide-
# grid runs land ~50 expiries. The cap is bigger than the empirical
# ceiling but bounded — keeps consistency with get_spot_series /
# query_sweep which both cap at MAX_ROWS_PER_RESPONSE. Per reviewer
# Grill #4 on 3264f37.
MAX_PER_TRADE_ROWS = 1_000


# ============================================================
# Models
# ============================================================

class CellStats(BaseModel):
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
            "Median per-trade ROI (the rank metric the dashboard "
            "defaults to)."
        ),
    )
    mean_roi_pct: float | None = Field(
        ...,
        description=(
            "Mean per-trade ROI. For left-skewed short-vol P&L, "
            "mean < median is structural — the gap measures the "
            "drag from rare large losses."
        ),
    )
    std_roi_pct: float | None = Field(
        ...,
        description=(
            "Observed-sample standard deviation of per-trade ROI "
            "(ddof=0). Treated as a LOWER bound on the true population "
            "spread; bias vs ddof=1 is ~11% at n=5, ~5% at n=10, "
            "~2.5% at n=20."
        ),
    )
    cvar_5_roi_pct: float | None = Field(
        ...,
        description=(
            f"CVaR-{int(CVAR_ALPHA*100)}%: mean of the worst-α fraction "
            "of per-trade ROI in the cell. Floor-at-1 so thin cells "
            "still surface the single-worst-trade as their tail "
            "estimate. None when n == 0."
        ),
    )
    total_net_pnl: float = Field(
        ..., description="Sum of net_pnl across all trades in the cell."
    )


class BootstrapCIResult(BaseModel):
    point_estimate: float | None = Field(
        ...,
        description="Point statistic value on the original sample (median ROI).",
    )
    ci_lo: float | None = Field(
        ..., description="Lower bound of the 95% bootstrap CI."
    )
    ci_hi: float | None = Field(
        ..., description="Upper bound of the 95% bootstrap CI."
    )
    method: str = Field(
        ...,
        description=(
            "Method description constructed from BOOTSTRAP_B / SEED / "
            "ALPHA module constants — single source of truth so the "
            "string can't drift from the actual call."
        ),
    )


class CellTradeRow(BaseModel):
    expiry: date
    entry_date: date
    exit_date: date
    net_pnl: float
    roi_pct: float
    hold_trading_days: int


class CellKey(BaseModel):
    strategy: str
    symbol: str
    entry_offset_td: int
    exit_offset_td: int


class CellSummaryInput(BaseModel):
    run_id: str
    strategy: str
    symbol: str
    entry_offset_td: int
    exit_offset_td: int
    include_per_trade: bool = Field(
        default=True,
        description=(
            "If False, ``per_trade`` is omitted (returns None). Use for "
            "lightweight stat-only queries; flip to True for the full "
            "drill-down."
        ),
    )


class CellSummaryOutput(CaveatedResponse):
    run_id: str
    cell_key: CellKey
    stats: CellStats
    bootstrap_ci_median_roi: BootstrapCIResult
    per_trade: list[CellTradeRow] | None
    observations: list[str] = Field(
        ...,
        description=(
            "Auto-detected structural observations from "
            "interpret_cell_stats (heavy-tail / outlier-carry / "
            "instability). Empty list when nothing notable."
        ),
    )


# ============================================================
# Pure helpers
# ============================================================

def _bottom_alpha_mean(values: np.ndarray, alpha: float) -> float:
    """Mean of the worst-α fraction of values (CVaR-α tail mean).
    Floor-at-1 — for tiny n the single-worst value IS the honest tail
    estimate. NaN-aware: drops NaNs before sorting."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return float("nan")
    k = max(1, int(np.ceil(alpha * len(arr))))
    return float(np.mean(np.sort(arr)[:k]))


def _empty_stats() -> CellStats:
    return CellStats(
        n=0,
        win_rate_pct=None,
        median_roi_pct=None,
        mean_roi_pct=None,
        std_roi_pct=None,
        cvar_5_roi_pct=None,
        total_net_pnl=0.0,
    )


def _compute_stats(cell: pd.DataFrame) -> CellStats:
    n = len(cell)
    if n == 0:
        return _empty_stats()
    roi = cell["roi_pct"].to_numpy(dtype=float)
    pnl = cell["net_pnl"].to_numpy(dtype=float)
    return CellStats(
        n=n,
        win_rate_pct=float(100.0 * (pnl > 0).sum() / n),
        median_roi_pct=float(np.median(roi)),
        mean_roi_pct=float(np.mean(roi)),
        std_roi_pct=float(np.std(roi, ddof=0)) if n >= 2 else None,
        cvar_5_roi_pct=_bottom_alpha_mean(roi, CVAR_ALPHA),
        total_net_pnl=float(pnl.sum()),
    )


def _compute_bootstrap_ci(cell: pd.DataFrame) -> BootstrapCIResult:
    if len(cell) < 2:
        return BootstrapCIResult(
            point_estimate=None, ci_lo=None, ci_hi=None, method=BOOTSTRAP_METHOD,
        )
    roi = cell["roi_pct"].to_numpy(dtype=float)
    point, lo, hi = bootstrap_ci(
        roi, B=BOOTSTRAP_B, seed=BOOTSTRAP_SEED, alpha=BOOTSTRAP_ALPHA,
    )
    return BootstrapCIResult(
        point_estimate=None if np.isnan(point) else float(point),
        ci_lo=None if np.isnan(lo) else float(lo),
        ci_hi=None if np.isnan(hi) else float(hi),
        method=BOOTSTRAP_METHOD,
    )


def _build_per_trade(cell: pd.DataFrame) -> list[CellTradeRow]:
    rows: list[CellTradeRow] = []
    for _, r in cell.sort_values("expiry").iterrows():
        rows.append(CellTradeRow(
            expiry=_as_date(r["expiry"]),
            entry_date=_as_date(r["entry_date"]),
            exit_date=_as_date(r["exit_date"]),
            net_pnl=float(r["net_pnl"]),
            roi_pct=float(r["roi_pct"]),
            hold_trading_days=int(r["hold_trading_days"]),
        ))
    return rows


def _as_date(v: Any) -> date:
    """Coerce a results-frame date cell (pd.Timestamp / datetime / date)
    to a plain ``datetime.date``. The result frame stores dates as
    ``datetime64[us]`` per canonical_column_order; .date() on the
    Timestamp gives us what we want."""
    if isinstance(v, pd.Timestamp):
        return v.date()
    if isinstance(v, date):
        return v
    return pd.Timestamp(v).date()


def _interpret_observations(cell: pd.DataFrame) -> list[str]:
    """Call into ``interpret_cell_stats``. Requires the per-trade
    frame to carry ``roi_pct`` (the column observations reads after
    fix(observations.roi_column) — the recalibrated thresholds are
    per-trade-scale, so the column read matches). Returns [] for an
    empty cell."""
    if len(cell) == 0:
        return []
    return interpret_cell_stats(cell)


# ============================================================
# Tool impl
# ============================================================

def cell_summary_impl(inp: CellSummaryInput) -> CellSummaryOutput:
    df = read_results(inp.run_id)
    cell = df[
        (df["strategy"] == inp.strategy)
        & (df["symbol"] == inp.symbol)
        & (df["entry_offset_td"] == inp.entry_offset_td)
        & (df["exit_offset_td"] == inp.exit_offset_td)
    ]
    stats = _compute_stats(cell)
    ci = _compute_bootstrap_ci(cell)
    obs = _interpret_observations(cell)
    per_trade = _build_per_trade(cell) if inp.include_per_trade else None

    caveats: list[str] = []

    # Per-trade list cap. Typical cells are ~24 trades; this only
    # fires if a future sweep grid materially expands expiry coverage.
    if per_trade is not None and len(per_trade) > MAX_PER_TRADE_ROWS:
        n_dropped = len(per_trade) - MAX_PER_TRADE_ROWS
        per_trade = per_trade[:MAX_PER_TRADE_ROWS]
        caveats.append(
            f"per_trade truncated to {MAX_PER_TRADE_ROWS} rows; "
            f"{n_dropped} additional trades dropped. Use query_sweep "
            f"with the same cell-key filter for full coverage."
        )

    # Min-N caveat — empty cell is the strongest case but it's
    # informative even for n=1..min_n-1.
    if stats.n == 0:
        caveats.append(
            "No trades in the requested cell — the cell is either "
            "outside the sweep grid OR every candidate trade was "
            "skipped (check skip_summary)."
        )
    elif stats.n < MIN_N_FOR_RANKING:
        caveats.append(
            f"n={stats.n} is below the conventional MIN_N_FOR_RANKING "
            f"threshold of {MIN_N_FOR_RANKING}. Statistics and "
            f"bootstrap CI are unstable below this size — treat the "
            f"point estimates as suggestive at best."
        )

    # Pre-arc caveat — surface the phantom-fill-bias framing whenever
    # the queried run lacks the current engine_version stamp.
    stamp = read_run_metadata(inp.run_id)
    if stamp.get("engine_version") != ENGINE_VERSION:
        caveats.append(PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT)

    return CellSummaryOutput(
        run_id=inp.run_id,
        cell_key=CellKey(
            strategy=inp.strategy,
            symbol=inp.symbol,
            entry_offset_td=inp.entry_offset_td,
            exit_offset_td=inp.exit_offset_td,
        ),
        stats=stats,
        bootstrap_ci_median_roi=ci,
        per_trade=per_trade,
        observations=obs,
        caveats=caveats,
    )


# ============================================================
# Registry export
# ============================================================

def register_cell_summary_tools() -> list[ToolEntry]:
    return [
        ToolEntry(
            name="cell_summary",
            description=(
                "Full single-cell drill-down: stats + 95% bootstrap CI "
                "on median ROI + auto-detected structural observations + "
                "per-trade list. The analyst's heaviest single-cell "
                "tool. Pre-pricing-arc caveat fires when the run lacks "
                "the engine_version stamp."
            ),
            input_model=CellSummaryInput,
            output_model=CellSummaryOutput,
            impl=cell_summary_impl,
        ),
    ]
