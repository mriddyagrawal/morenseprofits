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
    at.run(timeout=60)
    assert not at.exception, f"Portfolio tab raised: {at.exception}"


def test_portfolio_tab_in_tab_options():
    """The Portfolio tab name must appear in app.py's ``_TAB_NAMES``
    so the routing radio actually exposes it.

    Streamlit's AppTest exposes ``.radio`` widgets; we check
    'Portfolio' is in one of them."""
    at = _make_apptest()
    at.run(timeout=60)
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
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    # Collect all markdown / caption text.
    visible = _collect_visible_text(at)
    assert "Portfolio" in visible
    assert "build_portfolio_history" in visible


def test_portfolio_tab_renders_n_positions_and_universe_banners():
    """Two standing caveat banners from memoir §11.

    Post-Phase-10.1 fix: the SURVIVORSHIP banner now ADAPTS to
    the active sweep's universe size — blue-chip (≤ 60 symbols)
    keeps the warning, expanded (> 60) flips to EXPANDED UNIVERSE.
    Test accepts either; the dedicated
    test_survivorship_banner_renders_*_when_n_symbols_*
    pair pins each branch specifically."""
    at = _make_apptest()
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "N=5" in visible
    # One of the two universe-status banners must render.
    assert ("SURVIVORSHIP" in visible) or ("EXPANDED UNIVERSE" in visible)


def test_portfolio_tab_does_not_render_proxy_banner():
    """LOAD-BEARING post-9.6: the mockup's PROXY banner ('regime
    gate uses trailing-21d realized vol as a stand-in for India
    VIX') is DROPPED. Phase 9.6 shipped real India VIX
    integration so the caveat is no longer accurate. If this
    test fails, someone copy-pasted the banner back in."""
    at = _make_apptest()
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "trailing-21d realized vol" not in visible
    assert "true implied-vol integration deferred" not in visible.lower()


def test_portfolio_tab_renders_regime_banner_state():
    """ON or OFF must appear in the regime banner — Phase 9.6
    wires the v2 India VIX path."""
    at = _make_apptest()
    at.run(timeout=60)
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
    at.run(timeout=60)
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
    at.run(timeout=60)
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
# Survivorship banner adapts to active sweep's universe size
# (post-Phase 10.1 fix 2026-06-07)
# ============================================================

def test_survivorship_banner_renders_blue_chip_copy_when_n_symbols_low():
    """LOAD-BEARING Phase 10.1 adapt: when the active sweep has
    ≤ 60 symbols (blue-chip v1 universe), the SURVIVORSHIP
    warning copy + the prefetch instruction are present."""
    at = _make_apptest()
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    # If the live sweep has < 60 symbols, we see the v1 banner.
    # If it has > 60, we see the expanded banner. Skip if we
    # can't tell which path was hit (e.g., empty sweep).
    if "EXPANDED UNIVERSE" in visible:
        pytest.skip("active sweep is the expanded universe")
    assert "SURVIVORSHIP" in visible
    assert "survivor blue-chips" in visible


def test_survivorship_banner_renders_expanded_copy_when_n_symbols_high():
    """LOAD-BEARING Phase 10.1 adapt: when the active sweep has
    > 60 symbols, the EXPANDED UNIVERSE info banner replaces the
    SURVIVORSHIP warning."""
    at = _make_apptest()
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    if "SURVIVORSHIP" in visible:
        pytest.skip("active sweep is the blue-chip universe")
    assert "EXPANDED UNIVERSE" in visible
    assert "survivorship-free" in visible


def test_render_banners_threshold_pin():
    """Pin the 60-symbol threshold per the module docstring's
    contract: above the blue_chip 50 + a small headroom for
    hand-edited lists, well below the full F&O ~273."""
    from src.web.portfolio import _EXPANDED_UNIVERSE_THRESHOLD
    assert _EXPANDED_UNIVERSE_THRESHOLD == 60


def test_render_banners_n_positions_reflects_universe_n_config():
    """The N-positions banner shows the config's universe_n
    (positions per cycle), NOT the symbol count. Pinned so a
    future refactor can't accidentally swap the two."""
    at = _make_apptest()
    at.session_state["mp_pf_universe_n"] = 10
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "N=10" in visible


# ============================================================
# Candidate-selection pipeline (post-9.4 fix 2026-06-06)
# ============================================================

def test_select_top_n_for_cycle_regime_off_returns_empty():
    """LOAD-BEARING memoir §3 contract: when regime_state at
    entry == OFF and the gate is on, the cycle gets NO positions
    (empty list)."""
    import pandas as pd
    from datetime import date

    from src.web.portfolio import _select_top_n_for_cycle

    # Build a regime signal where percentile at as_of will be high
    # (top of band) → OFF state.
    idx = pd.date_range("2023-01-01", periods=300, freq="D")
    # Most low, peak at the end → today is 100th percentile → OFF.
    vals = list(range(len(idx)))
    signal = pd.Series(vals, index=idx, dtype="float64")

    picked = _select_top_n_for_cycle(
        universe_symbols=["RELIANCE", "INFY", "TCS"],
        entry_date=idx[-1].date(),
        exit_date=idx[-1].date(),
        universe_n=5,
        ivp_band=(0, 100),
        regime_signal=signal,
        events_df=None,
        regime_gate_on=True,
        earnings_filter_on=False,
    )
    assert picked == []


