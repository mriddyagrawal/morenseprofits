"""On-disk parquet cache.

The cache is the only persistence layer for raw NSE data. Every loader in
``src/data/`` reads through this module. Rules (see SPECS.md §7):

- Files are append-mostly; we never overwrite real historical data.
- A bumped ``CACHE_VERSION`` should be a deliberate breaking change. The
  cache root carries a ``.cache_version`` sentinel; opening a cache from
  a different version raises ``CacheVersionMismatch`` rather than silently
  corrupting reads.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from src.config import CACHE_DIR, CACHE_VERSION


class CacheVersionMismatch(RuntimeError):
    pass


_VERSION_FILE = ".cache_version"

# Memoize the version-sentinel check: SPECS-required loud failure on a
# mismatched cache, but a stat-per-path-build is too expensive once a sweep
# is constructing ~10k paths. We verify on first touch per process.
_root_verified: bool = False


class StrikeNotIntegerError(ValueError):
    """**Deprecated** as of the fractional-strikes-supported fix (post-P1.5
    perf commit). NSE genuinely emits fractional-rupee strikes for some
    stocks (e.g. BHEL ₹97.5 / 102.5 / 107.5 on 2024-01-04 — confirmed
    empirically from the cached bhavcopies). The original
    "strikes are integer" assumption was wrong; the class is retained for
    backwards-compat (test fixtures + log strings that reference it) but
    no longer raised by ``option_path``."""


class WouldOverwriteError(RuntimeError):
    """SPECS §7: cached historical data is append-mostly. Use overwrite=True
    on `write()` to opt into clobbering an existing file."""


def _ensure_root() -> Path:
    """Create cache root if missing and write/verify the version sentinel.
    Memoized via _root_verified — repeat calls cost ~zero."""
    global _root_verified
    if _root_verified:
        return CACHE_DIR
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    sentinel = CACHE_DIR / _VERSION_FILE
    if sentinel.exists():
        on_disk = sentinel.read_text().strip()
        if on_disk != str(CACHE_VERSION):
            raise CacheVersionMismatch(
                f"cache at {CACHE_DIR} is version {on_disk!r}, code expects {CACHE_VERSION!r}. "
                f"Move {CACHE_DIR} aside (see SPECS §7) before re-running."
            )
    else:
        sentinel.write_text(str(CACHE_VERSION))
    _root_verified = True
    return CACHE_DIR


def _reset_root_memo() -> None:
    """Test-only: drop the memoized verification so monkeypatched CACHE_DIR
    is re-validated. Production code never needs to call this."""
    global _root_verified
    _root_verified = False


def spot_path(symbol: str, year: int) -> Path:
    return _ensure_root() / "spot" / symbol.upper() / f"{year}.parquet"


def _strike_path_segment(strike: float) -> str:
    """Encode ``strike`` as a filesystem-safe deterministic string.

    Integer strikes use the bare integer form: 100 → "100" (backwards-
    compatible with all existing per-contract caches written under the
    integer-only assumption).

    Fractional strikes (e.g., BHEL ₹97.5 / 102.5) use ``{strike:g}``
    which renders 97.5 → "97.5". Collision-free: integer 100 → "100",
    100.0 → "100" (matches int path), 97.5 → "97.5" (distinct).
    """
    if float(strike) == int(strike):
        return f"{int(strike)}"
    # ``g`` trims trailing zeros: 97.5 → "97.5", 97.50 → "97.5"
    # (canonical). Two-decimal worst case for half-rupee tick size:
    # 102.5 → "102.5".
    return f"{strike:g}"


def option_path(symbol: str, expiry: date, strike: float, option_type: Literal["CE", "PE"]) -> Path:
    """Path to the per-contract EOD cache parquet.

    Supports both integer and fractional NSE strikes (the latter is
    real: BHEL had ₹97.5 / 102.5 strikes on 2024-01-04). Integer
    strikes encode as the bare integer (``100``); fractional strikes
    encode with ``g``-format (``97.5``). Backwards-compat: existing
    integer-strike caches written before fractional support are
    unaffected.
    """
    expiry_tag = expiry.strftime("%Y%m%d")
    return (
        _ensure_root()
        / "options"
        / symbol.upper()
        / expiry_tag
        / f"{_strike_path_segment(strike)}-{option_type.upper()}.parquet"
    )


def expiry_path(symbol: str) -> Path:
    return _ensure_root() / "expiries" / f"{symbol.upper()}.parquet"


def bhavcopy_fo_path(trade_date: date) -> Path:
    """Per-date F&O bhavcopy parquet — symbol-agnostic.

    One file serves every symbol's expiry-calendar build, so a 5-symbol ×
    5-year sweep fetches ~60 monthly bhavcopies once, not 300.

    Filename is the trade date in YYYYMMDD form so the cache directory
    sorts naturally and a future "rebuild expiries for all symbols in
    Jan 2024" knows exactly which files are relevant.

    **Type contract**: `trade_date` must be a `datetime.date` and **not** a
    `datetime.datetime` (a subclass of date — would be silently accepted).
    A tz-aware datetime would be genuinely ambiguous about which trade date
    it names (`23:59 UTC` vs `23:59 IST` straddle different calendar days);
    a naive datetime is merely unnecessary. Caller does `dt.date()` to opt
    in. Loud rejection beats silent truncation.
    """
    if isinstance(trade_date, datetime):
        raise TypeError(
            f"bhavcopy_fo_path expects datetime.date, got datetime: {trade_date!r}. "
            f"Call .date() on it first — a tz-aware datetime would be ambiguous "
            f"about which trade date it represents."
        )
    return _ensure_root() / "bhavcopy_fo" / f"{trade_date.strftime('%Y%m%d')}.parquet"


def bhavcopy_fo_lot_sizes_path(trade_date: date) -> Path:
    """Sibling-cache path for per-date UDiff lot-size triples
    extracted from the raw bhavcopy at fetch time.

    Schema written: ``symbol, expiry, lot_size, trade_date`` (one row
    per unique ``(symbol, expiry)`` from that day's OPTSTK+OPTIDX
    rows). Legacy bhavcopy dates get an empty parquet (legacy raw
    doesn't carry lot_size).

    Consumed by ``scripts/build_lot_size_parquet.py`` (P0.2) to merge
    with the regime B sidecars into the unified
    ``data/cache/lot_sizes.parquet``. Same date-stamped layout as
    ``bhavcopy_fo_path``, so ``rm -rf data/cache/`` wipes both.

    See MIGRATION.md §Architectural target diagram + §Phase 0 P0.2.
    """
    if isinstance(trade_date, datetime):
        raise TypeError(
            f"bhavcopy_fo_lot_sizes_path expects datetime.date, got "
            f"datetime: {trade_date!r}. Call .date() on it first."
        )
    return (
        _ensure_root() / "bhavcopy_fo_lot_sizes"
        / f"{trade_date.strftime('%Y%m%d')}.parquet"
    )


def lot_sizes_path() -> Path:
    """The unified ``(symbol, expiry_month) → lot_size`` lookup
    parquet, built by ``scripts/build_lot_size_parquet.py`` from BOTH
    the sidecars (``data/manual/contracts/NSE_FO_contract_*.csv.gz``)
    and the bhavcopy-derived lot-sizes
    (``data/cache/bhavcopy_fo_lot_sizes/*.parquet``).

    Auto-built by ``scripts/prefetch_universe.py`` when missing. See
    MIGRATION.md §Cross-source lot-size policy + §Phase 0 P0.2.
    """
    return _ensure_root() / "lot_sizes.parquet"


def exists(path: Path) -> bool:
    return path.is_file()


def read(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def write(path: Path, df: pd.DataFrame, *, overwrite: bool = False) -> None:
    """Write df to path atomically (write-then-rename) so a crash mid-write
    cannot leave a half-baked file the next reader would happily load.

    Refuses to clobber an existing file unless `overwrite=True` (SPECS §7);
    loaders that re-fetch the current year's spot tail will pass overwrite=True.

    Multi-writer safe — the tmp filename includes PID + a random suffix so
    concurrent workers writing the SAME target path (e.g. 8 sweep workers
    each refetching the open-year spot tail) don't collide on a shared
    `.tmp`. POSIX rename is atomic on a single filesystem, so the last
    rename wins cleanly; intermediate readers see either the OLD complete
    file or the NEW complete file, never a torn write.
    """
    if path.exists() and not overwrite:
        raise WouldOverwriteError(
            f"{path} already exists; pass overwrite=True to clobber (SPECS §7)."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f"{path.name}.tmp.{os.getpid()}.{os.urandom(4).hex()}"
    )
    try:
        df.to_parquet(tmp, index=False)
        tmp.replace(path)
    except Exception:
        # Atomic-write guarantee: never leave a half-baked .tmp behind on failure.
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
