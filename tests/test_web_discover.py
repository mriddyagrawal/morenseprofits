"""Tests for src.web.discover — Phase-6 sweep-parquet discovery.

Load-bearing cases per DESIGN_SPEC §4 commit `test(p6.1.discover)`:
  - empty results_dir → None
  - results_dir doesn't exist → None
  - single parquet → returns it
  - multiple parquets → returns newest mtime
  - mtime-tied parquets → deterministic name-ASC tiebreaker
  - corrupt parquet → raises (callers handle the loud failure)
  - skipped parquet excluded from candidate set
  - companion skips missing → empty_skips_frame (NOT None)
  - companion skips present → returned as second tuple element
  - non-canonical filename → fall back to empty skips

Pure pytest; no streamlit context needed (the discover module forbids
streamlit imports at module time per SPECS §11.1).
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import pytest

from src.engine.results import (
    SKIPS_COLUMNS,
    empty_results_frame,
    empty_skips_frame,
)
from src.web.discover import find_latest_sweep, list_sweeps, read_sweep_with_skips


# ============================================================
# list_sweeps — multi-sweep enumeration for the topbar picker
# ============================================================

def test_list_sweeps_empty_results_dir_returns_empty_list(tmp_path: Path):
    """No sweep_*.parquet files → empty list."""
    assert list_sweeps(tmp_path) == []


def test_list_sweeps_missing_results_dir_returns_empty_list(tmp_path: Path):
    """Results dir doesn't exist → empty list, no exception."""
    missing = tmp_path / "definitely_does_not_exist"
    assert list_sweeps(missing) == []


def test_list_sweeps_returns_all_candidates(tmp_path: Path):
    """Multiple sweep parquets → all returned (and only sweep_*.parquet;
    *_skipped.parquet excluded)."""
    import time
    a = tmp_path / "sweep_a123.parquet"
    a.write_bytes(b"x")
    time.sleep(0.01)
    b = tmp_path / "sweep_b456.parquet"
    b.write_bytes(b"y")
    # Companion skips parquet — should NOT be in the result.
    skips = tmp_path / "sweep_a123_skipped.parquet"
    skips.write_bytes(b"z")
    out = list_sweeps(tmp_path)
    assert set(out) == {a, b}
    assert skips not in out


def test_list_sweeps_sorted_mtime_desc(tmp_path: Path):
    """LOAD-BEARING: list_sweeps[0] is the freshest sweep — matches
    find_latest_sweep's contract so callers can use list_sweeps[0]
    as the default selection."""
    import time
    older = tmp_path / "sweep_old.parquet"
    older.write_bytes(b"x")
    time.sleep(0.05)
    newer = tmp_path / "sweep_new.parquet"
    newer.write_bytes(b"y")
    out = list_sweeps(tmp_path)
    assert out[0] == newer
    assert out[-1] == older


def test_list_sweeps_first_matches_find_latest_sweep(tmp_path: Path):
    """LOAD-BEARING parity contract: ``list_sweeps[0] ==
    find_latest_sweep()`` so the topbar picker's default agrees
    with the single-sweep path."""
    import time
    a = tmp_path / "sweep_a.parquet"
    a.write_bytes(b"x")
    time.sleep(0.05)
    b = tmp_path / "sweep_b.parquet"
    b.write_bytes(b"y")
    assert list_sweeps(tmp_path)[0] == find_latest_sweep(tmp_path)


def test_list_sweeps_excludes_skipped_parquets(tmp_path: Path):
    """Defensive pin: companion ``*_skipped.parquet`` files MUST
    be excluded — they're metadata, not sweep results."""
    a = tmp_path / "sweep_a.parquet"
    a.write_bytes(b"x")
    skips = tmp_path / "sweep_a_skipped.parquet"
    skips.write_bytes(b"y")
    assert list_sweeps(tmp_path) == [a]


# ============================================================
# find_latest_sweep — empty / missing-dir cases
# ============================================================

def test_empty_results_dir_returns_none(tmp_path: Path):
    """No sweep_*.parquet files at all → None. Caller's job to render
    a 'no sweeps yet' empty state."""
    assert find_latest_sweep(tmp_path) is None


