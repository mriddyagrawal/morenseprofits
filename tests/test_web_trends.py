"""Tests for src.web.trends — Phase 6.4 headline strip.

DESIGN_SPEC §2.5 Trends row. 4 cards: BEST MONTH, WORST MONTH,
TIGHTEST MONTH STD, LATEST YEAR ROI.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.web.trends import render_headline, render_yoy, render_yoy_n


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

    import src.web.trends as tr
    monkeypatch.setattr(tr.st, "columns", fake_columns)
    monkeypatch.setattr(tr.st, "metric", fake_metric)
    return metrics


def _row(strategy="S", symbol="X", year=2024, month=1,
         net_pnl=100.0, roi_pct=1.0, roi_pct_annualized=12.0):
    return {
        "strategy": strategy, "symbol": symbol,
        "expiry": pd.Timestamp(f"{year}-{month:02d}-15"),
        "entry_offset_td": 15, "exit_offset_td": 1,
        "net_pnl": net_pnl, "roi_pct": roi_pct,
        "roi_pct_annualized": roi_pct_annualized,
    }


# ============================================================
# Empty paths
# ============================================================

def test_empty_df_renders_four_dashes(captured_metrics):
    render_headline(pd.DataFrame({
        "strategy": pd.Series(dtype="string"),
        "symbol": pd.Series(dtype="string"),
        "expiry": pd.Series(dtype="datetime64[us]"),
        "entry_offset_td": pd.Series(dtype="int64"),
        "exit_offset_td": pd.Series(dtype="int64"),
        "net_pnl": pd.Series(dtype="float64"),
        "roi_pct": pd.Series(dtype="float64"),
        "roi_pct_annualized": pd.Series(dtype="float64"),
    }), strategy=None, symbol=None, min_n=5)
    assert len(captured_metrics) == 4
    assert [m["label"] for m in captured_metrics] == [
        "Best month", "Worst month", "Tightest month std",
        "Latest year ROI",
    ]
    assert all(m["value"] == "—" for m in captured_metrics)


def test_no_trades_for_selected_pair_renders_dashes(captured_metrics):
    """Selector picked a pair but the filtered df has no rows for it."""
    rows = [_row(strategy="OTHER", symbol="X")] * 6
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    assert all(m["value"] == "—" for m in captured_metrics)
    assert any("no trades for S × X" in m["delta"] for m in captured_metrics)


# ============================================================
# Populated paths — hand-derived month/year aggregates
# ============================================================

def test_best_and_worst_month_identified(captured_metrics):
    """Jan is best (50%/yr), Mar is worst (-20%/yr). Each month
    has N=6 trades (above min_n=5)."""
    rows = (
        [_row(year=2024, month=1, roi_pct_annualized=50.0)] * 6 +
        [_row(year=2024, month=2, roi_pct_annualized=20.0)] * 6 +
        [_row(year=2024, month=3, roi_pct_annualized=-20.0)] * 6
    )
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    best = captured_metrics[0]
    worst = captured_metrics[1]
    assert "+50.0%/yr" in best["value"]
    assert "month 1" in best["delta"]
    assert "-20.0%/yr" in worst["value"]
    assert "month 3" in worst["delta"]


def test_tightest_month_std_card_identifies_lowest_std(captured_metrics):
    """Month with the smallest std_roi_pct_annualized = tightest."""
    rows = (
        # month 1: 6 identical trades at 30%/yr → std=0
        [_row(year=2024, month=1, roi_pct_annualized=30.0)] * 6 +
        # month 2: varied trades → larger std
        [_row(year=2024, month=2, roi_pct_annualized=10.0)] * 3 +
        [_row(year=2024, month=2, roi_pct_annualized=50.0)] * 3
    )
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    tightest = captured_metrics[2]
    # Month 1's std = 0 → "±0.0%/yr"; subtitle names month 1
    assert "±0.0%/yr" in tightest["value"]
    assert "month 1" in tightest["delta"]
    assert "consistent" in tightest["delta"].lower()


def test_latest_year_roi_with_prior_year_delta(captured_metrics):
    """2024 latest year, prior was 2023 — subtitle shows "vs 2023:
    +X.X pp" (percentage points delta)."""
    rows = (
        # 2023: median 20%/yr
        [_row(year=2023, month=1, roi_pct_annualized=20.0)] * 6 +
        # 2024: median 50%/yr → +30 pp vs 2023
        [_row(year=2024, month=1, roi_pct_annualized=50.0)] * 6
    )
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    latest = captured_metrics[3]
    assert "+50.0%/yr" in latest["value"]
    assert "2024" in latest["delta"]
    assert "vs 2023" in latest["delta"]
    assert "+30.0 pp" in latest["delta"]


