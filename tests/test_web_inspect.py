"""Tests for src/web/inspect.py — Phase 9.5 skeleton (memoir §24).

Coverage:
  - Cascading-validity snap on the 5-tuple selector contract (§24.8)
  - URL-param read-on-mount: full deeplink + partial-fallback (§24.9)
  - Default selection lands on a real sweep row (cascading defaults)
  - Stat-strip values round-trip from a fixture sweep row
  - IV in→out reads from the ``iv_materializer`` cache (NOT BS) by
    monkeypatching ``load_iv_history``
  - Reviewer-grep gate per CONSTRAINT 1: ZERO Black-Scholes call
    patterns anywhere in src/web/inspect.py OR this test file

See PORTFOLIO_MEMOIR.md §24 for the spec being tested.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest


REPO = Path(__file__).resolve().parent.parent


# ============================================================
# Fixture sweep — a tiny in-memory DataFrame with the shape the
# production sweep parquet exposes (subset of columns Inspect reads).
# ============================================================

def _leg(side="SELL", typ="CE", strike=2500.0, entry_px=18.0, exit_px=2.0,
         lot=300, qty=1) -> dict:
    return {
        "side": side, "option_type": typ, "strike": strike,
        "entry_px": entry_px, "entry_px_realized": entry_px,
        "exit_px": exit_px, "exit_px_realized": exit_px,
        "entry_volume": 100000, "exit_volume": 50000,
        "entry_oi": 200000, "exit_oi": 150000,
        "entry_turnover": 100.0, "exit_turnover": 50.0,
        "lot_size": lot, "qty_lots": qty,
        "gross_pnl": (entry_px - exit_px) * qty * lot,
    }


def _row(
    strategy="short_straddle", symbol="RELIANCE",
    expiry="2026-04-28", entry_date="2026-04-07", exit_date="2026-04-25",
    entry=15, exit_=3,
    net_pnl=4500.0, roi_pct=2.5, roi_pct_annualized=120.0,
    entry_spot=1400.0, exit_spot=1420.0,
    margin=180000.0, hold_td=12,
    legs=None,
) -> dict:
    legs = legs or [_leg("SELL", "CE", 1400.0, 30.0, 5.0),
                    _leg("SELL", "PE", 1400.0, 28.0, 2.0)]
    return {
        "run_id": "test_run",
        "strategy": strategy, "symbol": symbol,
        "expiry": pd.Timestamp(expiry),
        "entry_date": pd.Timestamp(entry_date),
        "exit_date": pd.Timestamp(exit_date),
        "entry_offset_td": entry, "exit_offset_td": exit_,
        "params_json": "{}",
        "legs_json": json.dumps(legs),
        "gross_pnl": net_pnl + 200.0,
        "costs": 200.0,
        "costs_breakdown_json": "{}",
        "net_pnl": net_pnl,
        "margin_at_entry": margin,
        "margin_breakdown_json": "{}",
        "roi_pct": roi_pct,
        "hold_trading_days": hold_td,
        "roi_pct_annualized": roi_pct_annualized,
        "entry_spot_vwap": entry_spot, "exit_spot_vwap": exit_spot,
        "entry_spot_close": entry_spot, "exit_spot_close": exit_spot,
        "notional_at_entry_vwap": entry_spot * 1000.0,
    }


@pytest.fixture
def fixture_sweep() -> pd.DataFrame:
    """3 strategies × 2 symbols × 2 expiries × 4 entry × 3 exit grid
    (subset, ensuring entry > exit always)."""
    rows = []
    for strat in ("short_straddle", "short_strangle", "iron_condor"):
        for sym in ("RELIANCE", "PNB"):
            for exp in ("2026-03-30", "2026-04-28"):
                for en in (5, 10, 15, 20):
                    for ex in (0, 3, 7):
                        if ex >= en:
                            continue
                        rows.append(_row(
                            strategy=strat, symbol=sym, expiry=exp,
                            entry=en, exit_=ex,
                            net_pnl=(en - ex) * 100.0,
                            roi_pct_annualized=10.0 * en,
                        ))
    return pd.DataFrame(rows)


# ============================================================
# Cascading-validity snap (memoir §24.8)
# ============================================================

def test_snap_picks_first_when_strategy_invalid(fixture_sweep):
    from src.web.inspect import _snap_to_valid
    out = _snap_to_valid(
        fixture_sweep, strategy="bogus", symbol="RELIANCE",
        expiry=pd.Timestamp("2026-04-28"), entry=15, exit_=3,
    )
    assert out is not None
    strat, sym, exp, en, ex = out
    # First sorted strategy is iron_condor (alphabetical).
    assert strat == "iron_condor"
    # All downstream snapped to valid combination.
    assert sym in fixture_sweep["symbol"].unique()
    assert ex < en


def test_snap_picks_most_recent_expiry_when_invalid(fixture_sweep):
    from src.web.inspect import _snap_to_valid
    out = _snap_to_valid(
        fixture_sweep, strategy="short_straddle", symbol="RELIANCE",
        expiry=pd.Timestamp("2099-01-01"), entry=15, exit_=3,
    )
    assert out is not None
    _, _, exp, _, _ = out
    # Most recent in the fixture is 2026-04-28.
    assert exp == pd.Timestamp("2026-04-28")


def test_snap_enforces_entry_gt_exit(fixture_sweep):
    """Per the sweep grid: exit < entry. If a proposed (entry, exit)
    violates this, the snap must repair it."""
    from src.web.inspect import _snap_to_valid
    out = _snap_to_valid(
        fixture_sweep, strategy="short_straddle", symbol="RELIANCE",
        expiry=pd.Timestamp("2026-04-28"), entry=3, exit_=7,
    )
    assert out is not None
    _, _, _, en, ex = out
    assert ex < en


def test_snap_returns_none_on_empty_df():
    from src.web.inspect import _snap_to_valid
    assert _snap_to_valid(pd.DataFrame()) is None


def test_default_tuple_lands_on_a_real_sweep_row(fixture_sweep):
    """Default-cascading 5-tuple must address an actual row in the
    sweep grid (replacement for the status=taken test removed in the
    builder-prompt pin since the sweep parquet has no status column —
    Phase 9.2 forward-dependency)."""
    from src.web.inspect import _snap_to_valid
    out = _snap_to_valid(fixture_sweep)
    assert out is not None
    strat, sym, exp, en, ex = out
    matches = fixture_sweep[
        (fixture_sweep["strategy"] == strat)
        & (fixture_sweep["symbol"] == sym)
        & (fixture_sweep["expiry"] == exp)
        & (fixture_sweep["entry_offset_td"] == en)
        & (fixture_sweep["exit_offset_td"] == ex)
    ]
    assert len(matches) == 1, (
        f"default tuple {(strat, sym, exp, en, ex)} doesn't map to "
        f"exactly one sweep row (got {len(matches)})"
    )


# ============================================================
# URL-param read (memoir §24.9)
# ============================================================

def _stub_query_params(monkeypatch, **params):
    """Patch st.query_params with a simple dict-like wrapper."""
    import src.web.inspect as ins
    monkeypatch.setattr(ins.st, "query_params", params)


def test_read_url_params_full_5_tuple(monkeypatch):
    from src.web.inspect import _read_url_params
    _stub_query_params(
        monkeypatch,
        strategy="short_strangle", symbol="RELIANCE",
        expiry="2026-04-28", entry_offset_td="15", exit_offset_td="3",
    )
    out = _read_url_params()
    assert out["strategy"] == "short_strangle"
    assert out["symbol"] == "RELIANCE"
    assert out["expiry"] == pd.Timestamp("2026-04-28")
    assert out["entry_offset_td"] == 15
    assert out["exit_offset_td"] == 3


def test_read_url_params_partial_missing_are_absent(monkeypatch):
    from src.web.inspect import _read_url_params
    _stub_query_params(monkeypatch, strategy="short_strangle", symbol="PNB")
    out = _read_url_params()
    assert out == {"strategy": "short_strangle", "symbol": "PNB"}


def test_read_url_params_drops_unparseable_int(monkeypatch):
    """Garbage entry_offset_td should NOT raise — it's just absent."""
    from src.web.inspect import _read_url_params
    _stub_query_params(monkeypatch, entry_offset_td="not_an_int")
    out = _read_url_params()
    assert "entry_offset_td" not in out


