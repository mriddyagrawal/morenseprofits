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

**Sibling lot-size cache** (P0.2 — MIGRATION.md §Phase 0):
On every fresh fetch, ``load_bhavcopy_fo`` ALSO writes a per-date
parquet to ``data/cache/bhavcopy_fo_lot_sizes/{date}.parquet``
containing the ``(symbol, expiry, lot_size)`` triples extracted from
the raw UDiff CSV. Legacy bhavcopy dates get an empty parquet
(legacy raw doesn't carry lot_size — sidecar files in
``data/manual/contracts/`` cover those expiries).

The main cache parquet ``data/cache/bhavcopy_fo/{date}.parquet``
is INTENTIONALLY NARROW — ``lot_size`` is NOT carried per row.
Consumers needing lot_size should query the unified
``data/cache/lot_sizes.parquet`` (built by
``scripts/build_lot_size_parquet.py`` from sidecars + this sibling
cache). Rationale: lot_size is per-(symbol, expiry) stable; per-row
storage in the bhavcopy cache duplicates ~60-90 days of repeated
values per contract. See MIGRATION.md §Cross-source lot-size policy.
"""
from __future__ import annotations

import functools
import io
import warnings
import zipfile
from datetime import date
from typing import Literal

import pandas as pd
import requests

from jugaad_data.nse.archives import NSEArchives

from src.data import cache
from src.data.errors import BhavcopyFormatError, MissingDataError, OfflineCacheMiss
from src.data.offline import effective_offline
from src.data.telemetry import warn_fetch


# Per-process LRU cache size for the per-date bhavcopy parquet read.
# Wide sweeps touch ~500 trading dates × 8 workers = 4k cache fills max;
# maxsize=512 holds a few months of recent dates per worker.
# Each entry is ~1-2 MB → ~512 × 1.5 MB ≈ ~0.75 GB per worker worst-case.
# Across 8 workers that's ~6 GB — fits comfortably on a 32+ GB host.
_LRU_MAXSIZE_BHAVCOPY = 512


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
_LEGACY_MARKERS = {"INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR", "OPTION_TYP", "TIMESTAMP", "VAL_INLAKH"}
_UDIFF_MARKERS = {"TradDt", "FinInstrmTp", "TckrSymb", "FininstrmActlXpryDt", "StrkPric", "OptnTp", "TtlTrfVal", "LastPric"}

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
    403/5xx propagation.

    Timeout override: jugaad's NSEArchives ships with `timeout = 4`
    seconds which is too aggressive for NSE's archives endpoint —
    a single slow response (common during peak hours) crashes the
    whole sweep. We bump per-instance to 30s, which matches the UDiff
    path's 60s budget order-of-magnitude. The underlying read is a
    single-shot ZIP download (~few-hundred-KB); 30s is generous."""
    archives = NSEArchives()
    archives.timeout = 30
    try:
        return archives.bhavcopy_fo_raw(trade_date)
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
    warn_fetch("bhavcopy_fo_loader", str(trade_date))
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
    # turnover extension (P1.2 — MIGRATION.md §Phase 1). Legacy carries
    # VAL_INLAKH in the raw CSV (same underlying-notional convention as
    # UDiff's TtlTrfVal per 8c2c517 — both are total traded value in
    # lakhs of rupees including the underlying notional component).
    # Engine recovers per-share premium VWAP via
    # ``turnover × 10⁵ / volume − strike`` (see pnl._compute_vwap).
    #
    # Legacy does NOT carry ltp (no equivalent of UDiff's LastPric);
    # the regime A/B caveat surfacing in MCP's get_options_chain (P2.4)
    # handles that gap.
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
        "turnover": df["VAL_INLAKH"].astype("float64"),
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

    # ltp + turnover extension (P1.1 — MIGRATION.md §Phase 1). The
    # 2-col extension lets the bhavcopy_to_contract_timeseries
    # transform (P1.3) populate the engine's normalized schema
    # without re-parsing the raw CSV. NewBrdLotQty (lot_size) is
    # INTENTIONALLY NOT in this output — see module docstring +
    # MIGRATION.md §Cross-source lot-size policy + the sibling-cache
    # path written by _write_sibling_lot_sizes_cache.
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
        "ltp": df["LastPric"].astype("float64"),
        "settle_price": df["SttlmPric"].astype("float64"),
        "contracts": contracts,
        "turnover": df["TtlTrfVal"].astype("float64"),
        "oi": df["OpnIntrst"].astype("Int64"),
        "oi_change": df["ChngInOpnIntrst"].astype("Int64"),
    })
    out["trade_date"] = _stamp_trade_date(len(out), trade_date)
    return out


# ============================================================
# Sibling lot-size extractor (P0.2)
# ============================================================
#
# Distinct from ``parse_udiff`` because the main cache parquet is
# INTENTIONALLY narrow (no lot_size per row) — see module docstring.
# This helper produces the per-date sibling cache content consumed by
# ``scripts/build_lot_size_parquet.py``.

