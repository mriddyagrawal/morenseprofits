"""Tests for src.mcp.skip_summary — feat(p8.mcp.skip_summary).

Strategy: tests redirect RESULTS_DIR to a per-test tmp_path and write
minimal sweep + skip parquets via the existing write_results /
write_skips path. This exercises the read_skips integration end-to-
end without depending on operator cache state.
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from src.engine import results as r
from src.mcp._models import PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT
from src.mcp.skip_summary import (
    DEFAULT_MAX_EXAMPLES,
    MAX_MAX_EXAMPLES,
    SkipSummaryInput,
    register_skip_summary_tools,
    skip_summary_impl,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def _redirect_results_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "RESULTS_DIR", tmp_path)


def _minimal_row(
    *, strategy="short_straddle", symbol="RELIANCE",
    entry_offset=15, exit_offset=1,
    expiry="2024-01-25", net_pnl=100.0,
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
        "roi_pct": 0.5,
        "hold_trading_days": 14,
        "roi_pct_annualized": 9.0,
        "entry_spot": 2600.0,
        "exit_spot": 2650.0,
        "notional_at_entry": 1300000.0,
    }


def _skip_row(
    *, strategy="short_straddle", symbol="RELIANCE",
    expiry="2024-01-25", entry_offset=42, exit_offset=1,
    reason="IlliquidLegError", detail="entry_volume=0",
) -> dict:
    return {
        "run_id": "test",
        "strategy": strategy,
        "symbol": symbol,
        "expiry": pd.Timestamp(expiry),
        "entry_offset_td": entry_offset,
        "exit_offset_td": exit_offset,
        "skip_reason": reason,
        "skip_detail": detail,
    }


# ============================================================
# Empty-skip case
# ============================================================

def test_skip_summary_zero_skips_returns_empty_groups():
    """Sweep with no skip companion → empty groups, 0% skip rate,
    no caveats (run is stamped post-arc by write_results)."""
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="clean")
    out = skip_summary_impl(SkipSummaryInput(run_id="clean"))
    assert out.total_cells_skipped == 0
    assert out.total_cells_priced == 1
    assert out.total_cells_attempted == 1
    assert out.skip_rate_pct == 0.0
    assert out.groups == []
    assert not any("phantom-fill" in c.lower() for c in out.caveats)


def test_skip_summary_missing_run_id_raises():
    with pytest.raises(ValueError, match="no sweep parquet"):
        skip_summary_impl(SkipSummaryInput(run_id="does_not_exist"))


# ============================================================
# Grouping behavior
# ============================================================

def test_skip_summary_groups_by_reason_default():
    """Default group_by='reason' surfaces skip-reason buckets sorted
    by count DESC."""
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="grouped")
    r.write_skips([
        _skip_row(reason="IlliquidLegError"),
        _skip_row(reason="IlliquidLegError", symbol="TCS"),
        _skip_row(reason="IlliquidLegError", symbol="INFY"),
        _skip_row(reason="OfflineCacheMiss"),
        _skip_row(reason="OfflineCacheMiss", symbol="ITC"),
    ], run_id="grouped")
    out = skip_summary_impl(SkipSummaryInput(run_id="grouped"))
    assert out.total_cells_skipped == 5
    assert out.total_cells_priced == 1
    assert len(out.groups) == 2
    # Sorted DESC: IlliquidLegError (3) before OfflineCacheMiss (2)
    assert out.groups[0].key == "IlliquidLegError"
    assert out.groups[0].count == 3
    assert out.groups[1].key == "OfflineCacheMiss"
    assert out.groups[1].count == 2


def test_skip_summary_groups_by_symbol():
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="by_sym")
    r.write_skips([
        _skip_row(symbol="ADANIENT"),
        _skip_row(symbol="ADANIENT"),
        _skip_row(symbol="ADANIENT"),
        _skip_row(symbol="RELIANCE"),
    ], run_id="by_sym")
    out = skip_summary_impl(SkipSummaryInput(
        run_id="by_sym", group_by="symbol",
    ))
    keys = {g.key for g in out.groups}
    assert keys == {"ADANIENT", "RELIANCE"}
    by_key = {g.key: g for g in out.groups}
    assert by_key["ADANIENT"].count == 3
    assert by_key["RELIANCE"].count == 1


def test_skip_summary_groups_by_entry_offset():
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="by_eo")
    r.write_skips([
        _skip_row(entry_offset=42),
        _skip_row(entry_offset=42),
        _skip_row(entry_offset=15),
    ], run_id="by_eo")
    out = skip_summary_impl(SkipSummaryInput(
        run_id="by_eo", group_by="entry_offset_td",
    ))
    by_key = {g.key: g for g in out.groups}
    assert by_key["42"].count == 2
    assert by_key["15"].count == 1


def test_skip_summary_groups_by_expiry():
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="by_exp")
    r.write_skips([
        _skip_row(expiry="2024-01-25"),
        _skip_row(expiry="2024-01-25"),
        _skip_row(expiry="2024-02-29"),
    ], run_id="by_exp")
    out = skip_summary_impl(SkipSummaryInput(
        run_id="by_exp", group_by="expiry",
    ))
    by_key = {g.key: g for g in out.groups}
    assert by_key["2024-01-25"].count == 2
    assert by_key["2024-02-29"].count == 1


# ============================================================
# Examples + capping
# ============================================================

def test_skip_summary_examples_default_capped_at_three():
    """5 skips of the same reason → only DEFAULT_MAX_EXAMPLES (3)
    examples surface in the group."""
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="cap")
    r.write_skips([
        _skip_row(symbol=f"SYM{i}") for i in range(5)
    ], run_id="cap")
    out = skip_summary_impl(SkipSummaryInput(run_id="cap"))
    assert len(out.groups) == 1
    assert out.groups[0].count == 5  # full count still surfaces
    assert len(out.groups[0].examples) == DEFAULT_MAX_EXAMPLES


def test_skip_summary_max_examples_zero_returns_counts_only():
    """max_examples=0 produces a counts-only response (no example
    rows)."""
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="counts_only")
    r.write_skips([
        _skip_row(symbol=f"SYM{i}") for i in range(5)
    ], run_id="counts_only")
    out = skip_summary_impl(SkipSummaryInput(
        run_id="counts_only", max_examples=0,
    ))
    assert out.groups[0].count == 5
    assert out.groups[0].examples == []


def test_skip_summary_max_examples_clamped_at_max():
    """max_examples > MAX_MAX_EXAMPLES rejected at the schema layer
    (Pydantic ge/le constraints fire)."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        SkipSummaryInput(
            run_id="x", max_examples=MAX_MAX_EXAMPLES + 1,
        )


