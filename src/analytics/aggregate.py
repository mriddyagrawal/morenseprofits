"""Aggregation — per-stock × strategy summary stats from the sweep parquet.

Phase 5.1 turns the raw SPECS §2.5 results frame into a higher-order
table answering "how does each (stock, strategy) pair perform on
average?". Phase 5.2 will add the (entry_offset, exit_offset) heatmap;
Phase 5.5 will rank.

Design rules:
  - Pure function of an in-memory results DataFrame; no I/O.
  - Surfaces ``n_trades`` on every row so consumers can filter
    statistically-thin samples themselves rather than silently dropping
    them here (the user wanted honesty about small-N rankings).
  - Sort by (strategy, symbol) for determinism — ranking comes in
    p5.5, not here.
  - Empty input → empty frame with the canonical SUMMARY_COLUMNS
    schema (downstream code can group/filter without KeyError).
"""
from __future__ import annotations

import pandas as pd

# Canonical output schema. Phase-6 UI + Phase-8 MCP server both
# consume this; one source of truth here.
SUMMARY_COLUMNS: tuple[str, ...] = (
    # Grouping keys
    "strategy",
    "symbol",
    # Sample size — surfaced loud so consumers don't accidentally rank
    # a single-cell strategy against a 50-cell one as if comparable.
    "n_trades",
    "n_winning",
    "win_rate_pct",
    # Per-trade P&L (rupees)
    "mean_net_pnl",
    "median_net_pnl",
    # Holding-period ROI (% on margin) — the headline number
    "mean_roi_pct",
    "median_roi_pct",
    # Annualized ROI — cross-window-rankable per SPECS §4a caveat #2
    "mean_roi_pct_annualized",
    "median_roi_pct_annualized",
    # Range / per-trade drawdown — worst single-trade ROI is the
    # natural "max drawdown" for a per-trade dataset where we don't
    # impose a temporal ordering (one operator runs trades in
    # parallel; calendar-ordered drawdown is a Phase-6 concern).
    "worst_roi_pct",
    "best_roi_pct",
)


# Minimum sample size below which a row's headline numbers are
# statistically unreliable. The aggregator does NOT drop these rows
# (transparency over silent filtering) — consumers can use
# ``df.query("n_trades >= MIN_N_FOR_RANKING")`` to suppress thin
# samples from rankings. 5 is the conventional lower bound for
# treating a sample mean as a meaningful summary.
MIN_N_FOR_RANKING: int = 5


def empty_summary_frame() -> pd.DataFrame:
    """Empty frame with canonical SUMMARY_COLUMNS. Phase-6 UI's
    `df.groupby('strategy')` on a zero-row sweep doesn't KeyError."""
    return pd.DataFrame({col: pd.Series(dtype=_inferred_dtype(col)) for col in SUMMARY_COLUMNS})


def _inferred_dtype(col: str) -> str:
    if col in {"strategy", "symbol"}:
        return "string"
    if col in {"n_trades", "n_winning"}:
        return "int64"
    return "float64"


YEARLY_SUMMARY_COLUMNS: tuple[str, ...] = (
    "strategy",
    "symbol",
    "year",
) + SUMMARY_COLUMNS[2:]  # share the per-row stats schema verbatim


def empty_yearly_summary_frame() -> pd.DataFrame:
    """Empty frame with canonical YEARLY_SUMMARY_COLUMNS — Phase-6's
    decay-plot consumer won't KeyError on an empty sweep."""
    return pd.DataFrame({
        col: pd.Series(dtype=_yearly_inferred_dtype(col))
        for col in YEARLY_SUMMARY_COLUMNS
    })


def _yearly_inferred_dtype(col: str) -> str:
    if col == "year":
        return "int64"
    return _inferred_dtype(col)


