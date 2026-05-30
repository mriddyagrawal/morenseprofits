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
from src.data.errors import IlliquidLegError, LookaheadError, MissingDataError
from src.engine.costs import COST_MODEL_V1, CostModelV1
from src.engine.margin import MARGIN_MODEL_V1, MarginModelV1
from src.engine.slippage import SLIPPAGE_MODEL_V1, SlippageModelV1
from src.engine.vol import symbol_margin_pct as _symbol_margin_pct
from src.strategies.base import Leg, Trade, side_sign


# Type alias for a loader function — pluggable so tests can inject
# a deterministic fake without monkeypatching the module.
LoadOptionFn = Callable[..., pd.DataFrame]


# Units conversion for NSE F&O turnover.
#
# NSE's per-contract historical archive reports total traded value
# (``FH_TOT_TRADED_VAL`` → "PREMIUM VALUE") in LAKHS of rupees, not
# raw rupees. Verified against jugaad-data's legacy schema where the
# same field appears as ``VAL_INLAKH`` — the units are literally in
# the column name. The modern direct-fetch API follows the same
# convention.
#
# To compute a per-share VWAP in rupees: ``turnover * 100_000 / volume``.
# A median-ratio sanity check fires per-leg (see _pick_fill_price) so
# if NSE ever shifts the convention the wrong value surfaces loudly
# rather than silently producing fill prices off by 5 orders of
# magnitude.
TURNOVER_SCALE_FACTOR = 100_000.0

# VWAP-vs-close ratio bounds for the units-sanity assertion. A real
# day's VWAP should land within the day's OHLC range; for any but the
# most pathological intraday-trajectory contract, VWAP and close
# should be within roughly 50% of each other. Tighter bounds risk
# false positives on legitimately-volatile days; looser bounds risk
# masking a real units bug.
_VWAP_CLOSE_RATIO_MIN = 0.5
_VWAP_CLOSE_RATIO_MAX = 2.0


def _compute_vwap(turnover: float | None, volume: int | None) -> float | None:
    """Daily volume-weighted average price from turnover + volume.
    Returns None if either input is missing/NaN/zero — caller falls
    back to ``close`` in that case.

    Units: turnover is lakhs of rupees per NSE's historical archive
    convention (see ``TURNOVER_SCALE_FACTOR``), volume is shares.
    Output is rupees per share — directly comparable to ``close``."""
    if turnover is None or volume is None or volume == 0:
        return None
    if pd.isna(turnover):
        return None
    return float(turnover) * TURNOVER_SCALE_FACTOR / float(volume)


def _pick_fill_price(
    df: pd.DataFrame, target: date, *, context: str,
) -> tuple[float, int, int | None, int | None, float | None]:
    """Return (fill_px, lot_size, volume, oi, turnover) for the row
    whose date equals ``target``. ``fill_px`` is VWAP (turnover *
    scale / volume) when turnover + volume are both present and the
    VWAP-vs-close ratio passes a sanity check; falls back to ``close``
    otherwise.

    Why VWAP over close: close is the day's last trade, which on a
    thin-volume day can be a small print far from where the bulk of
    volume cleared. VWAP represents the volume-weighted centre of mass
    of the day's trading — materially closer to a real fill price
    than close for thin strikes.

    Sanity check: if a row has turnover + volume but the computed VWAP
    lands outside [0.5×, 2.0×] of close, raises ``MissingDataError``
    pointing at a likely units bug (NSE shifted convention, or a
    parser regression). This is a research-honesty trip-wire: silently
    producing a fill price 100,000× off close would be the worst
    failure mode the units risk can produce; failing loudly is the
    right behavior.

    ``volume`` / ``oi`` / ``turnover`` are returned as ``None`` if
    those columns are absent (legacy minimal test fixtures); production
    loader frames always carry them per §2.3.

    Raises ``MissingDataError`` if no row matches ``target``, or
    ``LookaheadError`` if multiple rows share the date (parser bug).
    Lookahead-vs-exit_date is enforced ONCE per leg in
    ``_price_one_leg`` against the trade's outer bound; this helper
    only validates duplicate-date.
    """
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
    close = float(r["close"])
    volume: int | None = None
    oi: int | None = None
    turnover: float | None = None
    if "volume" in row.columns and pd.notna(r["volume"]):
        volume = int(r["volume"])
    if "oi" in row.columns and pd.notna(r["oi"]):
        oi = int(r["oi"])
    if "turnover" in row.columns and pd.notna(r["turnover"]):
        turnover = float(r["turnover"])

    vwap = _compute_vwap(turnover, volume)
    if vwap is None:
        # No turnover available (legacy cache, NaN turnover, zero
        # volume). Use close — same behavior as pre-VWAP.
        fill_px = close
    else:
        # Units-sanity assertion: VWAP / close must land in the
        # plausible band. Outside the band points at a NSE units
        # shift OR a parser regression; either way the engine should
        # refuse to book a trade rather than silently use a fill price
        # off by orders of magnitude.
        ratio = vwap / close if close != 0 else float("inf")
        if not (_VWAP_CLOSE_RATIO_MIN <= ratio <= _VWAP_CLOSE_RATIO_MAX):
            raise MissingDataError(
                f"{context}: VWAP/close ratio {ratio:.4g} outside "
                f"[{_VWAP_CLOSE_RATIO_MIN}, {_VWAP_CLOSE_RATIO_MAX}] on "
                f"{target} — likely a units mismatch on PREMIUM VALUE "
                f"(turnover={turnover}, volume={volume}, close={close}, "
                f"computed vwap={vwap:.4f}). Refusing to book a trade "
                f"against a suspicious fill price."
            )
        fill_px = vwap
    return fill_px, int(r["lot_size"]), volume, oi, turnover


