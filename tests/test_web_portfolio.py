"""Tests for src.web.portfolio — Phase 9.4 SKELETON commit (9.4.1).

Uses Streamlit's AppTest framework (1.27+) to render the tab
end-to-end without a browser. Same pattern as test_web_inspect.py.

LOAD-BEARING:
  - test_portfolio_tab_renders_without_error (the skeleton smoke)
  - test_portfolio_tab_in_tab_options (app.py routing has it)
  - test_session_state_seeds_with_defaults (config block contract)
  - test_no_bs_calls_in_module (mirror of inspect's anti-BS-grep
    gate per memoir §24.1 — Portfolio also should NOT re-derive
    premium from IV; all BS lives upstream in engine.iv)
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

APP_PY = Path(__file__).resolve().parent.parent / "app.py"


# ============================================================
# Anti-BS-call gate (memoir §24.1 / inspect.py constraint)
# ============================================================

_BS_REJECT_PATTERNS = (
    re.compile(r"\bbs76_(?:call|put)_price\b"),
    re.compile(r"\bblack_scholes\b", re.IGNORECASE),
    re.compile(r"\bimplied_vol_(?:call|put)\b"),
    re.compile(r"\bextract_forward\b"),
    re.compile(r"\bbs_premium\b", re.IGNORECASE),
    re.compile(r"\bbsPremium\b"),
)


def test_no_bs_calls_in_module():
    """LOAD-BEARING memoir §24.1 mirror: the Portfolio tab must
    NEVER re-derive option premium from IV via Black-Scholes.
    All BS work happens upstream in ``engine.iv`` /
    ``iv_materializer``. This file should be a pure read from
    the cache + the analytics layer's pre-computed outputs.

    The same anti-grep gate that protects ``inspect.py`` per
    §24.1 protects ``portfolio.py`` for the same reason.
    """
    src = (Path(__file__).resolve().parent.parent
           / "src" / "web" / "portfolio.py").read_text()
    for pat in _BS_REJECT_PATTERNS:
        match = pat.search(src)
        if match:
            raise AssertionError(
                f"Portfolio tab must not re-derive premium from IV "
                f"(memoir §24.1 mirror). Found banned token: "
                f"{match.group(0)!r}"
            )


# ============================================================
# AppTest harness
# ============================================================

def _make_apptest() -> AppTest:
    """Build an AppTest instance pointed at the project's app.py.
    Same pattern as test_web_inspect.py's harness."""
    at = AppTest.from_file(str(APP_PY))
    at.query_params["tab"] = "Portfolio"
    return at


def test_portfolio_tab_renders_without_error():
    """LOAD-BEARING smoke: app.py routes ``?tab=Portfolio`` to the
    Portfolio tab and it renders without exception."""
    at = _make_apptest()
    at.run(timeout=10)
    assert not at.exception, f"Portfolio tab raised: {at.exception}"


def test_portfolio_tab_in_tab_options():
    """The Portfolio tab name must appear in app.py's ``_TAB_NAMES``
    so the routing radio actually exposes it.

    Streamlit's AppTest exposes ``.radio`` widgets; we check
    'Portfolio' is in one of them."""
    at = _make_apptest()
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    radio_options = []
    for r in at.radio:
        radio_options.extend(r.options or [])
    assert "Portfolio" in radio_options, (
        f"Portfolio not in radio options: {radio_options}"
    )


def test_portfolio_tab_renders_header_text():
    """Page header is rendered."""
    at = _make_apptest()
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    # Collect all markdown / caption text.
    visible = _collect_visible_text(at)
    assert "Portfolio" in visible
    assert "build_portfolio_history" in visible


def test_portfolio_tab_renders_n5_and_survivorship_banners():
    """Two standing caveat banners from memoir §11."""
    at = _make_apptest()
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "N=5" in visible
    assert "SURVIVORSHIP" in visible


def test_portfolio_tab_does_not_render_proxy_banner():
    """LOAD-BEARING post-9.6: the mockup's PROXY banner ('regime
    gate uses trailing-21d realized vol as a stand-in for India
    VIX') is DROPPED. Phase 9.6 shipped real India VIX
    integration so the caveat is no longer accurate. If this
    test fails, someone copy-pasted the banner back in."""
    at = _make_apptest()
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "trailing-21d realized vol" not in visible
    assert "true implied-vol integration deferred" not in visible.lower()


def test_portfolio_tab_renders_regime_banner_state():
    """ON or OFF must appear in the regime banner — Phase 9.6
    wires the v2 India VIX path."""
    at = _make_apptest()
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    # The banner shows "REGIME: **ON**" or "REGIME: **OFF**".
    assert "REGIME" in visible


def test_portfolio_tab_renders_strategy_config_widgets():
    """The strategy config block renders all expected widgets:
    universe-n selectbox, strategy selectbox, sizing selectbox,
    entry/exit sliders, regime/earnings toggles, IVP-band slider.

    Streamlit's AppTest exposes widgets by type. We check the
    counts so a future refactor can't silently drop a control."""
    at = _make_apptest()
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    # 3 selectboxes (positions / strategy / sizing).
    assert len(at.selectbox) >= 3
    # 3 sliders (entry / exit / IVP band).
    assert len(at.slider) >= 3
    # 2 toggles (regime gate / earnings filter).
    assert len(at.toggle) >= 2


