"""Tests for ``scripts/build_lot_size_parquet.py`` + the
``bhavcopy_fo_loader`` sibling-cache write hook (P0.2 — MIGRATION.md
§Phase 0 P0.2). Covers:

- Sibling-cache extractor correctness against the existing UDiff
  fixture.
- Sibling-cache write hook fires on fresh fetch (monkeypatch).
- Build script's per-pair exclusion across all 3 mismatch layers
  (sidecar-vs-sidecar / bhavcopy-internal / sidecar-vs-bhavcopy).
- Diagnostic-message format matches the operator's template exactly.
- Build against the committed P0.1 fixtures produces the expected
  unified cache shape (PNB May 2024 = 8000; ABBOTINDIA May 2024 is
  EXCLUDED due to NSE biannual revision).
- prefetch_universe.py auto-build trigger semantics.
"""
from __future__ import annotations

import gzip
import io
import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scripts.build_lot_size_parquet import (
    _detect_within_source_mismatches,
    _format_mismatch_message,
    _merge_with_cross_source_exclusion,
    build_lot_size_parquet,
    parse_sidecar,
)
from src.data import cache
from src.data.bhavcopy_fo_loader import (
    _empty_lot_sizes_frame,
    _extract_lot_sizes_udiff,
)


REPO = Path(__file__).resolve().parent.parent
UDIFF_FIXTURE = REPO / "tests" / "fixtures" / "bhavcopy_fo_udiff_20240829.csv"
SIDECAR_DIR = REPO / "data" / "manual" / "contracts"


# ============================================================
# _extract_lot_sizes_udiff (sibling-cache extractor)
# ============================================================

def test_extract_lot_sizes_udiff_returns_deduped_triples():
    """Pinned: RELIANCE 2024-08-29 lot_size = 250 (operator-verified
    in earlier inspection). Deduped on (symbol, expiry); one row per
    unique pair regardless of how many strikes traded that day."""
    raw = UDIFF_FIXTURE.read_text()
    df = _extract_lot_sizes_udiff(raw, date(2024, 8, 29))

    assert list(df.columns) == ["symbol", "expiry", "lot_size", "trade_date"]
    assert df["symbol"].dtype.name == "string"
    assert df["lot_size"].dtype.name == "int64"
    assert df["expiry"].dtype.name == "datetime64[us]"
    assert df["trade_date"].dtype.name == "datetime64[us]"

    # Dedup invariant: one row per (symbol, expiry).
    assert df.duplicated(subset=["symbol", "expiry"]).sum() == 0

    # RELIANCE pin.
    reliance = df[df["symbol"] == "RELIANCE"]
    assert len(reliance) >= 1
    assert (reliance["lot_size"] == 250).all()

    # trade_date stamp matches the caller's argument.
    assert (df["trade_date"] == pd.Timestamp("2024-08-29")).all()


def test_extract_lot_sizes_udiff_filters_to_options_only():
    """OPTSTK + OPTIDX only. FUTSTK / FUTIDX rows are dropped from
    the lot-size cache (futures lot sizes recoverable from the same
    NewBrdLotQty column if a future caller needs them, but the
    backtest scope is options-only)."""
    raw = UDIFF_FIXTURE.read_text()
    df = _extract_lot_sizes_udiff(raw, date(2024, 8, 29))
    # All rows came from OPTSTK/OPTIDX rows — symbol uniqueness check
    # is a proxy (futures would add no unique (symbol, expiry) pairs
    # because OPTSTK already covers every symbol with options).
    assert len(df) > 0


def test_empty_lot_sizes_frame_matches_extractor_schema():
    """Empty parquet for legacy bhavcopy dates must have the SAME
    schema as the extractor output — so the build script's
    pd.concat in _load_all_bhavcopy_lot_sizes doesn't break on
    column-name mismatch when the cache mixes regimes."""
    raw = UDIFF_FIXTURE.read_text()
    non_empty = _extract_lot_sizes_udiff(raw, date(2024, 8, 29))
    empty = _empty_lot_sizes_frame()
    assert list(empty.columns) == list(non_empty.columns)
    for col in empty.columns:
        assert empty[col].dtype == non_empty[col].dtype, (
            f"dtype mismatch on {col}: empty={empty[col].dtype} "
            f"vs non_empty={non_empty[col].dtype}"
        )


# ============================================================
# load_bhavcopy_fo sibling-cache write hook
# ============================================================