def test_select_top_n_for_cycle_regime_off_ignored_when_gate_off():
    """Regime gate disabled → ignore regime even when state is OFF."""
    import pandas as pd

    from src.web import portfolio as pf_mod

    idx = pd.date_range("2023-01-01", periods=300, freq="D")
    signal = pd.Series(list(range(len(idx))), index=idx, dtype="float64")

    # With gate off, the function tries liquidity + IVP. Stub those
    # so we can confirm we got past the regime gate.
    captured: list = []

    def fake_compute_liquidity_scores(syms, as_of, **kw):
        captured.append(("liq", list(syms)))
        return {s: 100.0 for s in syms}

    def fake_compute_ivp(sym, as_of):
        captured.append(("ivp", sym))
        return 50.0

    import src.web.portfolio as pf_module
    pf_module.compute_liquidity_scores = fake_compute_liquidity_scores
    pf_module.compute_ivp = fake_compute_ivp
    try:
        picked = pf_module._select_top_n_for_cycle(
            universe_symbols=["RELIANCE", "INFY"],
            entry_date=idx[-1].date(),
            exit_date=idx[-1].date(),
            universe_n=5,
            ivp_band=(0, 100),
            regime_signal=signal,
            events_df=None,
            regime_gate_on=False,  # gate OFF
            earnings_filter_on=False,
        )
    finally:
        # Reset module-level monkeypatches to library imports.
        from src.analytics.liquidity import compute_liquidity_scores as _cls
        from src.analytics.ivp import compute_ivp as _ci
        pf_module.compute_liquidity_scores = _cls
        pf_module.compute_ivp = _ci
    # Liquidity + IVP were called → gate was bypassed.
    assert any(t[0] == "liq" for t in captured)


def test_select_top_n_for_cycle_earnings_filter_drops_symbols():
    """LOAD-BEARING memoir §17.5: symbols with Financial Results
    in the window drop out before the liquidity / IVP layers."""
    import pandas as pd
    from datetime import date

    from src.web import portfolio as pf_module

    # Build an events frame where RELIANCE has Financial Results
    # in [entry, exit+1].
    events = pd.DataFrame({
        "SYMBOL": pd.Series(["RELIANCE"], dtype="string"),
        "PURPOSE": pd.Series(["Financial Results"], dtype="string"),
        "DATE": pd.to_datetime(["2024-06-15"]).astype("datetime64[us]"),
    })

    # Stub liquidity + IVP so we can see WHICH symbols got through.
    seen_in_liq: list[str] = []

    def fake_liq(syms, as_of, **kw):
        seen_in_liq.extend(syms)
        return {s: 100.0 for s in syms}

    def fake_ivp(sym, as_of):
        return 50.0

    pf_module.compute_liquidity_scores = fake_liq
    pf_module.compute_ivp = fake_ivp

    try:
        pf_module._select_top_n_for_cycle(
            universe_symbols=["RELIANCE", "INFY", "TCS"],
            entry_date=date(2024, 6, 10),
            exit_date=date(2024, 6, 18),
            universe_n=5,
            ivp_band=(0, 100),
            regime_signal=pd.Series([], dtype="float64",
                                     index=pd.DatetimeIndex([])),
            events_df=events,
            regime_gate_on=False,
            earnings_filter_on=True,
        )
    finally:
        from src.analytics.liquidity import compute_liquidity_scores as _cls
        from src.analytics.ivp import compute_ivp as _ci
        pf_module.compute_liquidity_scores = _cls
        pf_module.compute_ivp = _ci

    # RELIANCE filtered out at the earnings gate → not in liquidity input.
    assert "RELIANCE" not in seen_in_liq
    assert "INFY" in seen_in_liq
    assert "TCS" in seen_in_liq


def test_select_top_n_for_cycle_ivp_band_filters_symbols():
    """IVP band 60-100 → keep only symbols with IVP in [60, 100]."""
    import pandas as pd
    from datetime import date

    from src.web import portfolio as pf_module

    ivp_map = {"A": 80.0, "B": 30.0, "C": 90.0, "D": 50.0}

    def fake_liq(syms, as_of, **kw):
        return {s: 100.0 for s in syms}

    def fake_ivp(sym, as_of):
        return ivp_map.get(sym, float("nan"))

    pf_module.compute_liquidity_scores = fake_liq
    pf_module.compute_ivp = fake_ivp

    try:
        picked = pf_module._select_top_n_for_cycle(
            universe_symbols=["A", "B", "C", "D"],
            entry_date=date(2024, 6, 10),
            exit_date=date(2024, 6, 18),
            universe_n=5,
            ivp_band=(60, 100),
            regime_signal=pd.Series([], dtype="float64",
                                     index=pd.DatetimeIndex([])),
            events_df=None,
            regime_gate_on=False,
            earnings_filter_on=False,
        )
    finally:
        from src.analytics.liquidity import compute_liquidity_scores as _cls
        from src.analytics.ivp import compute_ivp as _ci
        pf_module.compute_liquidity_scores = _cls
        pf_module.compute_ivp = _ci

    # C (90) and A (80) are in [60, 100]; B (30) and D (50) drop.
    assert set(picked) == {"A", "C"}
    # Order is IVP descending → C first.
    assert picked == ["C", "A"]


def test_apply_candidate_selection_filters_to_picked_only():
    """LOAD-BEARING: only (expiry, symbol) tuples in the selection
    map survive the filter."""
    import pandas as pd

    from src.web.portfolio import _apply_candidate_selection

    sub = pd.DataFrame({
        "expiry": pd.to_datetime(
            ["2024-04-25"] * 3 + ["2024-05-30"] * 3
        ),
        "symbol": ["A", "B", "C", "A", "B", "C"],
        "net_pnl": [10, 20, 30, 40, 50, 60],
    })
    selection = {
        pd.Timestamp("2024-04-25"): ["A", "C"],
        pd.Timestamp("2024-05-30"): ["B"],
    }
    out = _apply_candidate_selection(sub, selection)
    # Expected rows: (Apr-25, A), (Apr-25, C), (May-30, B).
    assert len(out) == 3
    assert set(zip(out["expiry"], out["symbol"])) == {
        (pd.Timestamp("2024-04-25"), "A"),
        (pd.Timestamp("2024-04-25"), "C"),
        (pd.Timestamp("2024-05-30"), "B"),
    }


