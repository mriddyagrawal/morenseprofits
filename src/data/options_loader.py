"""Cached F&O option-price loader. One parquet per contract.

Per SPECS §2.2: cache layout
``data/cache/options/{SYMBOL}/{EXPIRY:yyyymmdd}/{STRIKE_INT}-{CE|PE}.parquet``.

Contract (frozen — change requires PLAN.md change-log entry):

1. **First fetch pulls the full contract lifetime** (~120 calendar days
   back from expiry, or up to ``today_fn()`` for not-yet-expired
   contracts). Narrow-window callers later hit cache without re-fetching.
2. **Closed expiries are immutable** on disk. ``force_refresh=True``
   re-fetches.
3. **Open expiries refetch** when cached's max date < ``min(today_fn(),
   expiry)``. Subset-checked: partial NSE response keeps cache + warns.
4. Returned frames sorted by date ASC with monotonicity assertion.
5. **MissingDataError on empty fetch** — indicates illegitimate strike,
   contract not yet listed, or zero-trade-zero-OI contract.

Notable upstream quirk: ``derivatives_df`` returns DATE at midnight
naive (unlike ``stock_df``, which returns 18:30 UTC — see chore(p1.4.prep)
commit for the discovery). No IST shift needed; ``_normalize`` asserts
"all dates at midnight" so a future jugaad change fails loud.
"""
from __future__ import annotations

import io
import time
import warnings
import zipfile
from datetime import date, datetime, timedelta
from typing import Callable, Literal

import pandas as pd
import requests

import functools

from src.data import cache
from src.data.errors import MissingDataError, OfflineCacheMiss, OptionsFormatError


# Per-process LRU cache size for the full contract-lifetime read.
# Wide sweep touches ~6,240 contracts (10 syms × 13 strikes × 2 types ×
# ~24 expiries). maxsize=2048 keeps a working-set per worker without
# exhausting memory: 8 workers × 2048 × ~50KB ≈ ~800 MB worst-case.
_LRU_MAXSIZE_OPTIONS = 2048
from src.data.offline import effective_offline
from src.data.telemetry import warn_fetch


# NSE lists stock options ~3 months ahead. 120 days covers every
# realistic listing window with margin.
_LIFETIME_DAYS_BACK = 120


# ============================================================
# Direct NSE derivatives fetcher — replaces jugaad's derivatives_df
# ============================================================
# Why we bypass jugaad for THIS endpoint specifically:
#   1. Jugaad creates a single module-level NSEHistory() and reuses
#      its Session across every call site in our codebase. When NSE
#      flags one session (rate-limit, WAF), ALL subsequent calls fail
#      with JSONDecodeError until the process restarts.
#   2. Jugaad's `derivatives_raw` uses ThreadPoolExecutor with workers=2
#      and chunks by date — so a single contract fetch can trigger
#      2 parallel API hits, which NSE's WAF reads as bot-like.
#   3. There's no retry logic for the "non-JSON response" case (which
#      happens when NSE returns its WAF challenge HTML).
#
# Our replacement: fresh requests.Session per fetch, single-shot
# cookie pre-fetch from /report-detail/eq_security, then ONE GET to
# /api/historicalOR/foCPV. If the response isn't JSON, we treat it
# as MissingDataError so the sweeper's skip-loop catches it instead
# of crashing. Same URL pattern jugaad uses; same JSON shape parsed.
#
# We KEEP jugaad as a dependency for stock_df + bhavcopy_fo_raw —
# those paths don't share this failure mode.

_NSE_BASE_URL = "https://www.nseindia.com"
_NSE_COOKIE_PATH = "/report-detail/eq_security"
_NSE_DERIVATIVES_PATH = "/api/historicalOR/foCPV"

# Headers mirror jugaad's exactly (matches modern Chrome on macOS).
# NSE's WAF is sensitive to header signatures.
_NSE_HEADERS = {
    "accept": "*/*",
    "accept-encoding": "deflate, br, zstd",
    "accept-language": "en-IN,en-US;q=0.9,en-GB;q=0.8,en;q=0.7",
    "cache-control": "no-cache",
    "pragma": "no-cache",
    "priority": "u=1, i",
    "referer": "https://www.nseindia.com/report-detail/eq_security",
    "sec-ch-ua": '"Not(A:Brand";v="8", "Chromium";v="144", "Google Chrome";v="144"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
    ),
}

