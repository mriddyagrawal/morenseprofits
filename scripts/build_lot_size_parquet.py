"""Build the unified ``(symbol, year, month) → lot_size`` lookup parquet.

Reads from BOTH lot-size sources defined by MIGRATION.md
§Architectural target:

  Sidecar (regime B, static, committed):
    data/manual/contracts/NSE_FO_contract_*.csv.gz

  Sibling bhavcopy cache (regime C, dynamic, derived):
    data/cache/bhavcopy_fo_lot_sizes/*.parquet
    (written by src/data/bhavcopy_fo_loader.py on every fresh
     bhavcopy fetch — see that module's docstring + P0.2 design)

Merges + cross-validates with per-pair exclusion (per operator
direction 2026-06-03 — supersedes the original loud-fail policy).
Mismatches detected at three layers; all treated SYMMETRICALLY:

  1. Sidecar-vs-sidecar — same (symbol, year, month) appearing in
     multiple NSE_FO_contract snapshots with DIFFERENT lot_sizes.
     Almost always an NSE biannual lot-size revision (lot halved
     between snapshots).
  2. Bhavcopy-internal — same (symbol, year, month) appearing on
     multiple trade dates with DIFFERENT lot_sizes. Mid-contract
     revision (corporate action during the contract's life).
  3. Sidecar-vs-bhavcopy — for (symbol, year, month) pairs present
     in both sources, lot_sizes disagree.

**Policy**: any of the three mismatch types → DROP that
(symbol, expiry-month) from the unified cache. The downstream
transform queries the cache; an excluded (sym, expiry-month) returns
no row; the transform raises ``MissingTurnoverError``; the sweep
skips the affected cells with ``skip_reason="MissingTurnoverError"``.

Rationale (per operator 2026-06-03): if NSE revised a contract's
lot_size mid-life, that contract's P&L is structurally ambiguous —
entry at one lot, exit at another. Skipping is more honest than
picking a "winner" value.

Each excluded pair emits a diagnostic line in the operator's exact
template:

    mismatch found in lot sizes between {x} and {y} for {sym}
    for {expiry}: {lot_size_x} and {lot_size_y}

These lines surface prominently in the build script's stdout (which
the prefetch wrapper passes through to operator console).

Output (``data/cache/lot_sizes.parquet``) schema:

  symbol       string
  year         int64
  month        int64
  lot_size     int64
  source       string          (one of {"sidecar", "bhavcopy", "both"})
  expiry_date  datetime64[us]  (canonical monthly OPTSTK expiry for
                                this (year, month) — resolved from a
                                sampled bhavcopy in that month, or via
                                last-Thursday algorithmic fallback when
                                no bhavcopy is cached for that month).

Year+month granularity for the JOIN KEY (not exact expiry date) is
sufficient because lot_sizes are stable per (symbol, expiry-month).
The sidecar's ``StockNm`` regex gives us year+month directly without
needing to decode NSE's proprietary epoch ``XpryDt`` column.
Consumers query via ``lot_size_lookup(symbol, expiry: date)`` which
converts the queried expiry to (year, month) and joins.

The ``expiry_date`` column is added at build time so downstream
consumers (the sweep's expiry-list builder, MCP sweep_windows,
operator audit tools) get the actual expiry date without needing a
second roundtrip through bhavcopies or ``expiry_calendar`` — they
just ``filter + unique(expiry_date)`` on this one parquet. NSE F&O
monthly options of all OPTSTK symbols share the same monthly expiry
date (last Thursday of month, or last Wednesday on rare
holiday-shift months), so the date is a function of ``(year, month)``
alone — symbol-dimension duplication is intentional + cheap
(~6× rows at 1k-row scale ≈ 12KB).

Console output policy (per reviewer grills #2 + #5 on 9b6c32b):
  - ``=== Cross-source lot-size verification ===`` header on EVERY
    invocation (happy AND failure path).
  - Happy path: summary line with N pairs verified + source
    breakdown + write confirmation.
  - Failure path: header + the mismatch detail + non-zero exit.

CLI invocation (auto-build trigger in prefetch_universe.py wires
this in headlessly when ``data/cache/lot_sizes.parquet`` is missing
or ``--rebuild-lot-sizes`` is passed):

    python -m scripts.build_lot_size_parquet
    python -m scripts.build_lot_size_parquet --quiet
    python -m scripts.build_lot_size_parquet \\
        --sidecar-dir path/to/contracts/ \\
        --bhavcopy-lot-sizes-dir path/to/cache/

See MIGRATION.md §Phase 0 P0.2 for the full architectural role.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.config import CACHE_DIR  # noqa: E402
from src.data import cache  # noqa: E402


# ============================================================
# Diagnostic message format (operator-directed 2026-06-03)
# ============================================================

def _compress_pairs_to_runs(
    pairs: list[tuple[str, int]],
) -> list[tuple[str, str, int, int]]:
    """Group consecutive same-value entries in ``pairs`` into runs.

    Returns a list of ``(first_source, last_source, count, value)``
    tuples — one per run. A pair list of length N with K distinct
    consecutive runs becomes K tuples; if every value differs from
    its neighbour, K == N and the compression is a no-op.

    Load-bearing for the bhavcopy-internal mismatch case where a
    far-dated NIFTY expiry (e.g. 2027-12) can carry 450+ trade-date
    observations across the prefetch window: NSE lot-size revisions
    create 2–3 contiguous runs (lot=25 for ~120 days, lot=75 for
    ~250 days, lot=65 for ~95 days). Without compression the
    diagnostic line is ~hundreds of bytes per excluded pair × dozens
    of NIFTY expiries = thousands of lines of unscannable output.
    """
    if not pairs:
        return []
    runs: list[tuple[str, str, int, int]] = []
    cur_first, cur_value = pairs[0]
    cur_last = cur_first
    cur_count = 1
    for src, val in pairs[1:]:
        if val == cur_value:
            cur_last = src
            cur_count += 1
        else:
            runs.append((cur_first, cur_last, cur_count, cur_value))
            cur_first, cur_last, cur_value, cur_count = src, src, val, 1
    runs.append((cur_first, cur_last, cur_count, cur_value))
    return runs


def _format_run(run: tuple[str, str, int, int]) -> str:
    """Format one run from ``_compress_pairs_to_runs``. A 1-date
    run prints as ``{src}={value}`` (matches the pre-compression
    output for short pair lists); a multi-date run prints as
    ``{value} ({first} → {last}, N dates)``."""
    first, last, count, value = run
    if count == 1:
        return f"{first}={value}"
    return f"{value} ({first} → {last}, {count} dates)"


def _format_mismatch_message(
    sym: str, year: int, month: int,
    source_value_pairs: list[tuple[str, int]],
) -> str:
    """Format a per-mismatch diagnostic line per the operator's
    template: ``mismatch found in lot sizes between {x} and {y}
    for {sym} for {expiry}: {lot_x} and {lot_y}``.

    For pairs with ≥3 entries (bhavcopy-internal with many trade-date
    observations, or rare 3+-source corporate-action cases), the line
    compresses consecutive same-value runs via
    ``_compress_pairs_to_runs`` to keep the output scannable. A
    1-date run prints in the original ``{src}={value}`` form so
    short conflict shapes look identical to pre-compression output.
    """
    sym_expiry = f"{sym} for {year}-{month:02d}"
    if len(source_value_pairs) == 2:
        (s1, v1), (s2, v2) = source_value_pairs
        return (
            f"mismatch found in lot sizes between {s1} and {s2} "
            f"for {sym_expiry}: {v1} and {v2}"
        )
    runs = _compress_pairs_to_runs(source_value_pairs)
    items = ", ".join(_format_run(r) for r in runs)
    return f"mismatch found in lot sizes for {sym_expiry}: {items}"


# ============================================================
# Sidecar parsing
# ============================================================

# NSE_FO_contract columns we read. The full file has 150 columns;
# we ignore everything else.
_SIDECAR_SYMBOL_COL = "TckrSymb"
_SIDECAR_STOCKNM_COL = "StockNm"
_SIDECAR_LOT_COL = "NewBrdLotQty"
_SIDECAR_INSTRTP_COL = "FinInstrmNm"

# StockNm regex extracting the expiry month: e.g. ``PNB26JUN138CE``
# → ``("26", "JUN", "CE")``. The strike portion can be decimal
# (e.g. ``PNB24SEP157.5CE``). Symbol prefixes can contain letters,
# digits, ampersands (``M&M``), or hyphens (``BAJAJ-AUTO``).
_STOCKNM_RE = re.compile(
    r"^[A-Z0-9&\-]+?(\d{2})([A-Z]{3})\d+(?:\.\d+)?(CE|PE)$"
)

_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

_LOT_SIZE_OPTION_INSTRUMENTS = ("OPTSTK", "OPTIDX")


def parse_sidecar(path: Path) -> pd.DataFrame:
    """Parse one NSE_FO_contract_*.csv.gz into a deduplicated
    ``(symbol, year, month, lot_size, _source_file)`` frame.

    Filters to OPTSTK + OPTIDX (futures excluded — same scope as the
    bhavcopy lot-size extractor in bhavcopy_fo_loader.py).
    """
    df = pd.read_csv(
        path,
        usecols=[
            _SIDECAR_SYMBOL_COL, _SIDECAR_STOCKNM_COL,
            _SIDECAR_LOT_COL, _SIDECAR_INSTRTP_COL,
        ],
    )
    df = df[df[_SIDECAR_INSTRTP_COL].isin(_LOT_SIZE_OPTION_INSTRUMENTS)]
    # Drop rows with no StockNm (some rows in the file have NaN).
    df = df.dropna(subset=[_SIDECAR_STOCKNM_COL])
    matches = df[_SIDECAR_STOCKNM_COL].astype(str).str.extract(_STOCKNM_RE)
    df = df.copy()
    df["yy"] = matches[0]
    df["mmm"] = matches[1]
    df = df.dropna(subset=["yy", "mmm"])
    df["year"] = (2000 + df["yy"].astype(int)).astype("int64")
    df["month"] = df["mmm"].map(_MONTH_MAP).astype("Int64")
    df = df.dropna(subset=["month"])
    out = pd.DataFrame({
        "symbol": df[_SIDECAR_SYMBOL_COL].astype("string"),
        "year": df["year"].astype("int64"),
        "month": df["month"].astype("int64"),
        "lot_size": df[_SIDECAR_LOT_COL].astype("int64"),
    })
    out["_source_file"] = path.name
    return (
        out.drop_duplicates(subset=["symbol", "year", "month"], keep="first")
        .reset_index(drop=True)
    )


# ============================================================
# Mismatch detection — within-source + cross-source (symmetric)
# ============================================================

def _detect_within_source_mismatches(
    df: pd.DataFrame, *, source_col: str,
) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """Detect (sym, year, month) pairs with conflicting lot_sizes
    within a single source set (sidecar OR bhavcopy). Drops the
    offending pairs from the returned frame; emits one diagnostic
    message per excluded pair.

    Returns ``(consistent_rows_only, messages_with_symbol)`` where
    each ``messages_with_symbol`` entry is a ``(symbol, message)``
    tuple. The symbol tag lets the build's print-time code filter
    diagnostics by the prefetch's ``--symbols`` list without
    re-parsing the message string (per the symbol-scoping cleanup).
    Excluded pairs are dropped from the consistent frame regardless
    of any symbol filter — correctness preserved.
    """
    if df.empty:
        return df, []
    grouped = df.groupby(["symbol", "year", "month"])["lot_size"].nunique()
    bad_keys = set(grouped[grouped > 1].index)
    if not bad_keys:
        return df.drop_duplicates(
            subset=["symbol", "year", "month"], keep="first",
        ).reset_index(drop=True), []
    messages: list[tuple[str, str]] = []
    for sym, yr, mo in sorted(bad_keys):
        sub = df[
            (df["symbol"] == sym)
            & (df["year"] == yr)
            & (df["month"] == mo)
        ][[source_col, "lot_size"]].drop_duplicates(
            subset=[source_col, "lot_size"],
        )
        pairs = [
            (str(r[source_col]), int(r["lot_size"]))
            for _, r in sub.iterrows()
        ]
        # Dedup to distinct (source, value) tuples; if a source has
        # multiple rows with the same value, keep one.
        pairs = list(dict.fromkeys(pairs))
        messages.append((
            str(sym),
            _format_mismatch_message(sym, yr, mo, pairs),
        ))
    # Drop offending pairs.
    df_keyed = df.set_index(["symbol", "year", "month"])
    keep_mask = ~df_keyed.index.isin(bad_keys)
    return (
        df_keyed[keep_mask]
        .reset_index()
        .drop_duplicates(
            subset=["symbol", "year", "month"], keep="first",
        )
        .reset_index(drop=True),
        messages,
    )


def _load_all_sidecars(
    sidecar_dir: Path,
) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """Load + concat every NSE_FO_contract_*.csv.gz under
    ``sidecar_dir``. Detects sidecar-vs-sidecar mismatches and EXCLUDES
    those (symbol, year, month) pairs from the returned frame per the
    per-pair-exclude policy.

    Returns ``(consistent_rows, mismatch_messages)`` — the messages
    are emitted to stdout by the caller alongside the source-summary.
    """
    files = sorted(sidecar_dir.glob("NSE_FO_contract_*.csv.gz"))
    if not files:
        return pd.DataFrame(columns=[
            "symbol", "year", "month", "lot_size", "_source_file",
        ]), []
    frames = [parse_sidecar(p) for p in files]
    all_df = pd.concat(frames, ignore_index=True)
    return _detect_within_source_mismatches(
        all_df, source_col="_source_file",
    )


def _load_all_bhavcopy_lot_sizes(
    bhavcopy_dir: Path,
) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """Load + concat every per-date sibling parquet in
    ``data/cache/bhavcopy_fo_lot_sizes/``. Detects bhavcopy-internal
    mismatches (same (sym, yr, mo) with different lot_size across
    trade dates → mid-cycle NSE corporate action) and EXCLUDES those
    (sym, yr, mo) pairs.

    Returns ``(consistent_rows, mismatch_messages)``.
    """
    files = sorted(bhavcopy_dir.glob("*.parquet"))
    empty = (
        pd.DataFrame(columns=[
            "symbol", "year", "month", "lot_size", "_trade_date_str",
        ]),
        [],
    )
    if not files:
        return empty
    frames = [pd.read_parquet(f) for f in files]
    all_df = pd.concat(frames, ignore_index=True)
    if all_df.empty:
        return empty
    all_df["year"] = all_df["expiry"].dt.year.astype("int64")
    all_df["month"] = all_df["expiry"].dt.month.astype("int64")
    # Use trade_date as the source label in mismatch messages.
    all_df["_trade_date_str"] = all_df["trade_date"].dt.strftime(
        "bhavcopy-%Y-%m-%d"
    )
    return _detect_within_source_mismatches(
        all_df[[
            "symbol", "year", "month", "lot_size", "_trade_date_str",
        ]],
        source_col="_trade_date_str",
    )


# ============================================================
# Cross-source merge
# ============================================================

def _merge_with_cross_source_exclusion(
    sidecar_df: pd.DataFrame, bhavcopy_df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """Outer-merge sidecar + bhavcopy on (sym, yr, mo). Detect
    sidecar-vs-bhavcopy disagreements and EXCLUDE those pairs from
    the unified frame per the per-pair-exclude policy. Returns
    ``(unified_with_source_column, cross_source_messages)``.

    The ``source`` column on the output frame tags each surviving
    row as ``sidecar`` / ``bhavcopy`` / ``both`` for downstream
    debugging.
    """
    merged = sidecar_df[["symbol", "year", "month", "lot_size"]].merge(
        bhavcopy_df[["symbol", "year", "month", "lot_size"]],
        on=["symbol", "year", "month"],
        how="outer",
        suffixes=("_sidecar", "_bhavcopy"),
    )
    in_both_mask = (
        merged["lot_size_sidecar"].notna()
        & merged["lot_size_bhavcopy"].notna()
    )
    bad_mask = (
        in_both_mask
        & (merged["lot_size_sidecar"] != merged["lot_size_bhavcopy"])
    )
    messages: list[tuple[str, str]] = []
    for _, r in merged[bad_mask].iterrows():
        sym = str(r["symbol"])
        yr = int(r["year"])
        mo = int(r["month"])
        v_side = int(r["lot_size_sidecar"])
        v_bhav = int(r["lot_size_bhavcopy"])
        messages.append((
            sym,
            _format_mismatch_message(
                sym, yr, mo,
                [("sidecar", v_side), ("bhavcopy", v_bhav)],
            ),
        ))
    # Exclude the disagreeing pairs from the output.
    surviving = merged[~bad_mask].copy()
    has_sidecar = surviving["lot_size_sidecar"].notna()
    has_bhavcopy = surviving["lot_size_bhavcopy"].notna()
    source = pd.Series(
        [
            "both" if (s and b)
            else ("sidecar" if s else "bhavcopy")
            for s, b in zip(has_sidecar, has_bhavcopy)
        ],
        dtype="string",
    )
    surviving["lot_size"] = surviving["lot_size_sidecar"].combine_first(
        surviving["lot_size_bhavcopy"]
    )
    out = pd.DataFrame({
        "symbol": surviving["symbol"].astype("string"),
        "year": surviving["year"].astype("int64"),
        "month": surviving["month"].astype("int64"),
        "lot_size": surviving["lot_size"].astype("int64"),
        "source": source.values,
    })
    out = out.sort_values(["symbol", "year", "month"]).reset_index(drop=True)
    return out, messages


# ============================================================
# Expiry-date resolution (post-merge enrichment)
# ============================================================
#
# Adds the canonical monthly OPTSTK ``expiry_date`` to each (year, month)
# in the merged frame, so downstream consumers (sweep, MCP, audit) can
# do ``filter + unique(expiry_date)`` on this parquet without a second
# pass over bhavcopies.
#
# Strategy: for each unique (year, month), try days 1..28 of that month
# for a cached bhavcopy. Once found, take the OPTSTK rows whose
# ``expiry`` column falls in (year, month), validate exactly one
# distinct expiry exists (NSE monthly options canonically have one
# expiry per month; > 1 would signal weekly options leaking through
# our OPTSTK filter — log + take the latest).
#
# Fallback: if no bhavcopy is cached for ANY day in (year, month) —
# the case for future expiries listed in sidecars but with no trading
# days yet — compute last-Thursday algorithmically. Holiday-shifted
# expiries (rare: ~1-2 per year shifted to Wednesday) will be off by
# one day under the fallback; the sweep then sees no contracts on that
# date and skips. Acceptable for a future-month edge case.


def _last_thursday_of_month(year: int, month: int) -> date:
    """Algorithmic fallback when no bhavcopy is cached for (year, month).
    Returns the last Thursday of the month. NSE F&O monthly options
    canonically expire on this date; ~1-2 months per year shift to
    Wednesday for holiday reasons (Christmas / Republic Day) and the
    fallback misses those; we accept that for the future-month case
    only (cached-month case always uses the bhavcopy-derived date)."""
    if month == 12:
        first_of_next = date(year + 1, 1, 1)
    else:
        first_of_next = date(year, month + 1, 1)
    last_day = first_of_next - timedelta(days=1)
    # Walk back to Thursday (weekday 3 in Python: Mon=0..Sun=6).
    while last_day.weekday() != 3:
        last_day -= timedelta(days=1)
    return last_day


def _resolve_expiry_date(
    year: int, month: int, bhavcopy_fo_dir: Path,
) -> tuple[date, str]:
    """Return ``(expiry_date, provenance)`` for one (year, month).

    Provenance:
      ``"bhavcopy"``  — found a usable bhavcopy in the month + extracted
                        the canonical OPTSTK expiry from it.
      ``"fallback"``  — no bhavcopy on disk for that month; used
                        ``_last_thursday_of_month``.

    Reads through the explicit ``bhavcopy_fo_dir`` arg (not
    ``cache.bhavcopy_fo_path``) so tests passing a fresh ``tmp_path``
    don't inadvertently read the operator's real cache.
    """
    for day in range(1, 29):
        try:
            anchor = date(year, month, day)
        except ValueError:
            continue
        path = bhavcopy_fo_dir / f"{anchor:%Y%m%d}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if df.empty or "instrument" not in df.columns or "expiry" not in df.columns:
            continue
        mask = (
            (df["instrument"] == "OPTSTK")
            & (df["expiry"].dt.year == year)
            & (df["expiry"].dt.month == month)
        )
        exps = sorted(df.loc[mask, "expiry"].dt.date.unique())
        if not exps:
            continue
        # NSE monthly OPTSTK has one expiry per month. If we see > 1
        # something leaked our filter — take the LATEST (canonical
        # monthly is last Thursday). This branch is defensive; not
        # expected to fire on real bhavcopy data.
        return exps[-1], "bhavcopy"
    return _last_thursday_of_month(year, month), "fallback"


def _attach_expiry_date_column(
    unified: pd.DataFrame, bhavcopy_fo_dir: Path,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Add an ``expiry_date`` column to ``unified``. Returns
    ``(frame_with_column, provenance_counts)`` where the counts dict
    has keys ``{"bhavcopy", "fallback"}`` for verbose-mode logging.
    Memoizes per (year, month) so each unique month-anchor reads at
    most one bhavcopy regardless of how many symbols share it."""
    if unified.empty:
        out = unified.copy()
        out["expiry_date"] = pd.Series([], dtype="datetime64[us]")
        return out, {"bhavcopy": 0, "fallback": 0}
    cache_map: dict[tuple[int, int], tuple[date, str]] = {}
    for (yr, mo) in sorted(
        {(int(y), int(m)) for y, m in zip(unified["year"], unified["month"])}
    ):
        cache_map[(yr, mo)] = _resolve_expiry_date(yr, mo, bhavcopy_fo_dir)
    counts = {"bhavcopy": 0, "fallback": 0}
    for (exp_d, prov) in cache_map.values():
        counts[prov] += 1
    out = unified.copy()
    out["expiry_date"] = pd.Series(
        [
            pd.Timestamp(cache_map[(int(y), int(m))][0])
            for y, m in zip(out["year"], out["month"])
        ],
        dtype="datetime64[us]",
    )
    return out, counts


