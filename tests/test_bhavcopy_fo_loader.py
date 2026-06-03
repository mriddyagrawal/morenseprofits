"""Tests for src.data.bhavcopy_fo_loader. No network — fixture-driven.

Two load-bearing tests singled out by the f5ff10c review:

  test_load_bhavcopy_fo_cache_hit — a regression that dropped the cache
  short-circuit would silently re-fetch every call and melt the laptop
  during a Phase-4 sweep. We monkeypatch the fetcher to RAISE on the
  second call to prove the cache absorbs it.

  test_holiday_shifted_expiry_warns — the XpryDt != FininstrmActlXpryDt
  warning path is reachable but our recorded fixture has 0 divergences.
  We synthesize one row of divergence and assert exactly one warning AND
  that the canonical `expiry` is FininstrmActlXpryDt per SPECS §2.4.
"""
from __future__ import annotations

import warnings
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import requests as _requests
import zipfile as _zipfile

from src.data import bhavcopy_fo_loader as bfo
from src.data import cache
from src.data.errors import BhavcopyFormatError, MissingDataError

FIXTURES = Path(__file__).parent / "fixtures"
LEGACY_DATE = date(2024, 1, 25)
UDIFF_DATE = date(2024, 8, 29)


def _legacy_raw() -> str:
    return (FIXTURES / "bhavcopy_fo_legacy_20240125.csv").read_text()


def _udiff_raw() -> str:
    return (FIXTURES / "bhavcopy_fo_udiff_20240829.csv").read_text()


def _redirect_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)


# ===========================================================
# Schema (SPECS §2.4) — verified on both formats
# ===========================================================

# Legacy parser output (15 cols, P1.2 adds turnover). Legacy does
# NOT carry ltp — no equivalent of UDiff's LastPric in raw — so
# the legacy schema stays narrower than UDiff (15 vs 16 cols).
LEGACY_COLS = [
    "instrument", "symbol", "expiry", "strike", "option_type",
    "open", "high", "low", "close", "settle_price",
    "contracts", "turnover", "oi", "oi_change", "trade_date",
]

# UDiff parser output (16 cols, P1.1 — MIGRATION.md §Phase 1).
# Adds ltp (after close) + turnover (after contracts). Does NOT add
# lot_size: per the unified-lookup architecture, lot_size lives in
# data/cache/lot_sizes.parquet via the sibling-cache write hook.
UDIFF_COLS = [
    "instrument", "symbol", "expiry", "strike", "option_type",
    "open", "high", "low", "close", "ltp", "settle_price",
    "contracts", "turnover", "oi", "oi_change", "trade_date",
]

# Backward-compat alias used by tests that don't care which parser
# produced the frame. Points at the LEGACY schema (the smaller
# subset; UDiff is a superset).
SPECS_COLS = LEGACY_COLS


def _assert_legacy_schema(df: pd.DataFrame) -> None:
    assert list(df.columns) == LEGACY_COLS, (
        f"legacy column-order drift: {list(df.columns)}"
    )
    _assert_common_dtypes(df)
    # P1.2 addition: turnover (from VAL_INLAKH; lakhs of rupees,
    # underlying-notional convention per 8c2c517).
    assert df["turnover"].dtype.name == "float64", (
        f"legacy turnover dtype = {df['turnover'].dtype.name}"
    )


def _assert_udiff_schema(df: pd.DataFrame) -> None:
    assert list(df.columns) == UDIFF_COLS, (
        f"UDiff column-order drift: {list(df.columns)}"
    )
    _assert_common_dtypes(df)
    # P1.1 additions: ltp + turnover are float64 (NaN-tolerant for
    # untrade days; ltp is rupees per share; turnover is lakhs of
    # rupees underlying-notional).
    assert df["ltp"].dtype.name == "float64", (
        f"ltp dtype = {df['ltp'].dtype.name}"
    )
    assert df["turnover"].dtype.name == "float64", (
        f"turnover dtype = {df['turnover'].dtype.name}"
    )