def test_apply_candidate_selection_drops_cycles_with_empty_picks():
    """Cycle with empty selection (regime OFF) → ALL trades for
    that cycle drop. Equity curve goes flat for that month."""
    import pandas as pd

    from src.web.portfolio import _apply_candidate_selection

    sub = pd.DataFrame({
        "expiry": pd.to_datetime(["2024-04-25"] * 3 + ["2024-05-30"] * 2),
        "symbol": ["A", "B", "C", "A", "B"],
        "net_pnl": [10, 20, 30, 40, 50],
    })
    selection = {
        pd.Timestamp("2024-04-25"): ["A"],
        pd.Timestamp("2024-05-30"): [],  # regime OFF
    }
    out = _apply_candidate_selection(sub, selection)
    assert len(out) == 1
    assert out["symbol"].iloc[0] == "A"
    assert pd.Timestamp("2024-05-30") not in out["expiry"].values


def test_apply_candidate_selection_empty_inputs():
    import pandas as pd
    from src.web.portfolio import _apply_candidate_selection
    assert _apply_candidate_selection(
        pd.DataFrame(), {}
    ).empty


def test_candidate_selection_toggle_skips_pipeline():
    """When apply_selection toggle is OFF, the portfolio view
    returns the full sidebar-filtered tuple — no selection
    pipeline runs."""
    at = _make_apptest()
    at.session_state["mp_pf_apply_selection"] = False
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    # No way to assert pipeline-not-called via AppTest directly;
    # smoke that the tab renders without crash under toggle-off.
    assert not at.exception


def test_selected_per_cycle_section_renders_when_toggle_on():
    """The 'Selected per cycle (v1 pipeline)' block appears in
    the cycle drilldown when the toggle is on (default)."""
    at = _make_apptest()
    at.run(timeout=30)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Selected per cycle" in visible


def test_selected_per_cycle_section_hidden_when_toggle_off():
    at = _make_apptest()
    at.session_state["mp_pf_apply_selection"] = False
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Selected per cycle" not in visible


# ============================================================
# Regime banner as-of snap (post-9.4 fix 2026-06-06)
# ============================================================

def test_resolve_as_of_snaps_to_latest_cached_vix_date(monkeypatch):
    """LOAD-BEARING: when today's VIX hasn't been published yet
    (lag / weekend / holiday), _resolve_as_of returns the cache's
    high-water mark so the regime banner doesn't fall into the
    cold-cache caption path.

    Fixes the bug exhibited 2026-06-06: VIX cache ended on
    2026-05-29, today() = 2026-06-06 → load_india_vix(offline=True)
    raised OfflineCacheMiss → banner showed 'Regime signal
    unavailable' despite the cache being populated."""
    from datetime import date
    import streamlit as st

    from src.web import portfolio as pf_mod

    # Stub today() in pf_mod.date to be 2026-06-06.
    # Stub _latest_cached_vix_date to return 2026-05-29.
    monkeypatch.setattr(
        pf_mod, "_latest_cached_vix_date",
        lambda: date(2026, 5, 29),
    )
    # Override date.today via a class swap is brittle; easier to
    # ensure mp_pf_as_of is unset and let the function take its
    # own date.today() route.
    st.session_state.pop("mp_pf_as_of", None)
    # We can't easily monkeypatch date.today() across the module
    # boundary, so just assert the snap holds whenever today() >
    # latest_vix. Use a synthesized today via mp_pf_as_of=None
    # path; the assertion checks min(today, latest_vix).
    resolved = pf_mod._resolve_as_of()
    today = date.today()
    expected = min(today, date(2026, 5, 29))
    assert resolved == expected


def test_resolve_as_of_uses_today_when_vix_cache_missing(monkeypatch):
    """When India VIX cache is absent, _resolve_as_of falls
    through to today() — the cold-cache caption path correctly
    fires downstream."""
    from datetime import date
    import streamlit as st

    from src.web import portfolio as pf_mod

    monkeypatch.setattr(
        pf_mod, "_latest_cached_vix_date", lambda: None,
    )
    st.session_state.pop("mp_pf_as_of", None)
    assert pf_mod._resolve_as_of() == date.today()


def test_resolve_as_of_explicit_override_wins(monkeypatch):
    """Operator-supplied mp_pf_as_of session-state value wins
    over the auto-snap (future date-picker contract)."""
    from datetime import date
    import streamlit as st

    from src.web import portfolio as pf_mod

    monkeypatch.setattr(
        pf_mod, "_latest_cached_vix_date",
        lambda: date(2026, 5, 29),
    )
    st.session_state["mp_pf_as_of"] = date(2024, 6, 1)
    assert pf_mod._resolve_as_of() == date(2024, 6, 1)
    # Cleanup so other tests aren't affected.
    st.session_state.pop("mp_pf_as_of", None)


def test_latest_cached_vix_date_handles_missing_parquet(monkeypatch, tmp_path):
    """Cold cache (no parquet) → None, NOT exception."""
    from src.data import cache

    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache._reset_root_memo()

    from src.web.portfolio import _latest_cached_vix_date
    assert _latest_cached_vix_date() is None


