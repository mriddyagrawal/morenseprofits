"""Tests for ``src.data.lot_size_lookup`` + ``src.data.bhavcopy_to_contract``
(P1.3 — MIGRATION.md §Phase 1 P1.3). Covers:

- lot_size_lookup cache-hit / cache-miss / no-parquet semantics.
- bhavcopy_to_contract_timeseries:
    - Schema parity with options_loader.load_option output (exact
      16 cols + dtypes + sort order).
    - Per-day filtering across [from_date, to_date].
    - volume = contracts × lot_size derivation.
    - MissingTurnoverError on excluded (sym, expiry) pair.
    - MissingTurnoverError on bad contracts value (≤0).
    - Empty range / no matching contract → empty frame with right schema.
    - Mixed-regime handling (legacy day produces uniform output).
- Module-level cache invalidation between tests via reset_lookup_cache().
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.data import cache
from src.data.bhavcopy_to_contract import (
    _OUTPUT_COLUMNS,
    bhavcopy_to_contract_timeseries,
    enumerate_contracts_from_bhavcopies,
    materialize_contract_from_bhavcopy,
    materialize_contracts_batch,
)
from src.data.errors import MissingTurnoverError
from src.data.lot_size_lookup import (
    _load_lot_sizes_parquet,
    lot_size_lookup,
    reset_lookup_cache,
)


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch, tmp_path):
    """Each test gets a fresh cache root + a cleared lookup cache."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache, "_ensure_root", lambda: tmp_path)
    reset_lookup_cache()
    yield
    reset_lookup_cache()


# ============================================================
# lot_size_lookup
# ============================================================

def test_lot_size_lookup_returns_none_when_parquet_missing(tmp_path):
    """No parquet on disk → every lookup returns None. Matches the
    semantics of "prefetch hasn't run yet" → every cell is
    structurally unbacktestable."""
    assert lot_size_lookup("PNB", date(2024, 6, 27)) is None


def test_lot_size_lookup_hit(tmp_path):
    """Round-trip a synthesized cache and confirm the lookup
    succeeds with the correct value + correct year/month
    interpretation (expiry_date.month → cache month column)."""
    _write_lot_sizes_parquet(tmp_path, [
        ("PNB", 2024, 6, 8000),
        ("RELIANCE", 2024, 8, 250),
    ])
    assert lot_size_lookup("PNB", date(2024, 6, 27)) == 8000
    assert lot_size_lookup("RELIANCE", date(2024, 8, 29)) == 250


def test_lot_size_lookup_miss_returns_none(tmp_path):
    """An excluded (sym, expiry-month) pair → cache has no row →
    lookup returns None."""
    _write_lot_sizes_parquet(tmp_path, [
        ("PNB", 2024, 6, 8000),
    ])
    # ABBOTINDIA 24May was excluded by the build script (see
    # documented sidecar-vs-sidecar mismatch); simulated here by
    # the absence of the row in the synthesized cache.
    assert lot_size_lookup("ABBOTINDIA", date(2024, 5, 30)) is None


def test_lot_size_lookup_is_case_insensitive_on_symbol(tmp_path):
    """``lot_size_lookup`` accepts mixed-case input and matches
    against the upper-cased cache values (operator-facing
    consistency)."""
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 6, 8000)])
    assert lot_size_lookup("pnb", date(2024, 6, 27)) == 8000
    assert lot_size_lookup("Pnb", date(2024, 6, 27)) == 8000


# ============================================================
# bhavcopy_to_contract_timeseries — schema parity (LOAD-BEARING)
# ============================================================