def _assert_common_dtypes(df: pd.DataFrame) -> None:
    """Dtype checks shared by legacy + UDiff outputs."""
    assert df["instrument"].dtype == pd.StringDtype()
    assert df["symbol"].dtype == pd.StringDtype()
    assert df["option_type"].dtype == pd.StringDtype()
    assert pd.api.types.is_datetime64_any_dtype(df["expiry"])
    assert pd.api.types.is_datetime64_any_dtype(df["trade_date"])
    for c in ("strike", "open", "high", "low", "close", "settle_price"):
        assert df[c].dtype.name == "float64", f"{c} dtype = {df[c].dtype.name}"
    # SPECS §2.4: contracts is plain int64 (absent → 0); oi / oi_change
    # are nullable Int64 (legitimately unknown is meaningful).
    assert df["contracts"].dtype.name == "int64", (
        f"contracts dtype = {df['contracts'].dtype.name}"
    )
    for c in ("oi", "oi_change"):
        assert df[c].dtype.name == "Int64", f"{c} dtype = {df[c].dtype.name}"


def _assert_specs_2_4_schema(df: pd.DataFrame) -> None:
    """Backward-compat alias for the legacy schema assertion. Existing
    callers that don't care about P1.1's UDiff extension still pass."""
    _assert_legacy_schema(df)


def test_legacy_parser_returns_specs_2_4_schema():
    df = bfo.parse_legacy(_legacy_raw(), LEGACY_DATE)
    _assert_legacy_schema(df)


def test_udiff_parser_returns_specs_2_4_schema():
    """LOAD-BEARING (P1.1): UDiff parser output now carries
    ``ltp`` (from LastPric) and ``turnover`` (from TtlTrfVal) per
    MIGRATION.md §Phase 1 P1.1. Schema-order drift fails loud."""
    df = bfo.parse_udiff(_udiff_raw(), UDIFF_DATE)
    _assert_udiff_schema(df)


def test_parse_udiff_carries_ltp_and_turnover():
    """At least one OPTSTK row must surface non-NaN ltp + turnover —
    sanity that the columns aren't silently all-NaN due to typo or
    drift in the source field names (LastPric / TtlTrfVal)."""
    df = bfo.parse_udiff(_udiff_raw(), UDIFF_DATE)
    optstk = df[df["instrument"] == "OPTSTK"]
    assert (optstk["ltp"].notna()).any(), (
        "ltp is all-NaN for OPTSTK rows — LastPric extraction broken"
    )
    assert (optstk["turnover"].notna()).any(), (
        "turnover is all-NaN for OPTSTK rows — TtlTrfVal extraction broken"
    )


def test_parse_udiff_ltp_is_nan_tolerant():
    """Dtype permissiveness: ``ltp`` must be float64, which means
    NaN passes through as NaN if NSE ever emits a missing LastPric
    cell. NSE's actual convention writes ``0.00`` for untrade days
    rather than NaN — the fixture reflects this — so the test
    asserts the dtype and the no-coercion behavior on an inserted
    NaN, NOT the fixture's NaN count."""
    df = bfo.parse_udiff(_udiff_raw(), UDIFF_DATE)
    # ltp must be float64 (covered by schema test; restated here as
    # the load-bearing claim for this test's name).
    assert df["ltp"].dtype.name == "float64"
    # Synthetic NaN row: mutate a raw CSV row to have an empty
    # LastPric cell; assert it survives as NaN, not 0.0.
    raw = _udiff_raw()
    lines = raw.splitlines()
    header = lines[0].split(",")
    last_pric_col = header.index("LastPric")
    data_lines = lines[1:]
    # Find an OPTSTK row to mutate.
    target_idx = None
    for i, line in enumerate(data_lines):
        cells = line.split(",")
        if cells[header.index("FinInstrmTp")] == "STO":
            target_idx = i
            break
    assert target_idx is not None
    cells = data_lines[target_idx].split(",")
    cells[last_pric_col] = ""  # blank the LastPric cell
    data_lines[target_idx] = ",".join(cells)
    mutated = "\n".join([lines[0]] + data_lines)
    mutated_df = bfo.parse_udiff(mutated, UDIFF_DATE)
    assert mutated_df["ltp"].isna().any(), (
        "blank LastPric cell should produce a NaN, not 0.0; pandas' "
        "default CSV NaN-coercion was not preserved across the parser"
    )