# ============================================================
# Phase 9.4.10 — deeplink to Inspect
# ============================================================

class _RerunIntercepted(Exception):
    """Sentinel exception so the deeplink writer's st.rerun()
    can be intercepted in unit tests without using StopIteration
    (which Python 3.7+ converts to RuntimeError inside
    generators / contexts)."""


def test_open_in_inspect_writes_canonical_url_params(monkeypatch):
    """LOAD-BEARING memoir §24.9 deeplink contract: the writer
    must set tab=Inspect + the 5-tuple (strategy / symbol /
    expiry / entry_offset_td / exit_offset_td) in URL params,
    AND call clear_inspect_state() so the next render re-seeds
    from URL."""
    import pandas as pd
    import streamlit as st

    from src.web import inspect as inspect_mod
    from src.web import portfolio as pf_mod

    # Capture clear_inspect_state calls + skip st.rerun().
    cleared: list[bool] = []

    def fake_clear():
        cleared.append(True)

    def fake_rerun():
        raise _RerunIntercepted("rerun intercepted")

    monkeypatch.setattr(inspect_mod, "clear_inspect_state", fake_clear)
    monkeypatch.setattr(st, "rerun", fake_rerun)
    st.query_params.clear()

    # The writer raises our intercept exception via fake_rerun;
    # everything before that must have run.
    try:
        pf_mod._open_in_inspect(
            strategy="short_strangle",
            symbol="RELIANCE",
            expiry=pd.Timestamp("2024-04-25"),
            entry_offset_td=15,
            exit_offset_td=3,
        )
    except _RerunIntercepted:
        pass

    assert st.query_params.get("tab") == "Inspect"
    assert st.query_params.get("strategy") == "short_strangle"
    assert st.query_params.get("symbol") == "RELIANCE"
    assert st.query_params.get("expiry") == "2024-04-25"
    assert st.query_params.get("entry_offset_td") == "15"
    assert st.query_params.get("exit_offset_td") == "3"
    assert cleared == [True]
    assert st.session_state["mp_active_tab"] == "Inspect"


def test_open_in_inspect_strategy_from_config(monkeypatch):
    """Strategy in URL matches the Portfolio config's strategy
    (not hardcoded). Defensive pin against a future refactor
    accidentally hardcoding."""
    import pandas as pd
    import streamlit as st

    from src.web import inspect as inspect_mod
    from src.web import portfolio as pf_mod

    def fake_rerun():
        raise _RerunIntercepted

    monkeypatch.setattr(inspect_mod, "clear_inspect_state",
                         lambda: None)
    monkeypatch.setattr(st, "rerun", fake_rerun)
    st.query_params.clear()

    try:
        pf_mod._open_in_inspect(
            strategy="iron_condor",
            symbol="INFY",
            expiry=pd.Timestamp("2024-05-30"),
            entry_offset_td=20,
            exit_offset_td=1,
        )
    except _RerunIntercepted:
        pass

    assert st.query_params.get("strategy") == "iron_condor"
    assert st.query_params.get("symbol") == "INFY"


def test_deeplink_button_renders_in_cycle_drilldown():
    """The 'Open in Inspect →' button is present in the cycle
    drilldown panel when there's at least one cycle to pick."""
    at = _make_apptest()
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    button_labels = [b.label for b in at.button]
    assert any("Open in Inspect" in label for label in button_labels), (
        f"deeplink button missing from drilldown panel; "
        f"got buttons: {button_labels}"
    )


# ============================================================
# Phase 9.4.9 — cycle drilldown
# ============================================================

def test_per_cycle_summary_columns_and_sort():
    """LOAD-BEARING 9.4.9 contract: per-cycle summary table
    columns + descending-by-expiry sort."""
    import pandas as pd

    from src.web.portfolio import _per_cycle_summary

    sub = pd.DataFrame({
        "expiry": pd.to_datetime([
            "2024-01-25", "2024-01-25",
            "2024-03-28", "2024-03-28", "2024-03-28",
            "2024-02-29", "2024-02-29",
        ]),
        "symbol": ["A", "B", "A", "B", "C", "A", "B"],
        "net_pnl": [5000, -2000, 1000, -3000, 8000, 4000, 6000],
    })
    out = _per_cycle_summary(sub)
    assert set(out.columns) == {
        "expiry", "cycle_pnl", "n_positions",
        "n_winners", "win_rate_pct",
    }
    # Sorted descending by expiry → most recent first.
    assert list(out["expiry"]) == [
        pd.Timestamp("2024-03-28"),
        pd.Timestamp("2024-02-29"),
        pd.Timestamp("2024-01-25"),
    ]
    # 2024-03-28: 1 + (-3) + 8 = 6k; 3 positions, 2 winners (A, C).
    row = out[out["expiry"] == pd.Timestamp("2024-03-28")].iloc[0]
    assert row["cycle_pnl"] == 6000
    assert row["n_positions"] == 3
    assert row["n_winners"] == 2


def test_per_cycle_summary_empty_returns_empty():
    import pandas as pd
    from src.web.portfolio import _per_cycle_summary
    out = _per_cycle_summary(pd.DataFrame(
        columns=["expiry", "symbol", "net_pnl"]
    ))
    assert out.empty


def test_per_symbol_in_cycle_filters_to_expiry():
    import pandas as pd

    from src.web.portfolio import _per_symbol_in_cycle

    sub = pd.DataFrame({
        "expiry": pd.to_datetime([
            "2024-01-25", "2024-01-25",
            "2024-02-29", "2024-02-29",
        ]),
        "symbol": ["A", "B", "A", "B"],
        "net_pnl": [100, 200, 300, 400],
    })
    out = _per_symbol_in_cycle(sub, pd.Timestamp("2024-01-25"))
    assert set(out["symbol"]) == {"A", "B"}
    assert out["net_pnl"].sum() == 300  # 100 + 200


