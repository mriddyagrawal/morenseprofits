"""Lookup helpers over the unified ``data/cache/lot_sizes.parquet``.

The unified cache is built by ``scripts/build_lot_size_parquet.py``
(P0.2) from BOTH committed sidecars (regime B) AND the sibling
bhavcopy lot-size parquets (regime C). See MIGRATION.md
§Architectural target + §Cross-source lot-size policy.

Public API:

  ``lot_size_lookup(symbol, expiry) -> int | None``
      Returns the lot_size for ``(symbol, expiry-month)`` or None if
      the pair is excluded (cross-source mismatch) / the cache
      doesn't exist yet (prefetch hasn't run).

  ``expiries_for_symbols(symbols, from_date, to_date) -> list[date]``
      Sorted unique list of OPTSTK expiry dates for the given
      symbol set in the inclusive date range. Reads from
      ``expiry_date`` column added 2026-06-04 — replaces the
      per-symbol bhavcopy scan that ``expiry_calendar.monthly_expiries``
      does. Per-pair lot-size exclusions automatically propagate
      (excluded pairs are absent from the parquet → never iterated
      by the sweep).

Consumers (the bhavcopy-to-contract transform in P1.3; the sweep's
expiry-list builder; future MCP tools that want operator-facing
lot_size data) treat None / empty-list as a structural skip signal —
the cell is unbacktestable per the per-pair-exclude policy.

Cache-read is module-level memoized via lru_cache(maxsize=1) — the
parquet is read ONCE per process and held for the worker's lifetime.
Sweep workers fork after prefetch runs, so they see a fresh-built
cache at process start; mid-process invalidation isn't a use case.
For the prefetch→sweep→drilldown handoff, each step is a fresh
process invocation, so each gets its own fresh read.
"""
from __future__ import annotations

import functools
from collections.abc import Iterable
from datetime import date

import pandas as pd

from src.data import cache


@functools.lru_cache(maxsize=1)
def _load_lot_sizes_parquet() -> pd.DataFrame:
    """Memoized read of the unified lot-sizes cache.

    Returns an empty DataFrame (correct columns + dtypes) when the
    parquet doesn't exist on disk. Downstream lookups against the
    empty frame return None for every query — equivalent to "every
    pair is unbacktestable until prefetch runs," which is the
    correct semantics for a fresh clone.
    """
    path = cache.lot_sizes_path()
    if not path.exists():
        return pd.DataFrame({
            "symbol": pd.Series(dtype="string"),
            "year": pd.Series(dtype="int64"),
            "month": pd.Series(dtype="int64"),
            "lot_size": pd.Series(dtype="int64"),
            "source": pd.Series(dtype="string"),
            "expiry_date": pd.Series(dtype="datetime64[us]"),
        })
    return pd.read_parquet(path)


def lot_size_lookup(symbol: str, expiry: date) -> int | None:
    """Look up ``lot_size`` for the given ``(symbol, expiry-month)``
    in the unified cache.

    Returns:
        int: the lot_size if the pair exists in the cache.
        None: the pair is excluded (cross-source mismatch) OR the
              cache parquet doesn't exist on disk (prefetch hasn't
              run).

    Year+month granularity matches the cache schema (sidecar's
    ``StockNm`` regex provides only year+month precision; bhavcopy
    sibling has exact dates which we collapse to year+month at build
    time). Lot_sizes are stable per (symbol, expiry-month) for the
    set of contracts NOT excluded by the cross-source check — so the
    coarser key is correct.
    """
    df = _load_lot_sizes_parquet()
    if df.empty:
        return None
    sym = symbol.upper()
    yr = expiry.year
    mo = expiry.month
    match = df[
        (df["symbol"] == sym)
        & (df["year"] == yr)
        & (df["month"] == mo)
    ]
    if len(match) == 0:
        return None
    return int(match.iloc[0]["lot_size"])


def expiries_for_symbols(
    symbols: Iterable[str], from_date: date, to_date: date,
) -> list[date]:
    """Sorted unique list of OPTSTK expiry dates for ``symbols`` whose
    ``expiry_date`` falls in ``[from_date, to_date]`` inclusive.

    Reads from the ``expiry_date`` column on
    ``data/cache/lot_sizes.parquet``. (sym, expiry-month) pairs that
    were excluded by lot-size mismatch during the build are absent from
    the parquet, so the returned list automatically respects exclusions
    — no `OfflineCacheMiss` skip rows from sweeping an excluded pair.

    Cold-cache (parquet missing / empty) returns ``[]``. The sweep
    treats this as "no work to do" and prints a no-op message; the
    operator runs the prefetch (which builds the parquet) and re-runs.

    Symbol matching is case-insensitive on the input list (stored
    parquet symbols are always upper).
    """
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} > to_date {to_date}")
    df = _load_lot_sizes_parquet()
    if df.empty:
        return []
    sym_set = {s.upper() for s in symbols}
    mask = (
        df["symbol"].isin(sym_set)
        & (df["expiry_date"] >= pd.Timestamp(from_date))
        & (df["expiry_date"] <= pd.Timestamp(to_date))
    )
    if not mask.any():
        return []
    out = df.loc[mask, "expiry_date"].dt.date.unique().tolist()
    return sorted(out)


def reset_lookup_cache() -> None:
    """Test-only: drop the memoized parquet read so monkeypatched
    cache directories take effect on subsequent lookups within the
    same process.

    Production code never calls this — the lookup cache is one-shot
    per process by design (see module docstring).
    """
    _load_lot_sizes_parquet.cache_clear()
