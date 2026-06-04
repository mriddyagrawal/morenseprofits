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


@pytest.fixture(autouse=True)
def _clear_calendar_cache_per_test():
    """Perf #2 (2026-06-04): trading_calendar now memoizes the wide
    calendar tuple via ``_full_calendar_cached``. The LRU is process-
    level state and would leak across tests within the same module —
    test A populates it with synthetic data X, test B's monkeypatched
    spot_loader returns synthetic data Y but the cache returns X.

    Clearing before AND after each test keeps tests hermetic without
    forcing every test to do it manually."""
    trading_calendar._clear_calendar_cache_for_test()
    yield
    trading_calendar._clear_calendar_cache_for_test()


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


# ============================================================
# Perf #2 (2026-06-04): bisect-based fast path equivalence
# ============================================================

def test_perf_2_repeated_calls_populate_cache_once(monkeypatch, tmp_path):
    """LOAD-BEARING: ``_full_calendar_cached`` populates once per
    process; subsequent ``trading_days`` / ``offset_trading_days``
    calls bisect the cached tuple instead of re-invoking ``load_spot``.

    The populate phase calls ``load_spot`` ONCE PER YEAR in the
    history window (perf #2 fix 2026-06-04: per-year iteration so
    that an uncached year raising ``OfflineCacheMiss`` doesn't abort
    the whole load). After the cache is populated, the count must
    stay constant across many bisect-served calls."""
    _redirect_cache(monkeypatch, tmp_path)
    call_count = {"n": 0}

    def counting_load_spot(symbol, from_date, to_date, *,
                           force_refresh=False, today_fn=date.today,
                           offline=False, **kw):
        call_count["n"] += 1
        in_window = [d for d in _JAN_2024_NSE_DAYS if from_date <= d <= to_date]
        return pd.DataFrame({
            "date": pd.Series(
                [pd.Timestamp(d) for d in in_window], dtype="datetime64[us]",
            ),
            "symbol": pd.array(["RELIANCE"] * len(in_window), dtype="string"),
            "close": [100.0] * len(in_window),
        })

    monkeypatch.setattr(spot_loader, "load_spot", counting_load_spot)
    today = lambda: date(2026, 5, 24)
    # First call triggers the per-year populate (one load_spot per
    # year in the 10-year window + current = 11 calls). Subsequent
    # calls bisect the cached tuple — NO additional load_spot.
    trading_calendar.offset_trading_days(date(2024, 1, 25), 5, today_fn=today)
    populate_count = call_count["n"]
    assert populate_count >= 1, "populate must invoke load_spot at least once"
    # Now do 99 more mixed calls. Cache is warm — count must not grow.
    for _ in range(50):
        trading_calendar.offset_trading_days(date(2024, 1, 25), 5, today_fn=today)
        trading_calendar.trading_days(
            date(2024, 1, 5), date(2024, 1, 25), today_fn=today,
        )
    assert call_count["n"] == populate_count, (
        f"cache should not re-populate; populate={populate_count}, "
        f"after-50×2-calls={call_count['n']}"
    )


def test_perf_2_fast_path_matches_slow_path_for_realistic_anchor(
    monkeypatch, tmp_path,
):
    """Equivalence: fast-path bisect MUST return the same date as
    the buffer-doubling slow path for an anchor that lies WITHIN the
    cached calendar range. Anti-regression on the index arithmetic —
    an off-by-one would silently shift every backtest's entry/exit
    by a day."""
    _redirect_cache(monkeypatch, tmp_path)
    _patch_load_spot(monkeypatch, _JAN_2024_NSE_DAYS)
    today = lambda: date(2026, 5, 24)

    fast = trading_calendar.offset_trading_days(
        date(2024, 1, 25), 15, today_fn=today,
    )
    # Force slow path by directly calling it (caller would only enter
    # the slow path when out-of-cache; for tests we exercise it
    # explicitly to pin equivalence).
    slow = trading_calendar._offset_trading_days_slow(
        date(2024, 1, 25), 15, today_fn=today,
    )
    assert fast == slow == date(2024, 1, 4)


