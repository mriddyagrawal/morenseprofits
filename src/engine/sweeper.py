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
import multiprocessing as mp
from datetime import date
from typing import Callable, Iterable

import pandas as pd

from src.config import RESULTS_DIR
from src.data import spot_loader, trading_calendar
from src.data.errors import MissingDataError
from src.engine import results as _results
from src.engine.pnl import price_trade
from src.strategies.base import Trade
from src.strategies.registry import STRATEGIES, get_strategy
from src.strategies.short_straddle import NoLiquidStrikeError


# Skip reasons — anything in this tuple is "absent data", logged + skipped.
# OfflineCacheMiss is intentionally NOT in this list — it propagates per
# SPECS §6a's class-distinction rule (a cold offline cache is operator
# error, not "no data").
_SKIPPABLE_ERRORS = (MissingDataError, NoLiquidStrikeError)


# ------------------------------------------------------------
# Worker-process state — for multiprocessing.Pool path.
# ------------------------------------------------------------
#
# `today_fn` is a Callable[[], date] which may be a lambda → unpicklable,
# so we can't ship it across the Pool boundary directly. Instead we
# resolve it once in the main process and stash the resulting date in a
# worker-module global via Pool's initializer. Each worker rebuilds a
# trivial closure-free today_fn from that global.
#
# Module-level (not class state) because Pool initializer requires a
# module-level callable + state mutation in the worker import.
_WORKER_TODAY: date | None = None


def _worker_init(today_date: date) -> None:
    """Pool initializer. Stashes today_date so worker tasks can build a
    today_fn without pickling a lambda from the main process."""
    global _WORKER_TODAY
    _WORKER_TODAY = today_date


def _worker_today_fn() -> date:
    """Module-level today_fn used inside worker processes. Picklable by
    name (closures wouldn't pickle, lambdas wouldn't pickle)."""
    assert _WORKER_TODAY is not None, (
        "_worker_today_fn called outside a Pool — initializer never ran"
    )
    return _WORKER_TODAY


def _worker_run(args: tuple) -> tuple:
    """Pool worker entrypoint. Unpacks the task tuple, runs sweep_one,
    returns (task_args, result) so the main process can pair skips back
    to their (strategy, symbol, expiry, entry, exit) for the skip log
    regardless of completion order."""
    s, sym, exp, eo, xo, offline = args
    result = sweep_one(
        s, sym, exp, eo, xo,
        today_fn=_worker_today_fn,
        offline=offline,
    )
    return ((s, sym, exp, eo, xo), result)


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
) -> dict | None | str:
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
            spot_at_entry=spot_at_entry,
            # Exact trading-day hold — both offsets are measured against
            # the same expiry's trading-day calendar, so their difference
            # is the true hold (no 252/365 round-trip approximation).
            hold_trading_days=int(entry_offset_td) - int(exit_offset_td),
            today_fn=today_fn,
        )
    except _SKIPPABLE_ERRORS as e:
        # Return the exception class name as a string so sweep_grid can
        # log the reason. None would lose the diagnostic info.
        return f"skip:{type(e).__name__}"

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
    n_workers: int = 1,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Cartesian-product sweep over the given grid.

    Returns the SPECS §2.5 results frame; also persists to
    ``data/results/sweep_{run_id}.parquet`` per SPECS §6c.4.

    Re-run policy (SPECS §6c.4): if the parquet for this run_id already
    exists and ``force=False``, returns the cached frame without
    re-running. ``force=True`` rebuilds.

    Determinism (SPECS §6c.3): byte-identical output regardless of
    ``n_workers``. Achieved because (a) ``sweep_one`` is pure, (b) we
    sort + reset_index post-collection by the canonical key tuple, and
    (c) parquet write is deterministic given input.

    n_workers > 1 routes through ``multiprocessing.Pool``. ``today_fn``
    is resolved ONCE in the main process and passed to workers via the
    Pool initializer so unpicklable lambdas are safe.

    show_progress=True wraps the iteration in tqdm for a per-cell bar —
    cheap, optional; tqdm is in requirements.txt for the prefetch script
    already.
    """
    if run_id is None:
        run_id = _compute_run_id(
            strategies, symbols, expiries, entry_offsets_td, exit_offsets_td,
        )
    path = RESULTS_DIR / f"sweep_{run_id}.parquet"

    if path.exists() and not force:
        return pd.read_parquet(path)

    # Enumerate tasks in deterministic order — sorted across every axis.
    # Single-threaded loop matches this order; parallel pool sorts results
    # post-hoc (via the canonical-key sort below) so worker completion
    # order doesn't matter for output.
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
    skipped: list[dict] = []

    def _handle(task_args: tuple, result) -> None:
        s, sym, exp, eo, xo = task_args
        if isinstance(result, str) and result.startswith("skip:"):
            skipped.append({
                "run_id": run_id,
                "strategy": s,
                "symbol": sym,
                "expiry": pd.Timestamp(exp),
                "entry_offset_td": int(eo),
                "exit_offset_td": int(xo),
                "skip_reason": result[len("skip:"):],
            })
            return
        if result is None:
            return
        result["run_id"] = run_id
        rows.append(result)

    if n_workers > 1:
        today_date = today_fn()
        worker_args = [(s, sym, exp, eo, xo, offline) for (s, sym, exp, eo, xo) in tasks]
        # chunksize keeps Pool scheduling efficient for 100k+-task sweeps;
        # too small → IPC overhead, too large → poor work-stealing at tail
        chunksize = max(1, len(worker_args) // (n_workers * 32))
        with mp.Pool(
            processes=n_workers,
            initializer=_worker_init,
            initargs=(today_date,),
        ) as pool:
            it = pool.imap_unordered(_worker_run, worker_args, chunksize=chunksize)
            if show_progress:
                from tqdm import tqdm
                it = tqdm(it, total=len(worker_args), desc="sweep", unit="cell")
            for (task_args, result) in it:
                _handle(task_args, result)
    else:
        it = tasks
        if show_progress:
            from tqdm import tqdm
            it = tqdm(it, total=len(tasks), desc="sweep", unit="cell")
        for (s, sym, exp, eo, xo) in it:
            result = sweep_one(
                s, sym, exp, eo, xo,
                today_fn=today_fn, offline=offline,
            )
            _handle((s, sym, exp, eo, xo), result)

    if not rows:
        # Empty sweep — preserve canonical column schema so downstream
        # consumers don't trip on missing columns. (Reviewer flag from 185a9cb.)
        df = _results.empty_results_frame()
    else:
        df = pd.DataFrame(rows)
        # Determinism: sort by canonical key tuple + reset_index
        df = df.sort_values(
            ["strategy", "symbol", "expiry", "entry_offset_td", "exit_offset_td"]
        ).reset_index(drop=True)
        # Canonical column order so the returned in-memory frame is
        # `assert_frame_equal`-clean against the parquet we just wrote.
        df = _results.canonical_column_order(df)

    _results.write_results(df, run_id=run_id)
    _results.write_skips(skipped, run_id=run_id)  # no-op if list empty
    return df
