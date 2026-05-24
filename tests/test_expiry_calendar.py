"""Tests for src.data.expiry_calendar. No network — load_bhavcopy_fo
is monkeypatched throughout.

The very first test below is `test_determinism_byte_identical_repeated_calls`:
the entire reason this module exists is to escape jugaad's
`list(set(dts))` non-determinism. If determinism regresses, every Phase-3
backtest's sweep order becomes non-reproducible.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.data import bhavcopy_fo_loader, cache, expiry_calendar
from src.data.errors import MissingDataError

FIXTURES = Path(__file__).parent / "fixtures"


def _redirect_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


def _parsed_legacy_jan25():
    """Parsed §2.4 frame from the legacy fixture (35 rows including the
    RELIANCE Jan-25 expiry options). Sentinel for the hand-check tests."""
    return bhavcopy_fo_loader.parse_legacy(
        (FIXTURES / "bhavcopy_fo_legacy_20240125.csv").read_text(),
        date(2024, 1, 25),
    )


def _make_fake_loader(per_month_frames: dict[tuple[int, int], pd.DataFrame],
                      non_trading_days: set[date] | None = None,
                      call_log: list[date] | None = None):
    """Build a fake `load_bhavcopy_fo`:

      - returns the pre-parsed frame for any day in a configured month
      - raises MissingDataError for any day in `non_trading_days`
      - raises MissingDataError for months not in per_month_frames
      - appends every call to `call_log` if provided (for assertions)
    """
    non_trading_days = non_trading_days or set()

    def fake(td: date, **kw) -> pd.DataFrame:
        if call_log is not None:
            call_log.append(td)
        if td in non_trading_days:
            raise MissingDataError(f"non-trading {td}")
        frame = per_month_frames.get((td.year, td.month))
        if frame is None:
            raise MissingDataError(f"no fixture configured for {td}")
        return frame

    return fake


# ============================================================
# LOAD-BEARING: determinism across repeated calls
# ============================================================

def test_determinism_byte_identical_repeated_calls(monkeypatch, tmp_path):
    """The reason this module exists. Two calls with identical inputs
    must return byte-identical lists."""
    _redirect_cache(monkeypatch, tmp_path)
    jan = _parsed_legacy_jan25()
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        _make_fake_loader({(2024, 1): jan}),
    )

    a = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    b = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    c = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    assert a == b == c
    # And the result is sorted (the loud invariant — if it ever flips to
    # set-order, the equality check above might pass once and fail next)
    assert a == sorted(a)


# ============================================================
# RELIANCE Jan 2024 = [2024-01-25] hand-check (the planned anchor)
# ============================================================

def test_reliance_jan_2024_hand_check(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    jan = _parsed_legacy_jan25()
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        _make_fake_loader({(2024, 1): jan}),
    )
    out = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    assert out == [date(2024, 1, 25)], (
        f"RELIANCE Jan 2024 monthly expiry hand-check failed: got {out}, "
        f"expected [date(2024, 1, 25)]. This is the load-bearing reference "
        f"value the entire Phase-1.3 plan was anchored on."
    )


# ============================================================
# Symbol filtering: only the requested symbol's expiries
# ============================================================

def test_only_requested_symbol_returned(monkeypatch, tmp_path):
    """The bhavcopy has many symbols. monthly_expiries must filter to
    the requested one only — confusion between RELIANCE expiries and,
    say, INFY expiries would silently break the engine."""
    _redirect_cache(monkeypatch, tmp_path)
    jan = _parsed_legacy_jan25()
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        _make_fake_loader({(2024, 1): jan}),
    )
    # Reliance has rows; INFY (or any other symbol not in the trimmed
    # fixture) should return empty.
    rel = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    other = expiry_calendar.monthly_expiries("DOES_NOT_EXIST", date(2024, 1, 1), date(2024, 1, 31))
    assert rel == [date(2024, 1, 25)]
    assert other == []


# ============================================================
# Symbol case insensitivity
# ============================================================

def test_symbol_normalized_to_upper(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    jan = _parsed_legacy_jan25()
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        _make_fake_loader({(2024, 1): jan}),
    )
    upper = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    lower = expiry_calendar.monthly_expiries("reliance", date(2024, 1, 1), date(2024, 1, 31))
    assert upper == lower == [date(2024, 1, 25)]


# ============================================================
# Sampling: skips non-trading days at start of month
# ============================================================

def test_skips_non_trading_days_at_start_of_month(monkeypatch, tmp_path):
    """If days 1, 2, 3 are non-trading, sampler should land on day 4 (or
    the first thereafter) without exploding."""
    _redirect_cache(monkeypatch, tmp_path)
    jan = _parsed_legacy_jan25()
    call_log: list[date] = []
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        _make_fake_loader(
            {(2024, 1): jan},
            non_trading_days={date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)},
            call_log=call_log,
        ),
    )
    out = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    assert out == [date(2024, 1, 25)]
    # Sampler should have tried Jan 1, 2, 3 (all MissingDataError) then 4 (hit)
    assert call_log == [
        date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4),
    ]


# ============================================================
# Empty month: all 7 candidate days non-trading → empty result for that month
# ============================================================

def test_month_with_no_trading_in_first_7_days_returns_empty_and_warns(monkeypatch, tmp_path):
    """Defensive — if all 7 candidate days raise MissingDataError, return
    [] for that month rather than crashing AND emit a warning so the
    operator sees the silent-loss case (per the 26b964e review flag)."""
    import warnings as _w
    _redirect_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        _make_fake_loader(
            {},  # no frames anywhere
            non_trading_days={date(2024, 1, d) for d in range(1, 8)},
        ),
    )
    with _w.catch_warnings(record=True) as wlog:
        _w.simplefilter("always")
        out = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    assert out == []
    matched = [w for w in wlog if "no usable F&O bhavcopy" in str(w.message)]
    assert len(matched) == 1, (
        f"expected one all-7-fail warning, got {len(matched)}: "
        f"{[str(w.message) for w in wlog]}"
    )


def test_multi_month_partial_failure_returns_only_successful_months(monkeypatch, tmp_path):
    """Three-month window where Feb is totally dark (all 7 candidate days
    fail) — Jan and Mar still produce expiries, Feb contributes nothing
    (plus emits a warning). The calendar must not be all-or-nothing."""
    import warnings as _w
    _redirect_cache(monkeypatch, tmp_path)

    def _df(expiry: date) -> pd.DataFrame:
        return pd.DataFrame({
            "instrument": pd.array(["OPTSTK"], dtype="string"),
            "symbol": pd.array(["RELIANCE"], dtype="string"),
            "expiry": pd.Series([pd.Timestamp(expiry)], dtype="datetime64[us]"),
            "strike": [2600.0],
            "option_type": pd.array(["CE"], dtype="string"),
            "open": [10.0], "high": [11.0], "low": [9.0], "close": [10.0],
            "settle_price": [10.0],
            "contracts": [1],
            "oi": pd.array([100], dtype="Int64"),
            "oi_change": pd.array([0], dtype="Int64"),
            "trade_date": pd.Series([pd.Timestamp("2024-01-15")], dtype="datetime64[us]"),
        })

    frames = {(2024, 1): _df(date(2024, 1, 25)), (2024, 3): _df(date(2024, 3, 28))}
    feb_dark = {date(2024, 2, d) for d in range(1, 8)}

    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        _make_fake_loader(frames, non_trading_days=feb_dark),
    )
    with _w.catch_warnings(record=True) as wlog:
        _w.simplefilter("always")
        out = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 3, 31))

    assert out == [date(2024, 1, 25), date(2024, 3, 28)], (
        f"Jan + Mar should succeed even when Feb is dark; got {out}"
    )
    # Exactly one Feb warning
    feb_warns = [w for w in wlog if "no usable F&O bhavcopy" in str(w.message) and "2024-02" in str(w.message)]
    assert len(feb_warns) == 1


def test_on_disk_parquet_is_byte_stable_across_regenerations(monkeypatch, tmp_path):
    """Cache bytes must be stable, not just the return list. A
    sort-then-reset_index regression could leave returns sorted while the
    on-disk row order varies — fine for return, bad for byte-level
    reproducibility audits."""
    _redirect_cache(monkeypatch, tmp_path)
    jan = _parsed_legacy_jan25()
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        _make_fake_loader({(2024, 1): jan}),
    )

    # Build cache twice (force_refresh-equivalent via wiping the parquet)
    expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    bytes_first = cache.expiry_path("RELIANCE").read_bytes()
    # Wipe and rebuild
    cache.expiry_path("RELIANCE").unlink()
    expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    bytes_second = cache.expiry_path("RELIANCE").read_bytes()
    assert bytes_first == bytes_second, (
        "on-disk parquet bytes differ across regenerations — sort/dedupe "
        "ordering is not stable"
    )


# ============================================================
# Cache: second call doesn't re-sample
# ============================================================

def test_cache_hit_skips_resampling(monkeypatch, tmp_path):
    """Sampling a bhavcopy hits the network (in production); the per-symbol
    expiry cache should absorb repeated calls. Mirrors spot_loader /
    bhavcopy_fo_loader's cache contract."""
    _redirect_cache(monkeypatch, tmp_path)
    jan = _parsed_legacy_jan25()
    call_log: list[date] = []
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        _make_fake_loader({(2024, 1): jan}, call_log=call_log),
    )
    expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    n_after_first = len(call_log)
    assert n_after_first >= 1  # at least one fetch happened

    expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    assert len(call_log) == n_after_first, (
        f"second call re-sampled {len(call_log) - n_after_first} bhavcopies — "
        f"per-symbol cache contract broken"
    )


