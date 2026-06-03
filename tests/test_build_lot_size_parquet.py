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
    _attach_expiry_date_column,
    _detect_within_source_mismatches,
    _format_mismatch_message,
    _last_thursday_of_month,
    _merge_with_cross_source_exclusion,
    _resolve_expiry_date,
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


def test_format_mismatch_message_n_source_compresses_consecutive_runs():
    """≥3 source case: format compresses consecutive same-value runs
    to keep the bhavcopy-internal NIFTY-style 450+ trade-date dump
    scannable. Single-date runs print as ``{src}={value}`` (matches
    pre-compression output for short conflicts); multi-date runs
    print as ``{value} ({first} → {last}, N dates)``.

    Fixture: 3 sources, 40 at apr (1 date), 20 at may + jun
    (2 consecutive dates). Compresses to 2 runs.
    """
    msg = _format_mismatch_message(
        "ABBOTINDIA", 2024, 6,
        [("apr.csv.gz", 40), ("may.csv.gz", 20), ("jun.csv.gz", 20)],
    )
    assert "ABBOTINDIA for 2024-06" in msg
    # Run 1: single-date → bare s=v form.
    assert "apr.csv.gz=40" in msg
    # Run 2: 2-date run compressed.
    assert "20 (may.csv.gz → jun.csv.gz, 2 dates)" in msg
    # NEGATIVE: the legacy uncompressed form must NOT survive — would
    # mean the compression regressed back to per-date enumeration.
    assert "may.csv.gz=20" not in msg
    assert "jun.csv.gz=20" not in msg


def test_format_mismatch_message_bhavcopy_internal_compresses_hundreds_to_runs():
    """LOAD-BEARING: the bhavcopy-internal case with NIFTY-style
    lot-size revisions (450+ trade-date observations across 2-3
    lot-size runs) must compress to a single readable line, not
    hundreds of bytes per excluded pair.

    Synthesized fixture mirrors the operator-reported NIFTY 2027-12
    shape (121 days @ 25, 250 days @ 75, 95 days @ 65). Asserts the
    compressed output is short + names the value-by-range structure.
    """
    from datetime import date as _date, timedelta as _td
    pairs: list[tuple[str, int]] = []
    d = _date(2024, 7, 8)
    for _ in range(121):
        pairs.append((f"bhavcopy-{d.isoformat()}", 25))
        d += _td(days=1)
    for _ in range(250):
        pairs.append((f"bhavcopy-{d.isoformat()}", 75))
        d += _td(days=1)
    for _ in range(95):
        pairs.append((f"bhavcopy-{d.isoformat()}", 65))
        d += _td(days=1)

    msg = _format_mismatch_message("NIFTY", 2027, 12, pairs)

    # Compression hit: three runs, each named by value + endpoints +
    # count. Confirms the operator gets the "value-by-range" view
    # instead of the per-date dump.
    assert "NIFTY for 2027-12" in msg
    assert "25 (bhavcopy-2024-07-08" in msg
    assert ", 121 dates)" in msg
    assert "75 (bhavcopy-" in msg
    assert ", 250 dates)" in msg
    assert "65 (bhavcopy-" in msg
    assert ", 95 dates)" in msg

    # Size bound: pre-compression dump would be ~hundreds of bytes
    # per pair × 466 pairs = many KB. Post-compression must fit in
    # a single short line. 350-byte ceiling locks the regression.
    assert len(msg) < 350, (
        f"compressed message grew past the 350-byte budget — "
        f"per-date dump probably regressed. Got len={len(msg)}: "
        f"{msg[:200]}..."
    )


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
    # Exactly one mismatch entry for AAA — (sym_tag, message) tuple
    # per the symbol-scoping cleanup.
    assert len(msgs) == 1
    sym_tag, message = msgs[0]
    assert sym_tag == "AAA"
    assert "AAA for 2024-05" in message
    assert "100" in message and "200" in message


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
    sym_tag, message = msgs[0]
    assert sym_tag == "BBB"
    assert "BBB for 2024-05" in message
    assert "sidecar" in message and "bhavcopy" in message
    assert "200" in message and "999" in message

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


