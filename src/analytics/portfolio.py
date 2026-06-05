"""Portfolio aggregator — cycle P&L, equity curve, drawdown series.

PORTFOLIO_MEMOIR.md §21.3 rows C13/C14/C15 + §21.4 formulas F12,
F13, F14. Pure functions over the per-trade frame (the sweep
parquet, optionally pre-filtered by Phase 9.2 candidate-selection
filters). The portfolio aggregator is the bridge between the
per-trade research surface (sweep + filters) and the portfolio-
level metrics surface (Calmar / Ulcer / Sortino / Max DD ₹ in
Phase 9.3.2 + the 2-D regime×IVP diagnostic in Phase 9.3.3).

Sizing convention (memoir §7 + §21.4 F13):

  **Equal-margin, no-reinvest** — each cycle deploys the same
  capital regardless of accumulated P&L. The P&L stream is
  therefore ARITHMETIC, not geometric:

      equity_t = starting_capital + sum_{i=1..t}(cycle_pnl_i)

  This is the v1 assumption per memoir §1 decision row 7. If the
  operator later wants compounded sizing (position size ∝ current
  equity), this module's equity_curve switches to a geometric
  product and §21.4 F15 (Calmar) reverts from simple to CAGR.
  Until then, additive + simple is the consistent pair — DON'T
  mix additive equity with geometric CAGR.

Public API:

  ``cycle_pnl_series(trades_df, *, expiry_col, pnl_col) -> pd.Series``
      F12 — per-cycle net P&L indexed by expiry date. Sums the
      `pnl_col` column across all rows sharing an `expiry_col`
      value. Caller's responsibility to pre-filter to ONE row
      per (symbol, expiry) — the aggregator doesn't dedup.

  ``equity_curve(cycle_pnl_series, starting_capital) -> pd.Series``
      F13 — additive cumulative equity per cycle. ``iloc[0]`` is
      ``starting_capital + first_cycle_pnl`` (NOT the t=0 starting
      capital; see memoir-deviation note below). Returns a same-
      length series indexed by the input's expiry index.

  ``drawdown_series(equity_curve) -> pd.Series``
      F14 — equity minus its running max (in rupees, ≤ 0 always).
      0 at every new-high cycle, increasingly negative when the
      book is underwater.

  ``drawdown_pct_series(equity_curve) -> pd.Series``
      Companion to F14: drawdown as a fraction of the running
      max (the form §21.4 F16 Ulcer Index consumes). Same ≤ 0
      sign convention. Returns 0 where running_max is 0
      (defensive — prevents inf when equity hasn't been
      positive yet).

Option-a prepend (REVISED 2026-06-06 — closes reviewer 70dc408 grill):

  ``equity_curve`` PREPENDS ``starting_capital`` as a synthetic t=0
  point so ``iloc[0] == starting_capital``. The 9.3.1 initial
  commit (76549ab) shipped option (b) (no prepend, length = N
  cycles); reviewer flagged this empirically — a NEGATIVE first
  cycle hides ₹{first_cycle_loss}k from the drawdown because
  ``cummax`` starts at ``starting + first_cycle_pnl`` (below the
  true peak). The 3-cycle case the reviewer exhibited:

      Cycles: -₹25k, +₹5k, +₹10k on ₹100k starting.
      Option b: equity = [75k, 80k, 90k]; cummax = [75k, 80k, 90k];
                DD = [0, 0, 0]; max DD = 0  ← WRONG.
      Option a: equity = [100k, 75k, 80k, 90k]; cummax = [100k]×4;
                DD = [0, -25k, -20k, -10k]; max DD = ₹25k  ← RIGHT.

  Matches the memoir literal: §21.4 F15 uses ``iloc[0]`` as the
  return-denominator (== starting_capital under the prepend) and
  ``len(equity_curve) - 1`` as the cycle count.

  Synthetic prepended index value: ``cycle_pnl_series.index[0] −
  1 day`` for a DatetimeIndex; integer-index falls back to
  ``index[0] − 1``. Callers who want a specific t=0 date pass
  ``start_date=``."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


# Canonical column names in the sweep parquet (SPECS §6c.3 +
# `src.engine.results` writer). Pinned here so a future refactor
# of the sweep schema touches one constant, not every analytics
# module.
DEFAULT_EXPIRY_COL = "expiry"
DEFAULT_PNL_COL = "net_pnl"


# ============================================================
# F12 — cycle P&L per expiry
# ============================================================

def cycle_pnl_series(
    trades_df: pd.DataFrame,
    *,
    expiry_col: str = DEFAULT_EXPIRY_COL,
    pnl_col: str = DEFAULT_PNL_COL,
) -> pd.Series:
    """Sum ``pnl_col`` per ``expiry_col`` and return a Series
    indexed by expiry (ascending).

    F12 per PORTFOLIO_MEMOIR.md §21.4. Each expiry is one cycle
    in the v1 portfolio backtest (memoir §5 fixes a single monthly
    cycle); within a cycle, the 5 selected names each contribute
    one trade row, and this function sums them.

    Args:
        trades_df: per-trade frame, typically the sweep parquet
            pre-filtered by candidate selection (Phase 9.2
            filters). Caller is responsible for ensuring AT MOST
            one row per (symbol, expiry) — the function does NOT
            dedup, so duplicate rows would double-count.
        expiry_col: cycle-key column name. Defaults to
            ``"expiry"`` (canonical sweep schema).
        pnl_col: P&L column to sum. Defaults to ``"net_pnl"``
            (post-cost). Override to ``"gross_pnl"`` for cost-
            attribution diagnostics.

    Returns:
        ``pd.Series`` of cycle P&L (float64) indexed by expiry,
        sorted ascending. Empty frame → empty series with a
        ``datetime64[us]`` index for downstream type stability.

    Edge cases:
        - Empty frame returns an empty Series.
        - A single row → single-element Series.
        - Multiple rows with the same expiry are summed (this is
          the normal portfolio-cycle case).
    """
    if trades_df is None:
        return pd.Series(
            [], index=pd.DatetimeIndex([], name=expiry_col), dtype="float64",
        )
    if not isinstance(trades_df, pd.DataFrame):
        raise TypeError(
            f"trades_df must be pd.DataFrame, got {type(trades_df).__name__}"
        )
    required = {expiry_col, pnl_col}
    missing = required - set(trades_df.columns)
    if missing:
        raise ValueError(
            f"trades_df missing required columns: {sorted(missing)}; "
            f"got {list(trades_df.columns)}"
        )
    if trades_df.empty:
        return pd.Series(
            [], index=pd.DatetimeIndex([], name=expiry_col), dtype="float64",
        )
    grouped = trades_df.groupby(expiry_col, sort=True)[pnl_col].sum()
    grouped.name = "cycle_pnl"
    return grouped.astype("float64")


# ============================================================
# F13 — additive equity curve
# ============================================================

def equity_curve(
    cycle_pnl_series: pd.Series,
    starting_capital: float,
    *,
    start_date: date | pd.Timestamp | None = None,
) -> pd.Series:
    """Cumulative additive equity, PREPENDED with starting_capital.

    F13 (REVISED 2026-06-04, FIXED 2026-06-06 reviewer 70dc408):

        equity_0   = starting_capital            ← prepended t=0
        equity_t   = starting_capital + cumsum_{i=1..t}(cycle_pnl_i)
                     for t in 1..N

    Length = N + 1 (one starting-capital row at t=0, then one row
    per cycle). The prepend is LOAD-BEARING for ``drawdown_series``:
    without it, a NEGATIVE first cycle hides the true peak from
    ``cummax`` (cummax starts at ``starting + first_cycle_pnl``
    instead of the true ``starting_capital`` peak), under-counting
    max DD. See module docstring for the empirical 3-cycle case.

    Args:
        cycle_pnl_series: F12 output (or compatible).
        starting_capital: book capital before any cycle runs.
            Must be > 0.
        start_date: index value for the prepended t=0 row.
            Defaults to ``cycle_pnl_series.index[0] - 1 day``
            for a DatetimeIndex; ``index[0] - 1`` for integer
            index. Callers who want a specific date pass it
            explicitly.

    Returns:
        Series of length N+1, dtype float64, name ``"equity"``.
        Empty cycle_pnl_series → empty Series (no prepend; the
        "no cycles" case has no equity history to render).
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
    if cycle_pnl_series.empty:
        return pd.Series(
            [], index=cycle_pnl_series.index, dtype="float64",
            name="equity",
        )
    cycle_equity = (
        starting_capital + cycle_pnl_series.astype("float64").cumsum()
    )
    # Synthetic t=0 index value.
    if start_date is not None:
        prepend_idx = pd.Timestamp(start_date)
    elif isinstance(cycle_pnl_series.index, pd.DatetimeIndex):
        prepend_idx = cycle_pnl_series.index[0] - pd.Timedelta(days=1)
    else:
        first = cycle_pnl_series.index[0]
        try:
            prepend_idx = first - 1
        except TypeError:
            # Hard-coded fallback for exotic indexes — keep going,
            # but the index is meaningless if the caller hand-built
            # an unusual one.
            prepend_idx = first
    prepend = pd.Series([float(starting_capital)], index=[prepend_idx])
    out = pd.concat([prepend, cycle_equity])
    out.name = "equity"
    return out


