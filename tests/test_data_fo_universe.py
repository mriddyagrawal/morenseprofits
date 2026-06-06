"""Tests for src.data.fo_universe — Phase 10.1 universe enumeration.

LOAD-BEARING:
  - test_enumerate_returns_distinct_optstk_symbols (the contract)
  - test_enumerate_excludes_optidx_rows (single-stock-only scope)
  - test_enumerate_excludes_futures_rows (no FUTSTK/FUTIDX leakage)
  - test_enumerate_skips_offline_cache_miss_days (best-effort
    degradation per the docstring)
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data import fo_universe as fo_mod
from src.data.errors import OfflineCacheMiss
from src.data.fo_universe import (
    OPTSTK_INSTRUMENT,
    enumerate_fo_universe,
)


def _bhavcopy_row(
    symbol: str, instrument: str = "OPTSTK",
) -> dict:
    """Minimal bhavcopy row — only the columns the enumerator
    reads (symbol + instrument)."""
    return {"symbol": symbol, "instrument": instrument}


def _patch_loaders(
    monkeypatch,
    *,
    days: list[date],
    frames: dict[date, pd.DataFrame],
):
    def fake_trading_days(start, end, **kw):
        return [d for d in days if start <= d <= end]

    def fake_load_bhavcopy(d, *, force_refresh=False, offline=False):
        if d not in frames:
            raise OfflineCacheMiss(f"no cache for {d}")
        return frames[d]

    monkeypatch.setattr(
        fo_mod.trading_calendar, "trading_days", fake_trading_days,
    )
    monkeypatch.setattr(
        fo_mod.bhavcopy_fo_loader, "load_bhavcopy_fo", fake_load_bhavcopy,
    )


# ============================================================
# Distinct-symbol enumeration
# ============================================================

def test_enumerate_returns_distinct_optstk_symbols(monkeypatch):
    """LOAD-BEARING: union of OPTSTK symbols across the window,
    sorted ascending, no duplicates."""
    d1, d2, d3 = date(2024, 4, 1), date(2024, 4, 2), date(2024, 4, 3)
    frames = {
        d1: pd.DataFrame([
            _bhavcopy_row("RELIANCE"),
            _bhavcopy_row("INFY"),
        ]),
        d2: pd.DataFrame([
            _bhavcopy_row("INFY"),  # duplicate
            _bhavcopy_row("TCS"),
        ]),
        d3: pd.DataFrame([
            _bhavcopy_row("HDFCBANK"),
        ]),
    }
    _patch_loaders(monkeypatch, days=[d1, d2, d3], frames=frames)
    out = enumerate_fo_universe(d1, d3)
    assert out == ["HDFCBANK", "INFY", "RELIANCE", "TCS"]


def test_enumerate_excludes_optidx_rows(monkeypatch):
    """LOAD-BEARING: index options (OPTIDX) out of scope per
    memoir §1 non-goals through Phase 11."""
    d = date(2024, 4, 1)
    frames = {
        d: pd.DataFrame([
            _bhavcopy_row("RELIANCE", instrument="OPTSTK"),
            _bhavcopy_row("NIFTY", instrument="OPTIDX"),
            _bhavcopy_row("BANKNIFTY", instrument="OPTIDX"),
        ]),
    }
    _patch_loaders(monkeypatch, days=[d], frames=frames)
    out = enumerate_fo_universe(d, d)
    assert out == ["RELIANCE"]
    assert "NIFTY" not in out
    assert "BANKNIFTY" not in out


def test_enumerate_excludes_futures_rows(monkeypatch):
    """Defensive: only OPTSTK survives; FUTSTK/FUTIDX rows ignored."""
    d = date(2024, 4, 1)
    frames = {
        d: pd.DataFrame([
            _bhavcopy_row("RELIANCE", instrument="OPTSTK"),
            _bhavcopy_row("RELIANCE", instrument="FUTSTK"),
            _bhavcopy_row("NIFTY", instrument="FUTIDX"),
        ]),
    }
    _patch_loaders(monkeypatch, days=[d], frames=frames)
    out = enumerate_fo_universe(d, d)
    assert out == ["RELIANCE"]


def test_enumerate_skips_offline_cache_miss_days(monkeypatch):
    """Missing day in cache → silently skip. Best-effort
    enumeration per the docstring contract."""
    d1, d2 = date(2024, 4, 1), date(2024, 4, 2)
    frames = {
        d1: pd.DataFrame([_bhavcopy_row("RELIANCE")]),
        # d2 absent → OfflineCacheMiss
    }
    _patch_loaders(monkeypatch, days=[d1, d2], frames=frames)
    out = enumerate_fo_universe(d1, d2)
    assert out == ["RELIANCE"]


def test_enumerate_empty_window_returns_empty(monkeypatch):
    _patch_loaders(monkeypatch, days=[], frames={})
    out = enumerate_fo_universe(date(2024, 1, 1), date(2024, 1, 31))
    assert out == []


def test_enumerate_handles_empty_bhavcopy_row(monkeypatch):
    """Empty bhavcopy frame (NSE-holiday-ish day in cache) →
    contributes nothing, doesn't crash."""
    d1, d2 = date(2024, 4, 1), date(2024, 4, 2)
    frames = {
        d1: pd.DataFrame([_bhavcopy_row("RELIANCE")]),
        d2: pd.DataFrame(columns=["symbol", "instrument"]),
    }
    _patch_loaders(monkeypatch, days=[d1, d2], frames=frames)
    out = enumerate_fo_universe(d1, d2)
    assert out == ["RELIANCE"]


def test_enumerate_handles_bhavcopy_missing_required_columns(monkeypatch):
    """Schema-incomplete bhavcopy → skip (don't KeyError).
    Defensive contract."""
    d = date(2024, 4, 1)
    frames = {
        d: pd.DataFrame({"foo": ["bar"]}),  # no instrument/symbol cols
    }
    _patch_loaders(monkeypatch, days=[d], frames=frames)
    out = enumerate_fo_universe(d, d)
    assert out == []


def test_enumerate_rejects_inverted_window():
    with pytest.raises(ValueError, match="from_date.*to_date"):
        enumerate_fo_universe(date(2024, 12, 31), date(2024, 1, 1))


def test_enumerate_handles_trading_calendar_failure(monkeypatch):
    """Cold trading-calendar cache → return empty list, NOT
    exception. Operator sees the empty list and runs the
    bhavcopy prefetch first."""

    def fake_trading_days(*args, **kw):
        raise OfflineCacheMiss("calendar cache cold")

    monkeypatch.setattr(
        fo_mod.trading_calendar, "trading_days", fake_trading_days,
    )
    out = enumerate_fo_universe(date(2024, 1, 1), date(2024, 12, 31))
    assert out == []


def test_optstk_instrument_constant_matches_specs():
    """Pin the constant — if SPECS §2.4 ever renames OPTSTK
    (it won't; NSE naming is stable since pre-2010), the
    enumerator's filter must update."""
    assert OPTSTK_INSTRUMENT == "OPTSTK"
