"""Portfolio tab — Phase 9.4 SKELETON commit (9.4.1).

PORTFOLIO_MEMOIR.md §1 #1 + §4 + mockup at
``DESIGN/Complete/components/portfolio.jsx``. The operator-facing
surface for the v1 Portfolio Foundation: equity curve of a rule-
based portfolio backtest with regime + earnings + IVP filters,
risk metrics, 2-D diagnostic, drilldown into per-contract trajectory.

This commit (skeleton) ships:
  - Page header + standing caveats
  - Static banners (N=5 universe / SURVIVORSHIP from memoir §11)
  - **Regime banner** — ON/OFF + India VIX percentile + positions-
    today/N. Wires Phase 9.6's ``current_regime_state`` directly.
  - **Strategy config block** — collapsible panel with universe
    size, strategy choice, entry/exit offsets, sizing mode, regime
    gate toggle, IVP filter range, earnings filter toggle.

Deferred to follow-on commits in this cluster:
  - Equity curve + drawdown subplot       → Phase 9.4.2
  - Headline metrics strip                → Phase 9.4.3
  - Year-by-year stability table          → Phase 9.4.4
  - Worst-10-days panel                   → Phase 9.4.5
  - Concentration + correlation           → Phase 9.4.6
  - 2-D regime × IVP diagnostic           → Phase 9.4.7
  - IVP sensitivity strip                 → Phase 9.4.8
  - Cycle drilldown                       → Phase 9.4.9
  - Deeplink writer (Portfolio → Inspect) → Phase 9.4.10

Routing pattern: this tab is one option in the
``st.radio(horizontal=True, key="mp_active_tab")`` shell in
``app.py`` (the ``st.navigation`` migration was shelved on
2026-06-06 per ``DESIGN/NAVIGATION_REFACTOR.md`` — keeping the
radio kludge for v1). URL routing: ``?tab=Portfolio``.

Session state contract: all config knobs live under the
``mp_pf_*`` prefix so the Tweaks panel + sidebar widgets can
coexist without key collisions.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.analytics.portfolio import (
    cycle_pnl_series,
    drawdown_series,
    equity_curve,
)
from src.analytics.ivp import compute_ivp
from src.analytics.portfolio_metrics import (
    calmar,
    cycle_returns,
    max_drawdown_inr,
    simple_annualized_return,
    sortino,
    ulcer_index,
)
from src.analytics.regime_ivp_diagnostic import (
    RegimeIvpBreakdown,
    regime_x_ivp_breakdown,
)
from src.analytics.regime import (
    current_regime_state,
    default_regime_signal,
    regime_percentile,
    regime_state,
)


# Session-state keys. Prefixed ``mp_pf_`` (morenseprofits portfolio)
# so they're greppable and namespaced from the sidebar /
# leaderboard / inspect keys.
_SS_UNIVERSE_N = "mp_pf_universe_n"
_SS_STRATEGY = "mp_pf_strategy"
_SS_ENTRY_OFFSET = "mp_pf_entry_offset_td"
_SS_EXIT_OFFSET = "mp_pf_exit_offset_td"
_SS_SIZING = "mp_pf_sizing"
_SS_REGIME_GATE = "mp_pf_regime_gate"
_SS_IVP_BAND = "mp_pf_ivp_band"
_SS_EARNINGS_FILTER = "mp_pf_earnings_filter"
_SS_AS_OF = "mp_pf_as_of"

# Defaults match the mockup's pfCfg in DESIGN/Complete/app.jsx
# lines 30-38. Override via the strategy config block UI.
_DEFAULTS: dict[str, Any] = {
    _SS_UNIVERSE_N: 5,
    _SS_STRATEGY: "short_strangle",
    _SS_ENTRY_OFFSET: 15,
    _SS_EXIT_OFFSET: 3,
    _SS_SIZING: "equal_margin",
    _SS_REGIME_GATE: True,
    _SS_IVP_BAND: (60, 100),
    _SS_EARNINGS_FILTER: True,
}

# Strategy display labels mirror the mockup's labels.
_STRATEGY_LABELS = {
    "short_strangle": "Short Strangle",
    "short_straddle": "Short Straddle",
    "iron_condor":    "Iron Condor",
    "long_strangle":  "Long Strangle",
    "long_straddle":  "Long Straddle",
}
_STRATEGY_KEYS = list(_STRATEGY_LABELS.keys())

# Sizing modes (mockup §B / memoir §7). v1 ships equal_margin;
# vol_targeted is Phase 10.2 deferred.
_SIZING_LABELS = {
    "equal_margin":  "Equal margin",
    "vol_targeted":  "Vol-targeted (Phase 10.2 deferred)",
}
_SIZING_KEYS = list(_SIZING_LABELS.keys())

# Regime gate uses memoir §3.1 default threshold = 75. Operator
# can override via the future sensitivity strip (Phase 9.4.8).
_REGIME_THRESHOLD_PCT = 75.0
_REGIME_LOOKBACK_TD = 252

# v1 starting capital for the equity curve. ₹10L is a realistic
# Indian retail-trader allocation; pinned here as a constant so a
# future change is greppable. NOT user-tunable in 9.4.2 — the
# Calmar / Ulcer / Sortino ratios in 9.4.3 are scale-invariant
# under equal-margin sizing, so the chart's y-axis labels are the
# only thing affected.
_DEFAULT_STARTING_CAPITAL = 1_000_000.0

# Plot dimensions — match the mockup's aspect ratio. The
# drawdown subplot gets ~30% of the height per Martin's
# canonical convention (Ulcer Index paper).
_EQUITY_PLOT_HEIGHT_PX = 380
_EQUITY_SUBPLOT_ROW_HEIGHTS = (0.7, 0.3)


def _seed_session_state() -> None:
    """First-render-only seed for the portfolio session keys.
    Mirrors the inspect.py pattern (``_initialize_session_state``)
    so URL params / Tweaks panel changes don't get clobbered on
    re-render."""
    for key, default in _DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = default


def _resolve_as_of() -> date:
    """Resolve the 'as-of' date for the regime banner.

    For v1 skeleton: use today (date.today()). Phase 9.4 future
    commits may add an explicit date picker; until then the banner
    surfaces "today's regime" against the cached India VIX
    history. Cold-cache (no VIX data for today) → ``current_regime_state``
    returns OFF per memoir §F9 skip-when-uncertain.
    """
    return st.session_state.get(_SS_AS_OF) or date.today()


def _render_header() -> None:
    """Page title strip — mirrors mockup ``<div className="page-h">``
    but in Streamlit-native markdown. No fancy styling; the mockup's
    serif accent isn't worth a custom CSS pass for the skeleton."""
    st.markdown("## Portfolio")
    st.caption(
        "build_portfolio_history(rules) · monthly cadence · "
        "research-only · no live deployment"
    )


