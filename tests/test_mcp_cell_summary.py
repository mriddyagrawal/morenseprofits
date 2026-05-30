"""Tests for src.mcp.cell_summary — feat(p8.mcp.cell_summary).

cell_summary is one of the top-4 tools per the consultation, so the
reviewer's Q3 tightening applies: structural schema invariants pinned
+ integration-style behavior tests for every caveat-trigger and every
stat field. Snapshots are NOT auto-updated; assertions are explicit
about exactly what fields the consumer Claude must be able to rely on.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd
import pytest

from src.analytics.aggregate import MIN_N_FOR_RANKING
from src.engine import results as r
from src.mcp.cell_summary import (
    BOOTSTRAP_ALPHA,
    BOOTSTRAP_B,
    BOOTSTRAP_METHOD,
    BOOTSTRAP_SEED,
    MAX_PER_TRADE_ROWS,
    CellSummaryInput,
    CellSummaryOutput,
    _bottom_alpha_mean,
    cell_summary_impl,
    register_cell_summary_tools,
)
from src.mcp._models import PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def _redirect_results_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "RESULTS_DIR", tmp_path)


def _trade(
    *,
    expiry: str = "2024-01-25",
    entry_date: str = "2024-01-04",
    exit_date: str = "2024-01-24",
    strategy: str = "short_straddle",
    symbol: str = "RELIANCE",
    entry_offset: int = 15,
    exit_offset: int = 1,
    net_pnl: float = 100.0,
    roi_pct: float = 0.5,
) -> dict[str, Any]:
    return {
        "run_id": "test",
        "strategy": strategy,
        "symbol": symbol,
        "expiry": pd.Timestamp(expiry),
        "entry_date": pd.Timestamp(entry_date),
        "exit_date": pd.Timestamp(exit_date),
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


def _cell_with_n_trades(n: int, *, roi_pcts: list[float] | None = None) -> list[dict]:
    """Build n synthetic trades for the same cell, varying expiry
    so each row is unique-by-key."""
    if roi_pcts is None:
        roi_pcts = [1.0] * n
    assert len(roi_pcts) == n
    rows = []
    for i in range(n):
        rows.append(_trade(
            expiry=f"2024-{1 + (i % 12):02d}-25",
            roi_pct=roi_pcts[i],
            net_pnl=100.0 * roi_pcts[i],
        ))
    return rows


# ============================================================
# Pure helpers
# ============================================================

def test_bottom_alpha_mean_floors_to_single_worst_for_tiny_n():
    import numpy as np
    # n=4, α=0.05 → ceil(0.2) = 1 → just the minimum
    out = _bottom_alpha_mean(np.array([10.0, 20.0, -5.0, 15.0]), alpha=0.05)
    assert out == -5.0


def test_bottom_alpha_mean_uses_strict_count_for_large_n():
    import numpy as np
    # n=100, α=0.05 → ceil(5) = 5 → mean of 5 smallest
    arr = np.arange(1, 101, dtype=float)
    out = _bottom_alpha_mean(arr, alpha=0.05)
    # mean(1..5) = 3
    assert out == pytest.approx(3.0)


def test_bottom_alpha_mean_drops_nans():
    import numpy as np
    arr = np.array([10.0, float("nan"), 20.0, -5.0])
    out = _bottom_alpha_mean(arr, alpha=0.50)
    # After dropping NaN: [10, 20, -5] → ceil(1.5) = 2 → mean(-5, 10) = 2.5
    assert out == pytest.approx(2.5)


# ============================================================
# cell_summary — empty cell
# ============================================================

def test_cell_summary_empty_cell_returns_zero_n_with_caveat():
    """Requesting a cell that doesn't exist in the parquet returns
    n=0 + a load-bearing caveat naming the no-trades case."""
    # Write a parquet with rows for a DIFFERENT cell.
    r.write_results(pd.DataFrame([_trade()]), run_id="empty_cell")
    out = cell_summary_impl(CellSummaryInput(
        run_id="empty_cell",
        strategy="iron_condor",  # different
        symbol="TCS",            # different
        entry_offset_td=20,
        exit_offset_td=5,
    ))
    assert out.stats.n == 0
    assert out.stats.win_rate_pct is None
    assert out.stats.median_roi_pct is None
    assert out.stats.total_net_pnl == 0.0
    assert out.per_trade == []  # include_per_trade=True default; but cell is empty
    assert any("No trades" in c for c in out.caveats)


# ============================================================
# cell_summary — happy path with N=10
# ============================================================

def test_cell_summary_happy_path_with_ten_trades():
    rows = _cell_with_n_trades(10, roi_pcts=list(range(1, 11)))  # 1..10
    r.write_results(pd.DataFrame(rows), run_id="happy")
    out = cell_summary_impl(CellSummaryInput(
        run_id="happy",
        strategy="short_straddle",
        symbol="RELIANCE",
        entry_offset_td=15,
        exit_offset_td=1,
    ))
    assert out.stats.n == 10
    # roi_pcts = 1..10; median = 5.5
    assert out.stats.median_roi_pct == pytest.approx(5.5)
    # mean = 5.5
    assert out.stats.mean_roi_pct == pytest.approx(5.5)
    # All > 0 → 100% win rate
    assert out.stats.win_rate_pct == pytest.approx(100.0)
    # std (ddof=0) of 1..10
    import numpy as np
    expected_std = float(np.std(np.arange(1, 11, dtype=float), ddof=0))
    assert out.stats.std_roi_pct == pytest.approx(expected_std)
    # CVaR-5%: n=10 → ceil(0.5) = 1 → mean of smallest = 1
    assert out.stats.cvar_5_roi_pct == pytest.approx(1.0)
    # total_net_pnl = 100 * (1+2+...+10) = 5500
    assert out.stats.total_net_pnl == pytest.approx(5500.0)
    # No min-N caveat since n=10 >= MIN_N_FOR_RANKING
    assert not any("MIN_N_FOR_RANKING" in c for c in out.caveats)


def test_cell_summary_bootstrap_ci_populated_for_n_geq_2():
    rows = _cell_with_n_trades(10, roi_pcts=list(range(1, 11)))
    r.write_results(pd.DataFrame(rows), run_id="ci")
    out = cell_summary_impl(CellSummaryInput(
        run_id="ci",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
    ))
    assert out.bootstrap_ci_median_roi.point_estimate is not None
    assert out.bootstrap_ci_median_roi.ci_lo is not None
    assert out.bootstrap_ci_median_roi.ci_hi is not None
    assert (
        out.bootstrap_ci_median_roi.ci_lo
        <= out.bootstrap_ci_median_roi.point_estimate
        <= out.bootstrap_ci_median_roi.ci_hi
    )
    # method string is frozen
    assert "B=1000" in out.bootstrap_ci_median_roi.method
    assert "seed=0" in out.bootstrap_ci_median_roi.method


def test_cell_summary_bootstrap_ci_undefined_for_n_lt_2():
    rows = _cell_with_n_trades(1, roi_pcts=[5.0])
    r.write_results(pd.DataFrame(rows), run_id="tiny")
    out = cell_summary_impl(CellSummaryInput(
        run_id="tiny",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
    ))
    assert out.bootstrap_ci_median_roi.point_estimate is None
    assert out.bootstrap_ci_median_roi.ci_lo is None
    assert out.bootstrap_ci_median_roi.ci_hi is None


# ============================================================
# Caveats — behavior tests (Q4 second half)
# ============================================================

def test_cell_summary_min_n_caveat_fires_below_threshold():
    """LOAD-BEARING caveat: n below MIN_N_FOR_RANKING must surface
    the explicit "treat point estimates as suggestive at best" framing
    so a consumer Claude can't propagate a noisy median as a signal."""
    rows = _cell_with_n_trades(3, roi_pcts=[5.0, 10.0, 15.0])
    r.write_results(pd.DataFrame(rows), run_id="thin")
    out = cell_summary_impl(CellSummaryInput(
        run_id="thin",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
    ))
    assert any("MIN_N_FOR_RANKING" in c for c in out.caveats)
    assert any(f"n={out.stats.n}" in c for c in out.caveats)