def test_parse_legacy_carries_turnover():
    """LOAD-BEARING (P1.2): legacy parser output now carries
    ``turnover`` (from VAL_INLAKH) per MIGRATION.md §Phase 1 P1.2.
    At least one row in the fixture surfaces a positive turnover
    value (sanity that VAL_INLAKH isn't silently NaN'd)."""
    df = bfo.parse_legacy(_legacy_raw(), LEGACY_DATE)
    assert "turnover" in df.columns
    assert df["turnover"].dtype.name == "float64"
    assert (df["turnover"] > 0).any(), (
        "every turnover value is 0/NaN — VAL_INLAKH extraction broken"
    )


def test_parse_legacy_does_not_carry_ltp():
    """Negative-space test: legacy bhavcopy has NO equivalent of
    UDiff's LastPric in its raw CSV (15 cols vs UDiff's 34). The
    regime A/B caveat surfaced in MCP get_options_chain (P2.4) names
    this gap explicitly. Anti-regression against a future maintainer
    adding a stub ``ltp`` column with all-NaN values — those would
    masquerade as bonafide LTP data downstream."""
    df = bfo.parse_legacy(_legacy_raw(), LEGACY_DATE)
    assert "ltp" not in df.columns, (
        "Legacy parser output MUST NOT carry an ltp column. The legacy "
        "bhavcopy doesn't have LastPric or any equivalent in its raw "
        "CSV. MCP's get_options_chain surfaces a caveat for trade_dates "
        "< 2024-07-08 (see P2.4). See MIGRATION.md §Coverage matrix."
    )


def test_legacy_marker_requires_val_inlakh():
    """LOAD-BEARING anti-regression: VAL_INLAKH is now in
    ``_LEGACY_MARKERS`` (P1.2). If NSE ever drops the column from a
    historical re-publish, the parser fails LOUD on the schema check
    rather than silently producing a turnover=NaN frame that would
    then crash MissingTurnoverError downstream."""
    assert "VAL_INLAKH" in bfo._LEGACY_MARKERS


def test_udiff_markers_require_lastpric_and_ttltrfval():
    """Same load-bearing schema check at the UDiff layer (P1.1).
    Anti-regression in case NSE renames either field in a future
    UDiff revision."""
    assert "LastPric" in bfo._UDIFF_MARKERS
    assert "TtlTrfVal" in bfo._UDIFF_MARKERS


def test_parse_udiff_does_not_carry_lot_size():
    """LOAD-BEARING anti-regression (per reviewer grill #3 on
    9b6c32b + the bhavcopy_fo_loader.py module docstring): the
    main-cache parquet's schema is INTENTIONALLY narrow. ``lot_size``
    lives in the unified ``data/cache/lot_sizes.parquet`` via the
    sibling-cache write hook, NOT per-row in this parser's output.

    Anti-regression against a future maintainer "fixing" the missing
    column by re-adding ``NewBrdLotQty`` → ``lot_size`` here."""
    df = bfo.parse_udiff(_udiff_raw(), UDIFF_DATE)
    assert "lot_size" not in df.columns, (
        "P1.1 architectural decision violated: lot_size MUST NOT be in "
        "the bhavcopy main-cache parquet schema. See "
        "bhavcopy_fo_loader.py module docstring + MIGRATION.md "
        "§Cross-source lot-size policy. Consumers needing lot_size "
        "query the unified data/cache/lot_sizes.parquet instead."
    )


# ===========================================================
# Hand-checks against the recorded fixtures
# ===========================================================

