"""Per-symbol monthly-expiry calendar built from cached F&O bhavcopies.

The entire reason this module exists is to escape ``jugaad.expiry_dates``'s
`list(set(dts))` non-determinism (PLAN.md 2026-05-24 change-log).

**Determinism contract** (SPECS §2.3): two calls to ``monthly_expiries``
with identical inputs return byte-identical sorted lists. Tests pin this
as the load-bearing first assertion.

**Sampling strategy** (SPECS §2.3 step-by-step):
  1. For each calendar month overlapping ``[from_date, to_date]``, try
     days 1..7 in order and take the first that loads without
     ``MissingDataError``. NSE lists ~3 forward months in any bhavcopy,
     so one sample per month is sufficient.
  2. Filter the sample for ``instrument == "OPTSTK"`` and the requested
     symbol; collect unique expiry values.
  3. Persist as ``(symbol, expiry_date, month_anchor)`` rows in
     ``data/cache/expiries/{SYMBOL}.parquet``. Subsequent calls only
     sample months whose ``month_anchor`` is not already cached.
  4. Return ``sorted({expiry_date for any row whose expiry_date ∈ window})``.

**Known v1 limitations** (flagged by the reviewer, accepted as cheap):

- **Empty-month cache miss**: a month whose sample contains zero
  rows for ``symbol`` (e.g. delisted/pre-listing symbol; pathological
  test fixture) writes no rows, so ``cached_anchors`` won't include it,
  so it'll be re-sampled on every future call. Harmless for our
  blue-chip universe but worth knowing for Phase 7 incremental cache.
- **All-7-days-non-trading**: returns ``[]`` for that month. NSE has
  never had 7 consecutive non-trading days, but a future force-majeure
  closure would silently miss expiries — we ``warnings.warn`` so it
  surfaces, but the calendar still proceeds.
"""
from __future__ import annotations

import warnings
from datetime import date
from typing import Iterable

import pandas as pd

from src.data import bhavcopy_fo_loader, cache
from src.data.errors import MissingDataError
from src.data.offline import effective_offline


_CANDIDATE_SAMPLE_DAYS: tuple[int, ...] = tuple(range(1, 8))  # days 1..7


def _month_anchors(from_date: date, to_date: date) -> list[date]:
    """Sorted list of first-of-month dates spanning [from_date, to_date]
    inclusive (by calendar month)."""
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} > to_date {to_date}")
    out: list[date] = []
    y, m = from_date.year, from_date.month
    while (y, m) <= (to_date.year, to_date.month):
        out.append(date(y, m, 1))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _sample_expiries_for_month(
    symbol: str, anchor: date, *, offline: bool = False
) -> list[date]:
    """Find a usable bhavcopy in the month, return that symbol's OPTSTK
    expiry list. Empty list if no usable day in days 1..7 (very rare —
    NSE has not had a 7-day continuous closure on record).

    Passes `offline` through to the underlying loader; OfflineCacheMiss
    (distinct from MissingDataError) propagates so the caller sees
    "offline + nothing cached" loudly rather than as a quiet skip."""
    symbol = symbol.upper()
    bc: pd.DataFrame | None = None
    for day in _CANDIDATE_SAMPLE_DAYS:
        candidate = date(anchor.year, anchor.month, day)
        try:
            bc = bhavcopy_fo_loader.load_bhavcopy_fo(candidate, offline=offline)
            break
        except MissingDataError:
            # OfflineCacheMiss is NOT a MissingDataError — it propagates.
            continue
    if bc is None:
        warnings.warn(
            f"no usable F&O bhavcopy in days 1..7 of {anchor:%Y-%m} for "
            f"symbol={symbol}; this month contributes no expiries. NSE has "
            f"never had 7 consecutive non-trading days — investigate if "
            f"you see this in production.",
            stacklevel=3,
        )
        return []
    mask = (bc["instrument"] == "OPTSTK") & (bc["symbol"] == symbol)
    seen = bc.loc[mask, "expiry"].dt.date.unique().tolist()
    return sorted(seen)


def _empty_calendar_frame() -> pd.DataFrame:
    """Empty frame in the SPECS §2.3 shape so concat/dedupe paths don't
    have to special-case the cold-cache case."""
    return pd.DataFrame({
        "symbol": pd.array([], dtype="string"),
        "expiry_date": pd.Series([], dtype="datetime64[us]"),
        "month_anchor": pd.Series([], dtype="datetime64[us]"),
    })


def _read_cached(symbol: str) -> pd.DataFrame:
    path = cache.expiry_path(symbol)
    if cache.exists(path):
        return cache.read(path)
    return _empty_calendar_frame()


def _build_new_rows(
    symbol: str, anchors: Iterable[date], *, offline: bool = False
) -> pd.DataFrame:
    rows = []
    for anchor in anchors:
        for expiry in _sample_expiries_for_month(symbol, anchor, offline=offline):
            rows.append({
                "symbol": symbol.upper(),
                "expiry_date": pd.Timestamp(expiry),
                "month_anchor": pd.Timestamp(anchor),
            })
    if not rows:
        return _empty_calendar_frame()
    df = pd.DataFrame(rows)
    df["symbol"] = df["symbol"].astype("string")
    df["expiry_date"] = df["expiry_date"].astype("datetime64[us]")
    df["month_anchor"] = df["month_anchor"].astype("datetime64[us]")
    return df


def monthly_expiries(
    symbol: str, from_date: date, to_date: date, *, offline: bool = False
) -> list[date]:
    """Sorted unique list of OPTSTK expiry dates for ``symbol`` whose
    ``expiry_date`` falls in ``[from_date, to_date]`` inclusive.

    `offline=True` (or env MORENSE_OFFLINE=1): cache miss on any sampled
    bhavcopy raises OfflineCacheMiss; never touches network.

    See module docstring for the sampling strategy and SPECS §2.3 for the
    cache shape. Determinism is contract — bytes-identical across calls.
    """
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} > to_date {to_date}")
    offline = effective_offline(offline)
    symbol_u = symbol.upper()
    needed_anchors = _month_anchors(from_date, to_date)
    cached = _read_cached(symbol_u)
    cached_anchors = (
        set(cached["month_anchor"].dt.date.unique().tolist())
        if not cached.empty
        else set()
    )
    missing_anchors = [a for a in needed_anchors if a not in cached_anchors]

    if missing_anchors:
        new_rows = _build_new_rows(symbol_u, missing_anchors, offline=offline)
        if not new_rows.empty:
            combined = pd.concat([cached, new_rows], ignore_index=True)
            # Dedupe on the full key — same expiry observed in multiple
            # month samples is one row per (anchor, expiry) by design.
            combined = combined.drop_duplicates(
                subset=["symbol", "expiry_date", "month_anchor"]
            )
            # Sort before persisting so a future hand-inspection is sane
            # AND so the file bytes are stable across regenerations.
            combined = combined.sort_values(
                ["month_anchor", "expiry_date"]
            ).reset_index(drop=True)
            cache.write(cache.expiry_path(symbol_u), combined, overwrite=True)
            cached = combined

    if cached.empty:
        return []

    in_window = cached[
        (cached["expiry_date"] >= pd.Timestamp(from_date))
        & (cached["expiry_date"] <= pd.Timestamp(to_date))
    ]
    return sorted(in_window["expiry_date"].dt.date.unique().tolist())
