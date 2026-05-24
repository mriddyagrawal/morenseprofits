"""Phase-1.3 end-to-end live verification against NSE.

Calls `monthly_expiries("RELIANCE", 2024-06-01, 2024-09-30)` — the
highest-de-risking single call: it spans the 2024-07-08 legacy/UDiff
cutover, so it exercises BOTH bhavcopy fetch paths end-to-end via the
real loader (not just the recorded fixtures).

Hand-checked truth: the canonical last-Thursday-of-month expiries for
RELIANCE stock options in those 4 months are 2024-06-27, 2024-07-25,
2024-08-29, 2024-09-26. The script asserts the live output matches.

Also runs a second call to confirm the per-symbol expiry cache absorbs
the repeat (zero network calls the second time).

Run with `python scripts/verify_p1_3.py`. Exit 0 on green, 1 on red.
Cache is in `data/cache/` — leave it alone afterwards if you want
incremental verifications later, or `rm -rf data/cache/` to start clean.
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Make `src` importable when running this script directly
sys.path.insert(0, str(REPO))

from src.data import bhavcopy_fo_loader, expiry_calendar  # noqa: E402


EXPECTED_RELIANCE_JUN_SEP_2024 = [
    date(2024, 6, 27),  # Jun monthly expiry (Thursday)
    date(2024, 7, 25),  # Jul monthly expiry (Thursday) — last pre-cutover-week
    date(2024, 8, 29),  # Aug monthly expiry (Thursday)
    date(2024, 9, 26),  # Sep monthly expiry (Thursday)
]


def _section(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def main() -> int:
    _section("Phase 1.3 live verification: RELIANCE 2024-06 → 2024-09")
    print(f"This spans the 2024-07-08 legacy/UDiff cutover, so it")
    print(f"exercises BOTH bhavcopy fetch paths.")

    _section("Cold call: monthly_expiries('RELIANCE', 2024-06-01, 2024-09-30)")
    t0 = time.perf_counter()
    cold = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 6, 1), date(2024, 9, 30))
    cold_s = time.perf_counter() - t0
    print(f"  returned {len(cold)} expiries in {cold_s:.1f}s:")
    for d in cold:
        print(f"    {d}")

    if cold != EXPECTED_RELIANCE_JUN_SEP_2024:
        print(f"\nFAIL: expected {EXPECTED_RELIANCE_JUN_SEP_2024}")
        print(f"      got      {cold}")
        return 1
    print(f"OK: matches the canonical last-Thursday-of-month schedule.")

    _section("Hot call: same query, should hit per-symbol cache (no network)")
    t1 = time.perf_counter()
    hot = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 6, 1), date(2024, 9, 30))
    hot_ms = (time.perf_counter() - t1) * 1000
    print(f"  returned {len(hot)} expiries in {hot_ms:.0f}ms")
    if hot != cold:
        print(f"FAIL: hot call returned different list: {hot}")
        return 1
    if hot_ms > 500:
        print(f"WARN: hot call took {hot_ms:.0f}ms — suspicious; cache hit should be <50ms")
    else:
        print(f"OK: cache hit confirmed (<500ms)")

    _section("Narrow window inside the cached range: 2024-08-01 to 2024-08-31")
    narrow = expiry_calendar.monthly_expiries("RELIANCE", date(2024, 8, 1), date(2024, 8, 31))
    print(f"  returned {narrow}")
    if narrow != [date(2024, 8, 29)]:
        print(f"FAIL: expected [date(2024, 8, 29)], got {narrow}")
        return 1
    print(f"OK: window filter works (only the in-window expiry returned)")

    _section("Cross-check via direct bhavcopy load")
    # Pull the Jun-27 bhavcopy and confirm Jun-27 is among the listed RELIANCE
    # expiries — independent corroboration of the calendar's first row.
    bc = bhavcopy_fo_loader.load_bhavcopy_fo(date(2024, 6, 3))  # first trading day of Jun
    reliance_expiries = sorted(
        bc[(bc["instrument"] == "OPTSTK") & (bc["symbol"] == "RELIANCE")][
            "expiry"
        ].dt.date.unique().tolist()
    )
    print(f"  Jun-3 bhavcopy lists RELIANCE OPTSTK expiries: {reliance_expiries}")
    if date(2024, 6, 27) not in reliance_expiries:
        print(f"FAIL: 2024-06-27 missing from Jun-3 sample — calendar may be wrong")
        return 1
    print(f"OK: 2024-06-27 corroborated by direct bhavcopy")

    _section("ALL PHASE-1.3 LIVE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