def test_missing_results_dir_returns_none(tmp_path: Path):
    """Results dir doesn't exist (fresh repo / clean checkout) → None.
    Defensive — no exception, just None."""
    missing = tmp_path / "definitely_does_not_exist"
    assert find_latest_sweep(missing) is None


def test_only_skipped_parquets_returns_none(tmp_path: Path):
    """Skipped-companion parquets must NOT count as candidates. A
    directory containing only `*_skipped.parquet` is still 'no sweeps'."""
    (tmp_path / "sweep_abc123_skipped.parquet").write_bytes(b"placeholder")
    assert find_latest_sweep(tmp_path) is None


# ============================================================
# find_latest_sweep — single / multiple candidates
# ============================================================

def _write_parquet(path: Path, rows: int = 1) -> Path:
    """Write a tiny parquet that read_parquet can ingest. Returns the path."""
    if rows == 0:
        df = empty_results_frame()
    else:
        # Use _full_row pattern; only writing the file matters for these tests
        df = pd.DataFrame({
            "run_id": pd.array(["x"] * rows, dtype="string"),
            "strategy": pd.array(["short_straddle"] * rows, dtype="string"),
            "symbol": pd.array(["RELIANCE"] * rows, dtype="string"),
            "net_pnl": [100.0] * rows,
        })
    df.to_parquet(path, index=False)
    return path


def test_single_parquet_returned(tmp_path: Path):
    p = _write_parquet(tmp_path / "sweep_aaa111.parquet")
    assert find_latest_sweep(tmp_path) == p


def test_multiple_parquets_returns_newest_mtime(tmp_path: Path):
    """LOAD-BEARING: the newest-mtime parquet wins. Matches operator's
    'the sweep I just ran' mental model per DESIGN_SPEC §1.5."""
    old = _write_parquet(tmp_path / "sweep_old.parquet")
    new = _write_parquet(tmp_path / "sweep_new.parquet")
    # Make `old` strictly older by 2s so the mtime gap is unambiguous
    # even on filesystems with second-resolution mtimes.
    old_time = time.time() - 5
    import os
    os.utime(old, (old_time, old_time))
    assert find_latest_sweep(tmp_path) == new


def test_mtime_ties_broken_by_name_ascending(tmp_path: Path):
    """LOAD-BEARING for determinism: when two files share an mtime (rare
    but possible on same-second writes), tie-break by name ASC. Without
    this the OS may return either order, breaking re-runs."""
    a = _write_parquet(tmp_path / "sweep_aaa.parquet")
    z = _write_parquet(tmp_path / "sweep_zzz.parquet")
    # Force identical mtimes
    import os
    t = time.time()
    os.utime(a, (t, t))
    os.utime(z, (t, t))
    # name-ASC → 'sweep_aaa' < 'sweep_zzz' lex, so aaa wins
    assert find_latest_sweep(tmp_path) == a


def test_skipped_parquet_excluded_alongside_real_sweep(tmp_path: Path):
    """A `*_skipped.parquet` companion next to a real sweep must NOT
    be picked even if its mtime is newer."""
    real = _write_parquet(tmp_path / "sweep_real.parquet")
    skip = tmp_path / "sweep_real_skipped.parquet"
    skip.write_bytes(b"placeholder")
    # Make skipped strictly newer
    import os
    t = time.time() + 5
    os.utime(skip, (t, t))
    assert find_latest_sweep(tmp_path) == real


# ============================================================
# read_sweep_with_skips — happy path + missing companion
# ============================================================

def test_read_missing_parquet_raises(tmp_path: Path):
    """Direct caller passes a stale path → loud FileNotFoundError.
    find_latest_sweep returns None first, so well-behaved callers
    don't hit this branch — but defensive raise for misuse."""
    with pytest.raises(FileNotFoundError, match="not found"):
        read_sweep_with_skips(tmp_path / "missing.parquet")