def test_transform_output_schema_matches_options_loader_exactly(tmp_path):
    """LOAD-BEARING (per reviewer grill #1 on e0bc85a, tightened in
    10f36be). The transform's output schema MUST be byte-identical
    to the options_loader.load_option output. Spec:
      - Same column NAMES in the same ORDER (16 cols).
      - Same dtype per column.
    Hand-curate a 2-day bhavcopy cache for one contract; assert
    each column meets the contract."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 22),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.5, 5.0, 4.0, 4.8, 4.85, 4.9,
               100, 84000.0, 1000, 200)],
        is_udiff=True,
    )
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.10, 5.05,
               150, 130000.0, 1100, 100)],
        is_udiff=True,
    )

    df = bhavcopy_to_contract_timeseries(
        "PNB", pnb_exp, 100.0, "CE",
        from_date=date(2024, 7, 22), to_date=date(2024, 7, 23),
    )

    # Same names + order as options_loader's _SPEC_COLS.
    assert list(df.columns) == _OUTPUT_COLUMNS

    # Dtypes (mirror options_loader's _normalize() output).
    assert df["date"].dtype.name == "datetime64[us]"
    assert df["symbol"].dtype == pd.StringDtype()
    assert df["expiry"].dtype.name == "datetime64[us]"
    assert df["option_type"].dtype == pd.StringDtype()
    for c in ("strike", "open", "high", "low", "close", "ltp",
              "settle_price", "turnover"):
        assert df[c].dtype.name == "float64", f"{c} dtype = {df[c].dtype.name}"
    assert df["lot_size"].dtype.name == "int64"
    assert df["volume"].dtype.name == "int64"
    assert df["oi"].dtype.name == "Int64"
    assert df["oi_change"].dtype.name == "Int64"


def test_transform_derives_volume_via_contracts_times_lot_size(tmp_path):
    """LOAD-BEARING: volume = contracts × lot_size. Hand-checkable
    pin: contracts=150, lot_size=8000 → volume=1,200,000."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.10, 5.05,
               150, 130000.0, 1100, 100)],
        is_udiff=True,
    )
    df = bhavcopy_to_contract_timeseries(
        "PNB", pnb_exp, 100.0, "CE",
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )
    assert len(df) == 1
    assert int(df.iloc[0]["lot_size"]) == 8000
    assert int(df.iloc[0]["volume"]) == 150 * 8000