def test_legacy_reliance_1900ce_hand_check():
    """RELIANCE OPTSTK 25-Jan-2024 1900CE was the one row in the legacy
    fixture with non-zero traded volume (the rest were illiquid wings).
    Hand-pinned values from the raw CSV: close=804, contracts=1,
    settle=2706.25, OI=250, dOI=250."""
    df = bfo.parse_legacy(_legacy_raw(), LEGACY_DATE)
    row = df[(df["symbol"] == "RELIANCE") & (df["strike"] == 1900) & (df["option_type"] == "CE")]
    assert len(row) == 1
    r = row.iloc[0]
    assert r["close"] == 804.0
    assert r["contracts"] == 1
    assert r["oi"] == 250
    assert r["oi_change"] == 250
    assert r["settle_price"] == 2706.25
    assert r["expiry"] == pd.Timestamp("2024-01-25")
    assert r["trade_date"] == pd.Timestamp("2024-01-25")
    assert r["instrument"] == "OPTSTK"


def test_udiff_reliance_2840ce_hand_check():
    """RELIANCE STO 2024-08-29 (trade) 2840CE expiring 2024-08-29. Pinned
    values from the raw CSV — including contracts=26 which guards the
    bug I caught in f5ff10c verification (was 0 with the wrong
    TtlTradgVol/lot division)."""
    df = bfo.parse_udiff(_udiff_raw(), UDIFF_DATE)
    row = df[
        (df["symbol"] == "RELIANCE")
        & (df["strike"] == 2840)
        & (df["option_type"] == "CE")
        & (df["expiry"] == pd.Timestamp("2024-08-29"))
    ]
    assert len(row) == 1
    r = row.iloc[0]
    assert r["close"] == 201.70
    assert r["oi"] == 41500
    assert r["oi_change"] == -1500
    assert r["contracts"] == 26
    assert r["trade_date"] == pd.Timestamp("2024-08-29")
    assert r["instrument"] == "OPTSTK"  # UDiff STO normalized to legacy OPTSTK


# ===========================================================
# Futures rows: strike NaN, option_type <NA>
# ===========================================================

def test_futures_rows_have_no_strike_or_option_type_legacy():
    df = bfo.parse_legacy(_legacy_raw(), LEGACY_DATE)
    fut = df[df["instrument"].isin(["FUTSTK", "FUTIDX"])]
    assert len(fut) > 0, "fixture should contain futures rows for this test to be meaningful"
    assert fut["strike"].isna().all()
    assert fut["option_type"].isna().all()


def test_futures_rows_have_no_strike_or_option_type_udiff():
    df = bfo.parse_udiff(_udiff_raw(), UDIFF_DATE)
    fut = df[df["instrument"].isin(["FUTSTK", "FUTIDX"])]
    assert len(fut) > 0
    assert fut["strike"].isna().all()
    assert fut["option_type"].isna().all()


# ===========================================================
# UDiff instrument code normalization to legacy names
# ===========================================================

def test_udiff_instrument_codes_normalized_to_legacy():
    df = bfo.parse_udiff(_udiff_raw(), UDIFF_DATE)
    seen = set(df["instrument"].dropna().tolist())
    assert seen.issubset({"OPTSTK", "OPTIDX", "FUTSTK", "FUTIDX"}), (
        f"unexpected instrument codes (should be legacy-form): {seen}"
    )


def test_udiff_unknown_instrument_code_raises():
    """A future NSE addition like 'CUR' (currency) would slip through map()
    as NaN; we want a loud BhavcopyFormatError, not a silent drop."""
    mutated = _udiff_raw().replace(",STO,", ",XYZ,", 1)
    with pytest.raises(BhavcopyFormatError, match="unknown codes"):
        bfo.parse_udiff(mutated, UDIFF_DATE)


# ===========================================================
# Off-by-one trade_date catches mis-dispatched fetches
# ===========================================================

def test_legacy_off_by_one_trade_date_raises():
    with pytest.raises(BhavcopyFormatError, match="TIMESTAMP"):
        bfo.parse_legacy(_legacy_raw(), date(2024, 1, 26))


def test_udiff_off_by_one_trade_date_raises():
    with pytest.raises(BhavcopyFormatError, match="TradDt"):
        bfo.parse_udiff(_udiff_raw(), date(2024, 8, 30))


