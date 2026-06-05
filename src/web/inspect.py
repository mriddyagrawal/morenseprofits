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
import streamlit as st

from src.analytics.ivp import compute_ivp
from src.data.iv_materializer import load_iv_history


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
    _render_footer()
