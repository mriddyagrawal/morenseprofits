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
import plotly.graph_objects as go
import streamlit as st

from src.analytics.aggregate import MIN_N_FOR_RANKING
from src.analytics.heatmap import pivot_counts, pivot_window
from src.web._filter import filter_pair
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


# ============================================================
# Dual heatmaps — Phase 6.3 commit 16 (feat(p6.3.pivot))
# ============================================================

def _format_offset_label(prefix: str, value: int) -> str:
    """Render an offset label like "T-15" for the axis tick labels.
    Used uniformly on both heatmaps so coordinate hover matches the
    axis titles."""
    return f"{prefix}-{int(value)}"


def _build_customdata(
    df: pd.DataFrame,
    strategy: str,
    symbol: str,
    entry_index,
    exit_columns,
):
    """Build a (H, W, 5) per-cell-stats array of STRINGS for Plotly's
    customdata channel:

        customdata[i][j] = [n_trades_str, win_rate_str, std_roi_str,
                            total_net_pnl_str, median_roi_str]

    Aligned with the value/density heatmap grids (entry rows × exit
    columns).

    All values are PRE-FORMATTED strings — never bare numbers — so
    the hovertemplate can interpolate them directly without Plotly's
    own format specifiers. Rationale:

      - format_inr's lakhs/crores notation requires Python logic
        Plotly's %{customdata[N]:,.0f} can't replicate (would
        break §2.7 contract for cells in the L / Cr range).
      - Empty cells (no trades) render as "—" universally — fixes
        the "Median ROI/yr: +0.0%" mislead for zero-count cells.

    Implementation: vectorized via a single groupby + reindex,
    replaces the prior O(H × W × N) nested-loop filter — important
    once the sweep grows past a hundred cells.
    """
    import numpy as np

    from src.web._format import format_inr, format_pct

    pair = filter_pair(df, strategy=strategy, symbol=symbol)
    H, W = len(entry_index), len(exit_columns)

    # Vectorized per-cell stats via single groupby — replaces the
    # nested H×W loop. Each (entry, exit) gets one summary row.
    if len(pair) > 0:
        grouped = pair.groupby(["entry_offset_td", "exit_offset_td"])
        stats = pd.DataFrame({
            "n": grouped.size(),
            "n_win": (pair["net_pnl"] > 0).groupby(
                [pair["entry_offset_td"], pair["exit_offset_td"]]
            ).sum(),
            "std": grouped["roi_pct_annualized"].std(ddof=0),
            "total_pnl": grouped["net_pnl"].sum(),
            "median_roi": grouped["roi_pct_annualized"].median(),
        }).reset_index()
        stats["win_rate"] = 100.0 * stats["n_win"] / stats["n"]
        # Index lookup by (entry, exit) tuple
        stats = stats.set_index(["entry_offset_td", "exit_offset_td"])
    else:
        stats = pd.DataFrame()

    out = np.empty((H, W, 5), dtype=object)
    for i, e in enumerate(entry_index):
        for j, x in enumerate(exit_columns):
            if (e, x) in stats.index:
                row = stats.loc[(e, x)]
                n_val = int(row["n"])
                out[i, j, 0] = f"{n_val}"
                out[i, j, 1] = format_pct(float(row["win_rate"]))
                out[i, j, 2] = (
                    f"±{float(row['std']):.1f}%"
                    if pd.notna(row["std"]) else "—"
                )
                out[i, j, 3] = format_inr(float(row["total_pnl"]))
                out[i, j, 4] = format_pct(
                    float(row["median_roi"]), signed=True, annualized=True,
                )
            else:
                # Zero-count cell — every field "—" so hover doesn't
                # mislead with "Median ROI/yr: +0.0%" on no data.
                out[i, j, 0] = "0"
                out[i, j, 1] = "—"
                out[i, j, 2] = "—"
                out[i, j, 3] = "—"
                out[i, j, 4] = "—"
    return out