def _render_banners() -> None:
    """The two standing caveat banners from mockup §banners.

    Note: the mockup's PROXY banner ("regime gate uses trailing-21d
    realized vol as a stand-in for India VIX") is DROPPED here —
    Phase 9.6 (commit 50d51c8) shipped real India VIX integration,
    so the PROXY caveat is no longer accurate.

    The N=5 and SURVIVORSHIP banners stay until Phase 10.1
    universe-widening lands.
    """
    col1, col2 = st.columns(2)
    with col1:
        st.info(
            "**N=5** — Universe is 5 names. "
            "Calmar / Ulcer / correlation are **directional only**. "
            "Widen to ~30 names before trusting diversification claims. "
            "*(memoir §11)*"
        )
    with col2:
        st.warning(
            "**SURVIVORSHIP** — Universe is survivor blue-chips. "
            "Delisted / merged names from 2023–24 excluded → "
            "returns biased upward. Phase 10.1 widens to ~180–220 "
            "names for honest survivorship-free analysis."
        )


def _render_regime_banner() -> None:
    """ON/OFF regime banner with India VIX percentile + positions-
    today/N. Wires ``current_regime_state`` directly.

    Memoir §3.7 + Phase 9.6: regime state computed against trailing-
    252-TD India VIX percentile, threshold 75. NaN history → OFF
    per F9 skip-when-uncertain.

    "positions today" placeholder: requires the candidate-selection
    pipeline (Phase 9.4.9 cycle drilldown). For the skeleton we
    render an em-dash so the layout is correct but no fake number
    is surfaced.
    """
    as_of = _resolve_as_of()
    universe_n = int(st.session_state[_SS_UNIVERSE_N])

    try:
        state = current_regime_state(
            as_of,
            threshold_pct=_REGIME_THRESHOLD_PCT,
            lookback_td=_REGIME_LOOKBACK_TD,
            offline=True,  # never touch the network from the UI
        )
        # Compute percentile for the banner stat — separate call
        # so the banner can show the actual value alongside the
        # ON/OFF verdict.
        from datetime import timedelta

        # Use the same backfill cushion convention as
        # current_regime_state.
        backfill_days = int(_REGIME_LOOKBACK_TD * 365 / 252) + 30
        signal = default_regime_signal(
            as_of - timedelta(days=backfill_days), as_of,
            offline=True,
        )
        pct = regime_percentile(
            signal, as_of, lookback_td=_REGIME_LOOKBACK_TD,
        )
    except Exception as e:
        # Cold cache / loader failure → degrade gracefully to OFF
        # with a transparent caption. Better than crashing the
        # whole tab.
        state = "OFF"
        pct = float("nan")
        st.caption(
            f"_Regime signal unavailable: {type(e).__name__}. "
            f"Run `scripts/prefetch_universe.py --vix-only` to "
            f"populate `data/cache/india_vix.parquet`._"
        )

    # Two-column banner: state + percentile / positions / as-of.
    col_state, col_stats = st.columns([2, 3])

    with col_state:
        if state == "ON":
            st.success(
                f"### REGIME: **ON**\n\nVol regime is calm — full "
                f"position count permitted."
            )
        else:
            st.error(
                f"### REGIME: **OFF**\n\nVol regime hot (or "
                f"insufficient history) — new positions suppressed "
                f"by the gate."
            )

    with col_stats:
        c1, c2, c3 = st.columns(3)
        with c1:
            pct_label = "—" if pd.isna(pct) else f"{pct:.0f}th"
            st.metric("India VIX pctile", pct_label)
        with c2:
            # Skeleton: positions-today is a placeholder until the
            # selection pipeline ships (Phase 9.4.9).
            st.metric("positions today", f"— / {universe_n}")
        with c3:
            st.metric("as of", as_of.isoformat())


