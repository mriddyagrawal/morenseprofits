"""Tests for src.data.options_loader. No network — `derivatives_df`
monkeypatched throughout.

The load-bearing test is `test_cross_layer_hand_check_matches_bhavcopy_fo`:
the bhavcopy_fo loader and the options_loader both look at the same
underlying NSE data via different jugaad endpoints; their numbers must
agree. If this test ever turns red, one of the layers is wrong.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Sequence

import pandas as pd
import pytest

from src.data import cache, options_loader
from src.data.errors import MissingDataError


# === fake derivatives_df builder ===
# jugaad returns these columns with DATE at midnight naive (verified live
# in chore(p1.4.prep)) and OI/CHANGE IN OI as float64.

_JUGAAD_COLS = [
    "DATE", "EXPIRY", "OPTION TYPE", "STRIKE PRICE", "OPEN", "HIGH",
    "LOW", "CLOSE", "LTP", "SETTLE PRICE", "TOTAL TRADED QUANTITY",
    "MARKET LOT", "PREMIUM VALUE", "OPEN INTEREST", "CHANGE IN OI", "SYMBOL",
]


def _fake_derivatives(
    symbol: str,
    expiry: date,
    strike: float,
    option_type: str,
    dates: Sequence[date],
    closes: Sequence[float] | None = None,
    ois: Sequence[float | None] | None = None,
    lot_size: int = 250,
):
    n = len(dates)
    if closes is None:
        closes = [10.0 + i for i in range(n)]
    if ois is None:
        ois = [1000.0 + i * 100 for i in range(n)]
    return pd.DataFrame({
        "DATE": pd.to_datetime([datetime(d.year, d.month, d.day) for d in dates]),
        "EXPIRY": pd.to_datetime([datetime(expiry.year, expiry.month, expiry.day)] * n),
        "OPTION TYPE": pd.array([option_type] * n, dtype="string"),
        "STRIKE PRICE": [float(strike)] * n,
        "OPEN": [c - 1 for c in closes],
        "HIGH": [c + 2 for c in closes],
        "LOW": [c - 2 for c in closes],
        "CLOSE": closes,
        "LTP": closes,
        "SETTLE PRICE": closes,
        "TOTAL TRADED QUANTITY": [lot_size * 10 + i for i in range(n)],
        "MARKET LOT": [lot_size] * n,
        "PREMIUM VALUE": [c * lot_size for c in closes],
        "OPEN INTEREST": ois,
        "CHANGE IN OI": [0.0] * n,  # arbitrary
        "SYMBOL": pd.array([symbol.upper()] * n, dtype="string"),
    })


def _patch_derivatives(monkeypatch, factory):
    """Replace derivatives_df as seen by options_loader. factory(symbol,
    from_date, to_date, expiry_date, instrument_type, strike_price,
    option_type) → DataFrame."""
    calls = []

    def fake(symbol, from_date, to_date, expiry_date, instrument_type,
             strike_price=None, option_type=None):
        calls.append({
            "symbol": symbol, "from_date": from_date, "to_date": to_date,
            "expiry_date": expiry_date, "instrument_type": instrument_type,
            "strike_price": strike_price, "option_type": option_type,
        })
        return factory(symbol, from_date, to_date, expiry_date,
                       instrument_type, strike_price, option_type)

    monkeypatch.setattr(options_loader, "derivatives_df", fake)
    return calls


def _redirect_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


# ============================================================
# LOAD-BEARING: cross-layer hand-check vs bhavcopy_fo loader
# ============================================================

def test_cross_layer_hand_check_matches_bhavcopy_fo(monkeypatch, tmp_path):
    """RELIANCE Aug 29 2024 2840 CE has these pinned values from the
    bhavcopy_fo loader (test_udiff_reliance_2840ce_hand_check):
        close=201.70, oi=41500, oi_change=-1500
    Plus from the live derivatives_df exploration:
        lot_size=250, volume=6500 (= 26 contracts × 250 lot)

    The options_loader must return the SAME numbers for the SAME row.
    If the layers disagree, one is wrong. This is the strongest single
    cross-validation we can run without going to two completely
    different data sources."""
    _redirect_cache(monkeypatch, tmp_path)

    def factory(symbol, from_date, to_date, expiry_date, *args, **kw):
        return pd.DataFrame({
            "DATE": pd.to_datetime([datetime(2024, 8, 29)]),
            "EXPIRY": pd.to_datetime([datetime(2024, 8, 29)]),
            "OPTION TYPE": pd.array(["CE"], dtype="string"),
            "STRIKE PRICE": [2840.0],
            "OPEN": [173.00],
            "HIGH": [201.85],
            "LOW": [169.45],
            "CLOSE": [201.70],
            "LTP": [201.40],
            "SETTLE PRICE": [3041.85],
            "TOTAL TRADED QUANTITY": [6500],
            "MARKET LOT": [250],
            "PREMIUM VALUE": [196.61],
            "OPEN INTEREST": [41500.0],
            "CHANGE IN OI": [-1500.0],
            "SYMBOL": pd.array(["RELIANCE"], dtype="string"),
        })

    _patch_derivatives(monkeypatch, factory)
    df = options_loader.load_option(
        "RELIANCE", date(2024, 8, 29), 2840, "CE",
        date(2024, 8, 29), date(2024, 8, 29),
        today_fn=lambda: date(2026, 5, 24),
    )
    assert len(df) == 1
    r = df.iloc[0]
    # The four numbers shared with bhavcopy_fo's hand-check
    assert r["close"] == 201.70
    assert r["oi"] == 41500
    assert r["oi_change"] == -1500
    assert r["lot_size"] == 250
    # volume in share units = 26 contracts × 250 lot
    assert r["volume"] == 6500


# ============================================================
# Schema (SPECS §2.2)
# ============================================================

def test_returned_schema_matches_specs_2_2(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    factory = lambda s, f, t, e, *a, **k: _fake_derivatives(
        s, e, 2620, "CE", [date(2024, 1, 25)], lot_size=250
    )
    _patch_derivatives(monkeypatch, factory)
    df = options_loader.load_option(
        "RELIANCE", date(2024, 1, 25), 2620, "CE",
        date(2024, 1, 25), date(2024, 1, 25),
        today_fn=lambda: date(2026, 5, 24),
    )
    expected_cols = [
        "date", "symbol", "expiry", "option_type", "strike",
        "open", "high", "low", "close", "ltp", "settle_price",
        "lot_size", "volume", "oi", "oi_change",
    ]
    assert list(df.columns) == expected_cols
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert pd.api.types.is_datetime64_any_dtype(df["expiry"])
    assert df["symbol"].dtype == pd.StringDtype()
    assert df["option_type"].dtype == pd.StringDtype()
    for c in ("strike", "open", "high", "low", "close", "ltp", "settle_price"):
        assert df[c].dtype.name == "float64"
    assert df["lot_size"].dtype.name == "int64"
    assert df["volume"].dtype.name == "int64"
    assert df["oi"].dtype.name == "Int64"
    assert df["oi_change"].dtype.name == "Int64"


# ============================================================
# Full contract lifetime: first fetch pulls ~120 days, not the requested window
# ============================================================

def test_first_fetch_pulls_full_contract_lifetime(monkeypatch, tmp_path):
    """Caller asks for a 3-day window; loader should fetch the full
    contract lifetime (~120 days back from expiry) so a wider follow-up
    call hits cache."""
    _redirect_cache(monkeypatch, tmp_path)
    expiry = date(2024, 1, 25)
    captured = {}

    def factory(symbol, from_date, to_date, expiry_date, *args, **kw):
        captured["from_date"] = from_date
        captured["to_date"] = to_date
        # Return a lifetime's worth of rows so subset assertions hold
        dates = [expiry - timedelta(days=i) for i in range(100, -1, -10)]
        return _fake_derivatives(symbol, expiry, 2620, "CE", dates)

    _patch_derivatives(monkeypatch, factory)
    options_loader.load_option(
        "RELIANCE", expiry, 2620, "CE",
        date(2024, 1, 23), date(2024, 1, 25),
        today_fn=lambda: date(2026, 5, 24),
    )
    # The fetch window must be ~120 days back from expiry, not the
    # 3-day window the caller asked for.
    assert captured["to_date"] == expiry
    days_back = (expiry - captured["from_date"]).days
    assert days_back >= 100, (
        f"first fetch only went {days_back} days back; should be ~120"
    )


# ============================================================
# Closed expiry: immutable on disk, second call doesn't refetch
# ============================================================

def test_closed_expiry_cache_hit_skips_refetch(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    expiry = date(2024, 1, 25)
    dates = [expiry - timedelta(days=i) for i in range(20, -1, -1)]
    calls = _patch_derivatives(
        monkeypatch,
        lambda s, f, t, e, *a, **k: _fake_derivatives(s, expiry, 2620, "CE", dates),
    )
    today_fn = lambda: date(2026, 5, 24)

    options_loader.load_option(
        "RELIANCE", expiry, 2620, "CE", date(2024, 1, 1), date(2024, 1, 25),
        today_fn=today_fn,
    )
    assert len(calls) == 1

    # Re-patch derivatives_df to RAISE — second call must succeed from cache
    def raiser(*args, **kw):
        raise RuntimeError("must not fetch on cache hit")

    monkeypatch.setattr(options_loader, "derivatives_df", raiser)
    out = options_loader.load_option(
        "RELIANCE", expiry, 2620, "CE", date(2024, 1, 10), date(2024, 1, 20),
        today_fn=today_fn,
    )
    assert len(out) > 0  # window filter still works


# ============================================================
# Empty fetch → MissingDataError
# ============================================================

def test_empty_fetch_raises_missing_data(monkeypatch, tmp_path):
    """Illegitimate strike or unlisted contract: derivatives_df returns
    empty. Loader must surface as MissingDataError, not a silent
    empty-DataFrame."""
    _redirect_cache(monkeypatch, tmp_path)
    _patch_derivatives(
        monkeypatch,
        lambda *a, **kw: pd.DataFrame(columns=_JUGAAD_COLS),
    )
    with pytest.raises(MissingDataError, match="no derivatives data"):
        options_loader.load_option(
            "RELIANCE", date(2024, 1, 25), 9999, "CE",  # bogus strike
            date(2024, 1, 1), date(2024, 1, 25),
            today_fn=lambda: date(2026, 5, 24),
        )


# ============================================================
# Datetime rejection on expiry — same pattern as bhavcopy_fo_path
# ============================================================

def test_rejects_datetime_expiry(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    _patch_derivatives(monkeypatch, lambda *a, **kw: _fake_derivatives(
        "X", date(2024, 1, 25), 100, "CE", [date(2024, 1, 25)]
    ))
    with pytest.raises(TypeError, match="datetime"):
        options_loader.load_option(
            "RELIANCE", datetime(2024, 1, 25), 2620, "CE",
            date(2024, 1, 1), date(2024, 1, 25),
            today_fn=lambda: date(2026, 5, 24),
        )


# ============================================================
# Option type validation
# ============================================================

def test_rejects_bad_option_type(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="option_type must be"):
        options_loader.load_option(
            "RELIANCE", date(2024, 1, 25), 2620, "BUY",
            date(2024, 1, 1), date(2024, 1, 25),
            today_fn=lambda: date(2026, 5, 24),
        )


def test_rejects_from_after_to(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="from_date.*>.*to_date"):
        options_loader.load_option(
            "RELIANCE", date(2024, 1, 25), 2620, "CE",
            date(2024, 1, 26), date(2024, 1, 25),
            today_fn=lambda: date(2026, 5, 24),
        )


# ============================================================
# Force refresh re-fetches
# ============================================================

def test_force_refresh_refetches(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    expiry = date(2024, 1, 25)
    calls = _patch_derivatives(
        monkeypatch,
        lambda s, f, t, e, *a, **k: _fake_derivatives(
            s, expiry, 2620, "CE", [expiry - timedelta(days=i) for i in range(5, -1, -1)]
        ),
    )
    today_fn = lambda: date(2026, 5, 24)

    options_loader.load_option(
        "RELIANCE", expiry, 2620, "CE", date(2024, 1, 1), date(2024, 1, 25),
        today_fn=today_fn,
    )
    options_loader.load_option(
        "RELIANCE", expiry, 2620, "CE", date(2024, 1, 1), date(2024, 1, 25),
        today_fn=today_fn,
    )
    assert len(calls) == 1  # cache hit
    options_loader.load_option(
        "RELIANCE", expiry, 2620, "CE", date(2024, 1, 1), date(2024, 1, 25),
        today_fn=today_fn, force_refresh=True,
    )
    assert len(calls) == 2


# ============================================================
# Window filter: full lifetime cached, narrow returns narrow
# ============================================================

def test_window_filter_returns_only_requested_dates(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    expiry = date(2024, 1, 25)
    dates = [expiry - timedelta(days=i) for i in range(20, -1, -1)]
    _patch_derivatives(
        monkeypatch,
        lambda *a, **kw: _fake_derivatives("RELIANCE", expiry, 2620, "CE", dates),
    )

    out = options_loader.load_option(
        "RELIANCE", expiry, 2620, "CE",
        date(2024, 1, 23), date(2024, 1, 25),
        today_fn=lambda: date(2026, 5, 24),
    )
    # Window is 3 days (Jan 23, 24, 25)
    assert len(out) == 3
    assert out["date"].min() == pd.Timestamp("2024-01-23")
    assert out["date"].max() == pd.Timestamp("2024-01-25")


# ============================================================
# Open-expiry refetch policy: cache only refreshes if stale
# ============================================================

def test_open_expiry_refetches_when_stale(monkeypatch, tmp_path):
    """Open-expiry contract with stale cache (cached max date < today)
    triggers re-fetch; full max date does not."""
    _redirect_cache(monkeypatch, tmp_path)
    expiry = date(2026, 6, 26)  # future-expiry

    # Sequence-able factory: tracks which "today" we're on
    state = {"today": date(2026, 5, 1)}
    def factory(*args, **kw):
        dates = [date(2026, 5, 1) - timedelta(days=i) for i in range(5, -1, -1)]
        # On second fetch, include later dates too
        if state["today"] >= date(2026, 5, 10):
            dates += [date(2026, 5, 2), date(2026, 5, 3), date(2026, 5, 4),
                      date(2026, 5, 5)]
        return _fake_derivatives("RELIANCE", expiry, 2620, "CE", dates)

    calls = _patch_derivatives(monkeypatch, factory)
    today_fn = lambda: state["today"]

    options_loader.load_option(
        "RELIANCE", expiry, 2620, "CE", date(2026, 5, 1), date(2026, 5, 1),
        today_fn=today_fn,
    )
    assert len(calls) == 1
    # Same today: no refetch
    options_loader.load_option(
        "RELIANCE", expiry, 2620, "CE", date(2026, 5, 1), date(2026, 5, 1),
        today_fn=today_fn,
    )
    assert len(calls) == 1

    # Advance today: cache is stale → refetch
    state["today"] = date(2026, 5, 10)
    options_loader.load_option(
        "RELIANCE", expiry, 2620, "CE", date(2026, 5, 1), date(2026, 5, 10),
        today_fn=today_fn,
    )
    assert len(calls) == 2


# ============================================================
# Non-midnight DATE → loud assertion failure
# ============================================================

def test_non_midnight_date_fails_loud(monkeypatch, tmp_path):
    """If a future jugaad rev starts returning DATE at non-midnight
    (e.g. 18:30:00 like stock_df), we want a loud AssertionError, NOT
    silent date drift downstream."""
    _redirect_cache(monkeypatch, tmp_path)
    expiry = date(2024, 1, 25)

    def factory(*args, **kw):
        df = _fake_derivatives("RELIANCE", expiry, 2620, "CE", [expiry])
        # Inject 18:30 like stock_df does
        df["DATE"] = pd.to_datetime([datetime(2024, 1, 25, 18, 30, 0)])
        return df

    _patch_derivatives(monkeypatch, factory)
    with pytest.raises(AssertionError, match="non-midnight"):
        options_loader.load_option(
            "RELIANCE", expiry, 2620, "CE",
            date(2024, 1, 25), date(2024, 1, 25),
            today_fn=lambda: date(2026, 5, 24),
        )


# ============================================================
# Strike integer guard inherited from cache.option_path
# ============================================================

def test_fractional_strike_raises_via_cache_guard(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    with pytest.raises(cache.StrikeNotIntegerError):
        options_loader.load_option(
            "RELIANCE", date(2024, 1, 25), 2620.5, "CE",
            date(2024, 1, 25), date(2024, 1, 25),
            today_fn=lambda: date(2026, 5, 24),
        )