# ===========================================================
# Corrupt header → BhavcopyFormatError (not silent parse)
# ===========================================================

def test_corrupt_header_raises_legacy():
    with pytest.raises(BhavcopyFormatError, match="missing required cols"):
        bfo.parse_legacy("FOO,BAR,BAZ\n1,2,3\n", LEGACY_DATE)


def test_corrupt_header_raises_udiff():
    with pytest.raises(BhavcopyFormatError, match="missing required cols"):
        bfo.parse_udiff("FOO,BAR,BAZ\n1,2,3\n", UDIFF_DATE)


# ===========================================================
# LOAD-BEARING: holiday-shifted expiry must warn and use ActlXpry
# ===========================================================

def test_holiday_shifted_expiry_warns_and_uses_actl():
    """Mutate one row of the udiff fixture so XpryDt != FininstrmActlXpryDt
    (simulating a holiday-shifted Thursday). Parser must (a) emit exactly
    one divergence warning at file level, (b) use FininstrmActlXpryDt as
    the canonical `expiry` per SPECS §2.4."""
    raw = _udiff_raw()
    lines = raw.splitlines()
    header_cols = lines[0].split(",")
    xpry_idx = header_cols.index("XpryDt")
    actl_idx = header_cols.index("FininstrmActlXpryDt")
    assert xpry_idx == 9 and actl_idx == 10  # sanity

    # Find an STO row where the two agree, divert the scheduled XpryDt to
    # a far-future date. The Actl stays — that's what `expiry` should hold.
    target_idx = None
    original_actl = None
    for i in range(1, len(lines)):
        fields = lines[i].split(",")
        if fields[4] == "STO" and fields[xpry_idx] == fields[actl_idx]:
            target_idx = i
            original_actl = fields[actl_idx]
            fields[xpry_idx] = "2099-12-31"  # divergent
            lines[i] = ",".join(fields)
            break
    assert target_idx is not None, "no convergent STO row to mutate — fixture changed?"

    mutated = "\n".join(lines) + "\n"

    with warnings.catch_warnings(record=True) as wlog:
        warnings.simplefilter("always")
        df = bfo.parse_udiff(mutated, UDIFF_DATE)

    divergence_warnings = [
        w for w in wlog if "FininstrmActlXpryDt" in str(w.message)
    ]
    assert len(divergence_warnings) == 1, (
        f"expected exactly one file-level divergence warning, got {len(divergence_warnings)}"
    )
    # Verify the count "1 rows" appears — file-level aggregation, not per-row
    assert "1 rows" in str(divergence_warnings[0].message)

    # The canonical expiry must NOT be 2099-12-31 (would mean the parser
    # picked XpryDt instead of FininstrmActlXpryDt — regression).
    assert pd.Timestamp("2099-12-31") not in df["expiry"].tolist()
    # The actual settlement date must be in the output expiry column.
    assert pd.Timestamp(original_actl) in df["expiry"].tolist()


# ===========================================================
# LOAD-BEARING: cache hit must not re-fetch
# ===========================================================

def test_load_bhavcopy_fo_cache_hit_skips_fetch(monkeypatch, tmp_path):
    """Without this, a regression that drops the `cache.exists` short-
    circuit silently re-fetches every call. Phase-4 sweeps with 60+
    bhavcopies × 5 stocks × N strategies would melt the laptop."""
    _redirect_cache(monkeypatch, tmp_path)
    raw = _legacy_raw()
    calls = {"n": 0}

    def fake_fetch(td):
        calls["n"] += 1
        return raw, "legacy"

    monkeypatch.setattr(bfo, "_fetch_raw", fake_fetch)

    df1 = bfo.load_bhavcopy_fo(LEGACY_DATE)
    assert calls["n"] == 1
    _assert_specs_2_4_schema(df1)

    # Make the fetcher RAISE on any further call. If the loader silently
    # re-fetches, this test explodes — exactly the noise we want.
    def raiser(td):
        raise RuntimeError(
            f"fetcher called for {td} on cache hit — short-circuit regressed"
        )

    monkeypatch.setattr(bfo, "_fetch_raw", raiser)
    df2 = bfo.load_bhavcopy_fo(LEGACY_DATE)
    assert calls["n"] == 1
    # Round-trip equality: post-parquet frame matches in-memory frame.
    pd.testing.assert_frame_equal(df1, df2)


