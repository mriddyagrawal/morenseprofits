"""Parameter sweep over (strategy × symbol × expiry × entry × exit).

The Phase-4 module that turns the Phase-3 single-trade pricer into a
research dataset. Each task is a pure function of its inputs; results
sort + concat into a SPECS §2.5 results parquet that Phase-5 ranks and
Phase-6 visualizes.

Determinism contract (SPECS §6c.3) — IDENTICAL inputs → byte-identical
parquet, regardless of:
  - worker count (1 vs many — perf(p4.5) adds Pool; this file is the
    single-threaded reference; the Pool version must agree byte-for-byte)
  - worker scheduling
  - repeat invocations

Achieved by:
  1. Each ``sweep_one(...)`` task is pure: only reads cache, returns
     one result dict. No shared mutable state.
  2. ``sweep_grid`` enumerates tasks in deterministic order
     (alphabetical / chronological) so SINGLE-THREADED execution is
     also deterministic.
  3. Final ``pd.concat(...)`` sorted by canonical key tuple +
     ``reset_index(drop=True)`` before persist.
  4. ``run_id`` is a deterministic hash of the input grid; same grid
     → same run_id → same on-disk file path → re-runs skip per
     SPECS §6c.4.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Callable, Iterable

import pandas as pd

from src.config import RESULTS_DIR
from src.data import spot_loader, trading_calendar
from src.data.errors import MissingDataError
from src.engine.pnl import price_trade
from src.strategies.base import Trade
from src.strategies.registry import STRATEGIES, get_strategy
from src.strategies.short_straddle import NoLiquidStrikeError


# Skip reasons — anything in this tuple is "absent data", logged + skipped.
# OfflineCacheMiss is intentionally NOT in this list — it propagates per
# SPECS §6a's class-distinction rule (a cold offline cache is operator
# error, not "no data").
_SKIPPABLE_ERRORS = (MissingDataError, NoLiquidStrikeError)


def _compute_run_id(
    strategies: list[str],
    symbols: list[str],
    expiries: list[date],
    entry_offsets_td: list[int],
    exit_offsets_td: list[int],
) -> str:
    """Deterministic 12-char hash of the logical-input tuple per SPECS
    §6c.3. Operational kwargs (today_fn, parallel, n_workers, offline)
    are explicitly EXCLUDED — same logical sweep produces same run_id
    regardless of how executed."""
    payload = (
        tuple(sorted(strategies)),
        tuple(sorted(symbols)),
        tuple(sorted(d.isoformat() for d in expiries)),
        tuple(sorted(entry_offsets_td)),
        tuple(sorted(exit_offsets_td)),
    )
    h = hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()
    return h[:12]


def sweep_one(
    strategy_name: str,
    symbol: str,
    expiry: date,
    entry_offset_td: int,
    exit_offset_td: int,
    *,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> dict | None:
    """Price ONE backtest cell: (strategy, symbol, expiry, offsets).

    Returns a SPECS §2.5 result dict augmented with sweep-specific
    decorations (entry_offset_td, exit_offset_td, notional_at_entry,
    entry_spot, exit_spot, run_id-deferred). Returns ``None`` if the
    task is skipped due to a SKIPPABLE_ERROR (logged separately by the
    sweeper).

    Pure function of its inputs (modulo `today_fn` injection) — no
    shared mutable state, no global I/O beyond the read-only cache.
    """
    if entry_offset_td <= exit_offset_td:
        # T-15 entry must be BEFORE T-1 exit (larger offset = further
        # back). Refusing same-day / inverted windows here keeps the
        # caller honest.
        raise ValueError(
            f"entry_offset_td ({entry_offset_td}) must be > exit_offset_td "
            f"({exit_offset_td}); larger offset = further back in time"
        )

    strategy = get_strategy(strategy_name)

    try:
        entry_date = trading_calendar.offset_trading_days(
            expiry, entry_offset_td, today_fn=today_fn, offline=offline,
        )
        exit_date = trading_calendar.offset_trading_days(
            expiry, exit_offset_td, today_fn=today_fn, offline=offline,
        )
        spot_df = spot_loader.load_spot(
            symbol, entry_date, entry_date, today_fn=today_fn, offline=offline,
        )
        if spot_df.empty:
            return None  # treat as missing; rare but possible
        spot_at_entry = float(spot_df.iloc[0]["close"])
        exit_spot_df = spot_loader.load_spot(
            symbol, exit_date, exit_date, today_fn=today_fn, offline=offline,
        )
        exit_spot = float(exit_spot_df.iloc[0]["close"]) if not exit_spot_df.empty else None

        trades = strategy.generate_trades(
            symbol=symbol, expiry=expiry,
            entry_date=entry_date, exit_date=exit_date,
            spot_at_entry=spot_at_entry,
            params={},
        )
        if not trades:
            return None
        trade = trades[0]
        result = price_trade(
            trade,
            strategy_offset_pct=strategy.recommended_strategy_offset_pct,
            today_fn=today_fn,
        )
    except _SKIPPABLE_ERRORS:
        return None

    # Sweep-specific decorations
    result["entry_offset_td"] = int(entry_offset_td)
    result["exit_offset_td"] = int(exit_offset_td)
    result["entry_spot"] = spot_at_entry
    result["exit_spot"] = exit_spot
    # notional_at_entry = spot × total share exposure. PLAN §4 rule #3:
    # read per-row lot_size from legs_json, NOT a constant. NSE lot sizes
    # vary by symbol (RELIANCE 250 / HDFCBANK 550 / INFY 400 / ICICIBANK
    # 700) and change over time within a symbol; the per-row value the
    # P&L kernel already extracted from the bhavcopy is canonical.
    leg_results = json.loads(result["legs_json"])
    total_share_exposure = sum(
        int(leg_r["qty_lots"]) * int(leg_r["lot_size"])
        for leg_r in leg_results
    )
    result["notional_at_entry"] = spot_at_entry * total_share_exposure
    return result


def sweep_grid(
    strategies: list[str],
    symbols: list[str],
    expiries: list[date],
    entry_offsets_td: list[int],
    exit_offsets_td: list[int],
    *,
    run_id: str | None = None,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
    force: bool = False,
) -> pd.DataFrame:
    """Cartesian-product sweep over the given grid.

    Returns the SPECS §2.5 results frame; also persists to
    ``data/results/sweep_{run_id}.parquet`` per SPECS §6c.4.

    Re-run policy (SPECS §6c.4): if the parquet for this run_id already
    exists and ``force=False``, returns the cached frame without
    re-running. ``force=True`` rebuilds.

    NOTE: this is the single-threaded reference impl. ``perf(p4.5)``
    adds the multiprocessing.Pool variant which must produce
    byte-identical output (semantic-equal per pandas).
    """
    if run_id is None:
        run_id = _compute_run_id(
            strategies, symbols, expiries, entry_offsets_td, exit_offsets_td,
        )
    path = RESULTS_DIR / f"sweep_{run_id}.parquet"

    if path.exists() and not force:
        return pd.read_parquet(path)

    # Enumerate tasks in deterministic order — sorted across every axis.
    # Single-threaded loop matches this order; parallel pool will sort
    # results post-hoc so the order doesn't matter for output.
    tasks = [
        (s, sym, exp, eo, xo)
        for s in sorted(strategies)
        for sym in sorted(symbols)
        for exp in sorted(expiries)
        for eo in sorted(entry_offsets_td, reverse=True)  # T-15 before T-1 in iteration
        for xo in sorted(exit_offsets_td, reverse=True)
        if eo > xo  # enforce entry > exit
    ]

    rows: list[dict] = []
    for (s, sym, exp, eo, xo) in tasks:
        result = sweep_one(
            s, sym, exp, eo, xo,
            today_fn=today_fn, offline=offline,
        )
        if result is None:
            continue
        result["run_id"] = run_id
        rows.append(result)

    if not rows:
        # Empty sweep — return an empty frame with the right columns
        df = pd.DataFrame(rows)
    else:
        df = pd.DataFrame(rows)
        # Determinism: sort by canonical key tuple + reset_index
        df = df.sort_values(
            ["strategy", "symbol", "expiry", "entry_offset_td", "exit_offset_td"]
        ).reset_index(drop=True)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df
