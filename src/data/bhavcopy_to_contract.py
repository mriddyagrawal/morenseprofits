"""Bhavcopy → per-contract EOD time-series transform.

Reconstructs the per-(symbol, expiry, strike, option_type) row
sequence the engine consumes by walking the daily bhavcopy parquet
cache and filtering each day's frame. Replaces the per-contract
``options_loader.load_option`` HTTP path for the migration's
bhavcopy-only architecture (MIGRATION.md §Phase 1 P1.3).

Public API:

  ``bhavcopy_to_contract_timeseries(
      symbol, expiry, strike, option_type,
      *, from_date, to_date,
  ) -> pd.DataFrame``

      Returns a DataFrame matching the ``options_loader.load_option``
      output schema EXACTLY: same 16 columns, same dtypes, sorted by
      date. The materialize step (P1.4) writes this output to the
      same disk path layout ``options_loader`` uses; sweep workers
      read it unchanged.

Data sources:

  1. ``data/cache/bhavcopy_fo/{YYYYMMDD}.parquet`` — daily UDiff or
     legacy bhavcopy with the P1.1/P1.2 extensions (ltp + turnover).
  2. ``data/cache/lot_sizes.parquet`` — unified lot-size lookup via
     ``lot_size_lookup`` (P1.3 / P0.2).

Regime handling is implicit: legacy bhavcopy rows arrive with
``ltp`` missing (the legacy parser doesn't emit the column); this
function fills NaN for those rows in the output schema. UDiff rows
carry ``ltp`` natively. Both regimes derive ``volume`` via
``contracts × lot_size`` (unified lookup).

Errors:

  - ``MissingTurnoverError`` if any of the matched rows has a
    missing ``lot_size`` (excluded cross-source pair) OR a
    missing / zero turnover / volume.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.data import cache
from src.data.errors import MissingTurnoverError
from src.data.lot_size_lookup import lot_size_lookup


# Target output schema — must match options_loader._SPEC_COLS in
# order + dtype. Any drift here will fail the LOAD-BEARING
# equivalence test against load_option's output.
_OUTPUT_COLUMNS = [
    "date", "symbol", "expiry", "option_type", "strike",
    "open", "high", "low", "close", "ltp",
    "settle_price", "lot_size", "volume", "turnover", "oi", "oi_change",
]


def _iterate_trading_days(from_date: date, to_date: date) -> list[date]:
    """All calendar days in [from_date, to_date] inclusive.

    The bhavcopy cache is sparse — non-trading days simply have no
    parquet on disk (weekends, NSE holidays, days before listing,
    days after expiry). The transform handles missing days by
    silently skipping. This matches options_loader.load_option's
    semantics (which skips dates absent from the contract's history).
    """
    return [
        from_date + pd.Timedelta(days=i)
        for i in range((to_date - from_date).days + 1)
    ]


def _load_one_day_filtered(
    trade_date: date,
    *, symbol: str, expiry: date, strike: float, option_type: str,
) -> pd.DataFrame | None:
    """Read one day's bhavcopy parquet (if cached) and filter to the
    requested contract. Returns None when the day has no cached
    parquet (silently skipped — non-trading day, pre-listing, or
    operator hasn't fetched that date)."""
    path = cache.bhavcopy_fo_path(trade_date)
    if not cache.exists(path):
        return None
    df = cache.read(path)
    # Note: trade_date column reflects the bhavcopy's stamp; we
    # don't re-validate here (the loader already enforces stamp
    # consistency at write time).
    matched = df[
        (df["symbol"] == symbol)
        & (df["expiry"] == pd.Timestamp(expiry))
        & (df["strike"] == strike)
        & (df["option_type"] == option_type)
    ]
    if len(matched) == 0:
        return None
    return matched.copy()


def _normalize_legacy_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Legacy parser output (15 cols) doesn't carry ``ltp``. Insert
    NaN ltp so the concatenation downstream sees a uniform 16-col
    intermediate frame. UDiff frames pass through unchanged."""
    if "ltp" not in df.columns:
        df = df.copy()
        df["ltp"] = pd.Series([float("nan")] * len(df), dtype="float64")
    return df


def bhavcopy_to_contract_timeseries(
    symbol: str, expiry: date, strike: float, option_type: str,
    *,
    from_date: date, to_date: date,
) -> pd.DataFrame:
    """Reconstruct per-contract EOD rows from cached bhavcopies.

    See module docstring for the architectural role + the source
    contract. Output is byte-identical to
    ``options_loader.load_option(symbol, expiry, strike, option_type)``
    filtered to ``[from_date, to_date]`` — same 16 columns, same
    dtypes, sorted by ``date`` ascending.

    Inputs are normalized once at the public boundary: ``symbol``
    and ``option_type`` are uppercased (bhavcopies always store the
    canonical upper-case form). Matches the batch path's
    ``sym_upper = {s.upper() for s in symbols}`` normalization in
    ``materialize_contracts_batch`` — closes the case-sensitivity
    divergence Grill from the ef4f71b review.

    Raises:
        MissingTurnoverError: lot_size_lookup returned None (the
            pair is excluded from the unified cache); OR contracts
            is missing/zero on any row.
    """
    # Public-boundary normalization: bhavcopies store upper-case
    # symbol + "CE"/"PE". A lower-case caller would otherwise hit
    # the equality filter inside ``_load_one_day_filtered`` and
    # silently return an empty frame — invisible at the operator
    # API surface today (all callers happen to pass upper) but a
    # latent footgun for any future caller (REPL, paper-trading,
    # an MCP tool). Symmetric with the batch path.
    symbol = symbol.upper()
    option_type = option_type.upper()

    days = _iterate_trading_days(from_date, to_date)
    daily_frames: list[pd.DataFrame] = []
    for d in days:
        sub = _load_one_day_filtered(
            d, symbol=symbol, expiry=expiry,
            strike=strike, option_type=option_type,
        )
        if sub is None:
            continue
        daily_frames.append(_normalize_legacy_columns(sub))

    if not daily_frames:
        # No rows in the date range — return empty frame with the
        # right schema so downstream code can still concat / dropna
        # without crashing.
        return _empty_output_frame()

    raw = pd.concat(daily_frames, ignore_index=True)

    # Resolve lot_size ONCE for this (symbol, expiry); the value is
    # stable per (symbol, expiry-month) for non-excluded pairs.
    lot_size = lot_size_lookup(symbol, expiry)
    if lot_size is None:
        raise MissingTurnoverError(
            f"lot_size unavailable for {symbol} {expiry.strftime('%Y-%m')} "
            f"— pair excluded from data/cache/lot_sizes.parquet due to "
            f"cross-source mismatch (see MIGRATION.md §Cross-source "
            f"lot-size policy). Contract is structurally unbacktestable."
        )

    # Reject the contract ONLY when it was never traded across the
    # entire window (every row has contracts == 0). Partial-zero
    # rows are normal in an active contract's life — listing day
    # to first-trade lag, quiet weeks, the day before expiry — and
    # are KEPT here (with volume = contracts × lot_size = 0). The
    # engine's per-row IlliquidLegError gate in pnl._price_one_leg
    # handles zero-volume rows at sweep time, matching the
    # options_loader.load_option behaviour we're replacing.
    if (raw["contracts"] <= 0).all():
        raise MissingTurnoverError(
            f"contracts == 0 on every trade day in window for "
            f"{symbol} {expiry.strftime('%Y-%m-%d')} "
            f"{cache._strike_path_segment(strike)}{option_type}; "
            f"contract was never actually traded — nothing to "
            f"materialize."
        )

    return _assemble_output_frame(raw, lot_size)


def enumerate_contracts_from_bhavcopies(
    *,
    symbols: list[str] | set[str],
    from_date: date, to_date: date,
    instrument_filter: tuple[str, ...] = ("OPTSTK",),
) -> list[tuple[str, date, float, str]]:
    """Scan cached daily bhavcopies in ``[from_date, to_date]`` and
    enumerate every distinct ``(symbol, expiry, strike, option_type)``
    that actually traded for any symbol in ``symbols``.

    Replaces the strike-planner pre-enumeration step under the
    bhavcopy-only architecture (P1.5). Every traded strike is
    naturally present in the bhavcopy — no "guess the strike window"
    needed, no strike-drift ``OfflineCacheMiss``.

    Returns a SORTED list of contract tuples for deterministic
    iteration order across runs.

    Days with no cached parquet (weekends, holidays, pre-listing,
    operator hasn't fetched that date) are silently skipped — same
    semantics as the transform's missing-day handling.
    """
    sym_upper = {s.upper() for s in symbols}
    instrument_set = set(instrument_filter)
    tuples: set[tuple[str, date, float, str]] = set()
    for d in _iterate_trading_days(from_date, to_date):
        path = cache.bhavcopy_fo_path(d)
        if not cache.exists(path):
            continue
        df = cache.read(path)
        df = df[
            df["symbol"].isin(sym_upper)
            & df["instrument"].isin(instrument_set)
        ]
        if df.empty:
            continue
        for _, r in df.iterrows():
            strike = r["strike"]
            opt = r["option_type"]
            # Skip futures (strike NaN) defensively even though the
            # OPTSTK filter should have excluded them.
            if pd.isna(strike) or pd.isna(opt):
                continue
            tuples.add((
                str(r["symbol"]),
                r["expiry"].date()
                if isinstance(r["expiry"], pd.Timestamp)
                else r["expiry"],
                float(strike),
                str(opt),
            ))
    return sorted(tuples)


def materialize_contract_from_bhavcopy(
    symbol: str, expiry: date, strike: float, option_type: str,
    *,
    from_date: date, to_date: date,
    force: bool = False,
) -> Path:
    """Build + persist a per-contract parquet at the SAME disk path
    ``options_loader`` writes to (``cache.option_path``).

    Wraps ``bhavcopy_to_contract_timeseries`` with disk-write
    semantics. The sweep workers don't care which path produced the
    parquet — same schema, same location.

    Args:
        symbol, expiry, strike, option_type: contract identity.
        from_date, to_date: bhavcopy scan window (inclusive).
        force: if False (default), skip writing when the target
            parquet already exists. If True, rewrite unconditionally.

    Returns:
        The path written (or the existing path under force=False).

    Raises:
        MissingTurnoverError: lot_size_lookup returned None or any
            row has contracts ≤ 0 (transform-level checks). No
            partial file is written — the caller can retry.

    Idempotency: the file-exists check is the only state — no
    hash / timestamp / content-comparison. Force-rewrite is the
    operator's escape hatch for stale data (e.g. after a
    ``--rebuild-lot-sizes`` run that may have changed exclusion
    membership).
    """
    path = cache.option_path(symbol, expiry, strike, option_type)
    if path.exists() and not force:
        return path
    df = bhavcopy_to_contract_timeseries(
        symbol, expiry, strike, option_type,
        from_date=from_date, to_date=to_date,
    )
    cache.write(path, df, overwrite=True)
    return path


def _assemble_output_frame(
    sub: pd.DataFrame, lot_size: int,
) -> pd.DataFrame:
    """Build the 16-col options_loader-shape output from a per-
    contract bhavcopy sub-frame + the resolved ``lot_size``.

    Shared by the per-contract transform path
    (``bhavcopy_to_contract_timeseries``) and the batch materialize
    path (``materialize_contracts_batch``). Single source of truth
    for the output dtype + column order.
    """
    # reset_index BEFORE constructing the output. Groupby sub-frames
    # retain the parent's indices (e.g., [0, 2, 5]); a freshly-built
    # ``lot_size`` Series has a 0-based RangeIndex. Without reset, the
    # DataFrame constructor aligns by index and silently produces
    # NaN-filled phantom rows where the indices don't overlap. This
    # is the canonical pandas footgun for "I just want to attach a
    # broadcast scalar column."
    sub = sub.reset_index(drop=True)
    return pd.DataFrame({
        "date": sub["trade_date"].astype("datetime64[us]"),
        "symbol": sub["symbol"].astype("string"),
        "expiry": sub["expiry"].astype("datetime64[us]"),
        "option_type": sub["option_type"].astype("string"),
        "strike": sub["strike"].astype("float64"),
        "open": sub["open"].astype("float64"),
        "high": sub["high"].astype("float64"),
        "low": sub["low"].astype("float64"),
        "close": sub["close"].astype("float64"),
        "ltp": sub["ltp"].astype("float64"),
        "settle_price": sub["settle_price"].astype("float64"),
        "lot_size": pd.Series([lot_size] * len(sub), dtype="int64"),
        "volume": (sub["contracts"] * lot_size).astype("int64"),
        "turnover": sub["turnover"].astype("float64"),
        "oi": sub["oi"].astype("Int64"),
        "oi_change": sub["oi_change"].astype("Int64"),
    }).sort_values("date").reset_index(drop=True)[_OUTPUT_COLUMNS]


def materialize_contracts_batch(
    symbols: list[str] | set[str],
    *,
    from_date: date, to_date: date,
    force: bool = False,
    instrument_filter: tuple[str, ...] = ("OPTSTK",),
    progress_callback=None,
) -> dict:
    """Batch materialize ALL per-contract parquets for the given
    symbol set in a single pass over the cached bhavcopies.

    Replaces the per-contract loop (which re-walks every cached day
    for each contract) with a single-pass O(days + contracts) scan.
    For a 4-symbol × 2-year window: ~466 file reads + ~10k group
    ops instead of ~4.4M file reads.

    Returns a dict with counts:

      - ``materialized``: contracts written to disk this call.
      - ``already_cached``: contracts whose parquet already existed
        (skipped per cache-first idempotency unless ``force=True``).
      - ``skipped_missing_turnover``: contracts where the unified
        cache excludes the lot_size OR any row has contracts ≤ 0.
      - ``skipped_other``: contracts that hit an unexpected error.
      - ``skip_log``: list of ``(sym, expiry, strike, opt, reason)``
        for the first 100 skipped contracts (operator-triage aid).

    Errors are caught per-contract — one bad contract doesn't halt
    the batch. The per-contract function
    ``materialize_contract_from_bhavcopy`` is retained for single-
    contract debug / Phase 2 paths.
    """
    sym_upper = {s.upper() for s in symbols}
    instrument_set = set(instrument_filter)

    # Single-pass bhavcopy load + symbol filter.
    days = _iterate_trading_days(from_date, to_date)
    frames: list[pd.DataFrame] = []
    for d in days:
        path = cache.bhavcopy_fo_path(d)
        if not cache.exists(path):
            continue
        df = cache.read(path)
        df = df[
            df["symbol"].isin(sym_upper)
            & df["instrument"].isin(instrument_set)
        ]
        if df.empty:
            continue
        frames.append(_normalize_legacy_columns(df))

    counts = {
        "materialized": 0,
        "already_cached": 0,
        "skipped_missing_turnover": 0,
        "skipped_other": 0,
        "skip_log": [],
    }
    if not frames:
        return counts

    big = pd.concat(frames, ignore_index=True)
    # Drop futures defensively (instrument filter should have done it,
    # but a NaN strike would break the groupby).
    big = big.dropna(subset=["strike", "option_type"])

    grouped = big.groupby(
        ["symbol", "expiry", "strike", "option_type"], sort=True,
    )
    total_groups = len(grouped)
    processed = 0
    for (symbol, expiry_ts, strike, opt_type), sub in grouped:
        processed += 1
        if progress_callback is not None:
            progress_callback(processed, total_groups)
        expiry_date = (
            expiry_ts.date() if isinstance(expiry_ts, pd.Timestamp) else expiry_ts
        )
        target = cache.option_path(
            str(symbol), expiry_date, float(strike), str(opt_type),
        )
        if target.exists() and not force:
            counts["already_cached"] += 1
            continue

        lot_size = lot_size_lookup(str(symbol), expiry_date)
        if lot_size is None:
            counts["skipped_missing_turnover"] += 1
            if len(counts["skip_log"]) < 100:
                counts["skip_log"].append((
                    str(symbol), expiry_date, float(strike), str(opt_type),
                    "lot_size excluded (cross-source mismatch)",
                ))
            continue

        if (sub["contracts"] <= 0).all():
            counts["skipped_missing_turnover"] += 1
            if len(counts["skip_log"]) < 100:
                counts["skip_log"].append((
                    str(symbol), expiry_date, float(strike), str(opt_type),
                    "never traded (contracts == 0 on every cached day)",
                ))
            continue

        try:
            out = _assemble_output_frame(sub, lot_size)
            cache.write(target, out, overwrite=True)
            counts["materialized"] += 1
        except Exception as e:
            counts["skipped_other"] += 1
            if len(counts["skip_log"]) < 100:
                counts["skip_log"].append((
                    str(symbol), expiry_date, float(strike), str(opt_type),
                    f"{type(e).__name__}: {str(e)[:200]}",
                ))

    return counts


def _empty_output_frame() -> pd.DataFrame:
    """Empty frame with the 16-col output schema + correct dtypes —
    same shape every caller would get from a populated transform."""
    return pd.DataFrame({
        "date": pd.Series(dtype="datetime64[us]"),
        "symbol": pd.Series(dtype="string"),
        "expiry": pd.Series(dtype="datetime64[us]"),
        "option_type": pd.Series(dtype="string"),
        "strike": pd.Series(dtype="float64"),
        "open": pd.Series(dtype="float64"),
        "high": pd.Series(dtype="float64"),
        "low": pd.Series(dtype="float64"),
        "close": pd.Series(dtype="float64"),
        "ltp": pd.Series(dtype="float64"),
        "settle_price": pd.Series(dtype="float64"),
        "lot_size": pd.Series(dtype="int64"),
        "volume": pd.Series(dtype="int64"),
        "turnover": pd.Series(dtype="float64"),
        "oi": pd.Series(dtype="Int64"),
        "oi_change": pd.Series(dtype="Int64"),
    })
