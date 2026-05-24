"""Tests for src.web.heatmap — headline strip (Phase 6.3.headline).

Same monkeypatch pattern as test_web_leaderboard: replace st.metric /
st.columns / st.selectbox with recorders and verify card values.

Load-bearing per DESIGN_SPEC §2.5 Heatmap row:
  - BEST CELL value matches pivot_window.max().max() post-mask
  - WORST CELL value matches pivot_window.min().min() post-mask
  - MEDIAN CELL value matches pivot_window.stack().median()
  - subtitle for best/worst names the (entry, exit) coordinates
  - subtitle for median names the visible-cell count
  - all 3 cards "—" when every cell masked out at min_n
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.web.heatmap import render_headline


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

    import src.web.heatmap as hm
    monkeypatch.setattr(hm.st, "columns", fake_columns)
    monkeypatch.setattr(hm.st, "metric", fake_metric)
    return metrics


def _row(strategy="S", symbol="X", entry=15, exit_=1,
         net_pnl=0.0, roi_pct=0.0, roi_pct_annualized=0.0):
    return {
        "strategy": strategy, "symbol": symbol,
        "entry_offset_td": entry, "exit_offset_td": exit_,
        "net_pnl": net_pnl, "roi_pct": roi_pct,
        "roi_pct_annualized": roi_pct_annualized,
    }


# ============================================================
# Empty / sentinel paths
# ============================================================

def test_empty_df_renders_three_dashes(captured_metrics):
    render_headline(pd.DataFrame({
        "strategy": pd.Series(dtype="string"),
        "symbol": pd.Series(dtype="string"),
        "entry_offset_td": pd.Series(dtype="int64"),
        "exit_offset_td": pd.Series(dtype="int64"),
        "net_pnl": pd.Series(dtype="float64"),
        "roi_pct": pd.Series(dtype="float64"),
        "roi_pct_annualized": pd.Series(dtype="float64"),
    }), strategy=None, symbol=None, min_n=5)
    assert [m["label"] for m in captured_metrics] == [
        "Best cell", "Worst cell", "Median cell",
    ]
    assert all(m["value"] == "—" for m in captured_metrics)
    assert all("no data" in m["delta"] for m in captured_metrics)


def test_none_strategy_or_symbol_renders_dashes(captured_metrics):
    """Selector returned None even though df has rows — still dashes
    (this branch happens when the data was loaded but selector hasn't
    been clicked yet)."""
    rows = [_row()] * 6
    render_headline(pd.DataFrame(rows), strategy=None, symbol="X", min_n=5)
    assert all(m["value"] == "—" for m in captured_metrics)


# ============================================================
# Populated paths
# ============================================================

def test_populated_3x2_cells_pinpoints_best_worst_median(captured_metrics):
    """3 entry offsets × 2 exit offsets = 6 cells, 6 trades each so
    every cell clears min_n=5. Hand-derive expected best / worst /
    median from a known matrix."""
    rows = []
    # (entry, exit) → roi_pct_annualized values:
    #   (15, 1) → 100.0  ← best
    #   (15, 3) → 50.0
    #   (10, 1) → 75.0
    #   (10, 3) → 25.0
    #   (5,  1) → 10.0   ← worst
    #   (5,  3) → 40.0
    grid = {
        (15, 1): 100.0,
        (15, 3): 50.0,
        (10, 1): 75.0,
        (10, 3): 25.0,
        (5, 1): 10.0,
        (5, 3): 40.0,
    }
    for (e, x), roi in grid.items():
        for _ in range(6):  # n=6 per cell, above min_n=5
            rows.append(_row(entry=e, exit_=x, roi_pct_annualized=roi))

    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    best = captured_metrics[0]
    worst = captured_metrics[1]
    median = captured_metrics[2]

    # BEST = 100% at (15, 1)
    assert "+100.0%/yr" in best["value"]
    assert "(entry T-15, exit T-1)" in best["delta"]

    # WORST = 10% at (5, 1)
    assert "+10.0%/yr" in worst["value"]
    assert "(entry T-5, exit T-1)" in worst["delta"]

    # MEDIAN = median of [100, 50, 75, 25, 10, 40] = 45
    assert "+45.0%/yr" in median["value"]
    assert "across 6 visible cell(s)" in median["delta"]


def test_all_cells_masked_at_high_min_n(captured_metrics):
    """LOAD-BEARING per DESIGN_SPEC §2.6: when every cell has fewer
    than min_n trades, headline cards say so explicitly rather than
    rendering a misleading max() over essentially-empty data."""
    rows = [_row(entry=15, exit_=1, roi_pct_annualized=100.0)] * 3
    rows += [_row(entry=10, exit_=1, roi_pct_annualized=50.0)] * 2
    # 3 + 2 = 5 trades total, 2 cells of N={3, 2}; min_n=10 masks both
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=10)
    for m in captured_metrics:
        assert m["value"] == "—"
        assert "min_n=10" in m["delta"]


def test_negative_roi_signs_render_correctly(captured_metrics):
    """Best can be negative (every-cell losses); worst can be more
    negative. Sign discipline pinned."""
    rows = (
        [_row(entry=15, exit_=1, roi_pct_annualized=-50.0)] * 6 +
        [_row(entry=10, exit_=1, roi_pct_annualized=-100.0)] * 6
    )
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    best = captured_metrics[0]
    worst = captured_metrics[1]
    # Best = less-bad = -50
    assert "-50.0%/yr" in best["value"]
    # Worst = -100
    assert "-100.0%/yr" in worst["value"]


def test_naming_rule_values_have_percent_suffix(captured_metrics):
    """LOAD-BEARING §2.5 naming rule: card values for percentages
    MUST end in % or %/yr. Anti-mockup-bug (rupees mislabeled etc.)."""
    rows = [_row(entry=15, exit_=1, roi_pct_annualized=42.0)] * 6
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    for m in captured_metrics:
        if m["value"] != "—":
            assert "%" in m["value"]
            # Bare "₹" should never appear in a percentage card
            assert "₹" not in m["value"]