def test_read_url_params_drops_unparseable_date(monkeypatch):
    from src.web.inspect import _read_url_params
    _stub_query_params(monkeypatch, expiry="not-a-date")
    out = _read_url_params()
    assert "expiry" not in out


# ============================================================
# 7aef085 GRILL 1 regression — URL-precedence locks user clicks
# ============================================================

def test_user_click_overrides_deeplink_on_subsequent_render(
    fixture_sweep, monkeypatch,
):
    """Regression test for 7aef085 GRILL 1.

    The previous ``url.get(k) or session_state.get(k)`` pattern in
    ``_initialize_session_state`` made the URL always win on every
    render, clobbering the operator's selectbox clicks because
    ``st.query_params`` doesn't auto-clear after a deeplink load.

    Sequence:
      1. Deeplink URL: strategy=short_strangle.
      2. First call to ``_initialize_session_state`` seeds session
         state from URL → strategy = short_strangle.
      3. Operator clicks the strategy selectbox → Streamlit's widget
         binding writes session_state.strategy = short_straddle.
      4. Rerun → ``_initialize_session_state`` runs again.
      5. URL still has strategy=short_strangle (no auto-clear).
      6. With the fix (first-render-only seed) session_state stays
         short_straddle. Without the fix, it gets clobbered.
    """
    import src.web.inspect as ins

    fake_ss: dict = {}
    monkeypatch.setattr(ins.st, "session_state", fake_ss)
    _stub_query_params(
        monkeypatch,
        strategy="short_strangle", symbol="RELIANCE",
    )

    # First render: URL seeds session state.
    ins._initialize_session_state(fixture_sweep)
    assert fake_ss[ins._SS_STRATEGY] == "short_strangle"

    # Operator click: widget binding writes new value to session state.
    # (URL stays at short_strangle — Streamlit doesn't auto-clear it.)
    fake_ss[ins._SS_STRATEGY] = "short_straddle"

    # Rerun: _initialize_session_state runs again. With first-render-
    # only guard, URL is ignored and the operator's click stands.
    ins._initialize_session_state(fixture_sweep)
    assert fake_ss[ins._SS_STRATEGY] == "short_straddle", (
        "operator's selectbox click was clobbered by stale URL param "
        "on the second render — 7aef085 GRILL 1 regression"
    )


