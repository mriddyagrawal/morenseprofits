"""Tests for src.web.leaderboard — headline strip (Phase 6.2.headline).

render_headline() requires a Streamlit context; we capture st.metric
calls via monkeypatch + verify the four cards land in the right
positions with the right values + the right subtitles.

Load-bearing per DESIGN_SPEC §2.5:
  - 4 cards in canonical order: TOP PAIR / WIN RATE / TOTAL P&L / RANKED
  - empty-frame fallback: every card "—" + "no data after filters"
  - rupee values go through format_inr (NOT a bare number)
  - percentage values go through format_pct (NOT a bare number)
  - mockup-bug prevention: a card labeled "P&L" must show ₹; a card
    labeled "rate" must show %
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.web.leaderboard import render_headline


@pytest.fixture
def captured_metrics(monkeypatch):
    """Replace st.metric with a recorder; replace st.columns with a
    pass-through that yields N context managers (matching real
    streamlit's columns API)."""
    metrics: list[dict] = []

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_columns(n_or_spec):
        n = n_or_spec if isinstance(n_or_spec, int) else len(n_or_spec)
        return [_NullCtx() for _ in range(n)]

    def fake_metric(label, value, delta=None, delta_color="normal", **kw):
        metrics.append({"label": label, "value": value, "delta": delta})

    import src.web.leaderboard as lb
    monkeypatch.setattr(lb.st, "columns", fake_columns)
    monkeypatch.setattr(lb.st, "metric", fake_metric)
    return metrics


def _row(strategy="S", symbol="X", net_pnl=100.0,
         roi_pct=1.0, roi_pct_annualized=12.0):
    return {
        "strategy": strategy, "symbol": symbol,
        "net_pnl": net_pnl, "roi_pct": roi_pct,
        "roi_pct_annualized": roi_pct_annualized,
    }


# ============================================================
# Empty-frame fallback
# ============================================================

def test_empty_frame_renders_four_dashes(captured_metrics):
    render_headline(pd.DataFrame({
        "strategy": pd.Series(dtype="string"),
        "symbol": pd.Series(dtype="string"),
        "net_pnl": pd.Series(dtype="float64"),
        "roi_pct": pd.Series(dtype="float64"),
        "roi_pct_annualized": pd.Series(dtype="float64"),
    }), min_n=5)
    assert len(captured_metrics) == 4
    # Canonical label order
    assert [m["label"] for m in captured_metrics] == [
        "Top pair", "Overall win rate", "Total net P&L", "Ranked pairs",
    ]
    # Every value is the em-dash placeholder per §2.5
    assert all(m["value"] == "—" for m in captured_metrics)
    assert all("no data" in m["delta"] for m in captured_metrics)


# ============================================================
# Populated frame — real metrics
# ============================================================

def test_populated_frame_emits_four_cards_in_canonical_order(captured_metrics):
    """6 trades on one (strategy, symbol) pair, all winning at 20%/yr."""
    rows = [_row(net_pnl=100.0, roi_pct=1.0, roi_pct_annualized=20.0)] * 6
    render_headline(pd.DataFrame(rows), min_n=5)
    assert [m["label"] for m in captured_metrics] == [
        "Top pair", "Overall win rate", "Total net P&L", "Ranked pairs",
    ]


def test_top_pair_value_is_strategy_x_symbol(captured_metrics):
    rows = [_row(strategy="iron_condor", symbol="HDFCBANK",
                 net_pnl=500.0, roi_pct=2.0, roi_pct_annualized=24.0)] * 6
    render_headline(pd.DataFrame(rows), min_n=5)
    top_card = captured_metrics[0]
    assert top_card["value"] == "iron_condor × HDFCBANK"
    # Subtitle includes the median ann ROI with sign + /yr suffix
    assert "+24.0%/yr" in top_card["delta"] or "+24.0 %/yr" in top_card["delta"]


def test_win_rate_card_format_is_percentage(captured_metrics):
    """LOAD-BEARING naming rule: card labeled with 'rate' must show %.
    Catches the mockup-bug class where a rate would be displayed as
    a bare number."""
    # 4 winners, 2 losers → 66.7%
    rows = (
        [_row(net_pnl=100.0)] * 4 +
        [_row(net_pnl=-50.0)] * 2
    )
    render_headline(pd.DataFrame(rows), min_n=5)
    win_card = captured_metrics[1]
    assert win_card["label"] == "Overall win rate"
    assert "%" in win_card["value"]
    # Hand-derived: 4/6 = 66.7%
    assert win_card["value"] == "66.7%"
    assert "4 of 6" in win_card["delta"]


def test_total_pnl_card_format_is_rupees(captured_metrics):
    """LOAD-BEARING naming rule: card labeled 'P&L' must show ₹.
    Catches "AVG ROI ₹25.76L"-style label mixups by inverting it —
    we pin that a P&L label is ALWAYS rupees."""
    # 6 trades at ₹100k each → ₹6 L total
    rows = [_row(net_pnl=100_000.0)] * 6
    render_headline(pd.DataFrame(rows), min_n=5)
    pnl_card = captured_metrics[2]
    assert pnl_card["label"] == "Total net P&L"
    assert "₹" in pnl_card["value"]
    # 6 × ₹100,000 = ₹600,000 = ₹6.00 L
    assert pnl_card["value"] == "₹6.00 L"


def test_ranked_pairs_card_shows_eligible_over_total(captured_metrics):
    """LOAD-BEARING for the min_n transparency contract per SPECS
    §11.5: the headline surfaces how many pairs PASS vs how many
    total. Operator can't accidentally think the leaderboard shows
    everything if they see "3/15"."""
    # Two pairs: A (n=6, eligible at min_n=5) and B (n=2, not eligible)
    rows = (
        [_row(strategy="A", symbol="X", net_pnl=100.0)] * 6 +
        [_row(strategy="B", symbol="Y", net_pnl=50.0)] * 2
    )
    render_headline(pd.DataFrame(rows), min_n=5)
    ranked_card = captured_metrics[3]
    assert ranked_card["label"] == "Ranked pairs"
    assert ranked_card["value"] == "1/2"
    assert "min_n=5" in ranked_card["delta"]


def test_top_pair_dash_when_no_pair_passes_min_n(captured_metrics):
    """If filter leaves rows but ALL pairs are below min_n, the
    TOP PAIR card surfaces this honestly — does NOT promote a thin
    sample to rank=1."""
    # Single (S, X) pair with n=2, well below min_n=5
    rows = [_row(strategy="S", symbol="X", net_pnl=100.0,
                 roi_pct_annualized=999.0)] * 2
    render_headline(pd.DataFrame(rows), min_n=5)
    top_card = captured_metrics[0]
    assert top_card["value"] == "—"
    assert "min_n=5" in top_card["delta"]
    # But OTHER cards still report aggregate stats — total P&L is
    # still computable, win rate is still computable
    pnl_card = captured_metrics[2]
    assert pnl_card["value"] == "₹200"  # 2 × ₹100 = ₹200, sub-lakh


def test_nan_safety_in_aggregates(captured_metrics):
    """If somehow a NaN sneaks into the source (e.g. a leg with
    missing data slipped through), the headline strip should NOT
    render 'nan%' anywhere — format_pct + format_inr both return
    em-dash on NaN."""
    rows = [_row(net_pnl=float("nan"), roi_pct=float("nan"),
                 roi_pct_annualized=float("nan"))] * 6
    render_headline(pd.DataFrame(rows), min_n=5)
    # Render shouldn't crash; values may be —
    for m in captured_metrics:
        v = m["value"] or ""
        assert "nan" not in str(v).lower()
