"""Unit tests for src.data.spot_loader. No network.

The single load-bearing test in this file is `test_date_shift_regression`:
if that ever turns red, every backtest's entry/exit-date prices are
off-by-one. Every other test pins one of the four invariants the loader
contracts in its module docstring.
"""
from __future__ import annotations

import warnings
from datetime import date, datetime
from typing import Sequence

import pandas as pd
import pytest

from src.data import cache, spot_loader


# === fake jugaad response builder ===
# jugaad's stock_df returns a DataFrame with these exact column names, and
# its DATE column is a naive datetime at 18:30:00 — which is 00:00 IST of
# the next day (UTC + 5:30 IST offset). We must mimic that shape precisely.

_JUGAAD_COLS = [
    "DATE", "SERIES", "OPEN", "HIGH", "LOW", "PREV. CLOSE", "LTP",
    "CLOSE", "VWAP", "VOLUME", "VALUE", "NO OF TRADES",
    "DELIVERY QTY", "DELIVERY %", "SYMBOL",
]


def _fake_jugaad(symbol: str, ist_dates: Sequence[date], closes: Sequence[float] | None = None):
    """Build a frame in jugaad's raw shape for the given IST trading dates.

    closes defaults to a deterministic ramp (100, 101, 102, …) so tests can
    cross-check values after the loader normalizes.
    """
    if closes is None:
        closes = [100.0 + i for i in range(len(ist_dates))]
    # IST date -> UTC datetime at 18:30 of the previous calendar day
    utc_naive = [datetime(d.year, d.month, d.day) - pd.Timedelta(hours=5, minutes=30) for d in ist_dates]
    return pd.DataFrame({
        # ms unit matches real jugaad output; ns vs ms is functionally
        # equivalent post +5h30m but matching exactly keeps the fake honest.
        "DATE": pd.to_datetime(utc_naive).astype("datetime64[ms]"),
        "SERIES": ["EQ"] * len(ist_dates),
        "OPEN": [c - 1 for c in closes],
        "HIGH": [c + 2 for c in closes],
        "LOW": [c - 2 for c in closes],
        "PREV. CLOSE": [c - 0.5 for c in closes],
        "LTP": closes,
        "CLOSE": closes,
        "VWAP": closes,
        "VOLUME": [1_000_000 + i * 1000 for i in range(len(ist_dates))],
        "VALUE": [c * 1e6 for c in closes],
        "NO OF TRADES": [10000 + i for i in range(len(ist_dates))],
        "DELIVERY QTY": [500_000 for _ in ist_dates],
        "DELIVERY %": [50.0 for _ in ist_dates],
        "SYMBOL": [symbol.upper()] * len(ist_dates),
    })


def _patch_jugaad(monkeypatch, factory):
    """Replace stock_df as seen by spot_loader. `factory(symbol, from, to, series)` returns a frame."""
    calls = []

    def fake(symbol, from_date, to_date, series="EQ", **kw):
        calls.append((symbol, from_date, to_date, series))
        return factory(symbol, from_date, to_date, series)

    monkeypatch.setattr(spot_loader, "stock_df", fake)
    return calls


def _redirect_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


# === THE load-bearing test ===

def test_date_shift_regression(monkeypatch, tmp_path):
    """LOAD-BEARING. jugaad returns trading-date-IST as UTC-18:30-the-day-before.
    The loader must shift +5h30m so single-day filters work and engine entry/exit
    prices are not off-by-one. If this fails, every backtest is wrong."""
    _redirect_cache(monkeypatch, tmp_path)

    def factory(symbol, from_date, to_date, series):
        # Three IST trading days; closes chosen to be uniquely identifiable
        return _fake_jugaad(symbol, [date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)],
                            closes=[2611.7, 2583.3, 2596.65])

    _patch_jugaad(monkeypatch, factory)

    today_fn = lambda: date(2026, 5, 24)  # year 2024 is "closed"
    out = spot_loader.load_spot("RELIANCE", date(2024, 1, 2), date(2024, 1, 2), today_fn=today_fn)

    assert len(out) == 1, f"single-day filter must return exactly 1 row, got {len(out)}"
    assert out.iloc[0]["date"] == pd.Timestamp("2024-01-02 00:00:00"), (
        f"row date must land at midnight IST naive, got {out.iloc[0]['date']!r}"
    )
    assert out.iloc[0]["close"] == 2611.7, (
        f"single-day filter returned wrong row; close={out.iloc[0]['close']!r}"
    )
    assert out.iloc[0]["symbol"] == "RELIANCE"


