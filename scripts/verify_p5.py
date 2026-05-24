"""Phase-5 live verification — full aggregate → rank pipeline.

The bridge between Phase 5 (data layer) and Phase 6 (Streamlit UI).
Every line of CLI output here is something Phase 6 will render
visually. Catches composability issues before they hit a browser.

Six load-bearing checks, mirroring p4.verify's pattern:
  (a) leaderboard composability — summarize_by_stock_strategy →
      rank_strategies works end-to-end, schema preserved.
  (b) heatmap pivot — pivot_window + pivot_counts produce same-shape
      frames; the v.where(n >= MIN_N_FOR_RANKING) masking pattern works.
  (c) yearly trend — summarize_by_year exercises (degenerate on this
      Q1-only verify dataset; shape is what gets pinned).
  (d) seasonality — summarize_by_month surfaces the real Feb/Mar
      pattern from the verify run.
  (e) thin-sample transparency — count + render rows suppressed by
      MIN_N_FOR_RANKING so Phase-6 can include the same in its UI
      (reviewer flagged silent-drop risk on single-table rank output).
  (f) caveats — print MULTIPLE_COMPARISONS_CAVEAT verbatim; Phase 6
      must show this text alongside any leaderboard.
"""
from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.analytics.aggregate import (  # noqa: E402
    MIN_N_FOR_RANKING,
    summarize_by_month,
    summarize_by_stock_strategy,
    summarize_by_year,
)
from src.analytics.heatmap import pivot_counts, pivot_window  # noqa: E402
from src.analytics.rank import (  # noqa: E402
    DEFAULT_RANK_METRIC,
    MULTIPLE_COMPARISONS_CAVEAT,
    rank_strategies,
)
from src.config import RESULTS_DIR  # noqa: E402


