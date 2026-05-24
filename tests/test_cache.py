"""Unit tests for src.data.cache. No network."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data import cache


def _redirect_cache(monkeypatch, tmp_path):
    """Point cache.CACHE_DIR at a per-test temp dir. The autouse fixture in
    conftest.py resets the memoized root-verification flag before each test,
    so we don't need to repeat that here."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


def test_round_trip(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    df = pd.DataFrame({"x": [1, 2, 3], "y": ["a", "b", "c"]})
    p = cache.spot_path("RELIANCE", 2024)
    cache.write(p, df)
    assert cache.exists(p)
    back = cache.read(p)
    pd.testing.assert_frame_equal(back, df)


def test_path_builders(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    spot = cache.spot_path("reliance", 2024)
    assert spot.name == "2024.parquet"
    assert spot.parent.name == "RELIANCE"  # symbol normalized to upper

    opt = cache.option_path("reliance", date(2024, 1, 25), 2580.0, "ce")
    assert opt.name == "2580-CE.parquet"  # option_type uppercased, strike int
    assert opt.parent.name == "20240125"
    assert opt.parent.parent.name == "RELIANCE"

    exp = cache.expiry_path("reliance")
    assert exp.name == "RELIANCE.parquet"


def test_bhavcopy_fo_path(monkeypatch, tmp_path):
    """bhavcopy_fo is symbol-agnostic — one file per trade date, used by
    every symbol's expiry calendar. Filename is YYYYMMDD for natural sort."""
    _redirect_cache(monkeypatch, tmp_path)
    p1 = cache.bhavcopy_fo_path(date(2024, 1, 25))
    assert p1.name == "20240125.parquet"
    assert p1.parent.name == "bhavcopy_fo"
    # Same date → same path (idempotent path build); different dates → different paths
    assert cache.bhavcopy_fo_path(date(2024, 1, 25)) == p1
    p2 = cache.bhavcopy_fo_path(date(2024, 2, 29))
    assert p2.name == "20240229.parquet"
    assert p1 != p2
    # No symbol involved — confirms the "share across symbols" contract by API shape.
    # (The function signature takes only a date; a symbol parameter would be a regression.)
    import inspect
    sig = inspect.signature(cache.bhavcopy_fo_path)
    assert list(sig.parameters) == ["trade_date"]


def test_sentinel_created_on_first_use(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    cache.spot_path("X", 2024)  # triggers _ensure_root
    sentinel = tmp_path / ".cache_version"
    assert sentinel.exists()
    assert sentinel.read_text().strip() == str(cache.CACHE_VERSION)


def test_version_mismatch_raises(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / ".cache_version").write_text("999")
    with pytest.raises(cache.CacheVersionMismatch):
        cache.spot_path("X", 2024)


def test_atomic_write_no_tmp_left_behind(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    df = pd.DataFrame({"x": [1]})
    p = cache.spot_path("X", 2024)
    cache.write(p, df)
    leftover = list(p.parent.glob("*.tmp"))
    assert leftover == [], f"unexpected tmp files: {leftover}"


def test_true_atomicity_on_failure(monkeypatch, tmp_path):
    """If the parquet write itself blows up, the destination must NOT exist
    and no .tmp file may be left behind. This is the actual property the
    'atomic write' commit message claimed; the happy-path test above only
    proved the rename completed."""
    _redirect_cache(monkeypatch, tmp_path)
    p = cache.spot_path("X", 2024)

    def boom(self, *args, **kwargs):
        raise RuntimeError("simulated mid-write failure")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", boom)
    with pytest.raises(RuntimeError, match="simulated"):
        cache.write(p, pd.DataFrame({"x": [1]}))
    assert not p.exists(), "destination file must not exist after failed write"
    assert list(p.parent.glob("*.tmp")) == [], "no .tmp may linger after failure"


def test_overwrite_protect(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    p = cache.spot_path("X", 2024)
    cache.write(p, pd.DataFrame({"x": [1]}))
    # Second write to the same path must be loud
    with pytest.raises(cache.WouldOverwriteError):
        cache.write(p, pd.DataFrame({"x": [2]}))
    # But explicit overwrite=True is allowed
    cache.write(p, pd.DataFrame({"x": [2]}), overwrite=True)
    assert cache.read(p).iloc[0, 0] == 2


def test_strike_integer_guard(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    # Whole-rupee strikes accepted as int OR float
    p_int = cache.option_path("X", date(2024, 1, 25), 2620, "CE")
    p_flt = cache.option_path("X", date(2024, 1, 25), 2620.0, "CE")
    assert p_int == p_flt
    assert p_int.name == "2620-CE.parquet"
    # Fractional strikes refused — guards against banker's-rounding collisions
    with pytest.raises(cache.StrikeNotIntegerError):
        cache.option_path("X", date(2024, 1, 25), 2620.5, "CE")
    with pytest.raises(cache.StrikeNotIntegerError):
        cache.option_path("X", date(2024, 1, 25), 50.5, "PE")


def test_version_mismatch_message_is_informative(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    (tmp_path / ".cache_version").write_text("999")
    with pytest.raises(cache.CacheVersionMismatch) as exc:
        cache.spot_path("X", 2024)
    msg = str(exc.value)
    # The message should help the user actually resolve the problem, not just say "boom".
    assert "999" in msg
    assert str(cache.CACHE_VERSION) in msg
    assert "SPECS" in msg  # points at the doc


def test_root_verification_memoized(monkeypatch, tmp_path):
    """A sweep building thousands of paths should pay sentinel I/O cost
    once per process, not per call."""
    _redirect_cache(monkeypatch, tmp_path)
    real_read_text = Path.read_text
    calls = {"n": 0}

    def counting_read_text(self, *args, **kwargs):
        if self.name == ".cache_version":
            calls["n"] += 1
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    # Prime the sentinel so subsequent path builds hit the memo
    cache.spot_path("X", 2024)
    primed = calls["n"]
    # Build many paths
    for i in range(50):
        cache.spot_path("X", 2024 + (i % 5))
        cache.option_path("X", date(2024, 1, 25), 1000 + i, "CE")
    assert calls["n"] == primed, (
        f"sentinel read {calls['n'] - primed} extra times across 100 builds — "
        f"memoization is broken"
    )


def test_round_trip_pins_dtypes(monkeypatch, tmp_path):
    """SPECS §2.1 schema uses specific dtypes (datetime64[ns], float64,
    int64). A round-trip must preserve them — parquet engines sometimes
    coerce silently and we want a test to scream if that ever happens."""
    _redirect_cache(monkeypatch, tmp_path)
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "symbol": pd.array(["RELIANCE", "RELIANCE"], dtype="string"),
            "open": np.array([2577.0, 2600.0], dtype="float64"),
            "volume": np.array([1_000_000, 2_000_000], dtype="int64"),
        }
    )
    p = cache.spot_path("RELIANCE", 2024)
    cache.write(p, df)
    back = cache.read(p)
    # Date semantics survive, but unit may be downgraded ns -> us by the
    # parquet round-trip (pandas 3.0 + pyarrow 24). SPECS §2.1 documents this.
    assert pd.api.types.is_datetime64_any_dtype(back["date"])
    assert pd.api.types.is_string_dtype(back["symbol"])
    assert back["open"].dtype == np.dtype("float64")
    assert back["volume"].dtype == np.dtype("int64")
    # Values themselves must be byte-identical at the precision we care about.
    pd.testing.assert_frame_equal(back, df, check_dtype=False)
