"""COST_MODEL_V1 — Indian discount-broker option-trading costs.

Rates pinned per SPECS §4 (Zerodha-style baseline as of 2024). A cost
model takes a list of priced legs (the engine's per-leg result dicts)
and returns a breakdown + total. The engine subtracts total from gross
P&L to get net P&L.

Componentwise per SPECS §4:
- Brokerage: flat ₹20 / executed order. A short straddle = 4 orders
  total (CE entry + PE entry + CE close + PE close) = ₹80.
- STT: 0.0625% of premium turnover, **SELL-side only on options**.
  (For a SHORT straddle, that's both legs' ENTRY premiums; for a long
  straddle, it's both legs' EXIT premiums.)
- Exchange txn fee: 0.0503% of premium turnover, **both sides**.
- GST: 18% on (brokerage + exchange txn fee).
- SEBI fee: ₹10 per crore of premium turnover (negligible but included
  for fidelity).
- Stamp duty: 0.003% on **BUY-side** premium turnover.

The model is FROZEN-versioned as a dataclass so Phase-5 sensitivity
analysis can swap in a `CostModelV2` without disturbing V1's pinned
behavior. The default singleton ``COST_MODEL_V1`` is what every backtest
in the project uses unless explicitly overridden.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class CostModelV1:
    """SPECS §4 rates. Frozen — for sensitivity analysis create a new
    instance (or a V2 dataclass) rather than mutating."""
    brokerage_per_order: float = 20.0       # ₹/order
    stt_sell_options_pct: float = 0.000625  # 0.0625%
    exchange_txn_pct: float = 0.000503      # 0.0503%
    gst_pct: float = 0.18                   # 18%
    sebi_per_crore: float = 10.0            # ₹/crore
    stamp_duty_buy_pct: float = 0.00003     # 0.003%

    def total_cost(self, legs: Iterable[dict]) -> dict:
        """Compute total cost for a trade's priced legs.

        Each ``leg`` dict is the per-leg output of ``engine.pnl._price_one_leg``
        and must have: ``side`` ∈ {"SELL", "BUY"}, ``qty_lots``,
        ``lot_size``, ``entry_px``, ``exit_px``.

        Returns dict with one entry per cost component plus ``total``,
        all positive. The engine subtracts ``total`` from ``gross_pnl``.

        Sign / side accounting:
        - A SELL leg opens with a SELL (premium credit) and closes with a
          BUY (premium debit). So entry_px contributes to sell-side
          turnover; exit_px to buy-side.
        - A BUY leg opens with a BUY and closes with a SELL. So entry_px
          contributes to buy-side turnover; exit_px to sell-side.
        """
        legs = list(legs)
        if not legs:
            raise ValueError("CostModelV1.total_cost called with no legs")

        n_orders = len(legs) * 2  # entry order + exit order per leg
        sell_side_turnover = 0.0
        buy_side_turnover = 0.0

        for leg in legs:
            shares = int(leg["qty_lots"]) * int(leg["lot_size"])
            entry_turnover = float(leg["entry_px"]) * shares
            exit_turnover = float(leg["exit_px"]) * shares
            side = leg["side"]
            if side == "SELL":
                sell_side_turnover += entry_turnover  # SELL at open
                buy_side_turnover += exit_turnover    # BUY at close
            elif side == "BUY":
                buy_side_turnover += entry_turnover   # BUY at open
                sell_side_turnover += exit_turnover   # SELL at close
            else:
                raise ValueError(f"leg side must be SELL or BUY, got {side!r}")

        total_turnover = sell_side_turnover + buy_side_turnover

        brokerage = n_orders * self.brokerage_per_order
        stt = sell_side_turnover * self.stt_sell_options_pct
        exchange = total_turnover * self.exchange_txn_pct
        gst = (brokerage + exchange) * self.gst_pct
        sebi = (total_turnover / 1e7) * self.sebi_per_crore
        stamp_duty = buy_side_turnover * self.stamp_duty_buy_pct

        total = brokerage + stt + exchange + gst + sebi + stamp_duty

        return {
            "brokerage": brokerage,
            "stt": stt,
            "exchange": exchange,
            "gst": gst,
            "sebi": sebi,
            "stamp_duty": stamp_duty,
            "total": total,
        }


# Default singleton: every backtest in the project uses this unless
# explicitly overridden. Frozen dataclass → safe to share.
COST_MODEL_V1 = CostModelV1()
