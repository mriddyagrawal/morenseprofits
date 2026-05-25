"""Per-trade gross P&L kernel.

The load-bearing module of Phase 3 — turns a Trade into a number.
The sign convention from SPECS §3a is implemented here once and only
here; every backtest depends on it.

Contracts:

1. **Sign convention** (SPECS §3a): per-leg gross P&L is
   ``(entry_px - exit_px) * side_sign(leg.side) * leg.qty_lots * lot_size``.
   SELL profits from premium decay; BUY profits from premium expansion.

2. **No look-ahead** (SPECS §3b): the kernel queries ``load_option`` with
   ``from_date=entry_date, to_date=exit_date``. It NEVER inspects any
   data with ``date > exit_date``. A frame returned by the loader that
   contains rows past exit_date is treated as a code bug and raises
   ``LookaheadError`` — that's stricter than necessary (the loader is
   already supposed to filter) but it pins the contract in code.

3. **No silent interpolation** (PLAN §4 rule #2): if any leg lacks a
   traded price on either entry_date OR exit_date,
   ``MissingDataError`` propagates. No averaging, no nearest-neighbour,
   no fill-forward.

4. **Lot size from the data, not a constant** (PLAN §4 rule #3): the
   per-row ``lot_size`` column on the entry-date option frame
   determines the multiplier. NSE changes lot sizes periodically;
   reading from per-row data sidesteps that whole class of bug.

Returns a dict matching SPECS §2.5 (`results` schema). Costs are NOT
applied here — see ``src/engine/costs.py``. The caller (sweeper /
single-trade runner) does ``net_pnl = gross_pnl - costs(trade)``.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Callable

import pandas as pd

from src.data import options_loader
from src.data.errors import LookaheadError, MissingDataError
from src.engine.costs import COST_MODEL_V1, CostModelV1
from src.engine.margin import MARGIN_MODEL_V1, MarginModelV1
from src.engine.slippage import SLIPPAGE_MODEL_V1, SlippageModelV1
from src.engine.vol import symbol_margin_pct as _symbol_margin_pct
from src.strategies.base import Leg, Trade, side_sign


# Type alias for a loader function — pluggable so tests can inject
# a deterministic fake without monkeypatching the module.
LoadOptionFn = Callable[..., pd.DataFrame]


def _pick_close_on(
    df: pd.DataFrame, target: date, *, context: str,
) -> tuple[float, int, int | None, int | None]:
    """Return (close, lot_size, volume, oi) for the row whose date equals
    ``target``. ``volume``/``oi`` are returned as ``None`` if those columns
    are absent (test fixtures use minimal frames); production loader frames
    always carry them per §2.3.

    Raises ``MissingDataError`` if no such row exists; raises
    ``LookaheadError`` if multiple rows share the date (parser bug).
    Does NOT check for rows past ``target`` — that lookahead check is
    enforced ONCE per leg in ``_price_one_leg`` against
    ``trade.exit_date`` (the trade's outer bound), since the kernel
    legitimately needs both entry and exit rows in the same frame."""
    if df.empty:
        raise MissingDataError(
            f"{context}: load_option returned empty frame; no price to use"
        )
    row = df[df["date"].dt.date == target]
    if len(row) == 0:
        raise MissingDataError(
            f"{context}: no traded row on {target}; can't price this leg"
        )
    if len(row) > 1:
        raise LookaheadError(
            f"{context}: multiple rows on {target} — duplicate date suggests "
            f"a parser bug, refusing to pick one silently"
        )
    r = row.iloc[0]
    volume: int | None = None
    oi: int | None = None
    if "volume" in row.columns and pd.notna(r["volume"]):
        volume = int(r["volume"])
    if "oi" in row.columns and pd.notna(r["oi"]):
        oi = int(r["oi"])
    return float(r["close"]), int(r["lot_size"]), volume, oi


def _price_one_leg(
    trade: Trade,
    leg: Leg,
    *,
    load_option_fn: LoadOptionFn,
    today_fn: Callable[[], date],
    slippage_model: SlippageModelV1 = SLIPPAGE_MODEL_V1,
) -> dict:
    """Price a single leg of ``trade``. Returns a dict that the trade-
    level pricer aggregates into the results-schema row."""
    df = load_option_fn(
        trade.symbol,
        trade.expiry,
        leg.strike,
        leg.option_type,
        trade.entry_date,
        trade.exit_date,
        today_fn=today_fn,
    )
    context = (
        f"{trade.symbol} {trade.expiry} {int(leg.strike)}-{leg.option_type}"
    )
    # No-look-ahead invariant (SPECS §3b): the frame returned by the
    # loader for window [entry_date, exit_date] must contain ZERO rows
    # past exit_date. Real loaders filter; this checks they did.
    if not df.empty and (df["date"].dt.date > trade.exit_date).any():
        offenders = df.loc[df["date"].dt.date > trade.exit_date, "date"].head(3).tolist()
        raise LookaheadError(
            f"{context}: frame contains rows past exit_date {trade.exit_date}: "
            f"{[str(d) for d in offenders]}. Look-ahead bias would leak."
        )
    entry_px, entry_lot, entry_vol, entry_oi = _pick_close_on(
        df, trade.entry_date, context=f"{context} entry",
    )
    exit_px, exit_lot, exit_vol, exit_oi = _pick_close_on(
        df, trade.exit_date, context=f"{context} exit",
    )
    # Lot size at ENTRY is what's used for the P&L calc (NSE rarely
    # changes lot size mid-contract; if it ever does, exit_lot would
    # differ and we'd want to know — assert).
    if entry_lot != exit_lot:
        raise LookaheadError(  # not really lookahead, but loud-failure class
            f"{context}: lot_size changed mid-contract "
            f"({entry_lot} -> {exit_lot}); refusing to price silently"
        )
    # Apply slippage to raw closes (SPECS §4b): the engine transacts at
    # entry_px_realized / exit_px_realized, not at the raw close.
    entry_px_realized, exit_px_realized = slippage_model.realized_entry_exit(
        leg.side, entry_px, exit_px,
    )
    sign = side_sign(leg.side)
    gross = (entry_px_realized - exit_px_realized) * sign * leg.qty_lots * entry_lot
    return {
        "option_type": leg.option_type,
        "strike": float(leg.strike),
        "side": leg.side,
        "qty_lots": leg.qty_lots,
        "lot_size": entry_lot,
        "entry_px": entry_px,                  # raw close from loader
        "exit_px": exit_px,                    # raw close from loader
        "entry_px_realized": entry_px_realized,  # post-slippage
        "exit_px_realized": exit_px_realized,    # post-slippage
        # Liquidity at entry + exit (shares units; contracts = vol/lot_size).
        # Surfaces per-leg thinness so the drill-down can flag low-OI /
        # zero-volume legs that the flat 1% slippage model under-charges.
        "entry_volume": entry_vol,
        "exit_volume": exit_vol,
        "entry_oi": entry_oi,
        "exit_oi": exit_oi,
        "gross_pnl": gross,
    }


def _safe_roi(net: float, margin: float) -> float | None:
    """Return on capital, %. None if margin is zero (avoid div-by-zero —
    a trade with zero margin is impossible in practice but defensive)."""
    if margin <= 0:
        return None
    return 100.0 * net / margin


def _annualize_roi(roi_pct: float | None, hold_trading_days: int) -> float | None:
    """Scale holding-period ROI to a 252-trading-day year. SPECS §4a
    caveat #2: cross-window ranking is meaningless without this — a
    30-day-hold strategy at 0.65% ROI looks identical in a leaderboard
    to a 5-day-hold strategy at 0.65% even though the second is 6× the
    daily rate.

    Returns None if roi_pct is None or hold_trading_days <= 0."""
    if roi_pct is None or hold_trading_days <= 0:
        return None
    return float(roi_pct) * 252.0 / hold_trading_days


def price_trade(
    trade: Trade,
    *,
    load_option_fn: LoadOptionFn | None = None,
    cost_model: CostModelV1 = COST_MODEL_V1,
    margin_model: MarginModelV1 = MARGIN_MODEL_V1,
    slippage_model: SlippageModelV1 = SLIPPAGE_MODEL_V1,
    strategy_offset_pct: float = 1.0,
    symbol_margin_pct: float | None = None,
    spot_at_entry: float | None = None,
    hold_trading_days: int | None = None,
    today_fn: Callable[[], date] = date.today,
) -> dict:
    """Price every leg of ``trade``; return one row in the
    results-schema (SPECS §2.5) shape with the full financial picture:
    `gross_pnl`, `costs`, `net_pnl`, `margin_at_entry`, and `roi_pct`
    (net_pnl / margin × 100).

    Tier-B margin kwargs (per SPECS §4a):

    - ``strategy_offset_pct`` (default 1.0): multiplier on sell-leg
      margin to reflect SPAN's multi-leg offset benefit. Strategy
      classes pass their real-world offset (short straddle 0.60, etc.);
      single-leg / long-only trades leave at 1.0.
    - ``symbol_margin_pct`` (default None = auto): per-symbol SPAN%
      derived from the symbol's realized vol via ``engine.vol``. If
      ``None``, the engine computes it from spot cache as of
      ``trade.entry_date``; passing an explicit float overrides
      (useful for tests and sensitivity analysis). Falls back to
      the margin model's uniform default if computation fails.
    - ``spot_at_entry`` (default None = strike-based — caveat #1):
      when provided, SELL-leg notional uses spot × shares × symbol_pct
      instead of strike × shares × symbol_pct. The sweeper passes the
      symbol's spot on entry_date to get the better approximation;
      ad-hoc callers can omit to preserve the legacy strike-based path.
    - ``hold_trading_days`` (default None — SPECS §4a caveat #2):
      exact trading-day hold count. The sweeper passes
      ``entry_offset_td − exit_offset_td`` (exact by construction since
      both are trading-day offsets from expiry); standalone callers can
      omit and the engine falls back to the 252/365 calendar-day
      approximation. The approximation rounds short windows (e.g., 2
      calendar days → 1 trading day) and inflates ``roi_pct_annualized``
      by up to 2× for short-hold trades — biased exactly where the
      Phase-5 ranker would over-favor them.
    """
    # Resolve load_option_fn lazily so monkeypatch.setattr on
    # options_loader.load_option takes effect (defaults are evaluated
    # at function-def time, not call time).
    if load_option_fn is None:
        load_option_fn = options_loader.load_option
    leg_results = [
        _price_one_leg(
            trade, leg,
            load_option_fn=load_option_fn,
            today_fn=today_fn,
            slippage_model=slippage_model,
        )
        for leg in trade.legs
    ]
    gross = float(sum(r["gross_pnl"] for r in leg_results))
    cost_breakdown = cost_model.total_cost(leg_results)
    costs = float(cost_breakdown["total"])
    net = gross - costs

    # Resolve symbol_margin_pct: explicit kwarg > auto-compute > default.
    resolved_symbol_pct: float | None = symbol_margin_pct
    if resolved_symbol_pct is None:
        try:
            resolved_symbol_pct = _symbol_margin_pct(
                trade.symbol, trade.entry_date, today_fn=today_fn,
            )
        except Exception:
            # Vol computation can fail (insufficient history, missing
            # data) — fall back to the margin model's uniform default
            # silently. The margin number is still a reasonable
            # estimate; no need to break the whole trade pricing.
            resolved_symbol_pct = None

    margin_breakdown = margin_model.estimate(
        leg_results,
        strategy_offset_pct=strategy_offset_pct,
        symbol_margin_pct=resolved_symbol_pct,
        spot_at_entry=spot_at_entry,
    )
    margin = float(margin_breakdown["total"])

    # Holding-period vs annualized ROI (SPECS §4a caveat #2). When
    # the caller knows the exact trading-day hold (the sweeper does
    # — it's just entry_offset_td − exit_offset_td), use it; otherwise
    # fall back to the calendar-day × 252/365 approximation. The
    # approximation rounds short windows wrong (e.g., 2 calendar days
    # → round(1.38) = 1 trading day instead of 2) which biases
    # short-hold annualized ROI by up to 2×; the sweeper-pass-through
    # eliminates that for every sweep cell.
    if hold_trading_days is None:
        hold_calendar_days = max(1, (trade.exit_date - trade.entry_date).days)
        hold_trading_days = max(1, round(hold_calendar_days * 252 / 365))
    else:
        hold_trading_days = max(1, int(hold_trading_days))
    roi = _safe_roi(net, margin)
    return {
        "symbol": trade.symbol,
        "expiry": trade.expiry,
        "entry_date": trade.entry_date,
        "exit_date": trade.exit_date,
        "strategy": trade.strategy,
        "params_json": json.dumps(trade.params, sort_keys=True),
        "legs_json": json.dumps(leg_results, sort_keys=True, default=str),
        "gross_pnl": gross,
        "costs": costs,
        "net_pnl": net,
        "costs_breakdown_json": json.dumps(cost_breakdown, sort_keys=True),
        "margin_at_entry": margin,
        "margin_breakdown_json": json.dumps(margin_breakdown, sort_keys=True),
        "roi_pct": roi,
        "hold_trading_days": hold_trading_days,
        "roi_pct_annualized": _annualize_roi(roi, hold_trading_days),
    }