def test_latest_year_card_single_year_omits_delta(captured_metrics):
    """Only one eligible year → "no prior year for delta" subtitle.
    NEVER a fake +0 pp."""
    rows = [_row(year=2024, month=1, roi_pct_annualized=25.0)] * 6
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    latest = captured_metrics[3]
    assert "+25.0%/yr" in latest["value"]
    assert "no prior year" in latest["delta"]


def test_all_months_below_min_n_dashes_for_month_cards(captured_metrics):
    """Every month has N < min_n → best/worst/tightest say so; the
    yearly card may still render IF year-level n ≥ min_n."""
    rows = (
        # 3 trades in month 1 (below min_n=5)
        [_row(year=2024, month=1, roi_pct_annualized=50.0)] * 3 +
        [_row(year=2024, month=2, roi_pct_annualized=10.0)] * 2
        # Total across months = 5 → year-level passes min_n=5
    )
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    # Best/Worst/Tightest dashed
    for m in captured_metrics[:3]:
        assert m["value"] == "—"
        assert "N ≥ 5" in m["delta"] or "N >= 5" in m["delta"]
    # Latest year populated (year-level N=5 passes)
    latest = captured_metrics[3]
    assert latest["value"] != "—"
    assert "2024" in latest["delta"]


# ============================================================
# render_yoy — line chart of median ROI over years
# ============================================================

@pytest.fixture
def captured_charts(monkeypatch):
    events: list[dict] = []

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_columns(n_or_spec):
        n = n_or_spec if isinstance(n_or_spec, int) else len(n_or_spec)
        return [_NullCtx() for _ in range(n)]

    def fake_plotly_chart(fig, **kw):
        events.append({"kind": "plotly_chart", "fig": fig})

    def fake_info(msg, **_):
        events.append({"kind": "info", "msg": msg})

    def fake_caption(msg, **_):
        events.append({"kind": "caption", "msg": msg})

    import src.web.trends as tr
    monkeypatch.setattr(tr.st, "columns", fake_columns)
    monkeypatch.setattr(tr.st, "plotly_chart", fake_plotly_chart)
    monkeypatch.setattr(tr.st, "info", fake_info)
    monkeypatch.setattr(tr.st, "caption", fake_caption)
    import src.web.empty_state as es
    monkeypatch.setattr(es.st, "info", fake_info)
    return events


