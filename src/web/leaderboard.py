"""Leaderboard tab — Phase 6.2 implementation.

DESIGN_SPEC §2.5 (headline strip) + §4 (commits 11-14: headline,
table, thin-samples sidecar, within/across toggle).

This commit (p6.2.headline): the 4-card strip across the top.
Subsequent commits add the rank table, thin-samples sidecar, and
the within/across toggle below it.

Naming rule pinned in §2.5: if a card's value is RUPEES, the label
contains "P&L" or "₹" — never "ROI". If a card's value is a
PERCENTAGE, the label ends in "%" or "%/yr" — never a bare number.
This is the contract that prevents the mockup's "AVG ROI ₹25.76 L"
bug (rupees mislabeled as percentage).
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.analytics.aggregate import summarize_by_stock_strategy
from src.analytics.rank import rank_strategies
from src.web._format import format_inr, format_pct
from src.web.empty_state import render_empty


def render_headline(df: pd.DataFrame, *, min_n: int) -> None:
    """Render the 4-card headline strip per DESIGN_SPEC §2.5.

    Cards (left → right):
      TOP PAIR          rank=1's strategy × symbol, subtitle =
                        +X.X %/yr median ann. ROI
      OVERALL WIN RATE  (net_pnl > 0).sum() / n_trades × 100
      TOTAL NET P&L     sum(net_pnl) formatted as ₹X.XX L or Cr
      RANKED PAIRS      n_above_min_n / n_pairs_total

    Empty-frame fallback per §2.5: zero rows → every card renders
    `—` with subtitle "no data after filters". No `nan%` ever shown.
    """
    cols = st.columns(4)

    # === Empty-frame branch ==================================
    if len(df) == 0:
        labels = ["Top pair", "Overall win rate", "Total net P&L", "Ranked pairs"]
        for col, label in zip(cols, labels):
            with col:
                st.metric(label, "—", "no data after filters",
                          delta_color="off")
        return

    # === Common computations =================================
    summary = summarize_by_stock_strategy(df)
    # min_n=0 because the headline summary should reflect ALL pairs,
    # not just rank-eligible ones — the RANKED PAIRS card surfaces
    # the suppression count separately.
    ranked_all = rank_strategies(summary, min_n=0)
    ranked_eligible = ranked_all[ranked_all["n_trades"] >= min_n]
    n_pairs_total = int(len(summary))
    n_pairs_eligible = int(len(ranked_eligible))

    # === Card 1 — TOP PAIR ===================================
    with cols[0]:
        if n_pairs_eligible > 0:
            top = ranked_eligible.iloc[0]
            st.metric(
                "Top pair",
                f"{top['strategy']} × {top['symbol']}",
                f"{format_pct(top['median_roi_pct_annualized'], signed=True, annualized=True)} median ann. ROI",
                delta_color="off",
            )
        else:
            st.metric(
                "Top pair", "—",
                f"no pairs pass min_n={min_n}",
                delta_color="off",
            )

    # === Card 2 — OVERALL WIN RATE ===========================
    n_trades_total = int(len(df))
    n_winning = int((df["net_pnl"] > 0).sum())
    with cols[1]:
        st.metric(
            "Overall win rate",
            format_pct(100.0 * n_winning / n_trades_total),
            f"{n_winning} of {n_trades_total} trades profitable",
            delta_color="off",
        )

    # === Card 3 — TOTAL NET P&L ==============================
    total_pnl = float(df["net_pnl"].sum())
    with cols[2]:
        st.metric(
            "Total net P&L",
            format_inr(total_pnl),
            f"across {n_pairs_total} (strategy, symbol) pair(s)",
            delta_color="off",
        )

    # === Card 4 — RANKED PAIRS ===============================
    with cols[3]:
        st.metric(
            "Ranked pairs",
            f"{n_pairs_eligible}/{n_pairs_total}",
            f"min_n={min_n} from sidebar",
            delta_color="off",
        )


# ============================================================
# Rank table — Phase 6.2 commit 12 (feat(p6.2.table))
# ============================================================

def render_rank_table(df: pd.DataFrame, *, min_n: int) -> None:
    """Render the main leaderboard rank table per DESIGN_SPEC §4
    commit 12. Columns (left → right):

      rank, strategy, symbol, n_trades, win_rate_pct, median_roi_ann,
      mean_roi_ann, std_roi_ann, total_net_pnl

    Empty-frame paths per §2.6:
      - 0 rows after filters             → leaderboard_no_rows_after_filters
      - 0 rows pass min_n AND ≥1 pair    → leaderboard_all_below_min_n

    Column formatting via st.column_config:
      - win_rate_pct       — ProgressColumn (0-100 range; visual bar)
      - rupee P&L          — NumberColumn with format="₹%,.0f"
      - percentages        — NumberColumn with format="%.1f%%"
        (annualized %s get "%.1f%%/yr"-equivalent via subtitle)
    """
    if len(df) == 0:
        render_empty("leaderboard_no_rows_after_filters")
        return

    summary = summarize_by_stock_strategy(df)
    n_pairs_total = int(len(summary))
    ranked = rank_strategies(summary, min_n=min_n)
    if len(ranked) == 0:
        render_empty(
            "leaderboard_all_below_min_n",
            n_pairs=n_pairs_total, min_n=min_n,
        )
        return

    # Slice to the columns we display. The aggregator emits more (e.g.
    # mean_net_pnl, worst/best per trade) — leaderboard surface keeps it
    # tight; full table is accessible via the CSV export (Phase 7).
    display_cols = [
        "rank", "strategy", "symbol", "n_trades",
        "win_rate_pct",
        "median_roi_pct_annualized",
        "mean_roi_pct_annualized",
        "std_roi_pct_annualized",
        "total_net_pnl",
    ]
    table = ranked[display_cols].copy()

    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "rank": st.column_config.NumberColumn(
                "#", format="%d", width="small",
                help="1-indexed; higher = lower rank.",
            ),
            "strategy": st.column_config.TextColumn(
                "Strategy", width="medium",
            ),
            "symbol": st.column_config.TextColumn(
                "Symbol", width="small",
            ),
            "n_trades": st.column_config.NumberColumn(
                "N", format="%d", width="small",
                help=(
                    "Sample size. Sidebar min_n suppresses rows with "
                    "fewer than this threshold from the ranking."
                ),
            ),
            "win_rate_pct": st.column_config.ProgressColumn(
                "Win %", format="%.1f%%",
                min_value=0.0, max_value=100.0, width="small",
            ),
            "median_roi_pct_annualized": st.column_config.NumberColumn(
                "Median ROI/yr", format="%+.1f%%",
                help=(
                    "Median holding-period ROI annualized to 252 trading days "
                    "(SPECS §4a caveat #2). Cross-window-comparable; robust "
                    "to single-trade outliers in small N samples."
                ),
            ),
            "mean_roi_pct_annualized": st.column_config.NumberColumn(
                "Mean ROI/yr", format="%+.1f%%",
            ),
            "std_roi_pct_annualized": st.column_config.NumberColumn(
                "Std ROI/yr", format="±%.1f%%",
                help=(
                    "Observed-sample dispersion (ddof=0). Treat as LOWER "
                    "BOUND on true population spread; small-N groups "
                    "understate spread by ~11% at n=5, ~5% at n=10, "
                    "~2.5% at n=20."
                ),
            ),
            "total_net_pnl": st.column_config.NumberColumn(
                "Net P&L (₹)", format="₹%,.0f",
                help="Sum of net_pnl across this pair's trades.",
            ),
        },
    )

    # Footer note — sample-size transparency per SPECS §11.5 +
    # DESIGN_SPEC §2.2 (`n_trades` visually prominent next to `rank`).
    st.caption(
        f"Showing {len(ranked)} of {n_pairs_total} (strategy, symbol) "
        f"pair(s) — min_n={min_n} from sidebar. Smaller N samples are "
        f"available via the 'Thin samples — not ranked' sidecar below "
        f"(p6.2.thin)."
    )
