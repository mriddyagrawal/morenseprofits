"""Phase-1 end-to-end integration verification.

Strings ALL FIVE data-layer modules together on one realistic backtest
preamble — the same shape a Phase-3 backtester will use:

  1. expiry_calendar.monthly_expiries  → discover RELIANCE Jan-2024 expiry
  2. trading_calendar.offset_trading_days → compute T-15 entry date
  3. options_loader.load_option         → fetch entry → expiry option prices
  4. bhavcopy_fo_loader.load_bhavcopy_fo → independently look up entry-day close
     and cross-check it matches options_loader's entry-day close.

If every step succeeds AND the cross-check passes, every Phase-1 contract
is operationally proven against live NSE — the data layer is ready for
Phase 2 (universe) and Phase 3 (engine).

Run: `python scripts/verify_phase1_integration.py`. Exit 0 on green.
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.data import (  # noqa: E402
    bhavcopy_fo_loader,
    expiry_calendar,
    options_loader,
    spot_loader,
    trading_calendar,
)


SYMBOL = "RELIANCE"
ENTRY_OFFSET = 15  # trading days back from expiry
TODAY_FN = lambda: date(2026, 5, 24)


def _h(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


def main() -> int:
    _h("Phase-1 integration verify: " f"{SYMBOL} Jan-2024 monthly expiry, T-{ENTRY_OFFSET} entry")
    print(f"  today_fn = {TODAY_FN()} (closed-contract regime)")
    print(f"  symbol   = {SYMBOL}")

    # --- 1. expiry_calendar -------------------------------------------
    _h("step 1: expiry_calendar.monthly_expiries(...Jan 2024)")
    t = time.perf_counter()
    expiries = expiry_calendar.monthly_expiries(
        SYMBOL, date(2024, 1, 1), date(2024, 1, 31)
    )
    print(f"  {len(expiries)} expiry/expiries in {time.perf_counter()-t:.2f}s: {expiries}")
    if expiries != [date(2024, 1, 25)]:
        print("  FAIL: expected [date(2024, 1, 25)]")
        return 1
    expiry = expiries[0]

    # --- 2. trading_calendar ------------------------------------------
    _h(f"step 2: trading_calendar.offset_trading_days({expiry}, {ENTRY_OFFSET})")
    t = time.perf_counter()
    entry_date = trading_calendar.offset_trading_days(
        expiry, ENTRY_OFFSET, today_fn=TODAY_FN
    )
    print(f"  T-{ENTRY_OFFSET} = {entry_date} (in {time.perf_counter()-t:.2f}s)")
    if entry_date != date(2024, 1, 4):
        print(f"  FAIL: expected date(2024, 1, 4); reviewer's canonical hand-check")
        return 1

    # --- 3. find an ATM strike on entry_date via spot --------------------
    _h(f"step 3: spot_loader.load_spot({SYMBOL}, {entry_date})")
    spot_df = spot_loader.load_spot(
        SYMBOL, entry_date, entry_date, today_fn=TODAY_FN
    )
    if len(spot_df) != 1:
        print(f"  FAIL: expected 1 spot row for {entry_date}, got {len(spot_df)}")
        return 1
    spot_close = float(spot_df.iloc[0]["close"])
    # RELIANCE strikes are in ₹20 steps around this price range
    atm = round(spot_close / 20) * 20
    print(f"  spot_close = {spot_close} → ATM strike (₹20 step) = {atm}")

    # --- 4. options_loader -------------------------------------------
    _h(f"step 4: options_loader.load_option({SYMBOL}, {expiry}, {atm}, 'CE', "
       f"{entry_date}, {expiry})")
    t = time.perf_counter()
    opt = options_loader.load_option(
        SYMBOL, expiry, atm, "CE",
        entry_date, expiry,
        today_fn=TODAY_FN,
    )
    print(f"  {len(opt)} rows in {time.perf_counter()-t:.2f}s")
    if len(opt) < 15:
        print(f"  WARN: only {len(opt)} option rows — illiquid contract or "
              f"data gaps")
    print(f"  date range: {opt['date'].min().date()} → {opt['date'].max().date()}")
    print(f"  entry close: {float(opt.iloc[0]['close']):>8.2f}  "
          f"exit close: {float(opt.iloc[-1]['close']):>8.2f}")
    print(f"  lot_size:    {int(opt.iloc[0]['lot_size'])}  "
          f"max OI: {int(opt['oi'].max())}")

    # entry_date row in options_loader output
    opt_entry = opt[opt["date"] == pd.Timestamp(entry_date)]
    if len(opt_entry) != 1:
        print(f"  FAIL: expected 1 option row on entry_date {entry_date}, "
              f"got {len(opt_entry)}")
        return 1
    opt_entry_close = float(opt_entry.iloc[0]["close"])

    # --- 5. bhavcopy_fo independent cross-check ----------------------
    _h(f"step 5: bhavcopy_fo_loader.load_bhavcopy_fo({entry_date}) cross-check")
    t = time.perf_counter()
    bc = bhavcopy_fo_loader.load_bhavcopy_fo(entry_date)
    bc_row = bc[
        (bc["symbol"] == SYMBOL)
        & (bc["instrument"] == "OPTSTK")
        & (bc["strike"] == float(atm))
        & (bc["option_type"] == "CE")
        & (bc["expiry"] == pd.Timestamp(expiry))
    ]
    print(f"  bhavcopy fetched in {time.perf_counter()-t:.2f}s; "
          f"{len(bc_row)} matching row(s)")
    if len(bc_row) != 1:
        print(f"  FAIL: expected 1 matching bhavcopy row; got {len(bc_row)}")
        return 1
    bc_close = float(bc_row.iloc[0]["close"])

    _h("CROSS-LAYER COMPARISON on entry_date close")
    print(f"  options_loader:        {opt_entry_close}")
    print(f"  bhavcopy_fo:           {bc_close}")
    if opt_entry_close != bc_close:
        print(f"  FAIL: cross-layer disagreement — one layer is wrong")
        return 1
    print(f"  OK — byte-identical")

    _h("ALL PHASE-1 INTEGRATION CHECKS PASSED")
    print("  monthly_expiries → offset_trading_days → load_spot →")
    print("  load_option → load_bhavcopy_fo all agree end-to-end on")
    print(f"  {SYMBOL} {expiry} {atm}{'CE'} entry_date={entry_date}.")
    print("  Phase 1 is operationally ready for Phase 2 + Phase 3.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
