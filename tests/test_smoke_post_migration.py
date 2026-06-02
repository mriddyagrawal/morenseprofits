"""Tests for ``scripts/smoke_post_migration.py`` (P1.6 — the gate
runner that compares api-derived vs bhavcopy-derived sweeps).

These tests focus on the comparison logic + threshold semantics.
The full operator procedure (wipe cache, re-run prefetch + sweep,
compare) is documented in the script's module docstring.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.smoke_post_migration import (
    BACKUP_PER_TRADE_DELTA_THRESHOLD_PP,
    PRIMARY_MEDIAN_DELTA_THRESHOLD_PP,
    _compare_cells,
    _compare_per_trade,
    run_smoke_comparison,
)
from src.config import RESULTS_DIR


# ============================================================
# Synthetic sweep frame builder
# ============================================================

def _build_sweep_frame(rows: list[tuple]) -> pd.DataFrame:
    """``rows`` is a list of:
    (strategy, symbol, expiry, entry, exit, roi_pct)"""
    return pd.DataFrame({
        "strategy": [r[0] for r in rows],
        "symbol": [r[1] for r in rows],
        "expiry": [pd.Timestamp(r[2]) for r in rows],
        "entry_offset_td": [r[3] for r in rows],
        "exit_offset_td": [r[4] for r in rows],
        "roi_pct": [r[5] for r in rows],
    })


def _write_sweep_parquet(
    run_id: str, rows: list[tuple], results_dir: Path,
) -> None:
    """Write a synthesized sweep parquet to results_dir at the
    canonical path."""
    results_dir.mkdir(parents=True, exist_ok=True)
    df = _build_sweep_frame(rows)
    df.to_parquet(results_dir / f"sweep_{run_id}.parquet", index=False)


@pytest.fixture(autouse=True)
def _isolate_results_dir(monkeypatch, tmp_path):
    """Each test gets a fresh results dir so the comparison reads
    only what the test wrote."""
    monkeypatch.setattr(
        "scripts.smoke_post_migration.RESULTS_DIR", tmp_path,
    )
    yield


# ============================================================
# Pass path
# ============================================================

def test_run_smoke_comparison_pass_when_within_thresholds(tmp_path):
    """Identical sweep frames → zero delta → both criteria pass."""
    rows = [
        ("short_straddle", "PNB", "2024-08-29", 15, 1, 1.234),
        ("short_straddle", "PNB", "2024-08-29", 10, 3, 0.567),
        ("short_strangle", "RELIANCE", "2024-08-29", 20, 5, -0.823),
    ]
    _write_sweep_parquet("api", rows, tmp_path)
    _write_sweep_parquet("bhavcopy", rows, tmp_path)
    passed = run_smoke_comparison("api", "bhavcopy", verbose=False)
    assert passed is True


def test_run_smoke_comparison_pass_when_delta_below_primary_threshold(tmp_path):
    """Cells differ by less than 0.01 pp on median → primary passes;
    no individual trade exceeds 0.5 pp → backup passes."""
    api_rows = [
        ("short_straddle", "PNB", "2024-08-29", 15, 1, 1.234),
    ]
    bhav_rows = [
        # 0.005 pp delta — under the 0.01 primary threshold.
        ("short_straddle", "PNB", "2024-08-29", 15, 1, 1.239),
    ]
    _write_sweep_parquet("api", api_rows, tmp_path)
    _write_sweep_parquet("bhavcopy", bhav_rows, tmp_path)
    passed = run_smoke_comparison("api", "bhavcopy", verbose=False)
    assert passed is True


# ============================================================
# Fail paths
# ============================================================

def test_run_smoke_comparison_fail_when_primary_threshold_exceeded(tmp_path):
    """A single cell with median delta > 0.01 pp → primary fails →
    overall fails."""
    api_rows = [
        ("short_straddle", "PNB", "2024-08-29", 15, 1, 1.234),
    ]
    bhav_rows = [
        # 0.5 pp delta — well above the 0.01 primary threshold.
        ("short_straddle", "PNB", "2024-08-29", 15, 1, 1.734),
    ]
    _write_sweep_parquet("api", api_rows, tmp_path)
    _write_sweep_parquet("bhavcopy", bhav_rows, tmp_path)
    passed = run_smoke_comparison("api", "bhavcopy", verbose=False)
    assert passed is False


def test_run_smoke_comparison_fail_when_backup_threshold_exceeded(tmp_path):
    """LOAD-BEARING: backup catches the scenario where one or two
    trades are wildly off but the cell median smooths them. Cell
    median delta is small; individual trade delta exceeds 0.5 pp.

    Construct: 2 expiries per cell. One expiry has matching ROI;
    the other has a large delta. Cell-level medians stay close,
    but per-trade backup fires."""
    api_rows = [
        ("short_straddle", "PNB", "2024-08-29", 15, 1, 1.234),
        ("short_straddle", "PNB", "2024-09-26", 15, 1, 1.5),
    ]
    bhav_rows = [
        # First trade matches; second trade differs by 0.8 pp.
        ("short_straddle", "PNB", "2024-08-29", 15, 1, 1.234),
        ("short_straddle", "PNB", "2024-09-26", 15, 1, 2.3),  # +0.8 pp
    ]
    _write_sweep_parquet("api", api_rows, tmp_path)
    _write_sweep_parquet("bhavcopy", bhav_rows, tmp_path)
    passed = run_smoke_comparison("api", "bhavcopy", verbose=False)
    assert passed is False


def test_run_smoke_comparison_warns_when_no_cells_match(tmp_path):
    """Disjoint sweeps (different symbols) → no cell join → return
    False (cell match count is the trustworthy signal that the two
    sweeps were generated on the same universe)."""
    api_rows = [("short_straddle", "PNB", "2024-08-29", 15, 1, 1.234)]
    bhav_rows = [
        ("short_straddle", "RELIANCE", "2024-08-29", 15, 1, 1.234),
    ]
    _write_sweep_parquet("api", api_rows, tmp_path)
    _write_sweep_parquet("bhavcopy", bhav_rows, tmp_path)
    passed = run_smoke_comparison("api", "bhavcopy", verbose=False)
    assert passed is False


# ============================================================
# I/O surfaces
# ============================================================

def test_run_smoke_comparison_raises_on_missing_api_parquet(tmp_path):
    _write_sweep_parquet("bhavcopy", [
        ("short_straddle", "PNB", "2024-08-29", 15, 1, 1.234),
    ], tmp_path)
    with pytest.raises(FileNotFoundError, match="sweep parquet not found"):
        run_smoke_comparison("nonexistent_api", "bhavcopy", verbose=False)


def test_run_smoke_comparison_raises_on_missing_bhavcopy_parquet(tmp_path):
    _write_sweep_parquet("api", [
        ("short_straddle", "PNB", "2024-08-29", 15, 1, 1.234),
    ], tmp_path)
    with pytest.raises(FileNotFoundError, match="sweep parquet not found"):
        run_smoke_comparison("api", "nonexistent_bhavcopy", verbose=False)


# ============================================================
# Threshold constants are sane
# ============================================================

def test_primary_threshold_matches_migration_spec():
    """LOAD-BEARING: MIGRATION.md §Phase 1 P1.6 pins the primary at
    0.01 pp. Anti-regression against silent threshold drift."""
    assert PRIMARY_MEDIAN_DELTA_THRESHOLD_PP == 0.01


def test_backup_threshold_matches_migration_spec():
    """LOAD-BEARING: backup threshold = 0.5 pp per the spec."""
    assert BACKUP_PER_TRADE_DELTA_THRESHOLD_PP == 0.5
