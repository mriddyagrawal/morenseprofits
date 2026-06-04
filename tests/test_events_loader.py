"""Tests for src.data.events_loader.

All tests synthesize CSV fixtures in tmp_path — no dependency on the
operator's actual CF-Event-equities CSV (which may or may not be
present in a given clone).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.data import cache, events_loader
from src.data.events_loader import (
    EVENTS_COLUMNS,
    has_earnings_in_window,
    load_events,
)


# ============================================================
# Helpers
# ============================================================

def _redirect_cache(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


def _write_csv(path: Path, rows: list[dict]) -> Path:
    """Write a synthetic NSE-shape Corporate Events CSV. Columns match
    the operator's file: SYMBOL/COMPANY/PURPOSE/DETAILS/DATE."""
    df = pd.DataFrame(rows, columns=["SYMBOL", "COMPANY", "PURPOSE", "DETAILS", "DATE"])
    df.to_csv(path, index=False)
    return path


# ============================================================
# Parser — schema + filtering
# ============================================================

def test_load_events_returns_canonical_schema(monkeypatch, tmp_path):
    """Output columns + dtypes pinned. Downstream consumers can rely
    on this shape without re-checking."""
    _redirect_cache(monkeypatch, tmp_path)
    csv = _write_csv(tmp_path / "CF-Event-equities-test.csv", [
        {"SYMBOL": "RELIANCE", "COMPANY": "Reliance Industries",
         "PURPOSE": "Financial Results", "DETAILS": "Q4",
         "DATE": "29-Apr-2025"},
    ])
    out = load_events(csv_path=csv)
    assert list(out.columns) == list(EVENTS_COLUMNS)
    assert out["SYMBOL"].dtype == pd.StringDtype()
    assert out["PURPOSE"].dtype == pd.StringDtype()
    assert out["DATE"].dtype.name == "datetime64[us]"


