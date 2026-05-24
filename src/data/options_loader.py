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
import warnings
import zipfile
from datetime import date, datetime, timedelta
from typing import Callable, Literal

import pandas as pd
import requests

from jugaad_data.nse import derivatives_df

from src.data import cache
from src.data.errors import MissingDataError, OfflineCacheMiss, OptionsFormatError
from src.data.offline import effective_offline
from src.data.telemetry import warn_fetch


# NSE lists stock options ~3 months ahead. 120 days covers every
# realistic listing window with margin.
_LIFETIME_DAYS_BACK = 120


# jugaad column → SPECS §2.2 column
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
    for col in ("strike", "open", "high", "low", "close", "ltp", "settle_price"):
        df[col] = df[col].astype("float64")
    df["lot_size"] = df["lot_size"].astype("int64")
    df["volume"] = df["volume"].astype("int64")
    df["oi"] = df["oi"].astype("Int64")
    df["oi_change"] = df["oi_change"].astype("Int64")

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

    offline = effective_offline(offline)
    path = cache.option_path(symbol, expiry, strike, option_type)
    today = today_fn()
    is_closed = expiry < today
    has_cache = cache.exists(path)

    if has_cache and not force_refresh:
        cached = cache.read(path)
        if is_closed:
            return _filter_window(cached, from_date, to_date)
        # Open expiry: refetch only when cache is stale relative to today
        max_cached = (
            cached["date"].max().date() if not cached.empty else None
        )
        deadline = min(today, expiry)
        if max_cached is not None and max_cached >= deadline:
            return _filter_window(cached, from_date, to_date)
        # Want to refetch — but offline says no network. Return stale cache
        # rather than raising; for an open expiry that just means "we're
        # showing yesterday's prices, not today's", which is fine.
        if offline:
            return _filter_window(cached, from_date, to_date)
        try:
            fresh = _fetch_contract_lifetime(
                symbol, expiry, strike, option_type, today_fn
            )
        except MissingDataError:
            # Fresh fetch came back empty (contract de-listed?). Keep cache.
            return _filter_window(cached, from_date, to_date)
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
            return _filter_window(cached, from_date, to_date)
        cache.write(path, fresh, overwrite=True)
        return _filter_window(fresh, from_date, to_date)

    # Cache miss OR force_refresh
    if offline:
        raise OfflineCacheMiss(
            f"option {symbol.upper()} {expiry} {int(strike)}-{option_type} "
            f"not in cache and offline mode requested "
            f"(offline=True or MORENSE_OFFLINE=1)"
        )
    fresh = _fetch_contract_lifetime(
        symbol, expiry, strike, option_type, today_fn
    )
    cache.write(path, fresh, overwrite=force_refresh)
    return _filter_window(fresh, from_date, to_date)
