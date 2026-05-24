"""Tests for src.engine.results — canonical schema + persistence."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.engine import results as r


@pytest.fixture(autouse=True)
def _redirect_results_dir(monkeypatch, tmp_path):
    """Every test in this module persists to a per-test temp dir."""
    monkeypatch.setattr(r, "RESULTS_DIR", tmp_path)


def _full_row() -> dict:
    """One row of all RESULTS_COLUMNS, populated with valid placeholder
    values for the schema tests."""
    return {
        "run_id": "abc123",
        "strategy": "short_straddle",
        "symbol": "RELIANCE",
        "expiry": pd.Timestamp("2024-01-25"),
        "entry_date": pd.Timestamp("2024-01-04"),
        "exit_date": pd.Timestamp("2024-01-24"),
        "entry_offset_td": 15,
        "exit_offset_td": 1,
        "params_json": "{}",
        "legs_json": "[]",
        "gross_pnl": 562.25,
        "costs": 139.68,
        "costs_breakdown_json": "{}",
        "net_pnl": 422.57,
        "margin_at_entry": 139319.0,
        "margin_breakdown_json": "{}",
        "roi_pct": 0.30,
        "hold_trading_days": 14,
        "roi_pct_annualized": 5.46,
        "entry_spot": 2596.65,
        "exit_spot": 2700.0,
        "notional_at_entry": 1298325.0,
    }


# ============================================================
# Empty-frame schema preservation
# ============================================================

def test_empty_results_frame_has_canonical_schema():
    df = r.empty_results_frame()
    assert list(df.columns) == list(r.RESULTS_COLUMNS)
    assert len(df) == 0


def test_empty_skips_frame_has_canonical_schema():
    df = r.empty_skips_frame()
    assert list(df.columns) == list(r.SKIPS_COLUMNS)


# ============================================================
# Path helpers
# ============================================================

def test_paths_use_canonical_naming():
    assert r.results_path("abc123").name == "sweep_abc123.parquet"
    assert r.skips_path("abc123").name == "sweep_abc123_skipped.parquet"
    assert r.results_path("abc123", name="custom").name == "custom_abc123.parquet"


# ============================================================
# Write / read round-trip
# ============================================================

def test_write_then_read_round_trips():
    df = pd.DataFrame([_full_row()])
    path = r.write_results(df, run_id="abc123")
    assert path.exists()
    back = r.read_results("abc123")
    assert len(back) == 1
    assert back.iloc[0]["net_pnl"] == 422.57


def test_canonical_order_coerces_date_columns_to_datetime64_us():
    """SPECS §2.0: date columns must be datetime64[us]. ``price_trade``
    returns Python date objects (object dtype) which would round-trip
    through parquet as object — breaking pd.Timestamp-based filters.
    canonical_column_order normalizes this once so both the persisted
    parquet AND the in-memory frame have the SPECS §2.0 schema."""
    from datetime import date

    raw = pd.DataFrame([{
        **_full_row(),
        # Override with date objects (what price_trade emits)
        "expiry": date(2024, 1, 25),
        "entry_date": date(2024, 1, 4),
        "exit_date": date(2024, 1, 24),
    }])
    # Confirm object dtype going in
    assert raw["expiry"].dtype == object

    normalized = r.canonical_column_order(raw)
    for col in ("expiry", "entry_date", "exit_date"):
        assert str(normalized[col].dtype) == "datetime64[us]", (
            f"{col} dtype should be datetime64[us], got {normalized[col].dtype}"
        )
    # And pd.Timestamp filters now work
    assert (normalized["expiry"] == pd.Timestamp("2024-01-25")).sum() == 1


def test_write_results_rejects_missing_columns():
    bad = pd.DataFrame([{"strategy": "x", "symbol": "y"}])  # missing most cols
    with pytest.raises(ValueError, match="missing required columns"):
        r.write_results(bad, run_id="abc123")


def test_read_results_raises_when_schema_drifted(monkeypatch, tmp_path):
    """A parquet written under an older schema (missing a column the
    code now requires) → loud failure on read, not silent NaN."""
    # Build a frame missing 'roi_pct_annualized'
    row = _full_row()
    del row["roi_pct_annualized"]
    df = pd.DataFrame([row])
    # Bypass the validating writer; just dump it to disk directly.
    direct_path = r.results_path("oldschema")
    direct_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(direct_path, index=False)

    with pytest.raises(ValueError, match="missing columns"):
        r.read_results("oldschema")


def test_read_results_raises_when_file_missing():
    with pytest.raises(FileNotFoundError):
        r.read_results("nonexistent")


# ============================================================
# Skip-log write / read
# ============================================================

def test_write_skips_skipped_when_empty():
    """No skips → no companion file written."""
    path = r.write_skips([], run_id="abc123")
    assert path is None


def test_write_then_read_skips():
    rows = [
        {
            "run_id": "abc123",
            "strategy": "short_straddle",
            "symbol": "RELIANCE",
            "expiry": pd.Timestamp("2024-01-25"),
            "entry_offset_td": 15,
            "exit_offset_td": 1,
            "skip_reason": "MissingDataError",
        }
    ]
    path = r.write_skips(rows, run_id="abc123")
    assert path is not None
    back = r.read_skips("abc123")
    assert len(back) == 1
    assert back.iloc[0]["skip_reason"] == "MissingDataError"


def test_read_skips_empty_when_no_companion_file():
    """No skip-log file → empty_skips_frame() (zero rows, canonical
    schema). Downstream code can do `skips_df.groupby('skip_reason')`
    on it without KeyError."""
    df = r.read_skips("nonexistent")
    assert list(df.columns) == list(r.SKIPS_COLUMNS)
    assert len(df) == 0


def test_write_skips_rejects_missing_columns():
    bad = [{"strategy": "x"}]  # missing most SKIPS_COLUMNS
    with pytest.raises(ValueError, match="missing required columns"):
        r.write_skips(bad, run_id="abc123")
