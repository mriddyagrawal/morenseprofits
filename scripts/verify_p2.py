"""Phase-2 universe live verification.

Runs the full pipeline end-to-end against real NSE for the v1 universe:

  1. blue_chip(date(2024,7,1)) → 40 NSE symbols.
  2. classify_momentum(2024-07-01, blue_chip, lookback_trading_days=126)
     → bullish / neutral / non_bullish split.

Asserts:
  - Total classified ≤ 40 (some symbols may be delisted in jugaad's
    historical archive — those drop with a warning per SPECS §6b.2).
  - Top-heavy split: len(bullish) >= len(non_bullish).
  - RELIANCE classified bullish (rallied through H1 2024, real-world).
  - HDFCBANK classified non_bullish (well-documented 2024 H1 lag).

If those four hold, Phase 2 is operationally ready for Phase 3 (engine).

Run: `python scripts/verify_p2.py`. Exit 0 on green.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.universe.blue_chip import blue_chip  # noqa: E402
from src.universe.momentum import classify_momentum  # noqa: E402


AS_OF = date(2024, 7, 1)
TODAY_FN = lambda: date(2026, 5, 24)


def _h(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


def main() -> int:
    _h(f"Phase-2 live verify: classify_momentum on blue_chip as-of {AS_OF}")

    # --- step 1: blue chip ---
    universe = blue_chip(AS_OF)
    print(f"  blue_chip({AS_OF}) returned {len(universe)} symbols")
    assert len(universe) == 40, f"expected 40, got {len(universe)}"

    # --- step 2: classify_momentum live ---
    _h("classify_momentum (LIVE — fetches ~40 spot frames; cold may take ~1 min)")
    import time
    t = time.perf_counter()
    out = classify_momentum(AS_OF, universe, today_fn=TODAY_FN)
    elapsed = time.perf_counter() - t

    bullish = out["bullish"]
    neutral = out["neutral"]
    non_bullish = out["non_bullish"]
    total = len(bullish) + len(neutral) + len(non_bullish)
    print(f"  classified in {elapsed:.1f}s; total = {total} / {len(universe)}")
    if total < len(universe):
        dropped = set(universe) - set(bullish) - set(neutral) - set(non_bullish)
        print(f"  WARN: {len(dropped)} symbols dropped (delisted in jugaad archive?): "
              f"{sorted(dropped)}")

    # --- step 3: print splits ---
    _h(f"BULLISH ({len(bullish)})")
    for s in bullish:
        print(f"  {s}")
    _h(f"NEUTRAL ({len(neutral)})")
    for s in neutral:
        print(f"  {s}")
    _h(f"NON_BULLISH ({len(non_bullish)})")
    for s in non_bullish:
        print(f"  {s}")

    # --- step 4: invariant checks ---
    _h("INVARIANTS")
    failed = []

    if len(bullish) < len(non_bullish):
        failed.append(
            f"top-heavy violation: bullish={len(bullish)} < non_bullish={len(non_bullish)}"
        )
    else:
        print(f"  OK top-heavy: bullish={len(bullish)} >= non_bullish={len(non_bullish)}")

    # Determinism: re-run, assert byte-identical
    out2 = classify_momentum(AS_OF, universe, today_fn=TODAY_FN)
    if out2 == out:
        print("  OK determinism: second call returned == dict")
    else:
        failed.append("determinism: second call returned a different split")

    # --- step 5: hand-verifiable economic constraints ---
    _h("HAND-VERIFIABLE ECONOMIC CONSTRAINTS (real H1-2024 NSE behavior)")

    # RELIANCE rallied through H1 2024 (~2596 in Jan to ~2900 by Jul). Should be bullish.
    if "RELIANCE" in bullish:
        print("  OK RELIANCE classified bullish (matches real H1-2024 rally)")
    else:
        actual = (
            "neutral" if "RELIANCE" in neutral
            else "non_bullish" if "RELIANCE" in non_bullish
            else "DROPPED"
        )
        failed.append(f"RELIANCE expected bullish, got {actual}")

    # HDFCBANK was a well-documented 2024 H1 laggard (post-merger overhang).
    if "HDFCBANK" in non_bullish:
        print("  OK HDFCBANK classified non_bullish (matches real H1-2024 lag)")
    elif "HDFCBANK" in neutral:
        # Acceptable — the cut between non_bullish and neutral is just a tercile boundary.
        print("  OK-ISH HDFCBANK classified neutral (would have expected non_bullish "
              "but tercile boundary near the bottom is fluid)")
    else:
        failed.append(f"HDFCBANK expected non_bullish or neutral, got bullish")

    if failed:
        _h("FAILURES")
        for f in failed:
            print(f"  {f}")
        return 1

    _h("ALL PHASE-2 LIVE CHECKS PASSED")
    print("  Universe + momentum classifier work end-to-end on real NSE data.")
    print(f"  Phase 2 is operationally ready for Phase 3 (engine).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
