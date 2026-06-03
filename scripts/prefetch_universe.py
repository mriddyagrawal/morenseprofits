"""Pre-cache NSE options data so future sweeps / heatmap-expansions
land cache-only with no network calls.

For each (symbol, monthly expiry) in the date range:
  - Read the bhavcopy on a reference day mid-cycle to get the
    available strike grid + the spot at that day.
  - Pick ATM + N strikes above + N strikes below = (2*N + 1) strikes.
  - Fetch CE + PE for each → (2*N + 1) × 2 contracts per (symbol, expiry).

Resumable: every fetch goes through ``options_loader.load_option``
which is cache-first. If the script dies mid-run, just re-run — it'll
skip cached contracts and only fetch the gaps.

Defaults are conservative — small enough for a ~2-hour run on a
laptop with NSE's 0.5s politeness delay. Override via CLI flags for
bigger scopes.

Usage:
    python scripts/prefetch_universe.py
    python scripts/prefetch_universe.py --symbols RELIANCE INFY --strikes-per-side 5
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
import time
import warnings
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tqdm import tqdm  # noqa: E402

from src.data import bhavcopy_fo_loader, expiry_calendar, options_loader, spot_loader, trading_calendar  # noqa: E402
from src.data.strike_planner import strikes_around_spot_hybrid  # noqa: E402
from src.data.errors import MissingDataError  # noqa: E402


# ============================================================
# Defaults
# ============================================================
def _build_default_symbols() -> list[str]:
    """48 NSE blue chips (sourced from src.universe.blue_chip — the
    canonical universe list) + PNB + BHEL = 50 symbols. Neither extra
    is in the blue-chip 48; both were explicitly added by the operator
    (public-sector industrials outside the NIFTY-50-derived list).

    Computed at import time so the universe stays in lockstep with
    src/universe/blue_chip.py — no drift if the blue-chip list ever
    updates. Operator can still override the full list with --symbols."""
    from datetime import date as _date
    from src.universe.blue_chip import blue_chip
    return blue_chip(_date.today()) + ["PNB", "BHEL"]


DEFAULT_SYMBOLS = _build_default_symbols()

DEFAULT_STRIKES_PER_SIDE = 6      # min strikes each side of ATM (per-day rule)
DEFAULT_STRIKES_PCT = 0.05        # min %-of-spot window around ATM (per-day rule)
DEFAULT_ENTRY_WINDOW_DAYS = 70    # calendar days back from expiry to scan spot
                                  # (~45 trading days; the sweep's T-45..T-1 grid
                                  # depth — strikes the strategy could pick across
                                  # any entry in that window must be cached)
DEFAULT_START = date(2024, 5, 1)
DEFAULT_END = date(2026, 5, 31)
TODAY_FN = lambda: date(2026, 5, 25)


def _h(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


def _lot_sizes_needs_rebuild(
    parquet_path: Path, sibling_dir: Path,
) -> tuple[bool, str]:
    """Return ``(rebuild?, reason)`` for Step 2b's unified-cache
    auto-build gate. Replaces the prior ``not parquet.exists()``-only
    check that missed the staleness case empirically observed on
    2026-06-03: ``data/cache/lot_sizes.parquet`` had 4 BHEL rows from
    the sidecar-only era while ``bhavcopy_fo_lot_sizes/`` had all 25
    BHEL year-months, but the exists-guard took the cache-hit path
    and 805/9392 contracts got skipped as `lot_size excluded`.

    Triggers a rebuild when:

      - the unified parquet is missing (fresh clone or operator nuke);
      - any sibling per-date lot-size parquet in ``sibling_dir`` has
        an mtime newer than the unified parquet (operator fetched
        new bhavcopies after the last unified build — the new
        per-date sibling carries year-months the unified cache won't
        have).

    Does NOT do a row-by-row coverage check (more expensive, same
    end-state in 99% of operator flows because the only way to add
    a year-month tuple is to fetch a new bhavcopy, which always
    bumps the sibling mtime). The mtime check is the cheapest
    defensible heuristic per the architectural reviewer's
    Plan A.1 spec.
    """
    if not parquet_path.exists():
        return True, f"{parquet_path} missing"
    if not sibling_dir.exists():
        # No siblings to compare against; the unified cache is the
        # only thing we have, so trust it (rebuild is a no-op).
        return False, "no sibling dir to compare against"
    parquet_mtime = parquet_path.stat().st_mtime
    newer_count = 0
    first_newer: str | None = None
    for child in sibling_dir.iterdir():
        if not child.is_file() or child.suffix != ".parquet":
            continue
        if child.stat().st_mtime > parquet_mtime:
            newer_count += 1
            if first_newer is None:
                first_newer = child.name
    if newer_count > 0:
        return True, (
            f"{newer_count} sibling parquet(s) in "
            f"{sibling_dir.name}/ have mtime > unified cache "
            f"(first: {first_newer})"
        )
    return False, "up-to-date vs sibling cache"


def _pick_reference_day(expiry: date, bhavcopy_dates: list[date]) -> date | None:
    """Pick a mid-cycle reference day for an expiry — used to read
    the strike grid + spot. We want a day that:
      - Is BEFORE the expiry (NSE archives the option from expiry-day
        bhavcopy too, but cleaner to use a pre-expiry day).
      - Has bhavcopy data available.
      - Is roughly mid-cycle so the strike grid + spot reflect
        typical contract conditions.

    Picks: latest available bhavcopy day in [expiry-25d, expiry-1d].
    Falls back to the latest available day <= expiry if no mid-cycle
    bhavcopy exists yet.
    """
    target_start = expiry - timedelta(days=25)
    target_end = expiry - timedelta(days=1)
    mid_cycle = [d for d in bhavcopy_dates if target_start <= d <= target_end]
    if mid_cycle:
        return max(mid_cycle)
    earlier = [d for d in bhavcopy_dates if d <= expiry]
    if earlier:
        return max(earlier)
    return None


# ============================================================
# Per-pair worker — used by both the serial loop and mp.Pool.
# Module-level (not closure) so mp.spawn can pickle it.
# ============================================================
def _process_pair(args_tuple: tuple) -> tuple[int, int, int, list]:
    """Process one (symbol, expiry) pair: scan the spot history across
    the entry window, compute hybrid (N per side, X% range) strikes per
    day, union the picks, fetch CE + PE for the union. Catches every
    exception locally so a Pool worker can't bring down the whole
    prefetch on a single bad contract.

    Why daily-union: the sweep prices entries up to T-45 days before
    expiry using THAT day's spot to pick the strategy's strike (SPECS
    §5). When spot drifts across the window, the strikes the strategy
    picks span a wider range than any single reference day's ATM ± N.
    Union'ing over the window guarantees cache coverage for every cell
    the sweep will price.

    args_tuple: (symbol, expiry, strikes_per_side, strikes_pct,
    entry_window_days, today_iso) — all primitives so
    multiprocessing.spawn pickling works on macOS.
    """
    import pandas as pd  # worker-local; spawn re-imports anyway
    sym, exp, strikes_per_side, strikes_pct, entry_window_days, today_iso = args_tuple
    today_fn = lambda: date.fromisoformat(today_iso)

    n_fetched = 0
    n_skipped_missing = 0
    n_skipped_other = 0
    skips: list[tuple[str, date, int, str, str]] = []

    try:
        # Walk back from expiry-1d to find a usable bhavcopy as the
        # canonical strike grid. (Strikes only get added over time, so
        # the near-expiry bhavcopy has the superset of strikes the
        # strategy could possibly pick across the entry window.)
        bc = None
        for delta in range(1, 10):
            cand = exp - timedelta(days=delta)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    bc = bhavcopy_fo_loader.load_bhavcopy_fo(cand)
                break
            except MissingDataError:
                continue
        if bc is None:
            skips.append((sym, exp, 0, "all", "no bhavcopy near expiry"))
            return 0, 0, 1, skips

        mask = (
            (bc["symbol"] == sym.upper())
            & (bc["instrument"] == "OPTSTK")
            & (bc["expiry"] == pd.Timestamp(exp))
            & (bc["option_type"].isin(["CE", "PE"]))
        )
        strike_grid = sorted({int(s) for s in bc.loc[mask, "strike"].dropna().tolist()})
        if not strike_grid:
            skips.append((sym, exp, 0, "all", "no strikes in bhavcopy"))
            return 0, 0, 1, skips

        # Spot history across the entry window. load_spot naturally
        # filters to trading days only (the spot parquet has 1 row per
        # trading day).
        window_start = exp - timedelta(days=entry_window_days)
        window_end = exp - timedelta(days=1)
        spot_df = spot_loader.load_spot(sym, window_start, window_end, today_fn=today_fn)
        if spot_df.empty:
            skips.append((sym, exp, 0, "all", "no spot in entry window"))
            return 0, 0, 1, skips

        # For each day in the window, compute the hybrid strike set the
        # strategy could pick if entry were on that day. Union across all
        # days = the cache-coverage set we need.
        picked: set[int] = set()
        for close in spot_df["close"].astype(float).tolist():
            picked.update(
                strikes_around_spot_hybrid(
                    strike_grid, close,
                    per_side=strikes_per_side,
                    pct_window=strikes_pct,
                )
            )
        picked_strikes = sorted(picked)

        for strike in picked_strikes:
            for opt_type in ("CE", "PE"):
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        options_loader.load_option(
                            symbol=sym, expiry=exp,
                            strike=float(strike), option_type=opt_type,
                            from_date=exp - timedelta(days=120),
                            to_date=min(exp, today_fn()),
                            today_fn=today_fn,
                        )
                    n_fetched += 1
                except MissingDataError as e:
                    n_skipped_missing += 1
                    skips.append((sym, exp, strike, opt_type, str(e)[:200]))
                except Exception as e:
                    n_skipped_other += 1
                    skips.append((
                        sym, exp, strike, opt_type,
                        f"{type(e).__name__}: {str(e)[:200]}",
                    ))
    except Exception as e:
        n_skipped_other += 1
        skips.append((sym, exp, 0, "all", f"{type(e).__name__}: {str(e)[:200]}"))

    return n_fetched, n_skipped_missing, n_skipped_other, skips


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--symbols", nargs="+", default=DEFAULT_SYMBOLS,
        help=f"NSE F&O symbols (default: top-10 blue chips: {DEFAULT_SYMBOLS})",
    )
    ap.add_argument(
        "--strikes-per-side", type=int, default=DEFAULT_STRIKES_PER_SIDE,
        help=f"Min strikes each side of ATM per day (default "
             f"{DEFAULT_STRIKES_PER_SIDE}). Combined with --strikes-pct "
             f"via max() — wider rule wins.",
    )
    ap.add_argument(
        "--strikes-pct", type=float, default=DEFAULT_STRIKES_PCT,
        help=f"Min %-of-spot window each side of ATM per day "
             f"(default {DEFAULT_STRIKES_PCT}). Combined with "
             f"--strikes-per-side via max().",
    )
    ap.add_argument(
        "--entry-window-days", type=int, default=DEFAULT_ENTRY_WINDOW_DAYS,
        help=f"Calendar days before expiry to scan for spot history; "
             f"strikes the strategy could pick on any day in that window "
             f"are union'd and cached (default {DEFAULT_ENTRY_WINDOW_DAYS}, "
             f"~45 trading days = the sweep grid depth).",
    )
    ap.add_argument(
        "--start", type=lambda s: date.fromisoformat(s),
        default=DEFAULT_START.isoformat(),
        help=f"Expiry range start (ISO date, default {DEFAULT_START.isoformat()})",
    )
    ap.add_argument(
        "--end", type=lambda s: date.fromisoformat(s),
        default=DEFAULT_END.isoformat(),
        help=f"Expiry range end (ISO date, default {DEFAULT_END.isoformat()})",
    )
    ap.add_argument(
        "--bulk-bhavcopies", action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Bulk-fetch ALL trading-day bhavcopies in the date range "
            "(default: on). Future-proofs the cache for any sweep grid "
            "later. Cheap (~13 min for a 2-year window, ~250MB disk). "
            "Pass --no-bulk-bhavcopies for cherry-pick behavior."
        ),
    )
    ap.add_argument(
        "--engine-source", choices=["bhavcopy", "api"],
        default="bhavcopy",
        help=(
            "Source for per-contract option EOD parquets. "
            "bhavcopy (default; MIGRATION.md §Phase 1): scan cached "
            "daily bhavcopies + materialize per-contract parquets "
            "from the unified lot_sizes cache. api (legacy): fetch "
            "per-contract via NSE direct API + jugaad. The legacy "
            "path is retained through the cutover-validation window "
            "(MIGRATION.md §P1.6 smoke gate) and deprecated in P1.8."
        ),
    )
    ap.add_argument(
        "--rebuild-lot-sizes", action="store_true",
        help=(
            "Force-rebuild the unified data/cache/lot_sizes.parquet "
            "even if it already exists. Default behavior is "
            "auto-build when missing only. See MIGRATION.md §Phase 0 "
            "P0.2."
        ),
    )
    ap.add_argument(
        "--workers", type=int, default=1,
        help=(
            "Parallelize the per-(symbol, expiry) fetch loop (default 1 "
            "= serial, current behavior). Start at 2 to validate that "
            "NSE doesn't WAF-throttle; the sweep saw 8 workers cause "
            "problems but 1 was clean — anything in-between is empirically "
            "untested. Each worker holds its own NSE session + politeness "
            "sleep, so aggregate request rate ≈ workers / 0.5s."
        ),
    )
    args = ap.parse_args()

    symbols: list[str] = args.symbols

    _h(f"Pre-cache universe — {len(symbols)} symbols × ~24 expiries")
    print(f"  symbols           = {symbols}")
    print(f"  strikes_per_side  = {args.strikes_per_side}  (per-day rule, min N strikes each side of ATM)")
    print(f"  strikes_pct       = {args.strikes_pct:.2%}  (per-day rule, min %-of-spot window each side)")
    print(f"  entry_window_days = {args.entry_window_days}  (calendar days back from expiry to scan spot)")
    print(f"  workers           = {args.workers}  (>1 → parallel mp.Pool over (sym, expiry) pairs)")
    print(f"  expiry range      = {args.start} → {args.end}")
    print(f"  cache dir         = data/cache/options/  (gitignored)")

    t_start = time.perf_counter()

    # ============================================================
    # Step 1 — pre-warm spot data for every symbol × year in range
    # ============================================================
    _h("Step 1 — pre-warm spot data")
    years = list(range(args.start.year, args.end.year + 1))
    spot_targets = [(sym, y) for sym in symbols for y in years]
    n_spot_fetched = 0
    spot_skips: list[tuple[str, int, str]] = []
    for sym, year in tqdm(spot_targets, desc="spot", unit="year-symbol"):
        try:
            jan1 = date(year, 1, 1)
            dec31 = date(year, 12, 31)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                spot_loader.load_spot(sym, jan1, dec31, today_fn=TODAY_FN)
            n_spot_fetched += 1
        except Exception as e:
            spot_skips.append((sym, year, type(e).__name__))
    print(f"  spot warmed: {n_spot_fetched}/{len(spot_targets)}; skips: {len(spot_skips)}")
    if spot_skips:
        for sym, y, err in spot_skips[:5]:
            print(f"    skip: {sym} {y} ({err})")

    # ============================================================
    # Step 2 — bulk-fetch all trading-day bhavcopies (optional)
    # ============================================================
    # Why bulk? Bhavcopies are shared across all 40 symbols (one zip
    # per trading day contains every option contract). Fetching them
    # all up-front future-proofs the cache for ANY sweep grid the
    # operator runs later — extended heatmaps (T-40 entries), deeper
    # OTM strategies, regime-filtered re-sweeps. Cheap relative to
    # the per-contract options fetch.
    #
    # Trading days are derived from RELIANCE's spot data via
    # trading_calendar — requires Step 1's spot warming to have run.
    if args.bulk_bhavcopies:
        _h("Step 2 — bulk-fetch trading-day bhavcopies")
        try:
            tdays = trading_calendar.trading_days(
                args.start, args.end, today_fn=TODAY_FN,
            )
            print(f"  trading days in range: {len(tdays)}")
        except Exception as e:
            print(f"  ⚠ couldn't build trading-day list ({type(e).__name__}: {e})")
            print(f"  skipping bulk-bhavcopy step; "
                  f"strike-discovery in Step 4 will lazily fetch as needed")
            tdays = []

        n_bhav_fetched = 0
        n_bhav_skipped = 0
        for td in tqdm(tdays, desc="bhavcopies", unit="day"):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    bhavcopy_fo_loader.load_bhavcopy_fo(td)
                n_bhav_fetched += 1
            except Exception as e:
                n_bhav_skipped += 1
        print(f"  bhavcopies loaded (cache-hit or fresh): {n_bhav_fetched}/{len(tdays)}")
        if n_bhav_skipped:
            print(f"  skipped: {n_bhav_skipped} (typically NSE holidays / no-data days)")
    else:
        _h("Step 2 — bulk-fetch trading-day bhavcopies  [SKIPPED via --no-bulk-bhavcopies]")
        print(f"  strike-discovery in Step 4 will lazily fetch bhavcopies as needed")

    # ============================================================
    # Step 2b — auto-build unified lot_sizes parquet (MIGRATION.md
    # §Phase 0 P0.2). Runs after the bhavcopy fetch loop so the
    # sibling per-date lot-size caches (written by
    # bhavcopy_fo_loader) exist on disk. Halts loudly on any
    # CrossSourceLotSizeMismatchError — no Step 3+ work runs against
    # a missing/stale unified cache.
    # ============================================================
    from src.data import cache as _cache  # local import for clarity
    from scripts.build_lot_size_parquet import build_lot_size_parquet

    lot_sizes_parquet = _cache.lot_sizes_path()
    sibling_dir = lot_sizes_parquet.parent / "bhavcopy_fo_lot_sizes"
    needs_rebuild, rebuild_reason = _lot_sizes_needs_rebuild(
        lot_sizes_parquet, sibling_dir,
    )
    if needs_rebuild or args.rebuild_lot_sizes:
        if args.rebuild_lot_sizes:
            _h("Step 2b — build unified lot_sizes.parquet  "
               "[--rebuild-lot-sizes]")
        else:
            _h(f"Step 2b — build unified lot_sizes.parquet  "
               f"[auto-trigger: {rebuild_reason}]")
        # Build emits per-pair exclusion diagnostics inline (see
        # scripts/build_lot_size_parquet.py + MIGRATION.md
        # §Cross-source lot-size policy). The build returns
        # successfully even when N (sym, expiry-month) pairs are
        # excluded — those become structural skips at sweep time
        # via MissingTurnoverError. Only real errors (parse
        # failure, missing source dir) escape as exceptions and
        # halt the prefetch.
        build_lot_size_parquet(verbose=True)
    else:
        _h(f"Step 2b — unified lot_sizes.parquet  "
           f"[cache hit: {lot_sizes_parquet}]")
        print(
            f"  Pass --rebuild-lot-sizes to force-rebuild "
            f"(e.g. after adding a new sidecar fixture)."
        )

    # ============================================================
    # Step 3 — bhavcopy-only fast path (MIGRATION.md §Phase 1 P1.5)
    # ============================================================
    # In `--engine-source bhavcopy` mode (default), enumerate every
    # (sym, expiry, strike, option_type) that actually traded in the
    # cached bhavcopy window for our symbol list, then materialize
    # per-contract parquets via the bhavcopy_to_contract transform.
    # The legacy strike_planner / spot-scan / per-contract NSE fetch
    # path (Steps 3 + 4 below) is preserved for `--engine-source api`
    # through the cutover-validation window (P1.6 smoke gate).

    if args.engine_source == "bhavcopy":
        from src.data.bhavcopy_to_contract import materialize_contracts_batch

        # Bhavcopy scan window matches Step 2's bulk-fetch range.
        bhav_scan_from = args.start
        bhav_scan_to = args.end

        _h(f"Step 3+4 — batch-materialize per-contract parquets from cached bhavcopies  "
           f"[--engine-source bhavcopy; scan {bhav_scan_from} → {bhav_scan_to}]")
        print(f"  single-pass over the bhavcopy cache (was per-contract loop; ~500-1000× speedup)")

        # Lightweight progress: print at ~5% intervals. The whole
        # batch typically completes in seconds for a 4-symbol smoke;
        # heavier universes get coarse-grained feedback.
        last_pct = [-1]
        def _progress(processed: int, total: int) -> None:
            pct = (processed * 100) // max(total, 1)
            if pct >= last_pct[0] + 5:
                last_pct[0] = pct
                print(f"    [{pct:>3}%] {processed}/{total} contracts processed")

        counts = materialize_contracts_batch(
            symbols=symbols,
            from_date=bhav_scan_from,
            to_date=bhav_scan_to,
            progress_callback=_progress,
        )

        _h("Done — bhavcopy-only materialize results")
        print(f"  materialized:                  {counts['materialized']}")
        print(f"  already cached (skipped):      {counts['already_cached']}")
        print(f"  skipped (MissingTurnoverError): {counts['skipped_missing_turnover']}")
        print(f"  skipped (other):               {counts['skipped_other']}")
        if counts["skip_log"][:10]:
            print(f"\n  first 10 skip reasons:")
            for (sym, exp, strike, opt, reason) in counts["skip_log"][:10]:
                print(f"    {sym} {exp} {strike:g}{opt}: {reason}")
        return 0

    # ============================================================
    # Step 3 — build per-symbol expiry list  (--engine-source api)
    # ============================================================
    _h("Step 3 — build expiry list per symbol  [--engine-source api]")
    expiries_by_symbol: dict[str, list[date]] = {}
    for sym in tqdm(symbols, desc="expiries", unit="symbol"):
        try:
            exps = expiry_calendar.monthly_expiries(sym, args.start, args.end)
            expiries_by_symbol[sym] = exps
        except Exception as e:
            print(f"  ⚠ {sym}: failed to load expiries ({type(e).__name__}: {e})")
            expiries_by_symbol[sym] = []
    total_pairs = sum(len(v) for v in expiries_by_symbol.values())
    print(f"  total (symbol, expiry) pairs: {total_pairs}")

    # ============================================================
    # Step 4 — for each (symbol, expiry), pick strikes + fetch
    # ============================================================
    _h("Step 4 — daily spot-scan → union strikes → fetch CE + PE per (symbol, expiry)")
    print(f"  per-pair contract count varies (depends on spot drift across the entry window)")
    print(f"  (cache-first — already-cached contracts skip immediately)")

    n_fetched = 0
    n_skipped_missing = 0
    n_skipped_other = 0
    skip_log: list[tuple[str, date, int, str, str]] = []

    work_units = [
        (sym, exp) for sym, exps in expiries_by_symbol.items() for exp in exps
    ]

    worker_args = [
        (sym, exp, args.strikes_per_side, args.strikes_pct,
         args.entry_window_days, TODAY_FN().isoformat())
        for (sym, exp) in work_units
    ]

    if args.workers > 1:
        # Parallel path. Each worker is a fresh process; spawns its own
        # NSE Session per call (inside options_loader._direct_derivatives_df).
        # imap_unordered streams results as workers finish so tqdm advances
        # smoothly.
        with mp.Pool(processes=args.workers) as pool:
            it = pool.imap_unordered(_process_pair, worker_args, chunksize=1)
            for pair_n_fetched, pair_n_miss, pair_n_other, pair_skips in tqdm(
                it, total=len(worker_args), desc="(symbol, expiry)", unit="pair",
            ):
                n_fetched += pair_n_fetched
                n_skipped_missing += pair_n_miss
                n_skipped_other += pair_n_other
                skip_log.extend(pair_skips)
    else:
        for arg in tqdm(worker_args, desc="(symbol, expiry)", unit="pair"):
            pair_n_fetched, pair_n_miss, pair_n_other, pair_skips = _process_pair(arg)
            n_fetched += pair_n_fetched
            n_skipped_missing += pair_n_miss
            n_skipped_other += pair_n_other
            skip_log.extend(pair_skips)

    # ============================================================
    # Summary
    # ============================================================
    t_total = time.perf_counter() - t_start
    _h(f"DONE — {t_total/60:.1f} min ({t_total:.0f}s)")
    total_attempts = n_fetched + n_skipped_missing + n_skipped_other
    print(f"  contracts loaded (cache-hit or fresh): {n_fetched}/{total_attempts}")
    print(f"  skipped (missing data): {n_skipped_missing}")
    print(f"  skipped (other errors): {n_skipped_other}")
    if skip_log:
        print(f"\n  First few skips:")
        for sym, exp, strike, opt, reason in skip_log[:10]:
            print(f"    {sym} {exp} {strike}-{opt}: {reason}")

    return 0 if (n_skipped_other + n_skipped_missing) < 0.1 * max(total_attempts, 1) else 1


if __name__ == "__main__":
    raise SystemExit(main())