def test_load_bhavcopy_fo_udiff_cache_hit_skips_fetch(monkeypatch, tmp_path):
    """Same guarantee for the udiff path — different code branch, same
    contract."""
    _redirect_cache(monkeypatch, tmp_path)
    raw = _udiff_raw()
    calls = {"n": 0}

    def fake_fetch(td):
        calls["n"] += 1
        return raw, "udiff"

    monkeypatch.setattr(bfo, "_fetch_raw", fake_fetch)
    df1 = bfo.load_bhavcopy_fo(UDIFF_DATE)
    assert calls["n"] == 1

    monkeypatch.setattr(bfo, "_fetch_raw", lambda td: (_ for _ in ()).throw(
        RuntimeError("must not fetch on cache hit")
    ))
    df2 = bfo.load_bhavcopy_fo(UDIFF_DATE)
    assert calls["n"] == 1
    pd.testing.assert_frame_equal(df1, df2)


def test_stale_pre_p11_cache_triggers_silent_refetch(monkeypatch, tmp_path, recwarn):
    """A pre-P1.1 14-col cached parquet (no ``turnover`` / no ``ltp``)
    must be detected as stale and silently re-fetched to the post-
    P1.1 16-col schema. Downstream consumers (bhavcopy_to_contract,
    pnl._pick_fill_price) require turnover — silently returning a
    stale frame would mask as ``MissingTurnoverError`` on every cell
    at sweep time.

    Reproduces the operator-reported failure: every contract bailed
    with ``KeyError: 'turnover'`` because the bhavcopy cache had
    been written in P0.x (pre-turnover-extension)."""
    _redirect_cache(monkeypatch, tmp_path)
    # Reset the one-time-warning flag so this test sees the warning.
    monkeypatch.setattr(bfo, "_STALE_CACHE_WARNING_EMITTED", False)
    # Plant a stale 14-col parquet at the cache path BEFORE any
    # load_bhavcopy_fo call. Simulates the operator's state: cache
    # was written by an earlier session under the pre-P1.1 parser.
    stale = pd.DataFrame({
        "instrument": ["OPTSTK"],
        "symbol": ["PNB"],
        "expiry": pd.to_datetime([date(2024, 7, 25)]),
        "strike": [100.0],
        "option_type": ["CE"],
        "open": [4.8], "high": [5.5], "low": [4.5], "close": [5.0],
        "settle_price": [5.05],
        "contracts": [100], "oi": [1000], "oi_change": [0],
        "trade_date": pd.to_datetime([UDIFF_DATE]),
        # NO ``turnover``, NO ``ltp`` — pre-P1.1 14-col schema.
    })
    cache.write(cache.bhavcopy_fo_path(UDIFF_DATE), stale)

    # Wire a synthetic fetch so the re-fetch path is observable.
    raw = _udiff_raw()
    calls = {"n": 0}

    def fake_fetch(td):
        calls["n"] += 1
        return raw, "udiff"

    monkeypatch.setattr(bfo, "_fetch_raw", fake_fetch)

    df = bfo.load_bhavcopy_fo(UDIFF_DATE)
    # The fetcher was called even though a parquet existed → stale
    # detection re-routed to fetch.
    assert calls["n"] == 1, (
        "stale parquet should have triggered a re-fetch, but the "
        "loader returned the cached frame unchanged"
    )
    # Returned frame has the post-P1.1 schema.
    assert "turnover" in df.columns
    assert "ltp" in df.columns
    # Operator-visible warning fired exactly once.
    stale_warns = [w for w in recwarn.list if "stale 14-col cache" in str(w.message)]
    assert len(stale_warns) == 1, (
        f"expected one stale-cache warning; got {len(stale_warns)}"
    )
    # On-disk parquet now carries the fresh schema (so subsequent
    # loads short-circuit without re-fetching).
    reread = cache.read(cache.bhavcopy_fo_path(UDIFF_DATE))
    assert "turnover" in reread.columns


