"""Phase-3 live verification: FIRST REAL ₹P&L NUMBER.

The user's original ask, end-to-end against real NSE data:

  "If I had sold an ATM short straddle on RELIANCE Jan-25-2024 expiry,
   entered T-15 trading days before (Jan-4) and closed T-1 (Jan-24),
   what would my P&L have been?"

This script answers it concretely. Walks the full pipeline:

  1. monthly_expiries → confirm RELIANCE Jan-2024 monthly expiry
  2. offset_trading_days → entry T-15, exit T-1
  3. load_spot → ATM strike from entry-day close
  4. ShortStraddle.generate_trades → Trade with two SELL legs
  5. price_trade → gross P&L, costs, net P&L, margin, ROI

Prints the result + a per-leg breakdown so the human can see exactly
which premiums went into the math.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from src.data import expiry_calendar, spot_loader, trading_calendar  # noqa: E402
from src.engine.pnl import price_trade  # noqa: E402
from src.strategies.short_straddle import (  # noqa: E402
    SHORT_STRADDLE_MARGIN_OFFSET, ShortStraddle,
)


SYMBOL = "RELIANCE"
ENTRY_OFFSET = 15  # trading days before expiry
EXIT_OFFSET = 1    # trading days before expiry (T-1, day before expiry)
TODAY_FN = lambda: date(2026, 5, 24)


def _h(s: str) -> None:
    print(f"\n=== {s} ===", flush=True)


def main() -> int:
    _h("Phase-3 FIRST REAL ₹P&L — RELIANCE Jan-2024 short straddle")
    print(f"  symbol           = {SYMBOL}")
    print(f"  strategy         = short straddle (sell ATM CE + sell ATM PE)")
    print(f"  entry offset T-? = {ENTRY_OFFSET} trading days before expiry")
    print(f"  exit offset T-?  = {EXIT_OFFSET} trading day before expiry")

    # === 1. expiry ============================================
    _h("step 1: expiry_calendar.monthly_expiries → Jan 2024 expiry")
    expiries = expiry_calendar.monthly_expiries(
        SYMBOL, date(2024, 1, 1), date(2024, 1, 31),
    )
    assert expiries == [date(2024, 1, 25)], f"expected [Jan 25], got {expiries}"
    expiry = expiries[0]
    print(f"  expiry = {expiry}")

    # === 2. entry / exit dates ================================
    _h("step 2: trading_calendar.offset_trading_days → entry/exit dates")
    entry_date = trading_calendar.offset_trading_days(expiry, ENTRY_OFFSET, today_fn=TODAY_FN)
    exit_date = trading_calendar.offset_trading_days(expiry, EXIT_OFFSET, today_fn=TODAY_FN)
    print(f"  entry_date (T-{ENTRY_OFFSET}) = {entry_date}")
    print(f"  exit_date  (T-{EXIT_OFFSET})  = {exit_date}")

    # === 3. ATM strike from entry-day spot ====================
    _h("step 3: spot_loader.load_spot → ATM strike")
    spot_df = spot_loader.load_spot(SYMBOL, entry_date, entry_date, today_fn=TODAY_FN)
    spot_at_entry = float(spot_df.iloc[0]["close"])
    print(f"  spot_close (entry) = ₹{spot_at_entry}")

    # === 4. ShortStraddle.generate_trades =====================
    _h("step 4: ShortStraddle.generate_trades → Trade with 2 SELL legs")
    strategy = ShortStraddle()
    trades = strategy.generate_trades(
        symbol=SYMBOL, expiry=expiry,
        entry_date=entry_date, exit_date=exit_date,
        spot_at_entry=spot_at_entry,
    )
    assert len(trades) == 1
    trade = trades[0]
    print(f"  ATM strike = {trade.legs[0].strike}")
    print(f"  legs       = {[(leg.option_type, leg.strike, leg.side) for leg in trade.legs]}")

    # === 5. price_trade — FIRST REAL ₹P&L NUMBER ==============
    _h(f"step 5: price_trade — the answer")
    result = price_trade(
        trade,
        strategy_offset_pct=SHORT_STRADDLE_MARGIN_OFFSET,
        today_fn=TODAY_FN,
    )

    # Per-leg breakdown — RAW (loader) AND REALIZED (post-slippage)
    import json
    legs_breakdown = json.loads(result["legs_json"])
    print(f"  Per-leg (raw close → realized post-slippage):")
    for r in legs_breakdown:
        print(f"    {r['option_type']:>2} {int(r['strike']):>5} {r['side']:>4}  "
              f"entry: {r['entry_px']:>7.2f} → {r['entry_px_realized']:>7.4f}   "
              f"exit: {r['exit_px']:>7.2f} → {r['exit_px_realized']:>7.4f}   "
              f"gross={r['gross_pnl']:>+10.2f}")

    print(f"\n  ┌──────────────────────────────────────────────────────────────┐")
    print(f"  │ Gross P&L (post-slippage)  : ₹{result['gross_pnl']:>+12.2f}                │")
    print(f"  │ Costs (Zerodha-style)      :  ₹{result['costs']:>11.2f}                 │")
    print(f"  │ NET P&L                    : ₹{result['net_pnl']:>+12.2f}                │")
    print(f"  │ Margin at entry (Tier-B)   :  ₹{result['margin_at_entry']:>11.0f}                 │")
    if result['roi_pct'] is not None:
        print(f"  │ ROI (holding-period)       : {result['roi_pct']:>+9.2f} %                  │")
    if result.get('roi_pct_annualized') is not None:
        print(f"  │ ROI (annualized, {result['hold_trading_days']:>2} td)     : "
              f"{result['roi_pct_annualized']:>+9.2f} %  ← cross-window-rankable │")
    print(f"  └──────────────────────────────────────────────────────────────┘")

    margin_breakdown = json.loads(result["margin_breakdown_json"])
    print(f"\n  Margin breakdown:")
    print(f"    sell_leg_margin_raw    = ₹{margin_breakdown['sell_leg_margin_raw']:,.0f}")
    print(f"    × strategy_offset_pct  = × {margin_breakdown['strategy_offset_pct']}")
    print(f"    sell_leg_margin (post) = ₹{margin_breakdown['sell_leg_margin']:,.0f}")
    print(f"    symbol_margin_pct (vol-derived) = {margin_breakdown['symbol_margin_pct']:.4f}")

    costs_breakdown = json.loads(result["costs_breakdown_json"])
    print(f"\n  Costs breakdown:")
    for k, v in costs_breakdown.items():
        if k == "total":
            print(f"    {k:>12s} = ₹{v:.4f}")
        else:
            print(f"    {k:>12s} = ₹{v:.4f}")

    # Show without-slippage comparison so the user sees the haircut
    _h("WITHOUT-SLIPPAGE COMPARISON (what a naive backtester would show)")
    from src.engine.slippage import SlippageModelV1
    naive = price_trade(
        trade, strategy_offset_pct=SHORT_STRADDLE_MARGIN_OFFSET,
        slippage_model=SlippageModelV1(slippage_pct=0.0),
        today_fn=TODAY_FN,
    )
    print(f"  Without slippage : Gross ₹{naive['gross_pnl']:>+8.2f}  Net ₹{naive['net_pnl']:>+8.2f}  "
          f"ROI {naive['roi_pct']:>+5.2f}% ({naive['roi_pct_annualized']:>+5.2f}%/yr)")
    print(f"  With 1% slippage : Gross ₹{result['gross_pnl']:>+8.2f}  Net ₹{result['net_pnl']:>+8.2f}  "
          f"ROI {result['roi_pct']:>+5.2f}% ({result['roi_pct_annualized']:>+5.2f}%/yr)")
    haircut = naive['net_pnl'] - result['net_pnl']
    print(f"  Haircut          : ₹{haircut:.2f} (= {100 * haircut / max(naive['net_pnl'], 1):.1f}% of naive net)")

    _h("INTERPRETATION")
    if result['net_pnl'] > 0:
        print(f"  ✓ Profitable trade. The short straddle PAID — premium decay >"
              f" underlying's realized vol.")
    else:
        print(f"  ✗ Losing trade. The underlying moved more than the combined"
              f" premium covered.")
    print(f"\n  This is the FIRST real ₹P&L number this project has produced.")
    print(f"  Every layer (data + universe + strategy + engine + costs + margin)")
    print(f"  is exercised end-to-end against actual NSE data.")
    print(f"\n  Phase 4 will sweep across many (entry_offset, exit_offset) pairs")
    print(f"  and many months/years to find which windows historically paid best.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