def test_cell_summary_min_n_caveat_silent_at_threshold():
    """Anti-regression for the threshold boundary: n == MIN_N_FOR_RANKING
    is just-above-the-line and should NOT surface the small-N caveat."""
    rows = _cell_with_n_trades(MIN_N_FOR_RANKING)
    r.write_results(pd.DataFrame(rows), run_id="at_threshold")
    out = cell_summary_impl(CellSummaryInput(
        run_id="at_threshold",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
    ))
    assert not any("MIN_N_FOR_RANKING" in c for c in out.caveats)


def test_cell_summary_pre_arc_caveat_fires_on_legacy_parquet():
    """LOAD-BEARING: pre-pricing-arc parquets must surface the
    phantom-fill-bias caveat per the 2026-05-30 analysis. Consumer
    Claudes reading a legacy cell can't accidentally treat the +10pt
    inflated ROI as real signal."""
    rows = _cell_with_n_trades(10, roi_pcts=list(range(1, 11)))
    # Write directly via pandas to skip the engine_version stamp.
    df = pd.DataFrame(rows)
    path = r.results_path("legacy_cell")
    path.parent.mkdir(parents=True, exist_ok=True)
    r.canonical_column_order(df).to_parquet(path, index=False)

    out = cell_summary_impl(CellSummaryInput(
        run_id="legacy_cell",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
    ))
    assert any("phantom-fill" in c.lower() for c in out.caveats)


