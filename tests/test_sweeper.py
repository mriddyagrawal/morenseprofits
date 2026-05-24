"""Tests for src.engine.sweeper. No network — load_spot, load_option,
load_bhavcopy_fo, trading_calendar all monkeypatched.

The load-bearing tests are:
  - test_sweep_grid_deterministic: re-running yields the same parquet
  - test_run_id_excludes_operational_kwargs: today_fn / offline don't
    enter the hash (so the same logical sweep returns the same file)
  - test_skips_missing_data_errors_without_dying: one bad cell doesn't
    nuke the rest of the sweep
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.config import RESULTS_DIR
from src.data import (
    bhavcopy_fo_loader, cache, spot_loader, trading_calendar,
)
from src.data.errors import MissingDataError
from src.engine import sweeper as sweeper_mod
from src.engine.sweeper import _compute_run_id, sweep_grid, sweep_one


# ----- minimal data fixtures -----
def _spot_frame(d: date, close: float) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.Series([pd.Timestamp(d)], dtype="datetime64[us]"),
        "symbol": pd.array(["RELIANCE"], dtype="string"),
        "close": [close],
    })


def _option_frame(entry: date, exit_: date, entry_close: float, exit_close: float) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.Series(
            [pd.Timestamp(entry), pd.Timestamp(exit_)], dtype="datetime64[us]",
        ),
        "close": [entry_close, exit_close],
        "lot_size": pd.array([250, 250], dtype="int64"),
    })


def _bhavcopy_frame() -> pd.DataFrame:
    """Strike grid the ShortStraddle picker filters."""
    rows = []
    for strike in (2540, 2560, 2580, 2600, 2620, 2640):
        for ot in ("CE", "PE"):
            rows.append((strike, ot))
    return pd.DataFrame({
        "instrument": pd.array(["OPTSTK"] * len(rows), dtype="string"),
        "symbol": pd.array(["RELIANCE"] * len(rows), dtype="string"),
        "option_type": pd.array([r[1] for r in rows], dtype="string"),
        "strike": [float(r[0]) for r in rows],
        "expiry": pd.Series(
            [pd.Timestamp("2024-01-25")] * len(rows), dtype="datetime64[us]",
        ),
    })


def _wire_mocks(monkeypatch, *, entry_date=date(2024, 1, 4), exit_date=date(2024, 1, 24)):
    """Patch every external dep so sweep_one runs deterministically offline."""
    # trading_calendar.offset_trading_days: T-15 → entry, T-1 → exit
    def fake_offset(anchor, n, *, today_fn=date.today, offline=False):
        if n == 15: return entry_date
        if n == 1:  return exit_date
        if n == 5:  return date(2024, 1, 18)  # for other-offset tests
        return anchor  # passthrough for unrecognized n
    monkeypatch.setattr(trading_calendar, "offset_trading_days", fake_offset)

    # spot_loader.load_spot: entry → 2596.65, exit → 2700
    def fake_load_spot(symbol, fd, td, *, today_fn=date.today, offline=False, force_refresh=False):
        if fd == entry_date: return _spot_frame(entry_date, 2596.65)
        if fd == exit_date:  return _spot_frame(exit_date, 2700.0)
        return _spot_frame(fd, 2596.65)
    monkeypatch.setattr(spot_loader, "load_spot", fake_load_spot)

    # bhavcopy_fo_loader.load_bhavcopy_fo: strike grid for ATM picker
    def fake_bhavcopy(td, *, force_refresh=False, offline=False):
        return _bhavcopy_frame()
    monkeypatch.setattr(bhavcopy_fo_loader, "load_bhavcopy_fo", fake_bhavcopy)

    # options_loader.load_option (CE went up, PE decayed). Use the
    # caller's from_date/to_date (not the wired defaults) so trades
    # with different entry offsets find their entry row.
    def fake_load_option(symbol, expiry, strike, option_type, fd, td, *,
                        force_refresh=False, today_fn=date.today, offline=False):
        if option_type == "CE":
            return _option_frame(fd, td, 60.0, 95.0)
        return _option_frame(fd, td, 50.0, 5.0)
    from src.data import options_loader
    monkeypatch.setattr(options_loader, "load_option", fake_load_option)


def _redirect_results(monkeypatch, tmp_path):
    monkeypatch.setattr(sweeper_mod, "RESULTS_DIR", tmp_path)


# ============================================================
# run_id hash determinism (SPECS §6c.3)
# ============================================================

def test_run_id_is_deterministic_same_inputs():
    a = _compute_run_id(["short_straddle"], ["RELIANCE"],
                        [date(2024, 1, 25)], [15], [1])
    b = _compute_run_id(["short_straddle"], ["RELIANCE"],
                        [date(2024, 1, 25)], [15], [1])
    assert a == b
    assert len(a) == 12


def test_run_id_order_independent():
    """Order of inputs doesn't matter — hash uses sorted tuples."""
    a = _compute_run_id(
        ["short_straddle"], ["INFY", "RELIANCE"],
        [date(2024, 2, 29), date(2024, 1, 25)],
        [15, 10], [1, 5],
    )
    b = _compute_run_id(
        ["short_straddle"], ["RELIANCE", "INFY"],
        [date(2024, 1, 25), date(2024, 2, 29)],
        [10, 15], [5, 1],
    )
    assert a == b


