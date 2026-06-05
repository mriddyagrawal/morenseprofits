"""Portfolio-level scalar metrics — Calmar, Ulcer, Sortino, Max DD ₹.

PORTFOLIO_MEMOIR.md §21.3 rows C16/C17/C18/C19 + §21.4 formulas
F15, F16, F17, F18 (with the 2026-06-04 revisions: F15 simple
annualization vs CAGR; F17 standard Sortino/Satchell TDD).

Consumes the ``equity_curve`` / ``drawdown_series`` /
``cycle_pnl_series`` outputs from ``src.analytics.portfolio``
(9.3.1). All four metrics are pure functions; no I/O.

The four are the Portfolio tab "headline strip" cards (per memoir
§4.1 + mockup). Combined with the year-by-year table (Phase 9.4
follow-up) they answer "is this portfolio worth running?":

  - **Calmar** — return per unit of max drawdown. Higher is
    better. Penalizes peak-to-trough pain. The premium-selling
    canonical headline metric.
  - **Ulcer Index** — RMS of underwater drawdown %. Lower is
    better. Penalizes BOTH depth and duration; a portfolio that
    sits 5% underwater for a year scores worse than one that
    dips 10% and recovers in a month.
  - **Sortino** — return per unit of DOWNSIDE std. Higher is
    better. Doesn't penalize upside vol the way Sharpe does;
    natural fit for short-vol P&L which has a left-skewed return
    distribution.
  - **Max DD ₹** — peak-to-trough rupee loss. Operator-facing
    "what's the worst it got" number; pairs with Calmar (which
    reports the same as a percentage).

Sizing-convention coupling (memoir §7 + §1 decision row 7 +
§21.4 F13 REVISED):

  Equal-margin, no-reinvest → SIMPLE annualization. Don't mix
  additive equity with geometric CAGR. The original F15 sketch
  used CAGR, which compounded on a non-compounding book and
  OVERSTATED the return — fixed in the 2026-06-04 memoir
  revision; this module implements the fixed (simple)
  formula.

  If the operator later switches to compounded sizing, F13's
  ``equity_curve`` switches to geometric and F15 reverts to CAGR.
  Until then, additive + simple is the consistent pair.

Public API:

  ``cycle_returns(cycle_pnl_series, starting_capital) -> pd.Series``
      Per-cycle simple return: ``cycle_pnl / starting_capital``.
      Under equal-margin no-reinvest sizing, every cycle's
      denominator is the same starting capital. Feeds Sortino.

  ``simple_annualized_return(equity_curve, *,
                              periods_per_year=12) -> float``
      F15 (REVISED) — simple per-year return, NOT CAGR. Uses
      ``equity_curve.iloc[0]`` as the starting-capital denominator
      (== starting capital under the 2026-06-06 prepend fix in
      ``analytics.portfolio.equity_curve``).

  ``calmar(equity_curve, *, periods_per_year=12) -> float``
      F15 (REVISED) — simple annualized return / max DD %.
      Returns inf when max DD == 0 (monotone-up book); negative
      when the book lost money.

  ``ulcer_index(equity_curve) -> float``
      F16 — RMS of underwater drawdown % (in % units, NOT
      fraction, per memoir). 0 → no drawdown ever.

  ``sortino(returns_series, *, target=0.0, periods_per_year=12)
             -> float``
      F17 (REVISED) — Sortino/Satchell standard target-downside-
      deviation. Denominator divides by N_TOTAL (NOT N_downside);
      squared term is (downside - target)², not downside² alone.

  ``max_drawdown_inr(equity_curve) -> float``
      F18 — abs(drawdown_series.min()). Reported as a positive
      rupee amount.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.analytics.portfolio import (
    drawdown_pct_series,
    drawdown_series,
)


# Monthly portfolio cycles per memoir §5 (single fixed (entry,
# exit) window per cycle). If a future strategy ships with weekly
# or quarterly cycles, callers override ``periods_per_year``.
DEFAULT_PERIODS_PER_YEAR = 12

# Memoir F16 multiplies dd_fraction by 100 before squaring so the
# Ulcer Index is in % units (e.g., a 10%-DD steady-state book
# scores ~10, not 0.10). Pinned here for downstream consumer clarity.
ULCER_PCT_SCALE = 100.0


# ============================================================
# cycle_returns — feeder for Sortino
# ============================================================

def cycle_returns(
    cycle_pnl_series: pd.Series,
    starting_capital: float,
) -> pd.Series:
    """Per-cycle simple return: ``cycle_pnl / starting_capital``.

    Under the equal-margin no-reinvest convention (memoir §7),
    every cycle's denominator is the same starting capital — so
    the simple "return per cycle" is just the cycle P&L divided
    by the fixed denominator. This is the input the Sortino
    calculation expects (cycle returns, not cumulative equity).

    Args:
        cycle_pnl_series: F12 output from
            ``analytics.portfolio.cycle_pnl_series``.
        starting_capital: the same fixed capital used in F13's
            ``equity_curve(..., starting_capital)`` call (must
            match for the equity ↔ returns relationship to hold).

    Returns:
        Same-length Series indexed by expiry. dtype float64.
        Empty input → empty Series.
    """
    if not isinstance(cycle_pnl_series, pd.Series):
        raise TypeError(
            f"cycle_pnl_series must be pd.Series, got "
            f"{type(cycle_pnl_series).__name__}"
        )
    if starting_capital <= 0:
        raise ValueError(
            f"starting_capital must be > 0, got {starting_capital}"
        )
    out = (cycle_pnl_series.astype("float64") / float(starting_capital))
    out.name = "cycle_return"
    return out


# ============================================================
# F15 — simple annualized return + Calmar
# ============================================================

def simple_annualized_return(
    equity_curve: pd.Series,
    *,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> float:
    """Simple annualized return from the additive equity curve.

    F15 (REVISED 2026-06-04). NOT CAGR — geometric CAGR on an
    additive non-compounding book overstates the headline. The
    formula matches the memoir literal:

        n_cycles      = len(equity_curve) − 1
        total_return  = (equity[-1] − equity[0]) / equity[0]
        annual_return = total_return × (periods_per_year / n_cycles)

    Post-2026-06-06 prepend fix: ``equity[0]`` is the synthetic t=0
    starting-capital row, so the (final − initial) / initial form
    matches the actual book return. Pre-fix Option-b version
    required a separate ``starting_capital`` parameter; that's no
    longer needed.

    Args:
        equity_curve: F13 output (length N+1 = 1 starting row + N
            cycle rows).
        periods_per_year: 12 for monthly cycles (default). 52 for
            weekly, 4 for quarterly, etc.

    Returns:
        Annualized return as a fraction (e.g. 0.15 = 15%/yr).
        ``np.nan`` on empty equity_curve OR length-1 (only the
        t=0 row, no cycles → no return to annualize).
    """
    if not isinstance(equity_curve, pd.Series):
        raise TypeError(
            f"equity_curve must be pd.Series, got "
            f"{type(equity_curve).__name__}"
        )
    if periods_per_year <= 0:
        raise ValueError(
            f"periods_per_year must be > 0, got {periods_per_year}"
        )
    if len(equity_curve) < 2:
        return float("nan")
    n_cycles = len(equity_curve) - 1
    initial = float(equity_curve.iloc[0])
    if initial <= 0:
        # Defensive — equity_curve from analytics.portfolio always
        # has iloc[0] == starting_capital > 0, but a hand-built
        # series could pass an invalid starting row.
        return float("nan")
    total_return = (float(equity_curve.iloc[-1]) - initial) / initial
    return total_return * (periods_per_year / n_cycles)


def calmar(
    equity_curve: pd.Series,
    *,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> float:
    """Calmar = simple annualized return / max drawdown %.

    F15 (REVISED 2026-06-04 + prepend fix 2026-06-06). The
    premium-selling canonical headline metric — higher is better;
    penalizes peak-to-trough pain.

    Returns:
        Calmar ratio. ``inf`` when max DD == 0 (monotone-up book).
        Negative when the book lost money. ``np.nan`` on empty or
        length-1 equity_curve (no cycles, no metric).

    Sign convention: max DD % is the absolute (positive) value;
    annualized return carries the loss sign.
    """
    annual_return = simple_annualized_return(
        equity_curve, periods_per_year=periods_per_year,
    )
    if pd.isna(annual_return):
        return float("nan")
    dd_pct = drawdown_pct_series(equity_curve)
    if dd_pct.empty:
        return float("nan")
    max_dd_abs = float(abs(dd_pct.min()))
    if max_dd_abs == 0.0:
        return float("inf")
    return annual_return / max_dd_abs


# ============================================================
# F16 — Ulcer Index
# ============================================================

def ulcer_index(equity_curve: pd.Series) -> float:
    """RMS of underwater drawdown %.

    F16 per PORTFOLIO_MEMOIR.md §21.4. Penalizes BOTH depth and
    duration; sitting 5% underwater for a year scores worse than
    a brief 10% dip + quick recovery.

    Returns:
        Ulcer Index in % units (e.g. 8.2 = ~8.2% steady-state
        DD-equivalent). 0 on monotone-up equity. ``np.nan`` on
        empty input.

    Memoir convention: the input ``dd_fraction`` is scaled by
    ``ULCER_PCT_SCALE = 100`` before squaring so the output is in
    natural % units — matches the standard literature (e.g.,
    Martin's original presentation).
    """
    if not isinstance(equity_curve, pd.Series):
        raise TypeError(
            f"equity_curve must be pd.Series, got "
            f"{type(equity_curve).__name__}"
        )
    if equity_curve.empty:
        return float("nan")
    dd_fraction = drawdown_pct_series(equity_curve)
    dd_pct = dd_fraction * ULCER_PCT_SCALE
    return float(np.sqrt(np.mean(dd_pct ** 2)))


# ============================================================
# F17 — Sortino (standard Sortino/Satchell TDD)
# ============================================================

def sortino(
    returns_series: pd.Series,
    *,
    target: float = 0.0,
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> float:
    """Annualized Sortino ratio with target-downside-deviation.

    F17 (REVISED 2026-06-04) per PORTFOLIO_MEMOIR.md §21.4:

        TDD = sqrt( mean_over_ALL_N( min(0, r - target)² ) × periods )
        annualized_excess = (mean(r) - target) × periods
        Sortino = annualized_excess / TDD

    LOAD-BEARING fix from the 2026-06-04 revision:

      1. **Denominator is N_total, NOT N_downside.** Dividing by
         downside-only N understates DD-deviation and OVERSTATES
         Sortino. Standard Sortino/Satchell uses total N.

      2. **Squared term is (downside - target)², not downside².**
         Harmless at default target=0 but wrong if anyone passes
         a non-zero target (e.g., risk-free rate).

    Args:
        returns_series: per-cycle simple returns (e.g., the
            output of ``cycle_returns(cycle_pnl, starting_capital)``).
        target: minimum acceptable return per cycle. Defaults to
            0.0 (the "any positive cycle is acceptable" convention).
            Pass a per-cycle risk-free rate for the canonical form.
        periods_per_year: 12 for monthly cycles. Same convention
            as F15.

    Returns:
        Annualized Sortino. ``inf`` when downside std == 0 (no
        cycles ever below target). ``np.nan`` on empty input.
    """
    if not isinstance(returns_series, pd.Series):
        raise TypeError(
            f"returns_series must be pd.Series, got "
            f"{type(returns_series).__name__}"
        )
    if periods_per_year <= 0:
        raise ValueError(
            f"periods_per_year must be > 0, got {periods_per_year}"
        )
    if returns_series.empty:
        return float("nan")

    excess_return_annualized = (
        float(returns_series.mean()) - target
    ) * periods_per_year
    # (r - target).clip(upper=0) → only the BELOW-target part;
    # at-or-above-target rows contribute 0 to the squared sum.
    deviations_below_target = (returns_series - target).clip(upper=0)
    # mean() over ALL N (not just downside count) — this is the F17 fix.
    downside_dev_sq = float((deviations_below_target ** 2).mean())
    target_downside_deviation = float(
        np.sqrt(downside_dev_sq * periods_per_year)
    )
    if target_downside_deviation == 0.0:
        return float("inf")
    return excess_return_annualized / target_downside_deviation


# ============================================================
# F18 — Max DD ₹
# ============================================================

def max_drawdown_inr(equity_curve: pd.Series) -> float:
    """Peak-to-trough rupee loss.

    F18 per PORTFOLIO_MEMOIR.md §21.4: ``abs(drawdown_series.min())``.

    Returned as a positive rupee amount. ``0.0`` on monotone-up
    equity or empty input — the convention is "max DD is the
    worst dip; no dips → 0", NOT NaN. Operator-facing scalar; NaN
    would render poorly on a UI card.
    """
    if not isinstance(equity_curve, pd.Series):
        raise TypeError(
            f"equity_curve must be pd.Series, got "
            f"{type(equity_curve).__name__}"
        )
    if equity_curve.empty:
        return 0.0
    dd = drawdown_series(equity_curve)
    return float(abs(dd.min()))