# Column mapping: NSE's FH_* fields → jugaad's "DATE / EXPIRY / ..."
# headers, so _normalize() can rename them to SPECS §2.2 columns
# unchanged. Order matches jugaad's options_final_headers.
_NSE_TO_JUGAAD_COLS = {
    "FH_TIMESTAMP": "DATE",
    "FH_EXPIRY_DT": "EXPIRY",
    "FH_OPTION_TYPE": "OPTION TYPE",
    "FH_STRIKE_PRICE": "STRIKE PRICE",
    "FH_OPENING_PRICE": "OPEN",
    "FH_TRADE_HIGH_PRICE": "HIGH",
    "FH_TRADE_LOW_PRICE": "LOW",
    "FH_CLOSING_PRICE": "CLOSE",
    "FH_LAST_TRADED_PRICE": "LTP",
    "FH_SETTLE_PRICE": "SETTLE PRICE",
    "FH_TOT_TRADED_QTY": "TOTAL TRADED QUANTITY",
    "FH_MARKET_LOT": "MARKET LOT",
    "FH_TOT_TRADED_VAL": "PREMIUM VALUE",
    "FH_OPEN_INT": "OPEN INTEREST",
    "FH_CHANGE_IN_OI": "CHANGE IN OI",
    "FH_SYMBOL": "SYMBOL",
}