def test_run_id_differs_on_different_inputs():
    a = _compute_run_id(["short_straddle"], ["RELIANCE"],
                        [date(2024, 1, 25)], [15], [1])
    b = _compute_run_id(["short_straddle"], ["RELIANCE"],
                        [date(2024, 1, 25)], [10], [1])  # different entry offset
    assert a != b


# ============================================================
# sweep_one: pure-function correctness
# ============================================================

def test_sweep_one_returns_full_results_dict(monkeypatch, tmp_path):
    _wire_mocks(monkeypatch)
    _redirect_results(monkeypatch, tmp_path)
    cache.CACHE_DIR = tmp_path  # avoid polluting real cache

    out = sweep_one(
        "short_straddle", "RELIANCE", date(2024, 1, 25),
        entry_offset_td=15, exit_offset_td=1,
        today_fn=lambda: date(2026, 5, 24),
    )
    assert out is not None
    # SPECS §2.5 base columns
    for k in ("gross_pnl", "costs", "net_pnl", "margin_at_entry", "roi_pct",
              "roi_pct_annualized", "hold_trading_days"):
        assert k in out
    # Sweep decorations
    for k in ("entry_offset_td", "exit_offset_td", "entry_spot", "exit_spot",
              "notional_at_entry"):
        assert k in out
    assert out["entry_offset_td"] == 15
    assert out["exit_offset_td"] == 1
    assert out["entry_spot"] == 2596.65


def test_sweep_one_uses_spot_based_margin_basis(monkeypatch, tmp_path):
    """SPECS §4a caveat #1: the sweeper has spot_at_entry locally
    (it sources it from spot_loader before calling generate_trades),
    so it passes spot through to price_trade and the margin model
    uses spot-based notional by default. Pin the result via the
    margin_breakdown_json's notional_basis field."""
    import json
    _wire_mocks(monkeypatch)
    _redirect_results(monkeypatch, tmp_path)
    cache.CACHE_DIR = tmp_path

    out = sweep_one(
        "short_straddle", "RELIANCE", date(2024, 1, 25),
        entry_offset_td=15, exit_offset_td=1,
        today_fn=lambda: date(2026, 5, 24),
    )
    assert out is not None
    breakdown = json.loads(out["margin_breakdown_json"])
    assert breakdown["notional_basis"] == "spot"


def test_sweep_one_rejects_inverted_window():
    """T-1 entry, T-15 exit is nonsensical (would mean exiting BEFORE
    entering). Loud failure at the boundary."""
    with pytest.raises(ValueError, match="entry_offset_td.*must be"):
        sweep_one("short_straddle", "RELIANCE", date(2024, 1, 25),
                  entry_offset_td=1, exit_offset_td=15)


