"""Phase 6.5.sweep — DESIGN_SPEC §3.2 first "real" Phase-6 dataset.

5 stocks × 2 years × 3 short-vol strategies × 5 entry × 3 exit ≈
5,400 cells. Bumps the verify_p4 18-cell dataset up to something
Phase-6's leaderboard / heatmap / trends actually exercise.

Per §3.2 reasoning:
  - 5 highest-liquidity blue chips → bhavcopies reliable across full window
  - 2 years (2023-2024) → enough for a YoY view; avoids the
    legacy/UDiff pre-2024-07-08 boundary noise that's already
    handled by bhavcopy_fo_loader but adds variance
  - 3 short-vol strategies → research target; longs are mirrors

Expected timing per §3.2: ~20-30 min cold-cache fetch (bhavcopies
+ options). Subsequent reruns ~30-60s.
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


SYMBOLS = ["RELIANCE", "HDFCBANK", "INFY", "ICICIBANK", "TCS"]
STRATEGIES = ["short_straddle", "short_strangle", "iron_condor"]
ENTRY_OFFSETS_TD = [15, 12, 9, 6, 3]
EXIT_OFFSETS_TD = [3, 1, 0]
TODAY_FN = lambda: date(2026, 5, 25)


def _h(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


def main() -> int:
    _h("Phase-6.5 first real sweep — DESIGN_SPEC §3.2 grid")
    print(f"  symbols     = {SYMBOLS}")
    print(f"  strategies  = {STRATEGIES}")
    print(f"  years       = 2023, 2024 (monthly expiries)")
    print(f"  entry_td    = {ENTRY_OFFSETS_TD}")
    print(f"  exit_td     = {EXIT_OFFSETS_TD}")

    # === Build expiry list ==================================
    # Monthly expiries across the year window. expiry_calendar's
    # monthly_expiries takes (symbol, from_date, to_date) and we
    # union across symbols since different stocks may have slightly
    # different expiry-day exceptions.
    _h("Building expiry list (2023-01-01 → 2024-12-31)")
    all_expiries: set = set()
    for sym in SYMBOLS:
        try:
            exps = expiry_calendar.monthly_expiries(
                sym, date(2023, 1, 1), date(2024, 12, 31),
            )
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
    print(f"  total cells planned: {n_cells_planned}")

    run_id = _compute_run_id(
        STRATEGIES, SYMBOLS, expiries, ENTRY_OFFSETS_TD, EXIT_OFFSETS_TD,
    )
    print(f"  run_id (sha-trunc): {run_id}")

    # === Run the sweep ======================================
    _h("Running sweep (force=False; cache-hit short-circuits)")
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
    )
    t_total = time.perf_counter() - t0
    _h(f"Sweep complete — {t_total:.1f}s ({t_total / max(n_cells_planned, 1) * 1000:.0f}ms/cell wall-clock)")
    print(f"  rows priced: {len(df)} / {n_cells_planned} planned")
    print(f"  skip rate  : {100.0 * (1 - len(df) / max(n_cells_planned, 1)):.1f}%")

    # === Per-strategy / per-symbol breakdown ================
    if len(df) > 0:
        _h("Per-pair counts (rows per strategy × symbol)")
        per_pair = df.groupby(["strategy", "symbol"]).size().unstack(fill_value=0)
        print(per_pair.to_string())

    # === Skip log inspection ================================
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
