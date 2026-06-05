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