# === invariant 1: full-year parquet on disk regardless of caller window ===

def test_full_year_parquet_invariant(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    # Build a full-year-shaped response (12 monthly-spaced "trading days" is enough)
    full_year_dates = [date(2024, m, 15) for m in range(1, 13)]

    def factory(symbol, from_date, to_date, series):
        # Loader must have requested the WHOLE year, not just the caller's window
        assert from_date == date(2024, 1, 1), f"expected full-year fetch start, got {from_date}"
        assert to_date == date(2024, 12, 31), f"expected full-year fetch end, got {to_date}"
        return _fake_jugaad(symbol, full_year_dates)

    _patch_jugaad(monkeypatch, factory)
    today_fn = lambda: date(2026, 5, 24)

    # Caller asks for a tiny window
    out = spot_loader.load_spot("X", date(2024, 3, 1), date(2024, 3, 31), today_fn=today_fn)
    assert len(out) == 1  # only March 15 falls inside

    # But the on-disk parquet must contain the WHOLE year
    cached = cache.read(cache.spot_path("X", 2024))
    assert len(cached) == 12, f"parquet must hold full year, got {len(cached)} rows"


# === invariant 2: closed-year immutable; second call hits cache only ===

def test_closed_year_immutable_and_no_network_on_hit(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    dates = [date(2024, m, 15) for m in range(1, 13)]

    calls = _patch_jugaad(monkeypatch, lambda s, f, t, se: _fake_jugaad(s, dates))
    today_fn = lambda: date(2026, 5, 24)

    spot_loader.load_spot("X", date(2024, 1, 1), date(2024, 12, 31), today_fn=today_fn)
    assert len(calls) == 1

    # Now monkeypatch jugaad to RAISE — second call must succeed purely from cache
    def raise_if_called(symbol, from_date, to_date, series="EQ"):
        raise RuntimeError(
            f"network must not be called on cache hit; got ({symbol},{from_date},{to_date})"
        )
    monkeypatch.setattr(spot_loader, "stock_df", raise_if_called)

    out = spot_loader.load_spot("X", date(2024, 6, 1), date(2024, 8, 31), today_fn=today_fn)
    assert len(out) == 3  # Jun, Jul, Aug


# === invariant 3: length-checked refetch refuses to shrink the cache ===

def test_partial_response_refuses_to_shrink_cache(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    # Day 1: today=Jun-15, NSE returns 100 daily rows Jan 1 - Jun 14
    dense_dates = pd.date_range("2024-01-01", "2024-06-14", freq="B").date.tolist()

    state = {"phase": "full"}

    def factory(symbol, from_date, to_date, series):
        if state["phase"] == "full":
            return _fake_jugaad(symbol, dense_dates)
        # phase "partial": NSE flakes, returns fewer rows
        return _fake_jugaad(symbol, dense_dates[:50])

    _patch_jugaad(monkeypatch, factory)

    spot_loader.load_spot("X", date(2024, 1, 1), date(2024, 6, 14), today_fn=lambda: date(2024, 6, 15))
    cached_full = cache.read(cache.spot_path("X", 2024))
    full_len = len(cached_full)

    # Day 2: today=Jun-16, NSE returns fewer rows -> loader must keep cache and warn
    state["phase"] = "partial"
    with warnings.catch_warnings(record=True) as wlog:
        warnings.simplefilter("always")
        spot_loader.load_spot("X", date(2024, 1, 1), date(2024, 6, 14), today_fn=lambda: date(2024, 6, 16))

    cached_after = cache.read(cache.spot_path("X", 2024))
    assert len(cached_after) == full_len, (
        f"cache must not shrink on partial response; was {full_len}, now {len(cached_after)}"
    )
    assert any("partial NSE response" in str(w.message) for w in wlog), (
        "expected a partial-response warning"
    )


# === invariant 4: returned frame is monotonic ascending ===

def test_partial_response_with_dropped_dates(monkeypatch, tmp_path):
    """LOAD-BEARING. The previous length-only check passed any same-length
    response — even one that DROPPED a date from the middle and added a
    spurious one. The subset check must reject this and keep the cache."""
    _redirect_cache(monkeypatch, tmp_path)
    full = pd.date_range("2024-01-01", "2024-06-14", freq="B").date.tolist()  # ~118 dates
    # Day-2 fresh: same length, but one date in the middle dropped and
    # one spurious "future" date added in place. Length-only check would
    # silently overwrite the cache with this lossy frame.
    n = len(full)
    middle_idx = n // 2
    dropped_date = full[middle_idx]
    spurious = date(2024, 6, 30)
    assert spurious not in full
    dropped_then_padded = full[:middle_idx] + full[middle_idx + 1 :] + [spurious]
    assert len(dropped_then_padded) == n  # same length — defeats length-only check

    state = {"phase": "full"}

    def factory(symbol, from_date, to_date, series):
        if state["phase"] == "full":
            return _fake_jugaad(symbol, full)
        return _fake_jugaad(symbol, dropped_then_padded)

    _patch_jugaad(monkeypatch, factory)
    spot_loader.load_spot("X", date(2024, 1, 1), date(2024, 6, 14), today_fn=lambda: date(2024, 6, 15))
    cached_before = cache.read(cache.spot_path("X", 2024))
    assert len(cached_before) == n
    assert pd.Timestamp(dropped_date) in cached_before["date"].tolist()

    state["phase"] = "dropped"
    with warnings.catch_warnings(record=True) as wlog:
        warnings.simplefilter("always")
        spot_loader.load_spot("X", date(2024, 1, 1), date(2024, 6, 14), today_fn=lambda: date(2024, 6, 16))

    cached_after = cache.read(cache.spot_path("X", 2024))
    assert len(cached_after) == n, "cache length must not change"
    # Critical: the date that was dropped from the fresh frame must STILL be in cache.
    assert pd.Timestamp(dropped_date) in cached_after["date"].tolist(), (
        f"subset check failed — date {dropped_date} got removed from cache"
    )
    # Spurious date from fresh must NOT have leaked into cache.
    assert pd.Timestamp(spurious) not in cached_after["date"].tolist(), (
        f"spurious date {spurious} leaked into cache"
    )
    assert any("partial NSE response" in str(w.message) for w in wlog), (
        "expected partial-response warning"
    )


def test_symbol_and_series_have_matching_dtype(monkeypatch, tmp_path):
    """Both string columns must use the same na_value sentinel so that
    dropna(subset=[...]) behaves consistently across them."""
    _redirect_cache(monkeypatch, tmp_path)
    _patch_jugaad(monkeypatch, lambda s, f, t, se: _fake_jugaad(s, [date(2024, 1, 2), date(2024, 1, 3)]))
    out = spot_loader.load_spot("X", date(2024, 1, 1), date(2024, 12, 31), today_fn=lambda: date(2026, 5, 24))
    # Both should be the explicit "string" StringDtype, not the
    # scalar-broadcast version that uses na_value=nan.
    assert out["symbol"].dtype == pd.StringDtype()
    assert out["series"].dtype == pd.StringDtype()
    assert out["symbol"].dtype == out["series"].dtype


def test_t0_series_rows_filtered_at_read_boundary_f9(monkeypatch, tmp_path):
    """F9 (logic-review 1347b8c, 2026-06-03): cached spot parquets can
    carry NSE T0-series rows alongside the EQ-series prints — typically
    single-trade micro-volume rows on the SAME date. Pre-fix
    ``load_spot`` returned both rows; downstream consumers (engine ATM
    picker, realized-vol computation, entry/exit_spot fetch) took
    ``iloc[0]`` order-dependently. The T0 row's close was copied from
    the EQ row but its OHLC was a single-print degenerate shape, which
    contaminated realized-vol (spurious zero-return day → understates
    vol → optimistic margin).

    Fix: ``load_spot`` filters ``series == "EQ"`` at the read-time
    boundary. Defense-in-depth even though ``_fetch_year`` already
    passes ``series="EQ"`` to jugaad (the upstream filter doesn't
    always hold + legacy caches may have been populated under a
    pathway that didn't filter).

    Fixture: a frame carrying TWO rows on 2024-08-29 — one EQ-series
    real print, one T0-series micro-volume duplicate. Assert load_spot
    returns the EQ row only.
    """
    _redirect_cache(monkeypatch, tmp_path)
    # Build a hand-crafted frame: 3 real EQ dates plus a T0 duplicate
    # on the middle date. Mirrors the NSE T0-series shape per F9.
    eq_dates = [date(2024, 8, 28), date(2024, 8, 29), date(2024, 8, 30)]
    eq_closes = [100.0, 105.0, 110.0]
    eq_frame = _fake_jugaad("X", eq_dates, eq_closes)
    # T0 row for 2024-08-29: close matches EQ; OHLC degenerate single
    # print (open=high=low=close); micro-volume.
    t0_row = pd.DataFrame({
        "DATE": eq_frame.iloc[[1]]["DATE"].values,
        "SERIES": ["T0"],
        "OPEN": [105.0], "HIGH": [105.0], "LOW": [105.0],
        "PREV. CLOSE": [100.0], "LTP": [105.0], "CLOSE": [105.0],
        "VWAP": [105.0], "VOLUME": [2], "VALUE": [210.0],
        "NO OF TRADES": [1], "DELIVERY QTY": [2], "DELIVERY %": [100.0],
        "SYMBOL": ["X"],
    }).astype({"DATE": "datetime64[ms]"})
    contaminated = pd.concat([eq_frame, t0_row], ignore_index=True)

    _patch_jugaad(monkeypatch, lambda s, f, t, se: contaminated)
    out = spot_loader.load_spot(
        "X", date(2024, 1, 1), date(2024, 12, 31),
        today_fn=lambda: date(2026, 5, 24),
    )
    # No date duplicates — the T0 row got filtered.
    assert out["date"].is_unique, (
        f"T0 row not filtered; got duplicate dates: "
        f"{out['date'][out['date'].duplicated()].tolist()}"
    )
    # Exactly 3 EQ rows survive.
    assert len(out) == 3
    assert out["series"].tolist() == ["EQ", "EQ", "EQ"]
    # The 2024-08-29 row is the EQ one (volume = 1_000_001 from the
    # _fake_jugaad fixture, not the T0 row's volume of 2).
    aug29 = out[out["date"] == pd.Timestamp("2024-08-29")].iloc[0]
    assert aug29["volume"] != 2, (
        "load_spot returned the T0 micro-volume row instead of the EQ row"
    )


def test_returned_frame_is_monotonic(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    # Hand jugaad an out-of-order response — loader must sort it
    shuffled = [date(2024, 1, 5), date(2024, 1, 2), date(2024, 1, 4), date(2024, 1, 3)]
    _patch_jugaad(monkeypatch, lambda s, f, t, se: _fake_jugaad(s, shuffled))

    out = spot_loader.load_spot("X", date(2024, 1, 1), date(2024, 12, 31), today_fn=lambda: date(2026, 5, 24))
    assert out["date"].is_monotonic_increasing, (
        f"loader output not monotonic: {out['date'].tolist()}"
    )


# === today_fn injection works for current-year clamping ===

def test_today_fn_clamps_current_year_fetch(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    fixed_today = date(2024, 6, 1)
    seen_to = []

    def factory(symbol, from_date, to_date, series):
        seen_to.append(to_date)
        return _fake_jugaad(symbol, [date(2024, 1, 15), date(2024, 3, 15), date(2024, 5, 15)])

    _patch_jugaad(monkeypatch, factory)
    spot_loader.load_spot("X", date(2024, 1, 1), date(2024, 12, 31), today_fn=lambda: fixed_today)

    assert seen_to == [fixed_today], (
        f"current-year fetch must clamp to today_fn(), saw {seen_to}"
    )


# === multi-year span fetches each year exactly once ===

def test_multi_year_span_fetches_each_year_once(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    fetched_years = []

    def factory(symbol, from_date, to_date, series):
        fetched_years.append(from_date.year)
        return _fake_jugaad(symbol, [date(from_date.year, 6, 15)])

    _patch_jugaad(monkeypatch, factory)
    spot_loader.load_spot("X", date(2022, 12, 1), date(2024, 1, 31), today_fn=lambda: date(2026, 5, 24))
    assert sorted(fetched_years) == [2022, 2023, 2024]


# === input validation ===

def test_rejects_from_after_to(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    _patch_jugaad(monkeypatch, lambda s, f, t, se: _fake_jugaad(s, []))
    with pytest.raises(ValueError, match="from_date.*>.*to_date"):
        spot_loader.load_spot("X", date(2024, 2, 1), date(2024, 1, 1), today_fn=lambda: date(2026, 5, 24))


# === force_refresh re-fetches even when cache exists ===

def test_force_refresh_refetches(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    fetch_count = {"n": 0}

    def factory(symbol, from_date, to_date, series):
        fetch_count["n"] += 1
        return _fake_jugaad(symbol, [date(2024, 1, 15)])

    _patch_jugaad(monkeypatch, factory)
    today = lambda: date(2026, 5, 24)

    spot_loader.load_spot("X", date(2024, 1, 1), date(2024, 12, 31), today_fn=today)
    spot_loader.load_spot("X", date(2024, 1, 1), date(2024, 12, 31), today_fn=today)  # cache hit
    assert fetch_count["n"] == 1
    spot_loader.load_spot("X", date(2024, 1, 1), date(2024, 12, 31), today_fn=today, force_refresh=True)
    assert fetch_count["n"] == 2
