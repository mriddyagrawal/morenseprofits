"""India VIX daily-OHLC loader — NSE's `/api/historicalOR/vixhistory`.

Source of truth for the Portfolio tab's regime-gate v2 signal
(PORTFOLIO_MEMOIR.md §3.7). India VIX is NSE's NIFTY-options-based
implied-vol index, published daily since 2008. The v1 regime gate
uses ``avg_single_name_realized_vol`` as a proxy (see
``src.analytics.regime``); v2 uses this loader's output directly.

API contract (operator-verified via Chrome dev tools 2026-06-04;
sample response keys reproduced in commit body):

    GET https://www.nseindia.com/api/historicalOR/vixhistory
    params: from=DD-MM-YYYY&to=DD-MM-YYYY   (DD-MM-YYYY, NOT ISO)
    max range per call: 365 days

    Response JSON:
        {"data": [{
            "EOD_TIMESTAMP":     "04-JUN-2025",
            "EOD_INDEX_NAME":    "INDIA VIX",
            "EOD_OPEN_INDEX_VAL": 16.555,
            "EOD_HIGH_INDEX_VAL": 17.06,
            "EOD_LOW_INDEX_VAL":  15.63,
            "EOD_CLOSE_INDEX_VAL": 15.75,
            "EOD_PREV_CLOSE":     16.555,
            "VIX_PTS_CHG": -0.81,    # ignored
            "VIX_PERC_CHG": -4.86,    # ignored
        }, ...]}

The Akamai bot-management cookies on www.nseindia.com require a
session-warming pattern: open a ``requests.Session``, hit the
referer URL once to populate cookies, then call the API. This
mirrors the standard NSE-Akamai workaround used elsewhere in the
ecosystem (jugaad-data's NSE wrappers do the same — our project's
existing ``bhavcopy_fo_loader`` hits ``nsearchives.nseindia.com``
which doesn't have the same Akamai layer, so it doesn't need
session-warming; the VIX endpoint does).

Cache: single parquet at ``data/cache/india_vix.parquet``. Sorted by
date ascending, no duplicates. Each call fetches only the
trading-day dates missing from the cache (incremental extend).
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Callable

import pandas as pd
import requests

from src.data import cache
from src.data.errors import OfflineCacheMiss
from src.data.offline import effective_offline
from src.data.telemetry import warn_fetch


# ============================================================
# NSE endpoint + session-warming constants
# ============================================================

_API_URL = "https://www.nseindia.com/api/historicalOR/vixhistory"
# Referer URL — the human-facing page that the API endpoint backs.
# Hitting this first sets the Akamai cookies the API requires.
_REFERER_URL = "https://www.nseindia.com/reports-indices-historical-vix"

# Headers proven to work with NSE's WAF + Akamai layer. Same UA
# string the operator's Chrome dev-tools capture used. Don't strip
# "to be tidy" — every one of these has been confirmed empirically
# necessary in some flow.
_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    ),
    "accept": "*/*",
    "accept-language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "referer": _REFERER_URL,
}

# NSE's `/api/historicalOR/vixhistory` rejects ranges > 365 days.
_MAX_CHUNK_DAYS = 365

# Politeness sleep between chunks. NSE's WAF will rate-limit aggressive
# bursts; 1.5s is well under any throttle the operator has observed
# empirically across the project.
_CHUNK_POLITENESS_SLEEP_S = 1.5

# Required response keys. The parser raises if any are missing —
# better a loud schema-drift error than silently writing NaN columns.
_REQUIRED_KEYS = {
    "EOD_TIMESTAMP",
    "EOD_OPEN_INDEX_VAL",
    "EOD_HIGH_INDEX_VAL",
    "EOD_LOW_INDEX_VAL",
    "EOD_CLOSE_INDEX_VAL",
    "EOD_PREV_CLOSE",
}


class IndiaVixSchemaError(ValueError):
    """The NSE response is missing expected keys. Indicates either a
    schema change upstream or a malformed response (e.g., HTML error
    page returned with 200). Loud failure mode — the parser refuses
    to write a half-baked cache."""


# ============================================================
# Schema
# ============================================================

# Canonical cache columns. Downstream consumers can rely on this
# tuple being stable; new fields land via additive columns.
INDIA_VIX_COLUMNS: tuple[str, ...] = (
    "date",
    "india_vix_open",
    "india_vix_high",
    "india_vix_low",
    "india_vix_close",
    "india_vix_prev_close",
)


def _empty_frame() -> pd.DataFrame:
    """Empty frame with the canonical schema — used by cold-cache /
    no-data paths so downstream consumers see a stable shape."""
    return pd.DataFrame({
        "date": pd.Series(dtype="datetime64[us]"),
        "india_vix_open": pd.Series(dtype="float64"),
        "india_vix_high": pd.Series(dtype="float64"),
        "india_vix_low": pd.Series(dtype="float64"),
        "india_vix_close": pd.Series(dtype="float64"),
        "india_vix_prev_close": pd.Series(dtype="float64"),
    })


# ============================================================
# Fetcher (NSE session + chunked download)
# ============================================================

def _open_session() -> requests.Session:
    """Open a Session and warm Akamai cookies by hitting the referer
    page first. NSE returns 401/403 from the API without these cookies
    on the session. Subsequent API calls within the same Session reuse
    them automatically.

    A 60s timeout covers slow NSE responses without hanging a sweep.
    """
    session = requests.Session()
    session.headers.update(_HEADERS)
    # Warm cookies via the referer page. Discard the body; we just
    # need the Set-Cookie side-effect.
    r = session.get(_REFERER_URL, timeout=60)
    r.raise_for_status()
    return session


def _fetch_chunk(
    session: requests.Session, from_date: date, to_date: date,
) -> list[dict]:
    """Single API call for a [from_date, to_date] window (≤ 365 days).
    Returns the raw ``data`` list. NSE expects ``DD-MM-YYYY``, not
    ISO."""
    params = {
        "from": from_date.strftime("%d-%m-%Y"),
        "to":   to_date.strftime("%d-%m-%Y"),
    }
    r = session.get(_API_URL, params=params, timeout=60)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, dict) or "data" not in payload:
        raise IndiaVixSchemaError(
            f"NSE response missing 'data' key for window "
            f"{from_date}..{to_date}; got top-level keys "
            f"{list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__}"
        )
    data = payload["data"]
    if not isinstance(data, list):
        raise IndiaVixSchemaError(
            f"NSE 'data' field is not a list for window "
            f"{from_date}..{to_date}; got {type(data).__name__}"
        )
    return data


def _chunks(from_date: date, to_date: date, *, chunk_days: int = _MAX_CHUNK_DAYS) -> list[tuple[date, date]]:
    """Split [from_date, to_date] into ≤ ``chunk_days`` windows. The
    365-day cap matches NSE's API max. Returned chunks are
    inclusive-inclusive and contiguous."""
    if from_date > to_date:
        return []
    out: list[tuple[date, date]] = []
    cursor = from_date
    while cursor <= to_date:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), to_date)
        out.append((cursor, chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return out


# ============================================================
# Parser (raw API response → canonical frame)
# ============================================================

def _parse_rows(rows: list[dict]) -> pd.DataFrame:
    """Parse a list of raw NSE row dicts into the canonical frame
    schema. Validates required keys; raises ``IndiaVixSchemaError``
    on drift. Skips/ignores the optional ``EOD_INDEX_NAME``,
    ``VIX_PTS_CHG``, ``VIX_PERC_CHG`` fields."""
    if not rows:
        return _empty_frame()
    sample_missing = _REQUIRED_KEYS - set(rows[0].keys())
    if sample_missing:
        raise IndiaVixSchemaError(
            f"NSE row missing required keys: {sorted(sample_missing)}; "
            f"got keys {sorted(rows[0].keys())}. Did the API schema "
            f"change?"
        )
    out = pd.DataFrame({
        "date": pd.to_datetime(
            [r["EOD_TIMESTAMP"] for r in rows], format="%d-%b-%Y",
        ).astype("datetime64[us]"),
        "india_vix_open": [float(r["EOD_OPEN_INDEX_VAL"]) for r in rows],
        "india_vix_high": [float(r["EOD_HIGH_INDEX_VAL"]) for r in rows],
        "india_vix_low":  [float(r["EOD_LOW_INDEX_VAL"]) for r in rows],
        "india_vix_close": [float(r["EOD_CLOSE_INDEX_VAL"]) for r in rows],
        "india_vix_prev_close": [float(r["EOD_PREV_CLOSE"]) for r in rows],
    })
    return out.sort_values("date").drop_duplicates(
        subset=["date"], keep="last",
    ).reset_index(drop=True)


# ============================================================
# Public entry point
# ============================================================

def load_india_vix(
    from_date: date,
    to_date: date,
    *,
    force_refresh: bool = False,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> pd.DataFrame:
    """Return India VIX daily OHLC between ``from_date`` and
    ``to_date`` inclusive.

    Cache-first: existing rows in ``data/cache/india_vix.parquet``
    are reused; only date ranges NOT covered by the cache are fetched
    from NSE. ``force_refresh=True`` re-fetches the entire requested
    range and merges into the cache.

    ``offline=True`` (or env ``MORENSE_OFFLINE=1``): cache miss on
    ANY part of the requested range raises ``OfflineCacheMiss``;
    never touches network. Takes precedence over ``force_refresh``.

    The cache parquet schema is canonical (``INDIA_VIX_COLUMNS``).
    Sorted by date ascending; no duplicates; sample-day pre-close
    rows (from NSE's pre-market preview) NOT in the cache — we
    only keep settled EOD rows.

    Cost/timing:
      - One ``load_india_vix`` call opens ONE ``requests.Session``;
        all chunks share it (cookies + connection pool reuse).
      - 365-day chunks per API call; ``time.sleep(1.5)`` between
        chunks (NSE WAF politeness).
      - A 3-year cold fetch = ~3 chunks × ~2s = ~10s wall-clock.
    """
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} > to_date {to_date}")
    offline = effective_offline(offline)

    # Read existing cache (if any) — defines what we DON'T need to fetch.
    path = cache.india_vix_path()
    cached = cache.read(path) if cache.exists(path) else _empty_frame()

    # Determine missing date ranges within [from_date, to_date].
    missing_ranges = _compute_missing_ranges(
        cached, from_date, to_date, force_refresh=force_refresh,
    )
    if not missing_ranges:
        return _filter_window(cached, from_date, to_date)
    if offline:
        raise OfflineCacheMiss(
            f"india_vix cache missing range(s) {missing_ranges} "
            f"and offline mode requested (offline=True or "
            f"MORENSE_OFFLINE=1)"
        )

    # Fetch missing ranges, accumulate, merge into cache.
    warn_fetch(
        "india_vix_loader",
        f"{from_date.isoformat()}..{to_date.isoformat()} "
        f"({len(missing_ranges)} missing range(s))",
    )
    session = _open_session()
    fetched_frames: list[pd.DataFrame] = []
    chunk_count = 0
    for (range_start, range_end) in missing_ranges:
        for (chunk_start, chunk_end) in _chunks(range_start, range_end):
            if chunk_count > 0:
                time.sleep(_CHUNK_POLITENESS_SLEEP_S)
            rows = _fetch_chunk(session, chunk_start, chunk_end)
            fetched_frames.append(_parse_rows(rows))
            chunk_count += 1

    if fetched_frames:
        merged = pd.concat([cached] + fetched_frames, ignore_index=True)
        merged = merged.sort_values("date").drop_duplicates(
            subset=["date"], keep="last",
        ).reset_index(drop=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        cache.write(path, merged, overwrite=True)
        cached = merged

    return _filter_window(cached, from_date, to_date)


# ============================================================
# Helpers — missing-range computation + window filter
# ============================================================

def _compute_missing_ranges(
    cached: pd.DataFrame,
    from_date: date,
    to_date: date,
    *,
    force_refresh: bool,
) -> list[tuple[date, date]]:
    """Return list of (start, end) inclusive ranges within
    [from_date, to_date] that are NOT covered by ``cached``.

    Approach (intentionally coarse): we don't try to fill per-day
    gaps inside the cached window — NSE bhavcopy days have natural
    holes (weekends, holidays) and treating those as "missing" would
    trigger pointless re-fetches. Instead, we extend at the EDGES:

      - From ``from_date`` to the day BEFORE the earliest cached date
        (if from_date is earlier than the cache starts).
      - From the day AFTER the latest cached date to ``to_date`` (if
        to_date is later than the cache ends).

    ``force_refresh=True`` returns the full [from_date, to_date]
    range as a single missing slot, bypassing cache."""
    if force_refresh:
        return [(from_date, to_date)]
    if cached.empty:
        return [(from_date, to_date)]
    cached_min = cached["date"].min().date()
    cached_max = cached["date"].max().date()
    ranges: list[tuple[date, date]] = []
    if from_date < cached_min:
        ranges.append(
            (from_date, min(cached_min - timedelta(days=1), to_date))
        )
    if to_date > cached_max:
        ranges.append(
            (max(cached_max + timedelta(days=1), from_date), to_date)
        )
    return ranges


def _filter_window(
    full: pd.DataFrame, from_date: date, to_date: date,
) -> pd.DataFrame:
    """Filter ``full`` to [from_date, to_date] inclusive, reset
    index. Stable schema even on empty input."""
    if full.empty:
        return _empty_frame()
    mask = (
        (full["date"] >= pd.Timestamp(from_date))
        & (full["date"] <= pd.Timestamp(to_date))
    )
    return full.loc[mask].reset_index(drop=True)