def test_clear_inspect_state_drops_private_keys_only(monkeypatch):
    """``clear_inspect_state()`` is the public helper for deeplink
    writers per §24.9. It must remove all 5 private inspect keys, and
    must NOT touch unrelated session-state keys."""
    import src.web.inspect as ins

    fake_ss: dict = {
        ins._SS_STRATEGY: "short_strangle",
        ins._SS_SYMBOL: "RELIANCE",
        ins._SS_EXPIRY: pd.Timestamp("2026-04-28"),
        ins._SS_ENTRY: 15,
        ins._SS_EXIT: 3,
        # Unrelated keys that MUST NOT be cleared.
        "mp_active_tab": "Inspect",
        "mp_selected_sweep": "test_sweep.parquet",
        "_unrelated_user_key": "preserved",
    }
    monkeypatch.setattr(ins.st, "session_state", fake_ss)
    ins.clear_inspect_state()
    for k in ins._PRIVATE_SS_KEYS:
        assert k not in fake_ss, f"{k!r} should have been cleared"
    assert fake_ss["mp_active_tab"] == "Inspect"
    assert fake_ss["mp_selected_sweep"] == "test_sweep.parquet"
    assert fake_ss["_unrelated_user_key"] == "preserved"


# ============================================================
# Position map (Commit 2 — memoir §24.2 + §24.3 + §24.4 + §24.5)
# ============================================================

def _spot_window_df(start, end) -> pd.DataFrame:
    """Tiny date-close frame for spot-path tests."""
    dates = pd.date_range(start, end, freq="B")
    return pd.DataFrame({
        "date": dates,
        "close": [1400.0 + i * 5 for i in range(len(dates))],
    })


def _build_strangle_row(
    symbol="RELIANCE", expiry="2026-04-28",
    entry_date="2026-04-07", exit_date="2026-04-25",
    K_call=1450.0, K_put=1350.0, ce_credit=25.0, pe_credit=20.0,
) -> dict:
    return _row(
        strategy="short_strangle", symbol=symbol, expiry=expiry,
        entry_date=entry_date, exit_date=exit_date,
        entry=15, exit_=3,
        legs=[
            _leg("SELL", "CE", K_call, ce_credit, 5.0),
            _leg("SELL", "PE", K_put, pe_credit, 4.0),
        ],
    )


def test_per_share_credit_is_signed_sum_of_realized_entry_pxs():
    """Net per-share credit anchors the static BE lines. SELL legs add
    credit; BUY legs subtract (memoir §24.2)."""
    from src.web.inspect import _per_share_credit
    row = _row(legs=[
        _leg("SELL", "CE", 1450.0, 25.0, 5.0),
        _leg("SELL", "PE", 1350.0, 20.0, 4.0),
        _leg("BUY",  "CE", 1500.0, 8.0,  1.0),
    ])
    # 25 + 20 - 8 = 37
    assert _per_share_credit(row["legs_json"]) == pytest.approx(37.0)


def test_short_legs_extracts_short_ce_and_short_pe():
    from src.web.inspect import _short_legs
    row = _row(legs=[
        _leg("SELL", "CE", 1450.0, 25.0, 5.0),
        _leg("SELL", "PE", 1350.0, 20.0, 4.0),
    ])
    sc, sp = _short_legs(row["legs_json"])
    assert sc is not None and sc["option_type"] == "CE" and sc["side"] == "SELL"
    assert sp is not None and sp["option_type"] == "PE" and sp["side"] == "SELL"
    assert float(sc["strike"]) == 1450.0
    assert float(sp["strike"]) == 1350.0


def test_short_legs_returns_none_when_no_short_call():
    from src.web.inspect import _short_legs
    # Only short put + long call → no short call.
    row = _row(legs=[
        _leg("BUY",  "CE", 1500.0, 8.0,  1.0),
        _leg("SELL", "PE", 1350.0, 20.0, 4.0),
    ])
    sc, sp = _short_legs(row["legs_json"])
    assert sc is None and sp is not None


def test_position_map_iron_condor_renders_blocked_card(
    monkeypatch, fixture_sweep,
):
    """§24.4: iron condor's 4-leg / 2-BE-pair structure makes a single
    spot-vs-leg chart misleading. The position map slot must render a
    blocked-state card; no Plotly chart is added."""
    import src.web.inspect as ins
    captured_markdown: list[str] = []
    chart_calls: list[object] = []
    monkeypatch.setattr(
        ins.st, "markdown", lambda body, **k: captured_markdown.append(body),
    )
    monkeypatch.setattr(
        ins.st, "plotly_chart",
        lambda fig, **k: chart_calls.append(fig),
    )
    row = fixture_sweep[
        fixture_sweep["strategy"] == "iron_condor"
    ].iloc[0]
    ins._render_position_map(
        row, "iron_condor", row["symbol"], row["expiry"],
    )
    assert any("condor" in m.lower() for m in captured_markdown), (
        "iron condor blocked-state card did not render"
    )
    assert chart_calls == [], (
        "iron condor must NOT render a position map chart"
    )


def test_position_map_warns_when_no_short_legs(monkeypatch):
    """When legs_json lacks a short CE / short PE pair (e.g. a long-vol
    structure), the position map must warn rather than crash."""
    import src.web.inspect as ins
    warnings: list[str] = []
    chart_calls: list[object] = []
    monkeypatch.setattr(ins.st, "warning", lambda m, **k: warnings.append(m))
    monkeypatch.setattr(
        ins.st, "plotly_chart", lambda fig, **k: chart_calls.append(fig),
    )
    row = _row(legs=[
        _leg("BUY", "CE", 1500.0, 8.0, 1.0),
        _leg("BUY", "PE", 1300.0, 6.0, 1.0),
    ])
    ins._render_position_map(
        row, "long_strangle", row["symbol"], row["expiry"],
    )
    assert any("short CE" in w and "short PE" in w for w in warnings)
    assert chart_calls == []


# ============================================================
# _build_position_map_figure — pure builder verifies trace structure
# ============================================================

