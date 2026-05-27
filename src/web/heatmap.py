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

Naming rule per §2.5: card values are percentages — labels end in %.
Per-trade ROI throughout (no annualization). Each cell's trades all
share the same hold period, so per-trade ROI is exactly comparable
within a cell.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analytics.aggregate import MIN_N_FOR_RANKING
from src.analytics.heatmap import pivot_counts, pivot_cvar, pivot_window
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

    # Honesty caption: surface the strike-selection rule the strategy
    # actually used so the analyst can see WHICH STRIKES the priced
    # trades touched (otherwise buried in src/strategies/*.py defaults).
    # Reads from the strategy implementation, not duplicated copy.
    try:
        from src.strategies.registry import get_strategy
        strat_obj = get_strategy(strategy)
        st.caption(f"ℹ Strike rule: {strat_obj.display_strike_rule()}")
    except Exception:
        # Defensive: if the registry / display_strike_rule isn't
        # available for this strategy (3rd-party plug-in, future
        # strategy that hasn't implemented the protocol yet), silently
        # skip the caption rather than crash the whole tab.
        pass

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
            format_pct(best_val, signed=True),
            _cell_label(best_idx),
            delta_color="off",
        )

    # === Card 2 — WORST CELL =================================
    with cols[1]:
        st.metric(
            "Worst cell",
            format_pct(worst_val, signed=True),
            _cell_label(worst_idx),
            delta_color="off",
        )

    # === Card 3 — MEDIAN CELL ================================
    with cols[2]:
        st.metric(
            "Median cell",
            format_pct(median_val, signed=True),
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
        the "Median ROI: +0.0%" mislead for zero-count cells.

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
            "std": grouped["roi_pct"].std(ddof=0),
            "total_pnl": grouped["net_pnl"].sum(),
            "median_roi": grouped["roi_pct"].median(),
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
                    float(row["median_roi"]), signed=True,
                )
            else:
                # Zero-count cell — every field "—" so hover doesn't
                # mislead with "Median ROI: +0.0%" on no data.
                out[i, j, 0] = "0"
                out[i, j, 1] = "—"
                out[i, j, 2] = "—"
                out[i, j, 3] = "—"
                out[i, j, 4] = "—"
    return out


# --- Right-pane mode toggle ----------------------------------
# Right pane currently shows CVaR-5% (tail-mean per cell) — the metric
# that surfaces what median ROI hides for short-vol strategies.
# Set ``_SHOW_DENSITY_PANE = True`` to swap back to the original sample-
# density (n_trades) pane. The density code path is preserved below
# (figure construction + hover template) so the flip is one constant.
_SHOW_DENSITY_PANE = False