def _direct_derivatives_df(
    *,
    symbol: str,
    from_date: date,
    to_date: date,
    expiry_date: date,
    instrument_type: str,
    strike_price: float,
    option_type: str,
) -> pd.DataFrame:
    """Fetch one OPTSTK contract's EOD history directly from NSE.

    Drop-in replacement for ``jugaad_data.nse.derivatives_df`` that
    avoids the failure modes documented above. Returns a pandas
    DataFrame with the same column names jugaad would produce, so
    ``_normalize()`` can rename to SPECS §2.2 columns unchanged.

    Raises ``MissingDataError`` if NSE returns a non-JSON body
    (typically a WAF challenge page, rate-limit page, or 4xx with
    HTML error) — sweeper's skip-loop catches this and records the
    cell as a skip with the reason, instead of crashing the whole run.
    Network-level failures (ConnectionError, Timeout) propagate
    unchanged — those are operator-actionable retries, not
    structural-data failures.
    """
    # Politeness delay — NSE rate-limits aggressively when burst-hit.
    # ~500ms between contract fetches keeps us well under the WAF
    # threshold observed during the Phase-6 sweep. Per-fetch cost is
    # small (single-shot serial), so a small sleep here doesn't hurt
    # operator ergonomics.
    time.sleep(0.5)

    sess = requests.Session()
    sess.headers.update(_NSE_HEADERS)

    # Cookie pre-fetch: NSE sets session cookies on its report pages
    # which it then validates on the API. Without this we get a 401
    # or HTML challenge. Transient failures (ReadTimeout when NSE
    # rate-limits or briefly degrades) map to MissingDataError so the
    # sweep skip-loop continues — partial parquet beats no parquet.
    try:
        sess.get(
            _NSE_BASE_URL + _NSE_COOKIE_PATH,
            timeout=30,
            verify=True,
        )
    except (requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError) as e:
        raise MissingDataError(
            f"NSE cookie pre-fetch failed ({type(e).__name__}) for "
            f"{symbol} {expiry_date} {int(strike_price)}-{option_type}; "
            f"likely rate-limit or transient. Treating as missing for "
            f"sweep purposes."
        ) from e

    # Format params exactly as NSE expects (matches jugaad's format
    # specifiers): from/to in DD-MM-YYYY, expiry in DD-MMM-YYYY
    # uppercase, strike as "{:.2f}".
    params = {
        "symbol": symbol.upper(),
        "from": from_date.strftime("%d-%m-%Y"),
        "to": to_date.strftime("%d-%m-%Y"),
        "expiryDate": expiry_date.strftime("%d-%b-%Y").upper(),
        "instrumentType": instrument_type,
        "year": from_date.year,
    }
    if "OPT" in instrument_type:
        params["strikePrice"] = f"{strike_price:.2f}"
        params["optionType"] = option_type

    try:
        r = sess.get(
            _NSE_BASE_URL + _NSE_DERIVATIVES_PATH,
            params=params,
            timeout=30,
            verify=True,
        )
    except (requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError) as e:
        raise MissingDataError(
            f"NSE derivatives endpoint failed ({type(e).__name__}) for "
            f"{symbol} {expiry_date} {int(strike_price)}-{option_type}; "
            f"likely rate-limit or transient."
        ) from e

    # NSE returns 200 even on WAF challenge — the body distinguishes.
    # JSON content-type means real data; HTML means challenge / error.
    content_type = r.headers.get("content-type", "").lower()
    if "application/json" not in content_type:
        raise MissingDataError(
            f"NSE returned non-JSON ({content_type or 'no content-type'}; "
            f"status={r.status_code}) for {symbol} {expiry_date} "
            f"{int(strike_price)}-{option_type}. Likely WAF challenge or "
            f"rate-limit; treating as missing data for sweep purposes."
        )

    try:
        body = r.json()
    except ValueError as e:
        raise MissingDataError(
            f"NSE response was not parseable JSON for {symbol} "
            f"{expiry_date} {int(strike_price)}-{option_type}: {e}"
        ) from e

    rows = body.get("data", [])
    if not rows:
        # Empty array means NSE has no record for this contract —
        # may be a never-traded strike. The caller's "empty fetch
        # → MissingDataError" branch handles this case; for now we
        # return an empty DataFrame in jugaad's shape so the caller's
        # downstream logic stays unchanged.
        return pd.DataFrame(columns=list(_NSE_TO_JUGAAD_COLS.values()))

    df = pd.DataFrame(rows)
    # Some FH_* columns may be absent if NSE changed its schema; the
    # ones we need are pinned in _NSE_TO_JUGAAD_COLS. Select +
    # rename in one shot to match jugaad's options_final_headers.
    needed = list(_NSE_TO_JUGAAD_COLS.keys())
    missing_cols = [c for c in needed if c not in df.columns]
    if missing_cols:
        raise OptionsFormatError(
            f"NSE response missing expected columns "
            f"{missing_cols} for {symbol} {expiry_date} "
            f"{int(strike_price)}-{option_type}. Schema may have changed."
        )
    df = df[needed].rename(columns=_NSE_TO_JUGAAD_COLS)
    # Parse date strings into datetime64 to match jugaad's contract.
    # NSE returns DD-Mon-YYYY ("27-Mar-2024") — explicit %b format
    # prevents pandas from auto-inferring %B (full month name) and
    # crashing on the abbreviated form. Jugaad did this via
    # ut.np_date.apply; we do it once via vectorized to_datetime.
    df["DATE"] = pd.to_datetime(df["DATE"], format="%d-%b-%Y")
    df["EXPIRY"] = pd.to_datetime(df["EXPIRY"], format="%d-%b-%Y")
    return df


# Keep the old name as the call-site alias so the existing
# `derivatives_df(...)` call inside `_fetch_contract_lifetime` works
# unchanged after the import-statement rewire below.
def derivatives_df(symbol, from_date, to_date, expiry_date,
                   instrument_type, strike_price=None, option_type=None):
    """Module-private wrapper preserving the jugaad-compatible signature.
    Routes to ``_direct_derivatives_df`` (our replacement)."""
    return _direct_derivatives_df(
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        expiry_date=expiry_date,
        instrument_type=instrument_type,
        strike_price=strike_price,
        option_type=option_type,
    )