def test_transform_sorted_by_date_ascending(tmp_path):
    """Concat result must be sorted by ``date`` ascending — the
    options_loader._normalize() output guarantees this and the
    sweep workers depend on it for monotonic date traversal."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    # Write days OUT OF ORDER to verify the transform sorts.
    for d in (date(2024, 7, 25), date(2024, 7, 22), date(2024, 7, 23)):
        _write_synthetic_bhavcopy_day(
            tmp_path, d,
            rows=[("PNB", pnb_exp, 100.0, "CE",
                   4.8, 5.5, 4.5, 5.0, 5.10, 5.05,
                   100, 84000.0, 1000, 0)],
            is_udiff=True,
        )
    df = bhavcopy_to_contract_timeseries(
        "PNB", pnb_exp, 100.0, "CE",
        from_date=date(2024, 7, 22), to_date=date(2024, 7, 26),
    )
    dates = df["date"].dt.date.tolist()
    assert dates == sorted(dates)


# ============================================================
# bhavcopy_to_contract_timeseries — error paths
# ============================================================

def test_transform_raises_when_lot_size_excluded(tmp_path):
    """Per the per-pair-exclude policy: an excluded
    (sym, expiry-month) → lookup returns None → transform raises
    MissingTurnoverError (auto-skippable via _SKIPPABLE_ERRORS at
    sweep time)."""
    pnb_exp = date(2024, 5, 30)
    # Lot-sizes parquet exists but doesn't have ABBOTINDIA May 2024
    # (simulates the documented mismatch-driven exclusion).
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 6, 8000)])
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 5, 22),
        rows=[("ABBOTINDIA", pnb_exp, 25000.0, "CE",
               100.0, 110.0, 95.0, 105.0, 106.0, 105.5,
               10, 100000.0, 50, 5)],
        is_udiff=True,
    )
    with pytest.raises(MissingTurnoverError, match="lot_size unavailable"):
        bhavcopy_to_contract_timeseries(
            "ABBOTINDIA", pnb_exp, 25000.0, "CE",
            from_date=date(2024, 5, 22), to_date=date(2024, 5, 22),
        )


def test_missing_turnover_error_is_skippable_via_sweeper_errors():
    """LOAD-BEARING: MissingTurnoverError MUST be a MissingDataError
    subtype so the sweeper's existing _SKIPPABLE_ERRORS catches it
    without code change. Anti-regression against future refactors
    that might break the subtype relationship."""
    from src.data.errors import MissingDataError
    from src.engine.sweeper import _SKIPPABLE_ERRORS

    assert issubclass(MissingTurnoverError, MissingDataError)
    # The sweeper catches by tuple membership against
    # MissingDataError; sub-types are matched implicitly.
    assert MissingDataError in _SKIPPABLE_ERRORS


def test_transform_raises_only_when_contract_never_traded(tmp_path):
    """Reject the contract ONLY if EVERY cached day in the window has
    ``contracts == 0`` — i.e. it was never actually traded. Listing-
    day-to-first-trade lag, quiet weeks, and the day before expiry
    routinely produce single zero-contracts rows in an otherwise
    active contract's life; rejecting on ANY-zero would discard
    nearly every real contract (≈9098/9392 in a 2-symbol smoke run
    — the bug that motivated this test).
    """
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    # Two cached days, both zero-contracts → contract was never
    # actually traded → loud-fail with MissingTurnoverError.
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 22),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
               0, 0.0, 0, 0)],
        is_udiff=True,
    )
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
               0, 0.0, 0, 0)],
        is_udiff=True,
    )
    with pytest.raises(MissingTurnoverError, match="never actually traded"):
        bhavcopy_to_contract_timeseries(
            "PNB", pnb_exp, 100.0, "CE",
            from_date=date(2024, 7, 22), to_date=date(2024, 7, 23),
        )


def test_transform_keeps_partial_zero_contract(tmp_path):
    """Positive-control for the ANY → ALL semantics shift: a real
    NSE contract with ONE zero-contracts day (listing lag, quiet
    day) flanked by traded days must be KEPT, not rejected. Zero-
    contracts rows pass through with volume=0; the engine's per-row
    IlliquidLegError gate handles them at sweep time (matches
    options_loader.load_option's behaviour)."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    # Day 1: zero contracts (listing-lag).
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 22),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               0.0, 0.0, 0.0, 0.0, 0.0, 5.05,
               0, 0.0, 0, 0)],
        is_udiff=True,
    )
    # Day 2: real trades.
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.10, 5.05,
               100, 84000.0, 1100, 100)],
        is_udiff=True,
    )
    df = bhavcopy_to_contract_timeseries(
        "PNB", pnb_exp, 100.0, "CE",
        from_date=date(2024, 7, 22), to_date=date(2024, 7, 23),
    )
    # Both days survive; the zero-contracts day has volume = 0.
    assert len(df) == 2
    assert df.iloc[0]["volume"] == 0
    assert df.iloc[1]["volume"] == 100 * 8000


# ============================================================
# Empty-range + missing-day handling
# ============================================================

def test_transform_empty_when_no_matching_contract(tmp_path):
    """Bhavcopy days exist but none have the queried contract →
    empty frame with the right schema (so downstream pipelines can
    still concat / sort / dtype-check without crashing)."""
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    # Cache has a different contract; the query asks for PNB but
    # the parquet has RELIANCE.
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("RELIANCE", date(2024, 7, 25), 2800.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.10, 5.05,
               150, 130000.0, 1100, 100)],
        is_udiff=True,
    )
    df = bhavcopy_to_contract_timeseries(
        "PNB", date(2024, 7, 25), 100.0, "CE",
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )
    assert len(df) == 0
    assert list(df.columns) == _OUTPUT_COLUMNS


