"""Tests for src.mcp.compare_cells — feat(p8.mcp.compare_cells).

LOAD-BEARING: the test_no_p_values_in_serialized_output test mirrors
the dashboard's ``test_compare_cells_renders_no_p_values`` enforcement.
Any contributor accidentally adding statistical-test machinery to
compare_cells_impl fails that test.
"""
from __future__ import annotations

import json
import re
from datetime import date

import pandas as pd
import pytest

from src.analytics.rank import MULTIPLE_COMPARISONS_CAVEAT
from src.engine import results as r
from src.mcp._models import PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT
from src.mcp.compare_cells import (
    MAX_DISTRIBUTION_ROWS,
    NO_P_VALUES_CAVEAT,
    CompareCellKey,
    CompareCellsInput,
    compare_cells_impl,
    register_compare_cells_tools,
)


# Banned-phrase regex set. Mirror of the dashboard's
# tests/test_web_e2e.py::test_compare_cells_renders_no_p_values
# enforcement. Case-insensitive.
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


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def _redirect_results_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "RESULTS_DIR", tmp_path)


def _trade(
    *, strategy="short_straddle", symbol="RELIANCE",
    entry_offset=15, exit_offset=1, roi_pct=1.0, net_pnl=100.0,
    expiry="2024-01-25",
) -> dict:
    return {
        "run_id": "test",
        "strategy": strategy,
        "symbol": symbol,
        "expiry": pd.Timestamp(expiry),
        "entry_date": pd.Timestamp("2024-01-04"),
        "exit_date": pd.Timestamp("2024-01-24"),
        "entry_offset_td": entry_offset,
        "exit_offset_td": exit_offset,
        "params_json": "{}",
        "legs_json": "[]",
        "gross_pnl": net_pnl + 40.0,
        "costs": 40.0,
        "costs_breakdown_json": "{}",
        "net_pnl": net_pnl,
        "margin_at_entry": 100000.0,
        "margin_breakdown_json": "{}",
        "roi_pct": roi_pct,
        "hold_trading_days": 14,
        "roi_pct_annualized": roi_pct * 18.0,
        "entry_spot": 2600.0,
        "exit_spot": 2650.0,
        "notional_at_entry": 1300000.0,
    }


def _build_cell(
    n: int, *, strategy="short_straddle", symbol="RELIANCE",
    entry_offset=15, exit_offset=1, roi_seq=None,
) -> list[dict]:
    if roi_seq is None:
        roi_seq = [1.0] * n
    return [
        _trade(strategy=strategy, symbol=symbol,
               entry_offset=entry_offset, exit_offset=exit_offset,
               roi_pct=roi_seq[i],
               expiry=f"2024-{1 + (i % 12):02d}-25")
        for i in range(n)
    ]


# ============================================================
# LOAD-BEARING: no-p-values regex enforcement
# ============================================================

def test_no_p_values_in_serialized_output():
    """LOAD-BEARING constraint mirror. Build a comparison, serialize
    via model_dump(mode='json'), scan for ANY banned regex pattern.
    Anti-regression against a future contributor adding statistical-
    test machinery."""
    rows = _build_cell(5) + _build_cell(5, entry_offset=10, exit_offset=3)
    r.write_results(pd.DataFrame(rows), run_id="no_p_test")
    out = compare_cells_impl(CompareCellsInput(
        run_id="no_p_test",
        cell_keys=[
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=15, exit_offset_td=1),
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=10, exit_offset_td=3),
        ],
    ))
    haystack = json.dumps(out.model_dump(mode="json")).lower()
    for pattern in _BANNED_STAT_PATTERNS:
        match = re.search(pattern, haystack)
        assert match is None, (
            f"banned statistical phrase {match.group()!r} surfaced in "
            f"compare_cells output (pattern: {pattern!r}). The "
            f"no-p-values constraint is load-bearing per the dashboard "
            f"+ MCP contract."
        )