def render_heatmaps(
    df: pd.DataFrame,
    *,
    strategy: str | None,
    symbol: str | None,
    min_n: int,
) -> None:
    """Dual Plotly heatmaps per DESIGN_SPEC §4 commit 16 + §2.3
    colormap mandate:

      Left pane  — MEDIAN ROI per (entry, exit) cell
                   Colormap: RdYlGn diverging with zmid=0 (red =
                   loss, white = breakeven, green = profit). Per
                   §2.3, NEVER sequential — a first-negative-cell
                   on a later sweep would otherwise render mid-green
                   and mislead.
      Right pane — CVaR-5% per cell (mean of worst 5% of per-trade
                   ROI outcomes). Same RdYlGn diverging colormap with
                   zmid=0: deep red = catastrophic tail, near-white =
                   breakeven worst-case, green = even the bottom 5%
                   were positive. Surfaces exactly the thing median
                   ROI hides — two cells with identical medians can
                   have wildly different worst-case behavior.

                   The original sample-density (n_trades) right pane
                   is preserved behind ``_SHOW_DENSITY_PANE`` for
                   rollback; toggle the constant to flip back.

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
    cvar = pivot_cvar(df, strategy=strategy, symbol=symbol)
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
    # Compose the full row's stats (win_rate_pct, std_roi_pct,
    # total_net_pnl, mean_roi_pct) into a 3D customdata
    # array aligned with the (entry, exit) grid. Hover renders the
    # full per-cell story per DESIGN_SPEC §2.5 + §2.2.
    custom = _build_customdata(df, strategy, symbol, values.index, values.columns)

    # === Left pane — median ROI (diverging colormap) ====
    value_z = masked.values  # NaN cells render as no-data
    value_fig = go.Figure(data=go.Heatmap(
        z=value_z,
        x=exit_ticks,
        y=entry_ticks,
        colorscale="RdYlGn",      # diverging — see §2.3
        zmid=0,                   # white at breakeven
        # Annotate each visible cell with its rounded value. Signed
        # format (+248% / -89%) matches the MoY bar annotations
        # for sign-format consistency across all annual-ROI surfaces.
        # NaN cells (masked) get blank annotations naturally.
        text=[[
            f"{value_z[i][j]:+.0f}%" if value_z[i][j] == value_z[i][j] else ""
            for j in range(value_z.shape[1])
        ] for i in range(value_z.shape[0])],
        texttemplate="%{text}",
        textfont={"size": 12},
        colorbar={"title": "%", "x": 1.02},
        hoverongaps=False,
        customdata=custom,
        hovertemplate=(
            "<b>entry %{y}, exit %{x}</b><br>"
            "Median ROI: %{customdata[4]}<br>"
            "N: %{customdata[0]}<br>"
            "Win rate: %{customdata[1]}<br>"
            "Std ROI: %{customdata[2]}<br>"
            "Net P&L: %{customdata[3]}"
            "<extra></extra>"
        ),
    ))
    value_fig.update_layout(
        title="Median ROI",
        xaxis_title="Exit offset",
        yaxis_title="Entry offset",
        height=400,
        margin=dict(l=60, r=60, t=50, b=50),
        # Phase-7 fix: Plotly heatmap traces emit ``plotly_click`` but
        # not ``plotly_selected`` on a single-click; Streamlit's
        # ``on_select="rerun"`` listens primarily for ``plotly_selected``.
        # Putting the chart into select-mode by default lets a 1-pixel
        # click register as a 1-cell box-select, so the drill-down fires.
        # If a future Plotly release changes heatmap click semantics and
        # this becomes a no-op, the documented fallback is the
        # streamlit-plotly-events package (see commit body).
        dragmode="select",
        clickmode="event+select",
    )

    # === Right pane — CVaR-5% per cell (diverging RdYlGn) ====
    # CVaR-5% = mean of the worst 5% of per-trade ROI within each cell.
    # Surfaces exactly the tail-risk dimension median ROI hides for
    # short-vol strategies: two cells with identical medians can have
    # wildly different worst-case behavior; the cell with worse CVaR is
    # the one that ends careers when a tail event arrives.
    # Same min_n mask as the value pane so the operator's "this cell is
    # too thin" gate applies uniformly across both views.
    cvar_masked = cvar.where(counts >= min_n) if not cvar.empty else cvar
    cvar_z = cvar_masked.values if not cvar_masked.empty else None
    cvar_fig = go.Figure(data=go.Heatmap(
        z=cvar_z,
        x=exit_ticks,
        y=entry_ticks,
        colorscale="RdYlGn",
        zmid=0,
        text=[[
            f"{cvar_z[i][j]:+.0f}%" if cvar_z is not None
            and cvar_z[i][j] == cvar_z[i][j] else ""
            for j in range(cvar_z.shape[1] if cvar_z is not None else 0)
        ] for i in range(cvar_z.shape[0] if cvar_z is not None else 0)],
        texttemplate="%{text}",
        textfont={"size": 12},
        colorbar={"title": "%", "x": 1.02},
        hoverongaps=False,
        customdata=custom,
        hovertemplate=(
            "<b>entry %{y}, exit %{x}</b><br>"
            "CVaR-5%%: %{z:+.1f}%%<br>"
            "Median ROI: %{customdata[4]}<br>"
            "N: %{customdata[0]}<br>"
            "Win rate: %{customdata[1]}"
            "<extra></extra>"
        ),
    ))
    cvar_fig.update_layout(
        title="CVaR-5% (mean of worst 5% of trades)",
        xaxis_title="Exit offset",
        yaxis_title="Entry offset",
        height=400,
        margin=dict(l=60, r=60, t=50, b=50),
    )

    # === Right pane — sample density (sequential blues) ====
    # PRESERVED for rollback; not rendered while _SHOW_DENSITY_PANE is
    # False. The CVaR pane above replaces it as the right-side surface
    # per the operator's tail-risk-over-sample-count preference.
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
            "Median ROI: %{customdata[4]}<br>"
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
    # Value pane uses st.plotly_chart with on_select="rerun" — this is
    # native, renders cleanly (preserves categorical T-N tick labels),
    # and the heatmap shows. The previous attempt to use
    # streamlit_plotly_events broke rendering: the chart came up blank
    # with default integer axes (the embedded React frontend in the
    # archived 2022 package is incompatible with Plotly 6.7 / Streamlit
    # 1.57 for heatmap traces).
    #
    # on_select=rerun catches plotly_selected reliably on box / lasso
    # drag, and on some browsers also on single-click (Plotly's click
    # semantics for heatmaps are weakly documented). When the click
    # path fails, the operator falls through to the manual cell-picker
    # selectbox below — that's the load-bearing fallback per
    # commit 384c65e (bug-fixed in 5b0c722).
    cols = st.columns(2)
    with cols[0]:
        selected = st.plotly_chart(
            value_fig,
            use_container_width=True,
            key="mp_heatmap_value_chart",
            on_select="rerun",
            selection_mode=("points",),
        )
        _capture_cell_selection(selected)
    with cols[1]:
        # Right-pane routing per ``_SHOW_DENSITY_PANE``. CVaR is the
        # default surface; the density chart is preserved for one-line
        # rollback if the operator wants the sample-count view back.
        if _SHOW_DENSITY_PANE:
            st.plotly_chart(
                density_fig,
                use_container_width=True,
                key="mp_heatmap_density_chart",
            )
        else:
            st.plotly_chart(
                cvar_fig,
                use_container_width=True,
                key="mp_heatmap_cvar_chart",
            )

    # std-bias tooltip text per DESIGN_SPEC §2.2 — surface as a small
    # caption below the panes since Plotly hovertemplates can't carry
    # tooltips on a column name.
    st.caption(
        "_Std ROI in the hover is observed-sample dispersion "
        "(ddof=0), not an unbiased population estimate. Bias vs "
        "ddof=1 sample-std: ~11% at n=5, ~5% at n=10, ~2.5% at n=20. "
        "Treat as a LOWER BOUND on true population spread._"
    )

    # ---- Cell picker (primary selection mechanism) -----------
    # Native st.plotly_chart on_select rarely fires on plotly heatmap
    # single-click (verified empirically across the click-handling
    # history — see click_failures.md). The dropdowns below are the
    # reliable, browser-agnostic way to select a cell; the click event
    # is kept as a possible fast-path but it's not load-bearing.
    available_entries = sorted(values.index.tolist(), reverse=True)
    available_exits = sorted(values.columns.tolist(), reverse=True)
    if available_entries and available_exits:
        st.markdown("**Pick a cell** to drill down:")
        sel = st.session_state.get("mp_heatmap_selected_cell")
        cur_entry = sel[0] if sel and sel[0] in available_entries else available_entries[0]
        cur_exit = sel[1] if sel and sel[1] in available_exits else available_exits[-1]
        fb_cols = st.columns(2)
        with fb_cols[0]:
            entry_pick = st.selectbox(
                "Entry offset",
                options=available_entries,
                index=available_entries.index(cur_entry),
                format_func=lambda v: f"T-{v}",
                key="mp_heatmap_manual_entry",
            )
        with fb_cols[1]:
            exit_pick = st.selectbox(
                "Exit offset",
                options=available_exits,
                index=available_exits.index(cur_exit),
                format_func=lambda v: f"T-{v}",
                key="mp_heatmap_manual_exit",
            )
        # Bug-fix for the original (buggy) guard: comparing against
        # ``sel`` (the click-driven selection) is the wrong reference
        # frame — on first render with sel=None, the selectbox defaults
        # always pass the != check and the picker auto-fires without
        # the operator touching anything.
        #
        # Correct pattern: stash a SEPARATE "previous picks" key. Only
        # write to mp_heatmap_selected_cell when the current picks
        # differ from the LAST OBSERVED picks (i.e. the user changed a
        # selectbox). First render is a no-op write because prev is None.
        new_manual = (entry_pick, exit_pick)
        prev_manual = st.session_state.get("_mp_heatmap_manual_prev")
        if prev_manual is not None and new_manual != prev_manual:
            if entry_pick > exit_pick:  # honor entry>exit constraint
                st.session_state["mp_heatmap_selected_cell"] = new_manual
        st.session_state["_mp_heatmap_manual_prev"] = new_manual

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

    # ---- Mode radio (Phase 7) ----------------------------------
    # Three operator-selectable below-heatmap actions. Render the
    # radio HERE so visually it sits right under the heatmaps. The
    # ACT (Drill-down vs Compare vs Export) happens back in app.py
    # via cell_action_mode() which reads the session_state key set
    # below.
    st.markdown("---")
    st.radio(
        "Cell action",
        options=["Drill-down", "Compare cells", "Export rule"],
        horizontal=True,
        key="mp_heatmap_mode",
    )


def cell_action_mode() -> str:
    """Read the current mode from session_state. ``app.py`` calls this
    after ``render_heatmaps`` to decide which below-heatmap render to
    invoke. Default is "Drill-down" — matches v0.6-ui behavior so
    existing flows are unchanged."""
    return st.session_state.get("mp_heatmap_mode", "Drill-down")


def render_compare_cells(
    df: pd.DataFrame,
    *,
    strategy: str | None,
    symbol: str | None,
    min_n: int,
) -> None:
    """Compare-cells mode.

    REVIEWER CONSTRAINT (load-bearing — failing-test enforced in
    tests/test_web_e2e.py::test_compare_cells_renders_no_p_values):
    NO p-values, NO "statistically significant" copy, NO statistical-
    test machinery. With N≈24 trades per cell, ~5% of identical-
    distribution cell-pairs would return p<0.05 by chance. Across 720
    cells × 5 (strategy, symbol) pairs an operator might compare, dozens
    of false-positive "significant differences" would surface as
    noise-disguised-as-signal. Honest framing: visual overlay + side-by-
    side stats + raw difference column ONLY.

    UX (no browser-side multi-click — click reliability documented in
    click_failures.md):
      - Selection list lives in ``st.session_state["mp_heatmap_compare_cells"]``
        as a list of ``(entry_td, exit_td)`` tuples (1-4 cells).
      - Operator picks Entry / Exit dropdowns, clicks "Add to comparison".
      - Each selected cell renders as a chip with a Remove button.
      - Once ≥2 cells are added, the comparison renders: side-by-side
        stats table + raw-difference column + overlay distribution chart.
    """
    if strategy is None or symbol is None:
        st.info(
            "Pick a strategy + symbol above, then add cells to compare."
        )
        return

    pair_df = filter_pair(df, strategy=strategy, symbol=symbol)
    if pair_df.empty:
        st.info(
            f"No data for {strategy} × {symbol} after current filters."
        )
        return

    # Available (entry, exit) combinations for this pair.
    pair_combos = sorted(
        pair_df[["entry_offset_td", "exit_offset_td"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    if not pair_combos:
        st.info(
            f"No (entry, exit) cells available for {strategy} × {symbol}."
        )
        return
    available_entries = sorted({e for (e, _) in pair_combos}, reverse=True)
    available_exits = sorted({x for (_, x) in pair_combos}, reverse=True)

    # ---- Selection management ----------------------------------
    if "mp_heatmap_compare_cells" not in st.session_state:
        st.session_state["mp_heatmap_compare_cells"] = []
    selected_cells: list[tuple[int, int]] = list(
        st.session_state["mp_heatmap_compare_cells"]
    )

    add_cols = st.columns([2, 2, 1, 1])
    with add_cols[0]:
        new_entry = st.selectbox(
            "Entry offset",
            options=available_entries,
            format_func=lambda v: f"T-{v}",
            key="mp_heatmap_compare_new_entry",
        )
    with add_cols[1]:
        new_exit = st.selectbox(
            "Exit offset",
            options=available_exits,
            format_func=lambda v: f"T-{v}",
            key="mp_heatmap_compare_new_exit",
        )
    with add_cols[2]:
        st.markdown("&nbsp;")  # vertical spacer for button alignment
        add_clicked = st.button(
            "Add to comparison",
            key="mp_heatmap_compare_add",
            disabled=(
                len(selected_cells) >= 4
                or new_entry <= new_exit
                or (new_entry, new_exit) in selected_cells
                or (new_entry, new_exit) not in pair_combos
            ),
        )
    with add_cols[3]:
        st.markdown("&nbsp;")
        clear_clicked = st.button(
            "Clear all",
            key="mp_heatmap_compare_clear",
            disabled=(len(selected_cells) == 0),
        )

    if add_clicked:
        selected_cells.append((new_entry, new_exit))
        st.session_state["mp_heatmap_compare_cells"] = selected_cells
        st.rerun()
    if clear_clicked:
        st.session_state["mp_heatmap_compare_cells"] = []
        st.rerun()

    # ---- Selected-cells chips with Remove buttons --------------
    if selected_cells:
        st.markdown("**Selected cells:**")
        for i, (e, x) in enumerate(selected_cells):
            chip_cols = st.columns([5, 1])
            chip_cols[0].markdown(f"`{i+1}.` entry T-{e} → exit T-{x}")
            if chip_cols[1].button(
                "Remove", key=f"mp_heatmap_compare_remove_{i}",
            ):
                new_list = selected_cells[:i] + selected_cells[i+1:]
                st.session_state["mp_heatmap_compare_cells"] = new_list
                st.rerun()

    if len(selected_cells) < 2:
        st.caption(
            "_Add at least 2 cells to see the side-by-side comparison._"
        )
        return

    # ---- Side-by-side stats table -----------------------------
    from src.web._format import format_inr
    st.markdown("---")
    st.markdown("### Side-by-side stats")
    stats_rows = []
    for (e, x) in selected_cells:
        cell_df = pair_df[
            (pair_df["entry_offset_td"] == e)
            & (pair_df["exit_offset_td"] == x)
        ]
        n = len(cell_df)
        if n == 0:
            stats_rows.append({
                "Cell": f"T-{e} → T-{x}",
                "N": 0,
                "Win %": "—",
                "Median ROI": "—",
                "Mean ROI": "—",
                "Std ROI": "—",
                "Σ Net P&L": "—",
            })
            continue
        roi = cell_df["roi_pct"]
        pnl = cell_df["net_pnl"]
        n_win = int((pnl > 0).sum())
        stats_rows.append({
            "Cell": f"T-{e} → T-{x}",
            "N": n,
            "Win %": f"{100.0 * n_win / n:.1f}%",
            "Median ROI": f"{roi.median():+.1f}%",
            "Mean ROI": f"{roi.mean():+.1f}%",
            "Std ROI": f"±{roi.std(ddof=0):.1f}%" if n > 1 else "—",
            "Σ Net P&L": format_inr(float(pnl.sum())),
        })
    stats_table = pd.DataFrame(stats_rows)
    st.dataframe(stats_table, hide_index=True, use_container_width=True)

    # ---- Raw-difference column (cell N+1 minus cell 1) --------
    # No p-values, no "significant". Just the raw delta the operator
    # can interpret with their own intuition + N counts.
    if len(selected_cells) >= 2:
        st.markdown("**Raw differences (vs cell 1):**")
        base_e, base_x = selected_cells[0]
        base_df = pair_df[
            (pair_df["entry_offset_td"] == base_e)
            & (pair_df["exit_offset_td"] == base_x)
        ]
        diff_rows = []
        for (e, x) in selected_cells[1:]:
            other_df = pair_df[
                (pair_df["entry_offset_td"] == e)
                & (pair_df["exit_offset_td"] == x)
            ]
            if base_df.empty or other_df.empty:
                continue
            diff_rows.append({
                "Cell": f"T-{e} → T-{x}",
                "Δ Median ROI": (
                    f"{other_df['roi_pct'].median() - base_df['roi_pct'].median():+.1f} pts"
                ),
                "Δ Mean ROI": (
                    f"{other_df['roi_pct'].mean() - base_df['roi_pct'].mean():+.1f} pts"
                ),
                "Δ Win %": (
                    f"{100.0 * ((other_df['net_pnl'] > 0).sum() / max(len(other_df), 1) - (base_df['net_pnl'] > 0).sum() / max(len(base_df), 1)):+.1f} pp"
                ),
                "Δ Σ Net P&L": format_inr(
                    float(other_df["net_pnl"].sum() - base_df["net_pnl"].sum())
                ),
            })
        if diff_rows:
            st.dataframe(
                pd.DataFrame(diff_rows), hide_index=True, use_container_width=True,
            )
        st.caption(
            "_Raw deltas only. With N ≈ 24 per cell, treat these as "
            "directional signals — not as definitive comparisons. "
            "No significance-test machinery; sample sizes are too "
            "small for that to be honest._"
        )

    # ---- Overlay distribution chart ---------------------------
    st.markdown("---")
    st.markdown("### ROI distribution overlay")
    overlay_fig = go.Figure()
    palette = ["#5dd39e", "#9aa3b2", "#f0c674", "#ff7676"]  # mockup tokens
    for i, (e, x) in enumerate(selected_cells):
        cell_df = pair_df[
            (pair_df["entry_offset_td"] == e)
            & (pair_df["exit_offset_td"] == x)
        ].sort_values("expiry")
        if cell_df.empty:
            continue
        overlay_fig.add_trace(go.Bar(
            x=cell_df["expiry"].dt.strftime("%Y-%m"),
            y=cell_df["roi_pct"],
            name=f"T-{e} → T-{x}",
            marker_color=palette[i % len(palette)],
            opacity=0.65,
        ))
    overlay_fig.update_layout(
        title="ROI per expiry — all selected cells",
        xaxis_title="Expiry",
        yaxis_title="ROI (%)",
        barmode="group",
        height=350,
        margin=dict(l=60, r=40, t=50, b=40),
    )
    st.plotly_chart(
        overlay_fig,
        use_container_width=True,
        key="mp_heatmap_compare_overlay",
    )


def render_export_rule(
    df: pd.DataFrame,
    *,
    strategy: str | None,
    symbol: str | None,
) -> None:
    """Export-rule mode (STUB). Implementation lands in
    feat(p7.heatmap.export).

    REVIEWER CONSTRAINT (do not relax in the follow-up commit):
    the exported .md MUST include MULTIPLE_COMPARISONS_CAVEAT from
    src.analytics.rank as a top-level "## Selection bias warning"
    section. Operator selecting one cell from ~3,600 candidate
    (strategy × symbol × entry × exit) rules has introduced selection
    bias the per-rule backtest doesn't capture. Re-export the constant;
    don't paraphrase or duplicate. No download path without it.
    """
    st.info(
        "**Export rule** — pick a single cell to download a "
        "deployment-ready trading rule (.md). "
        "_(Implementation pending — see feat(p7.heatmap.export).)_"
    )


# ============================================================
# Cell drill-down — Phase 7 (analyst exploration tool)
# ============================================================

def render_cell_drilldown(
    df: pd.DataFrame,
    *,
    skips_df: pd.DataFrame | None = None,
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

    Honesty contract — if any expiry was SKIPPED for this cell (e.g.
    corporate-action lot-size change, missing NSE data, no liquid
    strike), the skipped expiries are listed explicitly with their
    reason. The analyst MUST be able to see "n=21 priced + 3 skipped"
    rather than "n=21" — that's the difference between a model the
    analyst can trust and one that quietly lies by omission.

    Selection lives in ``st.session_state['mp_heatmap_selected_cell']``
    (a 2-tuple of int (entry_offset_td, exit_offset_td) populated by
    the value-pane click handler). Per-row JSON columns
    (``legs_json``, ``costs_breakdown_json``, ``margin_breakdown_json``)
    carry the full priced detail — no re-pricing needed.
    """
    import json

    if strategy is None or symbol is None:
        return
    # df may be empty (zero-row filter) but skips may still exist for
    # the selected cell — don't early-return on len(df)==0 alone.

    sel = st.session_state.get("mp_heatmap_selected_cell")
    st.markdown("---")
    if sel is None:
        st.markdown("### Cell drill-down")
        st.caption(
            "_Click any cell on the **Median ROI** heatmap above to "
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

    # Skips matching the same cell — surface even if 0 priced trades.
    if skips_df is not None and len(skips_df) > 0:
        cell_skips = skips_df[
            (skips_df["strategy"] == strategy)
            & (skips_df["symbol"] == symbol)
            & (skips_df["entry_offset_td"] == entry_td)
            & (skips_df["exit_offset_td"] == exit_td)
        ].copy().sort_values("expiry").reset_index(drop=True)
    else:
        cell_skips = pd.DataFrame()

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

    if len(rows) == 0 and len(cell_skips) == 0:
        st.info(
            f"No trades or skips for (T-{entry_td}, T-{exit_td}) on "
            f"{strategy} × {symbol} after current filters. Pick another cell."
        )
        return

    # Honesty banner: priced vs skipped count, always shown.
    n_priced = len(rows)
    n_skipped = len(cell_skips)
    if n_skipped > 0:
        st.warning(
            f"**{n_priced} priced + {n_skipped} skipped** for this cell. "
            f"Aggregate metrics below reflect ONLY the {n_priced} priced "
            f"trades — see the skipped-expiries section for which were "
            f"dropped and why."
        )

    if len(rows) == 0:
        # All expiries skipped — show only the skipped section + bail.
        _render_skipped_section(cell_skips)
        return

    # ---- Top row: 3 cards ------------------------------------
    # Selected Cell (rule card) / Median Hero / Across Years.
    # Matches the design/Complete mockup's three-question layout:
    # what is this trade? what's the result? does it hold up?
    from src.web._format import format_inr
    n = len(rows)
    pnl_series = rows["net_pnl"]
    roi_series = rows["roi_pct"]
    n_win = int((pnl_series > 0).sum())

    card_left, card_mid, card_right = st.columns([1, 1, 1])

    # --- Left card: Selected Cell (rule) ----------------------
    # The deployable trade specification. Equal weight given to every
    # field — strike rule sits next to entry/exit offsets as a peer,
    # not a tooltip, so this card is a self-contained spec the analyst
    # could screenshot for their trade journal.
    with card_left:
        st.markdown("**SELECTED CELL**")
        st.markdown(f"### {strategy} × {symbol}")
        try:
            from src.strategies.registry import get_strategy
            strike_rule = get_strategy(strategy).display_strike_rule()
        except Exception:
            strike_rule = "(strike rule unavailable for this strategy)"
        spec_rows = pd.DataFrame({
            "field": ["Entry offset", "Exit offset", "Strike rule"],
            "value": [f"T-{entry_td}", f"T-{exit_td}", strike_rule],
        })
        st.dataframe(spec_rows, hide_index=True, use_container_width=True)

    # --- Middle card: Median ROI hero + stats grid ------------
    # The headline number first, then the stats grid below so the
    # eye lands on "is this profitable?" before getting into N,
    # win-rate, etc.
    with card_mid:
        st.markdown("**MEDIAN ROI / ANNUALIZED**")
        st.metric(
            "Median ROI",
            format_pct(float(roi_series.median()), signed=True),
            label_visibility="collapsed",
        )
        # Bootstrap 95% CI under the headline — matches the honesty
        # stack from design/Complete (big number → uncertainty bound →
        # interpretation). 1,000 resamples is standard textbook B.
        # Seed is pinned so the CI is reproducible across renders;
        # caller can change via the bootstrap module if desired.
        from src.analytics.bootstrap import bootstrap_ci
        _, ci_lo, ci_hi = bootstrap_ci(roi_series.values, B=1000, seed=0)
        if not (pd.isna(ci_lo) or pd.isna(ci_hi)):
            st.caption(
                f"_95% CI {ci_lo:+.0f} … {ci_hi:+.0f}%  ·  bootstrap (B=1000)_"
            )
        # 6-cell stats grid. Sub-headers above the values so the
        # eye-fixation order matches the mockup (N → Win → Mean,
        # Std → Σ Net P&L → Worst).
        g1 = st.columns(3)
        g1[0].metric("N", f"{n}")
        g1[1].metric(
            "Win",
            format_pct(100.0 * n_win / max(n, 1)),
        )
        g1[2].metric(
            "Mean",
            format_pct(float(roi_series.mean()), signed=True),
        )
        g2 = st.columns(3)
        g2[0].metric(
            "Std (ddof=0)",
            f"{float(roi_series.std(ddof=0)):.1f}" if n > 1 else "—",
        )
        g2[1].metric("Σ Net P&L", format_inr(float(pnl_series.sum())))
        g2[2].metric("Worst trade", format_inr(float(pnl_series.min())))

    # --- Right card: Across Years (sparkline placeholder) -----
    # YoY mini-chart lands in feat(p7.drilldown.yoy_sparkline). This
    # commit just reserves the card slot so the layout is final and
    # YoY mean-ROI mini-chart — answers "does this cell's result hold
    # up across years, or is one good year carrying the average?".
    with card_right:
        st.markdown("**ACROSS YEARS**")
        yoy = (
            rows.assign(year=rows["expiry"].dt.year)
            .groupby("year")["roi_pct"]
            .mean()
            .reset_index()
            .sort_values("year")
        )
        if len(yoy) >= 2:
            spark = go.Figure()
            spark.add_trace(go.Scatter(
                x=yoy["year"].astype(str),
                y=yoy["roi_pct"],
                mode="lines+markers+text",
                line={"color": "#d4ff3a", "width": 2},
                marker={"size": 8, "color": "#d4ff3a"},
                text=[f"{v:.0f}%" for v in yoy["roi_pct"]],
                textposition="top center",
                hovertemplate="<b>%{x}</b><br>mean ROI: %{y:+.1f}%<extra></extra>",
            ))
            spark.update_layout(
                height=120,
                margin=dict(l=20, r=20, t=20, b=30),
                showlegend=False,
                xaxis={"showgrid": False, "title": None},
                yaxis={"showgrid": False, "title": None, "showticklabels": False},
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(
                spark,
                use_container_width=True,
                key="mp_drilldown_yoy_sparkline",
            )
            st.caption(
                f"_Stability check · {len(yoy)} year(s) observed in sweep._"
            )
        else:
            # Single-year cell can't show stability — be honest about
            # what's not measurable rather than draw a misleading line.
            st.caption(
                f"_Stability check unavailable — cell spans only "
                f"{len(yoy)} year. Need ≥ 2 to plot._"
            )

    # ---- Auto-detected structural callouts -------------------
    # The dashboard reads the data so the analyst doesn't have to:
    # heavy-tail signals, single-trade-carry, instability — all
    # surfaced as inline observations before the chart. Empty list
    # means "no structural surprises" — silent is honest.
    from src.analytics.observations import interpret_cell_stats
    for obs in interpret_cell_stats(rows):
        st.warning(obs)

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
            "ROI: %{y:+.1f}%<br>"
            "<extra></extra>"
        ),
    ))
    dist_fig.add_hline(
        y=float(roi_series.median()),
        line_dash="dash",
        line_color="#666",
        annotation_text=f"median {float(roi_series.median()):+.0f}%",
        annotation_position="top right",
    )
    dist_fig.update_layout(
        title="ROI per expiry — outlier + regime spotter",
        xaxis_title="Expiry",
        yaxis_title="ROI (%)",
        height=280,
        margin=dict(l=60, r=40, t=50, b=40),
        showlegend=False,
    )
    st.plotly_chart(
        dist_fig,
        use_container_width=True,
        key="mp_heatmap_drilldown_roi_dist",
    )

    # ---- Per-trade table — All / Winners / Losers tabs -------
    # Matches the design/Complete mockup's per-trade-table filter row.
    # Tab-based so the operator can switch context without losing the
    # ordering / column choice.
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
        "ROI (%)": rows["roi_pct"].round(1),
        "Margin at entry": rows["margin_at_entry"].round(0),
    })
    st.markdown("**Per-expiry trades** (sortable — click column headers)")
    tab_all, tab_wins, tab_losses = st.tabs([
        f"All ({len(rows)})",
        f"Winners ({int((rows['net_pnl'] > 0).sum())})",
        f"Losers ({int((rows['net_pnl'] <= 0).sum())})",
    ])
    with tab_all:
        st.dataframe(table, use_container_width=True, hide_index=True)
    with tab_wins:
        st.dataframe(
            table[rows["net_pnl"].values > 0],
            use_container_width=True, hide_index=True,
        )
    with tab_losses:
        st.dataframe(
            table[rows["net_pnl"].values <= 0],
            use_container_width=True, hide_index=True,
        )

    # ---- Expandable per-trade legs + cost/margin breakdowns --
    st.markdown(
        "**Per-trade detail** — click an expiry below to inspect "
        "legs, costs, and margin"
    )
    for i, row in rows.iterrows():
        exp_label = row["expiry"].strftime("%Y-%m-%d")
        roi_lbl = f"{row['roi_pct']:+.1f}%"
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

    # ---- Skipped expiries section ----------------------------
    # Always shown — if zero skips, surfaces the literary positive
    # statement; if any, lists each (expiry, reason, detail).
    if len(cell_skips) > 0:
        _render_skipped_section(cell_skips)
    else:
        st.markdown(
            f"_**No skipped expiries** — all {len(rows)} priced cleanly._"
        )

    # ---- std-bias caveat footer ------------------------------
    # Matches the mockup's footer disclosure exactly. ddof=0 sample
    # std is a LOWER BOUND on population dispersion; small-N groups
    # understate spread by ~20% at n=5, ~2.5% at n=20. Surface so the
    # analyst doesn't quote std as if it were the population spread.
    st.caption(
        "_**std (ddof=0)** is observed-sample dispersion, not a "
        "population estimate. Treat as a lower bound on true population "
        "variance — small-N groups understate spread by ~20% at n=5, "
        "~2.5% at n=20._"
    )