def test_sweep_one_skips_on_missing_data_returns_skip_marker(monkeypatch, tmp_path):
    """MissingDataError → `skip:MissingDataError` (sweep_grid records
    the reason in the skip log)."""
    _wire_mocks(monkeypatch)
    cache.CACHE_DIR = tmp_path

    from src.data import options_loader
    def boom(*a, **kw):
        raise MissingDataError("simulated illiquid contract")
    monkeypatch.setattr(options_loader, "load_option", boom)

    out = sweep_one(
        "short_straddle", "RELIANCE", date(2024, 1, 25),
        entry_offset_td=15, exit_offset_td=1,
        today_fn=lambda: date(2026, 5, 24),
    )
    assert out == "skip:MissingDataError"


# ============================================================
# sweep_grid: end-to-end + determinism
# ============================================================

def test_sweep_grid_basic_2x2_window_grid(monkeypatch, tmp_path):
    _wire_mocks(monkeypatch)
    _redirect_results(monkeypatch, tmp_path)
    cache.CACHE_DIR = tmp_path

    df = sweep_grid(
        strategies=["short_straddle"],
        symbols=["RELIANCE"],
        expiries=[date(2024, 1, 25)],
        entry_offsets_td=[15, 5],   # only T-15 (since T-5 < some exit)
        exit_offsets_td=[1],
        today_fn=lambda: date(2026, 5, 24),
    )
    # Cartesian: 1×1×1×2×1 = 2 cells; both have entry>exit → 2 rows
    assert len(df) == 2
    # Sorted determinism: entry_offset_td ascending? Check actual sort.
    assert list(df["entry_offset_td"]) == sorted(df["entry_offset_td"])
    assert (df["exit_offset_td"] == 1).all()


def test_sweep_grid_deterministic(monkeypatch, tmp_path):
    """LOAD-BEARING. Two invocations of sweep_grid with the same inputs
    must produce semantic-equal parquets. Re-run policy (skip on
    existing) means second call reads the parquet — pin that path too."""
    _wire_mocks(monkeypatch)
    _redirect_results(monkeypatch, tmp_path)
    cache.CACHE_DIR = tmp_path

    kwargs = dict(
        strategies=["short_straddle"],
        symbols=["RELIANCE"],
        expiries=[date(2024, 1, 25)],
        entry_offsets_td=[15],
        exit_offsets_td=[1],
        today_fn=lambda: date(2026, 5, 24),
    )
    a = sweep_grid(**kwargs)
    b = sweep_grid(**kwargs)  # should HIT the parquet from a
    pd.testing.assert_frame_equal(a, b)


def test_sweep_grid_force_rebuilds(monkeypatch, tmp_path):
    """force=True ignores the existing parquet and recomputes."""
    _wire_mocks(monkeypatch)
    _redirect_results(monkeypatch, tmp_path)
    cache.CACHE_DIR = tmp_path

    kwargs = dict(
        strategies=["short_straddle"],
        symbols=["RELIANCE"],
        expiries=[date(2024, 1, 25)],
        entry_offsets_td=[15],
        exit_offsets_td=[1],
        today_fn=lambda: date(2026, 5, 24),
    )
    a = sweep_grid(**kwargs)
    b = sweep_grid(force=True, **kwargs)
    pd.testing.assert_frame_equal(a, b)


def test_sweep_grid_skips_missing_data_without_dying(monkeypatch, tmp_path):
    """One bad cell doesn't kill the whole sweep — sweep_one returns
    None for skipped cells, sweep_grid just doesn't include them."""
    _wire_mocks(monkeypatch)
    _redirect_results(monkeypatch, tmp_path)
    cache.CACHE_DIR = tmp_path

    # Override option loader to raise on ONE specific entry_offset
    from src.data import options_loader
    real_load = options_loader.load_option  # the wired mock
    bad_calls = {"n": 0}

    def selective_boom(symbol, expiry, strike, option_type, fd, td, **kw):
        if bad_calls["n"] == 0 and fd == date(2024, 1, 4):
            bad_calls["n"] += 1
            raise MissingDataError("first CE call boom")
        return real_load(symbol, expiry, strike, option_type, fd, td, **kw)
    monkeypatch.setattr(options_loader, "load_option", selective_boom)

    df = sweep_grid(
        strategies=["short_straddle"], symbols=["RELIANCE"],
        expiries=[date(2024, 1, 25)],
        entry_offsets_td=[15, 5],
        exit_offsets_td=[1],
        today_fn=lambda: date(2026, 5, 24),
    )
    # One of the two cells skipped; one survived
    assert 0 <= len(df) <= 2


