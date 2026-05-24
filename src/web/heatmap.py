"""Heatmap tab — Phase 6.3 implementation.

DESIGN_SPEC §2.5 (headline strip — Heatmap row) + §4 (commits
15-17: headline, dual Plotly heatmaps, customdata hover tooltips).

This commit (p6.3.headline): the 3-card strip across the top of the
Heatmap tab. Subsequent commits add the dual Plotly heatmaps (value
+ density) and the customdata tooltip composition.

The Heatmap tab is unique: it requires the operator to pick ONE
(strategy, symbol) pair via in-tab selectors — there's no
meaningful heatmap across multiple pairs. The headline cards
report metrics for the SELECTED pair only, post-masking at the
sidebar's min_n threshold.

§2.5 Heatmap row:
  BEST CELL    pivot_window.max().max()  (post-mask)  → "(entry T-?, exit T-?)"
  WORST CELL   pivot_window.min().min()  (post-mask)  → "(entry T-?, exit T-?)"
  MEDIAN CELL  pivot_window.stack().median()           → "across N visible cells"

Naming rule per §2.5: card values are percentages — labels end
in % via format_pct(..., signed=True, annualized=True). Never a
bare number.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.analytics.aggregate import MIN_N_FOR_RANKING
from src.analytics.heatmap import pivot_counts, pivot_window
from src.web._format import format_pct
from src.web.empty_state import render_empty


def _selector(
    df: pd.DataFrame,
) -> tuple[str | None, str | None]:
    """Render the strategy + symbol selectors at the top of the tab.
    Returns the picked (strategy, symbol) — or (None, None) if the
    filtered frame has no rows. State persists in ``st.session_state``
    with mp_ prefix per SPECS §11.4."""
    if len(df) == 0:
        return None, None

    available_strategies = sorted(df["strategy"].unique().tolist())
    available_symbols = sorted(df["symbol"].unique().tolist())

    cols = st.columns(2)
    with cols[0]:
        # Default = first strategy alphabetically; persist in state.
        default_strat = st.session_state.get("mp_heatmap_strategy") \
            if st.session_state.get("mp_heatmap_strategy") in available_strategies \
            else available_strategies[0]
        strategy = st.selectbox(
            "Strategy",
            options=available_strategies,
            index=available_strategies.index(default_strat),
            key="mp_heatmap_strategy",
            help="One pair at a time — heatmaps don't aggregate meaningfully across strategies.",
        )
    with cols[1]:
        default_sym = st.session_state.get("mp_heatmap_symbol") \
            if st.session_state.get("mp_heatmap_symbol") in available_symbols \
            else available_symbols[0]
        symbol = st.selectbox(
            "Symbol",
            options=available_symbols,
            index=available_symbols.index(default_sym),
            key="mp_heatmap_symbol",
        )
    return strategy, symbol


def render_headline(
    df: pd.DataFrame,
    *,
    strategy: str | None,
    symbol: str | None,
    min_n: int,
) -> None:
    """3-card strip per DESIGN_SPEC §2.5 Heatmap row.

    Empty-frame fallback per §2.5: 0 rows after filters → every card
    "—" with subtitle "no data after filters".
    """
    cols = st.columns(3)

    # === Empty paths =========================================
    if len(df) == 0 or strategy is None or symbol is None:
        for col, label in zip(cols, ["Best cell", "Worst cell", "Median cell"]):
            with col:
                st.metric(label, "—", "no data after filters",
                          delta_color="off")
        return

    values = pivot_window(df, strategy=strategy, symbol=symbol)
    counts = pivot_counts(df, strategy=strategy, symbol=symbol)
    if values.empty:
        for col, label in zip(cols, ["Best cell", "Worst cell", "Median cell"]):
            with col:
                st.metric(label, "—", f"no cells for {strategy} × {symbol}",
                          delta_color="off")
        return

    # Mask thin cells per the §1.2 + §2.2 contract
    masked = values.where(counts >= min_n)
    if masked.notna().sum().sum() == 0:
        # Every cell masked — surface the cause honestly
        for col, label in zip(cols, ["Best cell", "Worst cell", "Median cell"]):
            with col:
                st.metric(label, "—",
                          f"all cells N < min_n={min_n}",
                          delta_color="off")
        return

    # === Compute headline stats from the masked view ========
    best_val = float(masked.max().max())
    worst_val = float(masked.min().min())
    median_val = float(masked.stack().median())
    n_visible_cells = int(masked.notna().sum().sum())

    # Identify best / worst coordinates for the subtitle.
    # stack() flattens; idxmax/idxmin give (row, col) tuple.
    stacked = masked.stack()
    best_idx = stacked.idxmax()    # (entry_offset_td, exit_offset_td)
    worst_idx = stacked.idxmin()

    def _cell_label(idx: tuple) -> str:
        e, x = idx
        return f"(entry T-{e}, exit T-{x})"

    # === Card 1 — BEST CELL ==================================
    with cols[0]:
        st.metric(
            "Best cell",
            format_pct(best_val, signed=True, annualized=True),
            _cell_label(best_idx),
            delta_color="off",
        )

    # === Card 2 — WORST CELL =================================
    with cols[1]:
        st.metric(
            "Worst cell",
            format_pct(worst_val, signed=True, annualized=True),
            _cell_label(worst_idx),
            delta_color="off",
        )

    # === Card 3 — MEDIAN CELL ================================
    with cols[2]:
        st.metric(
            "Median cell",
            format_pct(median_val, signed=True, annualized=True),
            f"across {n_visible_cells} visible cell(s)",
            delta_color="off",
        )