def test_build_position_map_figure_has_spot_call_put_traces():
    from src.web.inspect import _build_position_map_figure
    K_call, K_put, credit = 1450.0, 1350.0, 45.0
    sc = _leg("SELL", "CE", K_call, 25.0, 5.0)
    sp = _leg("SELL", "PE", K_put, 20.0, 4.0)
    spot = _spot_window_df("2026-04-07", "2026-04-15")
    cdays = list(spot["date"].dt.date)
    fig = _build_position_map_figure(
        symbol="RELIANCE",
        short_call=sc, short_put=sp,
        per_share_credit=credit,
        spot_df=spot,
        call_days=cdays, call_closes=[20.0, 18.0, 15.0, 13.0, 11.0, 9.0, 7.0],
        put_days=cdays, put_closes=[18.0, 17.0, 14.0, 12.0, 10.0, 8.0, 6.0],
        events_df=pd.DataFrame(columns=["SYMBOL", "DATE"]),
    )
    names = [t.name for t in fig.data]
    assert "spot" in names
    assert any("call" in n.lower() for n in names), names
    assert any("put" in n.lower() for n in names), names


def test_build_position_map_figure_static_BEs_are_horizontal():
    """§24.2: BE lines are LOCKED AT ENTRY — drawn as horizontals
    (y0 == y1, single y-value)."""
    from src.web.inspect import _build_position_map_figure
    K_call, K_put, credit = 1450.0, 1350.0, 45.0
    sc = _leg("SELL", "CE", K_call, 25.0, 5.0)
    sp = _leg("SELL", "PE", K_put, 20.0, 4.0)
    spot = _spot_window_df("2026-04-07", "2026-04-09")
    days = list(spot["date"].dt.date)
    fig = _build_position_map_figure(
        symbol="RELIANCE",
        short_call=sc, short_put=sp,
        per_share_credit=credit,
        spot_df=spot,
        call_days=days, call_closes=[20.0, 18.0, 15.0],
        put_days=days, put_closes=[18.0, 17.0, 14.0],
        events_df=pd.DataFrame(columns=["SYMBOL", "DATE"]),
    )
    # add_hline + add_hrect both create entries in fig.layout.shapes.
    # Match by y0==y1 to find the BE lines.
    horizontals = [
        s for s in fig.layout.shapes
        if getattr(s, "y0", None) is not None
        and getattr(s, "y1", None) is not None
        and s.y0 == s.y1
    ]
    assert len(horizontals) >= 2, (
        f"expected at least 2 horizontal BE lines; got {len(horizontals)}"
    )
    ys = sorted({float(s.y0) for s in horizontals})
    assert K_call + credit in ys, f"upper BE missing; ys={ys}"
    assert K_put - credit in ys, f"lower BE missing; ys={ys}"


def test_build_position_map_figure_profit_zone_between_BEs():
    """The profit zone is the rectangle between upper and lower BE.
    add_hrect produces a shape with y0=lower_BE, y1=upper_BE (or
    vice-versa) — the y-extent must match the BE spread."""
    from src.web.inspect import _build_position_map_figure
    K_call, K_put, credit = 1450.0, 1350.0, 45.0
    spot = _spot_window_df("2026-04-07", "2026-04-09")
    days = list(spot["date"].dt.date)
    fig = _build_position_map_figure(
        symbol="RELIANCE",
        short_call=_leg("SELL", "CE", K_call, 25.0, 5.0),
        short_put=_leg("SELL", "PE", K_put, 20.0, 4.0),
        per_share_credit=credit,
        spot_df=spot,
        call_days=days, call_closes=[20.0, 18.0, 15.0],
        put_days=days, put_closes=[18.0, 17.0, 14.0],
        events_df=pd.DataFrame(columns=["SYMBOL", "DATE"]),
    )
    # Find a shape whose y-extent equals the BE spread (the profit-zone
    # hrect). add_hrect produces a shape spanning the full x-range.
    upper_be, lower_be = K_call + credit, K_put - credit
    rects = [
        s for s in fig.layout.shapes
        if (
            getattr(s, "y0", None) is not None
            and getattr(s, "y1", None) is not None
            and {float(s.y0), float(s.y1)} == {upper_be, lower_be}
        )
    ]
    assert len(rects) == 1, (
        f"expected one profit-zone rect spanning [{lower_be}, {upper_be}]; "
        f"got {len(rects)}"
    )


def test_build_position_map_figure_leg_lines_NaN_propagates():
    """A NaN in the leg-closes input must produce NaN in the trace's y
    so connectgaps=False makes the line break visibly (memoir §24.5).
    """
    from src.web.inspect import _build_position_map_figure
    spot = _spot_window_df("2026-04-07", "2026-04-09")
    days = list(spot["date"].dt.date)
    fig = _build_position_map_figure(
        symbol="RELIANCE",
        short_call=_leg("SELL", "CE", 1450.0, 25.0, 5.0),
        short_put=_leg("SELL", "PE", 1350.0, 20.0, 4.0),
        per_share_credit=45.0,
        spot_df=spot,
        call_days=days, call_closes=[20.0, float("nan"), 15.0],
        put_days=days, put_closes=[18.0, 17.0, float("nan")],
        events_df=pd.DataFrame(columns=["SYMBOL", "DATE"]),
    )
    call_trace = next(t for t in fig.data if "call" in (t.name or "").lower())
    put_trace = next(t for t in fig.data if "put" in (t.name or "").lower())
    assert call_trace.connectgaps is False, (
        "call trace MUST set connectgaps=False so the FILTERS §A gap "
        "renders as a visible break per memoir §24.5"
    )
    assert put_trace.connectgaps is False
    # NaN entries propagate to the y values.
    import math
    assert any(math.isnan(y) for y in call_trace.y)
    assert any(math.isnan(y) for y in put_trace.y)


