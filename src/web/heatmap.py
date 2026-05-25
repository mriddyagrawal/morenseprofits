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
# Cell selection capture — Phase 7 drill-down
# ============================================================

def _capture_cell_selection(selected) -> None:
    """Translate Plotly click-event payload into
    ``st.session_state['mp_heatmap_selected_cell'] = (entry_td, exit_td)``.

    Plotly heatmap clicks return ``x`` and ``y`` as tick labels like
    "T-15"/"T-3"; parse the integer back out. Idempotent — repeated
    clicks on the same cell are a no-op; clicking a new cell replaces
    the prior selection."""
    if selected is None:
        return
    pts = selected.get("selection", {}).get("points", []) if hasattr(
        selected, "get"
    ) else getattr(getattr(selected, "selection", None), "points", []) or []
    if not pts:
        return
    pt = pts[0]
    x_label = pt.get("x") if isinstance(pt, dict) else getattr(pt, "x", None)
    y_label = pt.get("y") if isinstance(pt, dict) else getattr(pt, "y", None)
    if not isinstance(x_label, str) or not isinstance(y_label, str):
        return
    try:
        exit_td = int(x_label.lstrip("T-"))
        entry_td = int(y_label.lstrip("T-"))
    except (ValueError, AttributeError):
        return
    st.session_state["mp_heatmap_selected_cell"] = (entry_td, exit_td)


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
        # Annotate each visible cell with its rounded value. Signed
        # format (+248%/yr / -89%/yr) matches the MoY bar annotations
        # for sign-format consistency across all annual-ROI surfaces.
        # NaN cells (masked) get blank annotations naturally.
        text=[[
            f"{value_z[i][j]:+.0f}%/yr" if value_z[i][j] == value_z[i][j] else ""
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
    # Value pane has on_select so clicking a cell drives the drilldown
    # below (render_cell_drilldown reads mp_heatmap_selected_cell).
    cols = st.columns(2)
    with cols[0]:
        selected = st.plotly_chart(
            value_fig,
            use_container_width=True,
            key="mp_heatmap_value_chart",
            on_select="rerun",
            selection_mode="points",
        )
        _capture_cell_selection(selected)
    with cols[1]:
        st.plotly_chart(
            density_fig,
            use_container_width=True,
            key="mp_heatmap_density_chart",
        )

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


# ============================================================
# Cell drill-down — Phase 7 (analyst exploration tool)
# ============================================================

def render_cell_drilldown(
    df: pd.DataFrame,
    *,
    strategy: str | None,
    symbol: str | None,
) -> None:
    """Drill-down panel for a heatmap cell the analyst clicked.

    The heatmap aggregates ~24 expiries into a single colored cell;
    the median hides the distribution. This view restores it: see
    whether a cell's median is representative or whether it's hiding
    fat tails, regime-specific behavior (e.g. only the 2024 expiries
    worked), or one outlier carrying the average. Then drill into any
    specific trade's legs, costs, and margin to understand WHY.

    Selection lives in ``st.session_state['mp_heatmap_selected_cell']``
    (a 2-tuple of int (entry_offset_td, exit_offset_td) populated by
    the value-pane click handler). Per-row JSON columns
    (``legs_json``, ``costs_breakdown_json``, ``margin_breakdown_json``)
    carry the full priced detail — no re-pricing needed.
    """
    import json

    if strategy is None or symbol is None or len(df) == 0:
        return

    sel = st.session_state.get("mp_heatmap_selected_cell")
    st.markdown("---")
    if sel is None:
        st.markdown("### Cell drill-down")
        st.caption(
            "_Click any cell on the **Median ROI/yr** heatmap above to "
            "see the underlying trades, distribution, and full per-leg "
            "/ per-cost breakdown._"
        )
        return

    entry_td, exit_td = sel
    rows = df[
        (df["strategy"] == strategy)
        & (df["symbol"] == symbol)
        & (df["entry_offset_td"] == entry_td)
        & (df["exit_offset_td"] == exit_td)
    ].copy().sort_values("expiry").reset_index(drop=True)

    hdr_l, hdr_r = st.columns([5, 1])
    with hdr_l:
        st.markdown(
            f"### Cell drill-down — {strategy} × {symbol}: "
            f"entry T-{entry_td} → exit T-{exit_td}"
        )
    with hdr_r:
        if st.button("Clear", key="mp_heatmap_clear_drilldown"):
            st.session_state.pop("mp_heatmap_selected_cell", None)
            st.rerun()

    if len(rows) == 0:
        st.info(
            f"No trades for (T-{entry_td}, T-{exit_td}) on {strategy} × "
            f"{symbol} after current filters. Pick another cell."
        )
        return

    # ---- Summary stats row -----------------------------------
    from src.web._format import format_inr
    n = len(rows)
    pnl_series = rows["net_pnl"]
    roi_series = rows["roi_pct_annualized"]
    n_win = int((pnl_series > 0).sum())
    s = st.columns(6)
    s[0].metric("N trades", f"{n}")
    s[1].metric(
        "Win rate", format_pct(100.0 * n_win / max(n, 1))
    )
    s[2].metric(
        "Median ROI/yr",
        format_pct(float(roi_series.median()), signed=True, annualized=True),
    )
    s[3].metric(
        "Mean ROI/yr",
        format_pct(float(roi_series.mean()), signed=True, annualized=True),
    )
    s[4].metric(
        "Best ROI/yr",
        format_pct(float(roi_series.max()), signed=True, annualized=True),
    )
    s[5].metric(
        "Worst ROI/yr",
        format_pct(float(roi_series.min()), signed=True, annualized=True),
    )

    s2 = st.columns(4)
    s2[0].metric(
        "Total net P&L", format_inr(float(pnl_series.sum()))
    )
    s2[1].metric(
        "Best single trade", format_inr(float(pnl_series.max()))
    )
    s2[2].metric(
        "Worst single trade", format_inr(float(pnl_series.min()))
    )
    s2[3].metric(
        "Std ROI/yr",
        f"±{float(roi_series.std(ddof=0)):.1f}%"
        if n > 1 else "—",
    )

    # ---- ROI distribution mini-chart -------------------------
    # Lets the analyst see at a glance whether the cell's median is
    # representative or whether it's hiding fat tails / regime split.
    dist_fig = go.Figure()
    dist_fig.add_trace(go.Bar(
        x=rows["expiry"].dt.strftime("%Y-%m"),
        y=roi_series,
        marker_color=[
            "#2ca02c" if v > 0 else "#d62728" for v in roi_series
        ],
        text=[f"{v:+.0f}%" for v in roi_series],
        textposition="outside",
        hovertemplate=(
            "<b>%{x}</b><br>"
            "ROI/yr: %{y:+.1f}%<br>"
            "<extra></extra>"
        ),
    ))
    dist_fig.add_hline(
        y=float(roi_series.median()),
        line_dash="dash",
        line_color="#666",
        annotation_text=f"median {float(roi_series.median()):+.0f}%/yr",
        annotation_position="top right",
    )
    dist_fig.update_layout(
        title="ROI/yr per expiry — outlier + regime spotter",
        xaxis_title="Expiry",
        yaxis_title="ROI/yr (%)",
        height=280,
        margin=dict(l=60, r=40, t=50, b=40),
        showlegend=False,
    )
    st.plotly_chart(
        dist_fig,
        use_container_width=True,
        key="mp_heatmap_drilldown_roi_dist",
    )

    # ---- Per-trade table -------------------------------------
    table = pd.DataFrame({
        "Expiry": rows["expiry"].dt.strftime("%Y-%m-%d"),
        "Entry date": rows["entry_date"].dt.strftime("%Y-%m-%d"),
        "Exit date": rows["exit_date"].dt.strftime("%Y-%m-%d"),
        "Hold (TD)": rows["hold_trading_days"],
        "Spot entry": rows["entry_spot"].round(2),
        "Spot exit": rows["exit_spot"].round(2),
        "Gross P&L": rows["gross_pnl"].round(2),
        "Costs": rows["costs"].round(2),
        "Net P&L": rows["net_pnl"].round(2),
        "ROI (%)": rows["roi_pct"].round(2),
        "ROI/yr (%)": rows["roi_pct_annualized"].round(1),
        "Margin at entry": rows["margin_at_entry"].round(0),
    })
    st.markdown("**Per-expiry trades** (sortable — click column headers)")
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
    )

    # ---- Expandable per-trade legs + cost/margin breakdowns --
    st.markdown(
        "**Per-trade detail** — click an expiry below to inspect "
        "legs, costs, and margin"
    )
    for i, row in rows.iterrows():
        exp_label = row["expiry"].strftime("%Y-%m-%d")
        roi_lbl = f"{row['roi_pct_annualized']:+.1f}%/yr"
        pnl_lbl = format_inr(float(row["net_pnl"]))
        with st.expander(
            f"Expiry {exp_label} — Net P&L {pnl_lbl} ({roi_lbl})"
        ):
            # Legs
            try:
                legs = json.loads(row["legs_json"])
                legs_df = pd.DataFrame(legs)
                st.markdown("**Legs**")
                st.dataframe(legs_df, use_container_width=True, hide_index=True)
            except (ValueError, TypeError):
                st.warning("legs_json malformed for this row.")

            cols_bd = st.columns(2)
            with cols_bd[0]:
                st.markdown("**Costs breakdown** (₹)")
                try:
                    cb = json.loads(row["costs_breakdown_json"])
                    cb_df = pd.DataFrame(
                        [(k, round(v, 2)) for k, v in cb.items()],
                        columns=["component", "amount"],
                    )
                    st.dataframe(
                        cb_df, use_container_width=True, hide_index=True
                    )
                except (ValueError, TypeError):
                    st.warning("costs_breakdown_json malformed.")
            with cols_bd[1]:
                st.markdown("**Margin breakdown** (₹)")
                try:
                    mb = json.loads(row["margin_breakdown_json"])
                    mb_df = pd.DataFrame(
                        [(k, round(v, 4) if isinstance(v, float) else v)
                         for k, v in mb.items()],
                        columns=["component", "value"],
                    )
                    st.dataframe(
                        mb_df, use_container_width=True, hide_index=True
                    )
                except (ValueError, TypeError):
                    st.warning("margin_breakdown_json malformed.")