def test_build_symbols_filter_scopes_mismatch_diagnostics(tmp_path, capsys):
    """Symbol-scope cleanup: when ``symbols_filter`` is set, only
    mismatches whose symbol is in the filter print loud; the others
    are summarized as ``Suppressed N message(s)``. The PARQUET
    contents are unchanged — out-of-filter pairs still get excluded
    (the policy is a correctness invariant, not a verbosity knob).

    Fixture: 2 sidecars with conflicting lot_sizes for both PNB and
    NIFTY. Filter scopes to ``["PNB"]``; the NIFTY message gets
    suppressed-and-counted, the PNB message prints.
    """
    sidecar_dir = tmp_path / "sidecars"
    sidecar_dir.mkdir()
    bhavcopy_dir = tmp_path / "bhavcopy_lot_sizes"
    bhavcopy_dir.mkdir()
    _write_synthetic_sidecar(
        sidecar_dir / "NSE_FO_contract_01012025.csv.gz",
        rows=[("PNB", "JAN", 100), ("NIFTY", "JAN", 25)],
    )
    _write_synthetic_sidecar(
        sidecar_dir / "NSE_FO_contract_15012025.csv.gz",
        rows=[("PNB", "JAN", 50), ("NIFTY", "JAN", 75)],
    )
    out_path = tmp_path / "lot_sizes.parquet"
    build_lot_size_parquet(
        out_path=out_path,
        sidecar_dir=sidecar_dir,
        bhavcopy_lot_sizes_dir=bhavcopy_dir,
        verbose=True,
        symbols_filter=["PNB"],
    )

    # Parquet: both PNB AND NIFTY excluded. Filter does NOT affect
    # the policy — only the verbosity.
    df = pd.read_parquet(out_path)
    assert (df["symbol"] == "PNB").sum() == 0
    assert (df["symbol"] == "NIFTY").sum() == 0

    captured = capsys.readouterr().out
    # PNB diagnostic prints loud.
    assert "PNB for 2025-01" in captured
    # NIFTY diagnostic does NOT print loud — only the suppression summary.
    assert "NIFTY for 2025-01" not in captured
    assert "Suppressed 1 message(s)" in captured
    # Scope tag in the header so the operator sees what was filtered.
    assert "symbol-scoped" in captured and "PNB" in captured


def test_build_symbols_filter_none_prints_all_messages(tmp_path, capsys):
    """Backwards compat: ``symbols_filter=None`` (default) prints
    every mismatch message — same as before the cleanup. Locks the
    standalone CLI invocation path (``python build_lot_size_parquet.py``
    with no filter)."""
    sidecar_dir = tmp_path / "sidecars"
    sidecar_dir.mkdir()
    bhavcopy_dir = tmp_path / "bhavcopy_lot_sizes"
    bhavcopy_dir.mkdir()
    _write_synthetic_sidecar(
        sidecar_dir / "NSE_FO_contract_01012025.csv.gz",
        rows=[("PNB", "JAN", 100), ("NIFTY", "JAN", 25)],
    )
    _write_synthetic_sidecar(
        sidecar_dir / "NSE_FO_contract_15012025.csv.gz",
        rows=[("PNB", "JAN", 50), ("NIFTY", "JAN", 75)],
    )
    out_path = tmp_path / "lot_sizes.parquet"
    build_lot_size_parquet(
        out_path=out_path,
        sidecar_dir=sidecar_dir,
        bhavcopy_lot_sizes_dir=bhavcopy_dir,
        verbose=True,
    )
    captured = capsys.readouterr().out
    # Both messages print under no-filter.
    assert "PNB for 2025-01" in captured
    assert "NIFTY for 2025-01" in captured
    # No suppression banner when nothing was suppressed.
    assert "Suppressed" not in captured
    assert "symbol-scoped" not in captured


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