def _render_strategy_config() -> None:
    """Collapsible strategy config block — universe size, strategy,
    entry/exit offsets, sizing, regime gate toggle, IVP filter range,
    earnings filter toggle.

    Streamlit doesn't have a native collapsible panel; using
    ``st.expander`` which gives us the right affordance even if the
    visual differs from the mockup's custom panel.
    """
    with st.expander("**STRATEGY CONFIG**", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.session_state[_SS_UNIVERSE_N] = st.selectbox(
                "Positions / cycle",
                options=[3, 5, 8, 10, 15],
                index=[3, 5, 8, 10, 15].index(
                    int(st.session_state[_SS_UNIVERSE_N])
                ),
                help="Top-N after liquidity + IVP rank.",
            )
            st.session_state[_SS_STRATEGY] = st.selectbox(
                "Strategy",
                options=_STRATEGY_KEYS,
                format_func=lambda k: _STRATEGY_LABELS[k],
                index=_STRATEGY_KEYS.index(
                    st.session_state[_SS_STRATEGY]
                ),
                help="Leg structure.",
            )
            st.session_state[_SS_SIZING] = st.selectbox(
                "Sizing mode",
                options=_SIZING_KEYS,
                format_func=lambda k: _SIZING_LABELS[k],
                index=_SIZING_KEYS.index(
                    st.session_state[_SS_SIZING]
                ),
                help=(
                    "v1 ships equal_margin (memoir §7). "
                    "Vol-targeted deferred to Phase 10.2."
                ),
            )

        with c2:
            st.session_state[_SS_ENTRY_OFFSET] = st.slider(
                "Entry — trading days before expiry",
                min_value=1, max_value=45,
                value=int(st.session_state[_SS_ENTRY_OFFSET]),
                step=1, help="Memoir §5 default: 15.",
            )
            st.session_state[_SS_EXIT_OFFSET] = st.slider(
                "Exit — trading days before expiry",
                min_value=0, max_value=20,
                value=int(st.session_state[_SS_EXIT_OFFSET]),
                step=1, help="Memoir §5 default: 3.",
            )

        # Filter toggles + IVP band on their own row for visual
        # weight.
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.session_state[_SS_REGIME_GATE] = st.toggle(
                "Regime gate",
                value=bool(st.session_state[_SS_REGIME_GATE]),
                help=(
                    "Skip cycles when India VIX percentile > "
                    f"{_REGIME_THRESHOLD_PCT:.0f}th (memoir §3.1)."
                ),
            )
        with c2:
            st.session_state[_SS_EARNINGS_FILTER] = st.toggle(
                "Earnings filter",
                value=bool(st.session_state[_SS_EARNINGS_FILTER]),
                help=(
                    "Drop symbols with Financial Results event "
                    "in [entry, exit+1d] (memoir §17.5)."
                ),
            )
        with c3:
            ivp_band = st.session_state[_SS_IVP_BAND]
            if isinstance(ivp_band, list):
                ivp_band = tuple(ivp_band)
            new_band = st.slider(
                "IVP band",
                min_value=0, max_value=100,
                value=ivp_band, step=1,
                help=(
                    "Trades whose entry-day IVP falls in this "
                    "band are eligible (memoir §2.5)."
                ),
            )
            st.session_state[_SS_IVP_BAND] = new_band


def _portfolio_trades_view(df_filtered: pd.DataFrame) -> pd.DataFrame:
    """Slice the sidebar-filtered sweep frame to the Portfolio
    config's (strategy, entry_offset_td, exit_offset_td) tuple.

    v1 Portfolio backtest is single-(strategy, entry, exit) per
    memoir §5 — the strategy config picks ONE tuple, so this
    function reduces df_filtered to the matching rows.

    Returns:
        DataFrame of per-trade rows. May be empty if no rows
        match the config (e.g., sidebar excludes the chosen
        strategy, or the entry/exit slider lands on offsets the
        sweep doesn't have).
    """
    strategy = st.session_state[_SS_STRATEGY]
    entry_offset = int(st.session_state[_SS_ENTRY_OFFSET])
    exit_offset = int(st.session_state[_SS_EXIT_OFFSET])
    return df_filtered[
        (df_filtered["strategy"] == strategy)
        & (df_filtered["entry_offset_td"] == entry_offset)
        & (df_filtered["exit_offset_td"] == exit_offset)
    ]


def _regime_off_cycle_dates(
    cycle_dates: pd.DatetimeIndex,
    *,
    lookback_td: int = _REGIME_LOOKBACK_TD,
    threshold_pct: float = _REGIME_THRESHOLD_PCT,
) -> list[pd.Timestamp]:
    """For each cycle's expiry date, look up the regime state at
    expiry (per memoir §3 v1 — the gate fires at cycle entry, but
    for visualization we mark the cycle's expiry on the equity
    x-axis since that's the cycle's natural label).

    Returns the list of expiry timestamps where regime was OFF.
    Empty list on cold cache (graceful — no overlay rendered).
    """
    if cycle_dates.empty:
        return []
    try:
        # Load the VIX signal over the full window + 252-TD
        # backfill so each regime lookup is realized.
        backfill_days = int(lookback_td * 365 / 252) + 30
        from_date = cycle_dates.min().date() - timedelta(days=backfill_days)
        to_date = cycle_dates.max().date()
        signal = default_regime_signal(
            from_date, to_date, offline=True,
        )
    except Exception:
        return []
    off_cycles: list[pd.Timestamp] = []
    for ts in cycle_dates:
        try:
            state = regime_state(
                signal, ts.date(),
                threshold_pct=threshold_pct,
                lookback_td=lookback_td,
            )
        except Exception:
            continue
        if state == "OFF":
            off_cycles.append(ts)
    return off_cycles


# Worst-N cycle drilldown sizing — 10 by default per PLAN.md
# 9.4.5. Caller can override for narrower / wider views.
_DEFAULT_WORST_N_CYCLES = 10
# Attribution depth — top 3 symbols contributing to each cycle's
# loss surfaces enough context without overwhelming the table.
_ATTRIBUTION_TOP_K_SYMBOLS = 3

# Concentration + correlation visualization sizing.
_CONCENTRATION_TOP_K_SYMBOLS = 15
_CORRELATION_PLOT_HEIGHT_PX = 360


def _build_regime_signal_for_window(
    trades_df: pd.DataFrame,
) -> pd.Series:
    """Load the India VIX signal series covering the trades_df's
    entry_date window + 252-TD backfill cushion. Memoized via
    Streamlit cache so multi-section renders share the load.

    Returns an empty Series on cold cache / loader failure — the
    diagnostic function downstream handles empty signal cleanly.
    """
    if trades_df.empty:
        return pd.Series([], dtype="float64",
                          index=pd.DatetimeIndex([]))
    min_date = pd.to_datetime(trades_df["entry_date"]).min().date()
    max_date = pd.to_datetime(trades_df["entry_date"]).max().date()
    backfill_days = int(
        _REGIME_LOOKBACK_TD * 365 / 252,
    ) + 30
    from_date = min_date - timedelta(days=backfill_days)
    try:
        return default_regime_signal(
            from_date, max_date, offline=True,
        )
    except Exception:
        return pd.Series([], dtype="float64",
                          index=pd.DatetimeIndex([]))


def _build_ivp_per_symbol(
    trades_df: pd.DataFrame,
) -> dict[str, pd.Series]:
    """Per-symbol IVP series indexed by entry_date.

    For each unique (symbol, entry_date) pair in trades_df, calls
    ``analytics.ivp.compute_ivp`` to get the trailing-252-TD IVP
    rank. Symbols with no IVP cache (FileNotFoundError from
    load_iv_history) get an empty Series — the diagnostic
    function treats those trades as NaN-IVP and excludes them
    from the bucketing (counted in n_trades_dropped).

    The function is intentionally not @st.cache_data'd: the
    Streamlit cache rejects DataFrame keys, and the inner
    ``compute_ivp`` already memoizes the IV-history reads
    per-symbol via pandas' parquet loader.
    """
    out: dict[str, pd.Series] = {}
    if trades_df.empty:
        return out
    for sym, sub in trades_df.groupby("symbol"):
        dates = pd.to_datetime(sub["entry_date"]).drop_duplicates().sort_values()
        vals: list[float] = []
        for d in dates:
            try:
                v = compute_ivp(str(sym), d.date())
            except FileNotFoundError:
                v = float("nan")
            except Exception:
                v = float("nan")
            vals.append(v)
        out[str(sym)] = pd.Series(vals, index=dates)
    return out


def _render_regime_x_ivp_diagnostic(df_filtered: pd.DataFrame) -> None:
    """2-D diagnostic table (regime_state × IVP decile) per
    memoir §18.4 + §21.4 F19 + PLAN.md Phase 9.4.7.

    Composes:
      1. _portfolio_trades_view → per-trade slice for config.
      2. _build_regime_signal_for_window → India VIX signal.
      3. _build_ivp_per_symbol → {symbol: IVP series}.
      4. regime_x_ivp_breakdown → RegimeIvpBreakdown.

    Renders the breakdown's table + the caveat banner (quintile
    fallback / dropped trades count) so the operator sees the
    honest sample sizing.
    """
    sub = _portfolio_trades_view(df_filtered)
    if sub.empty:
        return

    st.markdown("##### Regime × IVP diagnostic")

    # Building these series is comparatively expensive (one
    # compute_ivp call per unique (symbol, entry_date) tuple).
    # Surface a spinner so the operator sees the wait.
    with st.spinner("Computing IVP at entry for each trade..."):
        regime_signal = _build_regime_signal_for_window(sub)
        ivp_per_sym = _build_ivp_per_symbol(sub)

    if regime_signal.empty:
        st.warning(
            "Regime signal unavailable — `data/cache/india_vix.parquet` "
            "missing or empty. Run `scripts/prefetch_universe.py --vix-only` "
            "to populate."
        )
        return
    if not ivp_per_sym:
        st.warning(
            "No per-symbol IVP cache found. Run the IV materializer "
            "(Phase 9.1) to populate `data/cache/iv/{SYMBOL}.parquet`."
        )
        return

    breakdown: RegimeIvpBreakdown = regime_x_ivp_breakdown(
        sub, regime_signal, ivp_per_sym,
    )

    if breakdown.table.empty:
        st.info(
            "Diagnostic table empty — no trades survived the regime + "
            "IVP lookup. "
            f"{breakdown.n_trades_dropped} of {breakdown.n_trades_total} "
            f"trades dropped."
        )
        return

    # Surface the caveat banner FIRST so the operator sees the
    # quintile-fallback + drop-count context before reading values.
    caveat = breakdown.caveat_text()
    if caveat:
        st.caption(f"_{caveat}._")

    # Format the table for display.
    disp = breakdown.table.copy()
    disp["count"] = disp["count"].astype(int)
    disp["mean"] = disp["mean"].map(_fmt_inr_compact)
    disp["median"] = disp["median"].map(_fmt_inr_compact)
    disp["cvar_5"] = disp["cvar_5"].map(_fmt_inr_compact)
    # Pretty column names.
    disp = disp.rename(columns={
        "count": "Count",
        "mean": "Mean",
        "median": "Median",
        "cvar_5": "CVaR-5%",
    })
    # Bring the multi-index out as columns so st.dataframe can
    # sort + filter cleanly.
    disp = disp.reset_index()
    disp = disp.rename(columns={
        "regime_state": "Regime",
        "ivp_bucket": "IVP bucket",
    })

    st.dataframe(disp, hide_index=True, width="stretch")
    st.caption(
        "Per-cell median (stable signal) AND CVaR-5% (worst-5% "
        "tail) — judge each (regime × IVP) cell on both. "
        "Memoir §18.4 + §F19. Bucket boundaries are FULL-SAMPLE "
        "qcut (retrospective only — NOT used for live filter)."
    )


def _per_symbol_margin_share(sub: pd.DataFrame) -> pd.DataFrame:
    """Per-symbol share of total margin deployed across all
    trades. Memoir §4 + mockup §D: surfaces which names dominate
    capital allocation under the equal-margin convention.

    Returns:
        DataFrame with columns:
          symbol, margin_total, share_pct.
        Sorted descending by margin_total. Empty if no margin
        column in input (defensive — older sweep parquets may
        lack it).
    """
    if sub.empty or "margin_at_entry" not in sub.columns:
        return pd.DataFrame(
            columns=["symbol", "margin_total", "share_pct"],
        )
    by_sym = (
        sub.groupby("symbol")["margin_at_entry"]
           .sum().sort_values(ascending=False)
    )
    total = float(by_sym.sum())
    if total <= 0:
        return pd.DataFrame(
            columns=["symbol", "margin_total", "share_pct"],
        )
    out = pd.DataFrame({
        "symbol": by_sym.index.astype(str),
        "margin_total": by_sym.values,
        "share_pct": by_sym.values / total * 100.0,
    })
    return out.reset_index(drop=True)


def _pairwise_correlation_matrix(sub: pd.DataFrame) -> pd.DataFrame:
    """Pairwise Pearson correlation of per-cycle P&L across
    symbols. Memoir §4 + mockup §D: the diversification signal
    operators care about — high pairwise correlation means the
    portfolio is structurally exposed to common factors and
    the apparent diversification is illusory.

    Pivots ``sub`` to (expiry × symbol) → net_pnl matrix and
    runs ``.corr()`` on the column-wise series. Empty input or
    a single-symbol universe → empty frame.

    Returns:
        Square DataFrame indexed by symbol, columns by symbol.
        Values in [-1, 1]. NaN where a symbol has < 2 non-NaN
        rows (pandas .corr default).
    """
    if sub.empty:
        return pd.DataFrame()
    wide = sub.pivot_table(
        index="expiry", columns="symbol", values="net_pnl",
        aggfunc="sum",
    )
    if wide.shape[1] < 2:
        # Need at least 2 symbols for a meaningful correlation.
        return pd.DataFrame()
    return wide.corr()


def _render_concentration_correlation(df_filtered: pd.DataFrame) -> None:
    """Two-panel concentration + correlation diagnostic per
    PLAN.md Phase 9.4.6 + memoir §4 + mockup §D.

    Left: per-symbol margin share bar chart (top-15 symbols by
          total margin deployed; everything else folded into
          "others" if more than 15 symbols).
    Right: pairwise correlation heatmap of per-cycle P&L across
           symbols (top-15 by margin for visual clarity).

    Silent on empty filter.
    """
    sub = _portfolio_trades_view(df_filtered)
    if sub.empty:
        return

    concentration = _per_symbol_margin_share(sub)
    corr = _pairwise_correlation_matrix(sub)
    if concentration.empty and corr.empty:
        return

    st.markdown("##### Concentration & correlation")
    col_left, col_right = st.columns(2)

    with col_left:
        if concentration.empty:
            st.caption("_No margin column in this sweep parquet._")
        else:
            top = concentration.head(_CONCENTRATION_TOP_K_SYMBOLS)
            # Horizontal bar; ascending order so the highest-
            # concentration symbol renders at top.
            fig = go.Figure(go.Bar(
                x=top["share_pct"][::-1],
                y=top["symbol"][::-1],
                orientation="h",
                marker_color="rgba(80, 140, 220, 0.8)",
                hovertemplate=(
                    "%{y}<br>margin share: %{x:.1f}%<extra></extra>"
                ),
            ))
            fig.update_layout(
                height=_CORRELATION_PLOT_HEIGHT_PX,
                margin=dict(l=10, r=10, t=30, b=10),
                title="Margin share by symbol (top 15)",
                xaxis_title="share of total margin (%)",
                yaxis_title=None,
            )
            st.plotly_chart(fig, width="stretch")

    with col_right:
        if corr.empty:
            st.caption(
                "_Correlation requires ≥ 2 symbols in the "
                "filtered view._"
            )
        else:
            # Limit to top-15 by margin for visual readability.
            if not concentration.empty:
                top_syms = concentration.head(
                    _CONCENTRATION_TOP_K_SYMBOLS
                )["symbol"].tolist()
                shown_corr = corr.loc[
                    corr.index.isin(top_syms),
                    corr.columns.isin(top_syms),
                ]
            else:
                shown_corr = corr.iloc[
                    :_CONCENTRATION_TOP_K_SYMBOLS,
                    :_CONCENTRATION_TOP_K_SYMBOLS,
                ]
            fig = go.Figure(go.Heatmap(
                z=shown_corr.values,
                x=shown_corr.columns,
                y=shown_corr.index,
                colorscale="RdBu",
                zmin=-1, zmax=1,
                hovertemplate=(
                    "%{y} vs %{x}<br>ρ = %{z:.2f}<extra></extra>"
                ),
            ))
            fig.update_layout(
                height=_CORRELATION_PLOT_HEIGHT_PX,
                margin=dict(l=10, r=10, t=30, b=10),
                title="Pairwise cycle-P&L correlation",
            )
            st.plotly_chart(fig, width="stretch")

    st.caption(
        "Concentration: where margin is deployed. Correlation: "
        "structural exposure to common factors — high pairwise "
        "correlation means the portfolio's apparent diversification "
        "is illusory."
    )


def _worst_cycles_with_attribution(
    sub: pd.DataFrame, *, n: int = _DEFAULT_WORST_N_CYCLES,
    top_k: int = _ATTRIBUTION_TOP_K_SYMBOLS,
) -> pd.DataFrame:
    """Top-N worst cycles by total cycle P&L with per-symbol
    "what blew up" attribution.

    For each of the n worst cycles, identifies the top_k symbols
    with the largest negative net_pnl contributions and surfaces
    them in a compact 'SYM (-₹X) · SYM (-₹X) · …' string. Memoir
    §4 + PLAN.md 9.4.5: the operator-facing tail-event view.

    Args:
        sub: per-trade frame already filtered to the Portfolio
            config tuple (strategy, entry, exit).
        n: how many worst cycles to surface. Default 10.
        top_k: how many symbol contributors per cycle.

    Returns:
        DataFrame with columns:
          expiry, cycle_pnl, attribution.
        Sorted ascending by cycle_pnl (worst first). May have
        fewer than n rows if fewer cycles exist.
    """
    if sub.empty:
        return pd.DataFrame(
            columns=["expiry", "cycle_pnl", "attribution"],
        )
    cycle_totals = (
        sub.groupby("expiry", sort=False)["net_pnl"].sum()
           .sort_values(ascending=True)
           .head(n)
    )
    rows: list[dict] = []
    for expiry, total in cycle_totals.items():
        cycle_trades = sub[sub["expiry"] == expiry]
        # Aggregate per-symbol P&L within this cycle, sort
        # ascending so the largest losses come first.
        per_sym = (
            cycle_trades.groupby("symbol")["net_pnl"]
                        .sum().sort_values(ascending=True).head(top_k)
        )
        chunks = [
            f"{sym} ({_fmt_inr_compact(val)})"
            for sym, val in per_sym.items()
        ]
        rows.append({
            "expiry": pd.Timestamp(expiry),
            "cycle_pnl": float(total),
            "attribution": " · ".join(chunks) if chunks else "—",
        })
    return pd.DataFrame(rows)


def _render_worst_10_cycles(df_filtered: pd.DataFrame) -> None:
    """Worst-10 cycles + per-symbol attribution panel per
    PLAN.md Phase 9.4.5.

    Renders silently on empty filter — equity-curve renderer
    already surfaced the explanation banner.
    """
    sub = _portfolio_trades_view(df_filtered)
    if sub.empty:
        return
    table = _worst_cycles_with_attribution(sub)
    if table.empty:
        return

    st.markdown("##### Worst 10 cycles")
    disp = pd.DataFrame({
        "Expiry": table["expiry"].dt.strftime("%Y-%m-%d"),
        "Cycle P&L": table["cycle_pnl"].map(_fmt_inr_compact),
        "What blew up": table["attribution"],
    })
    st.dataframe(disp, hide_index=True, width="stretch")
    st.caption(
        "Cycle expiry · total P&L across symbols traded in that "
        "cycle · top-3 per-symbol loss contributors. The tail-"
        "risk surface beyond the smoothed Calmar / Ulcer ratios."
    )


def _per_year_stats(
    pnl_series: pd.Series, starting_capital: float,
) -> pd.DataFrame:
    """Build the year-by-year stability table per memoir §4 +
    mockup §C.

    Each year is treated as a STANDALONE book starting at the
    prior year's ending equity (or ``starting_capital`` for the
    first year). This gives honest per-year Calmar / Ulcer that
    reflect what would have happened if you started the year at
    that balance — sidesteps the multi-year compounding question.

    Calmar per year is reported only when the year has ≥ 6
    cycles (half a year of monthly data); thinner samples surface
    as NaN to avoid optical noise.

    Returns:
        DataFrame with one row per year, columns:
          year, cycles, return_inr, return_pct,
          max_dd_inr, calmar, ulcer.
    """
    if pnl_series.empty:
        return pd.DataFrame(
            columns=[
                "year", "cycles", "return_inr", "return_pct",
                "max_dd_inr", "calmar", "ulcer",
            ],
        )
    rows: list[dict] = []
    cumulative = float(starting_capital)
    for year, year_pnl in pnl_series.groupby(pnl_series.index.year):
        year_start = cumulative
        eq = equity_curve(year_pnl, starting_capital=year_start)
        dd = drawdown_series(eq)
        year_total = float(year_pnl.sum())
        rows.append({
            "year": int(year),
            "cycles": int(len(year_pnl)),
            "return_inr": year_total,
            "return_pct": (year_total / year_start * 100.0) if year_start else float("nan"),
            "max_dd_inr": float(abs(dd.min())),
            "calmar": calmar(eq) if len(year_pnl) >= 6 else float("nan"),
            "ulcer": ulcer_index(eq),
        })
        cumulative += year_total
    return pd.DataFrame(rows)


def _render_yoy_stability(df_filtered: pd.DataFrame) -> None:
    """Year-by-year stability table per memoir §4 + mockup §C.

    Columns: Year / Cycles / Return ₹ / Return % / Max DD ₹ /
    Calmar / Ulcer. Surfaces "is this strategy STABLE across
    years, or does the headline Calmar come from one good year?"

    Empty-state: skip silently. The equity-curve renderer above
    already surfaced the explanation banner.
    """
    sub = _portfolio_trades_view(df_filtered)
    if sub.empty:
        return
    pnl = cycle_pnl_series(sub)
    if pnl.empty:
        return

    table = _per_year_stats(pnl, _DEFAULT_STARTING_CAPITAL)
    if table.empty:
        return

    st.markdown("##### Year-by-year stability")
    # Build a display frame with formatted strings so st.dataframe
    # renders aligned + parses sort cleanly.
    disp = pd.DataFrame({
        "Year": table["year"],
        "Cycles": table["cycles"],
        "Return": table["return_inr"].map(_fmt_inr_compact),
        "Return %": table["return_pct"].map(
            lambda v: "—" if pd.isna(v) else f"{v:+.2f}%"
        ),
        "Max DD ₹": table["max_dd_inr"].map(
            lambda v: _fmt_inr_compact(-v) if v > 0 else "₹0"
        ),
        "Calmar": table["calmar"].map(_fmt_ratio),
        "Ulcer": table["ulcer"].map(_fmt_ratio),
    })
    st.dataframe(disp, hide_index=True, width="stretch")
    st.caption(
        "Each year is treated as a standalone book starting at "
        "the prior year's ending equity. Calmar surfaces only "
        "when ≥ 6 cycles in the year (half a year of monthly data)."
    )


def _fmt_inr_compact(value: float) -> str:
    """Indian rupee compact formatter — ₹1L for lakh, ₹1Cr for crore.
    Per the mockup convention so the headline strip's cards fit in
    one line on a typical-width screen."""
    if pd.isna(value):
        return "—"
    sign = "-" if value < 0 else ""
    a = abs(value)
    if a >= 1e7:
        return f"{sign}₹{a / 1e7:.2f}Cr"
    if a >= 1e5:
        return f"{sign}₹{a / 1e5:.2f}L"
    if a >= 1e3:
        return f"{sign}₹{a / 1e3:.1f}k"
    return f"{sign}₹{a:.0f}"


def _fmt_ratio(value: float, *, decimals: int = 2) -> str:
    """Calmar / Sortino / Ulcer formatter. Renders inf cleanly."""
    if pd.isna(value):
        return "—"
    if value == float("inf"):
        return "∞"
    if value == float("-inf"):
        return "-∞"
    return f"{value:.{decimals}f}"


def _render_headline_strip(df_filtered: pd.DataFrame) -> None:
    """6-card headline metrics strip per memoir §4 + mockup §A.

    Cards: Total return / Calmar / Ulcer / Sortino / Max DD ₹ /
    Worst cycle. Win-rate + avg-positions land in Phase 9.4.9
    cycle drilldown (which has the candidate-selection pipeline
    needed for per-cycle position counts).

    Renders an empty-state info banner when the strategy config
    matches no cycles — mirrors _render_equity_curve's degrade-
    gracefully contract.
    """
    sub = _portfolio_trades_view(df_filtered)
    if sub.empty:
        # Equity curve already rendered the explanatory banner;
        # don't double-render here. Just skip silently.
        return

    pnl = cycle_pnl_series(sub)
    if pnl.empty:
        return

    eq = equity_curve(pnl, starting_capital=_DEFAULT_STARTING_CAPITAL)
    rets = cycle_returns(pnl, _DEFAULT_STARTING_CAPITAL)

    # Metrics. Each metric handles its own empty-input → NaN /
    # 0.0 fallback per the analytics layer's contract.
    total_return_inr = float(eq.iloc[-1]) - _DEFAULT_STARTING_CAPITAL
    ann_return = simple_annualized_return(eq)
    calmar_val = calmar(eq)
    ulcer_val = ulcer_index(eq)
    sortino_val = sortino(rets)
    max_dd_val = max_drawdown_inr(eq)
    worst_cycle = float(pnl.min())

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1:
        st.metric(
            "Total return",
            _fmt_inr_compact(total_return_inr),
            delta=(
                f"{ann_return * 100:+.2f}%/yr (simple)"
                if not pd.isna(ann_return) else None
            ),
            help=(
                "Total absolute ₹ return + simple annualized "
                "rate. Memoir §21.4 F15 REVISED — additive sizing "
                "implies simple, NOT geometric CAGR."
            ),
        )
    with c2:
        st.metric(
            "Calmar",
            _fmt_ratio(calmar_val),
            help=(
                "Simple annualized return / max DD %. Higher = "
                "better return per unit of pain. Memoir §21.4 F15."
            ),
        )
    with c3:
        st.metric(
            "Ulcer",
            _fmt_ratio(ulcer_val),
            help=(
                "RMS of underwater drawdown %. Lower = better. "
                "Penalizes BOTH depth and duration. Memoir §21.4 F16."
            ),
        )
    with c4:
        st.metric(
            "Sortino",
            _fmt_ratio(sortino_val),
            help=(
                "Annualized excess return / target-downside-"
                "deviation. Higher = better. Memoir §21.4 F17 "
                "REVISED — N_total denominator, (r−target)² "
                "squared term."
            ),
        )
    with c5:
        st.metric(
            "Max DD ₹",
            _fmt_inr_compact(-max_dd_val) if max_dd_val > 0 else "₹0",
            help=(
                "Peak-to-trough rupee loss. Memoir §21.4 F18. "
                "Positive ₹ amount shown with leading minus."
            ),
        )
    with c6:
        st.metric(
            "Worst cycle",
            _fmt_inr_compact(worst_cycle),
            help=(
                "Single worst cycle's P&L. Operator-facing tail "
                "signal beyond the smoothed Calmar / Ulcer / "
                "Sortino numbers."
            ),
        )


def _render_equity_curve(df_filtered: pd.DataFrame) -> None:
    """Equity curve + underwater drawdown subplot per memoir
    §4 + §21.4 F13 + F14. Regime-OFF cycles rendered as gray
    vertical bands per Phase 9.4.2 spec (PLAN.md line 343).

    Composition:
      1. Slice df_filtered to the (strategy, entry, exit) tuple
         from the strategy config.
      2. Build cycle_pnl_series (F12) → equity_curve (F13) →
         drawdown_series (F14) from analytics.portfolio.
      3. Plot equity on the top subplot, underwater DD on the
         bottom subplot (shared x-axis).
      4. Overlay gray vertical bands for OFF cycles.
    """
    sub = _portfolio_trades_view(df_filtered)
    if sub.empty:
        st.info(
            "No trades match the current strategy + entry/exit "
            "configuration. Adjust the strategy or offsets in the "
            "config block above, or widen the sidebar filters."
        )
        return

    pnl = cycle_pnl_series(sub)
    if pnl.empty:
        st.info(
            "Cycle P&L series is empty — no priced expiries in "
            "the filtered view. This usually means the strategy "
            "config's offsets don't match any rows in the sweep."
        )
        return

    eq = equity_curve(pnl, starting_capital=_DEFAULT_STARTING_CAPITAL)
    dd = drawdown_series(eq)

    # Regime-OFF cycles for the overlay.
    if st.session_state[_SS_REGIME_GATE]:
        off_dates = _regime_off_cycle_dates(pnl.index)
    else:
        off_dates = []

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=list(_EQUITY_SUBPLOT_ROW_HEIGHTS),
        subplot_titles=(
            "Equity (₹, additive)",
            "Underwater drawdown (₹)",
        ),
    )

    # Equity line.
    fig.add_trace(
        go.Scatter(
            x=eq.index, y=eq.values,
            mode="lines",
            name="Equity",
            line=dict(width=2),
            hovertemplate="%{x|%Y-%m-%d}<br>Equity: ₹%{y:,.0f}<extra></extra>",
        ),
        row=1, col=1,
    )
    # Starting capital reference.
    fig.add_hline(
        y=_DEFAULT_STARTING_CAPITAL,
        line=dict(color="gray", dash="dot", width=1),
        row=1, col=1,
    )

    # Drawdown area (filled negative).
    fig.add_trace(
        go.Scatter(
            x=dd.index, y=dd.values,
            mode="lines",
            name="Drawdown",
            line=dict(width=1, color="rgba(220, 60, 60, 0.9)"),
            fill="tozeroy",
            fillcolor="rgba(220, 60, 60, 0.25)",
            hovertemplate="%{x|%Y-%m-%d}<br>DD: ₹%{y:,.0f}<extra></extra>",
        ),
        row=2, col=1,
    )

    # Regime-OFF overlay — gray vertical bands. One band per OFF
    # cycle centered on its expiry.
    # Plotly's vrect needs an x0/x1 pair; use ±15 days as a visual
    # span representing the cycle.
    band_half_width = pd.Timedelta(days=15)
    for ts in off_dates:
        fig.add_vrect(
            x0=ts - band_half_width, x1=ts + band_half_width,
            fillcolor="rgba(140, 140, 140, 0.18)",
            line_width=0,
            row="all", col=1,
        )

    fig.update_layout(
        height=_EQUITY_PLOT_HEIGHT_PX,
        margin=dict(l=10, r=10, t=30, b=10),
        showlegend=False,
        hovermode="x unified",
    )
    fig.update_yaxes(tickformat=",.0f", row=1, col=1)
    fig.update_yaxes(tickformat=",.0f", row=2, col=1)

    st.plotly_chart(fig, width="stretch")

    # Footer caption with the diagnostic counts so the operator
    # can see how the chart maps to the data.
    cycles_n = len(pnl)
    off_n = len(off_dates)
    final_equity = float(eq.iloc[-1])
    delta_pct = (
        (final_equity - _DEFAULT_STARTING_CAPITAL)
        / _DEFAULT_STARTING_CAPITAL * 100.0
    )
    delta_sign = "+" if delta_pct >= 0 else ""
    st.caption(
        f"**{cycles_n}** cycles · **{off_n}** regime-OFF · "
        f"start ₹{_DEFAULT_STARTING_CAPITAL:,.0f} → "
        f"end ₹{final_equity:,.0f} ({delta_sign}{delta_pct:.2f}%) · "
        f"max DD ₹{abs(dd.min()):,.0f}. "
        f"Headline metrics (Calmar / Ulcer / Sortino / Max DD) "
        f"land in Phase 9.4.3."
    )


def render_portfolio_tab(df_filtered: pd.DataFrame) -> None:
    """Public entry point — called by ``app.py``'s tab router.

    Args:
        df_filtered: the sidebar-filtered sweep DataFrame (the
            same shape ``_render_leaderboard_tab`` etc. receive).
            For the skeleton we accept it for forward compatibility
            but don't yet aggregate from it (that's 9.4.2's job).
    """
    _seed_session_state()
    _render_header()
    _render_banners()
    st.markdown("---")
    _render_regime_banner()
    st.markdown("---")
    _render_strategy_config()
    st.markdown("---")
    _render_headline_strip(df_filtered)
    _render_equity_curve(df_filtered)
    _render_yoy_stability(df_filtered)
    _render_worst_10_cycles(df_filtered)
    _render_concentration_correlation(df_filtered)
    _render_regime_x_ivp_diagnostic(df_filtered)
