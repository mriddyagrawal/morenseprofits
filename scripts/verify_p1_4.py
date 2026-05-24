"""Phase-1.4 cross-layer live verification against NSE.

Two comparisons, both straddling the 2024-07-08 cutover:

  1. POST-cutover: RELIANCE Aug-29-2024 2840 CE (UDiff bhavcopy path).
  2. PRE-cutover:  RELIANCE Jan-25-2024 2620 CE (legacy bhavcopy path).

Each comparison loads the same (symbol, expiry, strike, type, trade_date)
row via BOTH `options_loader.load_option` AND `bhavcopy_fo_loader.load_bhavcopy_fo`,
then asserts close/oi/oi_change agree byte-for-byte. The two loaders pull
from completely different jugaad endpoints; cross-layer agreement is the
strongest cross-validation we can run without going to a third NSE source.

If both comparisons agree on both sides of the cutover, Phase 1.4 is
provably correct end-to-end and the data layer is ready for Phase 1.5.

Run: `python scripts/verify_p1_4.py`. Exit 0 on green, 1 on red.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.data import bhavcopy_fo_loader, options_loader  # noqa: E402


@dataclass(frozen=True)
class Case:
    label: str
    expiry: date
    strike: int
    option_type: str
    trade_date: date


CASES = [
    Case("POST-cutover (UDiff path)", date(2024, 8, 29), 2840, "CE", date(2024, 8, 29)),
    Case("PRE-cutover  (legacy path)", date(2024, 1, 25), 2620, "CE", date(2024, 1, 25)),
]

SYMBOL = "RELIANCE"
TODAY_FN = lambda: date(2026, 5, 24)  # closed-contract regime for both cases


def _section(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


def _bhavcopy_row(bc: pd.DataFrame, expiry: date, strike: int, otype: str) -> pd.Series | None:
    mask = (
        (bc["symbol"] == SYMBOL)
        & (bc["instrument"] == "OPTSTK")
        & (bc["strike"] == float(strike))
        & (bc["option_type"] == otype)
        & (bc["expiry"] == pd.Timestamp(expiry))
    )
    rows = bc.loc[mask]
    if len(rows) != 1:
        print(f"   WARN: bhavcopy filter returned {len(rows)} rows (expected 1)")
        return None
    return rows.iloc[0]


def verify(case: Case) -> bool:
    _section(case.label)
    print(f"   {SYMBOL} {case.expiry} {case.strike}{case.option_type} on {case.trade_date}")

    # --- via options_loader ---
    opt = options_loader.load_option(
        SYMBOL, case.expiry, case.strike, case.option_type,
        case.trade_date, case.trade_date, today_fn=TODAY_FN,
    )
    if len(opt) != 1:
        print(f"   FAIL: load_option returned {len(opt)} rows (expected 1)")
        return False
    o = opt.iloc[0]
    print(f"   load_option:        close={o['close']:>8} oi={int(o['oi']):>7} dOI={int(o['oi_change']):>7} lot={int(o['lot_size'])} vol={int(o['volume'])}")

    # --- via bhavcopy_fo_loader ---
    bc = bhavcopy_fo_loader.load_bhavcopy_fo(case.trade_date)
    b = _bhavcopy_row(bc, case.expiry, case.strike, case.option_type)
    if b is None:
        print(f"   FAIL: contract not present in bhavcopy_fo for {case.trade_date}")
        return False
    print(f"   bhavcopy_fo:        close={b['close']:>8} oi={int(b['oi']):>7} dOI={int(b['oi_change']):>7} contracts={int(b['contracts'])}")

    # --- cross-layer assertions ---
    ok = True
    if o["close"] != b["close"]:
        print(f"   FAIL: close mismatch — options={o['close']} bhavcopy={b['close']}")
        ok = False
    if int(o["oi"]) != int(b["oi"]):
        print(f"   FAIL: oi mismatch — options={int(o['oi'])} bhavcopy={int(b['oi'])}")
        ok = False
    if int(o["oi_change"]) != int(b["oi_change"]):
        print(f"   FAIL: oi_change mismatch — options={int(o['oi_change'])} bhavcopy={int(b['oi_change'])}")
        ok = False
    # Volume/contracts relationship: bhavcopy contracts = options volume // lot_size
    expected_contracts = int(o["volume"]) // int(o["lot_size"])
    if int(b["contracts"]) != expected_contracts:
        print(f"   FAIL: contracts mismatch — bhavcopy={int(b['contracts'])} "
              f"vs options volume//lot={expected_contracts}")
        ok = False

    if ok:
        print(f"   OK — close, oi, oi_change, and contracts=volume//lot agree byte-for-byte")
    return ok


def main() -> int:
    _section("Phase 1.4 cross-layer cutover-spanning verification")
    print(f"   today_fn = {TODAY_FN()} (closed-contract regime for both cases)")

    all_ok = True
    for case in CASES:
        if not verify(case):
            all_ok = False

    _section("RESULT")
    if all_ok:
        print("ALL PHASE-1.4 CROSS-LAYER CHECKS PASSED")
        print("Both loaders agree byte-for-byte on both sides of the cutover.")
        return 0
    else:
        print("FAILURES above — see per-case detail")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
