"""Cross-loader tests for offline-mode (SPECS §6a).

The load-bearing property is **uniformity**: every public loader respects
`offline=True` AND the `MORENSE_OFFLINE=1` env var with identical
semantics — cache miss raises `OfflineCacheMiss`. A leaky implementation
(one loader respects it, another doesn't) defeats the whole point of
the env var.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data import (
    bhavcopy_fo_loader,
    cache,
    expiry_calendar,
    options_loader,
    spot_loader,
    trading_calendar,
)
from src.data.errors import OfflineCacheMiss
from src.data.offline import effective_offline


def _redirect_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


# ============================================================
# effective_offline helper
# ============================================================

def test_effective_offline_kwarg_true():
    assert effective_offline(True) is True


def test_effective_offline_kwarg_false():
    assert effective_offline(False) is False


def test_effective_offline_env_var(monkeypatch):
    monkeypatch.setenv("MORENSE_OFFLINE", "1")
    assert effective_offline(False) is True


def test_effective_offline_env_var_other_values_ignored(monkeypatch):
    # Only "1" turns it on — "true", "yes", etc. are NOT honored. Strict
    # spec to avoid surprises.
    monkeypatch.setenv("MORENSE_OFFLINE", "true")
    assert effective_offline(False) is False
    monkeypatch.setenv("MORENSE_OFFLINE", "0")
    assert effective_offline(False) is False


def test_effective_offline_kwarg_or_env(monkeypatch):
    """Either kwarg=True or env=1 triggers offline. Both is fine."""
    monkeypatch.setenv("MORENSE_OFFLINE", "1")
    assert effective_offline(True) is True


# ============================================================
# Each loader: cache miss + offline=True → OfflineCacheMiss
# ============================================================

def test_load_spot_offline_cache_miss_raises(monkeypatch, tmp_path):
    """Cache miss in offline mode must raise — must NOT silently fetch."""
    _redirect_cache(monkeypatch, tmp_path)

    def must_not_be_called(*a, **kw):
        raise RuntimeError("network must not be hit in offline mode")

    monkeypatch.setattr(spot_loader, "stock_df", must_not_be_called)
    with pytest.raises(OfflineCacheMiss, match="spot RELIANCE"):
        spot_loader.load_spot(
            "RELIANCE", date(2024, 1, 2), date(2024, 1, 5),
            today_fn=lambda: date(2026, 5, 24),
            offline=True,
        )


def test_load_bhavcopy_fo_offline_cache_miss_raises(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)

    def must_not_be_called(*a, **kw):
        raise RuntimeError("network must not be hit in offline mode")

    monkeypatch.setattr(bhavcopy_fo_loader, "_fetch_raw", must_not_be_called)
    with pytest.raises(OfflineCacheMiss, match="bhavcopy_fo"):
        bhavcopy_fo_loader.load_bhavcopy_fo(date(2024, 1, 25), offline=True)


def test_load_option_offline_cache_miss_raises(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)

    def must_not_be_called(*a, **kw):
        raise RuntimeError("network must not be hit in offline mode")

    monkeypatch.setattr(options_loader, "derivatives_df", must_not_be_called)
    with pytest.raises(OfflineCacheMiss, match="option RELIANCE"):
        options_loader.load_option(
            "RELIANCE", date(2024, 1, 25), 2620, "CE",
            date(2024, 1, 25), date(2024, 1, 25),
            today_fn=lambda: date(2026, 5, 24),
            offline=True,
        )


def test_monthly_expiries_offline_propagates_OfflineCacheMiss(monkeypatch, tmp_path):
    """Critical: expiry_calendar's `except MissingDataError:` block must
    NOT swallow OfflineCacheMiss. Otherwise an offline cold-cache run
    would silently return [] for every month."""
    _redirect_cache(monkeypatch, tmp_path)

    def must_not_be_called(*a, **kw):
        raise RuntimeError("network must not be hit in offline mode")

    monkeypatch.setattr(bhavcopy_fo_loader, "_fetch_raw", must_not_be_called)
    with pytest.raises(OfflineCacheMiss):
        expiry_calendar.monthly_expiries(
            "RELIANCE", date(2024, 1, 1), date(2024, 1, 31), offline=True
        )


def test_trading_days_offline_cache_miss_raises(monkeypatch, tmp_path):
    """trading_calendar delegates to spot_loader; offline must thread
    through."""
    _redirect_cache(monkeypatch, tmp_path)

    def must_not_be_called(*a, **kw):
        raise RuntimeError("network must not be hit in offline mode")

    monkeypatch.setattr(spot_loader, "stock_df", must_not_be_called)
    with pytest.raises(OfflineCacheMiss):
        trading_calendar.trading_days(
            date(2024, 1, 1), date(2024, 1, 31),
            today_fn=lambda: date(2026, 5, 24),
            offline=True,
        )


# ============================================================
# Cache HIT in offline mode still works (offline ≠ disabled)
# ============================================================

def test_load_spot_offline_cache_hit_works(monkeypatch, tmp_path):
    """Pre-populate cache, then call with offline=True. Should succeed."""
    _redirect_cache(monkeypatch, tmp_path)
    # Pre-populate via a normal mock fetch
    from datetime import datetime

    def fake_stock_df(symbol, from_date, to_date, series="EQ", **kw):
        # Return one row at midnight IST naive
        dates_utc = [datetime(2024, 1, 2) - pd.Timedelta(hours=5, minutes=30)]
        return pd.DataFrame({
            "DATE": pd.to_datetime(dates_utc),
            "SERIES": ["EQ"], "SYMBOL": ["RELIANCE"],
            "OPEN": [100.0], "HIGH": [101.0], "LOW": [99.0],
            "CLOSE": [100.5], "VWAP": [100.2], "VOLUME": [1000],
            "PREV. CLOSE": [100.0], "LTP": [100.5],
            "VALUE": [100500.0], "NO OF TRADES": [10],
            "DELIVERY QTY": [500], "DELIVERY %": [50.0],
        })

    monkeypatch.setattr(spot_loader, "stock_df", fake_stock_df)
    spot_loader.load_spot(
        "RELIANCE", date(2024, 1, 1), date(2024, 1, 5),
        today_fn=lambda: date(2026, 5, 24),
    )

    # Now go offline; cache hit should still work
    def must_not_be_called(*a, **kw):
        raise RuntimeError("offline + cache hit shouldn't fetch")

    monkeypatch.setattr(spot_loader, "stock_df", must_not_be_called)
    out = spot_loader.load_spot(
        "RELIANCE", date(2024, 1, 1), date(2024, 1, 5),
        today_fn=lambda: date(2026, 5, 24),
        offline=True,
    )
    assert len(out) >= 1


# ============================================================
# MORENSE_OFFLINE env var works equivalently to kwarg
# ============================================================

def test_env_var_triggers_offline_mode(monkeypatch, tmp_path):
    """MORENSE_OFFLINE=1 should make a loader behave as if offline=True,
    even when the caller didn't pass the kwarg."""
    _redirect_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("MORENSE_OFFLINE", "1")

    def must_not_be_called(*a, **kw):
        raise RuntimeError("env-set offline mode must not hit network")

    monkeypatch.setattr(bhavcopy_fo_loader, "_fetch_raw", must_not_be_called)
    with pytest.raises(OfflineCacheMiss):
        bhavcopy_fo_loader.load_bhavcopy_fo(date(2024, 1, 25))


# ============================================================
# OfflineCacheMiss is NOT a MissingDataError
# ============================================================

def test_offline_cache_miss_is_not_missing_data_error():
    """The class distinction is the whole point of the design.
    expiry_calendar's `except MissingDataError:` must NOT catch
    OfflineCacheMiss."""
    from src.data.errors import DataError, MissingDataError
    assert issubclass(OfflineCacheMiss, DataError)
    assert not issubclass(OfflineCacheMiss, MissingDataError)
    assert not issubclass(MissingDataError, OfflineCacheMiss)
