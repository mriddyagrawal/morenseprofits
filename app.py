"""morenseprofits — Streamlit dashboard entry point.

Phase 6.1 skeleton. Thin: header → caveats → sidebar filters → 4 tabs
(currently placeholders). Subsequent commits flesh out each tab:

  p6.2.* — Leaderboard
  p6.3.* — Heatmap
  p6.4.* — Trends
  p6.5.* — Per-stock

Run with:
    streamlit run app.py

State convention (SPECS §11.4): every cross-cutting filter lives in
``st.session_state`` with keys prefixed ``mp_``. Tab modules read from
state; they never own filter state.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# When invoked via `streamlit run app.py` the cwd is the repo root —
# `src/...` imports just work. The explicit sys.path keeps the script
# runnable from any cwd.
REPO = Path(__file__).resolve().parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.analytics.aggregate import MIN_N_FOR_RANKING  # noqa: E402
from src.config import RESULTS_DIR  # noqa: E402
from src.strategies.registry import list_strategies  # noqa: E402
from src.web.caveats import render_caveats  # noqa: E402
from src.web.discover import find_latest_sweep, read_sweep_with_skips  # noqa: E402
from src.web.heatmap import (  # noqa: E402
    _selector as render_heatmap_selector,
    render_cell_drilldown as render_heatmap_drilldown,
    render_headline as render_heatmap_headline,
    render_heatmaps,
)
from src.web.leaderboard import (  # noqa: E402
    MODE_ACROSS,
    MODE_WITHIN,
    render_headline as render_leaderboard_headline,
    render_mode_toggle,
    render_rank_table,
    render_thin_samples,
    render_within_stock_rank,
)
from src.web.per_stock import (  # noqa: E402
    _quick_switcher as render_per_stock_switcher,
    render_headline as render_per_stock_headline,
    render_strategy_dashboard,
)
from src.web.trends import (  # noqa: E402
    _selector as render_trends_selector,
    render_headline as render_trends_headline,
    render_moy as render_trends_moy,
    render_yoy as render_trends_yoy,
    render_yoy_n as render_trends_yoy_n,
)


# ============================================================
# Page config — must be the first Streamlit call.
# ============================================================
st.set_page_config(
    page_title="morenseprofits — NSE options backtest research",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# Session-state defaults (SPECS §11.4 — `mp_` prefix)
# ============================================================
def _init_state() -> None:
    """Initialise every mp_ key once per session. Idempotent."""
    defaults = {
        "mp_caveats_dismissed": False,
        "mp_selected_sweep": None,    # Path | None — set by sidebar
        "mp_strategies_filter": [],   # list[str] — empty = all
        "mp_symbols_filter": [],      # list[str] — empty = all
        "mp_min_n": MIN_N_FOR_RANKING,
        "mp_regime_filter": "all",    # str: all | bullish | neutral | non_bullish
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


_init_state()


# ============================================================
# Data loading — cached so tab switches don't re-read parquet.
# ============================================================
@st.cache_data(show_spinner=False)
def _load_sweep(parquet_path_str: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cache-key on str(path) — Streamlit's hash works for strings."""
    return read_sweep_with_skips(Path(parquet_path_str))


# ============================================================
# Header — project name + sweep selector + status
# ============================================================
def _render_header() -> None:
    latest = find_latest_sweep(RESULTS_DIR)
    cols = st.columns([3, 4, 2])
    with cols[0]:
        st.markdown("### 📈 morenseprofits")
        st.caption("NSE options backtest research — Phase 6 v1")
    with cols[1]:
        if latest is None:
            st.warning(
                "No sweep parquets in `data/results/`. Run "
                "`python scripts/verify_p4.py` to produce one."
            )
            st.session_state["mp_selected_sweep"] = None
        else:
            st.session_state["mp_selected_sweep"] = latest
            mtime = datetime.fromtimestamp(latest.stat().st_mtime)
            st.markdown(f"**Sweep:** `{latest.name}`")
            st.caption(f"updated {mtime.strftime('%Y-%m-%d %H:%M')}")
    with cols[2]:
        st.caption("")  # alignment spacer
        st.caption("v0.6.1 skeleton")


# ============================================================
# Sidebar — cross-cutting filters (SPECS §11.4 / §11.5)
# ============================================================
def _render_sidebar(results_df: pd.DataFrame) -> None:
    st.sidebar.markdown("### Filters")

    available_strategies = (
        sorted(results_df["strategy"].unique().tolist())
        if len(results_df) else list_strategies()
    )
    st.session_state["mp_strategies_filter"] = st.sidebar.multiselect(
        "Strategies",
        options=available_strategies,
        default=st.session_state["mp_strategies_filter"] or available_strategies,
        help="Filter every tab. Empty = all strategies.",
    )

    available_symbols = (
        sorted(results_df["symbol"].unique().tolist())
        if len(results_df) else []
    )
    st.session_state["mp_symbols_filter"] = st.sidebar.multiselect(
        "Symbols",
        options=available_symbols,
        default=st.session_state["mp_symbols_filter"] or available_symbols,
        help="Filter every tab. Empty = all symbols in the sweep.",
    )

    st.sidebar.markdown("---")
    st.session_state["mp_min_n"] = st.sidebar.slider(
        "Min N for ranking",
        min_value=1,
        max_value=50,
        value=int(st.session_state["mp_min_n"]),
        step=1,
        help=(
            "Statistical-honesty threshold (DESIGN_SPEC §1.2). "
            "Leaderboard suppresses + heatmap masks cells with "
            "fewer than N trades. Default = 5."
        ),
    )

    st.sidebar.markdown("---")
    st.session_state["mp_regime_filter"] = st.sidebar.radio(
        "Regime filter",
        options=["all", "bullish", "neutral", "non_bullish"],
        index=["all", "bullish", "neutral", "non_bullish"].index(
            st.session_state["mp_regime_filter"]
        ),
        help=(
            "Filter symbols by trailing-6mo-return regime "
            "(Phase 6.5+ wire-up; v0.6.1 placeholder)."
        ),
    )

    # Sweep metadata for orientation
    st.sidebar.markdown("---")
    st.sidebar.caption("**Sweep metadata**")
    if len(results_df):
        st.sidebar.caption(f"rows: {len(results_df)}")
        st.sidebar.caption(
            f"strategies: {results_df['strategy'].nunique()}  "
            f"·  symbols: {results_df['symbol'].nunique()}"
        )
        if "run_id" in results_df.columns and len(results_df):
            run_id = results_df["run_id"].iloc[0]
            st.sidebar.caption(f"run_id: `{run_id}`")


