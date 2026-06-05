"""Tests for src.analytics.ivp — F5 (TS-IVP) + F6 (cross-sectional rank).

All tests synthesize pd.Series fixtures in-memory; ``compute_ivp``
end-to-end test monkeypatches ``load_iv_history`` so no parquet I/O
is required.

LOAD-BEARING tests:
  - ``test_time_series_ivp_median_day_pins_50``: hand-checked
    arithmetic on a uniform series.
  - ``test_time_series_ivp_today_nan_returns_nan``: F5's documented
    bug fix (silent-rank-NaN-as-0).
  - ``test_time_series_ivp_uses_len_valid_denominator``: closes
    reviewer d8620f8 GRILL 3 pattern in this module.
  - ``test_top_n_by_ivp_tiebreak_alphabetical``: SPECS §6c.3
    byte-identical determinism.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.analytics import ivp as ivp_mod
from src.analytics.ivp import (
    DEFAULT_IV_SERIES,
    IVP_LOOKBACK_TD,
    IVP_MIN_VALID_FRACTION,
    compute_ivp,
    time_series_ivp,
    top_n_by_ivp,
)


# ============================================================
# Helpers
# ============================================================

def _make_series(values: list[float], start: date = date(2024, 1, 1)) -> pd.Series:
    """Build a date-indexed pd.Series with consecutive calendar
    days. (TS-IVP only cares about ORDER + lookback count, not
    actual trading-day spacing — so calendar days are fine for
    testing.)"""
    idx = pd.date_range(start=start, periods=len(values), freq="D")
    return pd.Series(values, index=idx)


# ============================================================
# time_series_ivp — known values + edge cases
# ============================================================

def test_time_series_ivp_midpoint_value_pins_known_rank():
    """LOAD-BEARING. Uniform ascending series 0.10, 0.11, ..., 0.34
    (25 values), lookback=25. as_of at position 12 → trailing
    window covers positions 0..12 (13 values, monotone increasing).
    Today's value = 0.22; (valid < 0.22).sum() = 12 (the values
    0.10..0.21 strictly less). Denominator = len(valid) = 13.
    Rank = 12/13 * 100 ≈ 92.307692."""
    values = [0.10 + 0.01 * i for i in range(25)]
    s = _make_series(values)
    today = s.index[12].date()
    rank = time_series_ivp(s, today, lookback_td=25)
    assert rank == pytest.approx(12.0 / 13.0 * 100.0, abs=1e-9)


def test_time_series_ivp_top_value_returns_high_percentile():
    """Today = max of trailing window. 25 ascending values,
    as_of = last day, lookback = 25 → window = all 25. Today is
    strictly greater than 24 values. Rank = 24/25 * 100 = 96.0."""
    values = [0.10 + 0.01 * i for i in range(25)]
    s = _make_series(values)
    today = s.index[24].date()
    assert time_series_ivp(s, today, lookback_td=25) == pytest.approx(96.0, abs=1e-9)


def test_time_series_ivp_bottom_value_returns_zero():
    """Today = min of trailing window. DESCENDING series 0.34,
    0.33, ..., 0.10 (25 values). as_of = last day → today =
    0.10 (the min). Lookback = 25 → window = all 25. (valid <
    0.10).sum() = 0. Rank = 0/25 * 100 = 0.0.

    Note: tests with as_of at position 0 fail the 50%-of-lookback
    floor (window has only 1 element) — that case is covered by
    ``test_time_series_ivp_insufficient_history_returns_nan``."""
    values = [0.34 - 0.01 * i for i in range(25)]
    s = _make_series(values)
    today = s.index[24].date()
    assert time_series_ivp(s, today, lookback_td=25) == 0.0


def test_time_series_ivp_today_nan_returns_nan():
    """LOAD-BEARING F5 bug fix: ``(window < NaN).sum()`` silently
    returns 0 — would render a missing-IV day as 0th percentile
    (cheapest vol ever) and falsely trigger the entry filter.
    Memoir §21.4 F5 documents this as the original bug guarded
    by the explicit ``pd.isna(today)`` check."""
    values = [0.20] * 20 + [float("nan")] + [0.20] * 4
    s = _make_series(values)
    today = s.index[20].date()
    assert np.isnan(time_series_ivp(s, today, lookback_td=25))


def test_time_series_ivp_insufficient_history_returns_nan():
    """Lookback=252 but only 100 valid values → < 50% floor →
    NaN. Memoir §21.4 F5 + reviewer d8620f8 GRILL 1: floor is
    50% of LOOKBACK_TD, NOT of realized window."""
    values = [0.20] * 100
    s = _make_series(values)
    today = s.index[99].date()
    # 100 < 0.5 * 252 = 126 → NaN.
    assert np.isnan(time_series_ivp(s, today, lookback_td=252))


def test_time_series_ivp_uses_len_valid_denominator():
    """LOAD-BEARING — pins the reviewer d8620f8 GRILL 3 pattern
    in this module. 50-element ascending series with 5 NaN
    scattered in the early part; as_of at the last position so
    the trailing 50-element window captures all of them.

    Sanity: 45 valid entries (50 - 5 NaN); today = 0.59 (max);
    (valid < 0.59).sum() = 44.
      - WRONG denominator (len(window)=50): 44/50 * 100 = 88.0
      - RIGHT denominator (len(valid)=45):  44/45 * 100 ≈ 97.78

    The two differ by ~10 percentile points — easy to
    distinguish in test, easy to spot in code review if this
    drifts back."""
    values = [0.10 + 0.01 * i for i in range(50)]
    for i in (5, 10, 15, 20, 25):
        values[i] = float("nan")
    s = _make_series(values)
    today = s.index[49].date()
    rank = time_series_ivp(s, today, lookback_td=50)
    assert rank == pytest.approx(44.0 / 45.0 * 100.0, abs=1e-9)
    # Explicit comparison to the WRONG denominator — drift detector.
    assert rank != pytest.approx(44.0 / 50.0 * 100.0, abs=0.1)


def test_time_series_ivp_as_of_predates_series_returns_nan():
    """as_of < series start → no anchor position → NaN."""
    s = _make_series([0.20] * 200, start=date(2024, 6, 1))
    assert np.isnan(time_series_ivp(s, date(2024, 1, 1), lookback_td=10))


def test_time_series_ivp_non_trading_day_rounds_down():
    """``as_of`` on a weekend / holiday → use the most recent
    series date <= as_of. Series has daily frequency Mon-Fri;
    a Saturday as_of should resolve to the Friday before."""
    # Build a series with explicit Mon-Fri dates.
    mondays = pd.bdate_range(start="2024-01-01", periods=20, freq="B")
    values = [0.10 + 0.01 * i for i in range(20)]
    s = pd.Series(values, index=mondays)
    # Saturday after the last weekday.
    last_friday = mondays[-1].date()
    saturday = last_friday + pd.Timedelta(days=1).to_pytimedelta()
    rank_friday = time_series_ivp(s, last_friday, lookback_td=20)
    rank_saturday = time_series_ivp(s, saturday, lookback_td=20)
    assert rank_friday == rank_saturday


def test_time_series_ivp_empty_series_returns_nan():
    """Empty input → NaN (defensive; should never happen in
    practice but pin the behavior)."""
    s = pd.Series([], index=pd.DatetimeIndex([]), dtype=float)
    assert np.isnan(time_series_ivp(s, date(2024, 1, 1)))


def test_time_series_ivp_rejects_non_series():
    with pytest.raises(TypeError, match="must be pd.Series"):
        time_series_ivp([0.20, 0.21], date(2024, 1, 1))


def test_time_series_ivp_rejects_lookback_too_small():
    s = _make_series([0.20] * 10)
    with pytest.raises(ValueError, match="must be >= 2"):
        time_series_ivp(s, s.index[5].date(), lookback_td=1)


# ============================================================
# compute_ivp — convenience wrapper with monkeypatched I/O
# ============================================================

def test_compute_ivp_reads_default_series(monkeypatch):
    """Round-trip via the convenience function: stub
    load_iv_history → return a frame with all 3 IV columns →
    confirm compute_ivp ranks on ``iv_cmi30_excl7`` by default."""
    dates = pd.date_range("2024-01-01", periods=300, freq="D")
    # Build a series where excl7 puts today at 80th-ish percentile
    # but iv_front would put it at 20th. If compute_ivp is using
    # the default (excl7), we should see the high value.
    excl7_vals = np.linspace(0.10, 0.30, 300)  # ascending
    front_vals = np.linspace(0.30, 0.10, 300)  # descending
    df = pd.DataFrame({
        "date": dates,
        "iv_front": front_vals,
        "iv_cmi30_raw": excl7_vals,
        "iv_cmi30_excl7": excl7_vals,
        "atm_strike_front": [100.0] * 300,
        "n_expiries_used": [3] * 300,
    })

    def fake_load(symbol):
        assert symbol == "RELIANCE"
        return df

    monkeypatch.setattr(ivp_mod, "load_iv_history", fake_load)
    # As-of the last day → excl7 today is the max → should rank
    # near 100. iv_front today is the min → would rank near 0.
    rank = compute_ivp("RELIANCE", dates[-1].date(), lookback_td=252)
    assert rank > 90.0


def test_compute_ivp_accepts_alt_series(monkeypatch):
    """Explicit override of the default column."""
    dates = pd.date_range("2024-01-01", periods=300, freq="D")
    excl7_vals = np.linspace(0.10, 0.30, 300)
    front_vals = np.linspace(0.30, 0.10, 300)
    df = pd.DataFrame({
        "date": dates,
        "iv_front": front_vals,
        "iv_cmi30_raw": excl7_vals,
        "iv_cmi30_excl7": excl7_vals,
        "atm_strike_front": [100.0] * 300,
        "n_expiries_used": [3] * 300,
    })
    monkeypatch.setattr(ivp_mod, "load_iv_history", lambda sym: df)
    # iv_front today is the MIN of its series → rank near 0.
    rank = compute_ivp(
        "RELIANCE", dates[-1].date(), series="iv_front", lookback_td=252,
    )
    assert rank < 5.0


def test_compute_ivp_rejects_unknown_series_column(monkeypatch):
    """Asking for a column not in the parquet → loud failure."""
    df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=10),
                       "iv_cmi30_excl7": [0.20] * 10})
    monkeypatch.setattr(ivp_mod, "load_iv_history", lambda sym: df)
    with pytest.raises(ValueError, match="no column"):
        compute_ivp("RELIANCE", date(2024, 1, 10), series="iv_nonexistent")


# ============================================================
# top_n_by_ivp — cross-sectional rank
# ============================================================

def test_top_n_by_ivp_returns_descending():
    """Default n=5; output is the 5 highest-IVP symbols
    sorted descending."""
    ivp = {"A": 50.0, "B": 90.0, "C": 70.0, "D": 30.0, "E": 80.0,
           "F": 40.0, "G": 95.0}
    assert top_n_by_ivp(ivp, n=3) == ["G", "B", "E"]


def test_top_n_by_ivp_tiebreak_alphabetical():
    """LOAD-BEARING per SPECS §6c.3 byte-identical determinism.
    Three symbols all at 80.0 → must come out alphabetically."""
    ivp = {"ZEEL": 80.0, "ACC": 80.0, "MAR": 80.0, "RELIANCE": 50.0}
    assert top_n_by_ivp(ivp, n=3) == ["ACC", "MAR", "ZEEL"]


def test_top_n_by_ivp_drops_nan():
    """NaN entries excluded from the rank."""
    ivp = {"A": 90.0, "B": float("nan"), "C": 70.0,
           "D": 80.0, "E": float("nan")}
    assert top_n_by_ivp(ivp, n=5) == ["A", "D", "C"]


def test_top_n_by_ivp_drops_none():
    """None entries also excluded (defensive — caller might
    pass a dict built from Optional[float] returns)."""
    ivp = {"A": 90.0, "B": None, "C": 70.0}
    assert top_n_by_ivp(ivp, n=5) == ["A", "C"]


def test_top_n_by_ivp_returns_fewer_when_universe_smaller():
    """n=10 but only 3 valid → return all 3."""
    ivp = {"A": 90.0, "B": 80.0, "C": 70.0}
    assert top_n_by_ivp(ivp, n=10) == ["A", "B", "C"]


def test_top_n_by_ivp_empty_universe_returns_empty():
    assert top_n_by_ivp({}, n=5) == []


def test_top_n_by_ivp_all_nan_returns_empty():
    ivp = {"A": float("nan"), "B": float("nan")}
    assert top_n_by_ivp(ivp, n=5) == []


def test_top_n_by_ivp_zero_n_returns_empty():
    """``n=0`` is a degenerate but legal request — return []."""
    ivp = {"A": 90.0, "B": 80.0}
    assert top_n_by_ivp(ivp, n=0) == []


def test_top_n_by_ivp_rejects_negative_n():
    with pytest.raises(ValueError, match="n must be >= 0"):
        top_n_by_ivp({"A": 90.0}, n=-1)


# ============================================================
# Constants — pin the spec-driven values
# ============================================================

def test_constants_match_memoir_spec():
    """PORTFOLIO_MEMOIR.md §21.4 F5 + operator lock-in. If any of
    these drifts without a memoir revision, that's a spec-drift bug."""
    assert IVP_LOOKBACK_TD == 252
    assert IVP_MIN_VALID_FRACTION == 0.5
    assert DEFAULT_IV_SERIES == "iv_cmi30_excl7"
