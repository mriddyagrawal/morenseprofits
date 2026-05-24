"""Tests for src.universe.momentum. No network — load_spot monkeypatched.

The load-bearing test is `test_determinism_byte_identical`: the
classifier output feeds into Phase-4 sweep tagging, so non-determinism
here would make every sweep's regime labels drift.
"""
from __future__ import annotations

import warnings
from datetime import date, timedelta
from typing import Iterable

import pandas as pd
import pytest

from src.data import spot_loader, trading_calendar
from src.data.errors import MissingDataError, OfflineCacheMiss
from src.universe.momentum import classify_momentum


# Fake spot frame builder: returns a single-row frame with the given close
# at as_of and a "lookback" close N days earlier.
def _make_fake_spot(returns: dict[str, float]):
    """Build a fake load_spot that produces a frame implying the given
    trailing return per symbol. Lookback close pinned at 100; as_of close
    = 100 * (1 + return)."""
    def fake(symbol, from_date, to_date, *, force_refresh=False,
             today_fn=date.today, offline=False, **kw):
        if symbol not in returns:
            raise MissingDataError(f"no data for {symbol}")
        denom = 100.0
        numer = denom * (1 + returns[symbol])
        return pd.DataFrame({
            "date": pd.Series(
                [pd.Timestamp(from_date), pd.Timestamp(to_date)],
                dtype="datetime64[us]",
            ),
            "symbol": pd.array([symbol, symbol], dtype="string"),
            "close": [denom, numer],
        })

    return fake


def _patch_calendar(monkeypatch, lookback_date: date):
    """Stub offset_trading_days to return a fixed lookback_date so the
    momentum tests don't have to drive a real trading calendar."""
    def fake(anchor, n, *, today_fn=date.today, offline=False):
        return lookback_date

    monkeypatch.setattr(trading_calendar, "offset_trading_days", fake)


# ============================================================
# LOAD-BEARING: determinism
# ============================================================

def test_determinism_byte_identical(monkeypatch):
    """Two calls with the same inputs must return == dicts (and the
    contained lists are == too). Phase-4 sweep tagging breaks silently
    if the regime label flips between calls."""
    _patch_calendar(monkeypatch, date(2024, 1, 2))
    returns = {"A": 0.30, "B": 0.10, "C": 0.05, "D": -0.05, "E": -0.20, "F": -0.30}
    monkeypatch.setattr(spot_loader, "load_spot", _make_fake_spot(returns))

    a = classify_momentum(date(2024, 7, 1), list(returns), today_fn=lambda: date(2026, 5, 24))
    b = classify_momentum(date(2024, 7, 1), list(returns), today_fn=lambda: date(2026, 5, 24))
    c = classify_momentum(date(2024, 7, 1), list(returns), today_fn=lambda: date(2026, 5, 24))
    assert a == b == c
    for key in ("bullish", "neutral", "non_bullish"):
        assert a[key] == sorted(a[key]), f"{key} list not alphabetical"


# ============================================================
# Tercile boundary correctness (top-heavy per SPECS §6b.2)
# ============================================================

def test_tercile_split_n6(monkeypatch):
    """n=6 → ceil(6/3)=2 bullish, floor(6/3)=2 non_bullish, remainder=2 neutral.
    A's return is highest, F's lowest."""
    _patch_calendar(monkeypatch, date(2024, 1, 2))
    returns = {"A": 0.30, "B": 0.20, "C": 0.10, "D": -0.05, "E": -0.15, "F": -0.25}
    monkeypatch.setattr(spot_loader, "load_spot", _make_fake_spot(returns))

    out = classify_momentum(date(2024, 7, 1), list(returns), today_fn=lambda: date(2026, 5, 24))
    assert out == {
        "bullish": ["A", "B"],       # ceil(6/3) = 2 top
        "neutral": ["C", "D"],       # middle 2
        "non_bullish": ["E", "F"],   # floor(6/3) = 2 bottom
    }


def test_tercile_split_n40_top_heavy(monkeypatch):
    """n=40 → ceil(40/3)=14 bullish, floor(40/3)=13 non_bullish, 13 neutral.
    Matches the canonical blue_chip-size case in SPECS §6b.2."""
    _patch_calendar(monkeypatch, date(2024, 1, 2))
    syms = [f"S{i:02d}" for i in range(40)]
    # Descending returns S00 > S01 > ... > S39
    returns = {s: 1.0 - i * 0.01 for i, s in enumerate(syms)}
    monkeypatch.setattr(spot_loader, "load_spot", _make_fake_spot(returns))

    out = classify_momentum(date(2024, 7, 1), syms, today_fn=lambda: date(2026, 5, 24))
    assert len(out["bullish"]) == 14, f"bullish should be ceil(40/3)=14, got {len(out['bullish'])}"
    assert len(out["neutral"]) == 13
    assert len(out["non_bullish"]) == 13
    # Top-heavy invariant: bullish has at least as many as non_bullish
    assert len(out["bullish"]) >= len(out["non_bullish"])