# ============================================================
# Cache: extending window samples only the new months
# ============================================================

def test_extending_window_samples_only_new_months(monkeypatch, tmp_path):
    """First call asks for Jan; second for Jan-Mar; only Feb + Mar should
    be sampled the second time (Jan cached). Avoids the bug class where
    a wider window re-samples everything."""
    _redirect_cache(monkeypatch, tmp_path)
    # Three months, each with its own pretend bhavcopy frame containing
    # a synthesized RELIANCE expiry. The point is to count fetches per month.
    def make_frame_with_expiry(expiry: date) -> pd.DataFrame:
        return pd.DataFrame({
            "instrument": pd.array(["OPTSTK"], dtype="string"),
            "symbol": pd.array(["RELIANCE"], dtype="string"),
            "expiry": pd.Series([pd.Timestamp(expiry)], dtype="datetime64[us]"),
            "strike": [2600.0],
            "option_type": pd.array(["CE"], dtype="string"),
            "open": [10.0], "high": [11.0], "low": [9.0], "close": [10.5],
            "settle_price": [10.5],
            "contracts": [1],
            "oi": pd.array([100], dtype="Int64"),
            "oi_change": pd.array([0], dtype="Int64"),
            "trade_date": pd.Series([pd.Timestamp(expiry - pd.Timedelta(days=20))], dtype="datetime64[us]"),
        })

    frames = {
        (2024, 1): make_frame_with_expiry(date(2024, 1, 25)),
        (2024, 2): make_frame_with_expiry(date(2024, 2, 29)),
        (2024, 3): make_frame_with_expiry(date(2024, 3, 28)),
    }
    call_log: list[date] = []
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        _make_fake_loader(frames, call_log=call_log),
    )

    # First call: Jan only. Expect 1 sample (day 1 = success).
    expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    jan_calls = list(call_log)
    assert len({c.month for c in jan_calls}) == 1  # only Jan touched

    call_log.clear()

    # Second call: Jan-Mar. Jan already cached → no Jan fetch.
    # Feb + Mar fresh → one fetch each.
    out = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 3, 31))
    sampled_months = {c.month for c in call_log}
    assert sampled_months == {2, 3}, (
        f"second call should sample only new months, got months={sampled_months}"
    )
    assert out == [date(2024, 1, 25), date(2024, 2, 29), date(2024, 3, 28)]