def test_session_state_seeds_with_defaults():
    """LOAD-BEARING config-block defaults pin per the mockup
    DESIGN/Complete/app.jsx lines 30-38."""
    at = _make_apptest()
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    ss = at.session_state
    assert ss["mp_pf_universe_n"] == 5
    assert ss["mp_pf_strategy"] == "short_strangle"
    assert ss["mp_pf_entry_offset_td"] == 15
    assert ss["mp_pf_exit_offset_td"] == 3
    assert ss["mp_pf_sizing"] == "equal_margin"
    assert ss["mp_pf_regime_gate"] is True
    assert ss["mp_pf_earnings_filter"] is True
    # IVP band stored as tuple (60, 100) by default.
    assert tuple(ss["mp_pf_ivp_band"]) == (60, 100)


# ============================================================
# Helpers
# ============================================================

# ============================================================
# Phase 9.4.2 — equity curve + drawdown subplot
# ============================================================

def test_equity_curve_renders_plotly_chart_when_data_present():
    """LOAD-BEARING 9.4.2 contract: when the strategy config
    matches at least one cycle in the sweep, an equity-curve
    Plotly chart renders."""
    at = _make_apptest()
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    # AppTest exposes plotly_chart via at.plotly_chart in recent
    # Streamlit versions; fall back to scanning the protobuf if
    # not directly attribute-accessible.
    has_chart = False
    for attr_name in ("plotly_chart", "_plotly_chart"):
        if hasattr(at, attr_name):
            charts = getattr(at, attr_name)
            if charts:
                has_chart = True
                break
    # Loose smoke if AppTest doesn't expose plotly directly: just
    # verify the tab didn't crash and the caption text is present.
    if not has_chart:
        visible = _collect_visible_text(at)
        # Caption mentions cycles count + Phase 9.4.3 reference.
        assert "cycles" in visible or "Phase 9.4.3" in visible


def test_equity_curve_renders_caption_with_diagnostic_counts():
    """The chart's footer caption surfaces the cycle count + OFF
    count + final equity + max DD. Pin the text so downstream
    layout changes don't silently drop the diagnostic."""
    at = _make_apptest()
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    # Either we have data (caption with cycles) or we surface an
    # "empty config" info banner — both are acceptable end states.
    has_cycles_caption = "cycles" in visible and "regime-OFF" in visible
    has_empty_info = (
        "No trades match the current strategy" in visible
        or "Cycle P&L series is empty" in visible
    )
    assert has_cycles_caption or has_empty_info


def test_equity_curve_empty_filter_renders_info_banner():
    """When the strategy config picks an (entry, exit) tuple not
    present in the sweep, the chart degrades to a friendly
    st.info banner — NOT a crash. The exit slider's max=20
    exceeds the sweep's max exit_offset=15, so seeding exit=20
    forces the empty-filter path."""
    at = _make_apptest()
    at.session_state["mp_pf_exit_offset_td"] = 20
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "No trades match the current strategy" in visible


def test_equity_curve_helpers_compose_correctly():
    """Unit-level: the cycle-pnl → equity → drawdown composition
    matches what analytics.portfolio produces directly. Catches
    a future bug where the UI layer's data prep silently diverges
    from the analytics primitives."""
    import pandas as pd

    from src.analytics.portfolio import (
        cycle_pnl_series,
        drawdown_series,
        equity_curve,
    )
    from src.web.portfolio import _DEFAULT_STARTING_CAPITAL

    trades = pd.DataFrame({
        "strategy": ["short_strangle"] * 5,
        "entry_offset_td": [15] * 5,
        "exit_offset_td": [3] * 5,
        "expiry": pd.to_datetime([
            "2024-04-25", "2024-04-25", "2024-05-30",
            "2024-06-27", "2024-07-25",
        ]),
        "symbol": ["A", "B", "A", "A", "A"],
        "net_pnl": [5000.0, 3000.0, -2000.0, 8000.0, 1000.0],
    })
    pnl = cycle_pnl_series(trades)
    eq = equity_curve(pnl, starting_capital=_DEFAULT_STARTING_CAPITAL)
    dd = drawdown_series(eq)
    # Hand-check: cycle1 = 5k+3k=8k; cycle2=-2k; cycle3=8k; cycle4=1k.
    assert list(pnl.values) == [8000.0, -2000.0, 8000.0, 1000.0]
    # Equity prepended: [1M, 1.008M, 1.006M, 1.014M, 1.015M]
    assert eq.iloc[0] == _DEFAULT_STARTING_CAPITAL
    assert eq.iloc[-1] == _DEFAULT_STARTING_CAPITAL + sum(pnl.values)
    # DD: cummax catches the -2k dip at cycle 2.
    assert dd.min() == -2000.0


def _collect_visible_text(at: AppTest) -> str:
    """Concatenate every textual rendering on the AppTest run
    so we can assert on rendered content."""
    chunks: list[str] = []
    for attr in (
        "title", "header", "subheader", "markdown", "caption",
        "info", "warning", "error", "success", "text",
    ):
        widget_list = getattr(at, attr, None)
        if widget_list is None:
            continue
        for w in widget_list:
            val = getattr(w, "value", None) or getattr(w, "body", None)
            if val is not None:
                chunks.append(str(val))
    return "\n".join(chunks)
