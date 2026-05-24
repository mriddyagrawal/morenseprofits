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

Reviewer's design constraints (per p5.1 review):
  - Default value_col = ``roi_pct_annualized`` (cross-window-rankable)
  - Default aggfunc = ``median`` (robust to outliers in small samples)
  - Missing combinations → NaN (no false zero in the heatmap)
  - Indices sorted descending (T-15 at top of the heatmap)
"""
from __future__ import annotations

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
    value_col: str = "roi_pct_annualized",
    aggfunc: str = "median",
) -> pd.DataFrame:
    """Return a 2D pivot of ``value_col`` aggregated across the
    ``(entry_offset_td, exit_offset_td)`` grid for the filtered slice.

    Index: ``entry_offset_td`` descending (T-15 at top, T-1 at bottom).
    Columns: ``exit_offset_td`` descending (larger offset = earlier
    exit, leftmost; T-1 = rightmost = "held to expiry").
    Missing cells → NaN.

    Default ``value_col = "roi_pct_annualized"`` so the heatmap is
    cross-window-comparable per SPECS §4a caveat #2 (the now-exact
    annualization from p4.verify.a).

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