def test_cell_summary_no_pre_arc_caveat_on_stamped_parquet():
    """Anti-regression: a current-engine-stamped parquet does NOT trip
    the pre-arc caveat path."""
    rows = _cell_with_n_trades(10, roi_pcts=list(range(1, 11)))
    r.write_results(pd.DataFrame(rows), run_id="modern_cell")
    out = cell_summary_impl(CellSummaryInput(
        run_id="modern_cell",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
    ))
    assert not any("phantom-fill" in c.lower() for c in out.caveats)


# ============================================================
# per_trade payload control
# ============================================================

def test_cell_summary_per_trade_default_includes_full_list():
    rows = _cell_with_n_trades(5)
    r.write_results(pd.DataFrame(rows), run_id="per_trade_default")
    out = cell_summary_impl(CellSummaryInput(
        run_id="per_trade_default",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
    ))
    assert out.per_trade is not None
    assert len(out.per_trade) == 5


def test_cell_summary_per_trade_can_be_omitted():
    rows = _cell_with_n_trades(5)
    r.write_results(pd.DataFrame(rows), run_id="per_trade_off")
    out = cell_summary_impl(CellSummaryInput(
        run_id="per_trade_off",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
        include_per_trade=False,
    ))
    assert out.per_trade is None


def test_cell_summary_per_trade_rows_are_sorted_by_expiry():
    rows = [
        _trade(expiry="2024-03-25", entry_date="2024-03-04", exit_date="2024-03-24"),
        _trade(expiry="2024-01-25", entry_date="2024-01-04", exit_date="2024-01-24"),
        _trade(expiry="2024-02-29", entry_date="2024-02-04", exit_date="2024-02-28"),
    ]
    r.write_results(pd.DataFrame(rows), run_id="sorted")
    out = cell_summary_impl(CellSummaryInput(
        run_id="sorted",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
    ))
    assert out.per_trade is not None
    expiries = [t.expiry for t in out.per_trade]
    assert expiries == sorted(expiries)


# ============================================================
# Schema invariants — Q3 (no auto-update; explicit assertions)
# ============================================================

def test_cell_summary_output_schema_has_required_fields():
    """Snapshot-pinned shape per reviewer Q3. Any schema change here
    requires deliberate test update — no auto-regeneration."""
    schema = CellSummaryOutput.model_json_schema()
    # Top-level required fields.
    assert "properties" in schema
    required = set(schema.get("required", []))
    assert {
        "run_id", "cell_key", "stats", "bootstrap_ci_median_roi",
        "per_trade", "observations", "caveats",
    }.issubset(required)


def test_cell_summary_input_schema_pins_cell_key_fields():
    schema = CellSummaryInput.model_json_schema()
    required = set(schema.get("required", []))
    # The four cell-key fields + run_id are required; include_per_trade
    # has a default so isn't.
    assert {
        "run_id", "strategy", "symbol",
        "entry_offset_td", "exit_offset_td",
    }.issubset(required)