# ============================================================
# Window filtering: dont return expiries outside the window
# even if they show up in samples
# ============================================================

def test_filters_expiries_outside_window(monkeypatch, tmp_path):
    """A January bhavcopy lists Jan, Feb, Mar expiries. If caller asks for
    Jan only, return Jan only — don't leak Feb/Mar into the result just
    because they were sampled."""
    _redirect_cache(monkeypatch, tmp_path)
    # Build a frame with multiple RELIANCE expiries
    df = pd.DataFrame({
        "instrument": pd.array(["OPTSTK"]*3, dtype="string"),
        "symbol": pd.array(["RELIANCE"]*3, dtype="string"),
        "expiry": pd.Series([
            pd.Timestamp("2024-01-25"),
            pd.Timestamp("2024-02-29"),
            pd.Timestamp("2024-03-28"),
        ], dtype="datetime64[us]"),
        "strike": [2600.0]*3,
        "option_type": pd.array(["CE"]*3, dtype="string"),
        "open": [10.0]*3, "high": [11.0]*3, "low": [9.0]*3, "close": [10.0]*3,
        "settle_price": [10.0]*3,
        "contracts": [1]*3,
        "oi": pd.array([100]*3, dtype="Int64"),
        "oi_change": pd.array([0]*3, dtype="Int64"),
        "trade_date": pd.Series([pd.Timestamp("2024-01-15")]*3, dtype="datetime64[us]"),
    })
    monkeypatch.setattr(
        bhavcopy_fo_loader, "load_bhavcopy_fo",
        _make_fake_loader({(2024, 1): df}),
    )
    out = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 1, 1), date(2024, 1, 31))
    assert out == [date(2024, 1, 25)]  # Feb/Mar filtered out


# ============================================================
# Input validation
# ============================================================

def test_rejects_from_after_to(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="from_date.*>.*to_date"):
        expiry_calendar.monthly_expiries("RELIANCE", date(2024, 2, 1), date(2024, 1, 1))