# jugaad column → SPECS §2.2 column
#
# ``turnover`` (NSE: ``FH_TOT_TRADED_VAL`` → "PREMIUM VALUE") is the
# day's total traded value for this contract. With ``volume`` (total
# quantity in shares per §2.3), it lets the pricing engine compute a
# daily VWAP — materially better than ``close`` for thin strikes where
# a single late print can be far from where the bulk of volume cleared.
#
# UNITS NOTE: NSE F&O bhavcopy historically reports FH_TOT_TRADED_VAL
# in lakhs of rupees (×10⁵). The pricing engine is responsible for
# applying any scale factor when computing VWAP; this _RENAMES step
# only carries the raw column through unchanged. A median-ratio
# assertion will live alongside the VWAP fill code (next commit) to
# bake in the units invariant and fail loudly if NSE ever shifts the
# scale convention. Legacy cached parquets DO NOT carry turnover;
# loading them post-this-change yields NaN in the column, which the
# next-commit VWAP fill function falls back from gracefully to
# ``close``.
_RENAMES = {
    "DATE": "date",
    "SYMBOL": "symbol",
    "EXPIRY": "expiry",
    "OPTION TYPE": "option_type",
    "STRIKE PRICE": "strike",
    "OPEN": "open",
    "HIGH": "high",
    "LOW": "low",
    "CLOSE": "close",
    "LTP": "ltp",
    "SETTLE PRICE": "settle_price",
    "MARKET LOT": "lot_size",
    "TOTAL TRADED QUANTITY": "volume",
    "PREMIUM VALUE": "turnover",
    "OPEN INTEREST": "oi",
    "CHANGE IN OI": "oi_change",
}
_SPEC_COLS = list(_RENAMES.values())


