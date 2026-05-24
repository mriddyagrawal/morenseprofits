"""F&O bhavcopy loader — cached fetch + parse, dual-format (legacy + UDiff).

See SPECS §2.4 for the canonical schema and the dual-endpoint dispatch
rationale. The architecture splits cleanly:

  ``_fetch_raw(trade_date) -> (raw_text, format_tag)`` — dispatches by
  ``trade_date`` against ``NSEArchives.udiff_start_date`` (currently
  2024-07-08) and fetches via the appropriate channel. Returns the raw
  CSV text and a format tag (``"legacy"`` or ``"udiff"``).

  ``parse_legacy(raw, trade_date)`` and ``parse_udiff(raw, trade_date)``
  — normalize each upstream schema to the SPECS §2.4 shape. Public so
  tests can drive them directly from recorded fixtures, no network mock
  needed.

  ``load_bhavcopy_fo(trade_date)`` — public entry point with parquet
  cache.

The loader STAMPS ``trade_date`` from the requested date (not from
upstream's TIMESTAMP/TradDt) and asserts the upstream value matches —
catches a mis-dispatched fetch loudly (e.g. server returns the wrong
day, or jugaad's date arithmetic drifts).
"""
from __future__ import annotations

import io
import warnings
import zipfile
from datetime import date
from typing import Literal

import pandas as pd
import requests

from jugaad_data.nse.archives import NSEArchives

from src.data import cache
from src.data.errors import BhavcopyFormatError, MissingDataError


# Match the discovered post-Jul-8 archive URL pattern (verified live on 4
# dates in chore(p1.3.1.discovery)). The NSEDailyReports API exposes UDiff
# bhavcopies only for today/yesterday; historical requires direct URL.
_UDIFF_URL_TPL = (
    "https://nsearchives.nseindia.com/content/fo/"
    "BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
)