def test_perf_2_clear_cache_helper_actually_clears(monkeypatch, tmp_path):
    """Pin the ``_clear_calendar_cache_for_test`` contract — it must
    drop the LRU so a subsequent monkeypatched ``load_spot`` is
    re-invoked. Required for test hermeticity."""
    _redirect_cache(monkeypatch, tmp_path)
    call_count = {"n": 0}

    def counting(symbol, from_date, to_date, *, force_refresh=False,
                 today_fn=date.today, offline=False, **kw):
        call_count["n"] += 1
        in_window = [d for d in _JAN_2024_NSE_DAYS if from_date <= d <= to_date]
        return pd.DataFrame({
            "date": pd.Series(
                [pd.Timestamp(d) for d in in_window], dtype="datetime64[us]",
            ),
            "symbol": pd.array(["RELIANCE"] * len(in_window), dtype="string"),
            "close": [100.0] * len(in_window),
        })

    monkeypatch.setattr(spot_loader, "load_spot", counting)
    today = lambda: date(2026, 5, 24)

    trading_calendar.offset_trading_days(date(2024, 1, 25), 5, today_fn=today)
    populate_count = call_count["n"]
    assert populate_count >= 1, "populate must invoke load_spot at least once"

    # Cleared → next call must re-populate (≥1 additional invocation).
    trading_calendar._clear_calendar_cache_for_test()
    trading_calendar.offset_trading_days(date(2024, 1, 25), 5, today_fn=today)
    assert call_count["n"] >= 2 * populate_count, (
        f"cache clear failed; populate count stayed at {populate_count} "
        f"after the post-clear call (got {call_count['n']})"
    )


def test_perf_2_per_year_offline_cache_miss_skipped(monkeypatch, tmp_path):
    """Grill #6 anti-regression (logic-review bc3c4fe). cc2282a wired
    a single-range ``load_spot`` call inside ``_full_calendar_cached``;
    under cache_only=True the operator's prefetch covered 2024-2026
    but the 10-year window asked for 2016-onward, so the first
    uncached year raised ``OfflineCacheMiss``, propagated, and every
    sweep cell skipped (90,000/90,000 in 1.1s; ca8486f / 0a08d44).

    The fix iterates year-by-year and catches the per-year exception,
    accumulating only successful years. This test pins that behavior:
    a partial cache (2016-2023 raise; 2024-2026 succeed) must yield a
    non-empty calendar covering only the available years. Without
    this test, a future refactor back to a single-range call would
    silently re-introduce cc2282a's bug AND pytest would still pass
    (because no other test exercises the partial-cache path).
    """
    _redirect_cache(monkeypatch, tmp_path)

    # Synthetic load_spot that mimics the operator's actual cache
    # state: years before 2024 raise OfflineCacheMiss; 2024+ load
    # the synthetic _JAN_2024_NSE_DAYS subset.
    from src.data.errors import OfflineCacheMiss

    def partial_load_spot(symbol, from_date, to_date, *,
                          force_refresh=False, today_fn=date.today,
                          offline=False, **kw):
        if from_date.year < 2024:
            raise OfflineCacheMiss(
                f"synthetic: spot for {symbol} year {from_date.year} not in cache"
            )
        in_window = [d for d in _JAN_2024_NSE_DAYS if from_date <= d <= to_date]
        return pd.DataFrame({
            "date": pd.Series(
                [pd.Timestamp(d) for d in in_window], dtype="datetime64[us]",
            ),
            "symbol": pd.array(["RELIANCE"] * len(in_window), dtype="string"),
            "close": [100.0] * len(in_window),
        })

    monkeypatch.setattr(spot_loader, "load_spot", partial_load_spot)
    today = lambda: date(2026, 5, 24)

    # trading_days for the 2024 window must succeed even though
    # ~7 years before it raised OfflineCacheMiss during populate.
    days = trading_calendar.trading_days(
        date(2024, 1, 1), date(2024, 1, 31), today_fn=today, offline=True,
    )
    assert len(days) == len(_JAN_2024_NSE_DAYS), (
        f"per-year populate didn't recover after OfflineCacheMiss; "
        f"expected {len(_JAN_2024_NSE_DAYS)} 2024 days, got {len(days)}"
    )
    # offset_trading_days must succeed too (the production cell path).
    out = trading_calendar.offset_trading_days(
        date(2024, 1, 25), 15, today_fn=today, offline=True,
    )
    assert out == date(2024, 1, 4), (
        f"per-year populate broke offset_trading_days; got {out}"
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