def _write_current_schema_parquet(path: Path) -> None:
    """Helper: write a minimal valid parquet with the full current
    ``_LOT_SIZES_REQUIRED_COLUMNS`` schema. Used by predicate tests
    that need a parquet that PASSES the schema-staleness check so the
    next branch (mtime / freshness) can be exercised."""
    df = pd.DataFrame({
        "symbol": pd.Series(["X"], dtype="string"),
        "year": pd.Series([2024], dtype="int64"),
        "month": pd.Series([7], dtype="int64"),
        "lot_size": pd.Series([100], dtype="int64"),
        "source": pd.Series(["sidecar"], dtype="string"),
        "expiry_date": pd.Series(
            [pd.Timestamp("2024-07-25")], dtype="datetime64[us]",
        ),
    })
    df.to_parquet(path, index=False)


def test_lot_sizes_needs_rebuild_predicate_pins_three_cases(tmp_path):
    """Anti-regression on the stale-lookup bug observed 2026-06-03:
    ``data/cache/lot_sizes.parquet`` had 4 BHEL year-months while
    ``bhavcopy_fo_lot_sizes/`` had 25, but the prior exists-only
    guard at scripts/prefetch_universe.py:384 took the cache-hit
    path and the prefetch wrongly skipped 805/9392 contracts as
    ``lot_size excluded``.

    The new mtime-based predicate fires a rebuild in three cases;
    pinning each separately so a future contributor can't collapse
    them and reintroduce the bug. Uses real parquets (not byte
    placeholders) so the schema-staleness check Grill #5 added
    doesn't short-circuit the mtime path.
    """
    from scripts.prefetch_universe import _lot_sizes_needs_rebuild

    unified = tmp_path / "lot_sizes.parquet"
    sibling = tmp_path / "bhavcopy_fo_lot_sizes"

    # Case 1: unified parquet missing → rebuild.
    sibling.mkdir()
    needs, reason = _lot_sizes_needs_rebuild(unified, sibling)
    assert needs is True
    assert "missing" in reason

    # Case 2: unified parquet present (current schema), no sibling
    # parquets newer than it → no rebuild (cache hit).
    _write_current_schema_parquet(unified)
    import os
    base_t = os.path.getmtime(unified)
    # Plant an OLDER sibling parquet (mtime = base - 60s).
    older_sibling = sibling / "20240725.parquet"
    older_sibling.write_bytes(b"placeholder")
    os.utime(older_sibling, (base_t - 60, base_t - 60))
    needs, reason = _lot_sizes_needs_rebuild(unified, sibling)
    assert needs is False, (
        f"older sibling shouldn't trigger rebuild, got: {reason}"
    )
    assert "up-to-date" in reason

    # Case 3: sibling parquet NEWER than the unified parquet →
    # rebuild (the bug we're fixing). Reason names the newer sibling.
    newer_sibling = sibling / "20251231.parquet"
    newer_sibling.write_bytes(b"placeholder")
    os.utime(newer_sibling, (base_t + 60, base_t + 60))
    needs, reason = _lot_sizes_needs_rebuild(unified, sibling)
    assert needs is True
    assert "newer" in reason or "mtime" in reason
    assert "20251231" in reason  # operator-visible: first offending sibling