def test_tie_break_by_symbol_name_ascending(monkeypatch):
    """Two symbols with identical returns → tie broken by symbol name
    ascending (lower-alphabetical wins the higher rank)."""
    _patch_calendar(monkeypatch, date(2024, 1, 2))
    # All 6 symbols have identical returns; tercile boundaries land at
    # positions 2 and 4. Names B, A should be the bullish pair (alphabetical
    # tie-break: A before B).
    returns = {s: 0.10 for s in ("A", "B", "C", "D", "E", "F")}
    monkeypatch.setattr(spot_loader, "load_spot", _make_fake_spot(returns))

    out = classify_momentum(date(2024, 7, 1), list(returns), today_fn=lambda: date(2026, 5, 24))
    # Ascending tie-break: A, B end up at top.
    assert out["bullish"] == ["A", "B"]
    assert out["non_bullish"] == ["E", "F"]


# ============================================================
# Delisted-symbol policy (load-bearing)
# ============================================================

def test_delisted_symbol_dropped_with_warning(monkeypatch):
    """If load_spot raises MissingDataError for a symbol, the classifier
    drops it with a warning and continues with the rest.
    One stale name in blue_chip must not break the whole classifier."""
    _patch_calendar(monkeypatch, date(2024, 1, 2))
    # DELISTED has no data; others classify normally.
    returns = {"A": 0.30, "B": 0.10, "C": -0.20}
    fake = _make_fake_spot(returns)

    def fake_with_delisted(symbol, *a, **kw):
        if symbol == "DELISTED":
            raise MissingDataError(f"no data for {symbol}")
        return fake(symbol, *a, **kw)

    monkeypatch.setattr(spot_loader, "load_spot", fake_with_delisted)

    with warnings.catch_warnings(record=True) as wlog:
        warnings.simplefilter("always")
        out = classify_momentum(
            date(2024, 7, 1),
            ["A", "B", "C", "DELISTED"],
            today_fn=lambda: date(2026, 5, 24),
        )

    # DELISTED appears in NO output bucket
    all_returned = out["bullish"] + out["neutral"] + out["non_bullish"]
    assert "DELISTED" not in all_returned
    # Remaining 3 symbols classified normally (1/1/1 split for n=3)
    assert len(all_returned) == 3
    # Exactly one warning naming DELISTED
    drop_warns = [w for w in wlog if "DELISTED" in str(w.message)]
    assert len(drop_warns) == 1


# ============================================================
# OfflineCacheMiss propagates (per SPECS §6a)
# ============================================================

def test_offline_cache_miss_propagates(monkeypatch):
    """OfflineCacheMiss is NOT a MissingDataError — must NOT be swallowed
    by the delisted-symbol catch. Otherwise an offline run on a cold
    cache would silently drop every symbol and return empty buckets."""
    _patch_calendar(monkeypatch, date(2024, 1, 2))

    def raiser(symbol, *a, **kw):
        raise OfflineCacheMiss(f"cold cache for {symbol}")

    monkeypatch.setattr(spot_loader, "load_spot", raiser)
    with pytest.raises(OfflineCacheMiss):
        classify_momentum(
            date(2024, 7, 1),
            ["A", "B", "C"],
            today_fn=lambda: date(2026, 5, 24),
            offline=True,
        )


# ============================================================
# Edge cases
# ============================================================

def test_empty_universe_returns_empty_buckets():
    """Don't crash on an empty universe; return all-empty buckets."""
    out = classify_momentum(date(2024, 7, 1), [], today_fn=lambda: date(2026, 5, 24))
    assert out == {"bullish": [], "neutral": [], "non_bullish": []}


def test_lookback_zero_raises():
    with pytest.raises(ValueError, match="lookback_trading_days"):
        classify_momentum(
            date(2024, 7, 1), ["A", "B"],
            lookback_trading_days=0,
            today_fn=lambda: date(2026, 5, 24),
        )


# ============================================================
# Lookback uses offset_trading_days (the holiday-trap fix)
# ============================================================

def test_lookback_routed_through_offset_trading_days(monkeypatch):
    """Critical: lookback_date must come from offset_trading_days, NOT
    from naive `as_of - timedelta(days=N)`. Otherwise lookback can land
    on a NSE holiday → load_spot returns 0 rows → divide-by-zero."""
    calls = []

    def fake_offset(anchor, n, *, today_fn=date.today, offline=False):
        calls.append((anchor, n))
        # Return a deliberately weird date that no naive arithmetic
        # would produce; if classifier passes this to load_spot, we
        # know it routed through offset_trading_days.
        return date(2023, 12, 21)

    monkeypatch.setattr(trading_calendar, "offset_trading_days", fake_offset)

    received_from = []

    def fake_spot(symbol, from_date, to_date, **kw):
        received_from.append(from_date)
        return pd.DataFrame({
            "date": pd.Series([pd.Timestamp(from_date), pd.Timestamp(to_date)], dtype="datetime64[us]"),
            "symbol": pd.array([symbol, symbol], dtype="string"),
            "close": [100.0, 110.0],
        })

    monkeypatch.setattr(spot_loader, "load_spot", fake_spot)

    classify_momentum(
        date(2024, 7, 1), ["A"],
        lookback_trading_days=126,
        today_fn=lambda: date(2026, 5, 24),
    )

    # offset_trading_days called once with the right anchor + n
    assert calls == [(date(2024, 7, 1), 126)]
    # The lookback_date from offset_trading_days propagated to load_spot
    assert received_from == [date(2023, 12, 21)]