# ============================================================
# Fill-source audit helpers (shared with src/web + src/mcp)
# ============================================================
#
# Used by the dashboard's drill-down CSV export and the MCP
# backtest_one tool to classify each leg's fill as VWAP-derived,
# close-derived, or indeterminate. Centralized here per reviewer
# grills on c3545cc + 6ab4866: two duplicates had drifted independently;
# any future third consumer (e.g. a data_quality MCP tool) would
# compound the drift risk.
#
# Tolerance choice: relative 0.1% OR absolute 0.001 rupees, whichever
# is larger. The absolute floor is load-bearing for deep-OTM contracts
# (₹0.05 premium) where a tight relative tolerance would require
# byte-perfect agreement that turnover precision can't deliver.

VWAP_MATCH_TOLERANCE_REL = 1e-3
VWAP_MATCH_TOLERANCE_ABS = 1e-3


def classify_fill_source(
    entry_px: float | int | None,
    volume: int | None,
    turnover: float | None,
) -> str:
    """Derive whether the engine used VWAP or close based on per-leg
    telemetry. Mirrors the ``_pick_fill_price`` decision logic from
    the perspective of a post-hoc auditor reading legs_json fields.

    Returns one of:
      ``'vwap'``     — turnover + volume present AND entry_px matches
                       ``turnover × TURNOVER_SCALE_FACTOR / volume``
                       within tolerance.
      ``'close'``    — turnover unavailable OR volume = 0 (no VWAP
                       path possible), OR engine had VWAP available
                       but the result fell outside the units-sanity
                       band [_VWAP_CLOSE_RATIO_MIN, MAX] and got
                       rejected. The recorded entry_px is the close.
      ``'unknown'``  — entry_px is missing / NaN; can't classify.

    Tolerance is ``max(VWAP_MATCH_TOLERANCE_REL × |entry_px|,
    VWAP_MATCH_TOLERANCE_ABS)`` — relative-OR-absolute so deep-OTM
    contracts (₹0.05 premium) don't fail-match on turnover quantisation
    while liquid ATM contracts (₹100+ premium) still get a meaningful
    relative check.
    """
    import math
    if entry_px is None:
        return "unknown"
    try:
        f = float(entry_px)
    except (TypeError, ValueError):
        return "unknown"
    if math.isnan(f):
        return "unknown"
    has_turnover = (
        turnover is not None
        and not (isinstance(turnover, float) and math.isnan(turnover))
    )
    has_volume = volume is not None and volume > 0
    if not has_turnover or not has_volume:
        return "close"
    vwap_implied = float(turnover) * TURNOVER_SCALE_FACTOR / float(volume)
    tol = max(VWAP_MATCH_TOLERANCE_REL * abs(f), VWAP_MATCH_TOLERANCE_ABS)
    if abs(vwap_implied - f) <= tol:
        return "vwap"
    return "close"  # engine had VWAP available but used close (band reject)


