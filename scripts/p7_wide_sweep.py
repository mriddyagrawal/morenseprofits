"""Phase 7 — wide-grid sweep for full-resolution heatmap.

Universe matches the prefetch (10 blue chips × 25 monthly expiries
2024-05 → 2026-05 × 3 short-vol strategies) with the entry/exit grid
expanded to 45 × 16 — covering T-45 to T-1 entry and T-15 to T-0 exit.

Cells planned: 10 syms × 3 strats × ~25 expiries × ~600 valid (e,x)
pairs (entry > exit) ≈ 450,000 cells. Expected wall-clock ~10-15 min
on 8 workers with a fully-warm cache (every contract pre-fetched by
scripts/prefetch_universe.py).

Heatmap UI auto-adapts via render_heatmaps reading whatever offsets
are present in the sweep parquet — no Streamlit code changes needed.
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Suppress the noisy options_loader "dropped N partial row(s)" UserWarning
# from drowning out tqdm's progress bar. The warning is informational —
# it fires once per NSE fetch when settlement-only rows are filtered out.
# Workers re-set this filter via sweeper._worker_init since spawn() doesn't
# inherit warning state.
warnings.filterwarnings(
    "ignore",
    message=r".*dropped \d+ partial row.*",
    category=UserWarning,
)

from src.data import bhavcopy_fo_loader, expiry_calendar, options_loader, spot_loader  # noqa: E402
from src.engine.sweeper import _compute_run_id, sweep_grid  # noqa: E402


def _build_symbols() -> list[str]:
    """48 NSE blue chips (sourced from src.universe.blue_chip) + PNB
    + BHEL = 50 symbols. Mirrors scripts/prefetch_universe.py's
    DEFAULT_SYMBOLS so the sweep universe and the prefetch universe
    stay in lockstep — sweep against a stock that wasn't prefetched
    would just produce OfflineCacheMiss skips for every cell."""
    from src.universe.blue_chip import blue_chip
    return blue_chip(date.today()) + ["PNB", "BHEL"]


SYMBOLS = _build_symbols()   # 50 symbols (48 blue chips + PNB + BHEL)
STRATEGIES = ["short_straddle", "short_strangle", "iron_condor"]
ENTRY_OFFSETS_TD = list(range(1, 46))   # T-45 ... T-1
EXIT_OFFSETS_TD = list(range(0, 16))    # T-0  ... T-15
EXPIRY_FROM = date(2024, 5, 1)
EXPIRY_TO = date(2026, 5, 31)
WALL_TODAY = date(2026, 5, 26)   # actual calendar today (used for walk-back start)
N_WORKERS = 8   # M1 Max has 8 perf cores; efficiency cores add little


def _resolve_anchor_date(start: date, max_back: int = 7) -> date:
    """Find the most recent date with a usable bhavcopy on NSE.

    Why: NSE publishes today's F&O bhavcopy AFTER market close
    (~6 PM IST). Pre-market-close runs, weekends, and holidays all
    fail load_bhavcopy_fo(today). Walking back to the latest usable
    day gives us a date where both:

      (a) the bhavcopy strike-enumeration succeeds (pre-warm works),
      (b) cached contract max_date most likely matches → workers'
          open-expiry staleness check passes → no NSE during sweep.

    Returns the anchor date; raises RuntimeError if no bhavcopy in
    the past `max_back` days (e.g. NSE outage)."""
    for offset in range(max_back + 1):
        cand = start - timedelta(days=offset)
        try:
            bhavcopy_fo_loader.load_bhavcopy_fo(cand)
            return cand
        except Exception:
            continue
    raise RuntimeError(
        f"no usable F&O bhavcopy in last {max_back} days from {start}; "
        f"NSE outage or pre-warm cannot proceed"
    )


def _h(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Phase-7 wide-grid sweep. Defaults run the full 50-symbol "
            "universe; --symbols accepts a subset for smoke testing."
        ),
    )
    p.add_argument(
        "--symbols", nargs="+", default=SYMBOLS,
        help=(
            "NSE symbols to sweep (space-separated). Default: full "
            "50-symbol universe (48 blue chips + PNB + BHEL). "
            "Mirrors scripts/prefetch_universe.py's --symbols — pass "
            "the same list to both scripts to keep prefetch and "
            "sweep universes in lockstep (sweep against a non-"
            "prefetched stock yields OfflineCacheMiss skips)."
        ),
    )
    p.add_argument(
        "--workers", type=int, default=N_WORKERS,
        help=f"Worker process count (default: {N_WORKERS}).",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    symbols: list[str] = args.symbols
    n_workers: int = args.workers
    _h("Phase-7 wide-grid sweep — heatmap 45×16")
    print(f"  symbols     = {symbols}  (n={len(symbols)})")
    print(f"  strategies  = {STRATEGIES}")
    print(f"  entry_td    = T-{min(ENTRY_OFFSETS_TD)} … T-{max(ENTRY_OFFSETS_TD)} ({len(ENTRY_OFFSETS_TD)} values)")
    print(f"  exit_td     = T-{min(EXIT_OFFSETS_TD)} … T-{max(EXIT_OFFSETS_TD)} ({len(EXIT_OFFSETS_TD)} values)")

    # Resolve a "today" anchor — last NSE day with a published bhavcopy.
    # Pre-market-close on a trading day, today's bhavcopy isn't out yet,
    # so we walk back. Anchoring TODAY_FN here means the staleness checks
    # downstream compare against THIS date, not the wall-clock today, so
    # workers' open-expiry cache passes the check post pre-warm.
    anchor = _resolve_anchor_date(WALL_TODAY)
    print(f"  anchor today = {anchor.isoformat()}  "
          f"(wall today {WALL_TODAY.isoformat()}; walked back "
          f"{(WALL_TODAY - anchor).days} day(s) for usable bhavcopy)")
    TODAY_FN = lambda: anchor  # noqa: E731 — local override for the rest of main

    _h(f"Building expiry list ({EXPIRY_FROM.isoformat()} → {EXPIRY_TO.isoformat()})")
    all_expiries: set = set()
    for sym in symbols:
        try:
            exps = expiry_calendar.monthly_expiries(sym, EXPIRY_FROM, EXPIRY_TO)
            print(f"  {sym}: {len(exps)} expiries")
            all_expiries.update(exps)
        except Exception as e:
            print(f"  ⚠ {sym}: failed to load expiries ({type(e).__name__}: {e})")
    expiries = sorted(all_expiries)
    print(f"  union of expiries across symbols: {len(expiries)}")

    n_valid_pairs = sum(
        1 for e in ENTRY_OFFSETS_TD for x in EXIT_OFFSETS_TD if e > x
    )
    n_cells_planned = (
        len(STRATEGIES) * len(symbols) * len(expiries) * n_valid_pairs
    )
    print(f"  valid (entry > exit) pairs: {n_valid_pairs}")
    print(f"  total cells planned: {n_cells_planned}")

    run_id = _compute_run_id(
        STRATEGIES, symbols, expiries, ENTRY_OFFSETS_TD, EXIT_OFFSETS_TD,
    )
    print(f"  run_id (sha-trunc): {run_id}")

    # Pre-warm is gone — superseded by cache_only=True below. Workers
    # never touch NSE: any (sym, expiry, strike, type) tuple not in the
    # on-disk cache becomes a per-cell skip with reason OfflineCacheMiss
    # (the verbatim message goes to skip_detail, surfaced in the
    # heatmap drill-down's Skipped Expiries section).

    _h(f"Running sweep (n_workers={n_workers}; cache_only=True; force=False; cache-hit short-circuits)")
    t0 = time.perf_counter()
    df = sweep_grid(
        strategies=STRATEGIES,
        symbols=symbols,
        expiries=expiries,
        entry_offsets_td=ENTRY_OFFSETS_TD,
        exit_offsets_td=EXIT_OFFSETS_TD,
        today_fn=TODAY_FN,
        offline=False,
        force=False,
        n_workers=n_workers,
        show_progress=True,
        cache_only=True,
    )
    t_total = time.perf_counter() - t0
    _h(f"Sweep complete — {t_total:.1f}s ({t_total / max(n_cells_planned, 1) * 1000:.1f}ms/cell wall-clock)")
    print(f"  rows priced: {len(df)} / {n_cells_planned} planned")
    print(f"  skip rate  : {100.0 * (1 - len(df) / max(n_cells_planned, 1)):.1f}%")

    if len(df) > 0:
        _h("Per-pair counts (rows per strategy × symbol)")
        per_pair = df.groupby(["strategy", "symbol"]).size().unstack(fill_value=0)
        print(per_pair.to_string())

    from src.config import RESULTS_DIR
    skip_path = RESULTS_DIR / f"sweep_{run_id}_skipped.parquet"
    if skip_path.exists():
        import pandas as pd
        skips = pd.read_parquet(skip_path)
        _h(f"Skip log — {len(skips)} cells dropped")
        by_reason = skips.groupby("skip_reason").size().sort_values(ascending=False)
        print(by_reason.to_string())
    else:
        _h("Skip log — no skips")

    print(f"\nParquet: {RESULTS_DIR / f'sweep_{run_id}.parquet'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
