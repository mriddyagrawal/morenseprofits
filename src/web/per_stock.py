"""Per-stock tab — Phase 6.5 implementation.

DESIGN_SPEC §2.5 (Per-stock row) + §1.2 (quick-switcher) + §4
(commits 22-23: headline + switcher, small-multiples dashboard).

Unlike the Heatmap and Trends tabs (which use generic in-tab
selectboxes), Per-stock uses a **button-row quick-switcher** per
§1.2 — a row of symbol buttons at the top showing symbols currently
passing the sidebar filter (truncated to top-N=8 by trade count).

Critical contract per §1.2: clicking a switcher button does NOT
mutate the sidebar filter. The sidebar stays canonical; the switcher
is navigation-within-filter only. Resolves the "two sources of
truth" hazard.

§2.5 Per-stock row:
  TOP STRATEGY         best median_roi_pct_annualized for selected symbol
  SYMBOL WIN RATE      overall win rate for the symbol
  SYMBOL TOTAL P&L     sum of net_pnl for the symbol
  STRATEGIES ABOVE BENCHMARK  count where median ann ROI > 0
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analytics.aggregate import summarize_by_stock_strategy
from src.web._format import format_inr, format_pct
from src.web.empty_state import render_empty


# Top-N to show in the quick-switcher (per §1.2 truncation rule).
_SWITCHER_TOP_N: int = 8


def _quick_switcher(df: pd.DataFrame) -> Optional[str]:
    """Render the button-row quick-switcher at the top of the
    Per-stock tab. Returns the currently-selected symbol.

    Symbols are sorted by trade count DESC, truncated to top
    ``_SWITCHER_TOP_N`` so the row stays compact.

    State key: ``mp_per_stock_symbol``. Defaults to the first
    button's symbol when no prior selection exists.

    Per §1.2 the switcher does NOT call any sidebar mutator —
    the sidebar's mp_symbols_filter is the canonical multiselect;
    this state key is independent.
    """
    if len(df) == 0:
        return None

    # Sort symbols by N DESC, take top-N for the switcher.
    counts = df.groupby("symbol").size().sort_values(ascending=False)
    candidates = counts.head(_SWITCHER_TOP_N).index.tolist()
    if not candidates:
        return None

    # Initialize state with the first candidate if not set or stale.
    current = st.session_state.get("mp_per_stock_symbol")
    if current not in candidates:
        current = candidates[0]
        st.session_state["mp_per_stock_symbol"] = current

    # Render the button row. N+1 columns: N buttons + a small right-
    # aligned caption telling the operator the switcher's role.
    cols = st.columns(len(candidates) + 1)
    for i, sym in enumerate(candidates):
        with cols[i]:
            label = sym if sym != current else f"▶ {sym}"
            if st.button(label, key=f"mp_per_stock_sw_{sym}",
                         help=f"Switch to {sym} ({int(counts[sym])} trades)"):
                st.session_state["mp_per_stock_symbol"] = sym
                st.rerun()
    with cols[-1]:
        st.caption(
            f"_Top-{_SWITCHER_TOP_N} by N. Sidebar filter canonical._"
        )

    return st.session_state["mp_per_stock_symbol"]


# ============================================================
# Headline strip — 4 cards per §2.5 Per-stock row
# ============================================================

_HEADLINE_LABELS = (
    "Top strategy",
    "Symbol win rate",
    "Symbol total P&L",
    "Strategies above benchmark",
)


def render_headline(
    df: pd.DataFrame,
    *,
    symbol: Optional[str],
    min_n: int,
) -> None:
    """4-card strip for the Per-stock tab per DESIGN_SPEC §2.5."""
    cols = st.columns(4)

    # === Empty / no-symbol paths ============================
    if len(df) == 0 or symbol is None:
        for col, label in zip(cols, _HEADLINE_LABELS):
            with col:
                st.metric(label, "—", "no data after filters",
                          delta_color="off")
        return

    sym_df = df[df["symbol"] == symbol]
    if len(sym_df) == 0:
        for col, label in zip(cols, _HEADLINE_LABELS):
            with col:
                st.metric(label, "—", f"no trades for {symbol}",
                          delta_color="off")
        return

    # === Per-symbol summary ================================
    summary = summarize_by_stock_strategy(sym_df)
    eligible = summary[summary["n_trades"] >= min_n]

    # === Card 1 — TOP STRATEGY ============================
    with cols[0]:
        if len(eligible) > 0:
            top = eligible.loc[
                eligible["median_roi_pct_annualized"].idxmax()
            ]
            st.metric(
                "Top strategy",
                str(top["strategy"]),
                f"{format_pct(top['median_roi_pct_annualized'], signed=True, annualized=True)} median ann.",
                delta_color="off",
            )
        else:
            st.metric(
                "Top strategy", "—",
                f"no strategies with N ≥ {min_n}",
                delta_color="off",
            )

    # === Card 2 — SYMBOL WIN RATE =========================
    n_total = int(len(sym_df))
    n_win = int((sym_df["net_pnl"] > 0).sum())
    with cols[1]:
        st.metric(
            "Symbol win rate",
            format_pct(100.0 * n_win / n_total),
            f"{n_win} of {n_total} trades",
            delta_color="off",
        )

    # === Card 3 — SYMBOL TOTAL P&L ========================
    total = float(sym_df["net_pnl"].sum())
    n_strategies = int(sym_df["strategy"].nunique())
    n_windows = int(
        sym_df[["entry_offset_td", "exit_offset_td"]].drop_duplicates().shape[0]
    )
    with cols[2]:
        st.metric(
            "Symbol total P&L",
            format_inr(total),
            f"{n_strategies} strategy × {n_windows} window(s)",
            delta_color="off",
        )

    # === Card 4 — STRATEGIES ABOVE BENCHMARK ==============
    n_strats_total = int(len(summary))
    n_above = int((summary["median_roi_pct_annualized"] > 0).sum())
    with cols[3]:
        st.metric(
            "Strategies above benchmark",
            f"{n_above}/{n_strats_total}",
            "median ann ROI > 0% (breakeven)",
            delta_color="off",
        )


# ============================================================
# Small-multiples dashboard — Phase 6.5 commit 23 (feat(p6.5.dash))
# ============================================================

# Cards per row in the small-multiples grid.
_CARDS_PER_ROW: int = 3


def _sparkline_figure(net_pnls: list[float]) -> go.Figure:
    """Tiny inline Plotly line for per-trade net_pnl. Chronology is
    by sweep iteration order (since trade-date sorting isn't a
    natural axis for cross-cell collections — trades from different
    expiries interleave). For Phase-7 trade-level drill-down, the
    sparkline order will switch to entry_date sort."""
    color = "rgb(0, 100, 0)" if (net_pnls and net_pnls[-1] >= 0) \
            else "rgb(200, 50, 50)"
    fig = go.Figure(data=go.Scatter(
        y=net_pnls,
        mode="lines",
        line=dict(color=color, width=2),
        hoverinfo="skip",   # sparkline = at-a-glance; full data in headline
    ))
    fig.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.4)
    fig.update_layout(
        height=70,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def render_strategy_dashboard(
    df: pd.DataFrame,
    *,
    symbol: Optional[str],
    min_n: int,
) -> None:
    """Per-symbol small-multiples grid: one card per strategy. Each
    card shows N, win %, median ann ROI, and a sparkline of the
    per-trade net_pnl series.

    Cards laid out _CARDS_PER_ROW per row.

    Empty paths:
      - 0 filtered rows / no symbol  → no_rows_after_filters via render_empty
      - symbol has no trades         → "no trades for {symbol}" info
    """
    if len(df) == 0 or symbol is None:
        render_empty("leaderboard_no_rows_after_filters")
        return

    sym_df = df[df["symbol"] == symbol]
    if len(sym_df) == 0:
        st.info(f"No trades for {symbol} in this sweep.")
        return

    # One row per strategy for this symbol; sort by median ann ROI DESC
    # so the visually-most-interesting cards are top-left.
    summary = summarize_by_stock_strategy(sym_df)
    summary = summary.sort_values(
        "median_roi_pct_annualized", ascending=False,
    ).reset_index(drop=True)

    if len(summary) == 0:
        st.info(f"No strategies for {symbol}.")
        return

    # Iterate strategies in chunks of _CARDS_PER_ROW.
    for chunk_start in range(0, len(summary), _CARDS_PER_ROW):
        chunk = summary.iloc[chunk_start:chunk_start + _CARDS_PER_ROW]
        cols = st.columns(_CARDS_PER_ROW)
        for i, (_, row) in enumerate(chunk.iterrows()):
            strat = str(row["strategy"])
            n = int(row["n_trades"])
            with cols[i]:
                # Thin-N badge so operator sees the warning even on the
                # small-multiples (not only on the headline / leaderboard).
                thin_marker = f" ⚠ N<{min_n}" if n < min_n else ""
                st.markdown(f"##### {strat}{thin_marker}")
                # Top-line stats — 3 inline metric-style columns
                sub = st.columns(3)
                with sub[0]:
                    st.caption("N")
                    st.markdown(f"**{n}**")
                with sub[1]:
                    st.caption("Win %")
                    st.markdown(f"**{format_pct(row['win_rate_pct'])}**")
                with sub[2]:
                    st.caption("Median ROI/yr")
                    st.markdown(
                        f"**{format_pct(row['median_roi_pct_annualized'], signed=True, annualized=True)}**"
                    )
                # Sparkline of this strategy's per-trade net_pnl
                strat_trades = sym_df[sym_df["strategy"] == strat]
                if "net_pnl" in strat_trades.columns and len(strat_trades) >= 2:
                    series = strat_trades["net_pnl"].astype(float).tolist()
                    st.plotly_chart(
                        _sparkline_figure(series),
                        use_container_width=True,
                        config={"displayModeBar": False},
                    )
                else:
                    # 0-1 trades — sparkline isn't meaningful
                    st.caption("_sparkline needs ≥2 trades_")