# ============================================================
# F14 — drawdown series (₹ and %)
# ============================================================

def drawdown_series(equity_curve: pd.Series) -> pd.Series:
    """Underwater drawdown in rupees: ``equity - cummax(equity)``.

    F14 per PORTFOLIO_MEMOIR.md §21.4. Always ≤ 0; equals 0 at
    every new-high cycle. The MOST NEGATIVE value is the peak-
    to-trough max drawdown ₹ (F18); ``abs(dd.min())`` gives the
    rupee magnitude.

    Args:
        equity_curve: F13 output (or compatible). Empty → empty.

    Returns:
        Same-length Series, same index as input, dtype float64.
        Name: ``"drawdown_inr"``.
    """
    if not isinstance(equity_curve, pd.Series):
        raise TypeError(
            f"equity_curve must be pd.Series, got "
            f"{type(equity_curve).__name__}"
        )
    if equity_curve.empty:
        return pd.Series(
            [], index=equity_curve.index, dtype="float64",
            name="drawdown_inr",
        )
    running_max = equity_curve.cummax()
    out = (equity_curve - running_max).astype("float64")
    out.name = "drawdown_inr"
    return out


def drawdown_pct_series(equity_curve: pd.Series) -> pd.Series:
    """Drawdown as a fraction of the running maximum.

    Companion to ``drawdown_series`` — the form §21.4 F16 Ulcer
    Index consumes. Same ≤ 0 sign convention (NOT the absolute
    %; this is signed for downstream RMS math).

    Returns 0 where ``running_max == 0`` so a zero-equity prefix
    (e.g., starting_capital was 0 — defensive, the equity_curve
    above already rejects this) doesn't produce inf.

    Args:
        equity_curve: F13 output (or compatible).

    Returns:
        Same-length Series, same index as input, dtype float64.
        Name: ``"drawdown_pct"``. Values in [-1, 0].
    """
    if not isinstance(equity_curve, pd.Series):
        raise TypeError(
            f"equity_curve must be pd.Series, got "
            f"{type(equity_curve).__name__}"
        )
    if equity_curve.empty:
        return pd.Series(
            [], index=equity_curve.index, dtype="float64",
            name="drawdown_pct",
        )
    running_max = equity_curve.cummax()
    dd = (equity_curve - running_max).astype("float64")
    # Defensive zero guard: divide where running_max != 0, else 0.
    # np.where preserves the float64 dtype and the index alignment.
    pct = np.where(
        running_max != 0,
        dd / running_max.replace(0, np.nan),
        0.0,
    )
    out = pd.Series(pct, index=equity_curve.index, dtype="float64")
    out.name = "drawdown_pct"
    return out