def test_build_position_map_figure_event_markers_at_event_dates():
    """Earnings event in window adds a vertical line at the event date."""
    from src.web.inspect import _build_position_map_figure
    spot = _spot_window_df("2026-04-07", "2026-04-15")
    days = list(spot["date"].dt.date)
    events = pd.DataFrame({
        "SYMBOL": ["RELIANCE"],
        "DATE": [pd.Timestamp("2026-04-10")],
        "PURPOSE": ["Financial Results"],
    })
    fig = _build_position_map_figure(
        symbol="RELIANCE",
        short_call=_leg("SELL", "CE", 1450.0, 25.0, 5.0),
        short_put=_leg("SELL", "PE", 1350.0, 20.0, 4.0),
        per_share_credit=45.0,
        spot_df=spot,
        call_days=days, call_closes=[20.0] * len(days),
        put_days=days, put_closes=[18.0] * len(days),
        events_df=events,
    )
    # add_vline creates a shape with x0 == x1 at the event date.
    verticals = [
        s for s in fig.layout.shapes
        if getattr(s, "x0", None) is not None
        and getattr(s, "x1", None) is not None
        and s.x0 == s.x1
    ]
    assert len(verticals) >= 1, "expected at least 1 vertical event marker"


# ============================================================
# Per-leg gap handling — full _render_position_map round-trip
# ============================================================

def test_render_position_map_caption_reports_gap_count(monkeypatch):
    """When the per-leg-closes helper returns gap rows, the render
    function must surface them as a caption below the chart so the
    operator sees data-quality breaks explicitly (memoir §24.5)."""
    import src.web.inspect as ins

    # Make the per-leg helper return one synthetic gap on day 2 of 3.
    sample_days = [
        date(2026, 4, 7), date(2026, 4, 8), date(2026, 4, 9),
    ]
    def fake_per_leg(symbol, expiry, strike, option_type, entry_d, exit_d):
        # 1 NaN in the middle, simulating a FILTERS §A #8 zero-turnover day.
        return (
            sample_days,
            [20.0, float("nan"), 15.0],
            [(sample_days[1], "FILTERS §A #8 zero turnover")],
        )
    monkeypatch.setattr(ins, "_per_leg_observed_closes", fake_per_leg)
    monkeypatch.setattr(
        ins, "_spot_path",
        lambda symbol, e, x: _spot_window_df("2026-04-07", "2026-04-09"),
    )
    monkeypatch.setattr(
        ins, "_earnings_events_in_window",
        lambda symbol, e, x: pd.DataFrame(columns=["SYMBOL", "DATE"]),
    )

    captions: list[str] = []
    monkeypatch.setattr(ins.st, "caption", lambda m, **k: captions.append(m))
    monkeypatch.setattr(ins.st, "plotly_chart", lambda *a, **k: None)

    row = _build_strangle_row()
    ins._render_position_map(
        row, "short_strangle", "RELIANCE", row["expiry"],
    )
    # One gap each on call AND put legs → 2 captions.
    call_caps = [c for c in captions if "Call leg" in c]
    put_caps = [c for c in captions if "Put leg" in c]
    assert len(call_caps) == 1, f"expected one Call leg gap caption; got {call_caps}"
    assert len(put_caps) == 1, f"expected one Put leg gap caption; got {put_caps}"
    assert "zero turnover" in call_caps[0]
    assert "zero turnover" in put_caps[0]


# ============================================================
# Cumulative P&L path + legs table (Commit 3 — memoir §24.2 + §3a)
# ============================================================

def test_cumulative_pnl_path_sell_leg_profits_when_price_drops():
    """§3a sign convention: SELL leg P&L = (entry − obs) × +1 × qty × lot.
    Profit when obs drops below entry."""
    from src.web.inspect import _cumulative_pnl_path
    legs = [_leg("SELL", "CE", 1450.0, entry_px=25.0, lot=500, qty=1)]
    days = [date(2026, 4, 7), date(2026, 4, 8), date(2026, 4, 9)]
    # Price drops from 20 → 15 → 5 over the window (decay).
    closes = [[20.0, 15.0, 5.0]]
    out = _cumulative_pnl_path(legs, days, closes)
    # Day 1: (25 − 20) × +1 × 1 × 500 =  +2500
    # Day 2: (25 − 15) × +1 × 1 × 500 =  +5000
    # Day 3: (25 − 5)  × +1 × 1 × 500 = +10000
    assert out == [pytest.approx(2500.0), pytest.approx(5000.0), pytest.approx(10000.0)]


def test_cumulative_pnl_path_buy_leg_profits_when_price_rises():
    """§3a sign convention: BUY leg P&L = (entry − obs) × −1 × qty × lot
    = (obs − entry) × qty × lot. Profit when obs rises above entry."""
    from src.web.inspect import _cumulative_pnl_path
    legs = [_leg("BUY", "CE", 1500.0, entry_px=8.0, lot=500, qty=1)]
    days = [date(2026, 4, 7), date(2026, 4, 8)]
    # Price rises 8 → 12 → 20 (good for long call).
    closes = [[12.0, 20.0]]
    out = _cumulative_pnl_path(legs, days, closes)
    # Day 1: (8 − 12) × −1 × 1 × 500 = +2000
    # Day 2: (8 − 20) × −1 × 1 × 500 = +6000
    assert out == [pytest.approx(2000.0), pytest.approx(6000.0)]


