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

from src.web.heatmap import render_headline, render_heatmaps


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


# ============================================================
# render_heatmaps — dual Plotly heatmaps
# ============================================================

@pytest.fixture
def captured_charts(monkeypatch):
    """Recorder for st.plotly_chart, st.info, st.caption, st.columns."""
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

    import src.web.heatmap as hm
    monkeypatch.setattr(hm.st, "columns", fake_columns)
    monkeypatch.setattr(hm.st, "plotly_chart", fake_plotly_chart)
    monkeypatch.setattr(hm.st, "info", fake_info)
    monkeypatch.setattr(hm.st, "caption", fake_caption)
    # render_empty calls st.info via empty_state
    import src.web.empty_state as es
    monkeypatch.setattr(es.st, "info", fake_info)
    return events


def test_heatmaps_render_two_plotly_charts(captured_charts):
    """3 entry × 2 exit, n=6 each → both panes render."""
    rows = []
    for e in (15, 10, 5):
        for x in (3, 1):
            for _ in range(6):
                rows.append(_row(entry=e, exit_=x, roi_pct_annualized=50.0))
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    charts = [e for e in captured_charts if e["kind"] == "plotly_chart"]
    assert len(charts) == 2  # value pane + density pane


def _first_color(trace) -> str:
    """Extract the rgb color string at the 0.0 stop of a Plotly trace's
    resolved colorscale tuple."""
    return trace.colorscale[0][1]


def _last_color(trace) -> str:
    return trace.colorscale[-1][1]


def test_value_pane_uses_diverging_rdylgn_colormap(captured_charts):
    """LOAD-BEARING per DESIGN_SPEC §2.3: value pane MUST use RdYlGn
    with zmid=0. A sequential colormap would mid-color first negatives
    on a later sweep — wrong honesty signal.

    Plotly resolves the "RdYlGn" string to an rgb tuple list at trace
    construction. Fingerprint check: 0.0 stop is red-ish, 1.0 stop is
    green-ish. Robust against future Plotly version changes that
    refine the exact rgb values."""
    rows = [_row(entry=e, exit_=x, roi_pct_annualized=50.0)
            for e in (15, 10) for x in (3, 1) for _ in range(6)]
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    value_fig = [e for e in captured_charts if e["kind"] == "plotly_chart"][0]["fig"]
    trace = value_fig.data[0]
    first_rgb = _first_color(trace).lower()
    last_rgb = _last_color(trace).lower()
    # RdYlGn first stop is red (high R, low G, low B)
    assert "rgb(165" in first_rgb or "rgb(255" in first_rgb, first_rgb
    # RdYlGn last stop is green (low R, high G, low B)
    assert "rgb(0," in last_rgb or "rgb(26," in last_rgb, last_rgb
    # zmid pinned at 0 — the diverging-around-breakeven anchor
    assert trace.zmid == 0


def test_density_pane_uses_sequential_blues(captured_charts):
    """LOAD-BEARING per DESIGN_SPEC §2.3: density pane uses sequential
    Blues; 0 = white, max = dark blue. Fingerprint on first/last rgb."""
    rows = [_row(entry=e, exit_=x, roi_pct_annualized=50.0)
            for e in (15, 10) for x in (3, 1) for _ in range(6)]
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    density_fig = [e for e in captured_charts if e["kind"] == "plotly_chart"][1]["fig"]
    trace = density_fig.data[0]
    first_rgb = _first_color(trace).lower()
    last_rgb = _last_color(trace).lower()
    # Blues first stop is near-white (very high all RGB)
    assert "rgb(247,251,255)" in first_rgb or "rgb(255" in first_rgb, first_rgb
    # Blues last stop is dark blue (low R, low G, high B)
    assert "rgb(8,48,107)" in last_rgb or "rgb(8" in last_rgb, last_rgb


def test_single_axis_empty_state(captured_charts):
    """LOAD-BEARING per DESIGN_SPEC §2.6: <2 offsets on either axis
    → heatmap_single_axis message, NO plotly chart rendered (a
    one-row "heatmap" isn't a heatmap)."""
    # 3 entries × 1 exit
    rows = [_row(entry=e, exit_=1, roi_pct_annualized=50.0)
            for e in (15, 10, 5) for _ in range(6)]
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    kinds = [e["kind"] for e in captured_charts]
    assert "info" in kinds
    assert "plotly_chart" not in kinds


def test_all_cells_masked_empty_state(captured_charts):
    """Every cell N < min_n → heatmap_all_masked message; no charts."""
    rows = []
    for e in (15, 10, 5):
        for x in (3, 1):
            for _ in range(2):  # N=2 per cell, below min_n=5
                rows.append(_row(entry=e, exit_=x, roi_pct_annualized=50.0))
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    kinds = [e["kind"] for e in captured_charts]
    assert "info" in kinds
    info_msg = next(e for e in captured_charts if e["kind"] == "info")["msg"]
    assert "min_n=5" in info_msg
    assert "plotly_chart" not in kinds


