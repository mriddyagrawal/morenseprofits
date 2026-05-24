"""Cache-hit telemetry tests (SPECS §6a follow-up).

The load-bearing test is `test_warn_fires_on_cold_fetch_when_env_set`:
opt-in via MORENSE_WARN_ON_FETCH=1; a Phase-4 sweep with this set
surfaces every accidental network call as a warning.
"""
from __future__ import annotations

import warnings
from datetime import date, datetime

import pandas as pd
import pytest

from src.data import (
    bhavcopy_fo_loader,
    cache,
    options_loader,
    spot_loader,
)
from src.data import telemetry


def _redirect_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


# ============================================================
# warn_on_fetch_enabled — strict env-var spec
# ============================================================

def test_warn_on_fetch_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MORENSE_WARN_ON_FETCH", raising=False)
    assert telemetry.warn_on_fetch_enabled() is False


def test_warn_on_fetch_enabled_only_for_literal_1(monkeypatch):
    monkeypatch.setenv("MORENSE_WARN_ON_FETCH", "1")
    assert telemetry.warn_on_fetch_enabled() is True
    monkeypatch.setenv("MORENSE_WARN_ON_FETCH", "true")
    assert telemetry.warn_on_fetch_enabled() is False
    monkeypatch.setenv("MORENSE_WARN_ON_FETCH", "yes")
    assert telemetry.warn_on_fetch_enabled() is False
    monkeypatch.setenv("MORENSE_WARN_ON_FETCH", "0")
    assert telemetry.warn_on_fetch_enabled() is False


def test_warn_fetch_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("MORENSE_WARN_ON_FETCH", raising=False)
    with warnings.catch_warnings(record=True) as wlog:
        warnings.simplefilter("always")
        telemetry.warn_fetch("spot_loader", "RELIANCE 2024")
    assert wlog == []


def test_warn_fetch_emits_when_enabled(monkeypatch):
    monkeypatch.setenv("MORENSE_WARN_ON_FETCH", "1")
    with warnings.catch_warnings(record=True) as wlog:
        warnings.simplefilter("always")
        telemetry.warn_fetch("spot_loader", "RELIANCE 2024")
    assert len(wlog) == 1
    msg = str(wlog[0].message)
    assert "spot_loader" in msg
    assert "RELIANCE 2024" in msg


# ============================================================
# LOAD-BEARING: each loader emits a warning on cold-cache fetch
# ============================================================

def _fake_stock_df(symbol, from_date, to_date, series="EQ", **kw):
    """Minimal stock_df mock at midnight IST naive."""
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