# Backward-compat shim: existing callers (and the public price_trade
# entry point) call ``_pick_close_on`` and expect the 4-tuple. Keep
# the old name as an alias that drops the turnover field, while the
# kernel internally uses ``_pick_fill_price``. This avoids touching
# the public test surface for callers that don't need turnover.
def _pick_close_on(
    df: pd.DataFrame, target: date, *, context: str,
) -> tuple[float, int, int | None, int | None]:
    """Legacy 4-tuple wrapper around ``_pick_fill_price``. Returned
    fill price is VWAP (when available) or close (fallback), but the
    column is still named ``close`` historically for callers that
    haven't been migrated to the new helper.

    New code should call ``_pick_fill_price`` directly and use the
    5-tuple form to get turnover for downstream audit / VWAP-divergence
    analysis."""
    fill_px, lot_size, volume, oi, _turnover = _pick_fill_price(
        df, target, context=context,
    )
    return fill_px, lot_size, volume, oi


def _price_one_leg(
    trade: Trade,
    leg: Leg,
    *,
    load_option_fn: LoadOptionFn,
    today_fn: Callable[[], date],
    slippage_model: SlippageModelV1 = SLIPPAGE_MODEL_V1,
    offline: bool = False,
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
        offline=offline,
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
    entry_px, entry_lot, entry_vol, entry_oi, entry_turnover = _pick_fill_price(
        df, trade.entry_date, context=f"{context} entry",
    )
    exit_px, exit_lot, exit_vol, exit_oi, exit_turnover = _pick_fill_price(
        df, trade.exit_date, context=f"{context} exit",
    )
    # Lot size at ENTRY differing from EXIT means the contract straddled
    # a corporate-action ex-date (split / bonus / merger) — NSE adjusts
    # F&O contracts so the same contract has DIFFERENT lot sizes on
    # either side of the action. We can't price across the action
    # without adjustment math (strike + qty also need ratio'ing), so
    # skip via MissingDataError → sweeper records the cell + reason in
    # the skip log and the sweep continues. NOT a LookaheadError: the
    # data isn't bad, it's just unpriceable under our v1 model.
    if entry_lot != exit_lot:
        raise MissingDataError(
            f"{context}: lot_size changed mid-contract "
            f"({entry_lot} -> {exit_lot}); likely a corporate action "
            f"(split / bonus / merger). Skipping — pricing across the "
            f"adjustment requires strike+qty ratio'ing we don't model yet."
        )

    # Liquidity gate (p7.pricing.liquidity_gate): refuse to book a trade
    # whose entry or exit leg had ZERO traded contracts, or whose entry
    # day had ZERO open interest. NSE often publishes a close even when
    # nothing traded (theoretical fallback baked into the close field);
    # without this gate, the engine books a P&L on a price no participant
    # transacted at. The gate uses fields the loader already surfaces
    # (volume, oi) — no new data, no new fetches.
    #
    # Single skip reason (IlliquidLegError) for both volume=0 and oi=0
    # cases; the per-leg numbers are captured in the message for audit.
    # See errors.py::IlliquidLegError for the research-honesty-vs-deploy-
    # readiness caveat.
    if entry_vol == 0 or exit_vol == 0 or entry_oi == 0:
        raise IlliquidLegError(
            f"{context}: leg illiquid — "
            f"entry_volume={entry_vol}, exit_volume={exit_vol}, "
            f"entry_oi={entry_oi}. No real fill possible; skipping."
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
        "entry_px": entry_px,                  # VWAP if available, else close
        "exit_px": exit_px,                    # VWAP if available, else close
        "entry_px_realized": entry_px_realized,  # post-slippage
        "exit_px_realized": exit_px_realized,    # post-slippage
        # Liquidity at entry + exit (shares units; contracts = vol/lot_size).
        # Surfaces per-leg thinness so the drill-down can flag low-OI /
        # zero-volume legs that the flat 1% slippage model under-charges.
        "entry_volume": entry_vol,
        "exit_volume": exit_vol,
        "entry_oi": entry_oi,
        "exit_oi": exit_oi,
        # Per-leg turnover (in lakhs of rupees, NSE convention) for post-
        # hoc audit of VWAP vs close divergence. NaN on legacy parquets
        # whose ingest predated the turnover column landing — downstream
        # consumers should handle that by falling back to ``entry_px``
        # (which already encodes the choice between VWAP and close).
        "entry_turnover": entry_turnover,
        "exit_turnover": exit_turnover,
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
    offline: bool = False,
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
            offline=offline,
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