def test_transform_silently_skips_missing_bhavcopy_days(tmp_path):
    """Holiday / weekend / pre-listing gaps → no parquet on disk
    for that date. Transform silently skips (matches
    options_loader's behavior on the same gaps)."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    # Only ONE day's parquet exists; the range covers 3 days.
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.10, 5.05,
               100, 84000.0, 1000, 0)],
        is_udiff=True,
    )
    df = bhavcopy_to_contract_timeseries(
        "PNB", pnb_exp, 100.0, "CE",
        from_date=date(2024, 7, 22), to_date=date(2024, 7, 24),
    )
    assert len(df) == 1
    assert df.iloc[0]["date"] == pd.Timestamp(date(2024, 7, 23))


# ============================================================
# Mixed-regime: legacy day (no ltp) yields NaN ltp uniformly
# ============================================================

def test_transform_legacy_day_yields_nan_ltp(tmp_path):
    """Legacy bhavcopy days don't carry ltp (15-col parser output).
    Transform inserts NaN ltp so the unified output schema stays
    16-col across regimes. Anti-regression against future drift
    where a legacy day might silently get ltp=0.0."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    # Write a LEGACY-shaped row (no ltp column).
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, None, 5.05,
               100, 84000.0, 1000, 0)],
        is_udiff=False,
    )
    df = bhavcopy_to_contract_timeseries(
        "PNB", pnb_exp, 100.0, "CE",
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["ltp"])


# ============================================================
# materialize_contract_from_bhavcopy (P1.4)
# ============================================================

def test_materialize_writes_to_options_loader_path(tmp_path):
    """LOAD-BEARING: materialize writes to the same disk path the
    options_loader uses (``cache.option_path``). Sweep workers
    read THIS path, so the bhavcopy-derived parquet has to land
    there byte-identical to what options_loader.load_option would
    have produced."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.10, 5.05,
               100, 84000.0, 1000, 0)],
        is_udiff=True,
    )
    expected_path = cache.option_path("PNB", pnb_exp, 100.0, "CE")
    assert not expected_path.exists()

    written = materialize_contract_from_bhavcopy(
        "PNB", pnb_exp, 100.0, "CE",
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )

    assert written == expected_path
    assert expected_path.exists()
    df_on_disk = cache.read(expected_path)
    assert list(df_on_disk.columns) == _OUTPUT_COLUMNS
    assert len(df_on_disk) == 1
    assert int(df_on_disk.iloc[0]["lot_size"]) == 8000
    assert int(df_on_disk.iloc[0]["volume"]) == 100 * 8000


def test_materialize_is_idempotent_without_force(tmp_path, monkeypatch):
    """Second call with force=False is a no-op — does NOT re-invoke
    the transform. Verified by monkeypatching the transform to
    detect re-entry."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.10, 5.05,
               100, 84000.0, 1000, 0)],
        is_udiff=True,
    )
    materialize_contract_from_bhavcopy(
        "PNB", pnb_exp, 100.0, "CE",
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )

    # Monkeypatch the transform to raise — if the second call doesn't
    # short-circuit via the file-exists check, this raises.
    import src.data.bhavcopy_to_contract as btc
    sentinel = []
    def _spy_transform(*args, **kwargs):
        sentinel.append("called")
        raise RuntimeError("transform was re-invoked on idempotent call")
    monkeypatch.setattr(btc, "bhavcopy_to_contract_timeseries", _spy_transform)

    # Second call should NOT trigger the transform.
    materialize_contract_from_bhavcopy(
        "PNB", pnb_exp, 100.0, "CE",
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )
    assert sentinel == [], (
        "idempotent call re-invoked the transform; the file-exists "
        "short-circuit is broken"
    )


