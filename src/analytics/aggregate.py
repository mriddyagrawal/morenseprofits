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


def summarize_by_stock_strategy(results_df: pd.DataFrame) -> pd.DataFrame:
    """Group ``results_df`` by (strategy, symbol) and emit one row per
    pair with the SUMMARY_COLUMNS stats.

    Required input columns: ``strategy``, ``symbol``, ``net_pnl``,
    ``roi_pct``, ``roi_pct_annualized``. Other columns are ignored —
    forward-compat with future per-row additions.

    Raises ValueError if a required column is missing — silent NaN
    aggregations are exactly the kind of bug the SPECS §2.5 schema
    guard catches at the data-write boundary; we extend that here.

    Sort order: ``(strategy, symbol)`` ascending, deterministic across
    runs.
    """
    required = {"strategy", "symbol", "net_pnl", "roi_pct", "roi_pct_annualized"}
    missing = required - set(results_df.columns)
    if missing:
        raise ValueError(
            f"summarize_by_stock_strategy missing required columns: "
            f"{sorted(missing)}; got {sorted(results_df.columns)}"
        )

    if len(results_df) == 0:
        return empty_summary_frame()

    # Cast strategy/symbol to string dtype before grouping so the
    # output column dtypes match SUMMARY_COLUMNS regardless of input
    # dtype (could be object, string, category from various callers).
    df = results_df.copy()
    df["strategy"] = df["strategy"].astype("string")
    df["symbol"] = df["symbol"].astype("string")

    grouped = df.groupby(["strategy", "symbol"], dropna=False)

    out_rows: list[dict] = []
    for (strategy, symbol), block in grouped:
        n = int(len(block))
        n_win = int((block["net_pnl"] > 0).sum())
        out_rows.append({
            "strategy": strategy,
            "symbol": symbol,
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

    out = pd.DataFrame(out_rows)
    # Canonical column order + dtype normalization matches empty frame
    out = out[list(SUMMARY_COLUMNS)]
    out["strategy"] = out["strategy"].astype("string")
    out["symbol"] = out["symbol"].astype("string")
    out["n_trades"] = out["n_trades"].astype("int64")
    out["n_winning"] = out["n_winning"].astype("int64")
    # Sort + reset for determinism — ranking happens in p5.5
    return out.sort_values(["strategy", "symbol"]).reset_index(drop=True)
