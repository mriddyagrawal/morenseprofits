"""Trends tab — Phase 6.4 implementation.

DESIGN_SPEC §2.5 (Trends row) + §4 (commits 18-21: headline, YoY
line, YoY sister chart, MoY bars).

Like the Heatmap tab, Trends needs ONE (strategy, symbol) pair
picked via in-tab selectors — a trend across multiple pairs
averages out the signal we're looking for.

§2.5 Trends row:
  BEST MONTH        summarize_by_month top row by median ann ROI
  WORST MONTH       bottom row
  TIGHTEST MONTH STD  summarize_by_month std_roi_pct_annualized.idxmin()
  LATEST YEAR ROI   summarize_by_year most-recent-year median
                    + subtitle: "vs prior year ±X.X pp"
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analytics.aggregate import summarize_by_month, summarize_by_year
from src.web._format import format_pct
from src.web.empty_state import render_empty


# ============================================================
# Selectors — same shape as heatmap.py's _selector
# ============================================================

def _selector(df: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
    """Strategy + symbol selectors at the top of the Trends tab.
    Defaults persist via mp_trends_strategy / mp_trends_symbol keys."""
    if len(df) == 0:
        return None, None
    available_strategies = sorted(df["strategy"].unique().tolist())
    available_symbols = sorted(df["symbol"].unique().tolist())
    cols = st.columns(2)
    with cols[0]:
        default = st.session_state.get("mp_trends_strategy") \
            if st.session_state.get("mp_trends_strategy") in available_strategies \
            else available_strategies[0]
        strategy = st.selectbox(
            "Strategy",
            options=available_strategies,
            index=available_strategies.index(default),
            key="mp_trends_strategy",
            help="One pair at a time — trend signals dilute across strategies.",
        )
    with cols[1]:
        default_sym = st.session_state.get("mp_trends_symbol") \
            if st.session_state.get("mp_trends_symbol") in available_symbols \
            else available_symbols[0]
        symbol = st.selectbox(
            "Symbol",
            options=available_symbols,
            index=available_symbols.index(default_sym),
            key="mp_trends_symbol",
        )
    return strategy, symbol


# ============================================================
# Headline strip — 4 cards per §2.5 Trends row
# ============================================================

_HEADLINE_LABELS = (
    "Best month",
    "Worst month",
    "Tightest month std",
    "Latest year ROI",
)


def render_headline(
    df: pd.DataFrame,
    *,
    strategy: Optional[str],
    symbol: Optional[str],
    min_n: int,
) -> None:
    """Render the 4-card strip per DESIGN_SPEC §2.5 Trends row."""
    cols = st.columns(4)

    if len(df) == 0 or strategy is None or symbol is None:
        for col, label in zip(cols, _HEADLINE_LABELS):
            with col:
                st.metric(label, "—", "no data after filters",
                          delta_color="off")
        return

    pair = df[(df["strategy"] == strategy) & (df["symbol"] == symbol)]
    if len(pair) == 0:
        for col, label in zip(cols, _HEADLINE_LABELS):
            with col:
                st.metric(label, "—", f"no trades for {strategy} × {symbol}",
                          delta_color="off")
        return

    monthly = summarize_by_month(pair)
    yearly = summarize_by_year(pair)
    # Suppress thin months from the headline analysis — same min_n
    # discipline as everywhere else.
    monthly_eligible = monthly[monthly["n_trades"] >= min_n]
    yearly_eligible = yearly[yearly["n_trades"] >= min_n]

    # === Card 1 — BEST MONTH =================================
    with cols[0]:
        if len(monthly_eligible) > 0:
            best = monthly_eligible.loc[
                monthly_eligible["median_roi_pct_annualized"].idxmax()
            ]
            st.metric(
                "Best month",
                format_pct(best["median_roi_pct_annualized"],
                           signed=True, annualized=True),
                f"month {int(best['month'])} (N={int(best['n_trades'])})",
                delta_color="off",
            )
        else:
            st.metric("Best month", "—",
                      f"no months with N ≥ {min_n}",
                      delta_color="off")

    # === Card 2 — WORST MONTH ================================
    with cols[1]:
        if len(monthly_eligible) > 0:
            worst = monthly_eligible.loc[
                monthly_eligible["median_roi_pct_annualized"].idxmin()
            ]
            st.metric(
                "Worst month",
                format_pct(worst["median_roi_pct_annualized"],
                           signed=True, annualized=True),
                f"month {int(worst['month'])} (N={int(worst['n_trades'])})",
                delta_color="off",
            )
        else:
            st.metric("Worst month", "—",
                      f"no months with N ≥ {min_n}",
                      delta_color="off")

    # === Card 3 — TIGHTEST MONTH STD =========================
    with cols[2]:
        if len(monthly_eligible) > 0:
            tightest = monthly_eligible.loc[
                monthly_eligible["std_roi_pct_annualized"].idxmin()
            ]
            std_val = float(tightest["std_roi_pct_annualized"])
            st.metric(
                "Tightest month std",
                f"±{std_val:.1f}%/yr",
                f"month {int(tightest['month'])} (most consistent)",
                delta_color="off",
            )
        else:
            st.metric("Tightest month std", "—",
                      f"no months with N ≥ {min_n}",
                      delta_color="off")

    # === Card 4 — LATEST YEAR ROI ============================
    with cols[3]:
        if len(yearly_eligible) >= 1:
            latest = yearly_eligible.sort_values("year").iloc[-1]
            latest_val = float(latest["median_roi_pct_annualized"])
            value_str = format_pct(latest_val, signed=True, annualized=True)
            # "vs prior year ±X.X pp" subtitle requires ≥2 years
            if len(yearly_eligible) >= 2:
                prior = yearly_eligible.sort_values("year").iloc[-2]
                delta_pp = (latest_val
                            - float(prior["median_roi_pct_annualized"]))
                sign = "+" if delta_pp >= 0 else ""
                subtitle = (
                    f"{int(latest['year'])} (vs {int(prior['year'])}: "
                    f"{sign}{delta_pp:.1f} pp)"
                )
            else:
                subtitle = (
                    f"{int(latest['year'])} (no prior year for delta)"
                )
            st.metric(
                "Latest year ROI", value_str, subtitle,
                delta_color="off",
            )
        else:
            st.metric("Latest year ROI", "—",
                      f"no years with N ≥ {min_n}",
                      delta_color="off")
