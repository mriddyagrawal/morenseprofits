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

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st

from src.analytics.regime import (
    current_regime_state,
    default_regime_signal,
    regime_percentile,
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


def _render_skeleton_footer(df_filtered: pd.DataFrame) -> None:
    """Placeholder footer pointing at the work still to ship.
    Replaced by the equity curve + headline strip in 9.4.2 / 9.4.3."""
    st.markdown("---")
    st.caption(
        f"Skeleton commit (Phase 9.4.1). "
        f"Filtered sweep frame available: **{len(df_filtered):,} rows**. "
        f"Equity curve + headline metrics + 2-D diagnostic land in "
        f"Phase 9.4.2 - 9.4.7."
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
    _render_skeleton_footer(df_filtered)
