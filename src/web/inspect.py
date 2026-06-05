"""Inspect tab — visual diagnosis of a single sweep row.

Implements the SKELETON commit of Phase 9.5 per PORTFOLIO_MEMOIR.md §24:

  - 5 first-class selectors with cascading validity (§24.8)
  - URL-param read on mount per the deeplink contract (§24.9)
  - Header with TAKEN status badge (§24.2 — Phase 9.2 will replace
    with real status once the filter pipeline ships)
  - 6-card stat strip (§24.2)
  - Footer caption per §24.1 + §9

Hot-path constraint (§24.1, CONSTRAINT 1): this module contains ZERO
Black-Scholes pricing or inversion calls. All BS work happened
upstream in the engine when iv_materializer built
``data/cache/iv/{SYMBOL}.parquet``. Inspect is a pure read from the
cache. A reviewer-grep gate enforced in tests/test_web_inspect.py
rejects any banned BS-call pattern in this file; see that file's
``_BS_REJECT_PATTERNS`` for the canonical list.

Deferred to follow-on commits in this cluster:
  - Position map chart                    → Phase 9.5.2
  - Cumulative P&L path + legs table       → Phase 9.5.3

Forward-dependencies on later phases:
  - Counterfactual rendering for non-taken trades depends on Phase
    9.2 filter pipeline adding a ``status`` column to sweep rows.
    Until then EVERY sweep row is rendered as TAKEN.
  - Regime tag depends on Phase 9.4/9.6 building a regime cache; for
    now the badge slot renders ``REGIME: —`` to preserve the layout.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analytics.ivp import compute_ivp
from src.data.errors import (
    IlliquidLegError, MissingDataError, MissingTurnoverError, OfflineCacheMiss,
)
from src.data.events_loader import load_events
from src.data.iv_materializer import load_iv_history
from src.data.options_loader import load_option
from src.data.spot_loader import load_spot
from src.data.trading_calendar import trading_days


# ============================================================
# URL-param schema (memoir §24.9) — public deeplink contract
# ============================================================

URL_PARAM_STRATEGY = "strategy"
URL_PARAM_SYMBOL = "symbol"
URL_PARAM_EXPIRY = "expiry"
URL_PARAM_ENTRY = "entry_offset_td"
URL_PARAM_EXIT = "exit_offset_td"

URL_PARAM_KEYS = (
    URL_PARAM_STRATEGY,
    URL_PARAM_SYMBOL,
    URL_PARAM_EXPIRY,
    URL_PARAM_ENTRY,
    URL_PARAM_EXIT,
)


# ============================================================
# Session-state keys — PRIVATE (memoir §24.9)
# Internal to this module. Deeplink writers (Portfolio in Phase 9.4)
# MUST use the URL-param schema above, NOT these keys. Renaming these
# is allowed; renaming the URL-param schema is not.
# ============================================================

_SS_STRATEGY = "mp_inspect_strategy"
_SS_SYMBOL = "mp_inspect_symbol"
_SS_EXPIRY = "mp_inspect_expiry"
_SS_ENTRY = "mp_inspect_entry"
_SS_EXIT = "mp_inspect_exit"


_PRIVATE_SS_KEYS = (
    _SS_STRATEGY, _SS_SYMBOL, _SS_EXPIRY, _SS_ENTRY, _SS_EXIT,
)


# ============================================================
# IV series choice — memoir §24.10 / §2.2 step 7
# ============================================================
# Series C (30D CMI with 7-DTE exclusion) is the operator-locked
# production default. The iv_materializer cache stores it in the
# ``iv_cmi30_excl7`` column. Other valid values: ``iv_front`` (raw
# front-month, includes 1-DTE blowups), ``iv_cmi30_raw`` (30D CMI
# without exclusion). See PORTFOLIO_MEMOIR.md §2.2.
_IV_COLUMN = "iv_cmi30_excl7"


# ============================================================
# Cascading-validity snap (memoir §24.8)
# ============================================================

def _snap_to_valid(
    df: pd.DataFrame,
    strategy=None, symbol=None, expiry=None, entry=None, exit_=None,
):
    """Snap a proposed 5-tuple to the nearest valid combination in the
    sweep grid. Per §24.8: changing any selector may invalidate
    downstream selectors; cascade left-to-right and re-default each
    invalidated dimension to a sensible value.

    Cascade order: strategy → symbol → expiry → entry → exit.

    Returns ``(strategy, symbol, expiry, entry, exit)`` or ``None`` if
    the frame has no rows at all.

    Defaults at each level (when the proposed value is invalid or
    None):
      strategy : first by sorted value
      symbol   : first by sorted value among the chosen strategy
      expiry   : MOST RECENT (highest) expiry for (strategy, symbol)
      entry    : MEDIAN entry_offset_td for (strategy, symbol, expiry)
      exit     : MEDIAN exit_offset_td that satisfies ``exit < entry``

    The "entry > exit" constraint is the sweep grid's hard rule
    (entries are days before expiry; exit must be closer to expiry
    than entry). If no exit < entry exists for the chosen entry, we
    back off to a different entry (iterating downward through valid
    entries) until one with a valid exit appears.
    """
    if df.empty:
        return None

    strategies = sorted(df["strategy"].unique())
    if strategy not in strategies:
        strategy = strategies[0]
    sdf = df[df["strategy"] == strategy]
    if sdf.empty:
        return None

    symbols = sorted(sdf["symbol"].unique())
    if symbol not in symbols:
        symbol = symbols[0]
    sdf = sdf[sdf["symbol"] == symbol]
    if sdf.empty:
        return None

    expiries = sorted(sdf["expiry"].unique())
    if expiry not in expiries:
        expiry = expiries[-1]
    sdf = sdf[sdf["expiry"] == expiry]
    if sdf.empty:
        return None

    entries = sorted(sdf["entry_offset_td"].unique())
    if entry not in entries:
        entry = int(entries[len(entries) // 2])

    # Exit must be strictly less than entry. If the picked entry has no
    # valid exit, walk down through smaller entries until one does.
    def _valid_exits(e):
        edf = sdf[sdf["entry_offset_td"] == e]
        return sorted(edf[edf["exit_offset_td"] < e]["exit_offset_td"].unique())

    exits = _valid_exits(entry)
    if not exits:
        for e in reversed(entries):
            v = _valid_exits(e)
            if v:
                entry = int(e)
                exits = v
                break
        if not exits:
            return None

    if exit_ not in exits:
        exit_ = int(exits[len(exits) // 2])

    return strategy, symbol, expiry, int(entry), int(exit_)


# ============================================================
# URL-param read (memoir §24.9)
# ============================================================

def _read_url_params() -> dict:
    """Read the 5 Inspect URL params. Missing or unparseable values are
    simply absent from the returned dict — the caller blends them with
    session-state or defaults via the cascading-validity snap."""
    out: dict = {}
    qp = st.query_params

    def _scalar(key):
        v = qp.get(key)
        if isinstance(v, list):
            return v[0] if v else None
        return v

    s = _scalar(URL_PARAM_STRATEGY)
    if s:
        out["strategy"] = s
    s = _scalar(URL_PARAM_SYMBOL)
    if s:
        out["symbol"] = s
    s = _scalar(URL_PARAM_EXPIRY)
    if s:
        try:
            out["expiry"] = pd.to_datetime(s)
        except (ValueError, TypeError):
            pass
    s = _scalar(URL_PARAM_ENTRY)
    if s:
        try:
            out["entry_offset_td"] = int(s)
        except (ValueError, TypeError):
            pass
    s = _scalar(URL_PARAM_EXIT)
    if s:
        try:
            out["exit_offset_td"] = int(s)
        except (ValueError, TypeError):
            pass
    return out


def _initialize_session_state(df: pd.DataFrame) -> None:
    """Seed Inspect's private session state on FIRST RENDER ONLY.

    Precedence on first render: URL params (deeplink) > cascading
    defaults (per §24.8). After first render, the selectbox widgets in
    ``_render_selectors`` own their keys via Streamlit's widget binding;
    that function's pre-clip pattern handles validity on every render,
    so re-seeding here would only clobber user clicks.

    Why first-render-only (closes 7aef085 GRILL 1, "URL-precedence
    locks user clicks post-deeplink"): the previous ``url.get(k) or
    session_state.get(k)`` pattern made URL always win when present.
    Sequence that exposed the bug:

      1. Operator opens ``?strategy=A&...`` deeplink.
      2. First render: URL ``A`` wins → ``session_state.strategy = A``.
      3. Operator clicks the strategy selectbox to ``B`` → widget
         binding writes ``session_state.strategy = B`` and triggers
         rerun.
      4. Rerun: this function ran again. URL still has ``A`` (Streamlit
         doesn't auto-clear ``st.query_params``). ``A or B`` → ``A``
         wins → clobbers operator's click.

    Mirrors ``app.py``'s tab-routing seed:

        if "mp_active_tab" not in st.session_state:
            st.session_state["mp_active_tab"] = url_tab

    The cascading-validity snap is still applied (so a malformed
    deeplink lands on a real sweep row), but only at seed time.

    Phase 9.4 / future deeplink writers MUST call
    ``clear_inspect_state()`` immediately before ``st.rerun()`` so a
    fresh URL is honored. Reaching into ``mp_inspect_*`` keys directly
    would violate the §24.9 contract that session-state is private to
    this module.
    """
    if _SS_STRATEGY in st.session_state:
        # Already seeded; widget binding owns the keys from here.
        return

    url = _read_url_params()
    snapped = _snap_to_valid(
        df,
        url.get("strategy"),
        url.get("symbol"),
        url.get("expiry"),
        url.get("entry_offset_td"),
        url.get("exit_offset_td"),
    )
    if snapped is None:
        return
    s, sym, exp, en, ex = snapped
    st.session_state[_SS_STRATEGY] = s
    st.session_state[_SS_SYMBOL] = sym
    st.session_state[_SS_EXPIRY] = exp
    st.session_state[_SS_ENTRY] = en
    st.session_state[_SS_EXIT] = ex


def clear_inspect_state() -> None:
    """Drop Inspect's private session-state keys so the next render
    re-seeds from URL.

    Public helper for deeplink writers (Phase 9.4 Portfolio → Inspect,
    any future source). Lets them write new ``st.query_params`` + call
    ``st.rerun()`` without violating the §24.9 contract that
    ``mp_inspect_*`` keys are private to this module.

    Usage in a deeplink writer:

        for k, v in deeplink_url_params.items():
            st.query_params[k] = v
        st.query_params["tab"] = "Inspect"
        from src.web.inspect import clear_inspect_state
        clear_inspect_state()
        st.rerun()
    """
    for k in _PRIVATE_SS_KEYS:
        st.session_state.pop(k, None)


# ============================================================
# Selector widgets — 5 first-class selectbox dropdowns (§24.8)
# ============================================================
# Cascading is implicit via per-widget options-recomputation: each
# widget's options are filtered by the upstream selections currently
# in session state. If a stale downstream selection becomes invalid
# after an upstream change, we pre-clip it to the new options[0]
# BEFORE the widget renders so Streamlit doesn't raise on the
# value-not-in-options branch.
# ============================================================

def _render_selectors(df: pd.DataFrame) -> None:
    cols = st.columns(5)

    # 1 · strategy
    strategies = sorted(df["strategy"].unique())
    if st.session_state.get(_SS_STRATEGY) not in strategies:
        st.session_state[_SS_STRATEGY] = strategies[0] if strategies else None
    with cols[0]:
        st.selectbox(
            "strategy", strategies, key=_SS_STRATEGY,
        )
    s = st.session_state[_SS_STRATEGY]

    # 2 · symbol — filtered by strategy
    syms = sorted(df[df["strategy"] == s]["symbol"].unique())
    if st.session_state.get(_SS_SYMBOL) not in syms:
        st.session_state[_SS_SYMBOL] = syms[0] if syms else None
    with cols[1]:
        st.selectbox(
            "symbol", syms, key=_SS_SYMBOL,
        )
    sym = st.session_state[_SS_SYMBOL]

    # 3 · expiry (cycle) — filtered by (strategy, symbol)
    exps_ts = sorted(
        df[(df["strategy"] == s) & (df["symbol"] == sym)]["expiry"].unique()
    )
    if st.session_state.get(_SS_EXPIRY) not in exps_ts:
        st.session_state[_SS_EXPIRY] = exps_ts[-1] if exps_ts else None
    with cols[2]:
        st.selectbox(
            "cycle (expiry)", exps_ts, key=_SS_EXPIRY,
            format_func=lambda d: pd.to_datetime(d).strftime("%Y-%m-%d"),
        )
    exp = st.session_state[_SS_EXPIRY]

    # 4 · entry_offset_td — filtered by (strategy, symbol, expiry)
    sub = df[
        (df["strategy"] == s)
        & (df["symbol"] == sym)
        & (df["expiry"] == exp)
    ]
    entries = sorted(int(x) for x in sub["entry_offset_td"].unique())
    if st.session_state.get(_SS_ENTRY) not in entries:
        st.session_state[_SS_ENTRY] = (
            entries[len(entries) // 2] if entries else None
        )
    with cols[3]:
        st.selectbox(
            "entry offset", entries, key=_SS_ENTRY,
            format_func=lambda n: f"T-{n}",
        )
    en = st.session_state[_SS_ENTRY]

    # 5 · exit_offset_td — entry > exit per the grid constraint
    exits = sorted(
        int(x) for x in
        sub[sub["exit_offset_td"] < en]["exit_offset_td"].unique()
    )
    if st.session_state.get(_SS_EXIT) not in exits:
        st.session_state[_SS_EXIT] = (
            exits[len(exits) // 2] if exits else None
        )
    with cols[4]:
        st.selectbox(
            "exit offset", exits, key=_SS_EXIT,
            format_func=lambda n: f"T-{n}",
        )


# ============================================================
# Header — sym + strategy tag + cycle + offsets + regime + status
# ============================================================

def _render_header(row, strategy, symbol, expiry, entry, exit_):
    exp_str = pd.to_datetime(expiry).strftime("%Y-%m-%d")

    st.markdown(
        f"## inspect_trade · {symbol} · {exp_str} · T-{entry}/T-{exit_}"
    )

    bits = [
        f"**{symbol}**",
        f"`{strategy}`",
        f"cycle {exp_str}",
        f"entry T-{entry} → exit T-{exit_}",
        f"{int(row['hold_trading_days'])} TD held",
    ]
    st.markdown("  ·  ".join(bits))

    # Regime tag + status tag row. Regime is a forward-dependency on
    # Phase 9.4/9.6 regime materializer; status is a forward-dependency
    # on Phase 9.2 filter pipeline. Until those land we render
    # placeholder REGIME and pin status=TAKEN.
    tcols = st.columns([1, 1, 6])
    with tcols[0]:
        st.markdown(":grey-background[**REGIME: —**]")
    with tcols[1]:
        st.markdown(":green-background[**TAKEN**]")


# ============================================================
# Stat strip — 6 cards (memoir §24.2)
# ============================================================

def _net_credit_at_entry(legs_json_str: str) -> float:
    """Sum across legs of (entry_px_realized × qty_lots × lot_size)
    with side_sign(SELL)=+1, side_sign(BUY)=−1. Net credit collected
    at entry. Uses the OBSERVED entry premium per CONSTRAINT 1 —
    legs_json carries the price at fill time, no re-derivation."""
    legs = json.loads(legs_json_str)
    total = 0.0
    for leg in legs:
        side_sign = 1.0 if leg["side"] == "SELL" else -1.0
        px = float(leg["entry_px_realized"])
        qty = int(leg["qty_lots"])
        lot = int(leg["lot_size"])
        total += side_sign * px * qty * lot
    return total


def _iv_at_date(symbol: str, target_date: pd.Timestamp) -> float | None:
    """Look up Series-C 30D CMI ATM IV on ``target_date`` from
    ``data/cache/iv/{SYMBOL}.parquet``. Returns annualised σ as a
    float, or None on miss. CONSTRAINT 1: this is the IV cache read
    — no BS computation."""
    try:
        df = load_iv_history(symbol)
    except FileNotFoundError:
        return None
    if df.empty or _IV_COLUMN not in df.columns:
        return None
    df = df.set_index("date")
    td = pd.to_datetime(target_date).normalize()
    if td not in df.index:
        return None
    v = df.loc[td, _IV_COLUMN]
    if pd.isna(v):
        return None
    return float(v)


def _fmt_inr(x: float) -> str:
    """Indian formatting: ₹ K / L / Cr / unit. Signed."""
    sign = "−" if x < 0 else ""
    a = abs(x)
    if a >= 1e7:
        return f"{sign}₹{a/1e7:.2f} Cr"
    if a >= 1e5:
        return f"{sign}₹{a/1e5:.2f} L"
    if a >= 1e3:
        return f"{sign}₹{a/1e3:.1f} K"
    return f"{sign}₹{a:.0f}"


def _render_stat_strip(row, symbol: str) -> None:
    cols = st.columns(6)

    # 1 · Net P&L
    net_pnl = float(row["net_pnl"])
    with cols[0]:
        st.metric(
            "Net P&L", _fmt_inr(net_pnl),
            delta=f"ROI {float(row['roi_pct']):+.2f}%",
            delta_color=("normal" if net_pnl >= 0 else "inverse"),
        )

    # 2 · Ann. ROI
    ann = float(row["roi_pct_annualized"])
    with cols[1]:
        st.metric(
            "Ann. ROI", f"{ann:+.0f}%",
            delta=f"on margin {_fmt_inr(float(row['margin_at_entry']))}",
            delta_color="off",
        )

    # 3 · Premium collected — observed entry credit (CONSTRAINT 1)
    credit = _net_credit_at_entry(row["legs_json"])
    with cols[2]:
        st.metric(
            "Premium collected", _fmt_inr(credit),
            delta="net credit at entry", delta_color="off",
        )

    # 4 · Underlying move
    entry_spot = float(row["entry_spot_close"])
    exit_spot = float(row["exit_spot_close"])
    move = (exit_spot - entry_spot) / entry_spot * 100.0
    with cols[3]:
        st.metric(
            "Underlying", f"{move:+.1f}%",
            delta=f"{entry_spot:.0f} → {exit_spot:.0f}",
            delta_color="off",
        )

    # 5 · IV in→out — Series C from iv_materializer cache
    entry_date = pd.to_datetime(row["entry_date"])
    exit_date = pd.to_datetime(row["exit_date"])
    iv_in = _iv_at_date(symbol, entry_date)
    iv_out = _iv_at_date(symbol, exit_date)
    if iv_in is not None and iv_out is not None:
        iv_label = f"{iv_in*100:.1f}% → {iv_out*100:.1f}%"
        delta_v = f"Δ {(iv_out - iv_in) * 100:+.1f} pts"
        delta_color = "inverse" if iv_out > iv_in else "normal"
    else:
        iv_label = "—"
        delta_v = "iv cache miss"
        delta_color = "off"
    with cols[4]:
        st.metric("IV in→out", iv_label, delta=delta_v, delta_color=delta_color)

    # 6 · IVP at entry — trailing-252-TD percentile of Series C
    try:
        ivp = compute_ivp(symbol, entry_date.date())
    except (FileNotFoundError, ValueError):
        ivp = None
    if ivp is None or pd.isna(ivp):
        ivp_label = "—"
        ivp_sub = "ivp cache miss"
    else:
        ivp_label = f"{ivp:.0f}th"
        ivp_sub = "vs own 252-TD history"
    with cols[5]:
        st.metric("IVP at entry", ivp_label, delta=ivp_sub, delta_color="off")


# ============================================================
# Position map — price-space chart (memoir §24.2 + §24.3 + §24.4 + §24.5)
# ============================================================

# Visual palette — matches the operator-validated mockup at
# DESIGN/Complete/components/inspect.jsx lines 418, 432-433 + 454-455.
# (We extract palette only; the mockup's bsPremium() synthetic-data
# math is NOT ported per CONSTRAINT 1.)
_COLOR_CALL = "#ffaa4d"   # warm orange — short call & upper BE
_COLOR_PUT = "#7cd6ff"    # cool blue   — short put  & lower BE
_COLOR_SPOT = "#1f2937"   # heavy neutral — spot path
_COLOR_PROFIT_ZONE = "rgba(46, 160, 67, 0.07)"
_COLOR_EVENT = "#f59e0b"  # amber — earnings / event markers


def _short_legs(legs_json_str: str):
    """Return (short_call_leg, short_put_leg) from legs_json or
    (None, None) if either is missing. Used by the position map to
    locate the two legs whose strikes anchor the chart."""
    legs = json.loads(legs_json_str)
    short_call = next(
        (l for l in legs
         if l.get("option_type") == "CE" and l.get("side") == "SELL"),
        None,
    )
    short_put = next(
        (l for l in legs
         if l.get("option_type") == "PE" and l.get("side") == "SELL"),
        None,
    )
    return short_call, short_put


def _per_share_credit(legs_json_str: str) -> float:
    """Net entry credit per share = sum of leg.entry_px_realized with
    side_sign(SELL)=+1, side_sign(BUY)=−1 across all legs. Anchors the
    static breakeven lines in the position map: upper_BE = K_call +
    credit, lower_BE = K_put − credit. Per memoir §24.2 the credit is
    locked at entry, so both BE lines are horizontal.

    Assumes both legs share the same lot_size + qty_lots (the
    strangle/straddle convention); the chart is a per-share view so
    qty/lot scaling cancels."""
    legs = json.loads(legs_json_str)
    total = 0.0
    for leg in legs:
        s = 1.0 if leg.get("side") == "SELL" else -1.0
        total += s * float(leg["entry_px_realized"])
    return total


@st.cache_data(show_spinner=False)
def _per_leg_observed_closes(
    symbol: str, expiry: pd.Timestamp, strike: float, option_type: str,
    entry_date, exit_date,
):
    """For each trading day t in [entry_date, exit_date], load the
    option contract's close via ``options_loader.load_option(...)`` and
    NaN-fill days that fail FILTERS.md Part A gates. Cached by the
    full 6-tuple per CONSTRAINT 9 so selector changes don't re-pay
    the parquet-loop cost.

    Returns ``(days, closes, gaps)``:
      days   — list of ``date`` objects from trading_calendar
      closes — list[float|NaN] aligned with days
      gaps   — list of (date, reason_str) for days that failed Part A;
               operator-facing annotation captions read from this

    Per memoir §24.5: per-leg gap handling. The OTHER leg's series
    continues normally on the same day; the static BE lines, spot
    path, and the legs table are not subject to per-leg gaps."""
    exp_date = pd.to_datetime(expiry).date()
    # Normalise dates to plain ``date`` so the @st.cache_data key is
    # consistent across Timestamp / date / str call shapes.
    entry_d = pd.to_datetime(entry_date).date()
    exit_d = pd.to_datetime(exit_date).date()
    days = trading_days(entry_d, exit_d)
    closes: list[float] = []
    gaps: list[tuple] = []
    for t in days:
        try:
            df = load_option(
                symbol, exp_date, strike, option_type, t, t,
            )
            if df.empty:
                closes.append(float("nan"))
                gaps.append((t, "FILTERS §A #6 missing row"))
            else:
                closes.append(float(df["close"].iloc[0]))
        except MissingTurnoverError:
            closes.append(float("nan"))
            gaps.append((t, "FILTERS §A #8 zero turnover"))
        except IlliquidLegError:
            closes.append(float("nan"))
            gaps.append((t, "FILTERS §A #10 oi=0 + thin trades"))
        except MissingDataError:
            closes.append(float("nan"))
            gaps.append((t, "FILTERS §A missing data"))
        except OfflineCacheMiss:
            closes.append(float("nan"))
            gaps.append((t, "OfflineCacheMiss"))
    return days, closes, gaps


@st.cache_data(show_spinner=False)
def _spot_path(symbol: str, entry_date, exit_date) -> pd.DataFrame:
    """Window-load spot via spot_loader. Cached at the Inspect layer
    per CONSTRAINT 9 (spot_loader is fast, but Streamlit's per-render
    fresh call still adds up across selector changes)."""
    return load_spot(symbol, entry_date, exit_date)


@st.cache_data(show_spinner=False)
def _earnings_events_in_window(
    symbol: str, entry_date, exit_date,
) -> pd.DataFrame:
    """Subset of events with PURPOSE containing Financial Results for
    ``symbol`` whose DATE falls in ``[entry_date, exit_date]``. Empty
    frame on cache miss — operator still sees the chart, just without
    event markers."""
    try:
        events = load_events()
    except FileNotFoundError:
        return pd.DataFrame(columns=["SYMBOL", "DATE"])
    if events.empty:
        return events
    mask = (
        (events["SYMBOL"] == symbol)
        & (events["DATE"] >= pd.Timestamp(entry_date))
        & (events["DATE"] <= pd.Timestamp(exit_date))
    )
    return events.loc[mask].copy()


def _build_position_map_figure(
    *,
    symbol: str,
    short_call: dict,
    short_put: dict,
    per_share_credit: float,
    spot_df: pd.DataFrame,
    call_days, call_closes,
    put_days, put_closes,
    events_df: pd.DataFrame,
) -> go.Figure:
    """Pure builder: assemble the position-map figure from already-
    fetched data. Separating the build from the Streamlit render
    surface lets tests verify the trace + shape + annotation structure
    directly without mocking ``st.plotly_chart``."""
    K_call = float(short_call["strike"])
    K_put = float(short_put["strike"])
    upper_be = K_call + per_share_credit
    lower_be = K_put - per_share_credit

    # K_call + observed_call_close[t] — the line decays toward K_call
    # as expiry approaches because the call premium shrinks. Per §24.3.
    call_line = [
        K_call + c if not pd.isna(c) else float("nan")
        for c in call_closes
    ]
    # K_put − observed_put_close[t] — mirror image; line rises toward
    # K_put as put premium shrinks.
    put_line = [
        K_put - p if not pd.isna(p) else float("nan")
        for p in put_closes
    ]

    fig = go.Figure()

    # Profit zone shading between BEs. Drawn FIRST so the lines render
    # on top.
    fig.add_hrect(
        y0=lower_be, y1=upper_be,
        fillcolor=_COLOR_PROFIT_ZONE, line_width=0,
        annotation_text="profit zone", annotation_position="top left",
        annotation=dict(font_size=10, font_color="#2ea043"),
    )

    # Spot path — heavy neutral.
    if not spot_df.empty:
        fig.add_trace(go.Scatter(
            x=spot_df["date"], y=spot_df["close"],
            mode="lines", name="spot",
            line=dict(color=_COLOR_SPOT, width=2.5),
        ))

    # Call-leg line (K_call + observed close), connectgaps=False so a
    # FILTERS Part A NaN breaks the trace cleanly per §24.5.
    fig.add_trace(go.Scatter(
        x=call_days, y=call_line, mode="lines",
        name="K_call + observed call close",
        line=dict(color=_COLOR_CALL, width=2),
        connectgaps=False,
    ))

    # Put-leg line.
    fig.add_trace(go.Scatter(
        x=put_days, y=put_line, mode="lines",
        name="K_put − observed put close",
        line=dict(color=_COLOR_PUT, width=2),
        connectgaps=False,
    ))

    # Static breakeven horizontals — locked at entry, no time variation.
    fig.add_hline(
        y=upper_be, line=dict(color=_COLOR_CALL, dash="dot", width=1.5),
        annotation_text=f"↑BE {upper_be:.0f}",
        annotation_position="right",
        annotation_font_color=_COLOR_CALL, annotation_font_size=11,
    )
    fig.add_hline(
        y=lower_be, line=dict(color=_COLOR_PUT, dash="dot", width=1.5),
        annotation_text=f"↓BE {lower_be:.0f}",
        annotation_position="right",
        annotation_font_color=_COLOR_PUT, annotation_font_size=11,
    )

    # Earnings event markers (Financial Results only — §17.5 filter).
    # Plotly's ``add_vline(annotation_text=...)`` codepath calls
    # ``_mean(x)`` on the line endpoints to position the annotation;
    # that path is broken for ``pd.Timestamp`` (TypeError in pandas
    # 3.x) AND for ISO-date strings (sum() can't add strings to 0).
    # Workaround: place the line via add_shape and the label via
    # add_annotation separately, so no midpoint math runs.
    for _, ev in events_df.iterrows():
        ev_date_iso = pd.Timestamp(ev["DATE"]).strftime("%Y-%m-%d")
        fig.add_shape(
            type="line", xref="x", yref="paper",
            x0=ev_date_iso, x1=ev_date_iso, y0=0, y1=1,
            line=dict(color=_COLOR_EVENT, dash="dot", width=1),
        )
        fig.add_annotation(
            x=ev_date_iso, xref="x", y=1.0, yref="paper",
            text="⚠ earnings", showarrow=False,
            font=dict(color=_COLOR_EVENT, size=10),
            yanchor="bottom",
        )

    fig.update_layout(
        title=f"Position map · {symbol}",
        xaxis_title="Trading day",
        yaxis_title="₹ per share",
        height=420,
        margin=dict(l=60, r=60, t=50, b=50),
        showlegend=True,
        legend=dict(orientation="h", y=-0.18),
    )

    return fig


def _render_position_map(row, strategy: str, symbol: str, expiry) -> None:
    """Render the position map per memoir §24.2 + §24.3 + §24.4 + §24.5.

    Iron condor: blocked-state card per §24.4 — a 4-leg structure has
    two breakeven pairs and would mislead on a single spot-vs-leg view.
    The P&L path and legs table in Phase 9.5.3 still render.

    Strangle / straddle: full position map. All series are OBSERVED
    (CONSTRAINT 1) — spot from spot_loader, leg closes from
    options_loader, BE lines from legs_json entry_px_realized. NO BS.
    """
    if strategy == "iron_condor":
        st.markdown(
            "⊘ **Can't inspect a condor here.** "
            "The position map plots one short call and one short put "
            "against spot. An iron condor has **4 legs** and **two** "
            "breakeven pairs — a single spot-vs-leg view would "
            "misrepresent it. The **P&L path** and **legs table** "
            "below still apply. "
            "*switch strategy → Strangle or Straddle to see the map*"
        )
        return

    short_call, short_put = _short_legs(row["legs_json"])
    if short_call is None or short_put is None:
        st.warning(
            "Position map requires both a short CE leg and a short PE "
            "leg in this trade; one or both are missing from legs_json."
        )
        return

    entry_date = pd.to_datetime(row["entry_date"]).date()
    exit_date = pd.to_datetime(row["exit_date"]).date()
    per_share_credit = _per_share_credit(row["legs_json"])

    # Per-leg gap-aware observed closes. Each call is cached per
    # (symbol, expiry, strike, type, entry_date, exit_date) — typical
    # 30-day window does 30 parquet reads on first render, O(1) on
    # selector changes.
    try:
        call_days, call_closes, call_gaps = _per_leg_observed_closes(
            symbol, expiry, float(short_call["strike"]), "CE",
            entry_date, exit_date,
        )
        put_days, put_closes, put_gaps = _per_leg_observed_closes(
            symbol, expiry, float(short_put["strike"]), "PE",
            entry_date, exit_date,
        )
    except Exception as e:  # noqa: BLE001 — surface raw failure
        st.error(
            f"Could not load observed leg closes for the position map: "
            f"{type(e).__name__}: {e}"
        )
        return

    spot_df = _spot_path(symbol, entry_date, exit_date)
    events_df = _earnings_events_in_window(symbol, entry_date, exit_date)

    fig = _build_position_map_figure(
        symbol=symbol,
        short_call=short_call, short_put=short_put,
        per_share_credit=per_share_credit,
        spot_df=spot_df,
        call_days=call_days, call_closes=call_closes,
        put_days=put_days, put_closes=put_closes,
        events_df=events_df,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Per-§24.5 gap annotations below the chart so the operator sees
    # data-quality breaks explicitly rather than mistaking the line gap
    # for a chart bug.
    if call_gaps:
        reasons = sorted({r for _, r in call_gaps})
        st.caption(
            f"Call leg: {len(call_gaps)} day(s) no observed premium "
            f"({'; '.join(reasons)})"
        )
    if put_gaps:
        reasons = sorted({r for _, r in put_gaps})
        st.caption(
            f"Put leg: {len(put_gaps)} day(s) no observed premium "
            f"({'; '.join(reasons)})"
        )


# ============================================================
# Footer caption (§24.1 + §9)
# ============================================================

def _render_footer() -> None:
    st.caption(
        "STT rationale pending web verification per §9 (current rate "
        "set conservatively at 0.15%). Premiums are observed from the "
        "contract cache, not reconstructed (§24.1)."
    )


# ============================================================
# Top-level entry point — invoked from app.py
# ============================================================

def render_inspect_tab(df: pd.DataFrame) -> None:
    """Render the Inspect tab body. ``df`` is the post-filter sweep
    DataFrame (same shape the other tab renderers receive).

    See PORTFOLIO_MEMOIR.md §24 for the full spec. This skeleton
    commit lands the selectors + URL routing + header + stat strip +
    footer. Position map (commit 2) and P&L path + legs table
    (commit 3) follow."""
    if df is None or df.empty:
        st.info(
            "No sweep rows after the current sidebar filters — adjust "
            "the filters to populate Inspect."
        )
        return

    _initialize_session_state(df)
    _render_selectors(df)

    strategy = st.session_state.get(_SS_STRATEGY)
    symbol = st.session_state.get(_SS_SYMBOL)
    expiry = st.session_state.get(_SS_EXPIRY)
    entry = st.session_state.get(_SS_ENTRY)
    exit_ = st.session_state.get(_SS_EXIT)
    if None in (strategy, symbol, expiry, entry, exit_):
        st.warning("Could not resolve a valid 5-tuple from the filtered sweep.")
        return

    row_match = df[
        (df["strategy"] == strategy)
        & (df["symbol"] == symbol)
        & (df["expiry"] == expiry)
        & (df["entry_offset_td"] == entry)
        & (df["exit_offset_td"] == exit_)
    ]
    if row_match.empty:
        st.error(
            f"No sweep row matches "
            f"({strategy}, {symbol}, {pd.to_datetime(expiry).date()}, "
            f"T-{entry}/T-{exit_}). The cascading snap should have "
            f"prevented this — please report."
        )
        return
    row = row_match.iloc[0]

    st.divider()
    _render_header(row, strategy, symbol, expiry, entry, exit_)
    st.divider()
    _render_stat_strip(row, symbol)
    st.divider()
    _render_position_map(row, strategy, symbol, expiry)
    st.divider()
    _render_footer()
