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
from src.data.errors import (
    LookaheadError,
    MissingDataError,
    MissingTurnoverError,
)
from src.engine.costs import COST_MODEL_V1, CostModelV1
from src.engine.margin import MARGIN_MODEL_V1, MarginModelV1
from src.engine.slippage import SLIPPAGE_MODEL_V1, SlippageModelV1
from src.engine.vol import symbol_margin_pct as _symbol_margin_pct
from src.strategies.base import Leg, Trade, side_sign


# Type alias for a loader function — pluggable so tests can inject
# a deterministic fake without monkeypatching the module.
LoadOptionFn = Callable[..., pd.DataFrame]


# Units convention for NSE F&O turnover (post-F1, see LOGIC_REVIEW.md).
#
# The engine sees turnover in a SINGLE canonical convention: RUPEES.
# Parser-layer normalization at the three ingest sites brings the
# raw upstream conventions into this single shape:
#
#   - UDiff bhavcopy (``TtlTrfVal``): RUPEES natively — no scaling.
#   - Legacy bhavcopy (``VAL_INLAKH``): LAKHS — multiplied × 1e5 in
#     ``bhavcopy_fo_loader.parse_legacy`` at parse time.
#   - jugaad API (``FH_TOT_TRADED_VAL`` → "PREMIUM VALUE"): LAKHS —
#     multiplied × 1e5 in ``options_loader._normalize`` at parse time.
#
# Pre-F1 the engine carried a ×1e5 scale factor here on the assumption
# all three raw conventions were the same (lakhs). They are NOT —
# UDiff is rupees, while jugaad+legacy are lakhs. Treating UDiff as
# lakhs overshot VWAP by five orders of magnitude → band-rejected →
# 100% silent close fallback. The fix moves the unit normalization
# to parse time so a single TURNOVER_SCALE_FACTOR=1.0 works for all
# three regimes (see LOGIC_REVIEW.md F1 + addendum 1).
#
# Empirical anchor (RELIANCE 2024-08-29 2840-CE, post-F1 fix):
#   TtlTrfVal      = 19,661,050 rupees       (UDiff bhavcopy)
#   volume         = 6,500 shares            (26 contracts × 250 lot)
#   strike         = 2,840
#   notional/share = 19,661,050 / 6,500      = 3,024.78
#   premium_vwap   = 3,024.78 − 2,840        =   184.78 ✓
# The identity being verified is the underlying-notional convention
# documented in LOGIC_REVIEW.md F1: notional/share == strike + premium
# (3,024.78 = 2,840 + 184.78), not anything involving spot. This is
# an ITM call (spot 3,041 > strike 2,840) — earlier framing as
# "deep-OTM" was wrong on both moneyness AND identity. See
# LOGIC_REVIEW.md §1a F1 table for the full 4-symbol cross-check
# and the RELIANCE 2025-02-27 DTE-grid analysis.
#
# To recover the per-share premium VWAP in rupees:
#   premium_vwap = turnover * TURNOVER_SCALE_FACTOR / volume - strike
#                = turnover / volume - strike   (since SCALE = 1.0)
TURNOVER_SCALE_FACTOR = 1.0

# Recovered-premium-vs-close ratio bounds. After the strike correction
# the formula is arithmetically sound, so the band-check is no longer
# a units-sanity assertion; it's a numerical-ill-conditioning safety
# valve. Deep-OTM contracts (premium ≪ strike) push us into subtracting
# two large nearly-equal numbers, and turnover's rounding gets
# amplified into a residual that can swing far from close (or go
# negative). Under P1.7 (operator 2026-06-03 + reviewer F6 ship verdict),
# a band-reject on a thin contract RAISES MissingTurnoverError so the
# sweeper skips the cell honestly — the prior close-fallback fudged
# the fill with a tick-floor close print that misled backtest analysis.
# On LIQUID contracts (contracts_traded ≥
# _VWAP_LIQUIDITY_BYPASS_CONTRACTS) the band check is bypassed
# entirely and VWAP is used unconditionally — the band's "VWAP could
# be a thin-trade outlier" concern doesn't apply when N trades is
# large.
_VWAP_CLOSE_RATIO_MIN = 0.5
_VWAP_CLOSE_RATIO_MAX = 2.0

