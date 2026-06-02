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

  symbol     string
  year       int64
  month      int64
  lot_size   int64
  source     string  (one of {"sidecar", "bhavcopy", "both"})

Year+month granularity (not exact expiry date) is sufficient
because lot_sizes are stable per (symbol, expiry-month). The
sidecar's ``StockNm`` regex gives us year+month directly without
needing to decode NSE's proprietary epoch ``XpryDt`` column.
Consumers query via ``lot_size_lookup(symbol, expiry: date)``
which converts the queried expiry to (year, month) and joins.

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
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.config import CACHE_DIR  # noqa: E402
from src.data import cache  # noqa: E402


# ============================================================
# Diagnostic message format (operator-directed 2026-06-03)
# ============================================================

def _format_mismatch_message(
    sym: str, year: int, month: int,
    source_value_pairs: list[tuple[str, int]],
) -> str:
    """Format a per-mismatch diagnostic line per the operator's
    template: ``mismatch found in lot sizes between {x} and {y}
    for {sym} for {expiry}: {lot_x} and {lot_y}``.

    For pairs with ≥3 distinct (source, value) entries (rare; e.g. an
    NSE corporate action mid-window), the line enumerates all of them
    rather than picking two arbitrarily — the operator should see the
    full conflict shape.
    """
    sym_expiry = f"{sym} for {year}-{month:02d}"
    if len(source_value_pairs) == 2:
        (s1, v1), (s2, v2) = source_value_pairs
        return (
            f"mismatch found in lot sizes between {s1} and {s2} "
            f"for {sym_expiry}: {v1} and {v2}"
        )
    items = ", ".join(f"{s}={v}" for s, v in source_value_pairs)
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
) -> tuple[pd.DataFrame, list[str]]:
    """Detect (sym, year, month) pairs with conflicting lot_sizes
    within a single source set (sidecar OR bhavcopy). Drops the
    offending pairs from the returned frame; emits one diagnostic
    message per excluded pair.

    Returns ``(consistent_rows_only, messages)``.
    """
    if df.empty:
        return df, []
    grouped = df.groupby(["symbol", "year", "month"])["lot_size"].nunique()
    bad_keys = set(grouped[grouped > 1].index)
    if not bad_keys:
        return df.drop_duplicates(
            subset=["symbol", "year", "month"], keep="first",
        ).reset_index(drop=True), []
    messages: list[str] = []
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
        messages.append(_format_mismatch_message(sym, yr, mo, pairs))
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
) -> tuple[pd.DataFrame, list[str]]:
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
) -> tuple[pd.DataFrame, list[str]]:
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
) -> tuple[pd.DataFrame, list[str]]:
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
    messages: list[str] = []
    for _, r in merged[bad_mask].iterrows():
        sym = str(r["symbol"])
        yr = int(r["year"])
        mo = int(r["month"])
        v_side = int(r["lot_size_sidecar"])
        v_bhav = int(r["lot_size_bhavcopy"])
        messages.append(_format_mismatch_message(
            sym, yr, mo,
            [("sidecar", v_side), ("bhavcopy", v_bhav)],
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
# Public entry point
# ============================================================

def _default_sidecar_dir() -> Path:
    """Repo-root-relative sidecar location."""
    return REPO / "data" / "manual" / "contracts"


def _default_bhavcopy_lot_sizes_dir() -> Path:
    return CACHE_DIR / "bhavcopy_fo_lot_sizes"


def build_lot_size_parquet(
    *,
    out_path: Path | None = None,
    sidecar_dir: Path | None = None,
    bhavcopy_lot_sizes_dir: Path | None = None,
    verbose: bool = True,
) -> Path:
    """Build the unified ``(symbol, year, month) → lot_size`` cache
    and write to ``out_path``. Returns the written path.

    Verification header + summary printed on EVERY invocation when
    ``verbose=True``.

    Raises ``CrossSourceLotSizeMismatchError`` (a ``DataError``) on
    any of the 3 mismatch layers per MIGRATION.md §Cross-source
    lot-size policy.
    """
    out_path = out_path or cache.lot_sizes_path()
    sidecar_dir = sidecar_dir or _default_sidecar_dir()
    bhavcopy_lot_sizes_dir = (
        bhavcopy_lot_sizes_dir or _default_bhavcopy_lot_sizes_dir()
    )

    sidecar_df, sidecar_msgs = _load_all_sidecars(sidecar_dir)
    bhavcopy_df, bhavcopy_msgs = _load_all_bhavcopy_lot_sizes(
        bhavcopy_lot_sizes_dir,
    )
    unified, cross_msgs = _merge_with_cross_source_exclusion(
        sidecar_df, bhavcopy_df,
    )

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

        if n_excluded:
            print(
                f"\n=== Excluded {n_excluded} (symbol, expiry-month) "
                f"pair(s) due to lot_size mismatches ==="
            )
            if sidecar_msgs:
                print(
                    f"\n--- Sidecar-vs-sidecar ({len(sidecar_msgs)}) ---"
                )
                for m in sidecar_msgs:
                    print(f"  {m}")
            if bhavcopy_msgs:
                print(
                    f"\n--- Bhavcopy-internal ({len(bhavcopy_msgs)}) ---"
                )
                for m in bhavcopy_msgs:
                    print(f"  {m}")
            if cross_msgs:
                print(
                    f"\n--- Sidecar-vs-bhavcopy ({len(cross_msgs)}) ---"
                )
                for m in cross_msgs:
                    print(f"  {m}")
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
