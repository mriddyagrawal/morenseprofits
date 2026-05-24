"""MARGIN_MODEL_V1 — Indian options-specific margin approximation.

Margin is the capital that must be deposited as collateral while a
position is open. **Not** a cost — you get it back when you close the
trade. But it's load-bearing for ranking: a strategy that makes ₹2k on
₹1L margin (2% / month) beats one that makes ₹4k on ₹4L margin (1% /
month) even though absolute P&L favors the second.

NSE F&O margin asymmetry between BUY and SELL legs (SPECS §4a):

- **BUY leg** (long option): you pay the full premium upfront. That
  premium IS the max possible loss; nothing additional is blocked.
  ``margin_per_buy_leg = entry_premium × qty × lot_size``.

- **SELL leg** (short option, naked): you receive the premium as credit
  but the broker blocks SPAN + Exposure margin because losses are
  unbounded. Real SPAN math depends on daily volatility + NSE's SPAN
  file; we approximate with a constant fraction of the underlying
  notional:
  ``margin_per_sell_leg ≈ 0.20 × strike × qty × lot_size``
  (covers SPAN 13-18% + Exposure 3-5% per NSE's typical ranges).

**Multi-leg conservatism**: real SPAN gives benefit for partially-
offsetting legs (short straddle's max loss is bounded by the gap
between strikes if both ITM, etc.). v1 sums per-leg margins, which
**overstates** real margin. Backtest P&L per margin will look slightly
worse than real-broker P&L per margin — the SAFE direction for a
paper-then-live-trade pipeline.

Phase 7 backlog: parse NSE's SPAN file for accurate per-position margin.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class MarginModelV1:
    """SPECS §4a rates. Frozen — Phase-5 sensitivity builds new instances."""
    # SPAN + Exposure approximation for SELL legs (fraction of strike × shares).
    # NSE SPAN for single-stock options is typically 13-18%; exposure
    # adds 3-5%. 0.20 covers both with a small buffer (intentionally
    # slightly conservative).
    span_plus_exposure_pct: float = 0.20

    def estimate(
        self,
        legs: Iterable[dict],
        *,
        strategy_offset_pct: float = 1.0,
        symbol_margin_pct: float | None = None,
    ) -> dict:
        """Return per-component margin + total for a trade's priced legs.

        Each ``leg`` dict mirrors what engine.pnl._price_one_leg emits:
        ``side`` (SELL|BUY), ``qty_lots``, ``lot_size``, ``strike``,
        ``entry_px``.

        Tier-B optional kwargs (per SPECS §4a):

        ``strategy_offset_pct`` (default 1.0 = Tier-A conservative):
        multiplier on the SELL-leg margin total to reflect SPAN's
        portfolio-level offset benefit for multi-leg strategies.
        Strategy classes pass their real-world offset: short straddle
        0.60, short strangle 0.70, iron condor 0.35, naked 1.0.

        ``symbol_margin_pct`` (default None = use
        ``span_plus_exposure_pct``): per-symbol SPAN%, computed from
        realized vol in ``src/engine/vol.py``. When provided, overrides
        the model's uniform default. Lets high-vol stocks get higher
        margin blocks than low-vol stocks (real NSE SPAN does this).

        Returns dict with: ``sell_leg_margin_raw`` (sum before offset),
        ``sell_leg_margin`` (post-offset), ``buy_leg_premium``,
        ``strategy_offset_pct``, ``symbol_margin_pct``, ``total``.
        """
        legs = list(legs)
        if not legs:
            raise ValueError("MarginModelV1.estimate called with no legs")
        if not 0.0 < strategy_offset_pct <= 1.0:
            raise ValueError(
                f"strategy_offset_pct must be in (0, 1], got {strategy_offset_pct}"
            )

        margin_pct = (
            float(symbol_margin_pct) if symbol_margin_pct is not None
            else self.span_plus_exposure_pct
        )

        sell_margin_raw = 0.0
        buy_premium = 0.0

        for leg in legs:
            qty = int(leg["qty_lots"])
            lot = int(leg["lot_size"])
            shares = qty * lot
            if leg["side"] == "SELL":
                # Strike × shares × SPAN%. Independent of premium —
                # NSE blocks based on underlying notional, not premium.
                sell_margin_raw += margin_pct * float(leg["strike"]) * shares
            elif leg["side"] == "BUY":
                # Just the premium paid upfront — max loss for a long
                # option is the premium itself.
                buy_premium += float(leg["entry_px"]) * shares
            else:
                raise ValueError(f"leg side must be SELL or BUY, got {leg['side']!r}")

        sell_margin = sell_margin_raw * strategy_offset_pct

        return {
            "sell_leg_margin_raw": sell_margin_raw,
            "sell_leg_margin": sell_margin,
            "buy_leg_premium": buy_premium,
            "strategy_offset_pct": float(strategy_offset_pct),
            "symbol_margin_pct": margin_pct,
            "total": sell_margin + buy_premium,
        }


# Default singleton. Frozen → safe to share.
MARGIN_MODEL_V1 = MarginModelV1()