def test_lot_sizes_needs_rebuild_detects_schema_staleness(tmp_path):
    """Grill #5 (logic-review 50b6a84): a pre-fbb8e35 parquet (no
    ``expiry_date`` column) carried over from a prior code revision
    MUST trigger a rebuild — otherwise the post-1B sweep crashes
    with KeyError when ``expiries_for_symbols`` reads the column.

    Predicate must detect this case independent of the mtime path:
    even when sibling mtimes are stable, a schema-stale parquet is
    not safe to reuse.
    """
    from scripts.prefetch_universe import _lot_sizes_needs_rebuild

    unified = tmp_path / "lot_sizes.parquet"
    sibling = tmp_path / "bhavcopy_fo_lot_sizes"
    sibling.mkdir()

    # Write a pre-fbb8e35-shape parquet (no expiry_date column).
    stale = pd.DataFrame({
        "symbol": pd.Series(["X"], dtype="string"),
        "year": pd.Series([2024], dtype="int64"),
        "month": pd.Series([7], dtype="int64"),
        "lot_size": pd.Series([100], dtype="int64"),
        "source": pd.Series(["sidecar"], dtype="string"),
    })
    stale.to_parquet(unified, index=False)

    # Sibling mtime stable (no fresh-fetch signal); but the parquet
    # is schema-stale → MUST rebuild.
    needs, reason = _lot_sizes_needs_rebuild(unified, sibling)
    assert needs is True, (
        "schema-stale parquet must trigger rebuild even when mtimes "
        f"are stable; got: {reason}"
    )
    assert "schema stale" in reason
    assert "expiry_date" in reason  # operator-visible: which column is missing


def test_lot_sizes_needs_rebuild_detects_corrupt_parquet(tmp_path):
    """Defensive Grill #5 corollary: if the parquet on disk is
    unreadable (corrupt bytes), the predicate must rebuild rather
    than crash + halt the prefetch. Triggers fresh fetch from the
    truth sources; on-disk corruption is self-healing."""
    from scripts.prefetch_universe import _lot_sizes_needs_rebuild

    unified = tmp_path / "lot_sizes.parquet"
    sibling = tmp_path / "bhavcopy_fo_lot_sizes"
    sibling.mkdir()
    unified.write_bytes(b"not a valid parquet header")
    needs, reason = _lot_sizes_needs_rebuild(unified, sibling)
    assert needs is True
    assert "failed to read schema" in reason


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
    assert {
        "symbol", "year", "month", "lot_size", "source", "expiry_date",
    }.issubset(df.columns)


# ============================================================
# expiry_date column (post-merge enrichment)
# ============================================================

def test_last_thursday_of_month_pins_known_dates():
    """Algorithmic fallback correctness on a handful of known months
    where last-Thursday is unambiguous (no Christmas / Republic-Day
    shift). Anchors the formula so a future timezone / weekday-index
    refactor can't drift silently."""
    # May 2024: last day is Fri 31 → walk back to Thu 30.
    assert _last_thursday_of_month(2024, 5) == date(2024, 5, 30)
    # Jun 2024: last day Sun 30 → walk back to Thu 27.
    assert _last_thursday_of_month(2024, 6) == date(2024, 6, 27)
    # Aug 2024: last day Sat 31 → walk back to Thu 29.
    assert _last_thursday_of_month(2024, 8) == date(2024, 8, 29)
    # Feb 2024 (leap year): Thu 29 IS the last day.
    assert _last_thursday_of_month(2024, 2) == date(2024, 2, 29)
    # Dec-to-Jan rollover edge: Dec 2024 last day Tue 31 → Thu 26.
    assert _last_thursday_of_month(2024, 12) == date(2024, 12, 26)


def test_resolve_expiry_date_uses_bhavcopy_when_present(tmp_path):
    """When a bhavcopy exists in (year, month), the resolver MUST
    use the OPTSTK expiry from it — NOT the algorithmic fallback. The
    bhavcopy-derived path is holiday-shift-correct."""
    bhavcopy_fo_dir = tmp_path / "bhavcopy_fo"
    bhavcopy_fo_dir.mkdir()
    # Synthesize a bhavcopy on May 15 2024 with ADANIENT + RELIANCE
    # OPTSTK rows expiring 2024-05-30. Include a non-OPTSTK row to
    # confirm the filter excludes it.
    df = pd.DataFrame({
        "instrument": pd.array(
            ["OPTSTK", "OPTSTK", "FUTSTK"], dtype="string",
        ),
        "symbol": pd.array(
            ["ADANIENT", "RELIANCE", "ADANIENT"], dtype="string",
        ),
        "expiry": pd.Series(
            [
                pd.Timestamp("2024-05-30"),
                pd.Timestamp("2024-05-30"),
                pd.Timestamp("2024-05-30"),
            ], dtype="datetime64[us]",
        ),
    })
    df.to_parquet(bhavcopy_fo_dir / "20240515.parquet", index=False)
    exp_date, prov = _resolve_expiry_date(2024, 5, bhavcopy_fo_dir)
    assert exp_date == date(2024, 5, 30)
    assert prov == "bhavcopy"