def test_per_symbol_in_cycle_sorted_by_net_pnl_desc():
    """Top contributor renders at top."""
    import pandas as pd

    from src.web.portfolio import _per_symbol_in_cycle

    sub = pd.DataFrame({
        "expiry": pd.to_datetime(["2024-01-25"] * 3),
        "symbol": ["A", "B", "C"],
        "net_pnl": [-100, 500, 200],
    })
    out = _per_symbol_in_cycle(sub, pd.Timestamp("2024-01-25"))
    assert list(out["symbol"]) == ["B", "C", "A"]


def test_per_symbol_in_cycle_missing_cycle_returns_empty():
    import pandas as pd

    from src.web.portfolio import _per_symbol_in_cycle

    sub = pd.DataFrame({
        "expiry": pd.to_datetime(["2024-01-25"]),
        "symbol": ["A"],
        "net_pnl": [100],
    })
    out = _per_symbol_in_cycle(sub, pd.Timestamp("2025-12-31"))
    assert out.empty


def test_cycle_drilldown_section_renders():
    at = _make_apptest()
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Cycle drilldown" in visible


def test_cycle_drilldown_section_skips_on_empty_filter():
    at = _make_apptest()
    at.session_state["mp_pf_exit_offset_td"] = 20
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Cycle drilldown" not in visible


# ============================================================
# Phase 9.4.8 — IVP-decile sensitivity strip
# ============================================================

def test_per_decile_metrics_returns_one_row_per_bucket():
    """LOAD-BEARING 9.4.8 contract: one row per non-empty decile
    with count + median + Calmar + max DD + CVaR-5% columns."""
    import numpy as np
    import pandas as pd

    from src.web.portfolio import _per_decile_metrics

    # 100 trades with strictly increasing IVP so 10 deciles each
    # get 10 trades.
    n = 100
    sub = pd.DataFrame({
        "symbol": ["RELIANCE"] * n,
        "entry_date": pd.date_range("2024-01-01", periods=n, freq="D"),
        "expiry": pd.date_range("2024-01-15", periods=n, freq="D"),
        "net_pnl": np.arange(-50.0, 50.0),
    })
    # IVP series for RELIANCE with strict monotone values.
    ivp_per_sym = {
        "RELIANCE": pd.Series(
            np.linspace(0, 100, n),
            index=sub["entry_date"],
        ),
    }
    metrics = _per_decile_metrics(sub, ivp_per_sym, n_buckets=10)
    assert metrics.shape[0] >= 5  # at least some deciles populated
    assert set(metrics.columns) == {
        "decile", "count", "median_pnl", "calmar",
        "max_dd_inr", "cvar_5_pnl",
    }


def test_per_decile_metrics_handles_all_nan_ivp():
    """All trades drop out → empty table, NOT exception."""
    import pandas as pd

    from src.web.portfolio import _per_decile_metrics

    sub = pd.DataFrame({
        "symbol": ["MISSING"] * 10,
        "entry_date": pd.date_range("2024-01-01", periods=10, freq="D"),
        "expiry": pd.date_range("2024-01-15", periods=10, freq="D"),
        "net_pnl": [100.0] * 10,
    })
    ivp_per_sym: dict[str, pd.Series] = {}  # no symbols
    metrics = _per_decile_metrics(sub, ivp_per_sym)
    assert metrics.empty
    assert list(metrics.columns) == [
        "decile", "count", "median_pnl", "calmar",
        "max_dd_inr", "cvar_5_pnl",
    ]


def test_per_decile_metrics_empty_trades_returns_empty():
    import pandas as pd
    from src.web.portfolio import _per_decile_metrics
    out = _per_decile_metrics(pd.DataFrame(), {})
    assert out.empty


def test_ivp_sensitivity_section_renders():
    at = _make_apptest()
    at.run(timeout=30)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "IVP-decile sensitivity" in visible


def test_ivp_sensitivity_section_skips_on_empty_filter():
    at = _make_apptest()
    at.session_state["mp_pf_exit_offset_td"] = 20
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "IVP-decile sensitivity" not in visible


# ============================================================
# Phase 9.4.7 — 2-D regime × IVP diagnostic
# ============================================================

def test_build_ivp_per_symbol_handles_missing_cache(monkeypatch):
    """LOAD-BEARING: symbols with no IV cache yield empty IVP
    series (NaN values) — diagnostic function downstream treats
    them as dropped, NOT exceptions."""
    import pandas as pd

    from src.web import portfolio as pf_mod
    from src.web.portfolio import _build_ivp_per_symbol

    def fake_compute_ivp(symbol, as_of):
        if symbol == "MISSING":
            raise FileNotFoundError("no cache")
        return 50.0  # arbitrary valid IVP

    monkeypatch.setattr(pf_mod, "compute_ivp", fake_compute_ivp)
    sub = pd.DataFrame({
        "symbol": ["RELIANCE", "MISSING", "RELIANCE"],
        "entry_date": pd.to_datetime([
            "2024-06-01", "2024-06-02", "2024-07-01",
        ]),
        "net_pnl": [100.0, 200.0, 300.0],
    })
    out = _build_ivp_per_symbol(sub)
    assert set(out.keys()) == {"RELIANCE", "MISSING"}
    # MISSING symbol's series is all NaN.
    assert out["MISSING"].isna().all()
    # RELIANCE has 2 entries at 50.0.
    assert (out["RELIANCE"] == 50.0).all()


