"""Heatmap pivots — ``(entry_offset_td × exit_offset_td)`` matrix for
one strategy × symbol slice.

Phase 5.2 is the data shape Phase-6's visualization will render: a 2D
matrix where rows are entry offsets (T-15 at top, T-1 at bottom), and
columns are exit offsets (T-3 leftmost, T-1 rightmost). Each cell holds
the median annualized ROI for that (entry, exit) window — directly
mappable to a color in a Phase-6 heatmap.

Two parallel functions instead of one combined return:

  - ``pivot_window``: cell values (median of `value_col`, configurable)
  - ``pivot_counts``: cell sample sizes (= n_trades feeding each cell)

Consumers compose them with ``.where(counts >= MIN_N_FOR_RANKING)`` to
mask thin-sample cells. Same statistical-honesty contract as the
``aggregate`` module — surface N, never silently drop.

Reviewer's design constraints (per p5.1 review, amended for p7 expiry-ROI shift):
  - Default value_col = ``roi_pct`` (per-trade ROI, no annualization)
  - Default aggfunc = ``median`` (robust to outliers in small samples)
  - Missing combinations → NaN (no false zero in the heatmap)
  - Indices sorted descending (T-15 at top of the heatmap)

Operator-facing rationale for the per-trade default: every cell aggregates
trades that all share the same (entry, exit) offsets, so all trades in a
cell have the SAME hold period — per-trade ROI is exactly comparable
within a cell. Cross-cell comparison is hold-period-aware (a longer-hold
cell will naturally show a larger per-trade ROI for the same daily yield);
that's the operator's choice to make, not the engine's to hide behind
forced annualization.
"""
from __future__ import annotations

import math

import pandas as pd


_REQUIRED_KEYS = ("strategy", "symbol", "entry_offset_td", "exit_offset_td")


def _filter(
    results_df: pd.DataFrame,
    *,
    strategy: str | None,
    symbol: str | None,
) -> pd.DataFrame:
    """Filter to one ``(strategy, symbol)`` slice. Either or both can
    be ``None`` for an aggregated view (e.g., "all strategies on
    RELIANCE"). Returns a copy."""
    missing = set(_REQUIRED_KEYS) - set(results_df.columns)
    if missing:
        raise ValueError(
            f"results frame missing required keys: {sorted(missing)}; "
            f"got {sorted(results_df.columns)}"
        )
    out = results_df
    if strategy is not None:
        out = out[out["strategy"] == strategy]
    if symbol is not None:
        out = out[out["symbol"] == symbol]
    return out


def pivot_window(
    results_df: pd.DataFrame,
    *,
    strategy: str | None = None,
    symbol: str | None = None,
    value_col: str = "roi_pct",
    aggfunc: str = "median",
) -> pd.DataFrame:
    """Return a 2D pivot of ``value_col`` aggregated across the
    ``(entry_offset_td, exit_offset_td)`` grid for the filtered slice.

    Index: ``entry_offset_td`` descending (T-15 at top, T-1 at bottom).
    Columns: ``exit_offset_td`` descending (larger offset = earlier
    exit, leftmost; T-1 = rightmost = "held to expiry").
    Missing cells → NaN.

    Default ``value_col = "roi_pct"`` — per-trade ROI. Each cell's
    trades all share the same (entry, exit) offsets, so per-trade ROI
    is exactly comparable within a cell. Operators who need the
    annualized view can pass ``value_col="roi_pct_annualized"``.

    Default ``aggfunc = "median"`` so a single outlier cell doesn't
    dominate the color scale. Mean is available via aggfunc="mean".

    ``strategy`` and/or ``symbol`` may be ``None`` to aggregate across
    that axis — but a useful heatmap typically pins both, since
    averaging across stocks/strategies dilutes the signal.

    Empty result (no rows after filter, or empty input) → empty
    DataFrame (no fake zero-filled grid).
    """
    # Validate structural keys first (required for the pivot to make
    # sense), THEN the value column (which is a configuration choice).
    filtered = _filter(results_df, strategy=strategy, symbol=symbol)
    if value_col not in results_df.columns:
        raise ValueError(
            f"value_col {value_col!r} not in results frame columns; "
            f"got {sorted(results_df.columns)}"
        )
    if len(filtered) == 0:
        return pd.DataFrame()

    pivot = filtered.pivot_table(
        index="entry_offset_td",
        columns="exit_offset_td",
        values=value_col,
        aggfunc=aggfunc,
        # observed=True suppresses categorical NaN fill — we want the
        # natural sparse-grid NaN behavior for missing combinations.
    )
    # Descending sort so T-15 is at top (visual convention: entry
    # furthest back at top, exit closest to expiry at right).
    return pivot.sort_index(ascending=False).sort_index(axis=1, ascending=False)