def test_materialize_force_true_rewrites(tmp_path):
    """force=True rewrites unconditionally. Verified by mutating the
    underlying bhavcopy day's contents and confirming the materialized
    parquet picks up the new values after force=True."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.10, 5.05,
               100, 84000.0, 1000, 0)],
        is_udiff=True,
    )
    # First materialize.
    materialize_contract_from_bhavcopy(
        "PNB", pnb_exp, 100.0, "CE",
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )
    path = cache.option_path("PNB", pnb_exp, 100.0, "CE")
    first_close = cache.read(path).iloc[0]["close"]
    assert first_close == 5.0

    # Mutate the source bhavcopy: close → 6.5, contracts → 200.
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               6.0, 7.0, 5.5, 6.5, 6.55, 6.50,
               200, 168000.0, 1100, 100)],
        is_udiff=True,
    )

    # force=False would short-circuit; force=True rewrites.
    materialize_contract_from_bhavcopy(
        "PNB", pnb_exp, 100.0, "CE",
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
        force=True,
    )
    refreshed = cache.read(path).iloc[0]
    assert refreshed["close"] == 6.5
    assert int(refreshed["volume"]) == 200 * 8000


def test_materialize_propagates_missing_turnover_error_no_partial_file(tmp_path):
    """When the transform raises MissingTurnoverError (e.g. on an
    excluded (sym, expiry-month)), no partial parquet is written —
    the caller can retry once the underlying data is fixed."""
    pnb_exp = date(2024, 5, 30)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 5, 22),
        rows=[("ABBOTINDIA", pnb_exp, 25000.0, "CE",
               100.0, 110.0, 95.0, 105.0, 106.0, 105.5,
               10, 100000.0, 50, 5)],
        is_udiff=True,
    )
    expected_path = cache.option_path(
        "ABBOTINDIA", pnb_exp, 25000.0, "CE",
    )
    with pytest.raises(MissingTurnoverError):
        materialize_contract_from_bhavcopy(
            "ABBOTINDIA", pnb_exp, 25000.0, "CE",
            from_date=date(2024, 5, 22), to_date=date(2024, 5, 22),
        )
    assert not expected_path.exists(), (
        "transform error path wrote a partial / empty file; the caller "
        "can't distinguish 'first call failed' from 'cached empty result'"
    )


# ============================================================
# enumerate_contracts_from_bhavcopies (P1.5)
# ============================================================

def test_enumerate_returns_unique_sorted_tuples(tmp_path):
    """Enumeration scans the bhavcopy cache + returns one entry per
    unique (sym, expiry, strike, option_type), sorted for
    deterministic iteration order across runs."""
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    pnb_exp = date(2024, 7, 25)
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[
            ("PNB", pnb_exp, 100.0, "CE",
             4.5, 5.0, 4.0, 4.8, 4.85, 4.9, 100, 84000.0, 1000, 0),
            ("PNB", pnb_exp, 105.0, "CE",
             3.5, 4.0, 3.0, 3.8, 3.85, 3.9, 50, 42000.0, 500, 0),
            ("PNB", pnb_exp, 100.0, "PE",
             2.5, 3.0, 2.0, 2.8, 2.85, 2.9, 75, 7500.0, 800, 0),
        ],
        is_udiff=True,
    )
    # Second day surfaces ONE new strike and re-surfaces the others.
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 24),
        rows=[
            ("PNB", pnb_exp, 100.0, "CE",
             4.8, 5.5, 4.5, 5.0, 5.1, 5.05, 150, 130000.0, 1100, 100),
            ("PNB", pnb_exp, 110.0, "CE",
             2.5, 3.0, 2.0, 2.8, 2.85, 2.9, 25, 21000.0, 200, 0),
        ],
        is_udiff=True,
    )
    contracts = enumerate_contracts_from_bhavcopies(
        symbols=["PNB"],
        from_date=date(2024, 7, 22), to_date=date(2024, 7, 25),
    )
    # 4 unique (sym, expiry, strike, option_type) tuples across the
    # 2 days; sorted ascending.
    assert contracts == [
        ("PNB", pnb_exp, 100.0, "CE"),
        ("PNB", pnb_exp, 100.0, "PE"),
        ("PNB", pnb_exp, 105.0, "CE"),
        ("PNB", pnb_exp, 110.0, "CE"),
    ]


def test_enumerate_filters_to_operator_symbols(tmp_path):
    """Symbols not in the operator's list are excluded from
    enumeration (4-stock smoke shouldn't enumerate every F&O symbol
    that traded in the bhavcopy)."""
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[
            ("PNB", date(2024, 7, 25), 100.0, "CE",
             4.5, 5.0, 4.0, 4.8, 4.85, 4.9, 100, 84000.0, 1000, 0),
            ("RELIANCE", date(2024, 7, 25), 2840.0, "CE",
             201.7, 210.0, 195.0, 205.0, 205.5, 205.1, 26, 5300000.0, 41500, -1500),
        ],
        is_udiff=True,
    )
    contracts = enumerate_contracts_from_bhavcopies(
        symbols=["PNB"],
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )
    assert all(c[0] == "PNB" for c in contracts), (
        "RELIANCE leaked into PNB-only enumeration"
    )


def test_enumerate_silently_skips_missing_days(tmp_path):
    """Holidays / pre-listing gaps don't crash enumeration. The
    days are simply not in the result."""
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", date(2024, 7, 25), 100.0, "CE",
               4.5, 5.0, 4.0, 4.8, 4.85, 4.9, 100, 84000.0, 1000, 0)],
        is_udiff=True,
    )
    # Range covers 5 days; only 1 has a cached bhavcopy.
    contracts = enumerate_contracts_from_bhavcopies(
        symbols=["PNB"],
        from_date=date(2024, 7, 21), to_date=date(2024, 7, 25),
    )
    assert len(contracts) == 1


def test_enumerate_is_case_insensitive_on_symbol(tmp_path):
    """Operator passes mixed-case symbol → enumerate normalizes
    to upper-case before matching."""
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", date(2024, 7, 25), 100.0, "CE",
               4.5, 5.0, 4.0, 4.8, 4.85, 4.9, 100, 84000.0, 1000, 0)],
        is_udiff=True,
    )
    contracts = enumerate_contracts_from_bhavcopies(
        symbols=["pnb"],  # lowercase
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )
    assert len(contracts) == 1
    assert contracts[0][0] == "PNB"


# ============================================================
# materialize_contracts_batch (perf optimization)
# ============================================================

def test_batch_materializes_all_contracts_in_one_pass(tmp_path):
    """LOAD-BEARING: the batch path writes the same per-contract
    parquets as the per-contract path would, just in one pass over
    the bhavcopy cache. Verified by running both paths and
    asserting byte-equality on the on-disk parquet contents."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [
        ("PNB", 2024, 7, 8000), ("PNB", 2024, 8, 8000),
    ])
    # Day 1: PNB 100 CE + PNB 105 CE.
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 22),
        rows=[
            ("PNB", pnb_exp, 100.0, "CE",
             4.5, 5.0, 4.0, 4.8, 4.85, 4.9, 100, 84000.0, 1000, 0),
            ("PNB", pnb_exp, 105.0, "CE",
             3.5, 4.0, 3.0, 3.8, 3.85, 3.9, 50, 42000.0, 500, 0),
        ],
        is_udiff=True,
    )
    # Day 2: PNB 100 CE.
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.1, 5.05, 150, 130000.0, 1100, 100)],
        is_udiff=True,
    )

    counts = materialize_contracts_batch(
        symbols=["PNB"],
        from_date=date(2024, 7, 22), to_date=date(2024, 7, 23),
    )

    # Both unique contracts written.
    assert counts["materialized"] == 2
    assert counts["already_cached"] == 0
    assert counts["skipped_missing_turnover"] == 0
    assert counts["skipped_other"] == 0

    # Parquets exist at the expected paths.
    p100 = cache.option_path("PNB", pnb_exp, 100.0, "CE")
    p105 = cache.option_path("PNB", pnb_exp, 105.0, "CE")
    assert p100.exists()
    assert p105.exists()

    # 100-CE has 2 rows (both days); 105-CE has 1 row.
    df100 = cache.read(p100)
    df105 = cache.read(p105)
    assert len(df100) == 2
    assert len(df105) == 1
    assert list(df100.columns) == _OUTPUT_COLUMNS