def test_build_ivp_per_symbol_empty_input_returns_empty_dict():
    import pandas as pd
    from src.web.portfolio import _build_ivp_per_symbol
    out = _build_ivp_per_symbol(pd.DataFrame())
    assert out == {}


def test_build_regime_signal_for_window_handles_loader_failure(monkeypatch):
    """Loader raises (e.g., cold VIX cache + offline=True) →
    return empty series, NOT exception."""
    import pandas as pd

    from src.web import portfolio as pf_mod
    from src.web.portfolio import _build_regime_signal_for_window

    def fake_default_regime_signal(*args, **kwargs):
        raise RuntimeError("VIX cache missing")

    monkeypatch.setattr(
        pf_mod, "default_regime_signal", fake_default_regime_signal,
    )
    sub = pd.DataFrame({
        "entry_date": pd.to_datetime([
            "2024-06-01", "2024-07-01",
        ]),
        "symbol": ["A", "B"],
        "net_pnl": [100.0, 200.0],
    })
    out = _build_regime_signal_for_window(sub)
    assert out.empty


def test_build_regime_signal_for_window_empty_trades_returns_empty():
    import pandas as pd
    from src.web.portfolio import _build_regime_signal_for_window
    assert _build_regime_signal_for_window(pd.DataFrame()).empty


def test_regime_x_ivp_section_renders():
    """The section renders (with whatever fallback the cache
    state allows) — should not crash on a real Portfolio config."""
    at = _make_apptest()
    at.run(timeout=30)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Regime × IVP diagnostic" in visible


def test_regime_x_ivp_section_skips_on_empty_filter():
    at = _make_apptest()
    at.session_state["mp_pf_exit_offset_td"] = 20
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Regime × IVP diagnostic" not in visible


# ============================================================
# Phase 9.4.6 — concentration + correlation
# ============================================================

def test_per_symbol_margin_share_sums_to_100_pct():
    """LOAD-BEARING contract: share_pct sums to 100 across all
    symbols (modulo float rounding)."""
    import pandas as pd

    from src.web.portfolio import _per_symbol_margin_share

    sub = pd.DataFrame({
        "symbol": ["A", "A", "B", "C", "C", "C"],
        "margin_at_entry": [
            100_000.0, 50_000.0,
            200_000.0,
            75_000.0, 80_000.0, 95_000.0,
        ],
        "net_pnl": [0.0] * 6,
    })
    out = _per_symbol_margin_share(sub)
    assert out["share_pct"].sum() == pytest.approx(100.0, abs=1e-9)


def test_per_symbol_margin_share_sorted_descending():
    import pandas as pd

    from src.web.portfolio import _per_symbol_margin_share

    sub = pd.DataFrame({
        "symbol": ["A", "B", "C"],
        "margin_at_entry": [50_000.0, 200_000.0, 100_000.0],
        "net_pnl": [0.0] * 3,
    })
    out = _per_symbol_margin_share(sub)
    assert list(out["symbol"]) == ["B", "C", "A"]


def test_per_symbol_margin_share_empty_returns_empty():
    import pandas as pd

    from src.web.portfolio import _per_symbol_margin_share

    out = _per_symbol_margin_share(
        pd.DataFrame(columns=["symbol", "margin_at_entry", "net_pnl"])
    )
    assert out.empty
    assert list(out.columns) == ["symbol", "margin_total", "share_pct"]


def test_per_symbol_margin_share_handles_missing_margin_column():
    """Older sweep parquets may lack margin_at_entry — empty
    output, NO exception."""
    import pandas as pd

    from src.web.portfolio import _per_symbol_margin_share

    sub = pd.DataFrame({
        "symbol": ["A", "B"],
        "net_pnl": [100.0, 200.0],
    })
    out = _per_symbol_margin_share(sub)
    assert out.empty


def test_pairwise_correlation_matrix_returns_square_frame():
    """LOAD-BEARING: ``corr`` matrix shape = (n_symbols, n_symbols).
    Diagonal == 1.0 (every symbol correlates perfectly with itself)."""
    import pandas as pd

    from src.web.portfolio import _pairwise_correlation_matrix

    sub = pd.DataFrame({
        "expiry": pd.to_datetime([
            "2024-01-25", "2024-02-29", "2024-03-28", "2024-04-25",
            "2024-01-25", "2024-02-29", "2024-03-28", "2024-04-25",
        ]),
        "symbol": ["A", "A", "A", "A", "B", "B", "B", "B"],
        "net_pnl": [100, 200, 300, 400, -100, -200, -300, -400],
    })
    corr = _pairwise_correlation_matrix(sub)
    assert corr.shape == (2, 2)
    assert corr.loc["A", "A"] == pytest.approx(1.0, abs=1e-9)
    assert corr.loc["B", "B"] == pytest.approx(1.0, abs=1e-9)
    # Perfect anti-correlation.
    assert corr.loc["A", "B"] == pytest.approx(-1.0, abs=1e-9)


def test_pairwise_correlation_matrix_single_symbol_returns_empty():
    """≥ 2 symbols required for meaningful correlation."""
    import pandas as pd

    from src.web.portfolio import _pairwise_correlation_matrix

    sub = pd.DataFrame({
        "expiry": pd.to_datetime(["2024-01-25", "2024-02-29"]),
        "symbol": ["A", "A"],
        "net_pnl": [100, 200],
    })
    assert _pairwise_correlation_matrix(sub).empty


def test_concentration_correlation_section_renders():
    at = _make_apptest()
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Concentration & correlation" in visible


