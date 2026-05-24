"""Ranking — the final Phase-5 layer. Sorts a summary frame by a
configurable metric, filters statistically-thin samples, and returns
a copy with a 1-indexed ``rank`` column.

Consumed by Phase-6 UI to render the headline leaderboard
(e.g., "best (stock, strategy) pairs by median annualized ROI").

Statistical-honesty contract (continued from aggregate.py):
  - ``min_n=MIN_N_FOR_RANKING`` filters thin samples by default. Pass
    ``min_n=0`` to disable (with eyes open — small-N rows in a
    leaderboard are statistically suspect).
  - Multiple-comparisons caveat is a CONSTANT + docstring callout, not
    an algorithmic correction. Real Bonferroni / Holm-Sidák correction
    requires per-row p-values, which v1 doesn't compute. Surfacing the
    risk verbally in the leaderboard is the v1 mitigation.
"""
from __future__ import annotations

import warnings

import pandas as pd

from src.analytics.aggregate import MIN_N_FOR_RANKING


# Default ranking metric — median over mean for robustness to outliers,
# annualized so cells with different hold lengths are comparable per
# SPECS §4a caveat #2.
DEFAULT_RANK_METRIC: str = "median_roi_pct_annualized"


# v1 documentation-only mitigation for the selection-bias problem:
# when you rank N (strategy, symbol) pairs and pick the top-K, the
# realized edge of the top-K is biased upward (the top row "got lucky"
# more often than the bottom row). Phase-6 UI must render this caveat
# alongside any leaderboard derived from rank_strategies.
MULTIPLE_COMPARISONS_CAVEAT = (
    "Ranking N strategy×symbol pairs and selecting top-K introduces "
    "selection bias — the top-K's apparent edge is inflated by lucky "
    "draws. With N pairs each having a small backtest sample, expect "
    "the realized edge of the #1 rank to be smaller than displayed. "
    "Treat the leaderboard as a CANDIDATE LIST for further investigation, "
    "not a guaranteed-best-strategies finding. Phase-6 surfaces this "
    "verbally; Phase-7/8 may add formal multiple-testing correction."
)


def rank_strategies(
    summary_df: pd.DataFrame,
    *,
    by: str = DEFAULT_RANK_METRIC,
    ascending: bool = False,
    min_n: int = MIN_N_FOR_RANKING,
    top_n: int | None = None,
) -> pd.DataFrame:
    """Rank a summary frame by ``by`` and return a copy with a ``rank``
    column (1-indexed).

    Steps:
      1. Filter ``n_trades >= min_n`` (thin-sample suppression)
      2. Sort by ``by`` (descending by default — higher is better)
      3. Assign ``rank`` 1..N to surviving rows
      4. Truncate to ``top_n`` if provided

    Args:
      summary_df: output of ``aggregate.summarize_by_*`` — any frame
        with at least ``n_trades`` and the ``by`` column.
      by: column to sort by. Default = median annualized ROI (robust
        + cross-window-comparable).
      ascending: False (default) ranks high-ROI first; True ranks
        worst-first (useful for finding "what should I AVOID").
      min_n: minimum sample size to be ranked. ``MIN_N_FOR_RANKING``
        (5) by default. Pass 0 to disable.
      top_n: keep only the top N rows after ranking. ``None`` (default)
        returns all.

    Returns: a copy of ``summary_df`` with one extra column ``rank``,
    sorted by ``by`` (then by tiebreaker = first grouping key for
    determinism). Empty input → empty frame with ``rank`` column.

    **Tied-rank semantics**: ranks are dense integers 1..N regardless of
    metric ties — "competition ranking", not "shared-rank" (1, 1, 3).
    Lex tiebreaker on (strategy, symbol) means ties are broken
    deterministically across reruns but NOT by sample size. If two rows
    tie on the headline metric and one has N=50 vs the other N=5, the
    statistically thicker row may rank below the thinner one purely on
    alphabetic strategy name. Consumers (Phase-6 UI) should render
    ``n_trades`` prominently alongside ``rank`` so the operator can spot
    this. ``rank_strategies`` is the ranker, not a quality-weighted
    sorter.

    **Sharpe-like ranking**: passing
    ``by="mean_roi_pct_annualized / std_roi_pct_annualized"`` (after
    synthesizing the column on the input) gives a *Sharpe-LIKE* metric,
    NOT a real Sharpe ratio. True Sharpe subtracts a risk-free rate
    (~6.5% annualized for Indian markets). For ranking purposes the
    difference is small at high-ROI strategies; for absolute
    interpretation use ``(mean − rf) / std``.

    **All-suppressed warning**: if every input row has
    ``n_trades < min_n`` the function emits a ``warnings.warn(...)``
    so consumers can render an explicit "all samples below threshold"
    message rather than silent blank output.

    Caveat: see ``MULTIPLE_COMPARISONS_CAVEAT`` — top-K selection from
    a multi-hypothesis search inflates the apparent edge.
    """
    if "n_trades" not in summary_df.columns:
        raise ValueError(
            f"rank_strategies requires 'n_trades' column; "
            f"got {sorted(summary_df.columns)}"
        )
    if by not in summary_df.columns:
        raise ValueError(
            f"rank metric {by!r} not in summary frame columns; "
            f"got {sorted(summary_df.columns)}"
        )
    if min_n < 0:
        raise ValueError(f"min_n must be >= 0, got {min_n}")

    df = summary_df.copy()
    # Thin-sample suppression.
    n_input = len(df)
    df = df[df["n_trades"] >= min_n]
    if n_input > 0 and len(df) == 0:
        # All rows suppressed — operator would otherwise see an empty
        # leaderboard and wonder if the input was empty. Loud warning so
        # the UI / CLI consumer can render a "all samples below threshold"
        # message instead of silent blank. p5.5 reviewer flag (955d0f3).
        warnings.warn(
            f"rank_strategies: all {n_input} input rows suppressed by "
            f"min_n={min_n}. Consider lowering the threshold or expanding "
            f"the sweep grid.",
            stacklevel=2,
        )

    # Deterministic tiebreaker: first non-stat grouping column (strategy
    # by canonical convention), then symbol if present. Ties on ``by``
    # are broken in (strategy, symbol) lex order regardless of input
    # row order.
    sort_cols = [by]
    sort_dirs: list[bool] = [ascending]
    for tb in ("strategy", "symbol"):
        if tb in df.columns and tb != by:
            sort_cols.append(tb)
            sort_dirs.append(True)  # tiebreaker always ascending

    df = df.sort_values(sort_cols, ascending=sort_dirs).reset_index(drop=True)
    df.insert(0, "rank", range(1, len(df) + 1))
    df["rank"] = df["rank"].astype("int64")

    if top_n is not None:
        if top_n < 0:
            raise ValueError(f"top_n must be >= 0, got {top_n}")
        df = df.head(top_n).reset_index(drop=True)

    return df