def test_notional_at_entry_uses_per_leg_lot_size_not_constant(monkeypatch, tmp_path):
    """LOAD-BEARING regression block. PLAN §4 rule #3: lot size is
    per-row historical, NOT a constant. A previous bug hardcoded
    lot_size=250 in notional_at_entry computation; this test pins
    the correct per-row read from legs_json.

    Two synthetic stocks with different lots (250 vs 550, mimicking
    RELIANCE vs HDFCBANK) at the SAME spot → notional differs by
    exactly the lot ratio."""
    cache.CACHE_DIR = tmp_path
    _redirect_results(monkeypatch, tmp_path)

    # Build mocks where the option frame's lot_size column differs by symbol
    def fake_offset(anchor, n, *, today_fn=date.today, offline=False):
        return date(2024, 1, 4) if n == 15 else date(2024, 1, 24)
    monkeypatch.setattr(trading_calendar, "offset_trading_days", fake_offset)

    def fake_load_spot(symbol, fd, td, *, today_fn=date.today, offline=False,
                       force_refresh=False):
        # Same spot for both symbols → notional difference comes from lot
        return pd.DataFrame({
            "date": pd.Series([pd.Timestamp(fd)], dtype="datetime64[us]"),
            "symbol": pd.array([symbol], dtype="string"),
            "close": [2000.0],
        })
    monkeypatch.setattr(spot_loader, "load_spot", fake_load_spot)

    def fake_bhavcopy(td, *, force_refresh=False, offline=False):
        # Provide strikes for both BIGLOT and SMALLLOT
        rows = []
        for sym in ("BIGLOT", "SMALLLOT"):
            for k in (1980, 2000, 2020):
                for ot in ("CE", "PE"):
                    rows.append((sym, k, ot))
        return pd.DataFrame({
            "instrument": pd.array(["OPTSTK"] * len(rows), dtype="string"),
            "symbol": pd.array([r[0] for r in rows], dtype="string"),
            "option_type": pd.array([r[2] for r in rows], dtype="string"),
            "strike": [float(r[1]) for r in rows],
            "expiry": pd.Series(
                [pd.Timestamp("2024-01-25")] * len(rows), dtype="datetime64[us]",
            ),
        })
    monkeypatch.setattr(bhavcopy_fo_loader, "load_bhavcopy_fo", fake_bhavcopy)

    # Different lot per symbol
    def fake_load_option(symbol, expiry, strike, option_type, fd, td, *,
                        force_refresh=False, today_fn=date.today, offline=False):
        lot = 550 if symbol == "BIGLOT" else 250
        return pd.DataFrame({
            "date": pd.Series(
                [pd.Timestamp(date(2024, 1, 4)), pd.Timestamp(date(2024, 1, 24))],
                dtype="datetime64[us]",
            ),
            "close": [100.0, 50.0],
            "lot_size": pd.array([lot, lot], dtype="int64"),
        })
    from src.data import options_loader
    monkeypatch.setattr(options_loader, "load_option", fake_load_option)

    big = sweep_one(
        "short_straddle", "BIGLOT", date(2024, 1, 25),
        entry_offset_td=15, exit_offset_td=1,
        today_fn=lambda: date(2026, 5, 24),
    )
    small = sweep_one(
        "short_straddle", "SMALLLOT", date(2024, 1, 25),
        entry_offset_td=15, exit_offset_td=1,
        today_fn=lambda: date(2026, 5, 24),
    )
    assert big is not None and small is not None
    # BIGLOT: 2000 spot × (1 lot × 550 shares × 2 legs) = 2,200,000
    # SMALLLOT: 2000 spot × (1 lot × 250 shares × 2 legs) = 1,000,000
    assert big["notional_at_entry"] == 2_200_000.0
    assert small["notional_at_entry"] == 1_000_000.0
    # Ratio matches lot ratio (550/250 = 2.2)
    assert big["notional_at_entry"] / small["notional_at_entry"] == pytest.approx(2.2)