# NSE's WAF returns 403 without a browser User-Agent. Same string the
# capture script proved works. Don't strip "to be tidy".
_NSE_HEADERS = {
    "user-agent": (
        "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/134.0.6998.166 Safari/537.36"
    ),
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Required-column markers used for format sniffing. We pick a handful of
# columns unique to each schema rather than checking the full header so a
# benign upstream column-addition (NSE has been known to do this) doesn't
# falsely flip us into BhavcopyFormatError.
_LEGACY_MARKERS = {"INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR", "OPTION_TYP", "TIMESTAMP"}
_UDIFF_MARKERS = {"TradDt", "FinInstrmTp", "TckrSymb", "FininstrmActlXpryDt", "StrkPric", "OptnTp"}

# UDiff instrument codes map 1:1 to legacy. SPECS §2.4 normalizes to legacy
# names so downstream consumers don't care about format provenance.
_UDIFF_TO_LEGACY_INSTR = {"STO": "OPTSTK", "IDO": "OPTIDX", "STF": "FUTSTK", "IDF": "FUTIDX"}

FormatTag = Literal["legacy", "udiff"]


# ============================================================
# Fetcher
# ============================================================

def _udiff_start_date() -> date:
    """Source of truth for the legacy/UDiff cutover. Imported from jugaad so
    we stay in lockstep if upstream ever changes it."""
    return NSEArchives.udiff_start_date


# Status codes that mean "this URL has no content for this date"
# (cleanly wrapped as MissingDataError). Everything else propagates:
#  - 403 → WAF blocked (likely stale browser UA); operator must fix
#  - 5xx → NSE flaking transiently; caller decides retry policy
#  - other 4xx → genuine bad request, indicates a code bug
_NO_DATA_STATUSES = frozenset({404, 410})


def _fetch_legacy(trade_date: date) -> str:
    """Returns CSV text. Raises MissingDataError when NSE has no bhavcopy
    for this date (weekend or NSE holiday → NSE serves HTML → jugaad's
    @unzip decorator raises BadZipFile). Network-level errors
    (RequestException) propagate — those are retryable, not 'no data'.

    **Wrap-precision limitation**: jugaad's `@unzip` decorator collapses
    every non-ZIP response into BadZipFile, so we can't distinguish a
    403 (WAF block) or 5xx (transient flake) from the no-bhavcopy case
    on the legacy path. In practice the legacy archive endpoint has been
    stable for years and almost only fails with HTML for non-trading
    days, so this rarely bites — but if a legacy calendar build returns
    empty after a recent NSE WAF change, this is the first place to
    look. The UDiff path (which we control end-to-end) gets the precise
    403/5xx propagation."""
    try:
        return NSEArchives().bhavcopy_fo_raw(trade_date)
    except zipfile.BadZipFile as e:
        raise MissingDataError(
            f"no legacy F&O bhavcopy for {trade_date} (BadZipFile — typically "
            f"a non-trading day; NSE returns HTML instead of the ZIP)"
        ) from e


def _fetch_udiff(trade_date: date) -> str:
    """Returns CSV text. MissingDataError ONLY on 404/410 (no content for
    this date) or BadZipFile (200 with HTML body — NSE does both in the
    wild for missing dates). HTTP 403 (WAF block) and 5xx (transient
    flake) propagate unchanged so the operator sees them clearly — a
    calendar build silently skipping every date because the UA went
    stale would be the worst kind of quiet failure."""
    url = _UDIFF_URL_TPL.format(ymd=trade_date.strftime("%Y%m%d"))
    try:
        r = requests.get(url, headers=_NSE_HEADERS, timeout=60)
        r.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as fp:
                return fp.read().decode("utf-8")
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        if status in _NO_DATA_STATUSES:
            raise MissingDataError(
                f"no UDiff F&O bhavcopy for {trade_date} (HTTP {status})"
            ) from e
        raise  # 403 / 5xx / other 4xx propagate
    except zipfile.BadZipFile as e:
        raise MissingDataError(
            f"no UDiff F&O bhavcopy for {trade_date} (BadZipFile — NSE "
            f"likely returned HTML for a non-trading day)"
        ) from e


def _fetch_raw(trade_date: date) -> tuple[str, FormatTag]:
    if trade_date < _udiff_start_date():
        return _fetch_legacy(trade_date), "legacy"
    return _fetch_udiff(trade_date), "udiff"


# ============================================================
# Parsers (public — tests drive these directly from recorded fixtures)
# ============================================================

def _normalize_option_type(s: pd.Series) -> pd.Series:
    """Legacy uses 'XX' for futures, UDiff uses blank. Standardize to
    <NA> in a StringDtype column for both."""
    return s.where(s.isin(["CE", "PE"]), pd.NA).astype("string")


def _strike_nan_for_futures(strike: pd.Series, instrument: pd.Series) -> pd.Series:
    """Futures rows have STRIKE_PR=0 in legacy and 0 (or NaN) in UDiff.
    SPECS §2.4 says NaN for futures — option-type-aware nulling."""
    is_option = instrument.isin(["OPTSTK", "OPTIDX"])
    return pd.to_numeric(strike, errors="coerce").where(is_option, pd.NA).astype("float64")


def _stamp_trade_date(n: int, trade_date: date) -> pd.Series:
    """Build a length-n datetime64[us] series at trade_date midnight."""
    ts = pd.Timestamp(trade_date)  # midnight, naive
    return pd.Series([ts] * n).astype("datetime64[us]")


def parse_legacy(raw: str, trade_date: date) -> pd.DataFrame:
    """Pre-Jul-8-2024 BHAVDATA-FULL CSV → SPECS §2.4 frame."""
    df = pd.read_csv(io.StringIO(raw))
    # Trailing-comma rows produce an "Unnamed: 15" phantom column — drop.
    df = df.loc[:, ~df.columns.astype(str).str.startswith("Unnamed")]
    df.columns = df.columns.str.strip()
    if not _LEGACY_MARKERS.issubset(df.columns):
        raise BhavcopyFormatError(
            f"legacy header missing required cols: "
            f"{sorted(_LEGACY_MARKERS - set(df.columns))}; got {list(df.columns)}"
        )

    # Verify upstream date matches request before doing any heavy work.
    upstream = pd.to_datetime(df["TIMESTAMP"], format="%d-%b-%Y").dt.date.unique()
    if not (len(upstream) == 1 and upstream[0] == trade_date):
        raise BhavcopyFormatError(
            f"legacy TIMESTAMP {list(upstream)} != requested trade_date {trade_date}"
        )

    instrument = df["INSTRUMENT"].astype("string")
    out = pd.DataFrame({
        "instrument": instrument,
        "symbol": df["SYMBOL"].astype("string"),
        "expiry": pd.to_datetime(df["EXPIRY_DT"], format="%d-%b-%Y").astype("datetime64[us]"),
        "strike": _strike_nan_for_futures(df["STRIKE_PR"], instrument),
        "option_type": _normalize_option_type(df["OPTION_TYP"]),
        "open": df["OPEN"].astype("float64"),
        "high": df["HIGH"].astype("float64"),
        "low": df["LOW"].astype("float64"),
        "close": df["CLOSE"].astype("float64"),
        "settle_price": df["SETTLE_PR"].astype("float64"),
        "contracts": df["CONTRACTS"].fillna(0).astype("int64"),
        "oi": df["OPEN_INT"].astype("Int64"),
        "oi_change": df["CHG_IN_OI"].astype("Int64"),
    })
    out["trade_date"] = _stamp_trade_date(len(out), trade_date)
    return out


def parse_udiff(raw: str, trade_date: date) -> pd.DataFrame:
    """≥Jul-8-2024 UDiff CSV → SPECS §2.4 frame.

    Uses `FininstrmActlXpryDt` (not `XpryDt`) as the canonical `expiry`
    per SPECS §2.4 — that's the actually-settled date, which is what a
    backtest's exit price ties to. Emits a warning when the two diverge
    (holiday-shifted Thursdays) so the divergence surfaces visibly.
    """
    df = pd.read_csv(io.StringIO(raw))
    df.columns = df.columns.str.strip()
    if not _UDIFF_MARKERS.issubset(df.columns):
        raise BhavcopyFormatError(
            f"udiff header missing required cols: "
            f"{sorted(_UDIFF_MARKERS - set(df.columns))}; got {list(df.columns)}"
        )

    upstream = pd.to_datetime(df["TradDt"]).dt.date.unique()
    if not (len(upstream) == 1 and upstream[0] == trade_date):
        raise BhavcopyFormatError(
            f"udiff TradDt {list(upstream)} != requested trade_date {trade_date}"
        )

    # Surface holiday-shifted expiries.
    diverged_n = int((df["XpryDt"] != df["FininstrmActlXpryDt"]).sum())
    if diverged_n:
        warnings.warn(
            f"udiff {trade_date}: {diverged_n} rows have XpryDt != "
            f"FininstrmActlXpryDt (likely holiday-shifted expiries); "
            f"using FininstrmActlXpryDt per SPECS §2.4.",
            stacklevel=3,
        )

    instrument = df["FinInstrmTp"].map(_UDIFF_TO_LEGACY_INSTR)
    if instrument.isna().any():
        unknown = sorted(set(df.loc[instrument.isna(), "FinInstrmTp"].astype(str)))
        raise BhavcopyFormatError(
            f"udiff FinInstrmTp has unknown codes: {unknown}; "
            f"expected only STO/IDO/STF/IDF (see SPECS §2.4)"
        )
    instrument = instrument.astype("string")

    # UDiff `TtlTradgVol` is already in contract units (not share units).
    # Verified empirically: RELIANCE 2024-08-29 2840CE has TtlTradgVol=26,
    # TtlTrfVal=19,661,050, NewBrdLotQty=250 → notional/contract ≈ 3024,
    # ≈ UndrlygPric 3041 → TtlTrfVal is *underlying* notional, TtlTradgVol
    # is contracts. Earlier "divide by lot" math was wrong; fixed.
    contracts = df["TtlTradgVol"].fillna(0).astype("int64")

    out = pd.DataFrame({
        "instrument": instrument,
        "symbol": df["TckrSymb"].astype("string"),
        "expiry": pd.to_datetime(df["FininstrmActlXpryDt"]).astype("datetime64[us]"),
        "strike": _strike_nan_for_futures(df["StrkPric"], instrument),
        "option_type": _normalize_option_type(df["OptnTp"]),
        "open": df["OpnPric"].astype("float64"),
        "high": df["HghPric"].astype("float64"),
        "low": df["LwPric"].astype("float64"),
        "close": df["ClsPric"].astype("float64"),
        "settle_price": df["SttlmPric"].astype("float64"),
        "contracts": contracts,
        "oi": df["OpnIntrst"].astype("Int64"),
        "oi_change": df["ChngInOpnIntrst"].astype("Int64"),
    })
    out["trade_date"] = _stamp_trade_date(len(out), trade_date)
    return out


# ============================================================
# Public entry point
# ============================================================

def load_bhavcopy_fo(trade_date: date, *, force_refresh: bool = False) -> pd.DataFrame:
    """Returns the SPECS §2.4-shaped F&O bhavcopy frame for ``trade_date``.

    Cache hit → load parquet (unless ``force_refresh=True``).
    Cache miss or ``force_refresh`` → fetch + parse + cache + return.

    Mirrors ``spot_loader.load_spot``'s ``force_refresh`` semantics.
    """
    path = cache.bhavcopy_fo_path(trade_date)
    if cache.exists(path) and not force_refresh:
        return cache.read(path)
    raw, fmt = _fetch_raw(trade_date)
    parser = parse_legacy if fmt == "legacy" else parse_udiff
    df = parser(raw, trade_date)
    cache.write(path, df, overwrite=force_refresh)
    return df