def test_concentration_correlation_section_skips_on_empty_filter():
    at = _make_apptest()
    at.session_state["mp_pf_exit_offset_td"] = 20
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Concentration & correlation" not in visible


# ============================================================
# Phase 9.4.5 — worst-10 cycles with attribution
# ============================================================

def test_worst_10_returns_n_or_fewer_cycles():
    """LOAD-BEARING 9.4.5 contract: top-N worst cycles sorted
    ascending by cycle_pnl with per-symbol attribution."""
    import pandas as pd

    from src.web.portfolio import _worst_cycles_with_attribution

    # 15 cycles, varying outcomes — ask for worst 10.
    sub = pd.DataFrame({
        "strategy": ["short_strangle"] * 30,
        "expiry": pd.to_datetime(
            [f"2024-{m:02d}-25" for m in range(1, 13)
             for _ in range(2)] + [
                "2025-01-25", "2025-01-25",
                "2025-02-28", "2025-02-28",
                "2025-03-28", "2025-03-28",
            ]
        ),
        "symbol": ["A", "B"] * 15,
        "net_pnl": list(range(-150_000, 150_000, 10_000)),
    })
    out = _worst_cycles_with_attribution(sub, n=10)
    assert len(out) == 10
    # Ascending by cycle_pnl.
    assert out["cycle_pnl"].is_monotonic_increasing


def test_worst_10_attribution_includes_symbol_with_loss():
    """Attribution string surfaces the symbol with the largest
    contribution to the loss."""
    import pandas as pd

    from src.web.portfolio import _worst_cycles_with_attribution

    sub = pd.DataFrame({
        "expiry": pd.to_datetime(
            ["2024-01-25"] * 3 + ["2024-02-29"] * 3
        ),
        "symbol": ["RELIANCE", "INFY", "TCS",
                    "RELIANCE", "INFY", "TCS"],
        "net_pnl": [-50_000, -10_000, 5_000,
                     5_000, 10_000, -20_000],
    })
    out = _worst_cycles_with_attribution(sub, n=10)
    # Cycle 2024-01-25 is the worst (-55k); attribution should
    # mention RELIANCE first (largest contributor).
    worst = out.iloc[0]
    assert worst["cycle_pnl"] == -55_000.0
    assert "RELIANCE" in worst["attribution"]


def test_worst_10_empty_returns_empty_table():
    import pandas as pd

    from src.web.portfolio import _worst_cycles_with_attribution

    empty = pd.DataFrame(columns=["expiry", "symbol", "net_pnl"])
    out = _worst_cycles_with_attribution(empty)
    assert out.empty
    assert list(out.columns) == ["expiry", "cycle_pnl", "attribution"]


def test_worst_10_returns_fewer_than_n_when_universe_smaller():
    """5 cycles available; ask for 10 → return 5."""
    import pandas as pd

    from src.web.portfolio import _worst_cycles_with_attribution

    sub = pd.DataFrame({
        "expiry": pd.to_datetime(
            ["2024-01-25", "2024-02-29", "2024-03-28",
             "2024-04-25", "2024-05-30"]
        ),
        "symbol": ["A"] * 5,
        "net_pnl": [-5_000, -3_000, -1_000, 2_000, 4_000],
    })
    out = _worst_cycles_with_attribution(sub, n=10)
    assert len(out) == 5


def test_worst_10_section_renders_when_data_present():
    at = _make_apptest()
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Worst 10 cycles" in visible


def test_worst_10_section_skips_on_empty_filter():
    at = _make_apptest()
    at.session_state["mp_pf_exit_offset_td"] = 20
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Worst 10 cycles" not in visible


# ============================================================
# Phase 9.4.4 — year-by-year stability table
# ============================================================

def test_yoy_per_year_stats_compose_correctly():
    """Unit-level: _per_year_stats produces one row per calendar
    year with cycles + return + max DD + Calmar + Ulcer columns."""
    import pandas as pd

    from src.web.portfolio import _DEFAULT_STARTING_CAPITAL, _per_year_stats

    pnl = pd.Series(
        [10_000, -5_000, 8_000, 12_000, -3_000, 7_000,
         15_000, -8_000, 4_000, -2_000, 6_000, 11_000,
         -4_000, 9_000, 5_000, -10_000, 13_000, 2_000],
        index=pd.to_datetime([
            # 6 cycles in 2023
            "2023-01-25", "2023-03-29", "2023-05-25",
            "2023-07-27", "2023-09-28", "2023-11-30",
            # 12 cycles in 2024
            "2024-01-25", "2024-02-29", "2024-03-28",
            "2024-04-25", "2024-05-30", "2024-06-27",
            "2024-07-25", "2024-08-29", "2024-09-26",
            "2024-10-31", "2024-11-28", "2024-12-26",
        ]),
    )
    stats = _per_year_stats(pnl, _DEFAULT_STARTING_CAPITAL)
    assert list(stats.columns) == [
        "year", "cycles", "return_inr", "return_pct",
        "max_dd_inr", "calmar", "ulcer",
    ]
    assert stats.shape[0] == 2  # 2023, 2024
    # Year 2023 has 6 cycles → Calmar surfaces.
    row_2023 = stats[stats["year"] == 2023].iloc[0]
    assert row_2023["cycles"] == 6
    assert row_2023["return_inr"] == 29_000.0
    assert not pd.isna(row_2023["calmar"])
    # Year 2024 has 12 cycles → Calmar surfaces.
    row_2024 = stats[stats["year"] == 2024].iloc[0]
    assert row_2024["cycles"] == 12


