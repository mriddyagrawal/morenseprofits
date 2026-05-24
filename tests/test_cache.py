"""Unit tests for src.data.cache. No network."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.data import cache


def _redirect_cache(monkeypatch, tmp_path):
    """Point cache.CACHE_DIR at a per-test temp dir AND reset the memoized
    root-verification flag so the new dir's sentinel is checked fresh."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    cache._reset_root_memo()


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