def test_no_p_values_caveat_present_verbatim():
    """The exact NO_P_VALUES_CAVEAT string must appear in caveats —
    consumer Claudes parse for it to surface the framing."""
    rows = _build_cell(5) + _build_cell(5, entry_offset=10, exit_offset=3)
    r.write_results(pd.DataFrame(rows), run_id="caveat_text")
    out = compare_cells_impl(CompareCellsInput(
        run_id="caveat_text",
        cell_keys=[
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=15, exit_offset_td=1),
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=10, exit_offset_td=3),
        ],
    ))
    assert NO_P_VALUES_CAVEAT in out.caveats


def test_multiple_comparisons_caveat_re_exported_verbatim():
    """MULTIPLE_COMPARISONS_CAVEAT must appear in caveats verbatim
    from src.analytics.rank — same string the dashboard uses, both
    consumers cite by identity."""
    rows = _build_cell(5) + _build_cell(5, entry_offset=10, exit_offset=3)
    r.write_results(pd.DataFrame(rows), run_id="mc_caveat")
    out = compare_cells_impl(CompareCellsInput(
        run_id="mc_caveat",
        cell_keys=[
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=15, exit_offset_td=1),
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=10, exit_offset_td=3),
        ],
    ))
    assert MULTIPLE_COMPARISONS_CAVEAT in out.caveats


# ============================================================
# Input validation
# ============================================================

def test_compare_cells_input_rejects_single_cell():
    """Pydantic min_length=2 enforces "compare needs at least 2"."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CompareCellsInput(
            run_id="x",
            cell_keys=[CompareCellKey(
                strategy="X", symbol="Y",
                entry_offset_td=15, exit_offset_td=1,
            )],
        )


def test_compare_cells_input_rejects_five_or_more_cells():
    """Pydantic max_length=4 enforces "more than 4 is too noisy."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CompareCellsInput(
            run_id="x",
            cell_keys=[
                CompareCellKey(strategy="X", symbol="Y",
                                entry_offset_td=i, exit_offset_td=1)
                for i in range(5)
            ],
        )


# ============================================================
# Diff computation
# ============================================================

def test_compare_cells_diff_vs_baseline_is_signed_raw_delta():
    """diff_vs_baseline contains raw deltas (other - baseline). Hand-
    derive for two cells: baseline median=1.0, other median=5.0 →
    delta_median_roi = +4.0."""
    rows = _build_cell(3, roi_seq=[1.0, 1.0, 1.0])  # cell A
    rows += _build_cell(3, entry_offset=10, exit_offset=3,
                         roi_seq=[5.0, 5.0, 5.0])  # cell B
    r.write_results(pd.DataFrame(rows), run_id="diff")
    out = compare_cells_impl(CompareCellsInput(
        run_id="diff",
        cell_keys=[
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=15, exit_offset_td=1),
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=10, exit_offset_td=3),
        ],
    ))
    assert len(out.diff_vs_baseline) == 1
    diff = out.diff_vs_baseline[0]
    # B - A = 5 - 1 = +4
    assert diff.delta_median_roi == pytest.approx(4.0)
    assert diff.delta_mean_roi == pytest.approx(4.0)
    assert diff.delta_n_trades == 0  # same count


def test_compare_cells_diff_handles_empty_cell():
    """If a cell has no trades, delta fields are None (can't compute
    a meaningful signed difference vs an empty distribution)."""
    rows = _build_cell(3, roi_seq=[1.0, 1.0, 1.0])
    r.write_results(pd.DataFrame(rows), run_id="empty_diff")
    out = compare_cells_impl(CompareCellsInput(
        run_id="empty_diff",
        cell_keys=[
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=15, exit_offset_td=1),
            # Empty cell — different (eot, xot) with no trades.
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=40, exit_offset_td=10),
        ],
    ))
    diff = out.diff_vs_baseline[0]
    assert diff.delta_median_roi is None
    assert diff.delta_mean_roi is None
    # n delta is 0 - 3 = -3
    assert diff.delta_n_trades == -3


# ============================================================
# Distribution + caveats
# ============================================================