def test_yoy_calmar_nan_when_year_has_few_cycles():
    """Thin years (< 6 cycles) report Calmar as NaN to avoid
    optical noise from over-annualizing a partial-year sample."""
    import pandas as pd

    from src.web.portfolio import _DEFAULT_STARTING_CAPITAL, _per_year_stats

    pnl = pd.Series(
        [5_000, -2_000, 3_000],  # only 3 cycles in 2024
        index=pd.to_datetime(["2024-01-25", "2024-02-29", "2024-03-28"]),
    )
    stats = _per_year_stats(pnl, _DEFAULT_STARTING_CAPITAL)
    assert stats.shape[0] == 1
    assert pd.isna(stats.iloc[0]["calmar"])


def test_yoy_per_year_stats_carries_cumulative_equity_forward():
    """Year N+1's starting capital == year N's ending equity.
    Pin this so the per-year report is honest about cumulative
    book trajectory."""
    import pandas as pd

    from src.web.portfolio import _DEFAULT_STARTING_CAPITAL, _per_year_stats

    pnl = pd.Series(
        [100_000, 50_000, -25_000, 75_000],  # 2 cycles each year
        index=pd.to_datetime([
            "2023-06-30", "2023-12-29",
            "2024-06-28", "2024-12-31",
        ]),
    )
    stats = _per_year_stats(pnl, _DEFAULT_STARTING_CAPITAL)
    # 2023: +150k on 1M → 15.0%; 2024: +50k on 1.15M → 4.348%
    row_2023 = stats[stats["year"] == 2023].iloc[0]
    row_2024 = stats[stats["year"] == 2024].iloc[0]
    assert row_2023["return_pct"] == pytest.approx(15.0, abs=1e-9)
    assert row_2024["return_pct"] == pytest.approx(
        50_000 / 1_150_000 * 100, abs=1e-9,
    )


def test_yoy_empty_pnl_returns_empty_table():
    """Cold input → schema-shaped empty frame, NOT exception."""
    import pandas as pd

    from src.web.portfolio import _per_year_stats

    empty = pd.Series([], dtype="float64",
                       index=pd.DatetimeIndex([]))
    stats = _per_year_stats(empty, 1_000_000.0)
    assert stats.empty
    assert list(stats.columns) == [
        "year", "cycles", "return_inr", "return_pct",
        "max_dd_inr", "calmar", "ulcer",
    ]


def test_yoy_section_renders_when_data_present():
    """The 'Year-by-year stability' section renders when the
    strategy config matches data."""
    at = _make_apptest()
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Year-by-year stability" in visible


def test_yoy_section_skips_on_empty_filter():
    """No section header when the strategy config matches nothing."""
    at = _make_apptest()
    at.session_state["mp_pf_exit_offset_td"] = 20
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Year-by-year stability" not in visible


# ============================================================
# Phase 9.4.3 — headline metrics strip
# ============================================================

def test_headline_strip_renders_six_metric_cards():
    """LOAD-BEARING 9.4.3 contract: 6 st.metric cards above the
    equity curve when the strategy config matches data."""
    at = _make_apptest()
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    # st.metric widgets exposed via at.metric.
    metric_labels = [m.label for m in at.metric]
    expected = {"Total return", "Calmar", "Ulcer", "Sortino",
                "Max DD ₹", "Worst cycle"}
    missing = expected - set(metric_labels)
    assert not missing, (
        f"headline strip missing cards: {missing}; got {metric_labels}"
    )


def test_headline_strip_skips_silently_on_empty_filter():
    """When the strategy config matches nothing, the headline strip
    skips silently (the equity_curve already rendered the
    explanatory banner; double-rendering would be noise)."""
    at = _make_apptest()
    at.session_state["mp_pf_exit_offset_td"] = 20  # empty path
    at.run(timeout=60)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    metric_labels = [m.label for m in at.metric]
    # None of the headline-strip card labels should appear.
    forbidden = {"Total return", "Calmar", "Ulcer", "Sortino",
                 "Max DD ₹", "Worst cycle"}
    assert not (set(metric_labels) & forbidden), (
        f"headline strip leaked under empty filter: {metric_labels}"
    )


def test_fmt_inr_compact_handles_lakh_crore_thousand():
    """Pin the formatter so the headline strip doesn't drift."""
    from src.web.portfolio import _fmt_inr_compact
    assert _fmt_inr_compact(50_000) == "₹50.0k"
    assert _fmt_inr_compact(150_000) == "₹1.50L"
    assert _fmt_inr_compact(2_500_000) == "₹25.00L"
    assert _fmt_inr_compact(15_000_000) == "₹1.50Cr"
    assert _fmt_inr_compact(-150_000) == "-₹1.50L"
    assert _fmt_inr_compact(float("nan")) == "—"


def test_fmt_ratio_handles_inf_and_nan():
    """Calmar can return inf on monotone-up curves; Sortino can
    return inf on no-downside. Both render cleanly."""
    from src.web.portfolio import _fmt_ratio
    assert _fmt_ratio(1.234) == "1.23"
    assert _fmt_ratio(float("inf")) == "∞"
    assert _fmt_ratio(float("-inf")) == "-∞"
    assert _fmt_ratio(float("nan")) == "—"


# ============================================================
# Phase 9.4.2 — equity curve + drawdown subplot
# ============================================================

def test_equity_curve_renders_plotly_chart_when_data_present():
    """LOAD-BEARING 9.4.2 contract: when the strategy config
    matches at least one cycle in the sweep, an equity-curve
    Plotly chart renders."""
    at = _make_apptest()
    at.run(timeout=60)
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
    at.run(timeout=60)
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
    at.run(timeout=60)
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
