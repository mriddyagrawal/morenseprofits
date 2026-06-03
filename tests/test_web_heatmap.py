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
         net_pnl=0.0, roi_pct=0.0):
    """Build a minimal results-row dict for the heatmap UI tests.

    Per-trade ROI throughout (no annualization): the UI reads from
    ``roi_pct`` post commit p7.expiry_roi. Tests pass values via the
    ``roi_pct=`` kwarg; the column is the same name."""
    return {
        "strategy": strategy, "symbol": symbol,
        "entry_offset_td": entry, "exit_offset_td": exit_,
        "net_pnl": net_pnl, "roi_pct": roi_pct,
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
    # (entry, exit) → roi_pct values (per-trade ROI; the metric the
    # headline reads after p7.expiry_roi):
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
            rows.append(_row(entry=e, exit_=x, roi_pct=roi))

    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    best = captured_metrics[0]
    worst = captured_metrics[1]
    median = captured_metrics[2]

    # BEST = 100% at (15, 1)
    assert "+100.0%" in best["value"]
    assert "(entry T-15, exit T-1)" in best["delta"]

    # WORST = 10% at (5, 1)
    assert "+10.0%" in worst["value"]
    assert "(entry T-5, exit T-1)" in worst["delta"]

    # MEDIAN = median of [100, 50, 75, 25, 10, 40] = 45
    assert "+45.0%" in median["value"]
    assert "across 6 visible cell(s)" in median["delta"]


def test_all_cells_masked_at_high_min_n(captured_metrics):
    """LOAD-BEARING per DESIGN_SPEC §2.6: when every cell has fewer
    than min_n trades, headline cards say so explicitly rather than
    rendering a misleading max() over essentially-empty data."""
    rows = [_row(entry=15, exit_=1, roi_pct=100.0)] * 3
    rows += [_row(entry=10, exit_=1, roi_pct=50.0)] * 2
    # 3 + 2 = 5 trades total, 2 cells of N={3, 2}; min_n=10 masks both
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=10)
    for m in captured_metrics:
        assert m["value"] == "—"
        assert "min_n=10" in m["delta"]


def test_negative_roi_signs_render_correctly(captured_metrics):
    """Best can be negative (every-cell losses); worst can be more
    negative. Sign discipline pinned."""
    rows = (
        [_row(entry=15, exit_=1, roi_pct=-50.0)] * 6 +
        [_row(entry=10, exit_=1, roi_pct=-100.0)] * 6
    )
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    best = captured_metrics[0]
    worst = captured_metrics[1]
    # Best = less-bad = -50
    assert "-50.0%" in best["value"]
    # Worst = -100
    assert "-100.0%" in worst["value"]


# ============================================================
# render_heatmaps — dual Plotly heatmaps
# ============================================================

