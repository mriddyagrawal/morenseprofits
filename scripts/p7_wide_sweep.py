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

import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.data import expiry_calendar  # noqa: E402
from src.engine.sweeper import _compute_run_id, sweep_grid  # noqa: E402


SYMBOLS = [
    "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
    "SBIN", "AXISBANK", "KOTAKBANK", "BHARTIARTL", "LT",
]   # matches scripts/prefetch_universe.py — 10 blue chips with cache
STRATEGIES = ["short_straddle", "short_strangle", "iron_condor"]
ENTRY_OFFSETS_TD = list(range(1, 46))   # T-45 ... T-1
EXIT_OFFSETS_TD = list(range(0, 16))    # T-0  ... T-15
EXPIRY_FROM = date(2024, 5, 1)
EXPIRY_TO = date(2026, 5, 31)
TODAY_FN = lambda: date(2026, 5, 26)
N_WORKERS = 8   # M1 Max has 8 perf cores; efficiency cores add little


def _h(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


def main() -> int:
    _h("Phase-7 wide-grid sweep — heatmap 45×16")
    print(f"  symbols     = {SYMBOLS}")
    print(f"  strategies  = {STRATEGIES}")
    print(f"  entry_td    = T-{min(ENTRY_OFFSETS_TD)} … T-{max(ENTRY_OFFSETS_TD)} ({len(ENTRY_OFFSETS_TD)} values)")
    print(f"  exit_td     = T-{min(EXIT_OFFSETS_TD)} … T-{max(EXIT_OFFSETS_TD)} ({len(EXIT_OFFSETS_TD)} values)")

    _h(f"Building expiry list ({EXPIRY_FROM.isoformat()} → {EXPIRY_TO.isoformat()})")
    all_expiries: set = set()
    for sym in SYMBOLS:
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
        len(STRATEGIES) * len(SYMBOLS) * len(expiries) * n_valid_pairs
    )
    print(f"  valid (entry > exit) pairs: {n_valid_pairs}")
    print(f"  total cells planned: {n_cells_planned}")

    run_id = _compute_run_id(
        STRATEGIES, SYMBOLS, expiries, ENTRY_OFFSETS_TD, EXIT_OFFSETS_TD,
    )
    print(f"  run_id (sha-trunc): {run_id}")

    _h(f"Running sweep (n_workers={N_WORKERS}; force=False; cache-hit short-circuits)")
    t0 = time.perf_counter()
    df = sweep_grid(
        strategies=STRATEGIES,
        symbols=SYMBOLS,
        expiries=expiries,
        entry_offsets_td=ENTRY_OFFSETS_TD,
        exit_offsets_td=EXIT_OFFSETS_TD,
        today_fn=TODAY_FN,
        offline=False,
        force=False,
        n_workers=N_WORKERS,
        show_progress=True,
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
