"""Tests for src.mcp.sweep_query — feat(p8.mcp.list_runs_query_sweep).

Strategy: tests redirect RESULTS_DIR to a per-test tmp_path and write
minimal sweep parquets via the existing write_results path. This
exercises the real engine_version stamp + read_run_metadata round-trip
(critical for the pricing_arc_applied flag), without depending on the
operator's data/results/ contents.
"""
from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from src.engine import results as r
from src.mcp import sweep_query
from src.mcp.sweep_query import (
    ListRunsInput,
    QuerySweepInput,
    list_runs_impl,
    query_sweep_impl,
    register_sweep_query_tools,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def _redirect_results_dir(monkeypatch, tmp_path):
    """Each test gets a fresh empty RESULTS_DIR. Without this, list_runs
    would discover whatever's on the operator's disk + the test
    parquets, polluting assertions."""
    monkeypatch.setattr(r, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sweep_query, "RESULTS_DIR", tmp_path)


def _minimal_row(*, strategy="short_straddle", symbol="RELIANCE",
                  entry_offset=15, exit_offset=1, net_pnl=100.0,
                  roi_pct=0.5) -> dict:
    return {
        "run_id": "test",
        "strategy": strategy,
        "symbol": symbol,
        "expiry": pd.Timestamp("2024-01-25"),
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


def _write_legacy_unstamped(run_id: str, rows: list[dict]) -> None:
    """Write a parquet directly via pandas to simulate a pre-
    chore(p8.engine.version_stamp) legacy file (no engine_version
    in KV metadata)."""
    df = pd.DataFrame(rows)
    path = r.results_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    r.canonical_column_order(df).to_parquet(path, index=False)


# ============================================================
# list_runs
# ============================================================

def test_list_runs_returns_empty_when_no_parquets():
    out = list_runs_impl(ListRunsInput())
    assert out.n_runs == 0
    assert out.runs == []
    assert out.caveats == []


def test_list_runs_discovers_stamped_run_with_pricing_arc_flag():
    """Fresh write via write_results stamps engine_version. The
    discovered RunInfo carries pricing_arc_applied=True."""
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="modern")
    out = list_runs_impl(ListRunsInput())
    assert out.n_runs == 1
    assert out.runs[0].run_id == "modern"
    assert out.runs[0].pricing_arc_applied is True
    assert out.runs[0].engine_version == r.ENGINE_VERSION
    assert out.runs[0].n_rows == 1
    # No legacy-pre-arc caveat since 100% of runs are stamped.
    assert not any("phantom-fill" in c.lower() for c in out.caveats)


def test_list_runs_flags_legacy_unstamped_parquet():
    """LOAD-BEARING: a legacy parquet (no engine_version stamp) MUST
    surface pricing_arc_applied=False AND the top-level caveats must
    flag the phantom-fill-bias risk so a consumer Claude knows the
    queried data has the +10pt T-45 inflation artifact."""
    _write_legacy_unstamped("legacy", [_minimal_row()])
    out = list_runs_impl(ListRunsInput())
    assert out.n_runs == 1
    assert out.runs[0].pricing_arc_applied is False
    assert out.runs[0].engine_version is None
    assert any("phantom-fill" in c.lower() for c in out.caveats)


def test_list_runs_skips_companion_skipped_parquets():
    """sweep_*_skipped.parquet files are skip-log companions, not
    sweep results. list_runs must NOT surface them as runs."""
    rows = [_minimal_row()]
    r.write_results(pd.DataFrame(rows), run_id="run_a")
    # Companion file with the canonical _skipped suffix.
    r.write_skips(
        [{
            "run_id": "run_a",
            "strategy": "short_straddle",
            "symbol": "RELIANCE",
            "expiry": pd.Timestamp("2024-02-29"),
            "entry_offset_td": 5,
            "exit_offset_td": 0,
            "skip_reason": "TestSkip",
            "skip_detail": "synthetic",
        }],
        run_id="run_a",
    )
    out = list_runs_impl(ListRunsInput())
    # Only run_a — skipped companion is filtered out.
    assert out.n_runs == 1
    assert out.runs[0].run_id == "run_a"


def test_list_runs_returns_size_and_mtime():
    """RunInfo carries size_bytes + mtime so operators can spot the
    biggest / most recent run at a glance."""
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="X")
    out = list_runs_impl(ListRunsInput())
    info = out.runs[0]
    assert info.size_bytes > 0
    assert isinstance(info.mtime_utc, datetime)


# ============================================================
# query_sweep — filtering
# ============================================================

