"""Leaderboard tab — Phase 6.2 implementation.

DESIGN_SPEC §2.5 (headline strip) + §4 (commits 11-14: headline,
table, thin-samples sidecar, within/across toggle).

This commit (p6.2.headline): the 4-card strip across the top.
Subsequent commits add the rank table, thin-samples sidecar, and
the within/across toggle below it.

Naming rule pinned in §2.5: if a card's value is RUPEES, the label
contains "P&L" or "₹" — never "ROI". If a card's value is a
PERCENTAGE, the label ends in "%" — never a bare number. (Per-trade
ROI throughout, no annualization per p7.expiry_roi.)
This is the contract that prevents the mockup's "AVG ROI ₹25.76 L"
bug (rupees mislabeled as percentage).
"""
from __future__ import annotations

import warnings

import pandas as pd
import streamlit as st

from src.analytics.aggregate import summarize_by_stock_strategy
from src.analytics.rank import rank_strategies
from src.web._format import format_inr, format_pct
from src.web.empty_state import render_empty


def _rank_quiet(summary_df: pd.DataFrame, *, min_n: int) -> pd.DataFrame:
    """Wrapper around rank_strategies that suppresses the analytics-
    layer "all rows suppressed" UserWarning when the UI tier is
    about to render render_empty for the same condition. The warning
    is correct behavior for direct callers / CLI consumers; in the
    Streamlit UI the operator already sees the explicit empty-state
    message, and the warning would just pollute server logs.

    Only the suppression-specific warning is silenced; other warnings
    bubble normally.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"rank_strategies: all .* input rows suppressed",
            category=UserWarning,
        )
        return rank_strategies(summary_df, min_n=min_n)


def render_headline(df: pd.DataFrame, *, min_n: int) -> None:
    """Render the 4-card headline strip per DESIGN_SPEC §2.5.

    Cards (left → right):
      TOP PAIR          rank=1's strategy × symbol, subtitle =
                        +X.X% median ROI
      OVERALL WIN RATE  (net_pnl > 0).sum() / n_trades × 100
      TOTAL NET P&L     sum(net_pnl) formatted as ₹X.XX L or Cr
      RANKED PAIRS      n_above_min_n / n_pairs_total

    Empty-frame fallback per §2.5: zero rows → every card renders
    `—` with subtitle "no data after filters". No `nan%` ever shown.
    """
    cols = st.columns(4)

    # === Empty-frame branch ==================================
    if len(df) == 0:
        labels = ["Top pair", "Overall win rate", "Total net P&L", "Ranked pairs"]
        for col, label in zip(cols, labels):
            with col:
                st.metric(label, "—", "no data after filters",
                          delta_color="off")
        return

    # === Common computations =================================
    summary = summarize_by_stock_strategy(df)
    # min_n=0 because the headline summary should reflect ALL pairs,
    # not just rank-eligible ones — the RANKED PAIRS card surfaces
    # the suppression count separately.
    ranked_all = rank_strategies(summary, min_n=0)
    ranked_eligible = ranked_all[ranked_all["n_trades"] >= min_n]
    n_pairs_total = int(len(summary))
    n_pairs_eligible = int(len(ranked_eligible))

    # === Card 1 — TOP PAIR ===================================
    with cols[0]:
        if n_pairs_eligible > 0:
            top = ranked_eligible.iloc[0]
            st.metric(
                "Top pair",
                f"{top['strategy']} × {top['symbol']}",
                f"{format_pct(top['median_roi_pct'], signed=True)} median ROI",
                delta_color="off",
            )
        else:
            st.metric(
                "Top pair", "—",
                f"no pairs pass min_n={min_n}",
                delta_color="off",
            )

    # === Card 2 — OVERALL WIN RATE ===========================
    n_trades_total = int(len(df))
    n_winning = int((df["net_pnl"] > 0).sum())
    with cols[1]:
        st.metric(
            "Overall win rate",
            format_pct(100.0 * n_winning / n_trades_total),
            f"{n_winning} of {n_trades_total} trades profitable",
            delta_color="off",
        )

    # === Card 3 — TOTAL NET P&L ==============================
    # Sum across ALL filtered trades — including thin-N pairs the
    # ranker suppresses — so the operator's "did this filter view
    # make money overall?" question is answered honestly. The
    # subtitle counts ALL pairs (not just rank-eligible) to match.
    # This is a minor wording divergence from DESIGN_SPEC §2.5
    # ("across N rank-eligible cells") — implementation chose
    # whole-filter honesty over rank-window restriction. Documented
    # in DESIGN_SPEC §9 followup; either treatment is defensible.
    total_pnl = float(df["net_pnl"].sum())
    with cols[2]:
        st.metric(
            "Total net P&L",
            format_inr(total_pnl),
            f"across {n_pairs_total} (strategy, symbol) pair(s)",
            delta_color="off",
        )

    # === Card 4 — RANKED PAIRS ===============================
    with cols[3]:
        st.metric(
            "Ranked pairs",
            f"{n_pairs_eligible}/{n_pairs_total}",
            f"min_n={min_n} from sidebar",
            delta_color="off",
        )


# ============================================================
# Rank table — Phase 6.2 commit 12 (feat(p6.2.table))
# ============================================================

def render_rank_table(df: pd.DataFrame, *, min_n: int) -> None:
    """Render the main leaderboard rank table per DESIGN_SPEC §4
    commit 12. Columns (left → right):

      rank, strategy, symbol, n_trades, win_rate_pct, median_roi_ann,
      mean_roi_ann, std_roi_ann, total_net_pnl

    Empty-frame paths per §2.6:
      - 0 rows after filters             → leaderboard_no_rows_after_filters
      - 0 rows pass min_n AND ≥1 pair    → leaderboard_all_below_min_n

    Column formatting via st.column_config:
      - win_rate_pct       — ProgressColumn (0-100 range; visual bar)
      - rupee P&L          — NumberColumn with format="₹%,.0f"
      - percentages        — NumberColumn with format="%.1f%%"
        (per-trade ROI throughout per p7.expiry_roi)
    """
    if len(df) == 0:
        render_empty("leaderboard_no_rows_after_filters")
        return

    summary = summarize_by_stock_strategy(df)
    n_pairs_total = int(len(summary))
    ranked = _rank_quiet(summary, min_n=min_n)
    if len(ranked) == 0:
        render_empty(
            "leaderboard_all_below_min_n",
            n_pairs=n_pairs_total, min_n=min_n,
        )
        return

    # Slice to the columns we display. The aggregator emits more (e.g.
    # mean_net_pnl, worst/best per trade) — leaderboard surface keeps it
    # tight; full table is accessible via the CSV export (Phase 7).
    # Column order per DESIGN_SPEC §2.2: n_trades immediately right of
    # rank. The operator scans rank → N to judge how seriously to take
    # the row before reading the metrics; putting strategy/symbol in
    # between would force a backtrack.
    display_cols = [
        "rank", "n_trades", "strategy", "symbol",
        "win_rate_pct",
        "median_roi_pct",
        "mean_roi_pct",
        "std_roi_pct",
        "total_net_pnl",
    ]
    table = ranked[display_cols].copy()

    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "rank": st.column_config.NumberColumn(
                "#", format="%d", width="small",
                help="1-indexed; higher = lower rank.",
            ),
            "strategy": st.column_config.TextColumn(
                "Strategy", width="medium",
            ),
            "symbol": st.column_config.TextColumn(
                "Symbol", width="small",
            ),
            "n_trades": st.column_config.NumberColumn(
                "N", format="%d", width="small",
                help=(
                    "Sample size. Sidebar min_n suppresses rows with "
                    "fewer than this threshold from the ranking."
                ),
            ),
            "win_rate_pct": st.column_config.ProgressColumn(
                "Win %", format="%.1f%%",
                min_value=0.0, max_value=100.0, width="small",
            ),
            "median_roi_pct": st.column_config.NumberColumn(
                "Median ROI", format="%+.1f%%",
                help=(
                    "Median holding-period ROI annualized to 252 trading days "
                    "(SPECS §4a caveat #2). Cross-window-comparable; robust "
                    "to single-trade outliers in small N samples."
                ),
            ),
            "mean_roi_pct": st.column_config.NumberColumn(
                "Mean ROI", format="%+.1f%%",
            ),
            "std_roi_pct": st.column_config.NumberColumn(
                "Std ROI", format="±%.1f%%",
                help=(
                    "Observed-sample dispersion (ddof=0). Treat as LOWER "
                    "BOUND on true population spread; small-N groups "
                    "understate spread by ~11% at n=5, ~5% at n=10, "
                    "~2.5% at n=20."
                ),
            ),
            "total_net_pnl": st.column_config.NumberColumn(
                "Net P&L (₹)", format="₹%,.0f",
                help="Sum of net_pnl across this pair's trades.",
            ),
        },
    )

    # Footer note — sample-size transparency per SPECS §11.5 +
    # DESIGN_SPEC §2.2 (`n_trades` visually prominent next to `rank`).
    st.caption(
        f"Showing {len(ranked)} of {n_pairs_total} (strategy, symbol) "
        f"pair(s) — min_n={min_n} from sidebar. Smaller-N pair(s) are "
        f"available in the 'Thin samples — not ranked' sidecar below."
    )


# ============================================================
# Within-stock rank — Phase 6.2 commit 14 (feat(p6.2.toggle))
# ============================================================

# Session-state key + canonical mode strings for the within/across toggle.
TOGGLE_KEY: str = "mp_leaderboard_mode"
MODE_ACROSS: str = "Across stocks"
MODE_WITHIN: str = "Within stock"


def render_mode_toggle() -> str:
    """Render the across/within toggle at the top of the leaderboard
    table area. Returns the selected mode string; persists to
    ``st.session_state[TOGGLE_KEY]``.

    Mode semantics:
      Across stocks (default) — rank every (strategy, symbol) pair
                                 against every other; rank=1 = best
                                 pair in the sweep.
      Within stock           — rank strategies per symbol; rank=1 =
                                 best strategy ON THIS SYMBOL. Answers
                                 the "which window for stock X?" view
                                 per DESIGN_SPEC §5.2.
    """
    if TOGGLE_KEY not in st.session_state:
        st.session_state[TOGGLE_KEY] = MODE_ACROSS
    mode = st.radio(
        "Rank grouping",
        options=[MODE_ACROSS, MODE_WITHIN],
        index=[MODE_ACROSS, MODE_WITHIN].index(st.session_state[TOGGLE_KEY]),
        horizontal=True,
        key=TOGGLE_KEY,
        help=(
            "Across stocks → one big rank table across every "
            "(strategy, symbol) pair. Within stock → strategies "
            "ranked per symbol; the rank column resets at each new "
            "symbol."
        ),
    )
    return mode


def render_within_stock_rank(df: pd.DataFrame, *, min_n: int) -> None:
    """Per-symbol leaderboard: group by symbol, rank strategies inside
    each group. One table; symbol becomes a leading column, and the
    `#` rank resets to 1 at each symbol boundary.

    Empty-state paths mirror render_rank_table:
      - 0 rows → leaderboard_no_rows_after_filters
      - all-below-min_n → leaderboard_all_below_min_n

    Implementation note: this function DOES NOT call
    ``rank_strategies`` (unlike ``render_rank_table``). It filters via
    pandas ``.query``-equivalent comparison then assigns per-symbol
    ranks via ``groupby("symbol").cumcount() + 1``. Consequence: the
    analytics-layer 100%-suppression UserWarning does NOT fire on the
    all-below-min_n branch here (different code path, no rank_strategies
    invocation). The UI tier still routes to the canonical
    leaderboard_all_below_min_n empty-state message via render_empty —
    same operator experience, different internals.
    """
    if len(df) == 0:
        render_empty("leaderboard_no_rows_after_filters")
        return

    summary = summarize_by_stock_strategy(df)
    n_pairs_total = int(len(summary))
    # min_n filter first, then per-symbol rank
    eligible = summary[summary["n_trades"] >= min_n].copy()
    if len(eligible) == 0:
        render_empty(
            "leaderboard_all_below_min_n",
            n_pairs=n_pairs_total, min_n=min_n,
        )
        return

    # Per-symbol rank by median_roi_pct DESC.
    # Sort + cumulative rank within group; final sort is by (symbol,
    # rank_within_symbol) so the table reads naturally.
    eligible = eligible.sort_values(
        ["symbol", "median_roi_pct"],
        ascending=[True, False],
    )
    eligible["rank_within_symbol"] = (
        eligible.groupby("symbol").cumcount() + 1
    )
    eligible = eligible.sort_values(
        ["symbol", "rank_within_symbol"]
    ).reset_index(drop=True)

    # Same §2.2 contract for the per-symbol leaderboard — N immediately
    # right of the rank column (rank_within_symbol here).
    display_cols = [
        "symbol", "rank_within_symbol", "n_trades", "strategy",
        "win_rate_pct",
        "median_roi_pct",
        "mean_roi_pct",
        "std_roi_pct",
        "total_net_pnl",
    ]
    table = eligible[display_cols]

    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "symbol": st.column_config.TextColumn(
                "Symbol", width="small",
            ),
            "rank_within_symbol": st.column_config.NumberColumn(
                "#", format="%d", width="small",
                help="Rank WITHIN this symbol; 1 = best strategy on this stock.",
            ),
            "strategy": st.column_config.TextColumn(
                "Strategy", width="medium",
            ),
            "n_trades": st.column_config.NumberColumn(
                "N", format="%d", width="small",
            ),
            "win_rate_pct": st.column_config.ProgressColumn(
                "Win %", format="%.1f%%",
                min_value=0.0, max_value=100.0, width="small",
            ),
            "median_roi_pct": st.column_config.NumberColumn(
                "Median ROI", format="%+.1f%%",
            ),
            "mean_roi_pct": st.column_config.NumberColumn(
                "Mean ROI", format="%+.1f%%",
            ),
            "std_roi_pct": st.column_config.NumberColumn(
                "Std ROI", format="±%.1f%%",
            ),
            "total_net_pnl": st.column_config.NumberColumn(
                "Net P&L (₹)", format="₹%,.0f",
            ),
        },
    )
    st.caption(
        f"Showing {len(eligible)} of {n_pairs_total} (strategy, "
        f"symbol) pair(s) across {eligible['symbol'].nunique()} "
        f"symbol(s) — min_n={min_n} from sidebar. Rank resets per "
        f"symbol; thin samples in sidecar below."
    )


# ============================================================
# Thin samples sidecar — Phase 6.2 commit 13 (feat(p6.2.thin))
# ============================================================

def render_thin_samples(df: pd.DataFrame, *, min_n: int) -> None:
    """Render rows with ``n_trades < min_n`` under a "Thin samples —
    not ranked" sidecar (per DESIGN_SPEC §4 commit 13 +
    statistical-honesty discipline at SPECS §11.5).

    The ranker silently drops these rows from the leaderboard
    (different from aggregate, which surfaces them); the UI tier
    re-surfaces them so the operator sees what was suppressed and
    can lower the threshold if a thin row looks promising. Two-layer
    statistical-honesty: analytics is curated, UI is transparent.

    No-op if every pair clears ``min_n`` — operator doesn't need to
    see an empty sidecar.
    """
    if len(df) == 0:
        # The empty-frame message already lives in the main rank-table
        # path; sidecar stays silent.
        return

    summary = summarize_by_stock_strategy(df)
    thin = summary[summary["n_trades"] < min_n].copy()
    if len(thin) == 0:
        # All pairs clear threshold — no sidecar needed.
        st.caption(
            f"_All {len(summary)} (strategy, symbol) pair(s) clear "
            f"min_n={min_n} — no thin samples to surface._"
        )
        return

    # Sort thin samples by n_trades DESC then by median ann ROI DESC
    # so the operator sees the "biggest, best" thin samples first
    # (the ones most worth investigating further by lowering min_n).
    thin = thin.sort_values(
        ["n_trades", "median_roi_pct"],
        ascending=[False, False],
    ).reset_index(drop=True)

    display_cols = [
        "strategy", "symbol", "n_trades",
        "win_rate_pct",
        "median_roi_pct",
        "std_roi_pct",
        "total_net_pnl",
    ]
    table = thin[display_cols]

    st.markdown("#### Thin samples — not ranked")
    st.caption(
        f"{len(thin)} (strategy, symbol) pair(s) with N below the "
        f"sidebar threshold ({min_n}). The leaderboard ranker "
        f"suppresses these per the statistical-honesty contract; "
        f"lower min_n to inspect anyway."
    )
    st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        column_config={
            "strategy": st.column_config.TextColumn(
                "Strategy", width="medium",
            ),
            "symbol": st.column_config.TextColumn(
                "Symbol", width="small",
            ),
            "n_trades": st.column_config.NumberColumn(
                "N", format="%d", width="small",
                help=(
                    f"Sample size — all rows here have N < {min_n}. "
                    f"Median statistics are unreliable at this scale."
                ),
            ),
            "win_rate_pct": st.column_config.ProgressColumn(
                "Win %", format="%.1f%%",
                min_value=0.0, max_value=100.0, width="small",
            ),
            "median_roi_pct": st.column_config.NumberColumn(
                "Median ROI", format="%+.1f%%",
            ),
            "std_roi_pct": st.column_config.NumberColumn(
                "Std ROI", format="±%.1f%%",
            ),
            "total_net_pnl": st.column_config.NumberColumn(
                "Net P&L (₹)", format="₹%,.0f",
            ),
        },
    )
