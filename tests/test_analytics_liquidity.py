"""Tests for src.analytics.liquidity — F11.

Pure-math tests synthesize the bhavcopy frame in-memory; the
symbol-aware tests monkeypatch ``load_bhavcopy_fo`` +
``trading_calendar``.

LOAD-BEARING:
  - test_score_is_mean_of_per_day_totals (pins the documented
    deviation from the memoir's per-row mean sketch)
  - test_score_drops_OPTIDX_rows (§11.b single-stock scope)
  - test_top_n_alphabetical_tiebreak (SPECS §6c.3 determinism)
  - test_compute_liquidity_scores_loads_each_day_once (perf
    contract — proves the batch is doing what its docstring says)
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src.analytics import liquidity as liq_mod
from src.analytics.liquidity import (
    LIQUIDITY_INSTRUMENT,
    LIQUIDITY_LOOKBACK_TD,
    LIQUIDITY_MIN_VALID_FRACTION,
    compute_liquidity_score,
    compute_liquidity_scores,
    liquidity_score,
    top_n_by_liquidity,
)


# ============================================================
# Fixtures
# ============================================================

def _row(
    symbol: str,
    trade_date: date,
    *,
    instrument: str = "OPTSTK",
    contracts: int = 100,
    strike: float = 100.0,
    option_type: str = "CE",
) -> dict:
    """One SPECS §2.4-shaped bhavcopy row, narrowed to the
    columns the F11 kernel reads."""
    return {
        "symbol": symbol,
        "instrument": instrument,
        "contracts": contracts,
        "trade_date": trade_date,
        # Extras for downstream filters that might be added — keep
        # the synthetic frame realistic.
        "strike": strike,
        "option_type": option_type,
    }


def _synthetic_window(
    symbol: str,
    days: list[date],
    *,
    contracts_per_day: list[int] | int = 1000,
    rows_per_day: int = 3,
    instrument: str = "OPTSTK",
) -> pd.DataFrame:
    """Build a multi-day frame with ``rows_per_day`` rows per
    trade date. Each row carries (contracts_per_day / rows_per_day)
    contracts, so the SUM-per-day equals ``contracts_per_day``."""
    if isinstance(contracts_per_day, int):
        contracts_per_day = [contracts_per_day] * len(days)
    if len(contracts_per_day) != len(days):
        raise AssertionError("test fixture mis-shape")
    rows: list[dict] = []
    for d, total in zip(days, contracts_per_day):
        per_row = total // rows_per_day
        for i in range(rows_per_day):
            rows.append(_row(
                symbol, d, instrument=instrument, contracts=per_row,
                strike=100.0 + i,
                option_type="CE" if i % 2 == 0 else "PE",
            ))
    return pd.DataFrame(rows)


# ============================================================
# liquidity_score — pure kernel
# ============================================================

def test_score_is_mean_of_per_day_totals():
    """LOAD-BEARING: per-day totals → mean. NOT per-row mean.

    21 days, varying daily totals [10k, 20k, 30k, ..., 210k]
    (10k×i for i in 1..21). Mean = 110k.
    With 3 rows per day, per-row mean would be ~36.7k.
    The two diverge enough to detect drift."""
    days = pd.date_range("2024-04-01", periods=21).date.tolist()
    contracts = [10_000 * (i + 1) for i in range(21)]
    df = _synthetic_window("RELIANCE", days, contracts_per_day=contracts)
    score = liquidity_score(df, "RELIANCE", date(2024, 4, 21))
    # abs=1.0 absorbs the int-division rounding in the fixture
    # (each row gets total//3 contracts, so the per-day sum is
    # slightly less than the requested total; per-row → per-day
    # math drift is microscopic, the test pins the formula).
    assert score == pytest.approx(110_000.0, abs=1.0)
    # Drift detector vs per-row mean — per-row mean uses int division
    # in the fixture (each row gets total // 3 contracts), so it's
    # not exactly 36667; just assert it differs significantly.
    per_row_mean = df[df["symbol"] == "RELIANCE"]["contracts"].mean()
    assert abs(score - per_row_mean) > 1000


def test_score_drops_OPTIDX_rows():
    """§11.b: only OPTSTK rows count. OPTIDX rows for the same
    symbol must NOT contribute."""
    days = pd.date_range("2024-04-01", periods=21).date.tolist()
    optstk = _synthetic_window("RELIANCE", days, contracts_per_day=5000)
    optidx = _synthetic_window("RELIANCE", days, contracts_per_day=999_999,
                                instrument="OPTIDX")
    df = pd.concat([optstk, optidx], ignore_index=True)
    score = liquidity_score(df, "RELIANCE", date(2024, 4, 21))
    # If OPTIDX leaked, score would be near 999_999 + 5_000.
    assert score == pytest.approx(5_000.0, rel=0.05)


def test_score_drops_other_symbols():
    days = pd.date_range("2024-04-01", periods=21).date.tolist()
    df = pd.concat([
        _synthetic_window("RELIANCE", days, contracts_per_day=5_000),
        _synthetic_window("INFY", days, contracts_per_day=999_999),
    ], ignore_index=True)
    assert liquidity_score(df, "RELIANCE", date(2024, 4, 21)) == pytest.approx(5_000.0, rel=0.05)
    assert liquidity_score(df, "INFY", date(2024, 4, 21)) == pytest.approx(999_999.0, rel=0.05)


def test_score_nan_when_symbol_absent():
    days = pd.date_range("2024-04-01", periods=21).date.tolist()
    df = _synthetic_window("RELIANCE", days)
    assert np.isnan(liquidity_score(df, "UNKNOWNSYM", date(2024, 4, 21)))


def test_score_nan_below_min_valid_fraction():
    """Fewer than 0.5 × lookback (= 11) distinct trade dates →
    NaN. Build a 5-day window for a 21-day lookback."""
    days = pd.date_range("2024-04-01", periods=5).date.tolist()
    df = _synthetic_window("RELIANCE", days, contracts_per_day=10_000)
    assert np.isnan(
        liquidity_score(df, "RELIANCE", date(2024, 4, 5), lookback_td=21)
    )


def test_score_passes_min_valid_fraction_at_floor():
    """Exactly at the floor: 11 distinct days for lookback=21
    → ``11 >= 0.5 * 21 = 10.5`` → PASSES."""
    days = pd.date_range("2024-04-01", periods=11).date.tolist()
    df = _synthetic_window("RELIANCE", days, contracts_per_day=10_000)
    score = liquidity_score(df, "RELIANCE", date(2024, 4, 11), lookback_td=21)
    assert not np.isnan(score)


def test_score_nan_on_empty_frame():
    assert np.isnan(
        liquidity_score(pd.DataFrame(), "RELIANCE", date(2024, 4, 1))
    )


def test_score_nan_on_none_frame():
    assert np.isnan(
        liquidity_score(None, "RELIANCE", date(2024, 4, 1))
    )


def test_score_rejects_frame_missing_required_columns():
    bad = pd.DataFrame({"symbol": ["RELIANCE"], "contracts": [100]})
    with pytest.raises(ValueError, match="missing required columns"):
        liquidity_score(bad, "RELIANCE", date(2024, 4, 1))


def test_score_case_insensitive_symbol_input():
    days = pd.date_range("2024-04-01", periods=21).date.tolist()
    df = _synthetic_window("RELIANCE", days, contracts_per_day=10_000)
    a = liquidity_score(df, "RELIANCE", date(2024, 4, 21))
    b = liquidity_score(df, "reliance", date(2024, 4, 21))
    assert a == b


# ============================================================
# compute_liquidity_score(s) — symbol-aware path
# ============================================================

def _patch_loaders(
    monkeypatch,
    *,
    days: list[date],
    frames: dict[date, pd.DataFrame],
    load_calls: list[date] | None = None,
):
    """Stub the trading calendar + bhavcopy loader. If
    ``load_calls`` is provided, each load gets appended (lets a
    test prove the batch path loads each day exactly once)."""

    def fake_offset(as_of, td, **kw):
        idx = days.index(as_of)
        return days[max(0, idx - td)]

    def fake_trading_days(start, end, **kw):
        return [d for d in days if start <= d <= end]

    def fake_load(trade_date, *, force_refresh=False, offline=False):
        if load_calls is not None:
            load_calls.append(trade_date)
        return frames.get(trade_date, pd.DataFrame())

    monkeypatch.setattr(
        liq_mod.trading_calendar, "offset_trading_days", fake_offset,
    )
    monkeypatch.setattr(
        liq_mod.trading_calendar, "trading_days", fake_trading_days,
    )
    monkeypatch.setattr(liq_mod, "load_bhavcopy_fo", fake_load)


def test_compute_liquidity_score_symbol_aware(monkeypatch):
    """Single-symbol convenience: walks the calendar back 21 TDs,
    assembles the window, returns the F11 score."""
    days = pd.date_range("2024-04-01", periods=22).date.tolist()
    frames = {
        d: _synthetic_window("RELIANCE", [d], contracts_per_day=10_000)
        for d in days
    }
    _patch_loaders(monkeypatch, days=days, frames=frames)
    score = compute_liquidity_score("RELIANCE", days[-1], lookback_td=21)
    assert score == pytest.approx(10_000.0, rel=0.05)


def test_compute_liquidity_score_returns_nan_on_empty_window(monkeypatch):
    days = pd.date_range("2024-04-01", periods=22).date.tolist()
    _patch_loaders(monkeypatch, days=days, frames={})
    assert np.isnan(compute_liquidity_score("RELIANCE", days[-1]))


def test_compute_liquidity_scores_loads_each_day_once(monkeypatch):
    """LOAD-BEARING perf contract: batch path loads N days, not
    N × M (where M = symbols). The docstring's optimization claim
    must hold."""
    days = pd.date_range("2024-04-01", periods=22).date.tolist()
    frames = {}
    for d in days:
        # 3 symbols per day in the bhavcopy.
        rows = []
        for sym in ("RELIANCE", "INFY", "TCS"):
            for i in range(3):
                rows.append(_row(sym, d, contracts=1000))
        frames[d] = pd.DataFrame(rows)
    load_calls: list[date] = []
    _patch_loaders(monkeypatch, days=days, frames=frames, load_calls=load_calls)

    scores = compute_liquidity_scores(
        ["RELIANCE", "INFY", "TCS"], days[-1], lookback_td=21,
    )
    # All 3 symbols have valid scores ~3000 (3 rows × 1000 contracts).
    assert sorted(scores.keys()) == ["INFY", "RELIANCE", "TCS"]
    for v in scores.values():
        assert v == pytest.approx(3000.0, rel=0.05)
    # And the loader was called exactly once per day, NOT per (sym, day).
    assert len(load_calls) == 22


def test_compute_liquidity_scores_returns_nan_for_unlisted_symbol(monkeypatch):
    days = pd.date_range("2024-04-01", periods=22).date.tolist()
    frames = {
        d: _synthetic_window("RELIANCE", [d], contracts_per_day=10_000)
        for d in days
    }
    _patch_loaders(monkeypatch, days=days, frames=frames)
    scores = compute_liquidity_scores(["RELIANCE", "UNKNOWNSYM"], days[-1])
    assert not np.isnan(scores["RELIANCE"])
    assert np.isnan(scores["UNKNOWNSYM"])


def test_compute_liquidity_scores_empty_symbols_returns_empty():
    assert compute_liquidity_scores([], date(2024, 4, 1)) == {}


# ============================================================
# top_n_by_liquidity
# ============================================================

def test_top_n_by_liquidity_descending(monkeypatch):
    days = pd.date_range("2024-04-01", periods=22).date.tolist()
    # 5 symbols with distinct contracts/day so ranking is unambiguous.
    sym_to_total = {"A": 5000, "B": 9000, "C": 1000, "D": 7000, "E": 3000}
    frames = {}
    for d in days:
        rows = []
        for sym, total in sym_to_total.items():
            for i in range(3):
                rows.append(_row(sym, d, contracts=total // 3))
        frames[d] = pd.DataFrame(rows)
    _patch_loaders(monkeypatch, days=days, frames=frames)
    top3 = top_n_by_liquidity(list(sym_to_total), days[-1], n=3)
    assert top3 == ["B", "D", "A"]


def test_top_n_alphabetical_tiebreak(monkeypatch):
    """LOAD-BEARING SPECS §6c.3: tied scores → symbol ASCENDING."""
    days = pd.date_range("2024-04-01", periods=22).date.tolist()
    syms = ["ZEEL", "ACC", "MAR"]  # all tied
    frames = {}
    for d in days:
        rows = []
        for sym in syms:
            for i in range(3):
                rows.append(_row(sym, d, contracts=1000))
        frames[d] = pd.DataFrame(rows)
    _patch_loaders(monkeypatch, days=days, frames=frames)
    assert top_n_by_liquidity(syms, days[-1], n=3) == ["ACC", "MAR", "ZEEL"]


def test_top_n_drops_nan_scores(monkeypatch):
    days = pd.date_range("2024-04-01", periods=22).date.tolist()
    frames = {
        d: _synthetic_window("RELIANCE", [d], contracts_per_day=10_000)
        for d in days
    }
    _patch_loaders(monkeypatch, days=days, frames=frames)
    top = top_n_by_liquidity(["RELIANCE", "UNKNOWNSYM"], days[-1], n=5)
    assert top == ["RELIANCE"]


def test_top_n_rejects_negative_n():
    with pytest.raises(ValueError, match="n must be >= 0"):
        top_n_by_liquidity(["RELIANCE"], date(2024, 4, 1), n=-1)


def test_top_n_zero_returns_empty(monkeypatch):
    days = pd.date_range("2024-04-01", periods=22).date.tolist()
    frames = {d: _synthetic_window("RELIANCE", [d]) for d in days}
    _patch_loaders(monkeypatch, days=days, frames=frames)
    assert top_n_by_liquidity(["RELIANCE"], days[-1], n=0) == []


# ============================================================
# Constants
# ============================================================

def test_constants_match_memoir_spec():
    """F11 spec pin — drift detector."""
    assert LIQUIDITY_LOOKBACK_TD == 21
    assert LIQUIDITY_INSTRUMENT == "OPTSTK"
    assert LIQUIDITY_MIN_VALID_FRACTION == 0.5