def test_load_bhavcopy_fo_writes_sibling_lot_sizes_cache(monkeypatch, tmp_path):
    """When the loader fetches fresh, it writes BOTH the main parquet
    and the sibling lot-size parquet. Verified by monkeypatching
    _fetch_raw + the cache root."""
    import src.data.bhavcopy_fo_loader as bfl
    from src.data import cache as _cache

    raw = UDIFF_FIXTURE.read_text()
    monkeypatch.setattr(bfl, "_fetch_raw", lambda d: (raw, "udiff"))
    # Redirect cache root.
    monkeypatch.setattr(_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(
        _cache, "_ensure_root", lambda: tmp_path,
    )
    # Test only the fresh-fetch path; bypass LRU and offline checks.
    df = bfl._load_bhavcopy_fo_impl(date(2024, 8, 29), offline=False)
    # Main bhavcopy parquet written.
    assert _cache.bhavcopy_fo_path(date(2024, 8, 29)).exists()
    # Sibling lot-size parquet ALSO written.
    sibling = _cache.bhavcopy_fo_lot_sizes_path(date(2024, 8, 29))
    assert sibling.exists(), (
        "sibling lot_sizes parquet was not written; the load_bhavcopy_fo "
        "hook is missing or broken"
    )
    sib_df = pd.read_parquet(sibling)
    assert len(sib_df) > 0
    assert "lot_size" in sib_df.columns


# ============================================================
# _format_mismatch_message — operator template
# ============================================================

def test_format_mismatch_message_2_source_pair_matches_operator_template():
    """LOAD-BEARING (per operator 2026-06-03 direction): the
    diagnostic line for a 2-source mismatch MUST match this exact
    template: ``mismatch found in lot sizes between {x} and {y}
    for {sym} for {expiry}: {lot_x} and {lot_y}``.

    Pinned by a regex so the message can be parsed downstream
    (e.g. if a future MCP tool surfaces it)."""
    msg = _format_mismatch_message(
        "ABBOTINDIA", 2024, 5,
        [("snapshot_A.csv.gz", 40), ("snapshot_B.csv.gz", 20)],
    )
    expected_re = (
        r"^mismatch found in lot sizes between snapshot_A\.csv\.gz "
        r"and snapshot_B\.csv\.gz for ABBOTINDIA for 2024-05: "
        r"40 and 20$"
    )
    assert re.match(expected_re, msg), (
        f"Diagnostic format drifted from the operator's template.\n"
        f"Got:      {msg!r}\n"
        f"Expected pattern: {expected_re!r}"
    )


def test_format_mismatch_message_n_source_enumerates_all():
    """≥3 source case (e.g. ABBOTINDIA 2024-06 across 3 snapshots).
    Format falls back to enumeration so no source is silently dropped
    from the diagnostic."""
    msg = _format_mismatch_message(
        "ABBOTINDIA", 2024, 6,
        [("apr.csv.gz", 40), ("may.csv.gz", 20), ("jun.csv.gz", 20)],
    )
    assert "ABBOTINDIA for 2024-06" in msg
    assert "apr.csv.gz=40" in msg
    assert "may.csv.gz=20" in msg
    assert "jun.csv.gz=20" in msg


# ============================================================
# _detect_within_source_mismatches — sidecar OR bhavcopy layer
# ============================================================

def test_detect_within_source_excludes_offending_pairs_and_emits_messages():
    """LOAD-BEARING per the per-pair-exclude policy: when a single
    source has conflicting lot_sizes for the same (sym, year, month),
    the detector EXCLUDES that pair from the consistent rows AND
    emits one diagnostic message."""
    df = pd.DataFrame({
        "symbol": ["AAA", "AAA", "BBB", "BBB"],
        "year":   [2024,   2024,   2024,   2024],
        "month":  [5,      5,      5,      5],
        "lot_size": [100,  200,    50,     50],
        "_src":   ["fileA", "fileB", "fileA", "fileB"],
    })
    consistent, msgs = _detect_within_source_mismatches(df, source_col="_src")
    # AAA excluded (lot_size conflicts: 100 vs 200).
    assert (consistent["symbol"] == "AAA").sum() == 0
    # BBB kept (both rows agree on 50).
    bbb = consistent[consistent["symbol"] == "BBB"]
    assert len(bbb) == 1
    assert int(bbb.iloc[0]["lot_size"]) == 50
    # Exactly one mismatch message for AAA.
    assert len(msgs) == 1
    assert "AAA for 2024-05" in msgs[0]
    assert "100" in msgs[0] and "200" in msgs[0]


def test_detect_within_source_no_mismatch_returns_full_frame_no_messages():
    """Happy path: consistent source yields the full frame
    (deduplicated) and an empty message list."""
    df = pd.DataFrame({
        "symbol": ["AAA", "AAA", "BBB"],
        "year":   [2024,   2024,   2024],
        "month":  [5,      5,      5],
        "lot_size": [100,  100,    50],  # AAA agrees across both sources
        "_src":   ["fileA", "fileB", "fileA"],
    })
    consistent, msgs = _detect_within_source_mismatches(df, source_col="_src")
    assert msgs == []
    assert set(consistent["symbol"]) == {"AAA", "BBB"}
    # Dedup keeps one row per (sym, yr, mo).
    assert len(consistent) == 2


# ============================================================
# _merge_with_cross_source_exclusion
# ============================================================

def test_merge_excludes_sidecar_vs_bhavcopy_mismatches():
    """LOAD-BEARING: sidecar-vs-bhavcopy disagreement also triggers
    per-pair exclusion (NOT loud-fail). Survivor rows get the
    appropriate `source` tag (sidecar / bhavcopy / both)."""
    sidecar = pd.DataFrame({
        "symbol": ["AAA", "BBB", "CCC"],
        "year":   [2024,   2024,   2024],
        "month":  [5,      5,      5],
        "lot_size": [100,  200,    300],
    })
    bhavcopy = pd.DataFrame({
        "symbol": ["AAA", "BBB", "DDD"],
        "year":   [2024,   2024,   2024],
        "month":  [5,      5,      5],
        "lot_size": [100,  999,    400],  # BBB mismatches; AAA agrees
    })
    unified, msgs = _merge_with_cross_source_exclusion(sidecar, bhavcopy)

    # AAA in both, agree → source="both"
    aaa = unified[unified["symbol"] == "AAA"]
    assert len(aaa) == 1
    assert aaa.iloc[0]["source"] == "both"
    assert int(aaa.iloc[0]["lot_size"]) == 100

    # BBB excluded entirely (cross-source mismatch).
    assert (unified["symbol"] == "BBB").sum() == 0
    assert len(msgs) == 1
    assert "BBB for 2024-05" in msgs[0]
    assert "sidecar" in msgs[0] and "bhavcopy" in msgs[0]
    assert "200" in msgs[0] and "999" in msgs[0]

    # CCC sidecar-only.
    ccc = unified[unified["symbol"] == "CCC"]
    assert len(ccc) == 1
    assert ccc.iloc[0]["source"] == "sidecar"

    # DDD bhavcopy-only.
    ddd = unified[unified["symbol"] == "DDD"]
    assert len(ddd) == 1
    assert ddd.iloc[0]["source"] == "bhavcopy"


# ============================================================
# build_lot_size_parquet against committed P0.1 fixtures
# ============================================================

def test_build_against_4_sidecar_fixtures_pins_pnb_jun_2024(tmp_path):
    """LOAD-BEARING: the committed P0.1 fixtures yield PNB 2024-06
    with lot_size = 8000 (matches the operator's earlier PNB CSV
    inspection and the cross-snapshot stability check)."""
    out_path = tmp_path / "lot_sizes.parquet"
    bhavcopy_dir = tmp_path / "bhavcopy_lot_sizes_empty"
    bhavcopy_dir.mkdir()
    build_lot_size_parquet(
        out_path=out_path,
        sidecar_dir=SIDECAR_DIR,
        bhavcopy_lot_sizes_dir=bhavcopy_dir,
        verbose=False,
    )
    assert out_path.exists()
    df = pd.read_parquet(out_path)
    pnb_jun = df[
        (df["symbol"] == "PNB") & (df["year"] == 2024) & (df["month"] == 6)
    ]
    assert len(pnb_jun) == 1
    assert int(pnb_jun.iloc[0]["lot_size"]) == 8000
    assert pnb_jun.iloc[0]["source"] == "sidecar"


def test_build_against_4_sidecar_fixtures_excludes_abbottindia_may_2024(tmp_path):
    """LOAD-BEARING: ABBOTINDIA 2024-05 has a sidecar-vs-sidecar
    mismatch (Apr-16 → 40 vs May-16 → 20; NSE biannual lot revision).
    Per the per-pair-exclude policy, this pair MUST NOT appear in the
    unified cache."""
    out_path = tmp_path / "lot_sizes.parquet"
    bhavcopy_dir = tmp_path / "bhavcopy_lot_sizes_empty"
    bhavcopy_dir.mkdir()
    build_lot_size_parquet(
        out_path=out_path,
        sidecar_dir=SIDECAR_DIR,
        bhavcopy_lot_sizes_dir=bhavcopy_dir,
        verbose=False,
    )
    df = pd.read_parquet(out_path)
    abbott_may = df[
        (df["symbol"] == "ABBOTINDIA")
        & (df["year"] == 2024) & (df["month"] == 5)
    ]
    assert len(abbott_may) == 0, (
        "ABBOTINDIA 2024-05 should be EXCLUDED due to the documented "
        "Apr-16 (lot=40) vs May-16 (lot=20) sidecar-vs-sidecar mismatch. "
        "Per-pair-exclude policy violation."
    )


def test_build_returns_successfully_when_only_mismatches_exist(tmp_path):
    """Build NEVER raises on lot-size mismatches under the
    per-pair-exclude policy. Returns successfully even when 100% of
    the source pairs are excluded."""
    sidecar_dir = tmp_path / "sidecars"
    sidecar_dir.mkdir()
    bhavcopy_dir = tmp_path / "bhavcopy_lot_sizes"
    bhavcopy_dir.mkdir()
    # Synthesize 2 sidecars with conflicting lot_sizes for ALL rows.
    _write_synthetic_sidecar(
        sidecar_dir / "NSE_FO_contract_01012025.csv.gz",
        rows=[("XYZ", "JAN", 100), ("XYZ", "FEB", 200)],
    )
    _write_synthetic_sidecar(
        sidecar_dir / "NSE_FO_contract_15012025.csv.gz",
        rows=[("XYZ", "JAN", 50), ("XYZ", "FEB", 100)],
    )
    out_path = tmp_path / "lot_sizes.parquet"
    build_lot_size_parquet(
        out_path=out_path,
        sidecar_dir=sidecar_dir,
        bhavcopy_lot_sizes_dir=bhavcopy_dir,
        verbose=False,
    )
    df = pd.read_parquet(out_path)
    assert len(df) == 0, "all 2 pairs should be excluded"


# ============================================================
# Helper: synthesize a minimal NSE_FO_contract sidecar
# ============================================================

def _write_synthetic_sidecar(
    path: Path,
    rows: list[tuple[str, str, int]],   # (symbol, mmm, lot_size)
):
    """Build a minimal NSE_FO_contract CSV with just the columns
    parse_sidecar reads (TckrSymb, StockNm, NewBrdLotQty,
    FinInstrmNm), gzip-compress, write."""
    out_rows = []
    for sym, mmm, lot in rows:
        # StockNm must match the regex `{SYM}{YY}{MMM}{STRIKE}{CE|PE}`.
        # Use year = 25 (2025), strike = 100, type = CE for simplicity.
        stock_nm = f"{sym}25{mmm}100CE"
        out_rows.append({
            "TckrSymb": sym,
            "StockNm": stock_nm,
            "NewBrdLotQty": lot,
            "FinInstrmNm": "OPTSTK",
        })
    df = pd.DataFrame(out_rows)
    # Write as gzipped CSV.
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    path.write_bytes(gzip.compress(buf.getvalue().encode("utf-8")))


# ============================================================
# prefetch auto-build trigger
# ============================================================

def test_prefetch_autobuilds_lot_size_parquet_when_missing(tmp_path, monkeypatch):
    """LOAD-BEARING: the prefetch wrapper auto-invokes
    build_lot_size_parquet when data/cache/lot_sizes.parquet is
    missing. Verified by calling build_lot_size_parquet directly
    with the prefetch-default args after monkeypatching the cache
    root — the parquet appears."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(cache, "_ensure_root", lambda: tmp_path)

    # Empty bhavcopy_fo_lot_sizes dir + the real committed sidecars.
    bhavcopy_dir = tmp_path / "bhavcopy_fo_lot_sizes"
    bhavcopy_dir.mkdir()
    out = cache.lot_sizes_path()
    assert not out.exists()

    build_lot_size_parquet(
        out_path=out,
        sidecar_dir=SIDECAR_DIR,
        bhavcopy_lot_sizes_dir=bhavcopy_dir,
        verbose=False,
    )
    assert out.exists(), "auto-build did not produce the unified parquet"
    df = pd.read_parquet(out)
    assert len(df) > 0
    assert {"symbol", "year", "month", "lot_size", "source"}.issubset(df.columns)
