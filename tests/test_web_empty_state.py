"""Tests for src.web.empty_state — DESIGN_SPEC §2.6 thin-data contract.

The render_empty() helper itself needs a Streamlit context; we test
the streamlit-free accessor get_message() which exercises the same
formatting path. Every one of the 7 reason keys is covered.

Anti-regression for the "every tab is silent on an empty slice" bug
class: each test pins both (a) the operator-action verb is present
in the message ("Lower", "Widen", "Pick", "run a larger sweep"), and
(b) the contextual numbers are correctly interpolated into the
template.
"""
from __future__ import annotations

import pytest

from src.web.empty_state import get_message, render_empty


# ============================================================
# 7 reason keys × correct context + operator action verb
# ============================================================

def test_leaderboard_no_rows_after_filters_names_sidebar_action():
    msg = get_message("leaderboard_no_rows_after_filters")
    assert "filters" in msg.lower()
    assert "sidebar" in msg.lower()
    # operator-action verb
    assert "widen" in msg.lower() or "pick" in msg.lower()


def test_leaderboard_all_below_min_n_interpolates_counts():
    msg = get_message(
        "leaderboard_all_below_min_n",
        n_pairs=12, min_n=5,
    )
    assert "12" in msg
    assert "min_n=5" in msg
    assert "lower" in msg.lower()  # operator action: lower the slider
    assert "slider" in msg.lower()


def test_per_stock_no_trades_renders_symbol_name():
    msg = get_message("per_stock_no_trades", symbol="HDFCBANK")
    assert "HDFCBANK" in msg
    assert "pick another" in msg.lower()


def test_heatmap_all_masked_names_threshold():
    msg = get_message("heatmap_all_masked", min_n=5)
    assert "min_n=5" in msg
    assert "lower" in msg.lower()
    assert "(entry, exit)" in msg


def test_heatmap_single_axis_reports_axis_sizes():
    msg = get_message("heatmap_single_axis", n_entry=1, n_exit=3)
    assert "1 entry" in msg
    assert "3 exit" in msg
    assert "≥2" in msg or ">=2" in msg
    # Operator action: inspect leaderboard instead
    assert "leaderboard" in msg.lower()


def test_trends_yoy_single_year_reports_year_count():
    msg = get_message("trends_yoy_single_year", n_years=1)
    assert "1 year" in msg
    assert "≥2 years" in msg or ">=2 years" in msg


def test_trends_moy_single_month_reports_month_count():
    msg = get_message("trends_moy_single_month", n_months=3)
    assert "3 month" in msg
    assert "≥2 calendar months" in msg or "≥2 months" in msg.lower()


# ============================================================
# Unknown reason key — loud failure
# ============================================================

def test_unknown_reason_raises_value_error():
    """LOAD-BEARING for honest disclosure: a typo'd reason key must
    raise loudly, not silently render an empty st.info. Better that
    a Phase-6 commit fail to render than that the user sees a blank
    info box and assumes "no data" when really we mis-wired the
    reason key."""
    with pytest.raises(ValueError, match="unknown empty-state reason"):
        get_message("definitely_not_a_real_reason")  # type: ignore[arg-type]


# ============================================================
# render_empty is the streamlit-side-effect entry point
# ============================================================

def test_render_empty_calls_st_info(monkeypatch):
    """Pin that render_empty actually invokes st.info with the
    formatted message. Monkeypatch streamlit.info to capture calls."""
    captured: list[str] = []

    def fake_info(msg: str):
        captured.append(msg)

    import src.web.empty_state as es
    monkeypatch.setattr(es.st, "info", fake_info)
    render_empty("leaderboard_no_rows_after_filters")
    assert len(captured) == 1
    assert "filters" in captured[0].lower()
