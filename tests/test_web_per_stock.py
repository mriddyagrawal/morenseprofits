"""Tests for src.web.per_stock — Phase 6.5 headline strip.

Tests focus on render_headline; the _quick_switcher's button-row
rendering is verified visually via streamlit run app.py (its state-
plumbing is straightforward — st.button → st.session_state →
st.rerun).
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.web.per_stock import render_headline


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


def test_naming_rule_pnl_label_includes_rupee_symbol(captured_metrics):
    """LOAD-BEARING §2.5 anti-mockup-bug: card labeled "P&L" displays
    in rupees, not percentage. Pin label-name AND value-format."""
    rows = [_row(symbol="X", net_pnl=50_000.0)] * 6
    render_headline(pd.DataFrame(rows), symbol="X", min_n=5)
    pnl = captured_metrics[2]
    assert "P&L" in pnl["label"]
    assert "₹" in pnl["value"]
    assert "%" not in pnl["value"]