def test_cells_have_customdata_for_hover_tooltips(captured_charts):
    """LOAD-BEARING per DESIGN_SPEC §2.5: per-cell hover tooltips
    must compose (n_trades, win_rate, std, total_net_pnl, median).
    Customdata is the Plotly channel; verify it's populated and
    correctly aligned with each cell.

    After p6.5.cleanup: customdata is STRINGS (pre-formatted via
    format_inr / format_pct) so hover renders ₹X.XX L / Cr correctly
    via raw interpolation, NOT Plotly format specifiers (which can't
    do lakhs/crores). Zero-count cells render '—' universally."""
    # 2x2 grid, n=6 each, varied roi to make customdata distinguishable
    rows = []
    for e in (15, 10):
        for x in (3, 1):
            for _ in range(6):
                rows.append(_row(entry=e, exit_=x, net_pnl=100.0 * (e + x),
                                 roi_pct_annualized=10.0 * (e + x)))
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    value_fig = [e for e in captured_charts if e["kind"] == "plotly_chart"][0]["fig"]
    trace = value_fig.data[0]
    cd = trace.customdata
    # Shape: (H, W, 5) — object dtype (strings)
    assert cd.shape == (2, 2, 5)
    # All visible cells have N=6 (rendered as "6" string)
    assert (cd[:, :, 0] == "6").all()
    # All winning trades → win_rate = 100% (rendered as "100.0%" string)
    assert (cd[:, :, 1] == "100.0%").all()


def test_hover_template_includes_all_load_bearing_fields(captured_charts):
    """The hovertemplate string must reference every key field per
    DESIGN_SPEC §2.5. Pin the field set so a future template edit
    doesn't drop "N" or "Std" silently.

    After p6.5.cleanup: currency/percent SYMBOLS now come from the
    pre-formatted customdata strings, not from the template format
    specifiers. So the template no longer contains ₹/% literals —
    the formatted strings interpolated via %{customdata[N]} do."""
    rows = [_row(entry=e, exit_=x, roi_pct_annualized=50.0)
            for e in (15, 10) for x in (3, 1) for _ in range(6)]
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    value_fig = [e for e in captured_charts if e["kind"] == "plotly_chart"][0]["fig"]
    trace = value_fig.data[0]
    tmpl = trace.hovertemplate
    # Required field labels per §2.5
    assert "Median ROI/yr" in tmpl
    assert "N:" in tmpl
    assert "Win rate" in tmpl
    assert "Std ROI/yr" in tmpl
    assert "Net P&L" in tmpl
    # Currency / percent symbols now live inside the customdata
    # strings — check at least one cell's pre-formatted Net P&L
    # carries the rupee glyph.
    cd = trace.customdata
    sample_pnl = cd[0][0][3]  # first cell's Net P&L string
    assert "₹" in sample_pnl
    # Win-rate cell carries %
    sample_win = cd[0][0][1]
    assert "%" in sample_win


def test_density_pane_hover_references_value_via_customdata(captured_charts):
    """Density pane shows N as the main z; hover should ALSO surface
    the cell's median ROI so the operator doesn't need to switch
    panes."""
    rows = [_row(entry=e, exit_=x, roi_pct_annualized=42.0)
            for e in (15, 10) for x in (3, 1) for _ in range(6)]
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    density_fig = [e for e in captured_charts if e["kind"] == "plotly_chart"][1]["fig"]
    tmpl = density_fig.data[0].hovertemplate
    assert "N:" in tmpl
    assert "Median ROI/yr" in tmpl  # via customdata[4]
    assert "Win rate" in tmpl       # via customdata[1]


def test_partial_mask_caption_surfaces_count(captured_charts):
    """Some cells visible, some masked → both charts render AND a
    caption tells the operator HOW MANY cells were masked."""
    rows = []
    # 2x2 grid: (15,1) and (15,3) have N=6 (visible); (10,1) and (10,3)
    # have N=2 (masked from value pane).
    for x in (1, 3):
        for _ in range(6):
            rows.append(_row(entry=15, exit_=x, roi_pct_annualized=50.0))
        for _ in range(2):
            rows.append(_row(entry=10, exit_=x, roi_pct_annualized=50.0))
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    charts = [e for e in captured_charts if e["kind"] == "plotly_chart"]
    captions = [e for e in captured_charts if e["kind"] == "caption"]
    assert len(charts) == 2  # both panes
    # Two captions: the always-present std-bias note + the partial-mask
    # diagnostic. The mask-count caption is the load-bearing one here.
    mask_caps = [c for c in captions if "masked" in c["msg"]]
    assert len(mask_caps) == 1
    assert "min_n=5" in mask_caps[0]["msg"]


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