def pivot_cvar(
    results_df: pd.DataFrame,
    *,
    strategy: str | None = None,
    symbol: str | None = None,
    value_col: str = "roi_pct",
    alpha: float = 0.05,
) -> pd.DataFrame:
    """Per-cell CVaR-α: mean of the worst-α fraction of per-trade
    outcomes within each ``(entry_offset_td, exit_offset_td)`` cell.

    Default α = 0.05 → mean of the bottom 5% of trades. For typical p7
    sweep cells (N ≈ 25 trades), the bottom 5% is the 2 worst trades;
    for thinner cells (N < 20) the count floors to 1, so the metric is
    defined whenever the cell has ≥ 1 trade. Floor-at-1 makes the
    metric an honest "what would the worst-trade outcome have been" for
    thin cells rather than producing NaN where a single number IS the
    answer.

    Why this metric alongside ``pivot_window`` (median):
        Median ROI hides exactly the thing that kills short-vol
        strategies — the worst 5% of outcomes. Two cells with identical
        medians can have wildly different worst-case behavior; the cell
        with worse CVaR is the one that ends careers when a real-world
        tail event arrives. Surfacing CVaR per cell lets the operator
        pick the median-AND-tail-favorable region, not the median-only-
        favorable one.

    Args:
        results_df: per-trade frame from the sweep parquet. Must carry
            the structural keys + ``value_col``.
        strategy / symbol: pin one slice. Same semantics as
            ``pivot_window`` — either or both may be ``None`` to
            aggregate.
        value_col: which per-trade ROI column to compute the tail mean
            on. Defaults to ``roi_pct`` (per-trade ROI), matching the
            project-wide unit choice from p7.expiry_roi.
        alpha: tail fraction. 0.05 → worst 5%. Must be in (0, 1).

    Returns:
        DataFrame matching ``pivot_window``'s shape (entry_offset_td
        DESC × exit_offset_td DESC). Missing cells → NaN. Empty input
        → empty DataFrame.
    """
    filtered = _filter(results_df, strategy=strategy, symbol=symbol)
    if value_col not in results_df.columns:
        raise ValueError(
            f"value_col {value_col!r} not in results frame columns; "
            f"got {sorted(results_df.columns)}"
        )
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1); got {alpha}")
    if len(filtered) == 0:
        return pd.DataFrame()

    # Vectorised bottom-α-mean via sort + cumcount mask. A pivot_table
    # with a Python-lambda aggfunc is ~100× slower against a full-sweep
    # slice (Pandas falls back to per-group Python iteration); the e2e
    # AppTest times out at 30s on real data with the naive approach.
    # This implementation:
    #   1. Drops NaN in value_col,
    #   2. Sorts ascending so the K worst values land at the head of
    #      each group,
    #   3. Computes a within-group rank via cumcount,
    #   4. Masks to ranks ≤ K_per_group, where K = max(1, ceil(α·N)),
    #   5. Means the survivors per cell, then pivots.
    sorted_df = (
        filtered[["entry_offset_td", "exit_offset_td", value_col]]
        .dropna(subset=[value_col])
        .sort_values(value_col, kind="mergesort")
    )
    if sorted_df.empty:
        return pd.DataFrame()
    groups = sorted_df.groupby(
        ["entry_offset_td", "exit_offset_td"], sort=False,
    )
    n_per_group = groups[value_col].transform("size")
    # ceil(α·N) floored at 1 so thin cells (e.g. N=5, α=0.05) still
    # produce a defined CVaR — the worst single trade IS the honest
    # tail estimate when N is small.
    k_per_group = (
        (alpha * n_per_group).map(math.ceil).clip(lower=1).astype("int64")
    )
    rank_per_group = groups.cumcount() + 1   # 1-based, sorted ascending
    bottom_mask = rank_per_group <= k_per_group
    bottom = sorted_df[bottom_mask]
    cell_means = (
        bottom.groupby(["entry_offset_td", "exit_offset_td"], sort=False)[value_col]
        .mean()
        .reset_index()
    )
    pivot = cell_means.pivot(
        index="entry_offset_td",
        columns="exit_offset_td",
        values=value_col,
    )
    return pivot.sort_index(ascending=False).sort_index(axis=1, ascending=False)


def pivot_counts(
    results_df: pd.DataFrame,
    *,
    strategy: str | None = None,
    symbol: str | None = None,
) -> pd.DataFrame:
    """Sister function to ``pivot_window``: same shape, but cells hold
    the trade count contributing to that (entry, exit) cell.

    Consumers compose:
        v = pivot_window(...)
        n = pivot_counts(...)
        v.where(n >= MIN_N_FOR_RANKING)   # mask thin samples to NaN

    Missing combinations → 0 (not NaN) since "0 trades" is the
    accurate description of a sparse cell."""
    filtered = _filter(results_df, strategy=strategy, symbol=symbol)
    if len(filtered) == 0:
        return pd.DataFrame()

    counts = filtered.pivot_table(
        index="entry_offset_td",
        columns="exit_offset_td",
        values="net_pnl",  # any column — we count, not aggregate
        aggfunc="count",
        fill_value=0,
    )
    return counts.sort_index(ascending=False).sort_index(axis=1, ascending=False)