def test_load_spot_warns_on_cold_fetch(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("MORENSE_WARN_ON_FETCH", "1")
    monkeypatch.setattr(spot_loader, "stock_df", _fake_stock_df)

    with warnings.catch_warnings(record=True) as wlog:
        warnings.simplefilter("always")
        spot_loader.load_spot(
            "RELIANCE", date(2024, 1, 1), date(2024, 1, 3),
            today_fn=lambda: date(2026, 5, 24),
        )

    fetch_warns = [w for w in wlog if "spot_loader" in str(w.message)]
    assert len(fetch_warns) == 1
    assert "RELIANCE 2024" in str(fetch_warns[0].message)


def test_load_spot_hot_call_does_not_warn(monkeypatch, tmp_path):
    """Cache HIT must NOT emit a fetch warning. Otherwise a Phase-4
    sweep with a warm cache would spam thousands of false-positives."""
    _redirect_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("MORENSE_WARN_ON_FETCH", "1")
    monkeypatch.setattr(spot_loader, "stock_df", _fake_stock_df)

    # Cold fetch first
    spot_loader.load_spot(
        "RELIANCE", date(2024, 1, 1), date(2024, 1, 3),
        today_fn=lambda: date(2026, 5, 24),
    )

    # Hot call — no fetch warning expected
    with warnings.catch_warnings(record=True) as wlog:
        warnings.simplefilter("always")
        spot_loader.load_spot(
            "RELIANCE", date(2024, 1, 1), date(2024, 1, 3),
            today_fn=lambda: date(2026, 5, 24),
        )
    fetch_warns = [w for w in wlog if "spot_loader" in str(w.message)
                   and "cache miss" in str(w.message)]
    assert fetch_warns == []


def test_load_bhavcopy_fo_warns_on_cold_fetch(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("MORENSE_WARN_ON_FETCH", "1")
    # Mock _fetch_raw with a valid legacy-format response
    raw = (
        "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,"
        "CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP\n"
        "OPTSTK,RELIANCE,25-Jan-2024,2620,CE,10,11,9,10.5,10.5,1,0.5,250,250,25-JAN-2024\n"
    )

    def fake_fetch_legacy(td):
        return raw

    monkeypatch.setattr(bhavcopy_fo_loader, "_fetch_legacy", fake_fetch_legacy)

    with warnings.catch_warnings(record=True) as wlog:
        warnings.simplefilter("always")
        bhavcopy_fo_loader.load_bhavcopy_fo(date(2024, 1, 25))

    fetch_warns = [w for w in wlog if "bhavcopy_fo_loader" in str(w.message)]
    assert len(fetch_warns) == 1
    assert "2024-01-25" in str(fetch_warns[0].message)


def test_load_option_warns_on_cold_fetch(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("MORENSE_WARN_ON_FETCH", "1")

    def fake_derivatives(*a, **kw):
        return pd.DataFrame({
            "DATE": pd.to_datetime([datetime(2024, 1, 25)]),
            "EXPIRY": pd.to_datetime([datetime(2024, 1, 25)]),
            "OPTION TYPE": pd.array(["CE"], dtype="string"),
            "STRIKE PRICE": [2620.0],
            "OPEN": [10.0], "HIGH": [11.0], "LOW": [9.0], "CLOSE": [10.5],
            "LTP": [10.5], "SETTLE PRICE": [10.5],
            "TOTAL TRADED QUANTITY": [250], "MARKET LOT": [250],
            "PREMIUM VALUE": [10.5],
            "OPEN INTEREST": [1000.0], "CHANGE IN OI": [100.0],
            "SYMBOL": pd.array(["RELIANCE"], dtype="string"),
        })

    monkeypatch.setattr(options_loader, "derivatives_df", fake_derivatives)

    with warnings.catch_warnings(record=True) as wlog:
        warnings.simplefilter("always")
        options_loader.load_option(
            "RELIANCE", date(2024, 1, 25), 2620, "CE",
            date(2024, 1, 25), date(2024, 1, 25),
            today_fn=lambda: date(2026, 5, 24),
        )

    fetch_warns = [w for w in wlog if "options_loader" in str(w.message)]
    assert len(fetch_warns) == 1
    msg = str(fetch_warns[0].message)
    assert "RELIANCE" in msg and "2024-01-25" in msg and "2620-CE" in msg


# ============================================================
# Off by default — no warning unless env set
# ============================================================

def test_no_warnings_without_env_var(monkeypatch, tmp_path):
    """Default behavior: no fetch warnings emitted. Avoids spam during
    legitimate cold-cache work (verify scripts, first sweep run)."""
    _redirect_cache(monkeypatch, tmp_path)
    monkeypatch.delenv("MORENSE_WARN_ON_FETCH", raising=False)
    monkeypatch.setattr(spot_loader, "stock_df", _fake_stock_df)

    with warnings.catch_warnings(record=True) as wlog:
        warnings.simplefilter("always")
        spot_loader.load_spot(
            "RELIANCE", date(2024, 1, 1), date(2024, 1, 3),
            today_fn=lambda: date(2026, 5, 24),
        )

    fetch_warns = [w for w in wlog if "cache miss" in str(w.message)]
    assert fetch_warns == []