_LOT_SIZE_OPTION_INSTRUMENTS = ("OPTSTK", "OPTIDX")


def _extract_lot_sizes_udiff(raw: str, trade_date: date) -> pd.DataFrame:
    """Extract ``(symbol, expiry, lot_size, trade_date)`` triples from
    a raw UDiff bhavcopy CSV. One row per unique ``(symbol, expiry)``
    on this trade date, restricted to OPTSTK + OPTIDX
    (FUTSTK / FUTIDX intentionally excluded — our backtest scope is
    options-only; futures lot_sizes are recoverable from the same
    NewBrdLotQty column if a future caller needs them, just remove
    the instrument filter).

    Output schema (also the sibling-cache schema in
    ``data/cache/bhavcopy_fo_lot_sizes/{date}.parquet``):

    - ``symbol`` (string)
    - ``expiry`` (datetime64[us], from ``FininstrmActlXpryDt``)
    - ``lot_size`` (int64, from ``NewBrdLotQty``)
    - ``trade_date`` (datetime64[us], stamped from caller)

    Same ``_UDIFF_MARKERS`` header check as ``parse_udiff`` — same
    loud failure mode (``BhavcopyFormatError``) on schema drift.
    """
    df = pd.read_csv(io.StringIO(raw))
    df.columns = df.columns.str.strip()
    if not _UDIFF_MARKERS.issubset(df.columns):
        raise BhavcopyFormatError(
            f"udiff lot-size extract: header missing required cols: "
            f"{sorted(_UDIFF_MARKERS - set(df.columns))}; got "
            f"{list(df.columns)}"
        )
    instrument = df["FinInstrmTp"].map(_UDIFF_TO_LEGACY_INSTR)
    if instrument.isna().any():
        unknown = sorted(set(df.loc[instrument.isna(), "FinInstrmTp"].astype(str)))
        raise BhavcopyFormatError(
            f"udiff lot-size extract: FinInstrmTp has unknown codes: "
            f"{unknown}; expected only STO/IDO/STF/IDF"
        )
    is_option = instrument.isin(_LOT_SIZE_OPTION_INSTRUMENTS)
    df = df[is_option]
    if "NewBrdLotQty" not in df.columns:
        raise BhavcopyFormatError(
            "udiff lot-size extract: NewBrdLotQty column missing; "
            "raw header drift?"
        )
    out = pd.DataFrame({
        "symbol": df["TckrSymb"].astype("string"),
        "expiry": pd.to_datetime(
            df["FininstrmActlXpryDt"]
        ).astype("datetime64[us]"),
        "lot_size": df["NewBrdLotQty"].fillna(0).astype("int64"),
    })
    out = (
        out.drop_duplicates(subset=["symbol", "expiry"], keep="first")
        .reset_index(drop=True)
    )
    # Explicit [us] precision to match `expiry` + the rest of the
    # project's datetime convention (cache.py uses [us] across products).
    out["trade_date"] = pd.Series(
        [pd.Timestamp(trade_date)] * len(out), dtype="datetime64[us]",
    )
    return out


def _empty_lot_sizes_frame() -> pd.DataFrame:
    """Returned by the sibling-cache write path for legacy bhavcopy
    dates (which don't carry lot_size in their raw CSV). Schema
    identical to ``_extract_lot_sizes_udiff`` output; just empty."""
    return pd.DataFrame({
        "symbol": pd.Series(dtype="string"),
        "expiry": pd.Series(dtype="datetime64[us]"),
        "lot_size": pd.Series(dtype="int64"),
        "trade_date": pd.Series(dtype="datetime64[us]"),
    })


def _write_sibling_lot_sizes_cache(
    raw: str, fmt: FormatTag, trade_date: date,
) -> None:
    """Sibling-cache writer called from ``_load_bhavcopy_fo_impl`` and
    the ``force_refresh`` path. UDiff dates extract from raw; legacy
    dates write an empty parquet so the build script's directory scan
    sees a row-per-date completeness signal."""
    lot_sizes_df = (
        _extract_lot_sizes_udiff(raw, trade_date)
        if fmt == "udiff"
        else _empty_lot_sizes_frame()
    )
    cache.write(
        cache.bhavcopy_fo_lot_sizes_path(trade_date),
        lot_sizes_df, overwrite=True,
    )


# ============================================================
# Public entry point
# ============================================================

@functools.lru_cache(maxsize=_LRU_MAXSIZE_BHAVCOPY)
def _load_bhavcopy_fo_cached(trade_date_iso: str, offline: bool) -> pd.DataFrame:
    """Per-worker memoization of ``load_bhavcopy_fo`` for the
    ``force_refresh=False`` path. Bhavcopies are immutable historical
    data so no today_iso key is needed — cache lifetime = worker
    lifetime is correct."""
    trade_date = date.fromisoformat(trade_date_iso)
    return _load_bhavcopy_fo_impl(trade_date, offline=offline)