def _render_skipped_section(cell_skips: pd.DataFrame) -> None:
    """List the expiries for which this cell was unpriceable, with
    skip_reason and skip_detail (the original exception message).

    Surfacing these in the UI is the honesty contract — the analyst
    must be able to see WHICH expiries dropped and WHY, never just
    silently shrunken N counts.
    """
    st.markdown("---")
    st.markdown(
        f"#### Skipped expiries — {len(cell_skips)} cell-trial(s) "
        f"dropped before pricing"
    )
    st.caption(
        "_Each row is an (expiry × entry × exit) cell-trial the engine "
        "refused to price. The aggregate metrics ABOVE exclude these — "
        "they're surfaced here so you know exactly what's missing._"
    )
    has_detail = "skip_detail" in cell_skips.columns
    skip_table = pd.DataFrame({
        "Expiry": cell_skips["expiry"].dt.strftime("%Y-%m-%d"),
        "Reason": cell_skips["skip_reason"],
        "Detail": (
            cell_skips["skip_detail"].fillna("(no detail recorded — pre-skip-detail parquet)")
            if has_detail else
            pd.Series(["(no detail recorded — pre-skip-detail parquet)"] * len(cell_skips))
        ),
    })
    st.dataframe(skip_table, use_container_width=True, hide_index=True)

    # Grouped count by reason — quick "is this all the same reason
    # or mixed?" view.
    by_reason = cell_skips.groupby("skip_reason").size().reset_index(
        name="count"
    ).sort_values("count", ascending=False)
    st.markdown("**Skip-reason breakdown for this cell**")
    st.dataframe(by_reason, use_container_width=True, hide_index=True)
