"""Tests for src.mcp.sweep_windows — feat(p8.mcp.sweep_windows).

Strategy: monkeypatch backtest_one_impl + the calendar helpers so we
can construct deterministic grids without real cache state. Tests
exercise the aggregation, capping, and skip-summary plumbing.
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from src.mcp import sweep_windows as sw_module
from src.mcp.backtest_one import BacktestOneOutput
from src.mcp.sweep_windows import (
    MAX_GRID_TRADES,
    CellWindowResult,
    SweepWindowsInput,
    register_sweep_windows_tools,
    sweep_windows_impl,
)


# ============================================================
# Helpers
# ============================================================

def _make_priced_output(
    entry_date: date, exit_date: date, *,
    roi_pct: float, net_pnl: float,
) -> BacktestOneOutput:
    return BacktestOneOutput(
        strategy="short_straddle", symbol="X",
        expiry=date(2024, 1, 25), entry_date=entry_date, exit_date=exit_date,
        spot_at_entry=2600.0, gate_status="priced", gate_detail=None,
        gross_pnl=net_pnl + 40.0, costs=40.0, net_pnl=net_pnl,
        margin_at_entry=100000.0, roi_pct=roi_pct,
        hold_trading_days=14, legs=[], caveats=[],
    )


def _make_failed_output(
    entry_date: date, exit_date: date, *, status: str = "IlliquidLegError",
) -> BacktestOneOutput:
    return BacktestOneOutput(
        strategy="short_straddle", symbol="X",
        expiry=date(2024, 1, 25), entry_date=entry_date, exit_date=exit_date,
        spot_at_entry=2600.0, gate_status=status,
        gate_detail="synthetic",
        gross_pnl=None, costs=None, net_pnl=None,
        margin_at_entry=None, roi_pct=None,
        hold_trading_days=None, legs=[], caveats=[],
    )


def _patch_calendars(monkeypatch, expiries, entry_dates):
    """Patch monthly_expiries to return ``expiries`` and
    offset_trading_days to return values from a synthetic mapping."""
    monkeypatch.setattr(
        sw_module, "monthly_expiries",
        lambda symbol, frm, to, offline: list(expiries),
    )
    # Deterministic offset: anchor - n calendar days (approximation;
    # avoids needing real spot cache).
    def fake_offset(anchor, n, *, offline=False):
        from datetime import timedelta
        return anchor - timedelta(days=n)
    monkeypatch.setattr(sw_module, "offset_trading_days", fake_offset)


# ============================================================
# Input validation
# ============================================================

def test_sweep_windows_inverted_expiry_range_raises():
    with pytest.raises(ValueError, match="expiry_from"):
        sweep_windows_impl(SweepWindowsInput(
            strategy="short_straddle", symbol="X",
            expiry_from=date(2024, 12, 31), expiry_to=date(2024, 1, 1),
            entry_offset_min=10, entry_offset_max=15,
            exit_offset_min=0, exit_offset_max=5,
        ))


def test_sweep_windows_inverted_entry_offset_range_raises():
    with pytest.raises(ValueError, match="entry_offset_min"):
        sweep_windows_impl(SweepWindowsInput(
            strategy="short_straddle", symbol="X",
            expiry_from=date(2024, 1, 1), expiry_to=date(2024, 12, 31),
            entry_offset_min=20, entry_offset_max=10,
            exit_offset_min=0, exit_offset_max=5,
        ))


# ============================================================
# Aggregation behavior
# ============================================================

def test_sweep_windows_aggregates_priced_trades_per_cell(monkeypatch):
    """For one (entry=15, exit=1) cell × 3 expiries, all priced with
    different ROI values, the cell's stats reflect the n=3 distribution."""
    expiries = [date(2024, 1, 25), date(2024, 2, 29), date(2024, 3, 28)]
    _patch_calendars(monkeypatch, expiries, [])
    roi_seq = iter([10.0, 20.0, 30.0])
    def fake_bt(inp):
        roi = next(roi_seq)
        return _make_priced_output(inp.entry_date, inp.exit_date,
                                   roi_pct=roi, net_pnl=100.0 * roi)
    monkeypatch.setattr(sw_module, "backtest_one_impl", fake_bt)

    out = sweep_windows_impl(SweepWindowsInput(
        strategy="short_straddle", symbol="X",
        expiry_from=date(2024, 1, 1), expiry_to=date(2024, 12, 31),
        entry_offset_min=15, entry_offset_max=15,
        exit_offset_min=1, exit_offset_max=1,
    ))
    assert out.n_cells == 1
    cell = out.cells[0]
    assert cell.entry_offset_td == 15
    assert cell.exit_offset_td == 1
    assert cell.stats.n == 3
    assert cell.stats.median_roi_pct == 20.0
    assert cell.stats.mean_roi_pct == 20.0
    # Win rate: all 3 trades pnl > 0 → 100%
    assert cell.stats.win_rate_pct == 100.0
    assert out.total_trades_priced == 3
    assert out.total_trades_attempted == 3


