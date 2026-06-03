r"""Smoke-test runner for the bhavcopy-only migration cutover gate
(MIGRATION.md §Phase 1 P1.6).

Operator-driven comparison tool: takes TWO sweep run_ids (one
generated via the legacy api path, one via the new bhavcopy path)
and asserts the bhavcopy results match the api results to within the
acceptance criterion. PASS → green-light P1.7 (strip graceful-
degrade in pnl.py). FAIL → halt and investigate.

Acceptance criterion (per reviewer grill #2 on e0bc85a, tightened
in 10f36be):

  - PRIMARY: per-cell, |bhavcopy_median_roi_pct - api_median_roi_pct|
    < 0.01 absolute (percentage points) on the cell's median
    per-trade ROI.
  - BACKUP: per-trade, no individual ROI delta exceeds 0.5
    percentage points absolute. Catches the scenario where one or
    two trades are wildly off but the median smooths them.

Operator-side smoke procedure
=============================

1. Snapshot the EXISTING api-derived sweep run_id:

   $ ls data/results/sweep_*.parquet
   # → note the existing run_id (the api-derived sweep)

2. Wipe the per-contract options cache for the 4-stock smoke
   universe (PNB, SBIN, BHEL, RELIANCE):

   $ rm -rf data/cache/options/{PNB,SBIN,BHEL,RELIANCE}

3. Run prefetch in bhavcopy mode (single-line — no shell line-
   continuation backslashes to avoid copy-paste escaping issues):

   $ .venv/bin/python scripts/prefetch_universe.py --symbols PNB SBIN BHEL RELIANCE --workers 4 --engine-source bhavcopy --start 2024-07-08 --end 2026-06-02

4. Re-run the sweep against the bhavcopy-materialized contracts:

   $ .venv/bin/python scripts/p7_wide_sweep.py --symbols PNB SBIN BHEL RELIANCE --workers 4

   # → note the new run_id

5. Run this comparison:

   $ .venv/bin/python scripts/smoke_post_migration.py --api-run-id <existing run_id> --bhavcopy-run-id <new run_id>

6. If PASS: green-light P1.7. If FAIL: halt and investigate before
   stripping graceful-degrade.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.config import RESULTS_DIR  # noqa: E402


# ============================================================
# Acceptance thresholds
# ============================================================
# Both expressed in absolute percentage points (NOT relative deltas).
PRIMARY_MEDIAN_DELTA_THRESHOLD_PP = 0.01
BACKUP_PER_TRADE_DELTA_THRESHOLD_PP = 0.5


# ============================================================
# Identity columns — cell-level vs trade-level join keys
# ============================================================
# A CELL is one (strategy, symbol, entry, exit) — aggregated ACROSS
# expiries. The primary criterion is the cell's MEDIAN across its
# ~24 expiries (one trade per monthly expiry over the 2-year
# window). This matches the dashboard's cell_summary / heatmap /
# MCP-tool definition.
_CELL_KEYS = [
    "strategy", "symbol", "entry_offset_td", "exit_offset_td",
]
# A TRADE is one cell × one expiry — uniquely identified by the
# cell keys PLUS expiry. The backup criterion's per-trade join uses
# this 5-key tuple to match trades 1:1 between the two sweeps.
_TRADE_KEYS = _CELL_KEYS + ["expiry"]


def _load_sweep(run_id: str) -> pd.DataFrame:
    """Read a sweep results parquet from data/results/."""
    path = RESULTS_DIR / f"sweep_{run_id}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"sweep parquet not found: {path}. Available run_ids: "
            f"{sorted(p.stem.replace('sweep_', '') for p in RESULTS_DIR.glob('sweep_*.parquet') if not p.stem.endswith('_skipped'))}"
        )
    return pd.read_parquet(path)


def _compute_cell_median_rois(
    sweep_df: pd.DataFrame, label: str,
) -> pd.DataFrame:
    """Aggregate the sweep's per-trade roi_pct rows into per-cell
    median ROI rows. ``label`` distinguishes the api vs bhavcopy
    side for the join."""
    grouped = (
        sweep_df.groupby(_CELL_KEYS)["roi_pct"]
        .agg(["median", "size"])
        .reset_index()
    )
    grouped = grouped.rename(columns={
        "median": f"median_roi_{label}",
        "size": f"n_trades_{label}",
    })
    return grouped


def _compare_cells(
    api_df: pd.DataFrame, bhavcopy_df: pd.DataFrame,
) -> pd.DataFrame:
    """Inner-join the two cell summaries on the cell key + compute
    absolute median-roi delta. Returns the merged frame for
    inspection."""
    api_cells = _compute_cell_median_rois(api_df, "api")
    bhav_cells = _compute_cell_median_rois(bhavcopy_df, "bhavcopy")
    merged = api_cells.merge(bhav_cells, on=_CELL_KEYS, how="inner")
    merged["abs_median_delta_pp"] = (
        merged["median_roi_bhavcopy"] - merged["median_roi_api"]
    ).abs()
    return merged


def _compare_per_trade(
    api_df: pd.DataFrame, bhavcopy_df: pd.DataFrame,
) -> pd.DataFrame:
    """Inner-join the per-trade rows on ``_TRADE_KEYS`` (cell + expiry
    = one trade), find absolute delta per trade. Catches single-trade
    outliers the cell median would smooth over.

    Distinct from `_compare_cells` (which aggregates across expiries
    within a cell). See reviewer's grill on 6f4bea5 for the original
    bug — `_CELL_KEYS` previously included expiry which collapsed
    the cell aggregation to per-trade granularity."""
    pair = api_df[_TRADE_KEYS + ["roi_pct"]].merge(
        bhavcopy_df[_TRADE_KEYS + ["roi_pct"]],
        on=_TRADE_KEYS, how="inner", suffixes=("_api", "_bhavcopy"),
    )
    pair["abs_trade_delta_pp"] = (
        pair["roi_pct_bhavcopy"] - pair["roi_pct_api"]
    ).abs()
    return pair


# ============================================================
# Public smoke-runner entry point
# ============================================================

def run_smoke_comparison(
    api_run_id: str, bhavcopy_run_id: str,
    *,
    primary_threshold_pp: float = PRIMARY_MEDIAN_DELTA_THRESHOLD_PP,
    backup_threshold_pp: float = BACKUP_PER_TRADE_DELTA_THRESHOLD_PP,
    verbose: bool = True,
) -> bool:
    """Compare two sweep parquets. Returns True on PASS, False on
    FAIL. Both criteria must pass (primary AND backup)."""
    api_df = _load_sweep(api_run_id)
    bhav_df = _load_sweep(bhavcopy_run_id)

    if verbose:
        print(f"=== Sweep size check ===")
        print(f"  api    run_id={api_run_id}: {len(api_df):>8,} trade rows")
        print(f"  bhavcopy run_id={bhavcopy_run_id}: {len(bhav_df):>8,} trade rows")

    cell_cmp = _compare_cells(api_df, bhav_df)
    n_cells = len(cell_cmp)
    if n_cells == 0:
        if verbose:
            print(
                "\n  WARNING: no cell join matched between the two sweeps. "
                "Have both sweeps been generated against the same "
                "symbol+expiry universe?"
            )
        return False
    primary_fail = cell_cmp[
        cell_cmp["abs_median_delta_pp"] > primary_threshold_pp
    ]

    trade_cmp = _compare_per_trade(api_df, bhav_df)
    backup_fail = trade_cmp[
        trade_cmp["abs_trade_delta_pp"] > backup_threshold_pp
    ]

    if verbose:
        print(f"\n=== Primary criterion (cell-median delta < {primary_threshold_pp} pp) ===")
        print(f"  cells matched:      {n_cells:>8,}")
        print(f"  PASS:               {n_cells - len(primary_fail):>8,}")
        print(f"  FAIL (> threshold): {len(primary_fail):>8,}")
        if len(primary_fail) and len(primary_fail) <= 20:
            print(f"\n  First {min(20, len(primary_fail))} failing cells:")
            print(primary_fail.head(20).to_string(index=False))
        elif len(primary_fail) > 20:
            print(f"\n  First 20 failing cells (of {len(primary_fail)}):")
            print(primary_fail.head(20).to_string(index=False))

        print(f"\n=== Backup criterion (per-trade delta < {backup_threshold_pp} pp) ===")
        print(f"  trades matched:     {len(trade_cmp):>8,}")
        print(f"  PASS:               {len(trade_cmp) - len(backup_fail):>8,}")
        print(f"  FAIL (> threshold): {len(backup_fail):>8,}")
        if len(backup_fail) and len(backup_fail) <= 20:
            print(f"\n  First {min(20, len(backup_fail))} failing trades:")
            print(
                backup_fail.head(20)[
                    _TRADE_KEYS + ["roi_pct_api", "roi_pct_bhavcopy", "abs_trade_delta_pp"]
                ].to_string(index=False)
            )

    passed = (len(primary_fail) == 0) and (len(backup_fail) == 0)
    if verbose:
        if passed:
            print(
                f"\n  ✅ SMOKE TEST PASSED — green-light P1.7 "
                f"(strip graceful-degrade in pnl.py)."
            )
        else:
            print(
                f"\n  ❌ SMOKE TEST FAILED — halt before P1.7. "
                f"Investigate the failing cells/trades above."
            )
    return passed


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--api-run-id", required=True,
        help="run_id of the api-derived sweep (existing baseline).",
    )
    p.add_argument(
        "--bhavcopy-run-id", required=True,
        help="run_id of the bhavcopy-derived sweep (post-migration).",
    )
    args = p.parse_args()
    passed = run_smoke_comparison(args.api_run_id, args.bhavcopy_run_id)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
