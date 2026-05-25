"""Tests for src.web.caveats — constants + module structure.

The render_* helpers require a Streamlit script-context and are
verified visually in chore(p6.1.verify) (screenshot-comparison
against DESIGN/leaderboard.png). This module pins:

  - the three caveat constants exist as non-empty strings
  - MULTIPLE_COMPARISONS_CAVEAT is re-exported from src.analytics.rank
    (one source of truth — never duplicated)
  - DISMISS_KEY follows the SPECS §11.4 `mp_` prefix convention
  - the module-level __all__ exports what consumers need

NOTE: this test module DOES import src.web.caveats which DOES import
streamlit (it's the only src/web/ module allowed to per SPECS §11.1 —
it's the renderer). Streamlit import is fine in tests; what we forbid
in `discover` is streamlit at MODULE-import-time for unit-testability.
"""
from __future__ import annotations

import pytest

from src.analytics.rank import MULTIPLE_COMPARISONS_CAVEAT as _RANK_CAVEAT
from src.web.caveats import (
    DISMISS_KEY,
    MARGIN_TIER_B_CAVEAT,
    MULTIPLE_COMPARISONS_CAVEAT,
    SURVIVORSHIP_CAVEAT,
)


def test_multiple_comparisons_caveat_re_exported_identical():
    """LOAD-BEARING: one source of truth per SPECS §11.3. The web
    layer re-exports from analytics.rank rather than maintaining a
    parallel string — prevents divergent wording."""
    assert MULTIPLE_COMPARISONS_CAVEAT is _RANK_CAVEAT


def test_survivorship_caveat_cites_correct_snapshot_date():
    """LOAD-BEARING anti-regression for the 2026-07-01 typo (reviewer
    flag on 7b12228). Universe snapshot is 2024-07-01 per SPECS §6b.3
    + src/universe/blue_chip.py. Pin this so a future copy-edit can't
    drift the date again — a wrong date in an honest-disclosure
    constant silently undermines every backtest result an operator
    interprets."""
    assert "2024-07-01" in SURVIVORSHIP_CAVEAT
    # Explicit anti-regression for the specific typo
    assert "2026-07-01" not in SURVIVORSHIP_CAVEAT


def test_survivorship_caveat_is_substantive_paragraph():
    """Should be a single paragraph at least one screenful long,
    paraphrasing SPECS §6b.3. Pin length so a future trim doesn't
    silently shrink the disclosure to a one-liner."""
    assert isinstance(SURVIVORSHIP_CAVEAT, str)
    assert len(SURVIVORSHIP_CAVEAT) > 300
    # Must mention the key term so search-indexers / screen-readers
    # surface it.
    assert "survivorship" in SURVIVORSHIP_CAVEAT.lower() or \
           "delisted" in SURVIVORSHIP_CAVEAT.lower()
    assert "blue-chip" in SURVIVORSHIP_CAVEAT.lower()


def test_margin_tier_b_caveat_names_the_bias_direction():
    """Operator must see WHICH direction the bias goes — vague 'this
    is approximate' wording is exactly what asymmetric-conservatism
    discipline forbids."""
    assert isinstance(MARGIN_TIER_B_CAVEAT, str)
    assert len(MARGIN_TIER_B_CAVEAT) > 300
    # Bias direction explicit:
    text = MARGIN_TIER_B_CAVEAT.lower()
    assert "tier-b" in text or "tier b" in text
    assert "span" in text
    # The "BETTER" claim — high-vol + low-offset look BETTER here than prod
    assert "better" in text


def test_dismiss_key_uses_mp_namespace_prefix():
    """SPECS §11.4: every cross-cutting state key is prefixed `mp_`.
    Pin the convention here so a future rename without prefix is
    visible in a test diff."""
    assert DISMISS_KEY == "mp_caveats_dismissed"
    assert DISMISS_KEY.startswith("mp_")


def test_all_three_caveats_are_distinct_strings():
    """Should never accidentally point at the same string (cosmetic
    refactor regression catch — assigning all three to the same const
    would silently collapse three disclosures into one)."""
    assert MULTIPLE_COMPARISONS_CAVEAT != SURVIVORSHIP_CAVEAT
    assert SURVIVORSHIP_CAVEAT != MARGIN_TIER_B_CAVEAT
    assert MULTIPLE_COMPARISONS_CAVEAT != MARGIN_TIER_B_CAVEAT


def test_caveats_module_exports_expected_names():
    """Public API: the three constants + the four render helpers +
    the dismiss-key. Pinned in __all__."""
    from src.web import caveats
    expected = {
        "MULTIPLE_COMPARISONS_CAVEAT",
        "SURVIVORSHIP_CAVEAT",
        "MARGIN_TIER_B_CAVEAT",
        "render_caveats",            # top-level dispatcher
        "render_caveats_strip",
        "render_caveats_collapsed",
        "DISMISS_KEY",
    }
    assert expected.issubset(set(caveats.__all__))


def test_render_caveats_button_keys_unique_per_tab(monkeypatch):
    """LOAD-BEARING regression: Streamlit raises
    StreamlitDuplicateElementKey when 4 tabs each render
    render_caveats_strip() with a shared button key. The tab_id
    kwarg must produce distinct widget keys per call.

    Without this fix the app crashed the moment an operator navigated
    from Leaderboard to any other tab. Pinned here so a future
    refactor that drops the tab_id parameter is caught at test time."""
    captured_keys: list[str] = []

    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_columns(n_or_spec):
        n = n_or_spec if isinstance(n_or_spec, int) else len(n_or_spec)
        return [_NullCtx() for _ in range(n)]

    def fake_button(label, key=None, **kw):
        captured_keys.append(key)
        return False  # never "clicked"

    import src.web.caveats as cav
    monkeypatch.setattr(cav.st, "columns", fake_columns)
    monkeypatch.setattr(cav.st, "button", fake_button)
    monkeypatch.setattr(cav.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(cav.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(cav.st, "warning", lambda *a, **k: None)

    # Render the strip for all 4 tabs (the production call pattern)
    for tab in ("leaderboard", "per_stock", "heatmap", "trends"):
        cav.render_caveats_strip(tab_id=tab)
    # 4 dismiss buttons, all with unique keys
    assert len(captured_keys) == 4
    assert len(set(captured_keys)) == 4, (
        f"button keys must be unique per tab; got {captured_keys}"
    )
    # Each key carries its tab name for grep-ability
    for tab, key in zip(
        ("leaderboard", "per_stock", "heatmap", "trends"), captured_keys,
    ):
        assert tab in key


def test_render_caveats_default_tab_id_still_works(monkeypatch):
    """Backward-compat: calling without tab_id should not crash.
    Single-tab apps / standalone use of caveats module shouldn't
    require knowledge of the tab-namespace pattern."""
    class _NullCtx:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    import src.web.caveats as cav
    monkeypatch.setattr(cav.st, "columns",
                        lambda n: [_NullCtx() for _ in
                                   range(n if isinstance(n, int) else len(n))])
    monkeypatch.setattr(cav.st, "button", lambda *a, **k: False)
    monkeypatch.setattr(cav.st, "markdown", lambda *a, **k: None)
    monkeypatch.setattr(cav.st, "caption", lambda *a, **k: None)
    monkeypatch.setattr(cav.st, "warning", lambda *a, **k: None)
    # Should not raise
    cav.render_caveats_strip()
    cav.render_caveats_collapsed()
