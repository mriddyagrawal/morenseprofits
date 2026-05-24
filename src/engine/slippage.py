"""SLIPPAGE_MODEL_V1 — bid-ask haircut on every trade-leg's entry/exit.

Backtesting at close (the last traded price) systematically over-promises
because real bids/asks live ~1-2% away from close on NSE blue-chip
options. Without slippage, every backtest P&L number is optimistic by
~₹500 per straddle trade. Phase-4 sweeps aggregated across thousands of
trades would otherwise steer the operator toward false-positive winning
windows.

SPECS §4b: the model moves prices *against you* in both directions —
- SELL receives less than close
- BUY pays more than close

Per-leg realized prices replace the raw close in the gross-P&L calc.
Both raw and realized are reported in the result so audit trails are
intact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class SlippageModelV1:
    """Uniform per-side slippage. Phase-7 backlog: per-symbol rates."""
    slippage_pct: float = 0.01  # 1% per side; realistic for NSE blue-chip options

    def __post_init__(self):
        if not 0.0 <= self.slippage_pct < 1.0:
            raise ValueError(
                f"slippage_pct must be in [0, 1), got {self.slippage_pct}"
            )

    def realized_price(
        self,
        raw_close: float,
        action: Literal["SELL", "BUY"],
    ) -> float:
        """Returns the price the engine actually transacts at when the
        given action happens at the raw close.

        - action == "SELL" → receive LESS than close (price haircut down)
        - action == "BUY"  → pay MORE than close (price haircut up)
        """
        if action == "SELL":
            return float(raw_close) * (1.0 - self.slippage_pct)
        if action == "BUY":
            return float(raw_close) * (1.0 + self.slippage_pct)
        raise ValueError(f"action must be 'SELL' or 'BUY', got {action!r}")

    def realized_entry_exit(
        self,
        side: Literal["SELL", "BUY"],
        entry_close: float,
        exit_close: float,
    ) -> tuple[float, float]:
        """Convenience: given a leg's `side` (entry direction) and raw
        closes, return (entry_realized, exit_realized). The exit action
        is always the opposite of `side` (closing the position)."""
        if side == "SELL":
            return (
                self.realized_price(entry_close, "SELL"),
                self.realized_price(exit_close, "BUY"),
            )
        if side == "BUY":
            return (
                self.realized_price(entry_close, "BUY"),
                self.realized_price(exit_close, "SELL"),
            )
        raise ValueError(f"side must be 'SELL' or 'BUY', got {side!r}")


SLIPPAGE_MODEL_V1 = SlippageModelV1()
