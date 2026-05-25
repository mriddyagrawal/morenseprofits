"""Tests for src.web.per_stock — Phase 6.5 headline strip.

Tests focus on render_headline; the _quick_switcher's button-row
rendering is verified visually via streamlit run app.py (its state-
plumbing is straightforward — st.button → st.session_state →
st.rerun).
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.web.per_stock import render_headline, render_strategy_dashboard


@pytest.fixture
def captured_metrics(monkeypatch):
    metrics: list[dict] = []

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_columns(n_or_spec):
        n = n_or_spec if isinstance(n_or_spec, int) else len(n_or_spec)
        return [_NullCtx() for _ in range(n)]

    def fake_metric(label, value, delta=None, delta_color="normal", **kw):
        metrics.append({"label": label, "value": value, "delta": delta})

    import src.web.per_stock as ps
    monkeypatch.setattr(ps.st, "columns", fake_columns)
    monkeypatch.setattr(ps.st, "metric", fake_metric)
    return metrics


def _row(strategy="A", symbol="X", net_pnl=100.0,
         roi_pct=1.0, roi_pct_annualized=12.0,
         entry=15, exit_=1):
    return {
        "strategy": strategy, "symbol": symbol,
        "net_pnl": net_pnl, "roi_pct": roi_pct,
        "roi_pct_annualized": roi_pct_annualized,
        "entry_offset_td": entry, "exit_offset_td": exit_,
    }


# ============================================================
# Empty / sentinel paths
# ============================================================

def test_empty_df_renders_four_dashes(captured_metrics):
    render_headline(pd.DataFrame({
        "strategy": pd.Series(dtype="string"),
        "symbol": pd.Series(dtype="string"),
        "net_pnl": pd.Series(dtype="float64"),
        "roi_pct": pd.Series(dtype="float64"),
        "roi_pct_annualized": pd.Series(dtype="float64"),
        "entry_offset_td": pd.Series(dtype="int64"),
        "exit_offset_td": pd.Series(dtype="int64"),
    }), symbol=None, min_n=5)
    assert [m["label"] for m in captured_metrics] == [
        "Top strategy", "Symbol win rate", "Symbol total P&L",
        "Strategies above benchmark",
    ]
    assert all(m["value"] == "—" for m in captured_metrics)


def test_no_trades_for_selected_symbol_dashes(captured_metrics):
    """Symbol selected but no rows for it (e.g., stale switcher state
    after sidebar filter changed). Cards say so explicitly."""
    rows = [_row(symbol="OTHER")] * 6
    render_headline(pd.DataFrame(rows), symbol="RELIANCE", min_n=5)
    assert all(m["value"] == "—" for m in captured_metrics)
    assert any("no trades for RELIANCE" in m["delta"] for m in captured_metrics)


# ============================================================
# Populated paths
# ============================================================

def test_top_strategy_picked_by_median_ann_roi(captured_metrics):
    """3 strategies on RELIANCE: A median=10%, B median=30%, C median=20%.
    Top strategy card → B."""
    rows = (
        [_row(strategy="A", symbol="RELIANCE", roi_pct_annualized=10.0)] * 6 +
        [_row(strategy="B", symbol="RELIANCE", roi_pct_annualized=30.0)] * 6 +
        [_row(strategy="C", symbol="RELIANCE", roi_pct_annualized=20.0)] * 6
    )
    render_headline(pd.DataFrame(rows), symbol="RELIANCE", min_n=5)
    top = captured_metrics[0]
    assert top["value"] == "B"
    assert "+30.0%/yr" in top["delta"]


def test_symbol_win_rate_card_format_is_percentage(captured_metrics):
    """4 winners + 2 losers for RELIANCE → 66.7%. Pin format."""
    rows = (
        [_row(symbol="RELIANCE", net_pnl=100.0)] * 4 +
        [_row(symbol="RELIANCE", net_pnl=-50.0)] * 2
    )
    render_headline(pd.DataFrame(rows), symbol="RELIANCE", min_n=5)
    win_card = captured_metrics[1]
    assert win_card["value"] == "66.7%"
    assert "4 of 6" in win_card["delta"]


def test_symbol_total_pnl_card_format_is_rupees(captured_metrics):
    """6 × ₹100,000 = ₹6 L. Pin ₹ + L notation per format_inr."""
    rows = [_row(symbol="RELIANCE", net_pnl=100_000.0)] * 6
    render_headline(pd.DataFrame(rows), symbol="RELIANCE", min_n=5)
    pnl_card = captured_metrics[2]
    assert pnl_card["label"] == "Symbol total P&L"
    assert pnl_card["value"] == "₹6.00 L"
    assert "₹" in pnl_card["value"]


def test_strategies_above_benchmark_count(captured_metrics):
    """Of 3 strategies, 2 with median ann ROI > 0, 1 with < 0 →
    '2/3' value, subtitle names the benchmark."""
    rows = (
        [_row(strategy="A", symbol="X", roi_pct_annualized=10.0)] * 6 +
        [_row(strategy="B", symbol="X", roi_pct_annualized=20.0)] * 6 +
        [_row(strategy="C", symbol="X", roi_pct_annualized=-5.0)] * 6
    )
    render_headline(pd.DataFrame(rows), symbol="X", min_n=5)
    benchmark = captured_metrics[3]
    assert benchmark["value"] == "2/3"
    assert "breakeven" in benchmark["delta"].lower() or "0%" in benchmark["delta"]


# ============================================================
# render_strategy_dashboard — per-strategy small-multiples
# ============================================================

@pytest.fixture
def captured_dash(monkeypatch):
    """Capture markdown / metrics / charts / info from
    render_strategy_dashboard."""
    events: list[dict] = []

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_columns(n_or_spec):
        n = n_or_spec if isinstance(n_or_spec, int) else len(n_or_spec)
        return [_NullCtx() for _ in range(n)]

    def fake_markdown(text, **_):
        events.append({"kind": "markdown", "text": text})

    def fake_caption(text, **_):
        events.append({"kind": "caption", "text": text})

    def fake_plotly_chart(fig, **_):
        events.append({"kind": "plotly_chart", "fig": fig})

    def fake_info(msg, **_):
        events.append({"kind": "info", "msg": msg})

    import src.web.per_stock as ps
    monkeypatch.setattr(ps.st, "columns", fake_columns)
    monkeypatch.setattr(ps.st, "markdown", fake_markdown)
    monkeypatch.setattr(ps.st, "caption", fake_caption)
    monkeypatch.setattr(ps.st, "plotly_chart", fake_plotly_chart)
    monkeypatch.setattr(ps.st, "info", fake_info)
    import src.web.empty_state as es
    monkeypatch.setattr(es.st, "info", fake_info)
    return events


def test_dashboard_renders_card_per_strategy(captured_dash):
    """Two strategies on RELIANCE → at least 2 strategy headings
    + 2 sparkline charts."""
    rows = (
        [_row(strategy="A", symbol="RELIANCE")] * 6 +
        [_row(strategy="B", symbol="RELIANCE")] * 6
    )
    render_strategy_dashboard(pd.DataFrame(rows),
                              symbol="RELIANCE", min_n=5)
    # Strategy headings appear as markdown "##### A" / "##### B"
    headings = [
        e for e in captured_dash
        if e["kind"] == "markdown" and e["text"].startswith("##### ")
    ]
    assert len(headings) == 2
    heading_text = " ".join(h["text"] for h in headings)
    assert "A" in heading_text
    assert "B" in heading_text
    # And at least 2 sparkline charts (1 per strategy)
    charts = [e for e in captured_dash if e["kind"] == "plotly_chart"]
    assert len(charts) >= 2


def test_dashboard_sort_order_median_ann_roi_desc(captured_dash):
    """Cards sorted by median ann ROI DESC so visually-best appears
    top-left of the grid."""
    rows = (
        [_row(strategy="A", symbol="X", roi_pct_annualized=10.0)] * 6 +
        [_row(strategy="B", symbol="X", roi_pct_annualized=40.0)] * 6 +
        [_row(strategy="C", symbol="X", roi_pct_annualized=25.0)] * 6
    )
    render_strategy_dashboard(pd.DataFrame(rows), symbol="X", min_n=5)
    headings = [
        e for e in captured_dash
        if e["kind"] == "markdown" and e["text"].startswith("##### ")
    ]
    # Order: B (40) → C (25) → A (10)
    strats_in_order = [h["text"].replace("##### ", "").strip() for h in headings]
    assert strats_in_order == ["B", "C", "A"]


def test_dashboard_thin_n_strategy_carries_warning_badge(captured_dash):
    """Strategies with N < min_n keep their card but get a "⚠ N<K"
    suffix on the heading — visual signal even if operator only
    glances at the small-multiples grid."""
    rows = (
        [_row(strategy="A", symbol="X")] * 6 +    # N=6, eligible
        [_row(strategy="B", symbol="X")] * 2      # N=2, thin
    )
    render_strategy_dashboard(pd.DataFrame(rows), symbol="X", min_n=5)
    headings = [
        e for e in captured_dash
        if e["kind"] == "markdown" and e["text"].startswith("##### ")
    ]
    a_h = next(h["text"] for h in headings if "A" in h["text"])
    b_h = next(h["text"] for h in headings if "B" in h["text"])
    assert "⚠" not in a_h
    assert "⚠" in b_h
    assert "N<5" in b_h


def test_dashboard_empty_routes_through_empty_state(captured_dash):
    """0 filtered rows → no_rows_after_filters via render_empty."""
    render_strategy_dashboard(pd.DataFrame({
        "strategy": pd.Series(dtype="string"),
        "symbol": pd.Series(dtype="string"),
        "net_pnl": pd.Series(dtype="float64"),
        "roi_pct": pd.Series(dtype="float64"),
        "roi_pct_annualized": pd.Series(dtype="float64"),
        "entry_offset_td": pd.Series(dtype="int64"),
        "exit_offset_td": pd.Series(dtype="int64"),
    }), symbol=None, min_n=5)
    kinds = [e["kind"] for e in captured_dash]
    assert "info" in kinds
    info = next(e for e in captured_dash if e["kind"] == "info")
    assert "filters" in info["msg"].lower()


def test_dashboard_sparkline_color_by_total_not_last_trade(captured_dash):
    """LOAD-BEARING per d7e511d review: sparkline color must reflect
    TOTAL P&L sign, NOT just the last trade's. A strategy that won
    17 trades + lost the 18th has positive total and must NOT render
    as red. Inverse test: strategy with 17 losses + 1 small win has
    negative total and must NOT render as green."""
    from src.web.per_stock import _sparkline_figure

    # Won 17 × ₹100 = +₹1700, lost ₹50 on the 18th → total = +₹1650
    mostly_winning = [100.0] * 17 + [-50.0]
    fig_win = _sparkline_figure(mostly_winning)
    assert "0, 100, 0" in fig_win.data[0].line.color  # green

    # Lost 17 × ₹100 = -₹1700, won ₹50 on the 18th → total = -₹1650
    mostly_losing = [-100.0] * 17 + [50.0]
    fig_lose = _sparkline_figure(mostly_losing)
    assert "200, 50, 50" in fig_lose.data[0].line.color  # red

    # Zero total → green (>= 0 path)
    fig_zero = _sparkline_figure([10.0, -10.0])
    assert "0, 100, 0" in fig_zero.data[0].line.color


def test_dashboard_sparkline_omitted_when_lt_2_trades(captured_dash):
    """A strategy with 0-1 trades for the selected symbol gets a
    "_sparkline needs ≥2 trades_" caption instead of a chart."""
    rows = [_row(strategy="A", symbol="X")] * 1  # 1 trade
    render_strategy_dashboard(pd.DataFrame(rows), symbol="X", min_n=0)
    captions = [e for e in captured_dash if e["kind"] == "caption"]
    sparkline_msg = any("sparkline" in c["text"].lower() for c in captions)
    assert sparkline_msg


def test_naming_rule_pnl_label_includes_rupee_symbol(captured_metrics):
    """LOAD-BEARING §2.5 anti-mockup-bug: card labeled "P&L" displays
    in rupees, not percentage. Pin label-name AND value-format."""
    rows = [_row(symbol="X", net_pnl=50_000.0)] * 6
    render_headline(pd.DataFrame(rows), symbol="X", min_n=5)
    pnl = captured_metrics[2]
    assert "P&L" in pnl["label"]
    assert "₹" in pnl["value"]
    assert "%" not in pnl["value"]