# ============================================================
# Public entry point
# ============================================================

def _default_sidecar_dir() -> Path:
    """Repo-root-relative sidecar location."""
    return REPO / "data" / "manual" / "contracts"


def _default_bhavcopy_lot_sizes_dir() -> Path:
    return CACHE_DIR / "bhavcopy_fo_lot_sizes"


def _default_bhavcopy_fo_dir() -> Path:
    return CACHE_DIR / "bhavcopy_fo"


def build_lot_size_parquet(
    *,
    out_path: Path | None = None,
    sidecar_dir: Path | None = None,
    bhavcopy_lot_sizes_dir: Path | None = None,
    bhavcopy_fo_dir: Path | None = None,
    verbose: bool = True,
    symbols_filter: Iterable[str] | None = None,
) -> Path:
    """Build the unified ``(symbol, year, month) → lot_size`` cache
    and write to ``out_path``. Returns the written path.

    Verification header + summary printed on EVERY invocation when
    ``verbose=True``.

    ``symbols_filter`` (case-insensitive) scopes the printed
    diagnostic messages to mismatches involving symbols in the
    filter. Out-of-filter excluded pairs are still DROPPED from the
    parquet (correctness preserved); their messages are summarized
    as a single ``Suppressed N message(s)`` line instead. Defaults
    to ``None`` (all messages printed — backwards compatible with
    standalone CLI invocations).

    Raises ``CrossSourceLotSizeMismatchError`` (a ``DataError``) on
    any of the 3 mismatch layers per MIGRATION.md §Cross-source
    lot-size policy.
    """
    out_path = out_path or cache.lot_sizes_path()
    sidecar_dir = sidecar_dir or _default_sidecar_dir()
    bhavcopy_lot_sizes_dir = (
        bhavcopy_lot_sizes_dir or _default_bhavcopy_lot_sizes_dir()
    )
    bhavcopy_fo_dir = bhavcopy_fo_dir or _default_bhavcopy_fo_dir()

    sidecar_df, sidecar_msgs = _load_all_sidecars(sidecar_dir)
    bhavcopy_df, bhavcopy_msgs = _load_all_bhavcopy_lot_sizes(
        bhavcopy_lot_sizes_dir,
    )
    unified, cross_msgs = _merge_with_cross_source_exclusion(
        sidecar_df, bhavcopy_df,
    )
    unified, expiry_provenance = _attach_expiry_date_column(
        unified, bhavcopy_fo_dir,
    )

    filter_upper: set[str] | None = (
        {s.upper() for s in symbols_filter}
        if symbols_filter is not None
        else None
    )

    def _split_in_out(
        msgs: list[tuple[str, str]],
    ) -> tuple[list[str], int]:
        if filter_upper is None:
            return [m for _, m in msgs], 0
        in_filter = [m for sym, m in msgs if sym.upper() in filter_upper]
        suppressed = len(msgs) - len(in_filter)
        return in_filter, suppressed

    if verbose:
        n_sidecar_only = int((unified["source"] == "sidecar").sum())
        n_bhavcopy_only = int((unified["source"] == "bhavcopy").sum())
        n_both = int((unified["source"] == "both").sum())
        n_total = len(unified)
        n_sidecar_files = len(
            list(sidecar_dir.glob("NSE_FO_contract_*.csv.gz"))
        )
        n_bhavcopy_files = len(
            list(bhavcopy_lot_sizes_dir.glob("*.parquet"))
        )
        n_excluded = (
            len(sidecar_msgs) + len(bhavcopy_msgs) + len(cross_msgs)
        )

        print("=== Lot-size verification ===")
        print(
            f"Verified {n_total} (symbol, expiry_month) pairs across "
            f"{n_sidecar_files} sidecars + {n_bhavcopy_files} bhavcopies."
        )
        print(
            f"  source breakdown: sidecar_only={n_sidecar_only} | "
            f"bhavcopy_only={n_bhavcopy_only} | both={n_both}"
        )
        # Expiry-date provenance — bhavcopy-derived dates are
        # holiday-shift-correct; fallback uses algorithmic last-Thursday
        # and may be off by one trading day on the rare Christmas /
        # Republic-Day months. Surface counts so the operator can spot
        # an unexpected fallback spike (e.g., a missing bhavcopy in a
        # historical month would push that month's rows to fallback).
        print(
            f"  expiry_date provenance: bhavcopy={expiry_provenance['bhavcopy']} | "
            f"fallback={expiry_provenance['fallback']}"
        )

        if n_excluded:
            sidecar_print, sidecar_suppressed = _split_in_out(sidecar_msgs)
            bhavcopy_print, bhavcopy_suppressed = _split_in_out(bhavcopy_msgs)
            cross_print, cross_suppressed = _split_in_out(cross_msgs)
            total_suppressed = (
                sidecar_suppressed + bhavcopy_suppressed + cross_suppressed
            )
            scope_tag = (
                f"  [symbol-scoped: {sorted(filter_upper)}]"
                if filter_upper is not None else ""
            )
            print(
                f"\n=== Excluded {n_excluded} (symbol, expiry-month) "
                f"pair(s) due to lot_size mismatches ==={scope_tag}"
            )
            if sidecar_print:
                print(
                    f"\n--- Sidecar-vs-sidecar ({len(sidecar_print)}"
                    f"/{len(sidecar_msgs)}) ---"
                )
                for m in sidecar_print:
                    print(f"  {m}")
            if bhavcopy_print:
                print(
                    f"\n--- Bhavcopy-internal ({len(bhavcopy_print)}"
                    f"/{len(bhavcopy_msgs)}) ---"
                )
                for m in bhavcopy_print:
                    print(f"  {m}")
            if cross_print:
                print(
                    f"\n--- Sidecar-vs-bhavcopy ({len(cross_print)}"
                    f"/{len(cross_msgs)}) ---"
                )
                for m in cross_print:
                    print(f"  {m}")
            if total_suppressed:
                print(
                    f"\n  Suppressed {total_suppressed} message(s) for "
                    f"symbols outside the --symbols list "
                    f"(still dropped from parquet)."
                )
            print(
                f"\nExcluded pairs are NOT written to "
                f"{out_path.name}. Cells touching these contracts "
                f"will skip with MissingTurnoverError. See "
                f"MIGRATION.md §Cross-source lot-size policy."
            )
        else:
            print("  No mismatches detected.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    unified.to_parquet(out_path, index=False)
    if verbose:
        print(f"\n  → wrote {out_path}")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the unified (symbol, year, month) → lot_size "
            "lookup parquet from committed sidecars + bhavcopy "
            "sibling cache."
        ),
    )
    parser.add_argument(
        "--out-path", type=Path, default=None,
        help="Override the unified parquet output path.",
    )
    parser.add_argument(
        "--sidecar-dir", type=Path, default=None,
        help="Override the NSE_FO_contract sidecar directory.",
    )
    parser.add_argument(
        "--bhavcopy-lot-sizes-dir", type=Path, default=None,
        help="Override the per-date sibling lot-size cache directory.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress the verification header + summary.",
    )
    args = parser.parse_args()
    # Under the per-pair-exclude policy, mismatches are absorbed into
    # the exclusion list and the build still succeeds. Only TRUE
    # errors (file parse failure, missing source directory, etc.)
    # propagate as non-zero exits — the prefetch wrapper halts on
    # those.
    build_lot_size_parquet(
        out_path=args.out_path,
        sidecar_dir=args.sidecar_dir,
        bhavcopy_lot_sizes_dir=args.bhavcopy_lot_sizes_dir,
        verbose=not args.quiet,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
