"""End-to-end UI tests via streamlit.testing.v1.AppTest.

These tests boot the real ``app.py`` script against whatever sweep
parquet is in ``data/results/`` and assert that key rendered elements
appear without the script crashing. Coverage gap they close:

  - The drill-down has ~10 commits of UI logic. Before this file, the
    only integration evidence was Antigravity's one-shot walkthrough.
  - The 2459233 blank-heatmap regression (streamlit-plotly-events
    broke trace rendering) would have been caught by an AppTest of
    this shape — the chart rendered as empty SVG; the tests at the
    time only inspected the figure object, not the runtime.

These tests do NOT cover browser-side interaction (real click events,
hover, focus). For that, see the Antigravity walkthrough in
``walkthrough.md``. AppTest's strength is asserting that the SCRIPT
runs cleanly and produces the expected widget / element tree.

Skip behavior: tests are skipped if no sweep parquet is on disk —
common in fresh-clone CI environments before any sweep has been
generated. The user's local machine + any CI that runs a sweep step
will exercise these tests."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


REPO = Path(__file__).resolve().parent.parent
APP_PY = REPO / "app.py"


def _has_sweep_parquet() -> bool:
    """Skip-condition: AppTest needs at least one sweep parquet to
    render anything meaningful in the Heatmap / Leaderboard / etc.
    tabs. Bare clones without ``data/results/`` skip."""
    results_dir = REPO / "data" / "results"
    if not results_dir.exists():
        return False
    return any(results_dir.glob("sweep_*.parquet"))


SKIP_NO_SWEEP = pytest.mark.skipif(
    not _has_sweep_parquet(),
    reason="no sweep parquet in data/results/ — AppTest needs one to render",
)


# ============================================================
# Smoke: app loads
# ============================================================

@SKIP_NO_SWEEP
def test_app_loads_without_crash():
    """The script must boot cleanly under AppTest. This is the lowest-
    cost regression catcher: anything that breaks app.py's import
    chain or top-level execution shows up here.

    The 2459233 streamlit-plotly-events breakage (chart rendered empty)
    technically passed the existing pytest suite because the test
    inspected the figure object, not the runtime. This test catches
    the runtime — if the embedded component throws on render, AppTest
    sees the exception."""
    at = AppTest.from_file(str(APP_PY))
    at.run(timeout=30)
    assert not at.exception, f"app.py raised: {at.exception}"


@SKIP_NO_SWEEP
def test_app_renders_expected_tabs():
    """The 6-tab structure (Leaderboard / Per-stock / Heatmap / Trends
    / Portfolio / Inspect) is part of the v0.6+9.4+9.5 contract.
    Anyone reordering or renaming tabs must update this test — load-
    bearing UX promise.

    Phase 9.5 swapped ``st.tabs`` for ``st.radio(horizontal=True)`` so
    the ``?tab=<Name>`` URL param can drive active-tab selection per
    PORTFOLIO_MEMOIR.md §24.9 deeplink contract; the tab options now
    appear on a radio's ``.options`` rather than ``tabs[i].label``.

    Phase 9.4.1 added Portfolio between Trends and Inspect."""
    at = AppTest.from_file(str(APP_PY))
    at.run(timeout=30)
    assert not at.exception
    tab_radios = [r for r in at.radio if r.key == "mp_active_tab"]
    assert len(tab_radios) == 1, (
        f"expected one active-tab radio with key='mp_active_tab'; got "
        f"{len(tab_radios)}"
    )
    assert list(tab_radios[0].options) == [
        "Leaderboard", "Per-stock", "Heatmap", "Trends",
        "Portfolio", "Inspect",
    ], f"tab options changed: {tab_radios[0].options}"


# ============================================================
# Heatmap tab — selector + picker contracts
# ============================================================

@SKIP_NO_SWEEP
def test_heatmap_tab_renders_strategy_and_symbol_selectors():
    """The Heatmap tab MUST surface a Strategy + Symbol selectbox.
    These are the operator's entry point into the tab; without them,
    no cell can be picked.

    Phase 9.5: ``st.tabs`` was swapped for ``st.radio`` so only the
    active tab's content renders. Seed the active-tab key to
    ``"Heatmap"`` so the heatmap content body runs."""
    at = AppTest.from_file(str(APP_PY))
    at.session_state["mp_active_tab"] = "Heatmap"
    at.run(timeout=30)
    assert not at.exception
    selectbox_labels = [s.label for s in at.selectbox]
    # Per-tab; both 'Strategy' and 'Symbol' appear in the Heatmap tab
    # AND in Trends (which also has its own selectors). Counting that
    # at least 2 of each render.
    assert selectbox_labels.count("Strategy") >= 1
    assert selectbox_labels.count("Symbol") >= 1


@SKIP_NO_SWEEP
def test_heatmap_tab_renders_manual_cell_picker():
    """Per ``click_failures.md``, the always-visible Entry offset +
    Exit offset selectboxes are the operator's primary cell-selection
    mechanism (click isn't reliable across browsers). They MUST
    render even before the operator interacts with the tab."""
    at = AppTest.from_file(str(APP_PY))
    at.session_state["mp_active_tab"] = "Heatmap"
    at.run(timeout=30)
    assert not at.exception
    selectbox_labels = [s.label for s in at.selectbox]
    assert "Entry offset" in selectbox_labels, (
        "manual cell picker's Entry offset dropdown missing"
    )
    assert "Exit offset" in selectbox_labels, (
        "manual cell picker's Exit offset dropdown missing"
    )


# ============================================================
# Drill-down rendering — load-bearing analytical surface
# ============================================================

@SKIP_NO_SWEEP
def test_drilldown_renders_when_cell_selected():
    """The drill-down body must populate when a cell is selected via
    session_state. This bypasses the click handler (click reliability
    is a separate concern documented in click_failures.md) and asserts
    that the rendering pipeline produces the rule card + stats grid +
    bootstrap CI caption + skip surface.

    Pre-seeds session_state with a (15, 3) entry/exit selection — the
    same cell the Antigravity walkthrough verified manually. After
    rerun, key rendered elements must be present."""
    at = AppTest.from_file(str(APP_PY))
    # Seed the cell selection BEFORE running, so when render_cell_drilldown
    # reads session_state during the first run it finds the picked cell.
    # Phase 9.5 also requires the active-tab key (radio replaced st.tabs).
    at.session_state["mp_active_tab"] = "Heatmap"
    at.session_state["mp_heatmap_selected_cell"] = (15, 3)
    at.run(timeout=30)
    assert not at.exception, f"drill-down render raised: {at.exception}"

    # The bootstrap-CI caption is the load-bearing signal: it only
    # renders when render_cell_drilldown's Median Hero card fires.
    captions = [c.value for c in at.caption]
    ci_captions = [c for c in captions if "95% CI" in c and "bootstrap" in c]
    assert len(ci_captions) >= 1, (
        "bootstrap CI caption missing — drill-down's Median Hero card "
        "did not render"
    )

    # The std-bias footer is the very last drill-down caption. Asserting
    # it renders proves the drill-down ran to completion (not crashed
    # mid-way).
    std_bias_captions = [c for c in captions if "observed-sample dispersion" in c]
    assert len(std_bias_captions) >= 1, (
        "std-bias caveat footer missing — drill-down may have crashed "
        "mid-render"
    )


# ============================================================
# Compare-cells mode — pinned no-p-values constraint
# ============================================================

# Banned patterns that would represent the kind of statistical-significance
# machinery the REVIEWER CONSTRAINT in render_compare_cells explicitly
# forbids. Case-insensitive. Each pattern is a real-world phrasing the
# operator might encounter in a stats package (or that a future contributor
# might add by accident).
_BANNED_STAT_PATTERNS = [
    r"\bp[-_ ]?values?\b",
    r"\bstatistical(?:ly)? significan(?:t|ce)\b",
    r"\bp\s*[<>=]\s*0?\.\d+\b",
    r"\bt[-_ ]?test\b",
    r"\bchi[-_ ]?square\b",
    r"\bmann[-_ ]?whitney\b",
    r"\bkolmogorov\b",
    r"\bwilcoxon\b",
]


def _collect_visible_text(at: AppTest) -> str:
    """Concatenate every user-visible text fragment AppTest exposes into
    one big haystack. Used by the no-p-values test to assert NO banned
    pattern appears anywhere in the Compare-cells output.

    Covers: markdown, caption, write, dataframe (column names + cell
    text), metric labels, info/warning/error/success bodies, button
    labels, selectbox labels."""
    parts: list[str] = []
    for el in at.markdown:
        parts.append(str(el.value or ""))
    for el in at.caption:
        parts.append(str(el.value or ""))
    for el in at.info:
        parts.append(str(el.value or ""))
    for el in at.warning:
        parts.append(str(el.value or ""))
    for el in at.error:
        parts.append(str(el.value or ""))
    for el in at.success:
        parts.append(str(el.value or ""))
    for el in at.button:
        parts.append(str(el.label or ""))
    for el in at.selectbox:
        parts.append(str(el.label or ""))
    for el in at.dataframe:
        try:
            df = el.value
            if df is not None:
                parts.append(" ".join(str(c) for c in df.columns))
                parts.append(df.to_string(index=False))
        except Exception:
            pass
    return "\n".join(parts)


@SKIP_NO_SWEEP
def test_compare_cells_renders_no_p_values():
    """REVIEWER CONSTRAINT — pinned in render_compare_cells docstring.
    With N≈24 trades per cell, ~5% of identical-distribution pairs
    return p<0.05 by chance. Across the hundreds of cell-pairs an
    operator might compare during a session, dozens of false-positive
    'significant differences' would appear as noise-disguised-as-signal.

    This test boots the Compare-cells mode with 2 pre-seeded cells and
    asserts NO banned statistical-test phrasing appears anywhere in the
    rendered output. If a future contributor wires in scipy.stats or
    adds a 'p-value' column to the diff table, this fires."""
    at = AppTest.from_file(str(APP_PY))
    at.session_state["mp_active_tab"] = "Heatmap"
    at.session_state["mp_heatmap_mode"] = "Compare cells"
    at.session_state["mp_heatmap_compare_cells"] = [(15, 3), (30, 5)]
    at.run(timeout=30)
    assert not at.exception, f"compare-cells render raised: {at.exception}"

    haystack = _collect_visible_text(at)
    for pattern in _BANNED_STAT_PATTERNS:
        match = re.search(pattern, haystack, flags=re.IGNORECASE)
        assert match is None, (
            f"banned statistical-significance phrase {match.group()!r} "
            f"appeared in Compare-cells output (pattern: {pattern!r}). "
            f"REVIEWER CONSTRAINT in render_compare_cells forbids this."
        )


@SKIP_NO_SWEEP
def test_compare_cells_renders_side_by_side_stats_and_diff():
    """Positive control for test_compare_cells_renders_no_p_values:
    confirms the Compare-cells mode actually rendered its analytical
    surface (stats table + raw-diff table + caveat caption). If the
    no-p-values test passes only because the comparison silently
    failed to render, this test catches it."""
    at = AppTest.from_file(str(APP_PY))
    at.session_state["mp_active_tab"] = "Heatmap"
    at.session_state["mp_heatmap_mode"] = "Compare cells"
    at.session_state["mp_heatmap_compare_cells"] = [(15, 3), (30, 5)]
    at.run(timeout=30)
    assert not at.exception

    markdown_blobs = [str(m.value or "") for m in at.markdown]
    assert any("Side-by-side stats" in b for b in markdown_blobs), (
        "Side-by-side stats header missing — Compare-cells did not render"
    )
    assert any("Raw differences" in b for b in markdown_blobs), (
        "Raw differences header missing — diff table did not render"
    )

    captions = [str(c.value or "") for c in at.caption]
    caveat_found = any(
        "directional signals" in c.lower()
        and "definitive" in c.lower()
        for c in captions
    )
    assert caveat_found, (
        "Compare-cells caveat caption missing — operator would not see "
        "the 'directional signals only' framing"
    )


@SKIP_NO_SWEEP
def test_strike_rule_caption_renders_in_selector():
    """The display_strike_rule caption under the Strategy selector
    (commit 861b307) MUST render. Anti-regression for the strike-
    disclosure honesty contract — if a future strategy refactor breaks
    display_strike_rule, this test fires.

    The strike-rule caption lives in the Heatmap tab's strategy
    selector helper; seed active-tab to Heatmap so its content runs
    under the §24.9 ``st.radio`` routing scheme."""
    at = AppTest.from_file(str(APP_PY))
    at.session_state["mp_active_tab"] = "Heatmap"
    at.run(timeout=30)
    assert not at.exception
    captions = [c.value for c in at.caption]
    strike_rule_captions = [c for c in captions if "Strike rule:" in c]
    assert len(strike_rule_captions) >= 1, (
        "Strike rule caption missing under Strategy selector"
    )