# ============================================================
# Pre-arc caveat
# ============================================================

def test_skip_summary_pre_arc_caveat_fires_on_legacy_parquet():
    """LOAD-BEARING: legacy (no engine_version stamp) parquets must
    surface the shared PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT plus the
    additional 'skip distribution reflects pre-arc behavior' framing
    so consumer Claudes don't try to compare pre/post-arc breakdowns
    1-to-1."""
    df = pd.DataFrame([_minimal_row()])
    path = r.results_path("legacy_skips")
    path.parent.mkdir(parents=True, exist_ok=True)
    r.canonical_column_order(df).to_parquet(path, index=False)
    r.write_skips([_skip_row()], run_id="legacy_skips")
    out = skip_summary_impl(SkipSummaryInput(run_id="legacy_skips"))
    assert PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT in out.caveats
    assert any(
        "pre-arc" in c.lower() and "comparable" in c.lower()
        for c in out.caveats
    )


# ============================================================
# Registry assembly
# ============================================================

def test_register_skip_summary_tools_returns_one_entry():
    entries = register_skip_summary_tools()
    assert len(entries) == 1
    assert entries[0].name == "skip_summary"


def test_server_registry_now_exposes_skip_summary():
    from src.mcp.server import _collect_tool_entries
    registry = _collect_tool_entries()
    assert "skip_summary" in registry
    # 13 tools (12 + skip_summary)
    assert len(registry) >= 13


# ============================================================
# JSON round-trip
# ============================================================

def test_skip_summary_output_round_trips_through_json():
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="json")
    r.write_skips([_skip_row()], run_id="json")
    out = skip_summary_impl(SkipSummaryInput(run_id="json"))
    payload = json.dumps(out.model_dump(mode="json"))
    back = json.loads(payload)
    assert back["total_cells_skipped"] == 1
    assert "caveats" in back
    assert isinstance(back["groups"], list)