# ===========================================================
# Nullable Int64 for oi / oi_change — survives upstream blanks
# ===========================================================

def test_parser_handles_blank_oi_via_nullable_int(monkeypatch):
    """A future upstream row with a blank OPEN_INT (NSE has done this on
    new-contract bootstrap days) must NOT crash the parser. SPECS §2.4
    says oi is Int64 (nullable) for exactly this case."""
    raw = (
        "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,"
        "CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP\n"
        "OPTSTK,RELIANCE,25-Jan-2024,2620,CE,10,11,9,10.5,10.5,1,0.5,,,25-JAN-2024\n"
    )
    df = bfo.parse_legacy(raw, date(2024, 1, 25))
    assert len(df) == 1
    assert pd.isna(df.iloc[0]["oi"])
    assert pd.isna(df.iloc[0]["oi_change"])
    # contracts present → 1 (not coerced to NA — SPECS says fillna(0) for absent)
    assert df.iloc[0]["contracts"] == 1


# ===========================================================
# Fetcher dispatch at the cutover boundary (off-by-one trap)
# ===========================================================

def test_fetch_raw_dispatches_at_cutover_boundary(monkeypatch):
    """A `<` vs `<=` slip on the 2024-07-08 boundary would silently mis-
    route fetches. Pin: day-before -> legacy; cutover day -> udiff;
    day-after -> udiff."""
    monkeypatch.setattr(bfo, "_udiff_start_date", lambda: date(2024, 7, 8))
    seen = {"legacy": [], "udiff": []}

    def fake_legacy(td):
        seen["legacy"].append(td)
        return "raw-legacy"

    def fake_udiff(td):
        seen["udiff"].append(td)
        return "raw-udiff"

    monkeypatch.setattr(bfo, "_fetch_legacy", fake_legacy)
    monkeypatch.setattr(bfo, "_fetch_udiff", fake_udiff)

    raw, fmt = bfo._fetch_raw(date(2024, 7, 7))
    assert fmt == "legacy"
    raw, fmt = bfo._fetch_raw(date(2024, 7, 8))
    assert fmt == "udiff"
    raw, fmt = bfo._fetch_raw(date(2024, 7, 9))
    assert fmt == "udiff"

    assert seen["legacy"] == [date(2024, 7, 7)]
    assert seen["udiff"] == [date(2024, 7, 8), date(2024, 7, 9)]


# ===========================================================
# MissingDataError wrap for non-trading-day / 404 cases
# (p1.3.2 critical path — calendar iteration uses MissingDataError to skip)
# ===========================================================

def test_legacy_fetch_wraps_badzipfile_as_missing_data(monkeypatch):
    """When NSE serves an HTML 'not found' page (non-trading day, future
    date, post-cutover), jugaad raises BadZipFile. We surface it as
    MissingDataError so p1.3.2 can `except MissingDataError: continue`
    while sampling candidate dates."""
    class _FakeArc:
        def bhavcopy_fo_raw(self, dt):
            raise _zipfile.BadZipFile("not a zip")

    monkeypatch.setattr(bfo, "NSEArchives", lambda: _FakeArc())
    with pytest.raises(MissingDataError, match="no legacy F&O bhavcopy"):
        bfo._fetch_legacy(date(2024, 1, 6))  # Saturday


def test_udiff_fetch_wraps_404_as_missing_data(monkeypatch):
    class _FakeResp:
        status_code = 404
        def raise_for_status(self):
            err = _requests.HTTPError("404 Not Found")
            err.response = self
            raise err

    monkeypatch.setattr(bfo.requests, "get", lambda *a, **kw: _FakeResp())
    with pytest.raises(MissingDataError, match="no UDiff F&O bhavcopy.*404"):
        bfo._fetch_udiff(date(2024, 7, 13))  # Saturday