# Contracts-traded threshold for trusting VWAP unconditionally
# without the band check. The Option C bypass is keyed on contracts
# rather than share-volume so the threshold is SYMBOL-INVARIANT —
# 20 contracts means "the contract had ≥20 trade clears worth of
# price discovery" whether the lot_size is 75 (NIFTY) or 8000 (PNB),
# whereas a fixed share-volume threshold (e.g., 100k shares) meant
# wildly different trade counts across symbols (~12 contracts for
# PNB vs ~400 contracts for RELIANCE).
#
# Empirical basis (LOGIC_REVIEW.md F-band analysis, 2026-06-03 + the
# operator-driven recalibration after P1.7 first ship): of 8,168
# close-fallback cases in the F1-verified post-fix sweep, the median
# row had thousands of contracts; 20 catches ≥99.5% of the same
# liquid-contract close-fallback set while keeping the threshold
# defensible (≥20 contracts typically means ≥5-10 distinct trades,
# enough averaging that VWAP is meaningfully more stable than the
# single closing print). Below 20, the band stays as the safety
# valve for thin contracts where a single-trade outlier could
# dominate VWAP.
_VWAP_LIQUIDITY_BYPASS_CONTRACTS = 20  # ≥ this many contracts traded → VWAP is trusted


def _compute_vwap(
    turnover: float | None,
    volume: int | None,
    strike: float,
) -> float | None:
    """Daily volume-weighted average PREMIUM from notional turnover.

    NSE's per-contract turnover (post parser-layer normalization) is
    the day's underlying-notional flow in RUPEES — empirically
    ``(strike + premium) × shares``, NOT the premium turnover the
    "PREMIUM VALUE" jugaad label suggests. To recover the per-share
    premium VWAP we subtract the strike:

        premium_vwap = turnover * TURNOVER_SCALE_FACTOR / volume - strike
                     = turnover / volume - strike   (since SCALE = 1.0)

    Returns None when:
      - turnover or volume is missing/NaN/zero (no VWAP path possible;
        caller falls back to ``close``); OR
      - the recovered premium is ≤ 0 (deep-OTM ill-conditioning: at
        premium ≪ strike, turnover rounding of the underlying-notional
        gets amplified into a residual that can flip negative; caller
        falls back to ``close`` in that case too).

    Units: turnover is rupees (parser-layer normalized — see comment
    on TURNOVER_SCALE_FACTOR + LOGIC_REVIEW.md F1); volume is shares;
    strike is rupees. Output is rupees per share — directly comparable
    to ``close``."""
    if turnover is None or volume is None or volume == 0:
        return None
    if pd.isna(turnover):
        return None
    notional_per_share = float(turnover) * TURNOVER_SCALE_FACTOR / float(volume)
    premium_vwap = notional_per_share - float(strike)
    if premium_vwap <= 0:
        # Deep-OTM numerical ill-conditioning — recovered premium went
        # nonsensical because turnover rounding is comparable to the
        # actual residual. Fall through to close.
        return None
    return premium_vwap