def test_yoy_single_year_renders_empty_state(captured_charts):
    """LOAD-BEARING per DESIGN_SPEC §2.6: <2 distinct eligible years
    → trends_yoy_single_year message; NO plotly chart rendered (a
    one-point "line" isn't a trend)."""
    # 6 trades all in 2024 → 1 eligible year only
    rows = [_row(year=2024, month=1, roi_pct_annualized=20.0)] * 6
    render_yoy(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    kinds = [e["kind"] for e in captured_charts]
    assert "info" in kinds
    assert "plotly_chart" not in kinds
    info = next(e for e in captured_charts if e["kind"] == "info")["msg"]
    assert "1 year" in info


def test_yoy_two_years_renders_line(captured_charts):
    """≥2 eligible years → real plotly_chart; line connects per-year
    medians."""
    rows = (
        [_row(year=2023, month=1, roi_pct_annualized=15.0)] * 6 +
        [_row(year=2024, month=1, roi_pct_annualized=30.0)] * 6
    )
    render_yoy(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    charts = [e for e in captured_charts if e["kind"] == "plotly_chart"]
    assert len(charts) == 1
    trace = charts[0]["fig"].data[0]
    # x = years in order; y = medians
    assert list(trace.x) == [2023, 2024]
    assert list(trace.y) == [15.0, 30.0]


def test_yoy_thin_years_suppressed(captured_charts):
    """Years with N < min_n excluded BEFORE the eligibility check.
    If only 1 year clears threshold, single-year empty-state fires."""
    rows = (
        # 2023 has N=2 (below min_n=5) — should be suppressed
        [_row(year=2023, month=1, roi_pct_annualized=99.0)] * 2 +
        [_row(year=2024, month=1, roi_pct_annualized=30.0)] * 6
    )
    render_yoy(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    kinds = [e["kind"] for e in captured_charts]
    # Only 2024 eligible → single year → empty-state, no chart
    assert "info" in kinds
    assert "plotly_chart" not in kinds


def test_yoy_hover_surfaces_n_per_year(captured_charts):
    """LOAD-BEARING per DESIGN_SPEC §10 user-journey step 4:
    hover MUST surface N alongside the median so operator distinguishes
    real drift from thin-sample noise."""
    rows = (
        [_row(year=2023, month=1, roi_pct_annualized=15.0)] * 6 +
        [_row(year=2024, month=1, roi_pct_annualized=30.0)] * 24
    )
    render_yoy(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    trace = next(e for e in captured_charts if e["kind"] == "plotly_chart")["fig"].data[0]
    # customdata carries N (Scatter wraps it as a tuple of rows)
    cd = trace.customdata
    assert len(cd) == 2
    assert "N:" in trace.hovertemplate
    assert "%{customdata[0]}" in trace.hovertemplate


def test_yoy_empty_df_or_missing_pair_routes_through_empty_state(captured_charts):
    """0 filtered rows OR no rows for selected pair → empty-state."""
    render_yoy(pd.DataFrame({
        "strategy": pd.Series(dtype="string"),
        "symbol": pd.Series(dtype="string"),
        "expiry": pd.Series(dtype="datetime64[us]"),
        "entry_offset_td": pd.Series(dtype="int64"),
        "exit_offset_td": pd.Series(dtype="int64"),
        "net_pnl": pd.Series(dtype="float64"),
        "roi_pct": pd.Series(dtype="float64"),
        "roi_pct_annualized": pd.Series(dtype="float64"),
    }), strategy=None, symbol=None, min_n=5)
    kinds = [e["kind"] for e in captured_charts]
    assert "info" in kinds
    assert "plotly_chart" not in kinds


# ============================================================
# render_yoy_n — sister chart (win-rate line + N bars dual-axis)
# ============================================================

def test_yoy_n_silent_on_single_year(captured_charts):
    """LOAD-BEARING: sister chart must NOT render anything on the
    single-year branch — the main yoy already showed the empty-state
    message; duplicating it via a second info box would be banner
    blindness. yoy_n stays silent here per DESIGN_SPEC §10 reading."""
    rows = [_row(year=2024, month=1, roi_pct_annualized=20.0)] * 6
    render_yoy_n(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    assert len(captured_charts) == 0


def test_yoy_n_silent_on_empty_or_missing_pair(captured_charts):
    """Same silent contract for empty df / missing pair."""
    render_yoy_n(pd.DataFrame({
        "strategy": pd.Series(dtype="string"),
        "symbol": pd.Series(dtype="string"),
        "expiry": pd.Series(dtype="datetime64[us]"),
        "entry_offset_td": pd.Series(dtype="int64"),
        "exit_offset_td": pd.Series(dtype="int64"),
        "net_pnl": pd.Series(dtype="float64"),
        "roi_pct": pd.Series(dtype="float64"),
        "roi_pct_annualized": pd.Series(dtype="float64"),
    }), strategy=None, symbol=None, min_n=5)
    assert len(captured_charts) == 0


def test_yoy_n_renders_two_traces_on_multi_year_data(captured_charts):
    """Two eligible years → exactly one Plotly figure with 2 traces:
    Bar (sample size) + Scatter (win rate)."""
    rows = (
        [_row(year=2023, month=1, roi_pct_annualized=15.0)] * 8 +
        [_row(year=2024, month=1, roi_pct_annualized=30.0)] * 12
    )
    render_yoy_n(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    charts = [e for e in captured_charts if e["kind"] == "plotly_chart"]
    assert len(charts) == 1
    fig = charts[0]["fig"]
    assert len(fig.data) == 2
    # Trace 0 = Bar (sample size); trace 1 = Scatter (win rate)
    assert fig.data[0].type == "bar"
    assert fig.data[1].type == "scatter"


def test_yoy_n_win_rate_yaxis_bounded_0_100(captured_charts):
    """LOAD-BEARING: win rate is a percentage bounded [0, 100]. Pin
    the y-axis range so cross-year comparisons read correctly — a
    Plotly auto-zoom on (95%, 100%) would mid-color a 4-pp difference
    as visually dramatic."""
    rows = (
        [_row(year=2023, month=1, roi_pct_annualized=15.0)] * 8 +
        [_row(year=2024, month=1, roi_pct_annualized=30.0)] * 12
    )
    render_yoy_n(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    fig = next(e for e in captured_charts if e["kind"] == "plotly_chart")["fig"]
    # Find the secondary y-axis range (yaxis2 in subplots layout)
    yaxis2 = fig.layout.yaxis2
    assert tuple(yaxis2.range) == (0, 100)


def test_yoy_n_bar_heights_match_sample_sizes(captured_charts):
    """The bars MUST plot the actual n_trades per eligible year —
    pin so a future refactor that swaps in mean_n_trades silently
    is caught."""
    rows = (
        [_row(year=2023, month=1, roi_pct_annualized=15.0)] * 8 +
        [_row(year=2024, month=1, roi_pct_annualized=30.0)] * 12
    )
    render_yoy_n(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    fig = next(e for e in captured_charts if e["kind"] == "plotly_chart")["fig"]
    bar = fig.data[0]
    assert list(bar.x) == [2023, 2024]
    assert list(bar.y) == [8, 12]


def test_naming_rule_pct_cards_have_percent_suffix(captured_metrics):
    """LOAD-BEARING §2.5: best/worst/latest values end in % or %/yr."""
    rows = [_row(year=2024, month=1, roi_pct_annualized=42.0)] * 6
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    for m in captured_metrics:
        if m["value"] != "—":
            assert "%" in m["value"]
            assert "₹" not in m["value"]