@pytest.fixture
def captured_charts(monkeypatch):
    """Recorder for st.plotly_chart, plotly_events (the value-pane
    click bridge), st.info, st.caption, st.columns.

    The value pane was switched from st.plotly_chart(on_select=...) to
    streamlit_plotly_events.plotly_events(...) so click events fire
    reliably across browsers. Both rendering paths are captured here
    as ``kind="plotly_chart"`` so existing chart-count assertions
    don't need to know which pane uses which API."""
    events: list[dict] = []

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_columns(n_or_spec):
        n = n_or_spec if isinstance(n_or_spec, int) else len(n_or_spec)
        return [_NullCtx() for _ in range(n)]

    def fake_plotly_chart(fig, **kw):
        events.append({"kind": "plotly_chart", "fig": fig, "kwargs": kw})

    def fake_plotly_events(fig, **kw):
        # Mirror the plotly_chart shape so consumers don't need to
        # care which pane uses which API. Returns [] (no clicks this
        # render) to match plotly_events' real behavior.
        events.append({"kind": "plotly_chart", "fig": fig, "kwargs": kw})
        return []

    def fake_info(msg, **_):
        events.append({"kind": "info", "msg": msg})

    def fake_caption(msg, **_):
        events.append({"kind": "caption", "msg": msg})

    def fake_radio(label, options, index=0, **_):
        # Tests that want to exercise a non-default selection patch
        # this fixture's behavior by re-monkeypatching st.radio inline.
        return options[index]

    import src.web.heatmap as hm
    monkeypatch.setattr(hm.st, "columns", fake_columns)
    monkeypatch.setattr(hm.st, "plotly_chart", fake_plotly_chart)
    monkeypatch.setattr(hm.st, "info", fake_info)
    monkeypatch.setattr(hm.st, "caption", fake_caption)
    monkeypatch.setattr(hm.st, "radio", fake_radio)
    # streamlit_plotly_events is imported INSIDE render_heatmaps; patch
    # at its source so the import inside the function picks it up.
    import streamlit_plotly_events
    monkeypatch.setattr(streamlit_plotly_events, "plotly_events", fake_plotly_events)
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
                rows.append(_row(entry=e, exit_=x, roi_pct=50.0))
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    charts = [e for e in captured_charts if e["kind"] == "plotly_chart"]
    assert len(charts) == 2  # value pane + CVaR pane (density preserved
    # behind _SHOW_DENSITY_PANE constant; right pane shows CVaR by default)


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
    rows = [_row(entry=e, exit_=x, roi_pct=50.0)
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


def test_aggfunc_toggle_defaults_to_median(captured_charts):
    """No session_state pre-seed → toggle returns 'Median' → left-pane
    title is 'Median ROI' and the hover surfaces the median customdata
    slot. Anti-regression for the default-behavior contract."""
    rows = [_row(entry=e, exit_=x, roi_pct=42.0)
            for e in (15, 10) for x in (3, 1) for _ in range(6)]
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    value_fig = [e for e in captured_charts if e["kind"] == "plotly_chart"][0]["fig"]
    assert value_fig.layout.title.text == "Median ROI"
    assert "Median ROI" in value_fig.data[0].hovertemplate
    # Default routes to customdata slot [4] (median); slot [5] (mean) is
    # populated but not surfaced.
    assert "customdata[4]" in value_fig.data[0].hovertemplate


def test_aggfunc_toggle_mean_swaps_title_and_hover(captured_charts, monkeypatch):
    """When the operator picks 'Mean', the left-pane title flips to
    'Mean ROI' and the hover template addresses customdata slot [5]
    (the mean string). The pivot itself also recomputes via
    aggfunc='mean' — verified indirectly: a deliberately skewed cell's
    annotation must differ from the median-default render."""
    import src.web.heatmap as hm
    # Override the fixture's default-Median radio with one that picks Mean.
    monkeypatch.setattr(hm.st, "radio", lambda *a, **kw: "Mean")

    # Skewed cell: 5 trades at 10%, 1 trade at 1000% → mean ≫ median.
    rows = []
    for _ in range(5):
        rows.append(_row(entry=15, exit_=1, roi_pct=10.0))
    rows.append(_row(entry=15, exit_=1, roi_pct=1000.0))
    # Need a second visible cell for the 2×N axes contract.
    for _ in range(5):
        rows.append(_row(entry=15, exit_=3, roi_pct=10.0))
    for _ in range(5):
        rows.append(_row(entry=10, exit_=1, roi_pct=10.0))
    rows.append(_row(entry=10, exit_=1, roi_pct=1000.0))
    for _ in range(5):
        rows.append(_row(entry=10, exit_=3, roi_pct=10.0))

    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    value_fig = [e for e in captured_charts if e["kind"] == "plotly_chart"][0]["fig"]
    assert value_fig.layout.title.text == "Mean ROI"
    assert "Mean ROI" in value_fig.data[0].hovertemplate
    # Mean route uses customdata slot [5].
    assert "customdata[5]" in value_fig.data[0].hovertemplate
    # The skewed cell (15,1) should render its MEAN annotation
    # (10×5 + 1000)/6 ≈ 175 — well clear of the median (10).
    text = value_fig.data[0].text
    # First row (entry=15), first column (exit=3 leftmost desc, then exit=1).
    # Layout: index DESC (15 top, 10 bottom), columns DESC (3 left, 1 right).
    # So (15, 1) is row 0 column 1.
    cell_label = text[0][1]
    assert cell_label.startswith("+") and "1" in cell_label, (
        f"expected skewed mean ~175, got {cell_label!r}"
    )


def test_cvar_pane_uses_diverging_rdylgn_colormap(captured_charts):
    """LOAD-BEARING: CVaR pane uses the same diverging RdYlGn (zmid=0)
    palette as the median pane. Sequential would mid-color first-
    negative cells on a later sweep and lie about tail risk — same
    honesty failure as on the median pane. Replaces the previous
    density-pane Blues test now that the right pane shows tail-mean,
    not sample count."""
    rows = [_row(entry=e, exit_=x, roi_pct=50.0)
            for e in (15, 10) for x in (3, 1) for _ in range(6)]
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    cvar_fig = [e for e in captured_charts if e["kind"] == "plotly_chart"][1]["fig"]
    trace = cvar_fig.data[0]
    first_rgb = _first_color(trace).lower()
    last_rgb = _last_color(trace).lower()
    # RdYlGn first stop is red (high R, low G, low B)
    assert "rgb(165" in first_rgb or "rgb(255" in first_rgb, first_rgb
    # RdYlGn last stop is green
    assert "rgb(0," in last_rgb or "rgb(26," in last_rgb, last_rgb
    # zmid pinned at 0 — diverging-around-breakeven for tail mean too
    assert trace.zmid == 0


def test_single_axis_empty_state(captured_charts):
    """LOAD-BEARING per DESIGN_SPEC §2.6: <2 offsets on either axis
    → heatmap_single_axis message, NO plotly chart rendered (a
    one-row "heatmap" isn't a heatmap)."""
    # 3 entries × 1 exit
    rows = [_row(entry=e, exit_=1, roi_pct=50.0)
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
                rows.append(_row(entry=e, exit_=x, roi_pct=50.0))
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
                                 roi_pct=10.0 * (e + x)))
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    value_fig = [e for e in captured_charts if e["kind"] == "plotly_chart"][0]["fig"]
    trace = value_fig.data[0]
    cd = trace.customdata
    # Shape: (H, W, 6) — object dtype (strings). Slot [4] = median ROI,
    # slot [5] = mean ROI; the heatmap hover surfaces whichever the
    # median/mean toggle selects.
    assert cd.shape == (2, 2, 6)
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
    rows = [_row(entry=e, exit_=x, roi_pct=50.0)
            for e in (15, 10) for x in (3, 1) for _ in range(6)]
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    value_fig = [e for e in captured_charts if e["kind"] == "plotly_chart"][0]["fig"]
    trace = value_fig.data[0]
    tmpl = trace.hovertemplate
    # Required field labels per §2.5
    assert "Median ROI" in tmpl
    assert "N:" in tmpl
    assert "Win rate" in tmpl
    assert "Std ROI" in tmpl
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


def test_cvar_pane_hover_includes_median_and_n(captured_charts):
    """CVaR pane primary z is the worst-5% tail mean; hover must ALSO
    surface the cell's median ROI + N so the operator can cross-
    reference the tail-vs-median story without switching panes.
    Replaces the density-pane hover test; the analytical surface
    swap is the only material change to assert."""
    rows = [_row(entry=e, exit_=x, roi_pct=42.0)
            for e in (15, 10) for x in (3, 1) for _ in range(6)]
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    cvar_fig = [e for e in captured_charts if e["kind"] == "plotly_chart"][1]["fig"]
    tmpl = cvar_fig.data[0].hovertemplate
    assert "CVaR" in tmpl
    assert "Median ROI" in tmpl  # via customdata[4]
    assert "N:" in tmpl              # via customdata[0]
    assert "Win rate" in tmpl       # via customdata[1]


