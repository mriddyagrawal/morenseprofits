"""Canonical caveats for the Phase-6 UI.

SPECS §11.3 + DESIGN_SPEC §1.4 contract:

  Three caveat constants — one per honest-disclosure concern. The
  verbatim text lives here; UI tabs render via the strip / collapsed
  helpers, never inline-substitute.

  ``render_caveats_strip()`` paints three side-by-side cards at the
  top of every tab on first render. Operator clicks "Read once,
  then dismiss" → state flag flips → subsequent tabs (in the same
  session) render ``render_caveats_collapsed()`` (a slim single-line
  banner). A browser refresh re-expands (session-scoped only; never
  written to disk per DESIGN_SPEC §1.4).

  Three always-visible cards beat the "expander, collapsed by
  default" alternative because expanders train operators to skip
  past the label-line. Cards force the first read; the slim banner
  keeps re-callability without dominating real estate.

This module DOES import streamlit (it's the renderer; that's its job).
Per SPECS §11.1 it's the only one in `src/web/` that imports streamlit
at module-import time — all others (e.g. `discover`) stay streamlit-
free for unit-testability.
"""
from __future__ import annotations

import streamlit as st

from src.analytics.rank import MULTIPLE_COMPARISONS_CAVEAT


# Re-export so consumers import one place for all three.
__all__ = [
    "MULTIPLE_COMPARISONS_CAVEAT",
    "SURVIVORSHIP_CAVEAT",
    "MARGIN_TIER_B_CAVEAT",
    "render_caveats",            # top-level dispatcher — strip vs collapsed
    "render_caveats_strip",
    "render_caveats_collapsed",
    "DISMISS_KEY",
]


# Session-state key holding the dismissed-vs-expanded flag.
# Prefix `mp_` per SPECS §11.4 namespace convention.
DISMISS_KEY: str = "mp_caveats_dismissed"


# v1 paraphrase of SPECS §6b.3. Phase 6 surfaces this verbatim
# alongside any leaderboard derived from the blue-chip universe.
SURVIVORSHIP_CAVEAT = (
    "The blue-chip universe is a 2024-07-01 snapshot. Stocks that "
    "DELISTED before the snapshot — including bankruptcies, mergers, "
    "and de-listings for non-compliance — are absent by construction. "
    "Backtests on this universe systematically OVERSTATE the realized "
    "edge of any strategy because the losers have already been "
    "filtered out. Treat headline ROIs as upper bounds for what the "
    "same strategy would have produced on the contemporaneous "
    "universe. Phase-7 BLUE_CHIP_BY_QUARTER membership lands the "
    "structural fix; v1 ships the snapshot."
)


# Summarizes SPECS §4a caveats 1, 3, 4 — the Tier-B margin model's
# known biases relative to real-broker SPAN.
MARGIN_TIER_B_CAVEAT = (
    "Margin is Tier-B SPAN approximation (volatility-derived per-symbol "
    "rate × strategy-offset multiplier × shares × spot-based notional). "
    "Real NSE SPAN uses daily-published risk arrays not archived "
    "historically; ours is the realistic ceiling for backtest accuracy. "
    "Bias direction: HIGH-VOL symbols and LOW-OFFSET strategies (short "
    "straddle 0.60, iron condor 0.35) look BETTER here than on production "
    "margin, because real SPAN computes a tighter portfolio offset for "
    "well-correlated multi-leg structures. Cross-strategy ranking remains "
    "directionally sound (caveat caught at ~10-15% bias post Tier-B); "
    "absolute ROI numbers should be discounted by ~10% before treating "
    "any pair as 'production-ready'."
)


def _maybe_init_state() -> None:
    """Initialise the dismiss flag once per session if missing."""
    if DISMISS_KEY not in st.session_state:
        st.session_state[DISMISS_KEY] = False


def render_caveats_strip() -> None:
    """Render three side-by-side caveat cards at the top of a tab.

    Per DESIGN_SPEC §1.4: ALWAYS-visible mode. Three columns, one
    caveat each, plus a single dismiss button that flips
    ``st.session_state[DISMISS_KEY] = True`` for the rest of the
    session (subsequent tabs render the collapsed banner instead).

    Returns ``None`` — Streamlit side-effect."""
    _maybe_init_state()
    # Three caveats × three columns. Reading order: multiple-comparisons
    # first (most relevant to the leaderboard the operator's looking at),
    # survivorship middle, margin last.
    cols = st.columns(3)
    with cols[0]:
        st.markdown("#### ⚠ Multiple comparisons")
        st.caption(MULTIPLE_COMPARISONS_CAVEAT)
    with cols[1]:
        st.markdown("#### ⚠ Survivorship risk")
        st.caption(SURVIVORSHIP_CAVEAT)
    with cols[2]:
        st.markdown("#### ⚠ Margin Tier-B asymmetry")
        st.caption(MARGIN_TIER_B_CAVEAT)
    # Dismiss row — small, right-aligned via empty padding columns.
    pad, dismiss = st.columns([5, 1])
    with dismiss:
        if st.button("Read once, then dismiss",
                     key="mp_caveats_dismiss_btn",
                     help="Collapses the row to a slim banner for the "
                          "rest of this session. Browser refresh re-expands."):
            st.session_state[DISMISS_KEY] = True
            st.rerun()


def render_caveats_collapsed() -> None:
    """Render the slim single-line "⚠ 3 active caveats — click to
    expand" banner used after dismiss. Clicking re-expands the strip
    for the rest of the session.

    Returns ``None`` — Streamlit side-effect."""
    _maybe_init_state()
    cols = st.columns([6, 1])
    with cols[0]:
        st.warning(
            "⚠ 3 active caveats — multiple-comparisons selection bias, "
            "blue-chip survivorship, margin Tier-B asymmetry. Click "
            "→ to re-expand."
        )
    with cols[1]:
        if st.button("Expand",
                     key="mp_caveats_expand_btn",
                     help="Re-show the three caveat cards above."):
            st.session_state[DISMISS_KEY] = False
            st.rerun()


def render_caveats() -> None:
    """Top-level helper called by every tab. Renders the strip OR the
    collapsed banner depending on session-state. Always renders one or
    the other — satisfies PLAN §3 Phase-6.5 exit criterion ('caveats
    banner always visible')."""
    _maybe_init_state()
    if st.session_state[DISMISS_KEY]:
        render_caveats_collapsed()
    else:
        render_caveats_strip()