def _summarize(
    results_df: pd.DataFrame,
    group_keys: list[str],
    *,
    canonical_columns: tuple[str, ...],
) -> pd.DataFrame:
    """Group ``results_df`` by ``group_keys`` and emit one row per group
    with the canonical summary stats (n_trades, ROI percentiles, etc.).

    Each ``group_keys`` value becomes a column on the output (alongside
    the stat columns). The function checks required columns + handles
    empty input + sorts by ``group_keys`` for determinism. Internal
    helper for the public ``summarize_by_*`` functions — DRY across the
    three Phase-5 aggregators."""
    required = {*group_keys, "net_pnl", "roi_pct", "roi_pct_annualized"}
    missing = required - set(results_df.columns)
    if missing:
        raise ValueError(
            f"summarize missing required columns: {sorted(missing)}; "
            f"got {sorted(results_df.columns)}"
        )

    if len(results_df) == 0:
        # Empty input → empty canonical-schema frame (no KeyError downstream).
        return pd.DataFrame({
            col: pd.Series(dtype=_yearly_inferred_dtype(col))
            for col in canonical_columns
        })

    df = results_df.copy()
    # Cast text grouping keys to StringDtype for stable groupby output
    for k in ("strategy", "symbol"):
        if k in group_keys:
            df[k] = df[k].astype("string")

    grouped = df.groupby(group_keys, dropna=False)

    out_rows: list[dict] = []
    for keys, block in grouped:
        # groupby returns a tuple when len(group_keys) > 1, scalar otherwise
        keys = keys if isinstance(keys, tuple) else (keys,)
        row: dict = dict(zip(group_keys, keys))
        n = int(len(block))
        n_win = int((block["net_pnl"] > 0).sum())
        row.update({
            "n_trades": n,
            "n_winning": n_win,
            "win_rate_pct": (100.0 * n_win / n) if n else 0.0,
            "mean_net_pnl": float(block["net_pnl"].mean()),
            "median_net_pnl": float(block["net_pnl"].median()),
            "mean_roi_pct": float(block["roi_pct"].mean()),
            "median_roi_pct": float(block["roi_pct"].median()),
            "mean_roi_pct_annualized": float(block["roi_pct_annualized"].mean()),
            "median_roi_pct_annualized": float(block["roi_pct_annualized"].median()),
            "worst_roi_pct": float(block["roi_pct"].min()),
            "best_roi_pct": float(block["roi_pct"].max()),
        })
        out_rows.append(row)

    out = pd.DataFrame(out_rows)[list(canonical_columns)]
    # Dtype normalization matches the empty-frame schema
    for col in canonical_columns:
        target = _yearly_inferred_dtype(col)
        if str(out[col].dtype) != target:
            out[col] = out[col].astype(target)
    # Determinism — sort by the group keys themselves
    return out.sort_values(list(group_keys)).reset_index(drop=True)


def summarize_by_stock_strategy(results_df: pd.DataFrame) -> pd.DataFrame:
    """Group by ``(strategy, symbol)`` — one row per pair with
    SUMMARY_COLUMNS stats. The Phase-5 leaderboard table.

    Sort: ``(strategy, symbol)`` asc. Raises on missing required
    columns. Empty input → empty canonical frame."""
    return _summarize(
        results_df, ["strategy", "symbol"], canonical_columns=SUMMARY_COLUMNS,
    )


def summarize_by_year(results_df: pd.DataFrame) -> pd.DataFrame:
    """Group by ``(strategy, symbol, year)`` — one row per
    (strategy, symbol) pair PER YEAR. Lets consumers see decay:
    "is short_straddle on RELIANCE getting worse over time?".

    ``year`` is derived from ``expiry.year`` (semantic month-of-trade,
    not entry/exit which is a mechanic). The aggregator does NOT
    silently drop years with N<MIN_N_FOR_RANKING — same statistical-
    honesty contract as ``summarize_by_stock_strategy``. Consumers
    filter via ``df.query("n_trades >= MIN_N_FOR_RANKING")`` to suppress
    thin-sample years from a trend plot.

    Required: ``strategy``, ``symbol``, ``expiry``, ``net_pnl``,
    ``roi_pct``, ``roi_pct_annualized``."""
    if "expiry" not in results_df.columns:
        raise ValueError(
            f"summarize_by_year requires 'expiry' column; "
            f"got {sorted(results_df.columns)}"
        )
    if len(results_df) == 0:
        return empty_yearly_summary_frame()

    df = results_df.copy()
    # expiry is datetime64[us] per SPECS §2.0 (enforced by
    # canonical_column_order). Pull year out via .dt.year.
    df["year"] = pd.to_datetime(df["expiry"]).dt.year.astype("int64")
    return _summarize(
        df, ["strategy", "symbol", "year"],
        canonical_columns=YEARLY_SUMMARY_COLUMNS,
    )