# ============================================================
# Registry assembly
# ============================================================

def test_register_cell_summary_tools_returns_one_entry():
    entries = register_cell_summary_tools()
    assert len(entries) == 1
    assert entries[0].name == "cell_summary"


def test_server_registry_now_exposes_cell_summary():
    """Cross-sub-arc check: cell_summary lands alongside the existing
    tools without collision. Presence + non-empty registry (superset
    pattern so future sub-arcs landing more tools don't trip this
    test)."""
    from src.mcp.server import _collect_tool_entries
    registry = _collect_tool_entries()
    assert "cell_summary" in registry
    # At least 9 (cell_summary lands as the 9th); will grow as future
    # sub-arcs land.
    assert len(registry) >= 9


# ============================================================
# JSON round-trip
# ============================================================

def test_bootstrap_method_string_is_derived_from_constants():
    """Per reviewer Grill #3 on 3264f37: the method string must be
    constructed from the actual BOOTSTRAP_* constants used in the
    bootstrap_ci call — anti-regression against a future commit
    changing the constants but forgetting to update the string."""
    rows = _cell_with_n_trades(10, roi_pcts=list(range(1, 11)))
    r.write_results(pd.DataFrame(rows), run_id="method_str")
    out = cell_summary_impl(CellSummaryInput(
        run_id="method_str",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
    ))
    method = out.bootstrap_ci_median_roi.method
    # Method string must literally contain the constant values.
    assert f"B={BOOTSTRAP_B}" in method
    assert f"seed={BOOTSTRAP_SEED}" in method
    assert f"alpha={BOOTSTRAP_ALPHA}" in method
    # And match the module's pre-computed BOOTSTRAP_METHOD string.
    assert method == BOOTSTRAP_METHOD


def test_pre_arc_caveat_uses_shared_constant():
    """Per reviewer Grill #2 on 3264f37: the phantom-fill caveat
    string is sourced from src.mcp._models.PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT
    so a wording update is a single-site edit. This test pins the
    sourcing — if the impl gets re-inlined with copy-paste text, the
    test fires."""
    rows = _cell_with_n_trades(10, roi_pcts=list(range(1, 11)))
    df = pd.DataFrame(rows)
    path = r.results_path("shared_caveat")
    path.parent.mkdir(parents=True, exist_ok=True)
    r.canonical_column_order(df).to_parquet(path, index=False)

    out = cell_summary_impl(CellSummaryInput(
        run_id="shared_caveat",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
    ))
    # The shared constant must appear verbatim in the caveats list.
    assert PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT in out.caveats


def test_per_trade_truncates_at_max_with_caveat(monkeypatch):
    """Per reviewer Grill #4 on 3264f37: per_trade list now caps at
    MAX_PER_TRADE_ROWS with explicit truncation caveat. Anti-regression
    in case a future sweep grid materially expands expiry coverage."""
    # Force a tiny cap so the test can exercise it without building
    # 1000+ fake trades.
    monkeypatch.setattr("src.mcp.cell_summary.MAX_PER_TRADE_ROWS", 5)
    rows = _cell_with_n_trades(10, roi_pcts=list(range(1, 11)))
    r.write_results(pd.DataFrame(rows), run_id="cap_test")
    out = cell_summary_impl(CellSummaryInput(
        run_id="cap_test",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
    ))
    assert out.per_trade is not None
    assert len(out.per_trade) == 5
    assert any("per_trade truncated" in c for c in out.caveats)
    assert any("query_sweep" in c for c in out.caveats)


def test_cell_summary_output_round_trips_through_json():
    rows = _cell_with_n_trades(5)
    r.write_results(pd.DataFrame(rows), run_id="json")
    out = cell_summary_impl(CellSummaryInput(
        run_id="json",
        strategy="short_straddle", symbol="RELIANCE",
        entry_offset_td=15, exit_offset_td=1,
    ))
    payload = json.dumps(out.model_dump(mode="json"))
    back = json.loads(payload)
    assert back["stats"]["n"] == 5
    assert "caveats" in back
    assert "observations" in back
    # cell_key nested under output
    assert back["cell_key"]["strategy"] == "short_straddle"