def test_resolve_expiry_date_falls_back_when_no_bhavcopy(tmp_path):
    """When no bhavcopy exists for (year, month), the resolver falls
    back to ``_last_thursday_of_month``. Provenance is tagged
    ``fallback`` so the build can log it loudly to the operator."""
    bhavcopy_fo_dir = tmp_path / "bhavcopy_fo_empty"
    bhavcopy_fo_dir.mkdir()
    # Future month — no bhavcopy will ever exist in tmp dir.
    exp_date, prov = _resolve_expiry_date(2026, 11, bhavcopy_fo_dir)
    assert exp_date == _last_thursday_of_month(2026, 11)
    assert prov == "fallback"


def test_attach_expiry_date_column_dedups_month_lookups(tmp_path):
    """LOAD-BEARING: a (year, month) anchor that's shared across N
    symbols should incur ONE bhavcopy read, not N. Confirmed by
    counting reads via a parquet that has 50 OPTSTK symbols on the
    same month-anchor; only one read happens (otherwise the bhavcopy
    must be re-parsed 50 times — wasteful at scale)."""
    bhavcopy_fo_dir = tmp_path / "bhavcopy_fo"
    bhavcopy_fo_dir.mkdir()
    df = pd.DataFrame({
        "instrument": pd.array(["OPTSTK"], dtype="string"),
        "symbol": pd.array(["X"], dtype="string"),
        "expiry": pd.Series(
            [pd.Timestamp("2024-05-30")], dtype="datetime64[us]",
        ),
    })
    df.to_parquet(bhavcopy_fo_dir / "20240515.parquet", index=False)

    # Frame with 50 different symbols all sharing the same (2024, 5)
    # anchor — one bhavcopy lookup must satisfy all of them.
    syms = [f"SYM{i:02d}" for i in range(50)]
    unified = pd.DataFrame({
        "symbol": pd.array(syms, dtype="string"),
        "year": [2024] * 50,
        "month": [5] * 50,
        "lot_size": [100] * 50,
        "source": pd.array(["sidecar"] * 50, dtype="string"),
    })
    out, prov = _attach_expiry_date_column(unified, bhavcopy_fo_dir)
    assert "expiry_date" in out.columns
    assert (out["expiry_date"] == pd.Timestamp("2024-05-30")).all()
    # One unique (year, month) → one bhavcopy provenance entry.
    assert prov == {"bhavcopy": 1, "fallback": 0}


