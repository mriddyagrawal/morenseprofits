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


# ============================================================
# YoY line chart — Phase 6.4 commit 19 (feat(p6.4.yoy))
# ============================================================

def render_yoy(
    df: pd.DataFrame,
    *,
    strategy: Optional[str],
    symbol: Optional[str],
    min_n: int,
) -> None:
    """Plotly line chart: median_roi_pct_annualized over years for
    one (strategy, symbol) pair. Years with N < min_n excluded.

    Empty-state per DESIGN_SPEC §2.6: <2 distinct eligible years →
    trends_yoy_single_year message ("YoY decay needs ≥2 years").
    The current Q1-2024 verify set hits this branch on every
    (strategy, symbol) — operator sees an explicit "this sweep
    covers 1 year(s)" message, not an empty chart.
    """
    if len(df) == 0 or strategy is None or symbol is None:
        render_empty("leaderboard_no_rows_after_filters")
        return

    pair = df[(df["strategy"] == strategy) & (df["symbol"] == symbol)]
    if len(pair) == 0:
        st.info(f"No trades for {strategy} × {symbol}.")
        return

    yearly = summarize_by_year(pair)
    eligible = yearly[yearly["n_trades"] >= min_n].sort_values("year")
    n_years = int(eligible["year"].nunique())
    if n_years < 2:
        render_empty("trends_yoy_single_year", n_years=n_years)
        return

    years = eligible["year"].astype(int).tolist()
    medians = eligible["median_roi_pct_annualized"].astype(float).tolist()
    n_per_year = eligible["n_trades"].astype(int).tolist()

    fig = go.Figure(data=go.Scatter(
        x=years,
        y=medians,
        mode="lines+markers",
        line=dict(color="rgb(0, 100, 0)", width=3),
        marker=dict(size=10),
        # Custom hover: surface N alongside median so a "decay" call
        # can be sanity-checked against sample size per the
        # DESIGN_SPEC §10 user-journey step 4.
        customdata=[[n] for n in n_per_year],
        hovertemplate=(
            "<b>%{x}</b><br>"
            "Median ROI/yr: %{y:+.1f}%<br>"
            "N: %{customdata[0]}"
            "<extra></extra>"
        ),
    ))
    # Anchor at zero so the line tells the truth — a small positive
    # drift on a chart auto-zoomed to [40%, 60%] reads more dramatic
    # than the underlying data warrants.
    fig.update_layout(
        title=f"YoY median ROI/yr — {strategy} × {symbol}",
        xaxis_title="Year",
        yaxis_title="Median ROI/yr (%)",
        height=380,
        margin=dict(l=60, r=40, t=50, b=50),
        showlegend=False,
    )
    fig.add_hline(
        y=0, line_dash="dot", line_color="gray",
        annotation_text="breakeven",
        annotation_position="bottom right",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        f"Years with N ≥ {min_n} included. Sister chart below "
        f"(win-rate + sample size) helps distinguish real drift from "
        f"thin-sample noise per DESIGN_SPEC §10 step 4."
    )