def _pick_fill_price(
    df: pd.DataFrame, target: date, *, context: str,
) -> tuple[float, int, int | None, int | None, float | None]:
    """Return (fill_px, lot_size, volume, oi, turnover) for the row
    whose date equals ``target``. Under P1.7 (operator 2026-06-03 +
    reviewer F6 ship verdict), ``fill_px`` is ALWAYS the recovered
    premium VWAP (``turnover * SCALE / volume − strike``); the
    pre-P1.7 close-fallback paths now RAISE ``MissingTurnoverError``
    so the sweeper skips the cell with an honest skip_reason rather
    than fudging a fill with the tick-floor close print.

    Decision tree:

      1. ``turnover`` is None / NaN, OR ``volume`` is None / 0, OR
         ``strike`` is missing (minimal test fixture): raise
         ``MissingTurnoverError`` — no VWAP path is possible.
      2. Recovered ``premium_vwap = turnover/volume − strike`` is
         ≤ 0 (case 3 deep-OTM ill-conditioning — turnover rounding
         flips the residual on contracts where premium ≪ strike):
         raise ``MissingTurnoverError``. Per the P1.7 unified spec,
         this no longer falls through to close — the cell is
         unpriceable, and a close fill at the tick floor would
         systematically bias backtest analysis of deep-OTM legs.
      3. ``contracts_traded = volume // lot_size ≥
         _VWAP_LIQUIDITY_BYPASS_CONTRACTS`` (default 20 contracts):
         use VWAP UNCONDITIONALLY. Skip the band check — at this
         trade count the VWAP integrates over enough distinct
         clears to be structurally more stable than the single
         closing print, and the band's "thin-contract single-trade
         outlier" concern doesn't apply. Symbol-invariant by
         construction.
      4. Otherwise (thin contract: contracts_traded < threshold),
         check the band:
         - VWAP-vs-close ratio ∈ [0.5×, 2.0×] → use VWAP.
         - Out of band → raise ``MissingTurnoverError``. On a thin
           contract the band reject signals genuine arithmetic
           ill-conditioning; the cell is unpriceable.

    ``volume`` / ``oi`` / ``turnover`` are returned as ``None`` only
    when the row's column is absent (legacy minimal test fixtures);
    production loader frames carry all three per SPECS §2.3 — those
    cases bail to (1) above before returning.

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
    strike: float | None = None
    if "strike" in row.columns and pd.notna(r["strike"]):
        strike = float(r["strike"])
    volume: int | None = None
    oi: int | None = None
    turnover: float | None = None
    if "volume" in row.columns and pd.notna(r["volume"]):
        volume = int(r["volume"])
    if "oi" in row.columns and pd.notna(r["oi"]):
        oi = int(r["oi"])
    if "turnover" in row.columns and pd.notna(r["turnover"]):
        turnover = float(r["turnover"])

    # (1+2) Cases 1+2: missing turnover, volume, or strike → no VWAP
    # path. Under the P1.7 unified spec (operator 2026-06-03) the
    # taxonomy is collapsed: every "can't compute VWAP fill" case
    # surfaces as MissingTurnoverError. IlliquidLegError is no
    # longer raised by the engine — it was a holdover from the
    # pre-VWAP era where "volume=0 means no real fill" was a
    # distinct concept; under VWAP-or-skip it's just one of the
    # missing-data shapes.
    if turnover is None or volume is None or volume == 0 or strike is None:
        raise MissingTurnoverError(
            f"{context}: cannot compute VWAP fill on {target} "
            f"(turnover={turnover!r}, volume={volume!r}, strike={strike!r}); "
            f"P1.7 strip — cell unpriceable, skipping."
        )

    notional_per_share = float(turnover) * TURNOVER_SCALE_FACTOR / float(volume)
    premium_vwap = notional_per_share - float(strike)

    # (2) Case 3: deep-OTM ill-conditioning. Turnover precision is
    # comparable to the actual residual; recovered premium goes
    # nonsensical. Under P1.7 we skip the cell rather than booking a
    # close-fallback fill that would bias analysis.
    if premium_vwap <= 0:
        raise MissingTurnoverError(
            f"{context}: recovered VWAP premium ≤ 0 on {target} "
            f"(notional/share={notional_per_share:.4f}, strike={strike}, "
            f"residual={premium_vwap:.6f}); deep-OTM ill-conditioning, "
            f"P1.7 strip — cell unpriceable, skipping."
        )

    # Read lot_size now so we can compute contracts_traded for the
    # bypass decision below. Production loader frames carry lot_size
    # per row; tests inject it via the _stub_load_option helpers.
    lot_size = int(r["lot_size"])
    contracts_traded = volume // lot_size if lot_size > 0 else 0

    # (3) Option C: liquidity-gated VWAP-band bypass. At
    # contracts_traded ≥ _VWAP_LIQUIDITY_BYPASS_CONTRACTS the
    # contract has cleared enough distinct trades that VWAP
    # integrates over genuine price discovery; trust VWAP
    # unconditionally and skip the band check. Symbol-invariant —
    # the threshold is the same whether the lot_size is 75 (NIFTY)
    # or 8000 (PNB).
    if contracts_traded >= _VWAP_LIQUIDITY_BYPASS_CONTRACTS:
        return premium_vwap, lot_size, volume, oi, turnover

    # (4) Thin contract: band-reject → skip.
    ratio = premium_vwap / close if close != 0 else float("inf")
    if not (_VWAP_CLOSE_RATIO_MIN <= ratio <= _VWAP_CLOSE_RATIO_MAX):
        raise MissingTurnoverError(
            f"{context}: VWAP-vs-close band reject on thin contract on "
            f"{target} (vwap={premium_vwap:.4f}, close={close:.4f}, "
            f"ratio={ratio:.4f}, contracts_traded={contracts_traded} < "
            f"{_VWAP_LIQUIDITY_BYPASS_CONTRACTS}); P1.7 strip — "
            f"cell unpriceable, skipping."
        )
    return premium_vwap, lot_size, volume, oi, turnover


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
    strike: float | None = None,
) -> str:
    """Derive whether the engine used VWAP or close based on per-leg
    telemetry. Mirrors the ``_pick_fill_price`` decision logic from
    the perspective of a post-hoc auditor reading legs_json fields.

    Returns one of:
      ``'vwap'``     — turnover + volume + strike present AND entry_px
                       matches the recovered premium VWAP
                       ``turnover * TURNOVER_SCALE_FACTOR / volume − strike``
                       ( = ``turnover / volume − strike`` since SCALE = 1.0
                       post-F1) within tolerance.
      ``'close'``    — turnover/volume/strike unavailable (no VWAP path
                       possible), OR engine had VWAP available but the
                       result fell outside the safety band
                       [_VWAP_CLOSE_RATIO_MIN, MAX] or went non-positive
                       and got rejected; the recorded entry_px is close.
      ``'unknown'``  — entry_px is missing / NaN; can't classify.

    ``strike`` is required to recover the correct premium VWAP — the
    raw notional-per-share without the strike correction is the
    underlying-notional flow, not the premium. ``strike=None`` keeps
    backwards compatibility with telemetry callers that haven't been
    updated yet but degrades the classification to "close" since the
    correct match value can't be computed.

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
    if not has_turnover or not has_volume or strike is None:
        return "close"
    notional_per_share = float(turnover) * TURNOVER_SCALE_FACTOR / float(volume)
    vwap_implied = notional_per_share - float(strike)
    if vwap_implied <= 0:
        return "close"  # deep-OTM ill-conditioning — engine fell back to close
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

    # Pre-P1.7 had a separate IlliquidLegError gate here for
    # volume=0 / oi=0 cases. Under the unified P1.7 spec (operator
    # 2026-06-03) that taxonomy is collapsed into
    # MissingTurnoverError, raised one level up in _pick_fill_price
    # the moment volume=0 is seen. The oi=0 path is dropped entirely
    # — under VWAP-or-skip a contract with volume>0 has by
    # definition cleared trades, so the "no live OI to transact
    # against" concern was always at odds with the published volume.
    # See errors.py::IlliquidLegError for the back-compat note about
    # historical sweep parquets that still carry "IlliquidLegError"
    # as a skip_reason string.

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
