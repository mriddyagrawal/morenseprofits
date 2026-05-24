"""Tests for src.data.trading_calendar. Most tests monkeypatch
load_spot (and the underlying jugaad call) to drive the calendar from
a synthetic trading-day list — that keeps them offline and
deterministic.

A handful of tests (marked @pytest.mark.network) exercise the live
NSE path; skipped by default per pytest.ini, runnable via `pytest -m
network`.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

import pandas as pd
import pytest

from src.data import cache, spot_loader, trading_calendar


def _redirect_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


def _patch_load_spot(monkeypatch, trading_dates: Sequence[date]):
    """Replace spot_loader.load_spot to return a synthetic frame whose
    `date` column is exactly the given trading_dates."""
    def fake(symbol, from_date, to_date, *, force_refresh=False,
             today_fn=date.today, offline=False, **kw):
        in_window = [d for d in trading_dates if from_date <= d <= to_date]
        return pd.DataFrame({
            "date": pd.Series(
                [pd.Timestamp(d) for d in in_window], dtype="datetime64[us]"
            ),
            "symbol": pd.array(["RELIANCE"] * len(in_window), dtype="string"),
            "close": [100.0] * len(in_window),
        })

    monkeypatch.setattr(spot_loader, "load_spot", fake)


# Synthetic NSE-2024-January calendar (matches live NSE: Jan 22 closed
# for Ram Mandir, Jan 20 Saturday special session compensates)
_JAN_2024_NSE_DAYS = [
    date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4),
    date(2024, 1, 5),
    date(2024, 1, 8), date(2024, 1, 9), date(2024, 1, 10), date(2024, 1, 11),
    date(2024, 1, 12),
    date(2024, 1, 15), date(2024, 1, 16), date(2024, 1, 17), date(2024, 1, 18),
    date(2024, 1, 19),
    date(2024, 1, 20),  # Saturday special session
    # date(2024, 1, 22) NSE-closed for Ram Mandir
    date(2024, 1, 23), date(2024, 1, 24), date(2024, 1, 25),
    date(2024, 1, 29), date(2024, 1, 30), date(2024, 1, 31),
]


# ============================================================
# LOAD-BEARING: offset_trading_days hand-check
# ============================================================

def test_offset_trading_days_reliance_jan_15_anchor(monkeypatch, tmp_path):
    """LOAD-BEARING. offset_trading_days(2024-01-25, 15) must equal
    2024-01-04. Every Phase-3 backtest's entry/exit date depends on
    this; a single off-by-one breaks every backtest's prices silently.

    Works because Jan 20 Saturday special session compensates for
    Jan 22 Monday closure — net trading days in early Jan 2024 match
    a normal Mon-Fri calendar count."""
    _redirect_cache(monkeypatch, tmp_path)
    _patch_load_spot(monkeypatch, _JAN_2024_NSE_DAYS)
    assert trading_calendar.offset_trading_days(
        date(2024, 1, 25), 15, today_fn=lambda: date(2026, 5, 24)
    ) == date(2024, 1, 4)


# ============================================================
# Anchor semantics (SPECS §3)
# ============================================================

def test_n_zero_on_trading_day_returns_anchor(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    _patch_load_spot(monkeypatch, _JAN_2024_NSE_DAYS)
    out = trading_calendar.offset_trading_days(
        date(2024, 1, 25), 0, today_fn=lambda: date(2026, 5, 24)
    )
    assert out == date(2024, 1, 25)


def test_n_zero_on_non_trading_day_rounds_down(monkeypatch, tmp_path):
    """Jan 22 2024 was NSE-closed; n=0 must round down to the most
    recent trading day strictly before (Jan 20 Saturday session)."""
    _redirect_cache(monkeypatch, tmp_path)
    _patch_load_spot(monkeypatch, _JAN_2024_NSE_DAYS)
    out = trading_calendar.offset_trading_days(
        date(2024, 1, 22), 0, today_fn=lambda: date(2026, 5, 24)
    )
    assert out == date(2024, 1, 20)


def test_n_one_on_non_trading_day(monkeypatch, tmp_path):
    """n=1 returns 'one trading day before anchor', regardless of
    whether anchor itself is a trading day."""
    _redirect_cache(monkeypatch, tmp_path)
    _patch_load_spot(monkeypatch, _JAN_2024_NSE_DAYS)
    out = trading_calendar.offset_trading_days(
        date(2024, 1, 22), 1, today_fn=lambda: date(2026, 5, 24)
    )
    # Jan 22 closed → previous trading day is Sat Jan 20 (special session)
    # n=1 from Jan 22 anchor → one trading day before that = Fri Jan 19
    assert out == date(2024, 1, 19)


def test_n_negative_raises(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    _patch_load_spot(monkeypatch, _JAN_2024_NSE_DAYS)
    with pytest.raises(ValueError, match="n must be >= 0"):
        trading_calendar.offset_trading_days(
            date(2024, 1, 25), -1, today_fn=lambda: date(2026, 5, 24)
        )


def test_insufficient_history_raises(monkeypatch, tmp_path):
    """Asking for 100 trading days before a date that has only 5
    trading days of history must raise loudly, not return garbage."""
    _redirect_cache(monkeypatch, tmp_path)
    _patch_load_spot(monkeypatch, _JAN_2024_NSE_DAYS[:5])  # only 5 trading days
    with pytest.raises(ValueError, match="cannot find"):
        trading_calendar.offset_trading_days(
            date(2024, 1, 25), 100, today_fn=lambda: date(2026, 5, 24)
        )


# ============================================================
# trading_days basic shape
# ============================================================

def test_trading_days_window_inclusive(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    _patch_load_spot(monkeypatch, _JAN_2024_NSE_DAYS)
    out = trading_calendar.trading_days(
        date(2024, 1, 15), date(2024, 1, 25),
        today_fn=lambda: date(2026, 5, 24),
    )
    # Mon-Fri Jan 15-19 (5) + Sat Jan 20 (1) + Tue-Thu Jan 23-25 (3) = 9
    assert len(out) == 9
    assert out[0] == date(2024, 1, 15)
    assert out[-1] == date(2024, 1, 25)
    # Jan 20 Saturday is in the list (special session)
    assert date(2024, 1, 20) in out
    # Jan 22 Monday is NOT in the list (Ram Mandir closure)
    assert date(2024, 1, 22) not in out


def test_trading_days_sorted_ascending(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    _patch_load_spot(monkeypatch, _JAN_2024_NSE_DAYS)
    out = trading_calendar.trading_days(
        date(2024, 1, 1), date(2024, 1, 31),
        today_fn=lambda: date(2026, 5, 24),
    )
    assert out == sorted(out)


def test_trading_days_rejects_from_after_to(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    _patch_load_spot(monkeypatch, _JAN_2024_NSE_DAYS)
    with pytest.raises(ValueError, match="from_date.*>.*to_date"):
        trading_calendar.trading_days(
            date(2024, 1, 25), date(2024, 1, 1),
            today_fn=lambda: date(2026, 5, 24),
        )


# ============================================================
# Determinism
# ============================================================

def test_determinism(monkeypatch, tmp_path):
    """Two calls return == lists. Bedrock for backtest reproducibility."""
    _redirect_cache(monkeypatch, tmp_path)
    _patch_load_spot(monkeypatch, _JAN_2024_NSE_DAYS)
    a = trading_calendar.trading_days(
        date(2024, 1, 1), date(2024, 1, 31), today_fn=lambda: date(2026, 5, 24)
    )
    b = trading_calendar.trading_days(
        date(2024, 1, 1), date(2024, 1, 31), today_fn=lambda: date(2026, 5, 24)
    )
    assert a == b


# ============================================================
# Cross-validation with jugaad_data.holidays
# ============================================================

@pytest.mark.network
def test_overlap_with_jugaad_holidays_is_only_muhurat_trading():
    """LIVE cross-check. Our policy (SPECS §6): NSE recorded a close →
    trading day, full stop. jugaad's `holidays(year)` lists OFFICIAL
    market-closed dates — but NSE also runs Diwali "Muhurat Trading"
    sessions (~1 hour ceremonial trading on Lakshmi Puja) which produce
    real OHLC AND show up in jugaad's holidays list. Those are the only
    expected overlaps; anything else is a bug somewhere upstream."""
    from jugaad_data.holidays import holidays
    td = trading_calendar.trading_days(
        date(2024, 1, 1), date(2024, 12, 31)
    )
    hol = set(holidays(year=2024))
    overlap = set(td) & hol

    # Known Muhurat Trading sessions (Diwali) — verified live:
    # 2024 Diwali (Lakshmi Puja) muhurat session was Nov 1.
    KNOWN_MUHURAT_2024 = {date(2024, 11, 1)}
    unexpected = overlap - KNOWN_MUHURAT_2024
    assert not unexpected, (
        f"unexpected trading-day/holiday overlap in 2024: {sorted(unexpected)}; "
        f"only known-good overlaps are Muhurat Trading sessions "
        f"({sorted(KNOWN_MUHURAT_2024)})"
    )


@pytest.mark.network
def test_offset_trading_days_live_reliance_jan_25():
    """LIVE: the same hand-check, but driven by real NSE data through
    the real load_spot. If this disagrees with the offline test, the
    synthetic _JAN_2024_NSE_DAYS fixture is wrong (and we'd want to
    know)."""
    assert trading_calendar.offset_trading_days(
        date(2024, 1, 25), 15
    ) == date(2024, 1, 4)