def test_query_sweep_no_filters_returns_all_rows():
    rows = [
        _minimal_row(strategy="short_straddle", symbol="A"),
        _minimal_row(strategy="short_strangle", symbol="B"),
        _minimal_row(strategy="iron_condor", symbol="C"),
    ]
    r.write_results(pd.DataFrame(rows), run_id="all")
    out = query_sweep_impl(QuerySweepInput(run_id="all"))
    assert out.n_rows == 3


def test_query_sweep_filters_by_equality():
    rows = [
        _minimal_row(strategy="short_straddle", net_pnl=100.0),
        _minimal_row(strategy="short_strangle", net_pnl=200.0),
        _minimal_row(strategy="iron_condor", net_pnl=300.0),
    ]
    r.write_results(pd.DataFrame(rows), run_id="eq")
    out = query_sweep_impl(QuerySweepInput(
        run_id="eq", filters={"strategy": "short_straddle"},
    ))
    assert out.n_rows == 1
    assert out.rows[0]["strategy"] == "short_straddle"


def test_query_sweep_filters_by_in_list():
    rows = [
        _minimal_row(symbol="RELIANCE"),
        _minimal_row(symbol="TCS"),
        _minimal_row(symbol="INFY"),
        _minimal_row(symbol="ITC"),
    ]
    r.write_results(pd.DataFrame(rows), run_id="in_test")
    out = query_sweep_impl(QuerySweepInput(
        run_id="in_test", filters={"symbol": ["RELIANCE", "TCS"]},
    ))
    assert out.n_rows == 2
    syms = {r_["symbol"] for r_ in out.rows}
    assert syms == {"RELIANCE", "TCS"}


def test_query_sweep_filters_by_range_gte():
    rows = [
        _minimal_row(net_pnl=50.0),
        _minimal_row(net_pnl=100.0),
        _minimal_row(net_pnl=200.0),
    ]
    r.write_results(pd.DataFrame(rows), run_id="range")
    out = query_sweep_impl(QuerySweepInput(
        run_id="range", filters={"net_pnl__gte": 100.0},
    ))
    assert out.n_rows == 2


def test_query_sweep_filter_value_dtype_mismatch_raises_clean_error():
    """Per reviewer Grill #1 on bacf5cf: filter values are pre-validated
    against the target column's dtype. A typo like int_column__gte='ten'
    surfaces a clean MCP tool error (ValueError with column name +
    dtype + the offending value), NOT an opaque pandas TypeError from
    inside __ge__ comparisons."""
    rows = [_minimal_row(net_pnl=100.0)]
    r.write_results(pd.DataFrame(rows), run_id="bad_value")
    with pytest.raises(ValueError, match="not coercible"):
        query_sweep_impl(QuerySweepInput(
            run_id="bad_value",
            # entry_offset_td is int; "ten" can't coerce.
            filters={"entry_offset_td__gte": "ten"},
        ))


def test_query_sweep_filter_value_string_to_int_coerces_cleanly():
    """When a string IS coercible to the column's int dtype (e.g.
    '15' → 15), the filter succeeds rather than over-strictly
    rejecting. Anti-regression for over-zealous validation."""
    rows = [
        _minimal_row(),  # entry_offset_td=15 default
        # Different cell to ensure filter selects.
    ]
    rows[0]["entry_offset_td"] = 15
    r.write_results(pd.DataFrame(rows), run_id="coerce")
    out = query_sweep_impl(QuerySweepInput(
        run_id="coerce", filters={"entry_offset_td": "15"},  # str → int
    ))
    assert out.n_rows == 1


def test_query_sweep_unknown_filter_column_raises():
    """Typo at the consumer side surfaces immediately as ValueError;
    silent acceptance would let a bad filter return the whole frame
    (and the consumer would treat it as filtered)."""
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="bad")
    with pytest.raises(ValueError, match="unknown column"):
        query_sweep_impl(QuerySweepInput(
            run_id="bad", filters={"nonexistent_column": "X"},
        ))


# ============================================================
# query_sweep — sort, columns, limit
# ============================================================

def test_query_sweep_sort_by_ascending():
    rows = [
        _minimal_row(net_pnl=100.0),
        _minimal_row(net_pnl=300.0),
        _minimal_row(net_pnl=200.0),
    ]
    r.write_results(pd.DataFrame(rows), run_id="sort_asc")
    out = query_sweep_impl(QuerySweepInput(
        run_id="sort_asc", sort_by="net_pnl",
    ))
    pnls = [row["net_pnl"] for row in out.rows]
    assert pnls == [100.0, 200.0, 300.0]