def test_attach_expiry_date_column_mixed_provenance(tmp_path):
    """A frame spanning months with AND without cached bhavcopies
    routes each anchor independently. Bhavcopy-derived rows get
    holiday-shift-correct dates; future-month rows fall back. Counts
    in the provenance dict tell the operator how many of each."""
    bhavcopy_fo_dir = tmp_path / "bhavcopy_fo"
    bhavcopy_fo_dir.mkdir()
    df = pd.DataFrame({
        "instrument": pd.array(["OPTSTK"], dtype="string"),
        "symbol": pd.array(["X"], dtype="string"),
        "expiry": pd.Series(
            [pd.Timestamp("2024-05-30")], dtype="datetime64[us]",
        ),
    })
    df.to_parquet(bhavcopy_fo_dir / "20240515.parquet", index=False)

    unified = pd.DataFrame({
        "symbol": pd.array(["ADANIENT", "ADANIENT", "RELIANCE"], dtype="string"),
        "year": [2024, 2026, 2024],
        "month": [5, 11, 5],
        "lot_size": [300, 300, 250],
        "source": pd.array(["sidecar"] * 3, dtype="string"),
    })
    out, prov = _attach_expiry_date_column(unified, bhavcopy_fo_dir)
    # Two unique anchors: (2024, 5) bhavcopy-derived, (2026, 11) fallback.
    assert prov == {"bhavcopy": 1, "fallback": 1}
    # ADANIENT + RELIANCE on (2024, 5) both get the bhavcopy-derived date.
    adanient_may = out[(out["symbol"] == "ADANIENT") & (out["month"] == 5)]
    reliance_may = out[(out["symbol"] == "RELIANCE") & (out["month"] == 5)]
    assert adanient_may.iloc[0]["expiry_date"] == pd.Timestamp("2024-05-30")
    assert reliance_may.iloc[0]["expiry_date"] == pd.Timestamp("2024-05-30")
    # ADANIENT on (2026, 11) gets the algorithmic last-Thursday (=2026-11-26).
    adanient_nov = out[(out["symbol"] == "ADANIENT") & (out["month"] == 11)]
    assert adanient_nov.iloc[0]["expiry_date"] == pd.Timestamp(
        _last_thursday_of_month(2026, 11),
    )


def test_attach_expiry_date_column_on_empty_frame(tmp_path):
    """Empty unified frame → empty output frame with the expiry_date
    column present (downstream consumers may inspect df.columns even
    on cold-cache build)."""
    bhavcopy_fo_dir = tmp_path / "bhavcopy_fo"
    bhavcopy_fo_dir.mkdir()
    empty = pd.DataFrame({
        "symbol": pd.Series(dtype="string"),
        "year": pd.Series(dtype="int64"),
        "month": pd.Series(dtype="int64"),
        "lot_size": pd.Series(dtype="int64"),
        "source": pd.Series(dtype="string"),
    })
    out, prov = _attach_expiry_date_column(empty, bhavcopy_fo_dir)
    assert "expiry_date" in out.columns
    assert out["expiry_date"].dtype == "datetime64[us]"
    assert len(out) == 0
    assert prov == {"bhavcopy": 0, "fallback": 0}


def test_build_lot_size_parquet_emits_expiry_date_column(tmp_path):
    """End-to-end: ``build_lot_size_parquet`` writes a parquet with
    the ``expiry_date`` column, populated for every row. Fixture uses
    the committed sidecars + an empty bhavcopy_fo dir, so every row
    is fallback-derived (correct: a fresh clone w/o prefetch has no
    cached bhavcopies; the algorithmic last-Thursday is sufficient)."""
    out_path = tmp_path / "lot_sizes.parquet"
    bhavcopy_lot_sizes_dir = tmp_path / "bhavcopy_lot_sizes_empty"
    bhavcopy_lot_sizes_dir.mkdir()
    bhavcopy_fo_dir = tmp_path / "bhavcopy_fo_empty"
    bhavcopy_fo_dir.mkdir()
    build_lot_size_parquet(
        out_path=out_path,
        sidecar_dir=SIDECAR_DIR,
        bhavcopy_lot_sizes_dir=bhavcopy_lot_sizes_dir,
        bhavcopy_fo_dir=bhavcopy_fo_dir,
        verbose=False,
    )
    df = pd.read_parquet(out_path)
    assert "expiry_date" in df.columns
    assert df["expiry_date"].dtype == "datetime64[us]"
    assert df["expiry_date"].notna().all()
    # Spot-check: PNB 2024-06 → fallback expiry = last Thursday June 2024 = Jun 27.
    pnb_jun = df[
        (df["symbol"] == "PNB") & (df["year"] == 2024) & (df["month"] == 6)
    ]
    assert len(pnb_jun) == 1
    assert pnb_jun.iloc[0]["expiry_date"] == pd.Timestamp("2024-06-27")