def test_load_events_uppercases_symbol_at_parse_time(monkeypatch, tmp_path):
    """LOAD-BEARING (closes 68a97a7 GRILL 1): the parse-time SYMBOL
    column gets ``.str.upper()`` so a hypothetical mixed-case row
    in the CSV (e.g., NSE rebrand silently changing casing) can't
    cause a silent miss against ``has_earnings_in_window``'s
    ``symbol.upper()`` input normalization.

    Pre-grill behavior preserved source casing; post-fix normalizes
    on the way INTO the cache so input and stored side both agree."""
    _redirect_cache(monkeypatch, tmp_path)
    csv = _write_csv(tmp_path / "CF-Event-equities-case.csv", [
        {"SYMBOL": "Reliance", "COMPANY": "",   # mixed-case input
         "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "29-Apr-2025"},
        {"SYMBOL": "hdfcbank", "COMPANY": "",   # lowercase input
         "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "30-Apr-2025"},
    ])
    out = load_events(csv_path=csv)
    # Both rows are uppercase in the cache.
    assert sorted(out["SYMBOL"].tolist()) == ["HDFCBANK", "RELIANCE"]
    # Round-trip through has_earnings_in_window with the original
    # mixed-case input would hit the cache cleanly.
    assert has_earnings_in_window(
        out, "Reliance",
        entry_date=date(2025, 4, 15), exit_date=date(2025, 5, 1),
    )


def test_load_events_strips_whitespace_around_values(monkeypatch, tmp_path):
    """Operator-supplied NSE export ships with leading/trailing
    whitespace on SYMBOL and PURPOSE strings. Parser must normalize."""
    _redirect_cache(monkeypatch, tmp_path)
    csv = _write_csv(tmp_path / "CF-Event-equities-ws.csv", [
        {"SYMBOL": "  RELIANCE  ", "COMPANY": "Reliance",
         "PURPOSE": " Financial Results ", "DETAILS": "",
         "DATE": "29-Apr-2025"},
    ])
    out = load_events(csv_path=csv)
    assert out.iloc[0]["SYMBOL"] == "RELIANCE"
    assert out.iloc[0]["PURPOSE"] == "Financial Results"


def test_load_events_filters_to_financial_results_only(monkeypatch, tmp_path):
    """PORTFOLIO_MEMOIR.md §17.5: keep only rows whose PURPOSE
    contains "Financial Results". Dividend, Fund Raising, Bonus,
    Stock Split etc. don't move IV the same way and are dropped."""
    _redirect_cache(monkeypatch, tmp_path)
    csv = _write_csv(tmp_path / "CF-Event-equities-fr.csv", [
        {"SYMBOL": "A", "COMPANY": "A Ltd", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "01-Jan-2025"},
        {"SYMBOL": "B", "COMPANY": "B Ltd", "PURPOSE": "Dividend",
         "DETAILS": "", "DATE": "02-Jan-2025"},
        {"SYMBOL": "C", "COMPANY": "C Ltd", "PURPOSE": "Fund Raising",
         "DETAILS": "", "DATE": "03-Jan-2025"},
        {"SYMBOL": "D", "COMPANY": "D Ltd",
         "PURPOSE": "Financial Results/Dividend",
         "DETAILS": "", "DATE": "04-Jan-2025"},  # multi-category survives
    ])
    out = load_events(csv_path=csv)
    assert sorted(out["SYMBOL"].tolist()) == ["A", "D"]


def test_load_events_drops_rows_with_unparseable_date(monkeypatch, tmp_path):
    """Typos in the source DATE field → NaT → row drop. Loud-fail
    isn't right here; the rest of the dataset is still usable."""
    _redirect_cache(monkeypatch, tmp_path)
    csv = _write_csv(tmp_path / "CF-Event-equities-bad-date.csv", [
        {"SYMBOL": "A", "COMPANY": "A Ltd", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "29-Apr-2025"},
        {"SYMBOL": "B", "COMPANY": "B Ltd", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "not-a-date"},
    ])
    out = load_events(csv_path=csv)
    assert out["SYMBOL"].tolist() == ["A"]


def test_load_events_parses_dd_mon_yyyy_case_variants(monkeypatch, tmp_path):
    """NSE export uses mixed-case month abbreviations (Apr, JUN, Sep).
    pandas %d-%b-%Y handles case-insensitively by default."""
    _redirect_cache(monkeypatch, tmp_path)
    csv = _write_csv(tmp_path / "CF-Event-equities-case.csv", [
        {"SYMBOL": "A", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "29-Apr-2025"},
        {"SYMBOL": "B", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "29-APR-2025"},
        {"SYMBOL": "C", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "29-apr-2025"},
    ])
    out = load_events(csv_path=csv)
    # All three parse to the same date.
    assert (out["DATE"] == pd.Timestamp("2025-04-29")).all()


def test_load_events_rejects_csv_missing_required_columns(monkeypatch, tmp_path):
    """Loud fail if the CSV schema drifts (missing SYMBOL or PURPOSE
    or DATE). Better than silently writing a half-shape cache."""
    _redirect_cache(monkeypatch, tmp_path)
    bad = tmp_path / "CF-Event-equities-noschema.csv"
    bad.write_text("SYMBOL,COMPANY\nA,A Ltd\n")
    with pytest.raises(ValueError, match="missing required columns"):
        load_events(csv_path=bad)


# ============================================================
# Cache — write / read / invalidation
# ============================================================

def test_load_events_writes_cache_parquet(monkeypatch, tmp_path):
    """First load builds the cache parquet at the canonical path."""
    _redirect_cache(monkeypatch, tmp_path)
    csv = _write_csv(tmp_path / "CF-Event-equities-cache.csv", [
        {"SYMBOL": "A", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "01-Jan-2025"},
    ])
    load_events(csv_path=csv)
    assert cache.events_path().exists()


def test_load_events_uses_cache_on_second_call(monkeypatch, tmp_path):
    """Second call returns from parquet without re-parsing the CSV.
    Verified by mutating the CSV between calls (a new row added)
    and confirming the cached result is unchanged."""
    _redirect_cache(monkeypatch, tmp_path)
    csv = _write_csv(tmp_path / "CF-Event-equities-hit.csv", [
        {"SYMBOL": "A", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "01-Jan-2025"},
    ])
    first = load_events(csv_path=csv)
    # Mutate the CSV but DON'T bump mtime past the parquet.
    import os
    parquet_mtime = cache.events_path().stat().st_mtime
    _write_csv(csv, [
        {"SYMBOL": "A", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "01-Jan-2025"},
        {"SYMBOL": "B", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "02-Jan-2025"},
    ])
    # Force CSV mtime to be OLDER than parquet so cache wins.
    os.utime(csv, (parquet_mtime - 60, parquet_mtime - 60))
    second = load_events(csv_path=csv)
    assert len(second) == len(first) == 1


def test_load_events_invalidates_cache_when_csv_is_newer(monkeypatch, tmp_path):
    """LOAD-BEARING: when the operator drops in a fresh CSV (newer
    mtime than the cached parquet), the cache rebuilds on next call.
    Without this, the operator would have to manually delete the
    parquet every time they refresh the source export."""
    _redirect_cache(monkeypatch, tmp_path)
    csv = _write_csv(tmp_path / "CF-Event-equities-inv.csv", [
        {"SYMBOL": "A", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "01-Jan-2025"},
    ])
    first = load_events(csv_path=csv)
    assert len(first) == 1

    import os
    # Rewrite CSV with more rows.
    _write_csv(csv, [
        {"SYMBOL": "A", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "01-Jan-2025"},
        {"SYMBOL": "B", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "02-Jan-2025"},
    ])
    # Bump CSV mtime past the parquet's.
    parquet_mtime = cache.events_path().stat().st_mtime
    os.utime(csv, (parquet_mtime + 60, parquet_mtime + 60))
    second = load_events(csv_path=csv)
    assert len(second) == 2


def test_load_events_force_refresh_bypasses_cache(monkeypatch, tmp_path):
    """``force_refresh=True`` reparses even if cache is fresh."""
    _redirect_cache(monkeypatch, tmp_path)
    csv = _write_csv(tmp_path / "CF-Event-equities-fr.csv", [
        {"SYMBOL": "A", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "01-Jan-2025"},
    ])
    load_events(csv_path=csv)
    # Update CSV but keep old mtime (cache normally wins).
    import os
    parquet_mtime = cache.events_path().stat().st_mtime
    _write_csv(csv, [
        {"SYMBOL": "A", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "01-Jan-2025"},
        {"SYMBOL": "B", "COMPANY": "", "PURPOSE": "Financial Results",
         "DETAILS": "", "DATE": "02-Jan-2025"},
    ])
    os.utime(csv, (parquet_mtime - 60, parquet_mtime - 60))
    out = load_events(csv_path=csv, force_refresh=True)
    assert len(out) == 2


def test_load_events_raises_when_neither_cache_nor_csv_exists(monkeypatch, tmp_path):
    """Fresh clone with no cache and no CSV at the repo root → loud
    failure with operator guidance."""
    _redirect_cache(monkeypatch, tmp_path)
    # Point the default-CSV finder at an empty dir.
    monkeypatch.setattr(events_loader, "_REPO", tmp_path)
    with pytest.raises(FileNotFoundError, match="CF-Event-equities"):
        load_events()


# ============================================================
# has_earnings_in_window — §17.5 filter logic
# ============================================================

def _events_frame(rows: list[tuple[str, str, str]]) -> pd.DataFrame:
    """Build a canonical events frame from (SYMBOL, PURPOSE, DATE-iso) tuples."""
    return pd.DataFrame({
        "SYMBOL": pd.Series([r[0] for r in rows], dtype="string"),
        "PURPOSE": pd.Series([r[1] for r in rows], dtype="string"),
        "DATE": pd.Series(
            [pd.Timestamp(r[2]) for r in rows], dtype="datetime64[us]",
        ),
    })


def test_has_earnings_event_inside_window():
    """Event smack in the middle of [entry, exit] → True."""
    ev = _events_frame([("RELIANCE", "Financial Results", "2025-04-29")])
    assert has_earnings_in_window(
        ev, "RELIANCE",
        entry_date=date(2025, 4, 15), exit_date=date(2025, 5, 1),
    )


def test_has_earnings_event_outside_window():
    """Event before entry → False."""
    ev = _events_frame([("RELIANCE", "Financial Results", "2025-03-01")])
    assert not has_earnings_in_window(
        ev, "RELIANCE",
        entry_date=date(2025, 4, 15), exit_date=date(2025, 5, 1),
    )


def test_has_earnings_buffer_plus_one_day_after_exit():
    """LOAD-BEARING: §17.5 +1 day buffer. Event on exit_date + 1 day
    still triggers the filter (catches "exit the day before the
    announcement" case)."""
    ev = _events_frame([("RELIANCE", "Financial Results", "2025-05-02")])
    assert has_earnings_in_window(
        ev, "RELIANCE",
        entry_date=date(2025, 4, 15), exit_date=date(2025, 5, 1),
    )
    # But event two days after exit doesn't trigger.
    ev2 = _events_frame([("RELIANCE", "Financial Results", "2025-05-03")])
    assert not has_earnings_in_window(
        ev2, "RELIANCE",
        entry_date=date(2025, 4, 15), exit_date=date(2025, 5, 1),
    )


def test_has_earnings_event_exactly_on_entry_date():
    """Boundary: event == entry_date → True (inclusive)."""
    ev = _events_frame([("RELIANCE", "Financial Results", "2025-04-15")])
    assert has_earnings_in_window(
        ev, "RELIANCE",
        entry_date=date(2025, 4, 15), exit_date=date(2025, 5, 1),
    )


def test_has_earnings_event_day_before_entry_does_not_fire():
    """Boundary: event one day before entry → False."""
    ev = _events_frame([("RELIANCE", "Financial Results", "2025-04-14")])
    assert not has_earnings_in_window(
        ev, "RELIANCE",
        entry_date=date(2025, 4, 15), exit_date=date(2025, 5, 1),
    )


def test_has_earnings_filters_by_symbol():
    """Event for a different symbol doesn't fire the filter."""
    ev = _events_frame([
        ("HDFCBANK", "Financial Results", "2025-04-29"),
    ])
    assert not has_earnings_in_window(
        ev, "RELIANCE",
        entry_date=date(2025, 4, 15), exit_date=date(2025, 5, 1),
    )


def test_has_earnings_symbol_match_is_case_insensitive_on_input():
    """Lowercase input symbol matches the upper-cased SYMBOL column."""
    ev = _events_frame([("RELIANCE", "Financial Results", "2025-04-29")])
    assert has_earnings_in_window(
        ev, "reliance",
        entry_date=date(2025, 4, 15), exit_date=date(2025, 5, 1),
    )


def test_has_earnings_filters_by_purpose():
    """Defense-in-depth: a Dividend event hand-built into the frame
    doesn't fire the filter even if dates and symbol match. (The
    cached events.parquet is pre-filtered to Financial Results, but
    a future caller could pass a hand-built frame.)"""
    ev = _events_frame([("RELIANCE", "Dividend", "2025-04-29")])
    assert not has_earnings_in_window(
        ev, "RELIANCE",
        entry_date=date(2025, 4, 15), exit_date=date(2025, 5, 1),
    )


def test_has_earnings_multi_category_purpose_matches():
    """``Financial Results/Dividend`` (multi-category) still counts —
    the substring match catches it."""
    ev = _events_frame([
        ("RELIANCE", "Financial Results/Dividend", "2025-04-29"),
    ])
    assert has_earnings_in_window(
        ev, "RELIANCE",
        entry_date=date(2025, 4, 15), exit_date=date(2025, 5, 1),
    )


def test_has_earnings_empty_frame_returns_false():
    """Cold cache (no events frame) → no filter triggered (False).
    Operator-conservative default: don't block trades when we don't
    have data, but the operator should treat that as an alert."""
    ev = events_loader._empty_frame()
    assert not has_earnings_in_window(
        ev, "RELIANCE",
        entry_date=date(2025, 4, 15), exit_date=date(2025, 5, 1),
    )