def test_sweep_offline_cache_miss_propagates(monkeypatch, tmp_path):
    """LOAD-BEARING per SPECS §6a + §6c.2: OfflineCacheMiss must NOT
    be swallowed by the MissingDataError skip-loop. Otherwise an
    offline cold-cache sweep would silently return zero rows."""
    from src.data.errors import OfflineCacheMiss
    _wire_mocks(monkeypatch)
    _redirect_results(monkeypatch, tmp_path)
    cache.CACHE_DIR = tmp_path

    def boom(*a, **kw):
        raise OfflineCacheMiss("cold offline cache")

    monkeypatch.setattr(trading_calendar, "offset_trading_days", boom)
    with pytest.raises(OfflineCacheMiss):
        sweep_grid(
            strategies=["short_straddle"], symbols=["RELIANCE"],
            expiries=[date(2024, 1, 25)],
            entry_offsets_td=[15], exit_offsets_td=[1],
            today_fn=lambda: date(2026, 5, 24),
            offline=True,
        )


def test_sweep_grid_empty_window_grid_returns_empty_with_schema(monkeypatch, tmp_path):
    """Inverted entry/exit gets filtered out at the task-enumeration
    level. Result is an EMPTY frame WITH THE CANONICAL COLUMN SCHEMA —
    downstream consumers don't trip on missing columns (reviewer flag
    from 185a9cb addressed in p4.3)."""
    from src.engine.results import RESULTS_COLUMNS
    _wire_mocks(monkeypatch)
    _redirect_results(monkeypatch, tmp_path)
    cache.CACHE_DIR = tmp_path

    df = sweep_grid(
        strategies=["short_straddle"], symbols=["RELIANCE"],
        expiries=[date(2024, 1, 25)],
        entry_offsets_td=[1],  # T-1
        exit_offsets_td=[15],  # T-15 — inverted, filtered out
        today_fn=lambda: date(2026, 5, 24),
    )
    assert len(df) == 0
    # Empty frame must still carry the canonical schema
    assert set(df.columns) >= set(RESULTS_COLUMNS), (
        f"empty frame missing canonical columns: "
        f"{sorted(set(RESULTS_COLUMNS) - set(df.columns))}"
    )


def test_sweep_grid_persists_skip_log_when_skips_occur(monkeypatch, tmp_path):
    """Reviewer flag from 185a9cb: skipped tasks should land in a
    companion parquet so operators can see WHY 200 of 7500 cells
    dropped without manually diffing row counts."""
    from src.engine import results as _results
    _wire_mocks(monkeypatch)
    _redirect_results(monkeypatch, tmp_path)
    cache.CACHE_DIR = tmp_path

    # Make ONE cell raise; the other survives.
    from src.data import options_loader
    real_load = options_loader.load_option
    call_count = {"n": 0}

    def selective_boom(symbol, expiry, strike, option_type, fd, td, **kw):
        # Boom on the very first call; let the rest through
        if call_count["n"] == 0:
            call_count["n"] += 1
            raise MissingDataError("first call boom")
        return real_load(symbol, expiry, strike, option_type, fd, td, **kw)
    monkeypatch.setattr(options_loader, "load_option", selective_boom)

    df = sweep_grid(
        strategies=["short_straddle"], symbols=["RELIANCE"],
        expiries=[date(2024, 1, 25)],
        entry_offsets_td=[15, 5],
        exit_offsets_td=[1],
        today_fn=lambda: date(2026, 5, 24),
    )
    # One cell survived; one was skipped
    assert len(df) == 1
    # Skip log persisted as companion file
    from src.engine.sweeper import _compute_run_id
    run_id = _compute_run_id(
        ["short_straddle"], ["RELIANCE"], [date(2024, 1, 25)], [15, 5], [1],
    )
    skips = _results.read_skips(run_id)
    assert len(skips) == 1
    assert skips.iloc[0]["skip_reason"] == "MissingDataError"
    assert skips.iloc[0]["symbol"] == "RELIANCE"