def test_sweep_windows_skip_summary_counts_failure_modes(monkeypatch):
    """A mixed cell — 2 priced + 1 IlliquidLegError → skip_summary
    carries both buckets. The stat block reflects only the priced
    trades."""
    expiries = [date(2024, 1, 25), date(2024, 2, 29), date(2024, 3, 28)]
    _patch_calendars(monkeypatch, expiries, [])
    call_idx = iter(range(3))
    def fake_bt(inp):
        i = next(call_idx)
        if i == 0:
            return _make_failed_output(inp.entry_date, inp.exit_date,
                                       status="IlliquidLegError")
        return _make_priced_output(inp.entry_date, inp.exit_date,
                                   roi_pct=10.0, net_pnl=100.0)
    monkeypatch.setattr(sw_module, "backtest_one_impl", fake_bt)

    out = sweep_windows_impl(SweepWindowsInput(
        strategy="short_straddle", symbol="X",
        expiry_from=date(2024, 1, 1), expiry_to=date(2024, 12, 31),
        entry_offset_min=15, entry_offset_max=15,
        exit_offset_min=1, exit_offset_max=1,
    ))
    cell = out.cells[0]
    assert cell.stats.n == 2
    assert cell.skip_summary["priced"] == 2
    assert cell.skip_summary["IlliquidLegError"] == 1


def test_sweep_windows_filters_invalid_entry_le_exit_pairs(monkeypatch):
    """Only entry > exit pairs are valid. A (entry=3, exit=3) or
    (entry=3, exit=5) pair must not appear in the cells list."""
    expiries = [date(2024, 1, 25)]
    _patch_calendars(monkeypatch, expiries, [])
    monkeypatch.setattr(
        sw_module, "backtest_one_impl",
        lambda inp: _make_priced_output(inp.entry_date, inp.exit_date,
                                        roi_pct=5.0, net_pnl=50.0),
    )
    out = sweep_windows_impl(SweepWindowsInput(
        strategy="short_straddle", symbol="X",
        expiry_from=date(2024, 1, 1), expiry_to=date(2024, 12, 31),
        entry_offset_min=3, entry_offset_max=5,
        exit_offset_min=3, exit_offset_max=5,
    ))
    # Valid: (4,3), (5,3), (5,4) — 3 cells.
    pairs = {(c.entry_offset_td, c.exit_offset_td) for c in out.cells}
    assert pairs == {(4, 3), (5, 3), (5, 4)}


def test_sweep_windows_caps_total_trades_with_caveat(monkeypatch):
    """LOAD-BEARING: wide ranges that would exceed MAX_GRID_TRADES
    must cap + surface a caveat naming the script-based alternative."""
    # 25 expiries × 31 valid pairs = 775 > MAX_GRID_TRADES (500)
    expiries = [date(2024, m, 25) for m in range(1, 13)]
    expiries += [date(2025, m, 25) for m in range(1, 13)]
    expiries.append(date(2026, 1, 25))
    _patch_calendars(monkeypatch, expiries, [])
    monkeypatch.setattr(
        sw_module, "backtest_one_impl",
        lambda inp: _make_priced_output(inp.entry_date, inp.exit_date,
                                        roi_pct=5.0, net_pnl=50.0),
    )
    out = sweep_windows_impl(SweepWindowsInput(
        strategy="short_straddle", symbol="X",
        expiry_from=date(2024, 1, 1), expiry_to=date(2026, 12, 31),
        entry_offset_min=10, entry_offset_max=20,
        exit_offset_min=0, exit_offset_max=5,
    ))
    # The capping caveat must fire.
    assert any("capped" in c.lower() for c in out.caveats)
    assert any("wide-sweep" in c.lower() for c in out.caveats)
    assert out.total_trades_attempted <= MAX_GRID_TRADES + 50  # generous


def test_sweep_windows_empty_expiries_returns_empty_cells(monkeypatch):
    """No expiries in the range → empty cells + explicit caveat."""
    _patch_calendars(monkeypatch, [], [])
    out = sweep_windows_impl(SweepWindowsInput(
        strategy="short_straddle", symbol="X",
        expiry_from=date(2024, 1, 1), expiry_to=date(2024, 12, 31),
        entry_offset_min=10, entry_offset_max=15,
        exit_offset_min=0, exit_offset_max=5,
    ))
    assert out.expiries_used == []
    # Cells may still iterate (no expiries → 0 trades each) but caveats
    # should explicitly call out the empty expiry case.
    assert any("no expiries" in c.lower() for c in out.caveats)


# ============================================================
# Registry assembly
# ============================================================

def test_register_sweep_windows_tools_returns_one_entry():
    entries = register_sweep_windows_tools()
    assert len(entries) == 1
    assert entries[0].name == "sweep_windows"


def test_server_registry_now_exposes_sweep_windows():
    from src.mcp.server import _collect_tool_entries
    registry = _collect_tool_entries()
    assert "sweep_windows" in registry
    # 12 tools after this sub-arc closes (sub-arc 3.4 done).
    assert len(registry) >= 12


# ============================================================
# JSON round-trip
# ============================================================

def test_sweep_windows_output_round_trips_through_json(monkeypatch):
    expiries = [date(2024, 1, 25)]
    _patch_calendars(monkeypatch, expiries, [])
    monkeypatch.setattr(
        sw_module, "backtest_one_impl",
        lambda inp: _make_priced_output(inp.entry_date, inp.exit_date,
                                        roi_pct=5.0, net_pnl=50.0),
    )
    out = sweep_windows_impl(SweepWindowsInput(
        strategy="short_straddle", symbol="X",
        expiry_from=date(2024, 1, 1), expiry_to=date(2024, 12, 31),
        entry_offset_min=15, entry_offset_max=15,
        exit_offset_min=1, exit_offset_max=1,
    ))
    payload = json.dumps(out.model_dump(mode="json"))
    back = json.loads(payload)
    assert back["n_cells"] == 1
    assert back["cells"][0]["stats"]["n"] == 1
    assert "caveats" in back
