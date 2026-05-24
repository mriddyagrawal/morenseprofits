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


def _ensure_root() -> Path:
    """Create cache root if missing and write/verify the version sentinel."""
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
    return CACHE_DIR


def spot_path(symbol: str, year: int) -> Path:
    return _ensure_root() / "spot" / symbol.upper() / f"{year}.parquet"


def option_path(symbol: str, expiry: date, strike: float, option_type: Literal["CE", "PE"]) -> Path:
    strike_int = int(round(strike))
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


def exists(path: Path) -> bool:
    return path.is_file()


def read(path: Path) -> pd.DataFrame:
    return pd.read_parquet(path)


def write(path: Path, df: pd.DataFrame) -> None:
    """Write df to path atomically (write-then-rename) so a crash mid-write
    cannot leave a half-baked file the next reader would happily load."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)