def _load_bhavcopy_fo_impl(trade_date: date, *, offline: bool) -> pd.DataFrame:
    """Underlying cache-then-fetch logic; kept separate from the LRU
    wrapper so force_refresh can call it directly.

    **Schema staleness check** (post-P1.1/P1.2 — MIGRATION.md §Phase 1):
    a cached parquet is considered stale if it lacks the ``turnover``
    column. Pre-P1.1 caches were 14-col (no ``turnover`` / no ``ltp``);
    downstream consumers (``bhavcopy_to_contract``, the VWAP fill path
    in ``pnl._pick_fill_price``) require turnover. On detection, the
    stale parquet is silently re-fetched + rewritten so the caller
    gets the post-P1.1 16-col shape transparently. One-time warning
    per process so the operator knows why the bulk-fetch step is
    suddenly hitting the network for already-cached dates.
    """
    path = cache.bhavcopy_fo_path(trade_date)
    if cache.exists(path):
        df = cache.read(path)
        if "turnover" in df.columns:
            return df
        # Stale schema — fall through to re-fetch. (Skipping the cache
        # is safer than patching turnover=NaN: VWAP fills downstream
        # would silently degrade to MissingTurnoverError on every cell.)
        _warn_stale_bhavcopy_cache_once(trade_date)
    if offline:
        raise OfflineCacheMiss(
            f"bhavcopy_fo for {trade_date} not in cache and offline mode "
            f"requested (offline=True or MORENSE_OFFLINE=1)"
        )
    raw, fmt = _fetch_raw(trade_date)
    parser = parse_legacy if fmt == "legacy" else parse_udiff
    df = parser(raw, trade_date)
    # overwrite=True for multi-worker race safety (see options_loader.py
    # cache-miss block for the full reasoning) AND for stale-schema
    # rewrite (pre-P1.1 14-col → post-P1.1 16-col).
    cache.write(path, df, overwrite=True)
    # Sibling lot-size cache (P0.2 — MIGRATION.md §Phase 0). Written
    # alongside the main cache so they stay paired across refreshes.
    _write_sibling_lot_sizes_cache(raw, fmt, trade_date)
    return df


_STALE_CACHE_WARNING_EMITTED: bool = False


def _warn_stale_bhavcopy_cache_once(trade_date: date) -> None:
    """One-time-per-process warning that the bhavcopy_fo cache is
    pre-P1.1 14-col and is being silently re-fetched to the post-P1.1
    16-col schema. Skips subsequent calls so the operator gets a
    single line instead of 466."""
    global _STALE_CACHE_WARNING_EMITTED
    if _STALE_CACHE_WARNING_EMITTED:
        return
    _STALE_CACHE_WARNING_EMITTED = True
    import warnings
    warnings.warn(
        f"[bhavcopy_fo] stale 14-col cache detected (first hit: "
        f"{trade_date}). Re-fetching to post-P1.1 16-col schema "
        f"(adds turnover + ltp). One-time cost per cache."
    )


def load_bhavcopy_fo(
    trade_date: date,
    *,
    force_refresh: bool = False,
    offline: bool = False,
) -> pd.DataFrame:
    """Returns the SPECS §2.4-shaped F&O bhavcopy frame for ``trade_date``.

    Cache hit → load parquet (unless ``force_refresh=True``).
    Cache miss or ``force_refresh`` → fetch + parse + cache + return.

    `offline=True` (or env MORENSE_OFFLINE=1): cache miss raises
    OfflineCacheMiss; never touches network. Takes precedence over
    force_refresh.

    Mirrors ``spot_loader.load_spot``'s ``force_refresh`` semantics.
    Hot-path memoization (``_load_bhavcopy_fo_cached``) skips disk for
    repeat dates within the same worker — wide sweeps that touch each
    bhavcopy ~30× drop to 1× post-warm.
    """
    offline = effective_offline(offline)
    if force_refresh:
        # Bypass LRU; fetch+write unconditionally.
        path = cache.bhavcopy_fo_path(trade_date)
        if offline:
            raise OfflineCacheMiss(
                f"bhavcopy_fo for {trade_date} not in cache and offline mode "
                f"requested (offline=True or MORENSE_OFFLINE=1)"
            )
        raw, fmt = _fetch_raw(trade_date)
        parser = parse_legacy if fmt == "legacy" else parse_udiff
        df = parser(raw, trade_date)
        cache.write(path, df, overwrite=True)
        # Sibling lot-size cache also refreshed on force_refresh.
        _write_sibling_lot_sizes_cache(raw, fmt, trade_date)
        return df
    return _load_bhavcopy_fo_cached(trade_date.isoformat(), offline)
