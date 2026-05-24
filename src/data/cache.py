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

from datetime import date
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
    """NSE stock-option strikes are whole rupees. A non-integer strike here
    would collide via int(round(...)) with a neighbour (banker's rounding:
    50.5 → 50, same file as a true ₹50 strike)."""


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


def option_path(symbol: str, expiry: date, strike: float, option_type: Literal["CE", "PE"]) -> Path:
    if float(strike) != int(strike):
        raise StrikeNotIntegerError(
            f"strike {strike!r} is not a whole rupee; NSE stock-option strikes are integer. "
            f"Pass an int or a float with no fractional part."
        )
    strike_int = int(strike)
    expiry_tag = expiry.strftime("%Y%m%d")
    return (
        _ensure_root()
        / "options"
        / symbol.upper()
        / expiry_tag
        / f"{strike_int}-{option_type.upper()}.parquet"
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
    """
    return _ensure_root() / "bhavcopy_fo" / f"{trade_date.strftime('%Y%m%d')}.parquet"


def exists(path: Path) -> bool:
    return path.is_file()


def read(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def write(path: Path, df: pd.DataFrame, *, overwrite: bool = False) -> None:
    """Write df to path atomically (write-then-rename) so a crash mid-write
    cannot leave a half-baked file the next reader would happily load.

    Refuses to clobber an existing file unless `overwrite=True` (SPECS §7);
    loaders that re-fetch the current year's spot tail will pass overwrite=True.
    """
    if path.exists() and not overwrite:
        raise WouldOverwriteError(
            f"{path} already exists; pass overwrite=True to clobber (SPECS §7)."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        df.to_parquet(tmp, index=False)
        tmp.replace(path)
    except Exception:
        # Atomic-write guarantee: never leave a half-baked .tmp behind on failure.
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