def render_heatmaps(
    df: pd.DataFrame,
    *,
    strategy: str | None,
    symbol: str | None,
    min_n: int,
) -> None:
    """Dual Plotly heatmaps per DESIGN_SPEC §4 commit 16 + §2.3
    colormap mandate:

      Left pane  — MEDIAN ROI/yr per (entry, exit) cell
                   Colormap: RdYlGn diverging with zmid=0 (red =
                   loss, white = breakeven, green = profit). Per
                   §2.3, NEVER sequential — a first-negative-cell
                   on a later sweep would otherwise render mid-green
                   and mislead.
      Right pane — SAMPLE DENSITY (n_trades per cell). Sequential
                   Blues colormap; 0 = white.

    Both panes share orientation per DESIGN_SPEC §2.2: index =
    entry_offset_td DESC (T-15 at top), columns = exit_offset_td
    DESC (T-3 left, T-1 right).

    Empty-state branches use src.web.empty_state per §2.6:
      - 0 filtered rows                → no_rows_after_filters
      - sweep has <2 entry OR <2 exit  → heatmap_single_axis
      - every cell masked at min_n     → heatmap_all_masked
    """
    if len(df) == 0:
        render_empty("leaderboard_no_rows_after_filters")
        return
    if strategy is None or symbol is None:
        render_empty("leaderboard_no_rows_after_filters")
        return

    values = pivot_window(df, strategy=strategy, symbol=symbol)
    counts = pivot_counts(df, strategy=strategy, symbol=symbol)
    if values.empty:
        st.info(
            f"No (entry × exit) cells available for {strategy} × {symbol}. "
            f"Pick another pair."
        )
        return

    n_entry = int(values.shape[0])
    n_exit = int(values.shape[1])
    if n_entry < 2 or n_exit < 2:
        render_empty(
            "heatmap_single_axis",
            n_entry=n_entry, n_exit=n_exit,
        )
        return

    # Apply the min_n mask once; reused for both panes (the mask
    # decides which value cells are visible; the density pane shows
    # the raw counts so the operator sees WHY a cell was masked).
    masked = values.where(counts >= min_n)
    if masked.notna().sum().sum() == 0:
        render_empty("heatmap_all_masked", min_n=min_n)
        return

    # Convert axis labels to "T-N" form once so both panes match.
    entry_ticks = [_format_offset_label("T", v) for v in values.index]
    exit_ticks = [_format_offset_label("T", v) for v in values.columns]

    # === Per-cell customdata for hover tooltips (p6.3.hover) ===
    # Compose the full row's stats (win_rate_pct, std_roi_pct_annualized,
    # total_net_pnl, mean_roi_pct_annualized) into a 3D customdata
    # array aligned with the (entry, exit) grid. Hover renders the
    # full per-cell story per DESIGN_SPEC §2.5 + §2.2.
    custom = _build_customdata(df, strategy, symbol, values.index, values.columns)

    # === Left pane — median ROI/yr (diverging colormap) ====
    value_z = masked.values  # NaN cells render as no-data
    value_fig = go.Figure(data=go.Heatmap(
        z=value_z,
        x=exit_ticks,
        y=entry_ticks,
        colorscale="RdYlGn",      # diverging — see §2.3
        zmid=0,                   # white at breakeven
        # Annotate each visible cell with its rounded value.
        # NaN cells (masked) get blank annotations naturally.
        text=[[
            f"{value_z[i][j]:.0f}%/yr" if value_z[i][j] == value_z[i][j] else ""
            for j in range(value_z.shape[1])
        ] for i in range(value_z.shape[0])],
        texttemplate="%{text}",
        textfont={"size": 12},
        colorbar={"title": "%/yr", "x": 1.02},
        hoverongaps=False,
        customdata=custom,
        hovertemplate=(
            "<b>entry %{y}, exit %{x}</b><br>"
            "Median ROI/yr: %{customdata[4]}<br>"
            "N: %{customdata[0]}<br>"
            "Win rate: %{customdata[1]}<br>"
            "Std ROI/yr: %{customdata[2]}<br>"
            "Net P&L: %{customdata[3]}"
            "<extra></extra>"
        ),
    ))
    value_fig.update_layout(
        title="Median ROI/yr",
        xaxis_title="Exit offset",
        yaxis_title="Entry offset",
        height=400,
        margin=dict(l=60, r=60, t=50, b=50),
    )

    # === Right pane — sample density (sequential blues) ====
    density_z = counts.values
    density_fig = go.Figure(data=go.Heatmap(
        z=density_z,
        x=exit_ticks,
        y=entry_ticks,
        colorscale="Blues",
        zmin=0,
        text=[[
            str(int(density_z[i][j])) if density_z[i][j] > 0 else ""
            for j in range(density_z.shape[1])
        ] for i in range(density_z.shape[0])],
        texttemplate="%{text}",
        textfont={"size": 12},
        colorbar={"title": "N", "x": 1.02},
        hoverongaps=False,
        customdata=custom,
        hovertemplate=(
            "<b>entry %{y}, exit %{x}</b><br>"
            "N: %{z}<br>"
            "Median ROI/yr: %{customdata[4]}<br>"
            "Win rate: %{customdata[1]}"
            "<extra></extra>"
        ),
    ))
    density_fig.update_layout(
        title="Sample density (trades per cell)",
        xaxis_title="Exit offset",
        yaxis_title="Entry offset",
        height=400,
        margin=dict(l=60, r=60, t=50, b=50),
    )

    # Side-by-side render. Each chart claims its column.
    cols = st.columns(2)
    with cols[0]:
        st.plotly_chart(value_fig, use_container_width=True)
    with cols[1]:
        st.plotly_chart(density_fig, use_container_width=True)

    # std-bias tooltip text per DESIGN_SPEC §2.2 — surface as a small
    # caption below the panes since Plotly hovertemplates can't carry
    # tooltips on a column name.
    st.caption(
        "_Std ROI/yr in the hover is observed-sample dispersion "
        "(ddof=0), not an unbiased population estimate. Bias vs "
        "ddof=1 sample-std: ~11% at n=5, ~5% at n=10, ~2.5% at n=20. "
        "Treat as a LOWER BOUND on true population spread._"
    )

    # Footer caption — reinforces the masking story.
    n_masked = int(values.notna().sum().sum() -
                   masked.notna().sum().sum())
    if n_masked > 0:
        st.caption(
            f"{n_masked} cell(s) masked from the value pane at "
            f"min_n={min_n} (still visible in the density pane). "
            f"Lower the threshold via the sidebar slider to inspect "
            f"thin cells."
        )
