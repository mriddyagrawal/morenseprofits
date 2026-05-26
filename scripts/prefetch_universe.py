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
from src.data.errors import MissingDataError  # noqa: E402


# ============================================================
# Defaults
# ============================================================
DEFAULT_SYMBOLS = [
    # Top-10 NSE F&O blue chips by historical liquidity. Operator
    # can override with --symbols flag.
    "RELIANCE",   "HDFCBANK",   "ICICIBANK",  "INFY",       "TCS",
    "SBIN",       "AXISBANK",   "KOTAKBANK",  "BHARTIARTL", "LT",
]

DEFAULT_STRIKES_PER_SIDE = 6   # ATM + 6 above + 6 below = 13 strikes
DEFAULT_START = date(2024, 5, 1)
DEFAULT_END = date(2026, 5, 31)
TODAY_FN = lambda: date(2026, 5, 25)


def _h(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


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


def _strikes_around_atm(strike_grid: list[int], spot: float, per_side: int) -> list[int]:
    """Pick ``2*per_side + 1`` strikes from ``strike_grid`` centered
    on ``spot``: the ATM strike (nearest to spot) plus per_side strikes
    above and below.

    Edge cases:
      - Grid has fewer than 2*per_side+1 strikes → return all of them.
      - ATM is near the edge of the grid → still return up to
        2*per_side+1 strikes (just biased to the available side).
    """
    if not strike_grid:
        return []
    sorted_strikes = sorted(strike_grid)
    # Find ATM index (nearest to spot)
    atm_idx = min(
        range(len(sorted_strikes)),
        key=lambda i: (abs(sorted_strikes[i] - spot), sorted_strikes[i]),
    )
    lo = max(0, atm_idx - per_side)
    hi = min(len(sorted_strikes), atm_idx + per_side + 1)
    return sorted_strikes[lo:hi]


# ============================================================
# Per-pair worker — used by both the serial loop and mp.Pool.
# Module-level (not closure) so mp.spawn can pickle it.
# ============================================================
def _process_pair(args_tuple: tuple) -> tuple[int, int, int, list]:
    """Process one (symbol, expiry) pair: pick strikes around the
    reference-day ATM, fetch CE + PE for each, return per-pair counts +
    skip-log entries. Catches every exception locally so a Pool worker
    can't bring down the whole prefetch on a single bad contract.

    args_tuple: (symbol, expiry, strikes_per_side, today_iso) — all
    primitives so multiprocessing.spawn pickling works on macOS.
    """
    import pandas as pd  # worker-local; spawn re-imports anyway
    sym, exp, strikes_per_side, today_iso = args_tuple
    today_fn = lambda: date.fromisoformat(today_iso)

    n_fetched = 0
    n_skipped_missing = 0
    n_skipped_other = 0
    skips: list[tuple[str, date, int, str, str]] = []

    try:
        # Walk back from expiry-1d to find a usable bhavcopy.
        bc = None
        ref_day = exp - timedelta(days=1)
        for delta in range(1, 10):
            cand = exp - timedelta(days=delta)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    bc = bhavcopy_fo_loader.load_bhavcopy_fo(cand)
                ref_day = cand
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

        spot_df = spot_loader.load_spot(sym, ref_day, ref_day, today_fn=today_fn)
        if spot_df.empty:
            skips.append((sym, exp, 0, "all", "no spot at ref_day"))
            return 0, 0, 1, skips
        spot = float(spot_df.iloc[0]["close"])

        picked_strikes = _strikes_around_atm(strike_grid, spot, strikes_per_side)

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
                    skips.append((sym, exp, strike, opt_type, str(e)[:80]))
                except Exception as e:
                    n_skipped_other += 1
                    skips.append((
                        sym, exp, strike, opt_type,
                        f"{type(e).__name__}: {str(e)[:80]}",
                    ))
    except Exception as e:
        n_skipped_other += 1
        skips.append((sym, exp, 0, "all", f"{type(e).__name__}: {str(e)[:80]}"))

    return n_fetched, n_skipped_missing, n_skipped_other, skips


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--symbols", nargs="+", default=DEFAULT_SYMBOLS,
        help=f"NSE F&O symbols (default: top-10 blue chips: {DEFAULT_SYMBOLS})",
    )
    ap.add_argument(
        "--strikes-per-side", type=int, default=DEFAULT_STRIKES_PER_SIDE,
        help=f"Strikes above + below ATM each (default {DEFAULT_STRIKES_PER_SIDE}; "
             f"total = 2*N + 1 with ATM)",
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
    n_strikes = 2 * args.strikes_per_side + 1

    _h(f"Pre-cache universe — {len(symbols)} symbols × ~24 expiries × "
       f"{n_strikes} strikes × 2 option_types")
    print(f"  symbols          = {symbols}")
    print(f"  strikes_per_side = {args.strikes_per_side}  → {n_strikes} strikes/expiry")
    print(f"  expiry range     = {args.start} → {args.end}")
    print(f"  cache dir        = data/cache/options/  (gitignored)")

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
    # Step 3 — build per-symbol expiry list
    # ============================================================
    _h("Step 3 — build expiry list per symbol")
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
    _h("Step 4 — fetch CE + PE for ATM ± N strikes per (symbol, expiry)")
    expected_contracts = total_pairs * n_strikes * 2
    print(f"  expected contracts: {expected_contracts}")
    print(f"  (cache-first — already-cached contracts skip immediately)")

    n_fetched = 0
    n_skipped_missing = 0
    n_skipped_other = 0
    skip_log: list[tuple[str, date, int, str, str]] = []

    work_units = [
        (sym, exp) for sym, exps in expiries_by_symbol.items() for exp in exps
    ]

    if args.workers > 1:
        # Parallel path. Each worker is a fresh process; spawns its own
        # NSE Session per call (inside options_loader._direct_derivatives_df).
        # imap_unordered streams results as workers finish so tqdm advances
        # smoothly.
        worker_args = [
            (sym, exp, args.strikes_per_side, TODAY_FN().isoformat())
            for (sym, exp) in work_units
        ]
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
        for sym, exp in tqdm(work_units, desc="(symbol, expiry)", unit="pair"):
            pair_n_fetched, pair_n_miss, pair_n_other, pair_skips = _process_pair(
                (sym, exp, args.strikes_per_side, TODAY_FN().isoformat()),
            )
            n_fetched += pair_n_fetched
            n_skipped_missing += pair_n_miss
            n_skipped_other += pair_n_other
            skip_log.extend(pair_skips)

    # ============================================================
    # Summary
    # ============================================================
    t_total = time.perf_counter() - t_start
    _h(f"DONE — {t_total/60:.1f} min ({t_total:.0f}s)")
    print(f"  contracts loaded (cache-hit or fresh): {n_fetched}/{expected_contracts}")
    print(f"  skipped (missing data): {n_skipped_missing}")
    print(f"  skipped (other errors): {n_skipped_other}")
    if skip_log:
        print(f"\n  First few skips:")
        for sym, exp, strike, opt, reason in skip_log[:10]:
            print(f"    {sym} {exp} {strike}-{opt}: {reason}")

    return 0 if (n_skipped_other + n_skipped_missing) < 0.1 * expected_contracts else 1


if __name__ == "__main__":
    raise SystemExit(main())