def test_batch_output_matches_per_contract_path_for_same_inputs(tmp_path):
    """LOAD-BEARING equivalence: batch and per-contract paths
    produce byte-identical on-disk parquets for the same inputs.
    Anti-regression against a future _assemble_output_frame
    divergence between the two call sites."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.1, 5.05, 150, 130000.0, 1100, 100)],
        is_udiff=True,
    )

    # Per-contract path.
    materialize_contract_from_bhavcopy(
        "PNB", pnb_exp, 100.0, "CE",
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )
    p1 = cache.option_path("PNB", pnb_exp, 100.0, "CE")
    df_per = cache.read(p1)

    # Wipe + batch path.
    p1.unlink()
    counts = materialize_contracts_batch(
        symbols=["PNB"],
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )
    df_batch = cache.read(p1)

    assert counts["materialized"] == 1
    # Byte-equality on the round-tripped frame.
    pd.testing.assert_frame_equal(df_per, df_batch)


def test_batch_skips_already_cached_contracts(tmp_path):
    """Cache-first idempotency at the batch level: a contract
    already materialized is reported as ``already_cached``, not
    re-written."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.1, 5.05, 150, 130000.0, 1100, 100)],
        is_udiff=True,
    )

    # First batch.
    counts1 = materialize_contracts_batch(
        symbols=["PNB"],
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )
    assert counts1["materialized"] == 1

    # Second batch — already cached.
    counts2 = materialize_contracts_batch(
        symbols=["PNB"],
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )
    assert counts2["materialized"] == 0
    assert counts2["already_cached"] == 1