def test_cumulative_pnl_path_force_endpoint_clamps_last_value():
    """Force-endpoint = row.net_pnl makes the final point match the
    sweep row's authoritative net figure even though intermediate days
    sum to gross. Operator sees endpoint snap = costs absorbed at exit."""
    from src.web.inspect import _cumulative_pnl_path
    legs = [_leg("SELL", "CE", 1450.0, entry_px=25.0, lot=500, qty=1)]
    days = [date(2026, 4, 7), date(2026, 4, 8)]
    closes = [[20.0, 5.0]]
    # Gross final = (25 − 5) × 500 = 10000; net (after costs of 200) = 9800.
    out = _cumulative_pnl_path(legs, days, closes, force_endpoint=9800.0)
    assert out[-1] == pytest.approx(9800.0)
    # Intermediate point unchanged.
    assert out[0] == pytest.approx(2500.0)


def test_cumulative_pnl_path_gap_day_carries_forward_per_leg():
    """When one leg gaps (NaN close) for a day, the path holds that
    leg's previous value; the OTHER leg's contribution still updates."""
    from src.web.inspect import _cumulative_pnl_path
    legs = [
        _leg("SELL", "CE", 1450.0, entry_px=25.0, lot=500, qty=1),
        _leg("SELL", "PE", 1350.0, entry_px=20.0, lot=500, qty=1),
    ]
    days = [date(2026, 4, 7), date(2026, 4, 8), date(2026, 4, 9)]
    # CE closes 20 → NaN → 5. PE closes 15 → 10 → 5.
    closes = [
        [20.0, float("nan"), 5.0],
        [15.0, 10.0, 5.0],
    ]
    out = _cumulative_pnl_path(legs, days, closes)
    # Day 1: CE (25-20)·500=2500; PE (20-15)·500=2500 → 5000
    # Day 2: CE carries 2500; PE (20-10)·500=5000 → 7500
    # Day 3: CE (25-5)·500=10000; PE (20-5)·500=7500 → 17500
    assert out[0] == pytest.approx(5000.0)
    assert out[1] == pytest.approx(7500.0)
    assert out[2] == pytest.approx(17500.0)


def test_cumulative_pnl_path_empty_window_returns_empty():
    from src.web.inspect import _cumulative_pnl_path
    assert _cumulative_pnl_path([_leg()], [], [[]]) == []


# ============================================================
# Pure builder verification — _build_pnl_path_figure
# ============================================================

def test_build_pnl_path_figure_has_zero_baseline_and_endpoint_marker():
    from src.web.inspect import _build_pnl_path_figure
    days = pd.date_range("2026-04-07", "2026-04-15", freq="B").date.tolist()
    cumulative = [0.0, 1000.0, 2500.0, 4500.0, 7000.0, 9500.0, 12000.0]
    fig = _build_pnl_path_figure(
        symbol="RELIANCE", days=days, cumulative=cumulative,
        net_pnl=11800.0, events_df=pd.DataFrame(columns=["SYMBOL", "DATE"]),
    )
    # Endpoint trace exists with x = last day, y = net_pnl.
    endpoint_traces = [
        t for t in fig.data
        if (t.mode or "").endswith("text")
    ]
    assert len(endpoint_traces) == 1
    et = endpoint_traces[0]
    assert list(et.x) == [days[-1]]
    assert list(et.y) == [11800.0]


def test_build_pnl_path_figure_color_matches_sign_of_net_pnl():
    from src.web.inspect import (
        _build_pnl_path_figure, _COLOR_PNL_POS, _COLOR_PNL_NEG,
    )
    days = pd.date_range("2026-04-07", "2026-04-09", freq="B").date.tolist()
    # Winning trade — main trace is green.
    fig_pos = _build_pnl_path_figure(
        symbol="RELIANCE", days=days, cumulative=[0.0, 500.0, 1200.0],
        net_pnl=1200.0, events_df=pd.DataFrame(columns=["SYMBOL", "DATE"]),
    )
    main_trace = next(t for t in fig_pos.data if (t.mode or "") == "lines")
    assert main_trace.line.color == _COLOR_PNL_POS

    # Losing trade — main trace is red.
    fig_neg = _build_pnl_path_figure(
        symbol="PNB", days=days, cumulative=[0.0, -200.0, -1500.0],
        net_pnl=-1500.0, events_df=pd.DataFrame(columns=["SYMBOL", "DATE"]),
    )
    main_trace_neg = next(t for t in fig_neg.data if (t.mode or "") == "lines")
    assert main_trace_neg.line.color == _COLOR_PNL_NEG


def test_build_pnl_path_figure_event_marker_at_event_date():
    from src.web.inspect import _build_pnl_path_figure
    days = pd.date_range("2026-04-07", "2026-04-15", freq="B").date.tolist()
    events = pd.DataFrame({
        "SYMBOL": ["RELIANCE"],
        "DATE": [pd.Timestamp("2026-04-10")],
        "PURPOSE": ["Financial Results"],
    })
    fig = _build_pnl_path_figure(
        symbol="RELIANCE", days=days, cumulative=[100.0] * 7,
        net_pnl=100.0, events_df=events,
    )
    verticals = [
        s for s in fig.layout.shapes
        if getattr(s, "x0", None) == getattr(s, "x1", None) is not None
    ]
    assert any(verticals), "expected at least 1 vertical event marker"


# ============================================================
# _render_pnl_path round-trip: endpoint matches net_pnl
# ============================================================