def test_query_sweep_sort_by_descending_with_minus_prefix():
    rows = [
        _minimal_row(net_pnl=100.0),
        _minimal_row(net_pnl=300.0),
        _minimal_row(net_pnl=200.0),
    ]
    r.write_results(pd.DataFrame(rows), run_id="sort_desc")
    out = query_sweep_impl(QuerySweepInput(
        run_id="sort_desc", sort_by="-net_pnl",
    ))
    pnls = [row["net_pnl"] for row in out.rows]
    assert pnls == [300.0, 200.0, 100.0]


def test_query_sweep_columns_subset_returns_only_requested():
    """Tight column subset keeps response payload small + helps
    consumer reason about the data without legs_json blob noise."""
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="cols")
    out = query_sweep_impl(QuerySweepInput(
        run_id="cols", columns=["strategy", "symbol", "net_pnl"],
    ))
    assert out.n_rows == 1
    assert set(out.rows[0].keys()) == {"strategy", "symbol", "net_pnl"}


def test_query_sweep_unknown_column_in_columns_raises():
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="bad_col")
    with pytest.raises(ValueError, match="unknown columns"):
        query_sweep_impl(QuerySweepInput(
            run_id="bad_col", columns=["strategy", "nonexistent"],
        ))


def test_query_sweep_limit_truncates_with_caveat():
    """When the post-filter result exceeds ``limit``, response truncates
    AND a caveat surfaces stating the original match count."""
    rows = [_minimal_row(net_pnl=float(i)) for i in range(20)]
    r.write_results(pd.DataFrame(rows), run_id="limit")
    out = query_sweep_impl(QuerySweepInput(
        run_id="limit", limit=5,
    ))
    assert out.n_rows == 5
    assert any("truncated" in c.lower() for c in out.caveats)
    # The caveat should mention the actual matched count.
    assert any("20" in c for c in out.caveats)


# ============================================================
# Pricing-arc caveat at query level
# ============================================================

def test_query_sweep_against_legacy_run_carries_phantom_fill_caveat():
    """LOAD-BEARING: pre-arc parquets surface the phantom-fill bias
    caveat at every query response, so a consumer Claude reading the
    rows can't accidentally treat them as gate-corrected."""
    _write_legacy_unstamped("legacy_run", [_minimal_row()])
    out = query_sweep_impl(QuerySweepInput(run_id="legacy_run"))
    assert any("phantom-fill" in c.lower() for c in out.caveats)


def test_query_sweep_against_modern_run_no_phantom_fill_caveat():
    """Sanity check on the inverse: a stamped (current ENGINE_VERSION)
    parquet does NOT trip the pre-arc caveat path."""
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="modern_run")
    out = query_sweep_impl(QuerySweepInput(run_id="modern_run"))
    assert not any("phantom-fill" in c.lower() for c in out.caveats)


# ============================================================
# Registry assembly
# ============================================================

def test_register_sweep_query_tools_returns_two_entries():
    """Sub-arc-3.3 entry points ship 2 tools in this commit (list_runs
    + query_sweep). cell_summary + heatmap land in subsequent commits."""
    entries = register_sweep_query_tools()
    assert len(entries) == 2


def test_register_sweep_query_tools_names_match_expected():
    entries = register_sweep_query_tools()
    names = {e.name for e in entries}
    assert names == {"list_runs", "query_sweep"}


def test_server_assembles_all_three_subarcs_without_collision():
    """Cross-sub-arc assembly across the universe + spot_options +
    sweep_query entry-point sub-arcs. Superset check (rather than
    exact-set) so the test stays green as future sub-arcs land more
    tools (cell_summary, heatmap, backtest_one, etc.)."""
    from src.mcp.server import _collect_tool_entries
    registry = _collect_tool_entries()
    sweep_query_tools = {"list_runs", "query_sweep"}
    universe_tools = {"list_universe", "expiries_for", "list_strategies"}
    spot_options_tools = {
        "get_spot_series", "get_option_series", "get_options_chain",
    }
    assert sweep_query_tools.issubset(registry.keys())
    assert universe_tools.issubset(registry.keys())
    assert spot_options_tools.issubset(registry.keys())


# ============================================================
# JSON round-trip
# ============================================================

def test_query_sweep_output_round_trips_through_json():
    r.write_results(pd.DataFrame([_minimal_row()]), run_id="json")
    out = query_sweep_impl(QuerySweepInput(
        run_id="json", columns=["strategy", "symbol", "net_pnl", "expiry"],
    ))
    payload = json.dumps(out.model_dump(mode="json"))
    back = json.loads(payload)
    assert back["n_rows"] == 1
    # Expiry was a Timestamp; should round-trip as an ISO date string.
    assert back["rows"][0]["expiry"] == "2024-01-25"