def test_batch_force_true_rewrites_all(tmp_path):
    """``force=True`` bypasses the cache-first check at the batch
    level."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.1, 5.05, 150, 130000.0, 1100, 100)],
        is_udiff=True,
    )
    # Prime cache.
    materialize_contracts_batch(
        symbols=["PNB"],
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
    )
    # Force-rewrite.
    counts = materialize_contracts_batch(
        symbols=["PNB"],
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
        force=True,
    )
    assert counts["materialized"] == 1
    assert counts["already_cached"] == 0


def test_batch_skips_excluded_lot_size_pairs_with_named_reason(tmp_path):
    """An excluded (sym, expiry-month) doesn't crash the batch — it
    increments ``skipped_missing_turnover`` and adds a log entry.
    Other contracts in the same batch continue to materialize."""
    pnb_exp = date(2024, 7, 25)
    abbott_exp = date(2024, 5, 30)
    # Lot-sizes parquet has PNB but NOT ABBOTINDIA (simulating the
    # documented sidecar-vs-sidecar exclusion).
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 5, 22),
        rows=[
            ("ABBOTINDIA", abbott_exp, 25000.0, "CE",
             100.0, 110.0, 95.0, 105.0, 106.0, 105.5, 10, 100000.0, 50, 5),
        ],
        is_udiff=True,
    )
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[("PNB", pnb_exp, 100.0, "CE",
               4.8, 5.5, 4.5, 5.0, 5.1, 5.05, 150, 130000.0, 1100, 100)],
        is_udiff=True,
    )

    counts = materialize_contracts_batch(
        symbols=["ABBOTINDIA", "PNB"],
        from_date=date(2024, 5, 22), to_date=date(2024, 7, 23),
    )
    # PNB succeeds; ABBOTINDIA gets skipped.
    assert counts["materialized"] == 1
    assert counts["skipped_missing_turnover"] == 1
    assert any(
        "ABBOTINDIA" in str(row[0]) and "lot_size excluded" in str(row[4])
        for row in counts["skip_log"]
    )


def test_batch_progress_callback_fires_per_group(tmp_path):
    """``progress_callback`` is invoked once per (sym, expiry,
    strike, option_type) group. Lets prefetch_universe report
    coarse-grained progress without each contract printing."""
    pnb_exp = date(2024, 7, 25)
    _write_lot_sizes_parquet(tmp_path, [("PNB", 2024, 7, 8000)])
    _write_synthetic_bhavcopy_day(
        tmp_path, date(2024, 7, 23),
        rows=[
            ("PNB", pnb_exp, 100.0, "CE",
             4.5, 5.0, 4.0, 4.8, 4.85, 4.9, 100, 84000.0, 1000, 0),
            ("PNB", pnb_exp, 105.0, "CE",
             3.5, 4.0, 3.0, 3.8, 3.85, 3.9, 50, 42000.0, 500, 0),
            ("PNB", pnb_exp, 100.0, "PE",
             2.5, 3.0, 2.0, 2.8, 2.85, 2.9, 75, 7500.0, 800, 0),
        ],
        is_udiff=True,
    )
    seen = []
    def _cb(processed: int, total: int) -> None:
        seen.append((processed, total))
    materialize_contracts_batch(
        symbols=["PNB"],
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 23),
        progress_callback=_cb,
    )
    # 3 unique contracts → 3 callback invocations; processed counts
    # ascend; total stays constant.
    assert len(seen) == 3
    assert [p for p, _ in seen] == [1, 2, 3]
    assert all(t == 3 for _, t in seen)


def test_batch_empty_cache_returns_zero_counts(tmp_path):
    """No bhavcopies in the date range → returns zero counts cleanly,
    not an empty-frame crash. Operator can run the batch as a no-op
    to confirm the wiring works."""
    counts = materialize_contracts_batch(
        symbols=["PNB"],
        from_date=date(2024, 7, 23), to_date=date(2024, 7, 25),
    )
    assert counts["materialized"] == 0
    assert counts["already_cached"] == 0
    assert counts["skipped_missing_turnover"] == 0
    assert counts["skipped_other"] == 0


# ============================================================
# Helpers — synthetic fixture builders
# ============================================================

def _write_lot_sizes_parquet(
    cache_root: Path,
    rows: list[tuple[str, int, int, int]],
):
    """Write a minimal unified lot-sizes parquet with (sym, year,
    month, lot_size) tuples — mimics what build_lot_size_parquet
    would produce."""
    df = pd.DataFrame({
        "symbol": pd.Series([r[0] for r in rows], dtype="string"),
        "year":   pd.Series([r[1] for r in rows], dtype="int64"),
        "month":  pd.Series([r[2] for r in rows], dtype="int64"),
        "lot_size": pd.Series([r[3] for r in rows], dtype="int64"),
        "source": pd.Series(["sidecar"] * len(rows), dtype="string"),
    })
    path = cache_root / "lot_sizes.parquet"
    df.to_parquet(path, index=False)


def _write_synthetic_bhavcopy_day(
    cache_root: Path,
    trade_date: date,
    rows: list[tuple],
    *, is_udiff: bool,
):
    """Write a minimal bhavcopy parquet matching the parser output
    schemas. ``rows`` is a list of:
    (symbol, expiry, strike, option_type, open, high, low, close,
     ltp, settle_price, contracts, turnover, oi, oi_change)
    The ``ltp`` slot is ignored when ``is_udiff=False`` (legacy
    parser output doesn't have the column).
    """
    out_rows = []
    for r in rows:
        (sym, exp, strike, opt, o, h, lo, c, ltp, settle,
         contracts, turnover, oi, doi) = r
        row = {
            "instrument": "OPTSTK",
            "symbol": sym,
            "expiry": pd.Timestamp(exp),
            "strike": float(strike),
            "option_type": opt,
            "open": float(o),
            "high": float(h),
            "low": float(lo),
            "close": float(c),
            "settle_price": float(settle),
            "contracts": int(contracts),
            "turnover": float(turnover),
            "oi": pd.NA if oi is None else int(oi),
            "oi_change": pd.NA if doi is None else int(doi),
            "trade_date": pd.Timestamp(trade_date),
        }
        if is_udiff:
            row["ltp"] = float("nan") if ltp is None else float(ltp)
        out_rows.append(row)
    df = pd.DataFrame(out_rows)
    # Enforce dtypes to match parser output.
    df["instrument"] = df["instrument"].astype("string")
    df["symbol"] = df["symbol"].astype("string")
    df["option_type"] = df["option_type"].astype("string")
    df["expiry"] = df["expiry"].astype("datetime64[us]")
    df["trade_date"] = df["trade_date"].astype("datetime64[us]")
    df["oi"] = df["oi"].astype("Int64")
    df["oi_change"] = df["oi_change"].astype("Int64")
    # Reorder to match parser output (UDiff: 16 cols; legacy: 15).
    if is_udiff:
        cols = [
            "instrument", "symbol", "expiry", "strike", "option_type",
            "open", "high", "low", "close", "ltp", "settle_price",
            "contracts", "turnover", "oi", "oi_change", "trade_date",
        ]
    else:
        cols = [
            "instrument", "symbol", "expiry", "strike", "option_type",
            "open", "high", "low", "close", "settle_price",
            "contracts", "turnover", "oi", "oi_change", "trade_date",
        ]
    df = df[cols]
    path = cache_root / "bhavcopy_fo" / f"{trade_date.strftime('%Y%m%d')}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