def test_read_returns_empty_skips_when_companion_missing(
    tmp_path: Path, monkeypatch
):
    """Sweep parquet exists; no companion skips. read_sweep_with_skips
    returns the canonical empty skips frame (NOT None) so callers can
    .groupby unconditionally.

    Uses monkeypatch.setattr per the project's standard isolation
    convention — auto-reverts on test teardown (no importlib.reload
    dance needed)."""
    p = _write_parquet(tmp_path / "sweep_xyz.parquet")
    # results.skips_path derives from results.RESULTS_DIR — point it
    # at tmp_path so the helper looks for the companion alongside the
    # test parquet, not in the real cache.
    from src.engine import results as results_mod
    monkeypatch.setattr(results_mod, "RESULTS_DIR", tmp_path)

    df, skips = read_sweep_with_skips(p)
    assert len(df) == 1
    assert isinstance(skips, pd.DataFrame)
    # Canonical schema preserved
    assert list(skips.columns) == list(SKIPS_COLUMNS)
    assert len(skips) == 0
    # Composability: groupby on empty frame doesn't raise
    skips.groupby("skip_reason").size()


def test_read_returns_populated_skips_when_companion_present(
    tmp_path: Path, monkeypatch
):
    """Both parquets present → both returned. Same monkeypatch.setattr
    isolation pattern as the missing-companion test."""
    p = _write_parquet(tmp_path / "sweep_xyz.parquet")
    skips_df = pd.DataFrame([{
        "run_id": "xyz",
        "strategy": "short_straddle",
        "symbol": "RELIANCE",
        "expiry": pd.Timestamp("2024-01-25"),
        "entry_offset_td": 15,
        "exit_offset_td": 1,
        "skip_reason": "MissingDataError",
    }])
    companion = tmp_path / "sweep_xyz_skipped.parquet"
    skips_df.to_parquet(companion, index=False)

    from src.engine import results as results_mod
    monkeypatch.setattr(results_mod, "RESULTS_DIR", tmp_path)

    df, skips = read_sweep_with_skips(p)
    assert len(df) == 1
    assert len(skips) == 1
    assert skips.iloc[0]["skip_reason"] == "MissingDataError"


def test_non_canonical_filename_falls_back_to_empty_skips(tmp_path: Path):
    """A caller-built path that doesn't follow the `sweep_<run_id>.parquet`
    convention can't have its run_id derived — discover returns empty
    skips rather than guessing or crashing."""
    odd = tmp_path / "custom_export.parquet"
    _write_parquet(odd)
    df, skips = read_sweep_with_skips(odd)
    assert len(df) == 1
    assert len(skips) == 0
    assert list(skips.columns) == list(SKIPS_COLUMNS)


# ============================================================
# Corrupt-file behavior — the loud failure path
# ============================================================

def test_corrupt_parquet_raises_on_read(tmp_path: Path):
    """A corrupt sweep parquet is loud, not silent. find_latest_sweep
    happily returns its path (which is fast — just glob + stat); the
    error surfaces in read_sweep_with_skips where pyarrow tries to
    decode it. Caller renders the error message instead of an empty
    leaderboard."""
    bad = tmp_path / "sweep_corrupt.parquet"
    bad.write_bytes(b"not actually parquet bytes")
    assert find_latest_sweep(tmp_path) == bad  # discovery is metadata-only
    with pytest.raises(Exception):  # pyarrow.lib.ArrowInvalid or similar
        read_sweep_with_skips(bad)


# ============================================================
# Streamlit-free module-import — pin SPECS §11.1
# ============================================================

def test_discover_module_imports_without_streamlit():
    """Pinned per SPECS §11.1: src/web/discover.py must NOT import
    streamlit at module time. Inspect sys.modules after a fresh import
    and confirm streamlit is absent (assuming the test process didn't
    import it for an unrelated reason). On a clean import, no streamlit
    side-effect should leak into the test runner."""
    import sys
    # If streamlit was imported by an earlier test, this test is silent.
    # Run in isolation: pytest tests/test_web_discover.py::test_..._streamlit
    # if you suspect contamination.
    pre = "streamlit" in sys.modules
    # Re-import in a fresh subinterpreter isn't trivial; instead read the
    # source file and grep for the literal string. Compile-time check.
    src = (
        Path(__file__).resolve().parent.parent / "src/web/discover.py"
    ).read_text()
    assert "import streamlit" not in src, (
        "src/web/discover.py imports streamlit — breaks unit-testability "
        "per SPECS §11.1"
    )
    assert "from streamlit" not in src