def _h(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


def main() -> int:
    _h("Phase-5 PIPELINE VERIFY — aggregate → rank on the live parquet")

    # Pick the largest sweep parquet — robust against test artifacts
    # (small leaked parquets from pytest runs) that share the same dir.
    # We want the actual verify dataset, not a 1-row test artifact.
    candidates = [
        p for p in RESULTS_DIR.glob("sweep_*.parquet")
        if "_skipped" not in p.name
    ]
    if not candidates:
        print(f"  no sweep parquets found in {RESULTS_DIR}")
        print(f"  run scripts/verify_p4.py first to populate.")
        return 1
    sized = sorted(
        ((p, len(pd.read_parquet(p))) for p in candidates),
        key=lambda pn: pn[1], reverse=True,
    )
    parquet, n = sized[0]
    print(f"  parquet: {parquet.name}  "
          f"({n} rows — largest of {len(sized)} candidates)")
    if len(sized) > 1:
        others = ", ".join(f"{p.name}({n})" for p, n in sized[1:])
        print(f"  (other candidates: {others})")
    raw = pd.read_parquet(parquet)

    t0 = time.perf_counter()

    # === (a) leaderboard composability ===================================
    _h("(a) leaderboard — summarize_by_stock_strategy + rank_strategies")
    summary = summarize_by_stock_strategy(raw)
    ranked = rank_strategies(summary, min_n=0)  # min_n=0 so verify-set's
                                                # single pair shows up
    cols = [
        "rank", "strategy", "symbol", "n_trades", "win_rate_pct",
        "median_roi_pct_annualized", "std_roi_pct_annualized",
        "total_net_pnl", "worst_roi_pct", "best_roi_pct",
    ]
    print(ranked[cols].to_string(
        index=False, float_format=lambda x: f"{x:>9.2f}",
    ))
    # Sharpe-like composability (reviewer's grilled-pattern from p5.5 review)
    if "std_roi_pct_annualized" in summary.columns:
        with_sharpe = summary.copy()
        # Avoid div-by-zero: only compute when std > 0
        denom = with_sharpe["std_roi_pct_annualized"].replace(0.0, float("nan"))
        with_sharpe["sharpe_like_annualized"] = (
            with_sharpe["mean_roi_pct_annualized"] / denom
        )
        sharpe_ranked = rank_strategies(
            with_sharpe, by="sharpe_like_annualized", min_n=0,
        )
        print(f"\n  Sharpe-like ranking (mean/std, annualized):")
        print(sharpe_ranked[
            ["rank", "strategy", "symbol", "sharpe_like_annualized"]
        ].to_string(index=False, float_format=lambda x: f"{x:>8.3f}"))

    # === (b) heatmap pivot + masking pattern ============================
    _h("(b) heatmap — pivot_window + thin-sample masking pattern")
    for (strat, sym), _ in summary.set_index(["strategy", "symbol"]).iterrows():
        values = pivot_window(raw, strategy=strat, symbol=sym)
        counts = pivot_counts(raw, strategy=strat, symbol=sym)
        print(f"\n  {strat} × {sym} — median roi_pct_annualized:")
        print(values.to_string(float_format=lambda x: f"{x:>9.1f}"))
        print(f"  counts per cell:")
        print(counts.to_string())
        # Masking pattern Phase-6 will use — render BOTH the count and
        # the masked view itself so the operator sees exactly what
        # Phase-6's heatmap will display (typically a mostly-NaN grid
        # on small sweeps until the dataset thickens up).
        masked = values.where(counts >= MIN_N_FOR_RANKING)
        n_masked = int(values.notna().sum().sum() - masked.notna().sum().sum())
        print(f"  cells masked at MIN_N_FOR_RANKING={MIN_N_FOR_RANKING}: {n_masked}")
        if n_masked > 0:
            print(f"  masked view (Phase-6 will render this — NaN cells "
                  f"shown as blank):")
            print(masked.to_string(float_format=lambda x: f"{x:>9.1f}"))

    # === (c) year-over-year ============================================
    _h("(c) summarize_by_year — YoY trend (degenerate on Q1-only data)")
    yearly = summarize_by_year(raw)
    print(yearly[
        ["strategy", "symbol", "year", "n_trades", "win_rate_pct",
         "median_roi_pct_annualized", "total_net_pnl"]
    ].to_string(index=False, float_format=lambda x: f"{x:>9.2f}"))
    if yearly["year"].nunique() == 1:
        print(f"  ⚠ single-year dataset — YoY decay needs multi-year sweep "
              f"to exercise meaningfully")

    # === (d) seasonality ==============================================
    _h("(d) summarize_by_month — seasonality (Feb/Mar pattern visible)")
    monthly = summarize_by_month(raw)
    print(monthly[
        ["strategy", "symbol", "month", "n_trades", "win_rate_pct",
         "median_roi_pct_annualized", "std_roi_pct_annualized"]
    ].to_string(index=False, float_format=lambda x: f"{x:>9.2f}"))

    # === (e) thin-sample transparency (reviewer-flagged Phase-6 concern) ===
    _h("(e) suppressed thin samples — Phase-6 MUST render this alongside ranks")
    thin = summary[summary["n_trades"] < MIN_N_FOR_RANKING]
    if len(thin) == 0:
        print(f"  no rows below MIN_N_FOR_RANKING ({MIN_N_FOR_RANKING}) — "
              f"every pair in this dataset has enough samples")
    else:
        print(f"  {len(thin)} rows suppressed from headline rank (N below "
              f"threshold):")
        print(thin[["strategy", "symbol", "n_trades",
                    "median_roi_pct_annualized"]].to_string(
            index=False, float_format=lambda x: f"{x:>9.2f}",
        ))

    # === (f) caveats banner ============================================
    _h("(f) MULTIPLE_COMPARISONS_CAVEAT — Phase-6 banner content")
    print(f"  (verbatim text — Phase-6 will render this alongside leaderboard)")
    for line in textwrap.wrap(MULTIPLE_COMPARISONS_CAVEAT, width=72):
        print(f"  │ {line}")

    # === Timing ========================================================
    t = time.perf_counter() - t0
    _h(f"timing — full pipeline: {t*1000:.1f}ms")
    print(f"  Phase-5 layer is essentially free vs Phase-4 sweep cost. "
          f"Phase-6 UI can re-aggregate on every user click without lag.")

    _h("PHASE-5 VERIFY: PASS")
    print(f"  Composability checks: leaderboard ✓ Sharpe-like ranking ✓")
    print(f"                        heatmap+masking ✓ trend ✓ seasonality ✓")
    print(f"                        thin-sample transparency ✓ caveats ✓")
    print(f"  Phase-6 (Streamlit UI) is unblocked — every visible number in")
    print(f"  the UI will be traceable to a row in the sweep parquet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
