"""Tests for src.data.india_vix_loader.

Most tests monkeypatch the NSE session at the boundary — they exercise
the chunking / parsing / cache-extend logic without hitting the network.
The single @pytest.mark.network test calls the live NSE endpoint and
sanity-checks one year of real data.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.data import cache, india_vix_loader
from src.data.errors import OfflineCacheMiss
from src.data.india_vix_loader import (
    INDIA_VIX_COLUMNS,
    IndiaVixSchemaError,
    _chunks,
    _compute_missing_ranges,
    _empty_frame,
    _parse_rows,
    load_india_vix,
)


def _redirect_cache(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


def _sample_row(d: str, close: float = 12.0) -> dict:
    """One synthetic API row in the actual NSE shape (verified via
    the operator's dev-tools capture 2026-06-04)."""
    return {
        "EOD_TIMESTAMP": d,                  # DD-MON-YYYY e.g. "04-JUN-2025"
        "EOD_INDEX_NAME": "INDIA VIX",        # ignored
        "EOD_OPEN_INDEX_VAL": close - 0.5,
        "EOD_HIGH_INDEX_VAL": close + 0.5,
        "EOD_LOW_INDEX_VAL":  close - 1.0,
        "EOD_CLOSE_INDEX_VAL": close,
        "EOD_PREV_CLOSE":     close - 0.1,
        "VIX_PTS_CHG": 0.1,                   # ignored
        "VIX_PERC_CHG": 0.8,                  # ignored
    }


# ============================================================
# Chunking
# ============================================================

def test_chunks_respect_max_365_day_cap():
    """A 1000-day window must split into ≤365-day chunks."""
    out = _chunks(date(2024, 1, 1), date(2026, 9, 27))
    assert all((b - a).days < 365 for a, b in out)
    # First chunk starts at from_date; last chunk ends at to_date.
    assert out[0][0] == date(2024, 1, 1)
    assert out[-1][1] == date(2026, 9, 27)
    # Chunks are contiguous (no gaps, no overlaps).
    for (_, end), (next_start, _) in zip(out, out[1:]):
        assert (next_start - end).days == 1


def test_chunks_singleton_window():
    """Single-day window → single chunk."""
    out = _chunks(date(2025, 6, 4), date(2025, 6, 4))
    assert out == [(date(2025, 6, 4), date(2025, 6, 4))]


def test_chunks_inverted_window_returns_empty():
    """from > to → empty chunk list (load_india_vix raises before
    calling _chunks; the helper is defensive)."""
    assert _chunks(date(2025, 6, 5), date(2025, 6, 4)) == []


# ============================================================
# Parser
# ============================================================

def test_parser_handles_canonical_row_shape():
    """LOAD-BEARING: parse the exact shape the operator captured via
    Chrome dev tools 2026-06-04. Any change to NSE's response keys
    fires IndiaVixSchemaError; the parser refuses to write a
    half-baked cache."""
    rows = [_sample_row("04-JUN-2025", 16.55), _sample_row("05-JUN-2025", 15.08)]
    out = _parse_rows(rows)
    assert list(out.columns) == list(INDIA_VIX_COLUMNS)
    assert out["date"].dtype.name == "datetime64[us]"
    assert out["india_vix_close"].dtype.name == "float64"
    assert len(out) == 2
    # Date parsing matches DD-MON-YYYY (uppercase month abbrev).
    assert out["date"].iloc[0] == pd.Timestamp("2025-06-04")
    assert out["india_vix_close"].iloc[0] == pytest.approx(16.55)


def test_parser_sorts_and_dedupes():
    """Out-of-order rows must come back sorted; duplicate dates
    deduped (keep="last" so a re-fetch overwrites stale rows)."""
    rows = [
        _sample_row("05-JUN-2025", 15.0),
        _sample_row("04-JUN-2025", 16.0),
        _sample_row("05-JUN-2025", 99.0),   # dup — should override 15.0
    ]
    out = _parse_rows(rows)
    assert out["date"].is_monotonic_increasing
    assert out["date"].is_unique
    # Last-write-wins on the dup.
    jun5 = out[out["date"] == pd.Timestamp("2025-06-05")].iloc[0]
    assert jun5["india_vix_close"] == 99.0


def test_parser_raises_on_missing_required_key():
    """Schema drift on NSE's side → loud IndiaVixSchemaError, not
    a silent NaN column. Names the missing key for operator triage."""
    rows = [{
        "EOD_TIMESTAMP": "04-JUN-2025",
        "EOD_OPEN_INDEX_VAL": 16.0,
        "EOD_HIGH_INDEX_VAL": 17.0,
        "EOD_LOW_INDEX_VAL": 15.0,
        # EOD_CLOSE_INDEX_VAL missing
        "EOD_PREV_CLOSE": 16.0,
    }]
    with pytest.raises(IndiaVixSchemaError, match="EOD_CLOSE_INDEX_VAL"):
        _parse_rows(rows)


def test_parser_empty_input_returns_empty_frame_with_schema():
    """No rows → empty frame, but the schema is preserved so
    downstream consumers don't trip on missing columns."""
    out = _parse_rows([])
    assert list(out.columns) == list(INDIA_VIX_COLUMNS)
    assert len(out) == 0


# ============================================================
# Missing-range computation (cache-extend logic)
# ============================================================

def test_missing_ranges_returns_full_range_on_empty_cache():
    """Cold cache → whole requested range is missing."""
    out = _compute_missing_ranges(
        _empty_frame(),
        date(2024, 1, 1), date(2024, 12, 31),
        force_refresh=False,
    )
    assert out == [(date(2024, 1, 1), date(2024, 12, 31))]


def test_missing_ranges_extends_at_edges_only():
    """Cache covers [2024-06-01, 2024-12-31]; request [2024-01-01,
    2025-06-30]. Missing ranges = before + after, NOT internal gaps
    (those would trigger pointless re-fetches for weekends/holidays
    that legitimately don't have rows)."""
    cached_dates = pd.date_range("2024-06-01", "2024-12-31", freq="D")
    cached = _empty_frame()
    cached = pd.concat([cached, pd.DataFrame({
        "date": cached_dates.astype("datetime64[us]"),
        "india_vix_open": [10.0] * len(cached_dates),
        "india_vix_high": [11.0] * len(cached_dates),
        "india_vix_low":  [9.0] * len(cached_dates),
        "india_vix_close": [10.5] * len(cached_dates),
        "india_vix_prev_close": [10.4] * len(cached_dates),
    })], ignore_index=True)

    out = _compute_missing_ranges(
        cached, date(2024, 1, 1), date(2025, 6, 30),
        force_refresh=False,
    )
    assert out == [
        (date(2024, 1, 1), date(2024, 5, 31)),
        (date(2025, 1, 1), date(2025, 6, 30)),
    ]


def test_missing_ranges_no_missing_when_cache_covers_request():
    """Cache strictly covers the request → no fetch needed."""
    cached_dates = pd.date_range("2023-01-01", "2025-12-31", freq="D")
    cached = pd.DataFrame({
        "date": cached_dates.astype("datetime64[us]"),
        "india_vix_open": [10.0] * len(cached_dates),
        "india_vix_high": [11.0] * len(cached_dates),
        "india_vix_low":  [9.0] * len(cached_dates),
        "india_vix_close": [10.5] * len(cached_dates),
        "india_vix_prev_close": [10.4] * len(cached_dates),
    })
    out = _compute_missing_ranges(
        cached, date(2024, 6, 1), date(2024, 6, 30),
        force_refresh=False,
    )
    assert out == []


def test_missing_ranges_force_refresh_returns_full_range():
    """``force_refresh=True`` returns the whole requested range as
    a single slot regardless of cache contents."""
    cached_dates = pd.date_range("2023-01-01", "2025-12-31", freq="D")
    cached = pd.DataFrame({
        "date": cached_dates.astype("datetime64[us]"),
        "india_vix_open": [10.0] * len(cached_dates),
        "india_vix_high": [11.0] * len(cached_dates),
        "india_vix_low":  [9.0] * len(cached_dates),
        "india_vix_close": [10.5] * len(cached_dates),
        "india_vix_prev_close": [10.4] * len(cached_dates),
    })
    out = _compute_missing_ranges(
        cached, date(2024, 6, 1), date(2024, 6, 30),
        force_refresh=True,
    )
    assert out == [(date(2024, 6, 1), date(2024, 6, 30))]


# ============================================================
# load_india_vix — end-to-end (monkeypatched session)
# ============================================================

def test_offline_with_cold_cache_raises_offline_cache_miss(
    monkeypatch, tmp_path,
):
    """offline=True + no cache → OfflineCacheMiss. Matches the
    project-wide loader convention (spot_loader, options_loader)."""
    _redirect_cache(monkeypatch, tmp_path)
    with pytest.raises(OfflineCacheMiss, match="india_vix"):
        load_india_vix(
            date(2024, 1, 1), date(2024, 1, 31),
            today_fn=lambda: date(2026, 5, 24), offline=True,
        )


def test_cache_hit_does_not_open_session(monkeypatch, tmp_path):
    """When the cache fully covers the requested range, NO network
    activity occurs. Load-bearing for sweep-time use: every cell
    that needs VIX should hit the cache, not NSE."""
    _redirect_cache(monkeypatch, tmp_path)
    # Pre-populate cache covering Jan 2024.
    pre = _parse_rows([
        _sample_row("02-JAN-2024", 14.0),
        _sample_row("03-JAN-2024", 13.5),
    ])
    cache.india_vix_path().parent.mkdir(parents=True, exist_ok=True)
    pre.to_parquet(cache.india_vix_path(), index=False)

    # Patch the session-opener to FAIL — if called, the test fails.
    def boom():
        raise AssertionError("session opened despite full cache hit")
    monkeypatch.setattr(india_vix_loader, "_open_session", boom)

    out = load_india_vix(
        date(2024, 1, 2), date(2024, 1, 3),
        today_fn=lambda: date(2026, 5, 24),
    )
    assert len(out) == 2
    assert out["india_vix_close"].iloc[0] == 14.0


def test_incremental_extend_appends_to_cache(monkeypatch, tmp_path):
    """Cache has [Jan 2-3], request extends to Jan 4. Loader should
    fetch ONLY Jan 4 (not re-fetch Jan 2-3), merge, and write back."""
    _redirect_cache(monkeypatch, tmp_path)
    pre = _parse_rows([
        _sample_row("02-JAN-2024", 14.0),
        _sample_row("03-JAN-2024", 13.5),
    ])
    cache.india_vix_path().parent.mkdir(parents=True, exist_ok=True)
    pre.to_parquet(cache.india_vix_path(), index=False)

    fetched_calls: list[tuple[date, date]] = []

    class FakeSession:
        pass

    def fake_open_session() -> FakeSession:
        return FakeSession()

    def fake_fetch_chunk(session, from_date, to_date):
        fetched_calls.append((from_date, to_date))
        # Return Jan 4 only.
        return [_sample_row("04-JAN-2024", 12.8)]

    monkeypatch.setattr(india_vix_loader, "_open_session", fake_open_session)
    monkeypatch.setattr(india_vix_loader, "_fetch_chunk", fake_fetch_chunk)

    out = load_india_vix(
        date(2024, 1, 2), date(2024, 1, 4),
        today_fn=lambda: date(2026, 5, 24),
    )
    assert len(out) == 3
    assert out["india_vix_close"].tolist() == [14.0, 13.5, 12.8]
    # Only fetched the missing tail, NOT the cached prefix.
    assert fetched_calls == [(date(2024, 1, 4), date(2024, 1, 4))]
    # The cache on disk now covers all three days.
    on_disk = pd.read_parquet(cache.india_vix_path())
    assert len(on_disk) == 3


def test_rejects_from_after_to(monkeypatch, tmp_path):
    """Inverted range → ValueError, same as spot_loader convention."""
    _redirect_cache(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="from_date.*>.*to_date"):
        load_india_vix(
            date(2024, 1, 5), date(2024, 1, 1),
            today_fn=lambda: date(2026, 5, 24),
        )


# ============================================================
# Live network test (gated)
# ============================================================

@pytest.mark.network
def test_live_one_year_call_returns_plausible_values(monkeypatch, tmp_path):
    """LIVE: fetch ~one year of real India VIX data; assert shape +
    plausible value range. Skipped by default per pytest.ini; run
    via ``pytest -m network``. Failures here usually mean the NSE
    schema drifted (parser fires IndiaVixSchemaError) or the
    Akamai cookies are no longer warming via this referer URL."""
    _redirect_cache(monkeypatch, tmp_path)
    out = load_india_vix(
        date(2024, 5, 1), date(2025, 4, 30),
        today_fn=lambda: date(2026, 5, 24),
    )
    # ~250 trading days in a year (NSE).
    assert 200 <= len(out) <= 260, (
        f"unexpected row count for one year of NSE trading days: {len(out)}"
    )
    # Plausible VIX value range: 5-50 over normal Indian market regimes.
    assert out["india_vix_close"].between(5.0, 50.0).all(), (
        f"some india_vix_close values outside [5, 50]: "
        f"{out[~out['india_vix_close'].between(5.0, 50.0)]}"
    )