def test_render_pnl_path_endpoint_matches_sweep_net_pnl(monkeypatch):
    """The §24.2 contract: chart endpoint = sweep row's net_pnl. The
    intermediate days reflect cumulative gross-P&L from observed leg
    closes; the endpoint snaps to the authoritative figure (which
    absorbs the row's costs)."""
    import src.web.inspect as ins
    chart_calls: list[object] = []
    monkeypatch.setattr(
        ins.st, "plotly_chart", lambda fig, **k: chart_calls.append(fig),
    )
    monkeypatch.setattr(ins.st, "caption", lambda *a, **k: None)
    sample_days = [
        date(2026, 4, 7), date(2026, 4, 8), date(2026, 4, 9),
    ]
    monkeypatch.setattr(
        ins, "_per_leg_observed_closes",
        lambda symbol, expiry, strike, opt_type, e, x: (
            sample_days, [20.0, 15.0, 5.0], [],
        ),
    )
    monkeypatch.setattr(
        ins, "_earnings_events_in_window",
        lambda symbol, e, x: pd.DataFrame(columns=["SYMBOL", "DATE"]),
    )
    row = _build_strangle_row()
    ins._render_pnl_path(row, "RELIANCE", row["expiry"])
    assert len(chart_calls) == 1
    fig = chart_calls[0]
    # Endpoint trace has y[0] == row["net_pnl"]
    endpoint_traces = [
        t for t in fig.data if (t.mode or "").endswith("text")
    ]
    assert len(endpoint_traces) == 1
    assert list(endpoint_traces[0].y) == [float(row["net_pnl"])]


def test_render_pnl_path_iron_condor_renders_chart(monkeypatch):
    """§24.4: iron condor SUPPRESSES the position map but NOT the P&L
    path or legs table. The P&L path must render for iron_condor too."""
    import src.web.inspect as ins
    chart_calls: list[object] = []
    monkeypatch.setattr(
        ins.st, "plotly_chart", lambda fig, **k: chart_calls.append(fig),
    )
    monkeypatch.setattr(ins.st, "caption", lambda *a, **k: None)
    sample_days = [date(2026, 4, 7), date(2026, 4, 8)]
    monkeypatch.setattr(
        ins, "_per_leg_observed_closes",
        lambda symbol, expiry, strike, opt_type, e, x: (
            sample_days, [10.0, 5.0], [],
        ),
    )
    monkeypatch.setattr(
        ins, "_earnings_events_in_window",
        lambda symbol, e, x: pd.DataFrame(columns=["SYMBOL", "DATE"]),
    )
    # 4-leg iron-condor-shaped row.
    row = _row(
        strategy="iron_condor",
        legs=[
            _leg("SELL", "CE", 1450.0, 25.0, 5.0),
            _leg("BUY",  "CE", 1500.0, 8.0,  1.0),
            _leg("SELL", "PE", 1350.0, 20.0, 4.0),
            _leg("BUY",  "PE", 1300.0, 5.0,  1.0),
        ],
    )
    ins._render_pnl_path(row, "RELIANCE", row["expiry"])
    assert len(chart_calls) == 1, (
        "iron condor MUST render the cumulative P&L path; only the "
        "position map is suppressed per memoir §24.4"
    )


# ============================================================
# Legs table — total row + premium signs
# ============================================================

def test_render_legs_table_total_row_leg_pnl_matches_net_pnl(monkeypatch):
    """§24.2: legs-table total row's leg-P&L column shows the trade's
    authoritative net_pnl (not the sum of per-leg gross_pnl — those
    differ by row.costs)."""
    import src.web.inspect as ins
    captured_df: list = []
    monkeypatch.setattr(
        ins.st, "dataframe", lambda df, **k: captured_df.append(df),
    )
    monkeypatch.setattr(ins.st, "caption", lambda *a, **k: None)
    row = _build_strangle_row()
    ins._render_legs_table(row)
    assert len(captured_df) == 1
    df = captured_df[0]
    # Last row is the "net" total.
    last = df.iloc[-1]
    assert last["side"] == "net"
    assert last["leg P&L (₹)"] == pytest.approx(float(row["net_pnl"]))


def test_render_legs_table_premium_total_signed_sum_per_share(monkeypatch):
    """The total-row premium column shows the signed net credit per
    share (SELL=+, BUY=−). For a short strangle with C=25 + P=20 → 45."""
    import src.web.inspect as ins
    captured_df: list = []
    monkeypatch.setattr(
        ins.st, "dataframe", lambda df, **k: captured_df.append(df),
    )
    monkeypatch.setattr(ins.st, "caption", lambda *a, **k: None)
    row = _build_strangle_row(ce_credit=25.0, pe_credit=20.0)
    ins._render_legs_table(row)
    df = captured_df[0]
    last = df.iloc[-1]
    assert last["premium (entry, ₹/share)"] == pytest.approx(45.0)


# ============================================================
# Existing tests resume below
# ============================================================

def test_clear_then_seed_picks_up_new_url(fixture_sweep, monkeypatch):
    """End-to-end for the deeplink-rewrite flow Phase 9.4 will use:
    a fresh URL + ``clear_inspect_state()`` + re-call seed → new URL
    wins. Closes the question "how do future deeplink writers force
    Inspect to re-read the URL?" raised by the first-render-only guard.
    """
    import src.web.inspect as ins

    fake_ss: dict = {}
    monkeypatch.setattr(ins.st, "session_state", fake_ss)

    # First deeplink: strategy=short_strangle.
    _stub_query_params(monkeypatch, strategy="short_strangle")
    ins._initialize_session_state(fixture_sweep)
    assert fake_ss[ins._SS_STRATEGY] == "short_strangle"

    # Second deeplink (simulated by Portfolio): writes new URL +
    # clears Inspect state + reruns.
    _stub_query_params(monkeypatch, strategy="short_straddle")
    ins.clear_inspect_state()
    ins._initialize_session_state(fixture_sweep)
    assert fake_ss[ins._SS_STRATEGY] == "short_straddle"


