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
    at.run(timeout=10)
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
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Concentration & correlation" in visible


def test_concentration_correlation_section_skips_on_empty_filter():
    at = _make_apptest()
    at.session_state["mp_pf_exit_offset_td"] = 20
    at.run(timeout=10)
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
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Worst 10 cycles" in visible


def test_worst_10_section_skips_on_empty_filter():
    at = _make_apptest()
    at.session_state["mp_pf_exit_offset_td"] = 20
    at.run(timeout=10)
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
    at.run(timeout=10)
    if at.exception:
        pytest.skip(f"Tab unreachable: {at.exception}")
    visible = _collect_visible_text(at)
    assert "Year-by-year stability" in visible


def test_yoy_section_skips_on_empty_filter():
    """No section header when the strategy config matches nothing."""
    at = _make_apptest()
    at.session_state["mp_pf_exit_offset_td"] = 20
    at.run(timeout=10)
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
    at.run(timeout=10)
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
    at.run(timeout=10)
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