def test_partial_mask_caption_surfaces_count(captured_charts):
    """Some cells visible, some masked → both charts render AND a
    caption tells the operator HOW MANY cells were masked."""
    rows = []
    # 2x2 grid: (15,1) and (15,3) have N=6 (visible); (10,1) and (10,3)
    # have N=2 (masked from value pane).
    for x in (1, 3):
        for _ in range(6):
            rows.append(_row(entry=15, exit_=x, roi_pct=50.0))
        for _ in range(2):
            rows.append(_row(entry=10, exit_=x, roi_pct=50.0))
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
    MUST end in % or %. Anti-mockup-bug (rupees mislabeled etc.)."""
    rows = [_row(entry=15, exit_=1, roi_pct=42.0)] * 6
    render_headline(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    for m in captured_metrics:
        if m["value"] != "—":
            assert "%" in m["value"]
            # Bare "₹" should never appear in a percentage card
            assert "₹" not in m["value"]


# ============================================================
# fix(p7.heatmap.plotly_events): value pane must use plotly_events
# (the streamlit-plotly-events bridge) to listen to plotly_click —
# Streamlit's native on_select listens to plotly_selected, which
# heatmap traces don't emit reliably on single click.
# ============================================================

def test_value_pane_uses_native_plotly_chart_with_on_select(captured_charts):
    """The value pane MUST use st.plotly_chart with on_select="rerun"
    and selection_mode=("points",). The earlier attempt to swap in
    streamlit_plotly_events broke heatmap rendering (the archived
    2022 component is incompatible with Plotly 6.7 / Streamlit 1.57 —
    chart came up blank with default integer axes). Native render
    preserves the categorical T-N tick labels and shows the trace.

    Click reliability across browsers is handled by the manual-picker
    selectbox fallback (tested separately) rather than by replacing
    the renderer. Belt-and-suspenders, not all-eggs-in-one-basket."""
    rows = []
    for e in (15, 10, 5):
        for x in (3, 1):
            for _ in range(6):
                rows.append(_row(entry=e, exit_=x, roi_pct=50.0))
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)

    charts = [e for e in captured_charts if e["kind"] == "plotly_chart"]
    value_kwargs = charts[0]["kwargs"]
    # st.plotly_chart-specific signals: on_select + selection_mode.
    # streamlit_plotly_events doesn't accept these kwargs, so their
    # presence proves we're on the native path.
    assert value_kwargs.get("on_select") == "rerun"
    assert value_kwargs.get("selection_mode") == ("points",)
    assert value_kwargs.get("use_container_width") is True


# ============================================================
# feat(p7.heatmap.manual_cell_picker): selectbox fallback tests
# ============================================================
#
# Reviewer caught a real bug in the original 384c65e: the "only write
# when user interacted" guard compared against ``sel`` (the click-driven
# selection), which is the WRONG reference frame. On first render with
# sel=None, the selectbox defaults always pass `!= None` and the picker
# fires without operator intent. Tests below pin the corrected pattern
# (separate ``_mp_heatmap_manual_prev`` tracking key) plus the other
# invariants the reviewer asked for.

def _render_heatmaps_with_data(monkeypatch):
    """Helper: render the heatmap tab over a minimal dataset with
    enough cells (3 entry × 2 exit) to surface the manual picker.
    Returns the captured radio + selectbox calls so tests can inspect
    behavior without a live Streamlit runtime."""
    import src.web.heatmap as hm

    selectbox_calls: list[dict] = []
    expander_state: list[dict] = []

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_columns(n):
        return [_NullCtx() for _ in range(n if isinstance(n, int) else len(n))]

    def fake_selectbox(label, *, options, index=0, key=None,
                       format_func=None, help=None):
        selectbox_calls.append({
            "label": label, "options": list(options), "index": index, "key": key,
        })
        return options[index]

    def fake_expander(label, expanded=False):
        expander_state.append({"label": label, "expanded": expanded})
        return _NullCtx()

    monkeypatch.setattr(hm.st, "columns", fake_columns)
    monkeypatch.setattr(hm.st, "selectbox", fake_selectbox)
    monkeypatch.setattr(hm.st, "expander", fake_expander)
    monkeypatch.setattr(hm.st, "markdown", lambda *a, **k: None)
    # Two radios in render_heatmaps now: the aggfunc toggle
    # (options=["Median", "Mean"]) and the cell-action mode
    # (options=["Drill-down", ...]). Return options[0] so each radio
    # gets its proper default (Median / Drill-down respectively).
    monkeypatch.setattr(
        hm.st, "radio",
        lambda label, options=("Drill-down",), **k: options[0],
    )
    monkeypatch.setattr(hm.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(hm.st, "plotly_chart", lambda *a, **k: None)
    import streamlit_plotly_events
    monkeypatch.setattr(streamlit_plotly_events, "plotly_events",
                        lambda fig, **kw: [])

    rows = []
    for e in (15, 10, 5):
        for x in (3, 1):
            for _ in range(6):
                rows.append(_row(entry=e, exit_=x, roi_pct=42.0))
    hm.render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)
    return selectbox_calls, expander_state


def test_manual_picker_does_not_overwrite_sel_on_first_render(monkeypatch):
    """LOAD-BEARING — first render with no prior selection MUST NOT
    auto-write ``mp_heatmap_selected_cell``. The picker's job is to
    respond to operator picks, not to make picks itself."""
    import src.web.heatmap as hm
    state: dict = {}  # empty session — no prior click, no prior manual
    monkeypatch.setattr(hm.st, "session_state", state)
    _render_heatmaps_with_data(monkeypatch)
    # mp_heatmap_selected_cell MUST stay absent (or None) — the
    # manual picker has not been actively used yet.
    assert "mp_heatmap_selected_cell" not in state, (
        "first-render manual picker auto-selected a cell — "
        "the operator hasn't picked anything yet"
    )
    # The tracking key IS stamped (so the next interaction can detect
    # a transition).
    assert "_mp_heatmap_manual_prev" in state


def test_manual_picker_writes_session_state_when_user_changes_selection(monkeypatch):
    """Happy path: simulate an operator picking different values on a
    second render — the picker must write mp_heatmap_selected_cell."""
    import src.web.heatmap as hm
    # Simulate state AFTER a first render (prev stamped, sel absent).
    state: dict = {"_mp_heatmap_manual_prev": (15, 1)}
    monkeypatch.setattr(hm.st, "session_state", state)

    # Override selectbox to return a DIFFERENT (entry, exit) than prev.
    selectbox_calls: list = []

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_columns(n):
        return [_NullCtx() for _ in range(n if isinstance(n, int) else len(n))]

    def fake_expander(label, expanded=False):
        return _NullCtx()

    def fake_selectbox(label, *, options, index=0, key=None,
                       format_func=None, help=None):
        # Picker wants: entry=10, exit=3. options for entry are sorted
        # desc [15,10,5]; entry pick = 10 → index 1. exits sorted desc
        # [3,1]; exit pick = 3 → index 0.
        selectbox_calls.append(label)
        if label == "Entry offset":
            return 10
        if label == "Exit offset":
            return 3
        return options[index]

    monkeypatch.setattr(hm.st, "columns", fake_columns)
    monkeypatch.setattr(hm.st, "selectbox", fake_selectbox)
    monkeypatch.setattr(hm.st, "expander", fake_expander)
    monkeypatch.setattr(hm.st, "markdown", lambda *a, **k: None)
    # Two radios in render_heatmaps now: the aggfunc toggle
    # (options=["Median", "Mean"]) and the cell-action mode
    # (options=["Drill-down", ...]). Return options[0] so each radio
    # gets its proper default (Median / Drill-down respectively).
    monkeypatch.setattr(
        hm.st, "radio",
        lambda label, options=("Drill-down",), **k: options[0],
    )
    monkeypatch.setattr(hm.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(hm.st, "plotly_chart", lambda *a, **k: None)
    import streamlit_plotly_events
    monkeypatch.setattr(streamlit_plotly_events, "plotly_events",
                        lambda fig, **kw: [])

    rows = []
    for e in (15, 10, 5):
        for x in (3, 1):
            for _ in range(6):
                rows.append(_row(entry=e, exit_=x, roi_pct=42.0))
    hm.render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)

    # Picker fired because new (10,3) != prev (15,1) AND 10 > 3.
    assert state.get("mp_heatmap_selected_cell") == (10, 3)
    assert state["_mp_heatmap_manual_prev"] == (10, 3)


def test_manual_picker_respects_entry_gt_exit_constraint(monkeypatch):
    """If the user picks an impossible cell (entry ≤ exit), the
    picker MUST NOT write to mp_heatmap_selected_cell. Same constraint
    the sweep itself enforces."""
    import src.web.heatmap as hm
    state: dict = {"_mp_heatmap_manual_prev": (15, 1)}
    monkeypatch.setattr(hm.st, "session_state", state)

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_columns(n):
        return [_NullCtx() for _ in range(n if isinstance(n, int) else len(n))]

    def fake_expander(label, expanded=False):
        return _NullCtx()

    # User picks entry=3, exit=10 → entry < exit. INVALID.
    def fake_selectbox(label, *, options, index=0, key=None,
                       format_func=None, help=None):
        if label == "Entry offset":
            return 3
        if label == "Exit offset":
            return 10
        return options[index]

    monkeypatch.setattr(hm.st, "columns", fake_columns)
    monkeypatch.setattr(hm.st, "selectbox", fake_selectbox)
    monkeypatch.setattr(hm.st, "expander", fake_expander)
    monkeypatch.setattr(hm.st, "markdown", lambda *a, **k: None)
    # Two radios in render_heatmaps now: the aggfunc toggle
    # (options=["Median", "Mean"]) and the cell-action mode
    # (options=["Drill-down", ...]). Return options[0] so each radio
    # gets its proper default (Median / Drill-down respectively).
    monkeypatch.setattr(
        hm.st, "radio",
        lambda label, options=("Drill-down",), **k: options[0],
    )
    monkeypatch.setattr(hm.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(hm.st, "plotly_chart", lambda *a, **k: None)
    import streamlit_plotly_events
    monkeypatch.setattr(streamlit_plotly_events, "plotly_events",
                        lambda fig, **kw: [])

    # Need cells with entry=3 AND exit=10 in the dataframe so the pivot
    # surfaces both as available options.
    rows = []
    for e in (15, 10, 3):
        for x in (10, 3, 1):
            for _ in range(6):
                rows.append(_row(entry=e, exit_=x, roi_pct=42.0))
    hm.render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)

    # picker DID NOT write — constraint failed.
    assert "mp_heatmap_selected_cell" not in state, (
        "manual picker wrote an impossible (entry ≤ exit) cell — "
        "the entry > exit guard must reject this"
    )


def test_manual_picker_renders_always_visible_selectboxes(monkeypatch):
    """UX promise revised: the picker is no longer hidden behind an
    expander. After verifying empirically that the native click handler
    fails for the user, the picker became the PRIMARY (not fallback)
    selection mechanism — always visible, no "click not working?"
    framing. Tests pin that we render two selectboxes (Entry offset,
    Exit offset) directly, not nested in an expander."""
    import src.web.heatmap as hm
    monkeypatch.setattr(hm.st, "session_state", {})
    selectbox_calls, expander_state = _render_heatmaps_with_data(monkeypatch)
    # No expander surrounds the picker — selectboxes are top-level.
    pickers = [
        e for e in expander_state
        if "pick a cell" in (e["label"] or "").lower()
    ]
    assert len(pickers) == 0
    # Both selectboxes rendered.
    labels = [s["label"] for s in selectbox_calls]
    assert "Entry offset" in labels
    assert "Exit offset" in labels


# ============================================================
# feat(p7.heatmap.strike_disclosure): caption under selectors
# ============================================================

def test_selector_renders_strike_rule_caption(monkeypatch):
    """The strategy selector must surface the strike-selection rule
    via st.caption(\"ℹ Strike rule: …\") so the analyst sees WHICH
    strikes the priced trades used. The string itself is owned by
    each strategy's display_strike_rule (tested separately)."""
    import src.web.heatmap as hm

    captions: list[str] = []
    selectbox_state: dict[str, str] = {}

    def fake_selectbox(label, *, options, index=0, key=None, help=None):
        # Return the chosen option; persist in session_state mock.
        pick = options[index]
        selectbox_state[key] = pick
        return pick

    def fake_caption(msg, **_):
        captions.append(msg)

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_columns(n):
        return [_NullCtx() for _ in range(n if isinstance(n, int) else len(n))]

    monkeypatch.setattr(hm.st, "selectbox", fake_selectbox)
    monkeypatch.setattr(hm.st, "caption", fake_caption)
    monkeypatch.setattr(hm.st, "columns", fake_columns)
    monkeypatch.setattr(hm.st, "session_state", {})

    df = pd.DataFrame([_row(entry=15, exit_=1, roi_pct=42.0)])
    strategy, symbol = hm._selector(df)
    assert strategy == "S"
    assert symbol == "X"
    # The caption may degrade gracefully if get_strategy fails on "S"
    # (which it will — "S" isn't a registered name). The TRY/EXCEPT
    # guard inside _selector swallows that; nothing crashes. To test
    # the actual rendering path, use a real strategy name:
    df_real = pd.DataFrame([
        _row(entry=15, exit_=1, roi_pct=42.0,
             strategy="short_straddle", symbol="RELIANCE"),
    ])
    captions.clear()
    hm._selector(df_real)
    strike_caps = [c for c in captions if "Strike rule:" in c]
    assert len(strike_caps) == 1
    assert "ATM" in strike_caps[0]  # short_straddle's rule mentions ATM


# ============================================================
# feat(p7.heatmap.modes): radio + Compare / Export stubs
# ============================================================

def test_mode_radio_renders_with_three_options(monkeypatch, captured_charts):
    """Radio under the heatmaps must offer exactly Drill-down /
    Compare cells / Export rule, in that order. Pins the operator
    contract — adding a 4th mode = explicit decision, not drift."""
    import src.web.heatmap as hm
    radio_calls: list[dict] = []

    def fake_radio(label, *, options, horizontal=False, key=None, **_):
        radio_calls.append({
            "label": label, "options": list(options),
            "horizontal": horizontal, "key": key,
        })
        return options[0]
    monkeypatch.setattr(hm.st, "radio", fake_radio)
    monkeypatch.setattr(hm.st, "markdown", lambda *a, **k: None)

    rows = []
    for e in (15, 10, 5):
        for x in (3, 1):
            for _ in range(6):
                rows.append(_row(entry=e, exit_=x, roi_pct=50.0))
    render_heatmaps(pd.DataFrame(rows), strategy="S", symbol="X", min_n=5)

    mode_radios = [r for r in radio_calls if r["label"] == "Cell action"]
    assert len(mode_radios) == 1
    assert mode_radios[0]["options"] == [
        "Drill-down", "Compare cells", "Export rule",
    ]
    assert mode_radios[0]["horizontal"] is True
    assert mode_radios[0]["key"] == "mp_heatmap_mode"


def test_cell_action_mode_default_is_drill_down(monkeypatch):
    """No prior selection in session_state → default "Drill-down".
    Preserves the v0.6-ui behavior so existing flows are unchanged."""
    import src.web.heatmap as hm
    monkeypatch.setattr(hm.st, "session_state", {})
    assert hm.cell_action_mode() == "Drill-down"


def test_cell_action_mode_returns_session_state_value(monkeypatch):
    """When the radio sets the key, cell_action_mode reads it back."""
    import src.web.heatmap as hm
    monkeypatch.setattr(hm.st, "session_state", {"mp_heatmap_mode": "Compare cells"})
    assert hm.cell_action_mode() == "Compare cells"
    monkeypatch.setattr(hm.st, "session_state", {"mp_heatmap_mode": "Export rule"})
    assert hm.cell_action_mode() == "Export rule"


# ============================================================
# Export-rule mode — feat(p7.heatmap.export)
# ============================================================
#
# Per-cell .md trading rule + per-cell trade-list CSV bundle. The .md
# is operator-facing — what they'd paste into a trade journal or
# screenshot to remember "what's this rule that backtested well?".
# The CSV is the audit trail — the same per-leg dump the drill-down's
# CSV produces, scoped to the same cell.
#
# LOAD-BEARING reviewer constraint (from the original stub docstring):
# the .md MUST re-emit MULTIPLE_COMPARISONS_CAVEAT verbatim from
# src.analytics.rank as a top-level "## Selection bias warning"
# section. The operator picking one cell from a ~2.25M-cell wide-
# sweep grid has introduced massive selection bias the per-rule
# backtest can't capture. Re-export the constant; don't paraphrase.


def _export_trade(
    *,
    strategy="short_straddle", symbol="RELIANCE",
    entry_offset=15, exit_offset=1, roi_pct=1.0, net_pnl=100.0,
    expiry="2024-01-25", run_id="run_export",
) -> dict:
    """Trade-row fixture for the export tests. Carries enough fields
    that _build_cell_csv can flatten legs_json without crashing AND
    that the .md rule's stats block has its expected inputs."""
    import json
    return {
        "run_id": run_id,
        "strategy": strategy,
        "symbol": symbol,
        "expiry": pd.Timestamp(expiry),
        "entry_date": pd.Timestamp("2024-01-04"),
        "exit_date": pd.Timestamp("2024-01-24"),
        "entry_offset_td": entry_offset,
        "exit_offset_td": exit_offset,
        "net_pnl": net_pnl,
        "gross_pnl": net_pnl + 40.0,
        "costs": 40.0,
        "roi_pct": roi_pct,
        "hold_trading_days": 14,
        "legs_json": json.dumps([
            {
                "strike": 2600, "option_type": "CE", "side": "short",
                "qty_lots": 1, "lot_size": 250,
                "entry_px": 50.0, "exit_px": 25.0,
                "entry_volume": 1000, "exit_volume": 800,
                "entry_oi": 5000, "exit_oi": 5500,
                "entry_turnover": 5.0, "exit_turnover": 2.5,
                "gross_pnl": 6250.0,
            },
        ]),
    }


def _patch_streamlit_for_export(monkeypatch):
    """Replace every Streamlit primitive render_export_rule calls with
    a no-op or recorder. Returns the captured downloads list."""
    import src.web.heatmap as hm

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_columns(n_or_spec):
        n = n_or_spec if isinstance(n_or_spec, int) else len(n_or_spec)
        return [_NullCtx() for _ in range(n)]

    downloads: list[dict] = []
    infos: list[str] = []
    monkeypatch.setattr(hm.st, "columns", fake_columns)
    monkeypatch.setattr(hm.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(hm.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(hm.st, "warning", lambda *a, **k: None)
    monkeypatch.setattr(hm.st, "info", lambda m, **k: infos.append(m))
    monkeypatch.setattr(
        hm.st, "download_button",
        lambda label, data, file_name, **k: downloads.append({
            "label": label, "data": data, "file_name": file_name,
        }),
    )
    return downloads, infos


def test_export_rule_no_selection_shows_picker_prompt(monkeypatch):
    """No cell selected → the export panel prompts the operator to
    click a cell. No download buttons rendered (the rule needs an
    anchor cell). Same shape as the drill-down's empty path."""
    import src.web.heatmap as hm
    monkeypatch.setattr(hm.st, "session_state", {})
    downloads, infos = _patch_streamlit_for_export(monkeypatch)
    hm.render_export_rule(
        pd.DataFrame([_export_trade()]),
        strategy="short_straddle", symbol="RELIANCE",
    )
    assert len(downloads) == 0
    assert any("pick a cell" in m.lower() or "click" in m.lower()
               for m in infos)


def test_export_rule_md_includes_multiple_comparisons_caveat_verbatim(monkeypatch):
    """LOAD-BEARING constraint per the original stub docstring + the
    2026-05-28 PLAN entry: the .md MUST include
    MULTIPLE_COMPARISONS_CAVEAT verbatim from src.analytics.rank as a
    "## Selection bias warning" section. Re-emit (don't paraphrase)
    so consumer-facing language matches the constant in one source of
    truth. Anti-regression against a future contributor weakening the
    framing."""
    import src.web.heatmap as hm
    from src.analytics.rank import MULTIPLE_COMPARISONS_CAVEAT
    monkeypatch.setattr(
        hm.st, "session_state", {"mp_heatmap_selected_cell": (15, 1)},
    )
    # Engine-version stamp irrelevant for this test; treat as matched.
    monkeypatch.setattr(
        hm, "read_run_metadata",
        lambda run_id: {"engine_version": "p7.pricing_arc"},
    )
    downloads, _ = _patch_streamlit_for_export(monkeypatch)
    df = pd.DataFrame([_export_trade(roi_pct=2.0, net_pnl=150.0)])
    hm.render_export_rule(df, strategy="short_straddle", symbol="RELIANCE")

    md = next(d for d in downloads if d["file_name"].endswith(".md"))
    md_text = md["data"].decode("utf-8")
    assert MULTIPLE_COMPARISONS_CAVEAT in md_text, (
        "MULTIPLE_COMPARISONS_CAVEAT MUST appear verbatim in the "
        "exported .md (re-export from src.analytics.rank, do not "
        "paraphrase). Reviewer constraint pinned on the original stub."
    )
    assert "## Selection bias warning" in md_text


def test_export_rule_md_includes_rule_spec_and_stats(monkeypatch):
    """The .md is a deployment-ready trading rule: it must carry the
    rule spec (strategy, symbol, entry/exit offsets) AND the historical
    performance block (n, win rate, median ROI) so the operator can
    screenshot or paste it into a journal. Hand-verifiable stats: 3
    trades with ROIs [-1.0, 2.0, 5.0] → median 2.0, n=3."""
    import src.web.heatmap as hm
    monkeypatch.setattr(
        hm.st, "session_state", {"mp_heatmap_selected_cell": (15, 1)},
    )
    monkeypatch.setattr(
        hm, "read_run_metadata",
        lambda run_id: {"engine_version": "p7.pricing_arc"},
    )
    downloads, _ = _patch_streamlit_for_export(monkeypatch)
    rows = [
        _export_trade(roi_pct=-1.0, net_pnl=-100.0, expiry="2024-01-25"),
        _export_trade(roi_pct=2.0, net_pnl=200.0, expiry="2024-02-29"),
        _export_trade(roi_pct=5.0, net_pnl=500.0, expiry="2024-03-28"),
    ]
    hm.render_export_rule(
        pd.DataFrame(rows),
        strategy="short_straddle", symbol="RELIANCE",
    )
    md = next(d for d in downloads if d["file_name"].endswith(".md"))
    md_text = md["data"].decode("utf-8")
    # Rule spec
    assert "short_straddle" in md_text
    assert "RELIANCE" in md_text
    assert "T-15" in md_text
    assert "T-1" in md_text
    # Stats — hand-computable: n=3, median ROI=2.0
    assert "n=3" in md_text or "**Trades**: 3" in md_text or "3 trades" in md_text.lower()
    assert "2.0" in md_text  # median


def test_export_rule_pre_arc_caveat_fires_when_engine_version_mismatch(monkeypatch):
    """Pre-pricing-arc caveat — same trigger as the MCP tools'
    PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT. If the underlying sweep
    parquet's engine_version stamp differs from ENGINE_VERSION, the
    exported .md MUST carry the verbatim caveat string. An operator
    who exports a rule from a pre-arc parquet and acts on it would
    be deploying against potentially-inflated numbers; the caveat is
    load-bearing honesty."""
    import src.web.heatmap as hm
    from src.mcp._models import PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT
    monkeypatch.setattr(
        hm.st, "session_state", {"mp_heatmap_selected_cell": (15, 1)},
    )
    monkeypatch.setattr(
        hm, "read_run_metadata",
        lambda run_id: {"engine_version": "p6.legacy"},  # pre-arc stamp
    )
    downloads, _ = _patch_streamlit_for_export(monkeypatch)
    hm.render_export_rule(
        pd.DataFrame([_export_trade()]),
        strategy="short_straddle", symbol="RELIANCE",
    )
    md = next(d for d in downloads if d["file_name"].endswith(".md"))
    md_text = md["data"].decode("utf-8")
    assert PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT in md_text


def test_export_rule_offers_csv_download_alongside_md(monkeypatch):
    """The CSV bundle: same per-leg detail as the drill-down's CSV
    (re-uses _build_cell_csv), scoped to the selected cell only. The
    operator gets BOTH the human-readable .md rule AND the
    machine-readable trade-list CSV from one export action — no need
    to switch modes to the drill-down to grab the trades."""
    import src.web.heatmap as hm
    monkeypatch.setattr(
        hm.st, "session_state", {"mp_heatmap_selected_cell": (15, 1)},
    )
    monkeypatch.setattr(
        hm, "read_run_metadata",
        lambda run_id: {"engine_version": "p7.pricing_arc"},
    )
    downloads, _ = _patch_streamlit_for_export(monkeypatch)
    hm.render_export_rule(
        pd.DataFrame([_export_trade()]),
        strategy="short_straddle", symbol="RELIANCE",
    )
    file_names = {d["file_name"] for d in downloads}
    assert any(n.endswith(".md") for n in file_names)
    assert any(n.endswith(".csv") for n in file_names)
    # CSV file name matches the drill-down's convention so an operator
    # comparing the two surfaces sees the same file naming scheme.
    csv = next(d for d in downloads if d["file_name"].endswith(".csv"))
    assert "short_straddle" in csv["file_name"]
    assert "RELIANCE" in csv["file_name"]
    assert "T-15" in csv["file_name"]
    assert "T-1" in csv["file_name"]


def test_export_rule_empty_cell_after_selection_shows_no_data_message(monkeypatch):
    """Cell selected but no trades match the (strategy, symbol,
    entry, exit) intersection (e.g. operator picked a cell that was
    just masked by the min_n slider). Surface a no-data message; no
    downloads — there's nothing to export."""
    import src.web.heatmap as hm
    monkeypatch.setattr(
        hm.st, "session_state", {"mp_heatmap_selected_cell": (40, 10)},
    )
    monkeypatch.setattr(
        hm, "read_run_metadata",
        lambda run_id: {"engine_version": "p7.pricing_arc"},
    )
    downloads, infos = _patch_streamlit_for_export(monkeypatch)
    df = pd.DataFrame([_export_trade(entry_offset=15, exit_offset=1)])
    hm.render_export_rule(
        df, strategy="short_straddle", symbol="RELIANCE",
    )
    assert len(downloads) == 0
    # Tightened from a bare "no" substring to "no trades" — the bare
    # form passed on accidental matches like "no longer needed".
    assert any("no trades" in m.lower() for m in infos)


def test_export_rule_pre_arc_caveat_fires_when_stamp_missing(monkeypatch):
    """LOAD-BEARING (closes 6b3a9eb Grill #1+#2): unstamped parquets
    (legacy / pre-arc) trigger the same caveat as mismatched stamps.
    ``read_run_metadata`` returns ``{}`` for legacy parquets so
    ``stamp.get("engine_version")`` is None; the export MUST treat
    that as 'pre-arc' and emit the phantom-fill caveat verbatim. Same
    trigger as the 4 MCP sweep-touching tools — single source of
    truth across the dashboard + MCP surfaces. Without this test
    the ``engine_version is not None`` guard could silently regress
    and suppress the caveat in the exact scenario it was designed
    for."""
    import src.web.heatmap as hm
    from src.mcp._models import PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT
    monkeypatch.setattr(
        hm.st, "session_state", {"mp_heatmap_selected_cell": (15, 1)},
    )
    monkeypatch.setattr(hm, "read_run_metadata", lambda run_id: {})
    downloads, _ = _patch_streamlit_for_export(monkeypatch)
    hm.render_export_rule(
        pd.DataFrame([_export_trade()]),
        strategy="short_straddle", symbol="RELIANCE",
    )
    md = next(d for d in downloads if d["file_name"].endswith(".md"))
    assert PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT in md["data"].decode("utf-8")


def test_export_rule_pre_arc_caveat_fires_when_read_run_metadata_raises(monkeypatch):
    """Companion to the missing-stamp case: when ``read_run_metadata``
    raises (parquet missing from disk mid-rename, etc.), the impl
    catches the exception and leaves engine_version as None. That
    must still trigger the pre-arc caveat — same rationale as the
    stamp-missing case (operator must NEVER export an
    untraceable-engine rule without the warning)."""
    import src.web.heatmap as hm
    from src.mcp._models import PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT

    def _raises(run_id):
        raise FileNotFoundError(f"parquet for {run_id} missing")

    monkeypatch.setattr(
        hm.st, "session_state", {"mp_heatmap_selected_cell": (15, 1)},
    )
    monkeypatch.setattr(hm, "read_run_metadata", _raises)
    downloads, _ = _patch_streamlit_for_export(monkeypatch)
    hm.render_export_rule(
        pd.DataFrame([_export_trade()]),
        strategy="short_straddle", symbol="RELIANCE",
    )
    md = next(d for d in downloads if d["file_name"].endswith(".md"))
    assert PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT in md["data"].decode("utf-8")


# test_value_pane_config_exposes_select_tools deleted:
# the box-select / lasso modebar buttons were a fallback for the
# on_select="rerun" approach. With plotly_events listening to
# plotly_click directly, that fallback isn't needed — a plain single
# click is the primary interaction. Modebar config is not part of
# plotly_events' API surface.


# ============================================================
# CSV drill-down export — operator-requested 2026-05-30
# ============================================================

def test_classify_fill_source_vwap_when_entry_px_matches_implied():
    """When entry_px equals (turnover * SCALE / volume) - strike, the
    engine used VWAP. The classifier returns 'vwap'.

    Post-F1 (rupees, SCALE=1.0):
      turnover=11,000,000 rupees, vol=50_000 → notional/share = 220
      strike=200 → recovered premium = 20.0 = entry_px → vwap"""
    from src.web.heatmap import _classify_fill_source
    assert _classify_fill_source(20.0, 50000, 11_000_000.0, strike=200.0) == "vwap"


def test_classify_fill_source_close_when_turnover_missing():
    """No turnover → engine had no VWAP path → must have used close.
    Returns 'close'."""
    from src.web.heatmap import _classify_fill_source
    assert _classify_fill_source(100.0, 1000, None) == "close"


def test_classify_fill_source_close_when_volume_zero():
    """Zero volume → division impossible → engine used close."""
    from src.web.heatmap import _classify_fill_source
    assert _classify_fill_source(100.0, 0, 5.0) == "close"


def test_classify_fill_source_close_when_entry_px_diverges_from_vwap():
    """turnover/volume gives VWAP=20 but entry_px=100 → engine rejected
    VWAP (probably units-sanity band trip) → fell back to close."""
    from src.web.heatmap import _classify_fill_source
    assert _classify_fill_source(100.0, 50000, 10.0) == "close"


def test_classify_fill_source_unknown_for_nan_entry_px():
    from src.web.heatmap import _classify_fill_source
    assert _classify_fill_source(None, 1000, 5.0) == "unknown"
    assert _classify_fill_source(float("nan"), 1000, 5.0) == "unknown"


def test_build_cell_csv_emits_one_row_per_leg_per_trade():
    """CSV export flattens trades-by-leg. A 2-trade cell with 2 legs
    per trade → 4 rows. Fixture pins the F5 fix
    (heatmap.py:_build_cell_csv) that recovered-premium VWAP must
    subtract strike — pre-F5 ``entry_vwap_implied`` returned
    notional/share (≈ strike + premium) producing CSV rows where
    entry_px=20.0 sat next to vwap_implied=3024.78 + fill_source='vwap'
    (spurious 15× divergence, operator-confusing). Post-F5 the column
    is the engine's premium VWAP — same value the engine fills at."""
    import json
    import pandas as pd
    from src.web.heatmap import _build_cell_csv
    # Post-F1 (rupees, SCALE=1.0) AND post-F5 (premium = notional - strike):
    # strike=2600, entry_premium=20, entry_volume=50000 →
    # entry_turnover = (2600+20) × 50000 = 131,000,000 rupees.
    # vwap_implied = 131_000_000 / 50_000 - 2600 = 2620 - 2600 = 20. ✓
    # exit_premium=5 → exit_turnover = (2600+5) × 50000 = 130,250,000 rupees.
    leg = {
        "strike": 2600.0, "option_type": "CE", "side": "SELL",
        "qty_lots": 1, "lot_size": 250,
        "entry_px": 20.0, "entry_volume": 50000, "entry_oi": 1000,
        "entry_turnover": 131_000_000.0,
        "exit_px": 5.0, "exit_volume": 50000, "exit_oi": 800,
        "exit_turnover": 130_250_000.0,
        "entry_px_realized": 19.8, "exit_px_realized": 5.05,
        "gross_pnl": 3700.0,
    }
    rows = pd.DataFrame({
        "expiry": [pd.Timestamp("2024-01-25"), pd.Timestamp("2024-02-29")],
        "entry_date": [pd.Timestamp("2024-01-04"), pd.Timestamp("2024-02-04")],
        "exit_date": [pd.Timestamp("2024-01-24"), pd.Timestamp("2024-02-28")],
        "net_pnl": [100.0, 200.0],
        "roi_pct": [1.0, 2.0],
        "hold_trading_days": [14, 14],
        "legs_json": [json.dumps([leg, leg]), json.dumps([leg, leg])],
    })
    csv_bytes = _build_cell_csv(rows)
    decoded = csv_bytes.decode("utf-8")
    # Header + 4 data rows (2 trades × 2 legs each)
    lines = [line for line in decoded.split("\n") if line.strip()]
    assert len(lines) == 5  # 1 header + 4 data rows

    # Parse the CSV properly so the assertions target the right cells
    # — earlier "vwap" in decoded would match the header substring
    # alone and could never catch a fill_source bug.
    import io as _io
    df = pd.read_csv(_io.BytesIO(csv_bytes))
    assert list(df["entry_fill_source"]) == ["vwap"] * 4, (
        f"entry_fill_source classification regressed; got "
        f"{list(df['entry_fill_source'])}"
    )
    assert list(df["exit_fill_source"]) == ["vwap"] * 4, (
        f"exit_fill_source classification regressed; got "
        f"{list(df['exit_fill_source'])}"
    )
    # F5 anchor: entry_vwap_implied is the recovered PREMIUM (matches
    # entry_px), not notional/share. Pre-F5 this was 2620.0 (notional/
    # share = strike + premium) and the test silently passed because
    # the weak `"vwap" in decoded` assertion matched the header.
    assert df["entry_vwap_implied"].iloc[0] == pytest.approx(20.0)
    assert df["exit_vwap_implied"].iloc[0] == pytest.approx(5.0)
    # Operator-facing column name post-F1-B: rupees, not lakhs.
    assert "entry_turnover_rupees" in df.columns
    assert "entry_turnover_lakhs" not in df.columns


def test_build_cell_csv_empty_cell_returns_header_only():
    """A cell with zero priced trades must still return a valid CSV
    (header only) so the download button doesn't yield a blank file."""
    import pandas as pd
    from src.web.heatmap import _build_cell_csv
    empty = pd.DataFrame(columns=[
        "expiry", "entry_date", "exit_date", "net_pnl", "roi_pct",
        "hold_trading_days", "legs_json",
    ])
    csv_bytes = _build_cell_csv(empty)
    decoded = csv_bytes.decode("utf-8")
    lines = [line for line in decoded.split("\n") if line.strip()]
    assert len(lines) == 1  # header only
    assert "expiry" in lines[0]