# ============================================================
# Stat strip — values round-trip from a known sweep row
# ============================================================

def test_net_credit_at_entry_signs_and_sums():
    """SELL legs add credit, BUY legs subtract — per CONSTRAINT 1's
    'observed entry premium' contract sourced from legs_json."""
    from src.web.inspect import _net_credit_at_entry
    row = _row(legs=[
        _leg("SELL", "CE", 1400.0, 30.0, 5.0, lot=300, qty=1),  # +9000
        _leg("BUY",  "CE", 1500.0, 10.0, 1.0, lot=300, qty=1),  # -3000
    ])
    credit = _net_credit_at_entry(row["legs_json"])
    assert credit == pytest.approx(30.0 * 300 - 10.0 * 300, abs=1e-6)


def test_fmt_inr_lakhs_crores():
    from src.web.inspect import _fmt_inr
    assert "Cr" in _fmt_inr(1.5e7)
    assert "L" in _fmt_inr(2.4e5)
    assert "K" in _fmt_inr(4500.0)
    assert _fmt_inr(-2.5e5).startswith("−")  # using minus glyph


# ============================================================
# IV in→out reads from cache, NEVER from BS (CONSTRAINT 1)
# ============================================================

def test_iv_at_date_reads_from_iv_materializer_cache(monkeypatch):
    """Stub ``load_iv_history`` to return a controlled DataFrame and
    verify ``_iv_at_date`` returns the cached value verbatim. The
    point: the read path goes through ``iv_materializer.load_iv_history``
    (which loaded a parquet built upstream by ``engine.iv`` BS work),
    NOT through any BS computation inside this module."""
    import src.web.inspect as ins
    fake_history = pd.DataFrame({
        "date": [pd.Timestamp("2026-04-07"), pd.Timestamp("2026-04-25")],
        ins._IV_COLUMN: [0.215, 0.182],
    })
    monkeypatch.setattr(ins, "load_iv_history", lambda symbol: fake_history)
    iv_in = ins._iv_at_date("RELIANCE", pd.Timestamp("2026-04-07"))
    iv_out = ins._iv_at_date("RELIANCE", pd.Timestamp("2026-04-25"))
    assert iv_in == pytest.approx(0.215)
    assert iv_out == pytest.approx(0.182)


def test_iv_at_date_returns_none_on_cache_miss(monkeypatch):
    import src.web.inspect as ins
    def _raise(symbol):
        raise FileNotFoundError(f"no IV cache for {symbol}")
    monkeypatch.setattr(ins, "load_iv_history", _raise)
    assert ins._iv_at_date("BOGUS", pd.Timestamp("2026-04-07")) is None


def test_iv_at_date_returns_none_when_date_absent(monkeypatch):
    import src.web.inspect as ins
    history = pd.DataFrame({
        "date": [pd.Timestamp("2026-04-07")],
        ins._IV_COLUMN: [0.21],
    })
    monkeypatch.setattr(ins, "load_iv_history", lambda symbol: history)
    assert ins._iv_at_date("RELIANCE", pd.Timestamp("2025-01-01")) is None


# ============================================================
# Reviewer-grep gate (CONSTRAINT 1 + cross-cutting #9 in prompt)
# ============================================================
#
# This is the load-bearing constraint of the whole Inspect cluster:
# the Inspect-side hot path computes ZERO Black-Scholes prices. All
# BS work belongs upstream in src/engine/iv.py; Inspect reads the
# materialized cache only. The gate also applies to this test file —
# we must verify the IV cache read by stubbing load_iv_history, NOT
# by re-computing IV via BS as a ground-truth oracle.

_BS_REJECT_PATTERNS = [
    r"\bbs76\b",
    r"\bbs_premium\b",
    r"\bblack_scholes\b",
    r"\bimplied_vol\b",
]


def _content_of(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_no_bs_calls_in_inspect_module():
    """CONSTRAINT 1: src/web/inspect.py must contain ZERO BS call
    patterns. A reviewer that grep-rejects this file finds nothing."""
    src = _content_of(REPO / "src" / "web" / "inspect.py")
    for pat in _BS_REJECT_PATTERNS:
        m = re.search(pat, src)
        assert m is None, (
            f"src/web/inspect.py contains banned BS-call pattern "
            f"{pat!r} (match: {m.group() if m else None!r}). "
            f"CONSTRAINT 1 + memoir §24.1 forbid Black-Scholes work in "
            f"the Inspect hot path; it belongs upstream in src/engine/iv.py."
        )


def test_no_bs_calls_in_this_test_file():
    """Mechanical uniformity per the operator's pin: the grep rule
    applies to tests too. The IV-cache read is verified by stubbing
    load_iv_history, NOT by re-computing IV via BS as ground truth."""
    src = _content_of(REPO / "tests" / "test_web_inspect.py")
    # Strip the reject-pattern literal list itself before scanning so
    # the test file's reject-rule definitions don't false-positive.
    sanitized = re.sub(
        r"_BS_REJECT_PATTERNS\s*=\s*\[.*?\]", "", src, flags=re.DOTALL,
    )
    for pat in _BS_REJECT_PATTERNS:
        m = re.search(pat, sanitized)
        assert m is None, (
            f"tests/test_web_inspect.py contains banned BS-call pattern "
            f"{pat!r}. The CONSTRAINT 1 grep gate applies mechanically "
            f"to tests too."
        )