def _normalize(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    df = raw.rename(columns=_RENAMES)[_SPEC_COLS].copy()
    df["symbol"] = pd.array([symbol.upper()] * len(df), dtype="string")
    df["option_type"] = df["option_type"].astype("string")
    df["expiry"] = pd.to_datetime(df["expiry"]).astype("datetime64[us]")
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[us]")
    # Float columns are forgiving — pd.to_numeric coerces dirty values
    # (whitespace, strings) to NaN rather than crashing. NSE
    # occasionally returns settlement-only rows with empty trade-price
    # fields; tolerating NaN here keeps the contract usable.
    for col in ("strike", "open", "high", "low", "close", "ltp",
                "settle_price", "turnover"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    # Essential-row filter: rows missing lot_size or volume can't be
    # priced (no contract size = no P&L). NSE rarely emits such rows
    # — typically the last row of an expiry's lifetime when no actual
    # trading occurred — but the direct-fetch path surfaces them
    # (jugaad's old path silently swallowed via apply(np_int)).
    pre_n = len(df)
    df["lot_size"] = pd.to_numeric(df["lot_size"], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    df = df.dropna(subset=["lot_size", "volume", "close"]).copy()
    if len(df) < pre_n:
        warnings.warn(
            f"[options_loader] dropped {pre_n - len(df)} partial row(s) "
            f"from {symbol} (missing lot_size / volume / close — "
            f"typically NSE settlement-only rows with no trade data).",
            stacklevel=2,
        )
    df["lot_size"] = df["lot_size"].astype("int64")
    df["volume"] = df["volume"].astype("int64")
    df["oi"] = pd.to_numeric(df["oi"], errors="coerce").astype("Int64")
    df["oi_change"] = pd.to_numeric(df["oi_change"], errors="coerce").astype("Int64")

    # Verify every date is at midnight naive — derivatives_df should
    # return 00:00:00, unlike stock_df's 18:30 UTC. If a future jugaad
    # change starts returning offsets, fail loud rather than silently
    # mis-aligning entry/exit dates downstream. Plain `raise` instead of
    # `assert` so the check survives `python -O`.
    times = df["date"].dt.time
    midnight = pd.Timestamp("00:00:00").time()
    if not (times == midnight).all():
        non_midnight = df.loc[times != midnight, "date"].head().tolist()
        raise OptionsFormatError(
            f"derivatives_df DATE column has non-midnight times "
            f"(first few: {non_midnight}); a future jugaad change may have "
            f"altered the date convention — investigate before trusting prices"
        )

    df = df.sort_values("date").reset_index(drop=True)

    # Duplicate trading dates would silently corrupt entry/exit lookups —
    # NSE bhavcopies shouldn't produce them but guard anyway.
    dup_mask = df["date"].duplicated()
    if dup_mask.any():
        dups = sorted(set(df.loc[dup_mask, "date"].tolist()))
        raise OptionsFormatError(
            f"derivatives_df returned duplicate trading dates: "
            f"{[str(d) for d in dups[:3]]} (n={int(dup_mask.sum())})"
        )

    return df


def _fetch_contract_lifetime(
    symbol: str,
    expiry: date,
    strike: float,
    option_type: Literal["CE", "PE"],
    today_fn: Callable[[], date],
) -> pd.DataFrame:
    today = today_fn()
    start = expiry - timedelta(days=_LIFETIME_DAYS_BACK)
    end = min(expiry, today)
    warn_fetch(
        "options_loader",
        f"{symbol.upper()} {expiry} {int(strike)}-{option_type}",
    )
    # Symmetry with bhavcopy_fo_loader's wrap policy: "no data" failure
    # modes (404, 410, BadZipFile from HTML response) → MissingDataError;
    # transient network errors (403/5xx/ConnectionError) propagate raw.
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=r".*timezones available.*")
            raw = derivatives_df(
                symbol=symbol.upper(),
                from_date=start,
                to_date=end,
                expiry_date=expiry,
                instrument_type="OPTSTK",
                strike_price=strike,
                option_type=option_type,
            )
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in (404, 410):
            raise MissingDataError(
                f"no derivatives data for {symbol.upper()} {expiry} "
                f"{int(strike)}-{option_type}: HTTP {status}"
            ) from e
        raise  # 403/5xx/other → caller's problem (WAF or transient)
    except zipfile.BadZipFile as e:
        raise MissingDataError(
            f"no derivatives data for {symbol.upper()} {expiry} "
            f"{int(strike)}-{option_type}: BadZipFile — NSE likely "
            f"returned HTML for an unlisted contract"
        ) from e

    if raw.empty:
        raise MissingDataError(
            f"no derivatives data for {symbol.upper()} {expiry} "
            f"{int(strike)}-{option_type} between {start} and {end}; "
            f"either contract wasn't listed (check strike + expiry combo) "
            f"or it had zero trades AND zero open interest the whole time"
        )
    return _normalize(raw, symbol)


def _filter_window(df: pd.DataFrame, from_date: date, to_date: date) -> pd.DataFrame:
    mask = (df["date"] >= pd.Timestamp(from_date)) & (
        df["date"] <= pd.Timestamp(to_date)
    )
    return df.loc[mask].reset_index(drop=True)


@functools.lru_cache(maxsize=_LRU_MAXSIZE_OPTIONS)
def _load_full_contract_cached(
    symbol: str, expiry_iso: str, strike: float, option_type: str,
    today_iso: str, offline: bool,
) -> pd.DataFrame:
    """Per-worker memoization of the full contract lifetime read
    (post any open-expiry staleness refetch). ``load_option`` calls
    this then applies the ``[from_date, to_date]`` window filter.

    The 600-pair × 24-expiry × 3-strategy sweep redundantly re-reads
    the same contract parquet ~600× per (sym, exp, strike, type) tuple
    without this cache; with it, that drops to 1× per worker (cache
    fill) + 599× memory hits.

    Cache key includes ``today_iso`` so an open-expiry staleness
    refresh on a later day's run doesn't return stale data; ``offline``
    is keyed because it changes the branch behavior."""
    today = date.fromisoformat(today_iso)
    expiry = date.fromisoformat(expiry_iso)
    today_fn = lambda: today
    return _load_full_contract_impl(
        symbol, expiry, strike, option_type, today_fn, offline,
    )


def _load_full_contract_impl(
    symbol: str, expiry: date, strike: float, option_type: str,
    today_fn: Callable[[], date], offline: bool,
    *, force_refresh: bool = False,
) -> pd.DataFrame:
    """Underlying cache-then-fetch + open-expiry staleness logic. Kept
    separate from the LRU wrapper so ``force_refresh=True`` and tests
    can call it directly without polluting the cache."""
    path = cache.option_path(symbol, expiry, strike, option_type)
    today = today_fn()
    is_closed = expiry < today
    has_cache = cache.exists(path) and not force_refresh

    if has_cache:
        cached = cache.read(path)
        if is_closed:
            return cached
        max_cached = (
            cached["date"].max().date() if not cached.empty else None
        )
        deadline = min(today, expiry)
        if max_cached is not None and max_cached >= deadline:
            return cached
        if offline:
            return cached
        try:
            fresh = _fetch_contract_lifetime(
                symbol, expiry, strike, option_type, today_fn
            )
        except MissingDataError:
            return cached
        cached_dates = set(cached["date"].tolist())
        fresh_dates = set(fresh["date"].tolist())
        if not cached_dates.issubset(fresh_dates):
            missing = sorted(cached_dates - fresh_dates)
            warnings.warn(
                f"partial NSE response for {symbol.upper()} {expiry} "
                f"{int(strike)}-{option_type}: fresh fetch missing "
                f"{len(missing)} dates that exist in cache "
                f"(first 3: {[str(d) for d in missing[:3]]}). Keeping cache.",
                stacklevel=3,
            )
            return cached
        cache.write(path, fresh, overwrite=True)
        return fresh

    # Cache miss
    if offline:
        raise OfflineCacheMiss(
            f"option {symbol.upper()} {expiry} {int(strike)}-{option_type} "
            f"not in cache and offline mode requested "
            f"(offline=True or MORENSE_OFFLINE=1)"
        )
    fresh = _fetch_contract_lifetime(
        symbol, expiry, strike, option_type, today_fn
    )
    # overwrite=True is required for multi-worker safety (see commit
    # 8419a8c). cache.write's PID-unique tmp ensures atomic, race-safe
    # rename even when two workers fetch the same missing contract.
    cache.write(path, fresh, overwrite=True)
    return fresh


def load_option(
    symbol: str,
    expiry: date,
    strike: float,
    option_type: Literal["CE", "PE"],
    from_date: date,
    to_date: date,
    *,
    force_refresh: bool = False,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> pd.DataFrame:
    """Return SPECS §2.2-shaped frame for the option contract's
    [from_date, to_date] inclusive window.

    Args:
        symbol: underlying stock symbol (case-insensitive — uppercased).
        expiry: contract expiry as ``datetime.date`` (NOT ``datetime`` —
            rejected loud to avoid tz-ambiguity, same as bhavcopy_fo_path).
        strike: whole-rupee strike (enforced by ``cache.option_path``).
        option_type: ``"CE"`` or ``"PE"``.
        from_date, to_date: inclusive trading-date window to return.
        force_refresh: ignore cache and re-fetch.
        today_fn: for test-time-freezing (default: ``date.today``).

    Raises:
        ValueError: bad date inputs / bad option_type.
        TypeError: ``expiry`` is a ``datetime``.
        MissingDataError: contract has no data on NSE.
        cache.StrikeNotIntegerError: ``strike`` has a fractional part.

    Hot-path memoization: under ``force_refresh=False`` (the default),
    the full-contract read goes through ``_load_full_contract_cached``;
    repeated calls within a worker for the same (sym, exp, strike, type)
    skip disk entirely after the first.
    """
    if isinstance(expiry, datetime):
        raise TypeError(
            f"load_option expects datetime.date for `expiry`, got datetime: "
            f"{expiry!r}. Call .date() on it first — a tz-aware datetime "
            f"would be ambiguous about which expiry date it names."
        )
    if from_date > to_date:
        raise ValueError(f"from_date {from_date} > to_date {to_date}")
    if option_type not in ("CE", "PE"):
        raise ValueError(f"option_type must be 'CE' or 'PE', got {option_type!r}")

    offline_eff = effective_offline(offline)
    if force_refresh:
        full = _load_full_contract_impl(
            symbol, expiry, strike, option_type, today_fn, offline_eff,
            force_refresh=True,
        )
    else:
        today_iso = today_fn().isoformat()
        full = _load_full_contract_cached(
            symbol.upper(), expiry.isoformat(), float(strike), option_type,
            today_iso, offline_eff,
        )
    return _filter_window(full, from_date, to_date)
