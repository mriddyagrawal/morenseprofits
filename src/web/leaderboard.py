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