def test_udiff_fetch_wraps_badzipfile_as_missing_data(monkeypatch):
    """NSE sometimes returns HTML with 200 status instead of a 404 for
    missing dates — that surfaces as BadZipFile inside the unzip."""
    class _FakeResp:
        status_code = 200
        content = b"<html>not a zip</html>"
        def raise_for_status(self):
            pass

    monkeypatch.setattr(bfo.requests, "get", lambda *a, **kw: _FakeResp())
    with pytest.raises(MissingDataError, match="no UDiff F&O bhavcopy.*BadZipFile"):
        bfo._fetch_udiff(date(2024, 7, 13))


def test_udiff_403_propagates_not_wrapped(monkeypatch):
    """403 means the WAF blocked us (likely stale UA). Wrapping as
    MissingDataError would let a calendar-build silently skip every
    sampled day without surfacing why. Must propagate raw HTTPError."""
    class _FakeResp:
        status_code = 403
        def raise_for_status(self):
            err = _requests.HTTPError("403 Forbidden")
            err.response = self
            raise err

    monkeypatch.setattr(bfo.requests, "get", lambda *a, **kw: _FakeResp())
    with pytest.raises(_requests.HTTPError, match="403"):
        bfo._fetch_udiff(date(2024, 8, 29))


def test_udiff_5xx_propagates_not_wrapped(monkeypatch):
    """5xx is NSE flaking transiently — retryable, not 'no data'.
    Mapping to MissingDataError during a calendar build would mask a
    real outage as a quiet skip."""
    class _FakeResp:
        status_code = 503
        def raise_for_status(self):
            err = _requests.HTTPError("503 Service Unavailable")
            err.response = self
            raise err

    monkeypatch.setattr(bfo.requests, "get", lambda *a, **kw: _FakeResp())
    with pytest.raises(_requests.HTTPError, match="503"):
        bfo._fetch_udiff(date(2024, 8, 29))


def test_network_errors_are_not_wrapped(monkeypatch):
    """A connection-level RequestException is retryable, not 'no data';
    must propagate unchanged so caller can decide how to handle it."""
    def boom(*a, **kw):
        raise _requests.ConnectionError("network down")

    monkeypatch.setattr(bfo.requests, "get", boom)
    with pytest.raises(_requests.ConnectionError):
        bfo._fetch_udiff(date(2024, 8, 29))


# ===========================================================
# Cache round-trip preserves SPECS §2.4 schema
# ===========================================================

def test_force_refresh_refetches(monkeypatch, tmp_path):
    """Mirrors spot_loader.test_force_refresh_refetches: cache present
    + force_refresh=True triggers a re-fetch and overwrites the cache."""
    _redirect_cache(monkeypatch, tmp_path)
    raw = _legacy_raw()
    calls = {"n": 0}

    def fake_fetch(td):
        calls["n"] += 1
        return raw, "legacy"

    monkeypatch.setattr(bfo, "_fetch_raw", fake_fetch)

    bfo.load_bhavcopy_fo(LEGACY_DATE)
    assert calls["n"] == 1
    bfo.load_bhavcopy_fo(LEGACY_DATE)  # cache hit
    assert calls["n"] == 1
    bfo.load_bhavcopy_fo(LEGACY_DATE, force_refresh=True)
    assert calls["n"] == 2
    # And a subsequent normal call hits the (overwritten) cache
    bfo.load_bhavcopy_fo(LEGACY_DATE)
    assert calls["n"] == 2


def test_cache_round_trip_preserves_schema(monkeypatch, tmp_path):
    _redirect_cache(monkeypatch, tmp_path)
    raw = _legacy_raw()
    monkeypatch.setattr(bfo, "_fetch_raw", lambda td: (raw, "legacy"))
    df_in = bfo.load_bhavcopy_fo(LEGACY_DATE)
    # Second load reads from parquet, not in-memory df
    df_out = bfo.load_bhavcopy_fo(LEGACY_DATE)
    _assert_specs_2_4_schema(df_out)
    pd.testing.assert_frame_equal(df_in, df_out)