# ============================================================
# Filter-application helper — every tab calls this before render.
# ============================================================
def _apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    """Apply the sidebar's strategy + symbol multiselect filters."""
    if df.empty:
        return df
    out = df
    sf = st.session_state.get("mp_strategies_filter") or []
    if sf:
        out = out[out["strategy"].isin(sf)]
    yf = st.session_state.get("mp_symbols_filter") or []
    if yf:
        out = out[out["symbol"].isin(yf)]
    return out


# ============================================================
# Tab placeholders — Phase 6.2-6.5 will replace each
# ============================================================
def _placeholder(tab_name: str, next_commit: str) -> None:
    st.info(
        f"**{tab_name}** — placeholder. Implemented in `{next_commit}`."
    )


def _render_leaderboard_tab(df_filtered: pd.DataFrame) -> None:
    render_caveats(tab_id="leaderboard")
    st.markdown("## Leaderboard")
    min_n = int(st.session_state["mp_min_n"])
    render_leaderboard_headline(df_filtered, min_n=min_n)
    st.markdown("---")
    mode = render_mode_toggle()
    if mode == MODE_WITHIN:
        render_within_stock_rank(df_filtered, min_n=min_n)
    else:
        render_rank_table(df_filtered, min_n=min_n)
    st.markdown("---")
    render_thin_samples(df_filtered, min_n=min_n)


def _render_per_stock_tab(df_filtered: pd.DataFrame) -> None:
    render_caveats(tab_id="per_stock")
    st.markdown("## Per-stock")
    min_n = int(st.session_state["mp_min_n"])
    symbol = render_per_stock_switcher(df_filtered)
    render_per_stock_headline(df_filtered, symbol=symbol, min_n=min_n)
    st.markdown("---")
    render_strategy_dashboard(df_filtered, symbol=symbol, min_n=min_n)


def _render_heatmap_tab(df_filtered: pd.DataFrame, skips_df: pd.DataFrame) -> None:
    render_caveats(tab_id="heatmap")
    st.markdown("## Heatmap")
    min_n = int(st.session_state["mp_min_n"])
    strategy, symbol = render_heatmap_selector(df_filtered)
    render_heatmap_headline(
        df_filtered, strategy=strategy, symbol=symbol, min_n=min_n,
    )
    st.markdown("---")
    render_heatmaps(
        df_filtered, strategy=strategy, symbol=symbol, min_n=min_n,
    )
    render_heatmap_drilldown(
        df_filtered, skips_df=skips_df, strategy=strategy, symbol=symbol,
    )


def _render_trends_tab(df_filtered: pd.DataFrame) -> None:
    render_caveats(tab_id="trends")
    st.markdown("## Trends")
    min_n = int(st.session_state["mp_min_n"])
    strategy, symbol = render_trends_selector(df_filtered)
    render_trends_headline(
        df_filtered, strategy=strategy, symbol=symbol, min_n=min_n,
    )
    st.markdown("---")
    render_trends_yoy(
        df_filtered, strategy=strategy, symbol=symbol, min_n=min_n,
    )
    render_trends_yoy_n(
        df_filtered, strategy=strategy, symbol=symbol, min_n=min_n,
    )
    st.markdown("---")
    render_trends_moy(
        df_filtered, strategy=strategy, symbol=symbol, min_n=min_n,
    )


# ============================================================
# Main
# ============================================================
def main() -> None:
    _render_header()

    selected = st.session_state.get("mp_selected_sweep")
    if selected is None:
        return  # header already rendered the "no sweeps" warning

    try:
        results_df, skips_df = _load_sweep(str(selected))
    except FileNotFoundError as e:
        st.error(f"Sweep parquet not found: {e}")
        return
    except Exception as e:  # pyarrow.lib.ArrowInvalid, etc.
        st.error(f"Failed to read sweep parquet: {e}")
        return

    _render_sidebar(results_df)
    df_filtered = _apply_filters(results_df)

    tabs = st.tabs(["Leaderboard", "Per-stock", "Heatmap", "Trends"])
    with tabs[0]:
        _render_leaderboard_tab(df_filtered)
    with tabs[1]:
        _render_per_stock_tab(df_filtered)
    with tabs[2]:
        _render_heatmap_tab(df_filtered, skips_df=skips_df)
    with tabs[3]:
        _render_trends_tab(df_filtered)


if __name__ == "__main__":
    main()
else:
    # Streamlit imports this module directly (not via __main__), so
    # the entry-point check above doesn't fire. Run main() at import
    # time so `streamlit run app.py` works.
    main()
