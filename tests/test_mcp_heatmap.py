"""Tests for src.mcp.heatmap — feat(p8.mcp.heatmap).

heatmap is one of the top-4 tools per the consultation, so the Q3
tightening applies: structural schema invariants pinned + integration-
style behavior tests for every caveat-trigger and the underlying
analytics dispatch (pivot_window vs pivot_cvar).
"""
from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest

from src.analytics.rank import MULTIPLE_COMPARISONS_CAVEAT
from src.engine import results as r
from src.mcp._models import PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT
from src.mcp.heatmap import (
    MULTIPLE_COMPARISONS_CELL_THRESHOLD,
    HeatmapInput,
    HeatmapOutput,
    heatmap_impl,
    register_heatmap_tools,
)


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
) -> dict[str, Any]:
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
        "entry_spot_vwap": 2600.0,
        "exit_spot_vwap": 2650.0,
        "entry_spot_close": 2600.0,
        "exit_spot_close": 2650.0,
        "notional_at_entry_vwap": 1300000.0,
    }


def _build_grid(
    entry_offsets: list[int],
    exit_offsets: list[int],
    *,
    trades_per_cell: int = 6,
    roi_pct_by_cell=None,
) -> list[dict]:
    """Build a grid of trades — `trades_per_cell` rows per (entry, exit)
    cell. ``roi_pct_by_cell`` lets callers override per-cell ROI; default
    is 1.0 everywhere."""
    rows: list[dict] = []
    for e in entry_offsets:
        for x in exit_offsets:
            roi = (
                roi_pct_by_cell.get((e, x), 1.0)
                if roi_pct_by_cell else 1.0
            )
            for i in range(trades_per_cell):
                rows.append(_trade(
                    entry_offset=e, exit_offset=x, roi_pct=roi,
                    # Vary expiry so rows are unique-by-key.
                    expiry=f"2024-{1 + (i % 12):02d}-25",
                ))
    return rows


# ============================================================
# Happy path
# ============================================================

def test_heatmap_returns_cells_for_2x2_grid():
    """2x2 grid × 6 trades/cell → 4 visible cells + axes correct +
    no pre-arc / multiple-comparisons caveats since the grid is small
    and stamped."""
    rows = _build_grid([15, 10], [3, 1], trades_per_cell=6)
    r.write_results(pd.DataFrame(rows), run_id="happy")
    out = heatmap_impl(HeatmapInput(
        run_id="happy", strategy="short_straddle", symbol="RELIANCE",
    ))
    assert out.n_cells_total == 4
    assert out.n_cells_visible == 4
    # Axes sorted descending — dashboard convention.
    assert out.entry_offsets == [15, 10]
    assert out.exit_offsets == [3, 1]
    # No masked cells with n=6 >= default min_n=5.
    assert all(c.masked is False for c in out.cells)
    assert all(c.value == 1.0 for c in out.cells)


def test_heatmap_value_col_routes_to_pivot_cvar_for_cvar_5():
    """When value_col='cvar_5', the tool routes to pivot_cvar rather
    than pivot_window. CVaR-5% returns the tail mean per cell —
    different output than the median."""
    # Build a cell with one large outlier so median ≠ CVaR.
    rows = [
        _trade(roi_pct=10.0, expiry=f"2024-{m:02d}-25")
        for m in range(1, 10)
    ]
    rows.append(_trade(roi_pct=-100.0, expiry="2024-10-25"))  # outlier
    # Also add a second cell so the grid has 2x1 shape.
    rows.extend([
        _trade(entry_offset=10, exit_offset=1, roi_pct=10.0,
               expiry=f"2024-{m:02d}-25")
        for m in range(1, 7)
    ])
    r.write_results(pd.DataFrame(rows), run_id="cvar_test")
    out_median = heatmap_impl(HeatmapInput(
        run_id="cvar_test", strategy="short_straddle", symbol="RELIANCE",
        value_col="roi_pct", agg_fn="median",
    ))
    out_cvar = heatmap_impl(HeatmapInput(
        run_id="cvar_test", strategy="short_straddle", symbol="RELIANCE",
        value_col="cvar_5",
    ))
    # The (15, 1) cell: median=10 (the outlier doesn't move it) but
    # CVaR-5%=-100 (the outlier IS the worst trade).
    median_cell = next(
        c for c in out_median.cells
        if c.entry_offset_td == 15 and c.exit_offset_td == 1
    )
    cvar_cell = next(
        c for c in out_cvar.cells
        if c.entry_offset_td == 15 and c.exit_offset_td == 1
    )
    assert median_cell.value == 10.0
    assert cvar_cell.value == -100.0


def test_heatmap_min_n_masks_thin_cells():
    """Cells with n < min_n must have value=None + masked=True. The
    test builds a mixed grid: one cell with n=6 (visible) and one with
    n=2 (masked)."""
    rows = []
    # Visible cell at (15, 1) — 6 trades.
    rows.extend([
        _trade(entry_offset=15, exit_offset=1, roi_pct=1.0,
               expiry=f"2024-{m:02d}-25")
        for m in range(1, 7)
    ])
    # Thin cell at (10, 1) — 2 trades.
    rows.extend([
        _trade(entry_offset=10, exit_offset=1, roi_pct=1.0,
               expiry=f"2024-{m:02d}-25")
        for m in range(1, 3)
    ])
    r.write_results(pd.DataFrame(rows), run_id="mask")
    out = heatmap_impl(HeatmapInput(
        run_id="mask", strategy="short_straddle", symbol="RELIANCE",
        min_n=5,
    ))
    by_key = {(c.entry_offset_td, c.exit_offset_td): c for c in out.cells}
    assert by_key[(15, 1)].masked is False
    assert by_key[(15, 1)].value == 1.0
    assert by_key[(10, 1)].masked is True
    assert by_key[(10, 1)].value is None
    assert out.n_cells_visible == 1
    assert out.n_cells_total == 2