def test_compare_cells_roi_distribution_sorted_ascending():
    rows = _build_cell(5, roi_seq=[3.0, 1.0, 5.0, 2.0, 4.0])
    rows += _build_cell(2, entry_offset=10, exit_offset=3,
                         roi_seq=[10.0, 20.0])
    r.write_results(pd.DataFrame(rows), run_id="dist")
    out = compare_cells_impl(CompareCellsInput(
        run_id="dist",
        cell_keys=[
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=15, exit_offset_td=1),
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=10, exit_offset_td=3),
        ],
    ))
    assert out.cells[0].roi_distribution == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert out.cells[1].roi_distribution == [10.0, 20.0]


def test_compare_cells_distribution_truncation_caveat(monkeypatch):
    """Per-cell ROI distribution capped at MAX_DISTRIBUTION_ROWS;
    truncation surfaces a caveat naming cell_summary as the path for
    full coverage."""
    monkeypatch.setattr("src.mcp.compare_cells.MAX_DISTRIBUTION_ROWS", 3)
    rows = _build_cell(5, roi_seq=[1.0, 2.0, 3.0, 4.0, 5.0])
    rows += _build_cell(2, entry_offset=10, exit_offset=3,
                         roi_seq=[10.0, 20.0])
    r.write_results(pd.DataFrame(rows), run_id="trunc")
    out = compare_cells_impl(CompareCellsInput(
        run_id="trunc",
        cell_keys=[
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=15, exit_offset_td=1),
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=10, exit_offset_td=3),
        ],
    ))
    assert len(out.cells[0].roi_distribution) == 3
    assert any("truncated" in c.lower() for c in out.caveats)


def test_compare_cells_pre_arc_caveat_on_legacy_parquet():
    """Pre-pricing-arc parquets surface the shared phantom-fill
    caveat alongside the no-p-values + multiple-comparisons ones."""
    rows = _build_cell(3) + _build_cell(3, entry_offset=10, exit_offset=3)
    df = pd.DataFrame(rows)
    path = r.results_path("legacy_cmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    r.canonical_column_order(df).to_parquet(path, index=False)
    out = compare_cells_impl(CompareCellsInput(
        run_id="legacy_cmp",
        cell_keys=[
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=15, exit_offset_td=1),
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=10, exit_offset_td=3),
        ],
    ))
    assert PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT in out.caveats


def test_compare_cells_all_empty_cells_surfaces_caveat():
    r.write_results(pd.DataFrame([_trade()]), run_id="all_empty")
    out = compare_cells_impl(CompareCellsInput(
        run_id="all_empty",
        cell_keys=[
            CompareCellKey(strategy="iron_condor", symbol="TCS",
                            entry_offset_td=20, exit_offset_td=5),
            CompareCellKey(strategy="iron_condor", symbol="TCS",
                            entry_offset_td=30, exit_offset_td=10),
        ],
    ))
    assert any("empty" in c.lower() for c in out.caveats)


# ============================================================
# Registry assembly
# ============================================================

def test_register_compare_cells_tools_returns_one_entry():
    entries = register_compare_cells_tools()
    assert len(entries) == 1
    assert entries[0].name == "compare_cells"


def test_server_registry_now_exposes_compare_cells():
    from src.mcp.server import _collect_tool_entries
    registry = _collect_tool_entries()
    assert "compare_cells" in registry
    assert len(registry) >= 15  # sub-arc 3.6 part 1


# ============================================================
# JSON round-trip
# ============================================================

def test_compare_cells_output_round_trips_through_json():
    rows = _build_cell(3) + _build_cell(3, entry_offset=10, exit_offset=3)
    r.write_results(pd.DataFrame(rows), run_id="json_cmp")
    out = compare_cells_impl(CompareCellsInput(
        run_id="json_cmp",
        cell_keys=[
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=15, exit_offset_td=1),
            CompareCellKey(strategy="short_straddle", symbol="RELIANCE",
                            entry_offset_td=10, exit_offset_td=3),
        ],
    ))
    payload = json.dumps(out.model_dump(mode="json"))
    back = json.loads(payload)
    assert len(back["cells"]) == 2
    assert len(back["diff_vs_baseline"]) == 1
    assert "caveats" in back
