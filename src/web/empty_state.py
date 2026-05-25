"""Empty-state / thin-data UX renderers.

DESIGN_SPEC §2.6 contract — every tab states one rule for "not enough
data to show this visual" and renders an ``st.info`` box with the rule
plus an operator action, NEVER an empty chart with axes ("never render
a nan axis or a one-bar bar chart and call it a trend").

Seven pre-written reasons, one per row of the §2.6 table. The mockup-
driven Q1-2024 verify set hits at least three of these on first render
(every cell masked, no YoY history, MoY almost-degenerate), so the
empty-state paths are exercised constantly during dev — not just
edge-case code.

This module imports streamlit (it IS a renderer); per SPECS §11.1 it
joins ``caveats.py`` as the second streamlit-importing module in
``src/web/``. The reason-key constants are pure strings and remain
importable without a Streamlit context (handy for unit tests).
"""
from __future__ import annotations

from typing import Literal

import streamlit as st


# ============================================================
# Reason keys — stable identifiers for the 7 pre-written messages
# ============================================================
Reason = Literal[
    "leaderboard_no_rows_after_filters",
    "leaderboard_all_below_min_n",
    "per_stock_no_trades",
    "heatmap_all_masked",
    "heatmap_single_axis",
    "trends_yoy_single_year",
    "trends_moy_single_month",
]


def _format_message(reason: Reason, **ctx) -> str:
    """Look up the canonical message for a reason key + format context.

    Context vars expected per reason:
      leaderboard_no_rows_after_filters → (none)
      leaderboard_all_below_min_n       → n_pairs (int), min_n (int)
      per_stock_no_trades               → symbol (str)
      heatmap_all_masked                → min_n (int)
      heatmap_single_axis               → n_entry (int), n_exit (int)
      trends_yoy_single_year            → n_years (int)
      trends_moy_single_month           → n_months (int)
    """
    if reason == "leaderboard_no_rows_after_filters":
        return (
            "No (strategy, symbol) pairs match the current filters. "
            "Widen the sidebar selection or pick a different sweep."
        )
    if reason == "leaderboard_all_below_min_n":
        n = ctx.get("n_pairs", "?")
        k = ctx.get("min_n", "?")
        return (
            f"All {n} pair(s) have fewer than min_n={k} trades. "
            f"Lower the threshold (sidebar slider) to inspect anyway, "
            f"or run a larger sweep."
        )
    if reason == "per_stock_no_trades":
        sym = ctx.get("symbol", "?")
        return (
            f"No trades for `{sym}` in this sweep. Pick another symbol."
        )
    if reason == "heatmap_all_masked":
        k = ctx.get("min_n", "?")
        return (
            f"Heatmap is empty: every (entry, exit) cell has fewer "
            f"than min_n={k} trades. Lower the threshold (sidebar) or "
            f"run a larger sweep."
        )
    if reason == "heatmap_single_axis":
        e = ctx.get("n_entry", "?")
        x = ctx.get("n_exit", "?")
        return (
            f"A heatmap needs ≥2 offsets on each axis. This sweep has "
            f"{e} entry offset(s) × {x} exit offset(s) — inspect the "
            f"leaderboard cells instead."
        )
    if reason == "trends_yoy_single_year":
        y = ctx.get("n_years", "?")
        return (
            f"YoY decay needs ≥2 years of trade data. This sweep "
            f"covers {y} year(s)."
        )
    if reason == "trends_moy_single_month":
        m = ctx.get("n_months", "?")
        return (
            f"Monthly seasonality needs ≥2 calendar months. This "
            f"sweep covers {m} month(s)."
        )
    # Unknown key — loud failure beats silent blank
    raise ValueError(f"unknown empty-state reason: {reason!r}")


def render_empty(reason: Reason, **ctx) -> None:
    """Render the canonical empty-state ``st.info`` box for the given
    reason + context.

    The message naming the operator action is the load-bearing part —
    a generic 'no data' box leaves the operator stuck; a specific
    'lower the min_n slider or run a larger sweep' tells them exactly
    what to do next.

    Returns ``None`` — Streamlit side-effect.
    """
    st.info(_format_message(reason, **ctx))


def get_message(reason: Reason, **ctx) -> str:
    """Return the canonical message string for a reason key without
    touching Streamlit (no st.info call). The FUNCTION itself doesn't
    invoke Streamlit, but importing this module DOES — ``import
    streamlit as st`` runs at module-import time because
    ``render_empty`` needs it. So a true "streamlit-free" import path
    isn't available here; consumers running in a non-Streamlit
    context (e.g., a CSV export header) still need streamlit installed.
    Phase-7 hardening can move the message templates to a sibling
    streamlit-free module if that constraint matters operationally."""
    return _format_message(reason, **ctx)