# ============================================================
# Caveats — behavior tests
# ============================================================

def test_heatmap_multiple_comparisons_caveat_fires_above_threshold():
    """LOAD-BEARING: any heatmap covering >100 cells surfaces the
    MULTIPLE_COMPARISONS_CAVEAT verbatim. Consumer Claudes selecting
    the best cell from a 720-cell grid must see this warning."""
    # 11x10 = 110 cells, above the 100 threshold.
    entry_offsets = list(range(1, 12))
    exit_offsets = list(range(0, 10))
    rows = _build_grid(entry_offsets, exit_offsets, trades_per_cell=6)
    r.write_results(pd.DataFrame(rows), run_id="big_grid")
    out = heatmap_impl(HeatmapInput(
        run_id="big_grid", strategy="short_straddle", symbol="RELIANCE",
    ))
    assert out.n_cells_total == 110
    assert MULTIPLE_COMPARISONS_CAVEAT in out.caveats


def test_heatmap_multiple_comparisons_caveat_silent_below_threshold():
    """Anti-regression for the boundary: a small grid (well below 100
    cells) must NOT trip the caveat."""
    rows = _build_grid([15, 10], [3, 1])  # 2×2 = 4 cells
    r.write_results(pd.DataFrame(rows), run_id="tiny_grid")
    out = heatmap_impl(HeatmapInput(
        run_id="tiny_grid", strategy="short_straddle", symbol="RELIANCE",
    ))
    assert MULTIPLE_COMPARISONS_CAVEAT not in out.caveats


def test_heatmap_pre_arc_caveat_fires_on_legacy_run():
    """LOAD-BEARING: pre-pricing-arc parquets must surface the shared
    PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT verbatim."""
    rows = _build_grid([15, 10], [3, 1])
    df = pd.DataFrame(rows)
    path = r.results_path("legacy_hm")
    path.parent.mkdir(parents=True, exist_ok=True)
    r.canonical_column_order(df).to_parquet(path, index=False)

    out = heatmap_impl(HeatmapInput(
        run_id="legacy_hm", strategy="short_straddle", symbol="RELIANCE",
    ))
    assert PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT in out.caveats


def test_heatmap_all_masked_caveat_when_min_n_eats_everything():
    """When every cell has n < min_n, surface a caveat naming the
    threshold so the consumer can lower it."""
    rows = _build_grid([15, 10], [3, 1], trades_per_cell=2)  # n=2 each
    r.write_results(pd.DataFrame(rows), run_id="all_masked")
    out = heatmap_impl(HeatmapInput(
        run_id="all_masked", strategy="short_straddle", symbol="RELIANCE",
        min_n=5,
    ))
    assert out.n_cells_visible == 0
    assert any("min_n=5" in c for c in out.caveats)


def test_heatmap_empty_strategy_symbol_returns_empty_cells():
    """No data for the requested slice → empty cells + explicit caveat
    so the consumer doesn't treat empty as 'no signal'."""
    rows = _build_grid([15], [1])  # only short_straddle / RELIANCE
    r.write_results(pd.DataFrame(rows), run_id="empty_slice")
    out = heatmap_impl(HeatmapInput(
        run_id="empty_slice", strategy="iron_condor", symbol="TCS",
    ))
    assert out.cells == []
    assert out.n_cells_total == 0
    assert any("No (entry, exit) cells found" in c for c in out.caveats)


# ============================================================
# Schema invariants — Q3
# ============================================================

def test_heatmap_output_schema_pins_required_fields():
    schema = HeatmapOutput.model_json_schema()
    required = set(schema.get("required", []))
    assert {
        "run_id", "strategy", "symbol",
        "value_col", "agg_fn", "min_n",
        "cells", "entry_offsets", "exit_offsets",
        "n_cells_total", "n_cells_visible",
        "caveats",
    }.issubset(required)


def test_heatmap_input_schema_rejects_unsupported_value_col():
    """Literal type catches typos at the schema layer."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        HeatmapInput(
            run_id="x", strategy="s", symbol="y",
            value_col="garbage",  # type: ignore[arg-type]
        )


# ============================================================
# Registry assembly
# ============================================================

def test_register_heatmap_tools_returns_one_entry():
    entries = register_heatmap_tools()
    assert len(entries) == 1
    assert entries[0].name == "heatmap"


def test_server_registry_now_exposes_heatmap():
    from src.mcp.server import _collect_tool_entries
    registry = _collect_tool_entries()
    assert "heatmap" in registry
    # At least 10 (heatmap lands as the 10th tool); will grow as
    # future sub-arcs land.
    assert len(registry) >= 10


# ============================================================
# JSON round-trip
# ============================================================

def test_heatmap_output_round_trips_through_json():
    rows = _build_grid([15, 10], [3, 1])
    r.write_results(pd.DataFrame(rows), run_id="json_hm")
    out = heatmap_impl(HeatmapInput(
        run_id="json_hm", strategy="short_straddle", symbol="RELIANCE",
    ))
    payload = json.dumps(out.model_dump(mode="json"))
    back = json.loads(payload)
    assert back["n_cells_total"] == 4
    assert "caveats" in back
    assert isinstance(back["cells"], list)
