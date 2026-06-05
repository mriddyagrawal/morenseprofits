"""F19 — Regime × IVP-decile 2-D diagnostic table.

PORTFOLIO_MEMOIR.md §21.3 row C20 + §21.4 F19 + §18.4 + §18.5. The
canonical empirical test of whether the IVP edge survives AFTER
the regime gate — answers the operator's "does IVP add signal
beyond regime?" question without writing per-cell statistical
tests by hand.

The diagnostic answers:

  For each (regime_state, IVP_decile) cell, what was the realized
  P&L distribution? Specifically:
    - count: how many trades fell in this cell
    - mean: average P&L per trade
    - median: middle P&L per trade (robust to outlier cycles)
    - cvar_5: average of the WORST 5% of trades in the cell
              (the tail-risk view — same metric the MCP
              ``compare_cells`` + ``cell_summary`` tools expose)

A naive read of mean-only can hide a left-skewed distribution
where the cell PASSED on average but blew up catastrophically
in the 5% tail. Per memoir §18.4 + §18.5, judge each cell on
BOTH median (stable signal) AND CVaR-5% (tail risk) — the table
surfaces both columns so the operator can scan them together.

LOOK-AHEAD CAVEAT (memoir §21.4 F19, 2026-06-04):

  ``pd.qcut`` computes decile boundaries from the FULL retrospective
  sample. That's correct for THIS diagnostic — we WANT to see how
  trades grouped by their TRUE IVP percentile performed in
  retrospect. But the resulting boundaries MUST NOT be used for
  LIVE trade selection: live filtering needs trailing-only
  quantile boundaries (e.g., trailing-252-TD cross-sectional IVP
  values per memoir §21.4 F5). Using full-sample boundaries live =
  peeking at future periods = backtest fraud.

  The diagnostic and the live filter are two different operations.
  This module implements the diagnostic only; the live filter is
  the Phase 9.4 cycle-selection wire-in.

Thin-bucket fallback (memoir §F19 caveat):

  If any decile bucket has < ``thin_bucket_threshold`` trades
  (default 50), automatically fall back to QUINTILES (n=5). The
  table's metadata reports both the bucket count used and
  whether the fallback fired so the UI can surface a
  "switched-to-quintiles" caveat.

Public API:

  ``regime_x_ivp_breakdown(trades_df, regime_signal_series,
                             ivp_series_per_symbol, *,
                             n_buckets=10, regime_threshold_pct=75.0,
                             regime_lookback_td=252,
                             thin_bucket_threshold=50,
                             entry_date_col, symbol_col, pnl_col)
                             -> RegimeIvpBreakdown``

      Returns the breakdown + metadata for the regime-gated 2-D
      diagnostic.

  ``RegimeIvpBreakdown`` dataclass:
      .table                   : pd.DataFrame multi-indexed by
                                  (regime_state, ivp_bucket)
      .n_trades_used           : int  — trades that landed in a
                                          bucket
      .n_trades_dropped        : int  — trades dropped (NaN IVP /
                                          NaN regime / pre-series
                                          entry_date)
      .n_buckets               : int  — 10 (deciles) or 5
                                          (quintile fallback)
      .fallback_to_quintiles   : bool — True when fallback fired
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from src.analytics.regime import regime_state


# Memoir §F19 thresholds.
DEFAULT_N_BUCKETS = 10                # deciles
DEFAULT_QUINTILE_FALLBACK = 5
DEFAULT_THIN_BUCKET_THRESHOLD = 50    # min trades per bucket
DEFAULT_CVAR_FRACTION = 0.05          # worst 5% tail

# Same defaults as analytics.regime (so the diagnostic and the
# live gate report on the same regime semantics).
DEFAULT_REGIME_THRESHOLD_PCT = 75.0
DEFAULT_REGIME_LOOKBACK_TD = 252

# Sweep parquet column conventions (matches analytics.portfolio).
DEFAULT_ENTRY_DATE_COL = "entry_date"
DEFAULT_SYMBOL_COL = "symbol"
DEFAULT_PNL_COL = "net_pnl"


@dataclass(frozen=True)
class RegimeIvpBreakdown:
    """Result of F19 diagnostic — table + metadata.

    The metadata fields let the UI render an honest caveat:
    "X trades dropped (insufficient IVP history); ran at quintiles
    after deciles produced bucket(s) with < 50 trades."
    """
    table: pd.DataFrame
    n_trades_used: int
    n_trades_dropped: int
    n_buckets: int
    fallback_to_quintiles: bool

    @property
    def n_trades_total(self) -> int:
        return self.n_trades_used + self.n_trades_dropped

    def caveat_text(self) -> str:
        """One-line caveat for the diagnostic banner.
        Empty string when nothing's worth surfacing."""
        parts: list[str] = []
        if self.fallback_to_quintiles:
            parts.append(
                f"quintile fallback (deciles produced bucket(s) "
                f"< {DEFAULT_THIN_BUCKET_THRESHOLD} trades)"
            )
        if self.n_trades_dropped > 0:
            parts.append(
                f"{self.n_trades_dropped} of {self.n_trades_total} "
                f"trades dropped (insufficient IVP / regime history)"
            )
        return "; ".join(parts)


def _cvar_5(series: pd.Series, *, fraction: float = DEFAULT_CVAR_FRACTION) -> float:
    """Mean of the worst ``fraction`` of values (CVaR-5% by
    default). Same shape as the MCP layer's CVaR helper — kept
    inline here to avoid an upstream import. NaN on empty input."""
    if series.empty:
        return float("nan")
    n_tail = max(1, int(len(series) * fraction))
    return float(series.nsmallest(n_tail).mean())


def _ivp_at_entry(
    ivp_series_per_symbol: Mapping[str, pd.Series],
    symbol: str,
    entry_date: pd.Timestamp,
) -> float:
    """Look up the IVP for ``symbol`` at ``entry_date``.

    Uses ``Series.asof`` so a non-trading-day entry rounds DOWN
    to the most recent trading day. NaN if symbol is unknown,
    series is empty, or entry_date predates the symbol's IVP
    history.
    """
    s = ivp_series_per_symbol.get(symbol)
    if s is None or s.empty:
        return float("nan")
    try:
        v = s.asof(entry_date)
    except (TypeError, KeyError):
        return float("nan")
    return float(v) if pd.notna(v) else float("nan")


def _bucket_with_thin_fallback(
    values: pd.Series,
    *,
    n_buckets: int,
    thin_threshold: int,
    fallback_n: int,
) -> tuple[pd.Series, int, bool]:
    """Run ``pd.qcut`` at ``n_buckets``; if any bucket has fewer
    than ``thin_threshold`` rows, re-run at ``fallback_n``.

    Returns (bucket_labels, n_buckets_used, fallback_fired).
    """
    # qcut can fail on degenerate distributions (e.g., all values
    # equal); duplicates='drop' lets it produce fewer buckets
    # silently. If the resulting bin count is < 2 we can't
    # meaningfully bucket — return NaN labels.
    try:
        labels = pd.qcut(
            values, q=n_buckets, labels=False, duplicates="drop",
        )
    except ValueError:
        return (
            pd.Series([np.nan] * len(values), index=values.index),
            0, False,
        )
    counts = labels.value_counts(dropna=True)
    if counts.empty or counts.min() >= thin_threshold:
        return labels, int(counts.size), False
    # Fall back to quintiles.
    try:
        labels_q = pd.qcut(
            values, q=fallback_n, labels=False, duplicates="drop",
        )
    except ValueError:
        return labels, int(counts.size), False
    return labels_q, int(labels_q.value_counts(dropna=True).size), True


def regime_x_ivp_breakdown(
    trades_df: pd.DataFrame,
    regime_signal_series: pd.Series,
    ivp_series_per_symbol: Mapping[str, pd.Series],
    *,
    n_buckets: int = DEFAULT_N_BUCKETS,
    regime_threshold_pct: float = DEFAULT_REGIME_THRESHOLD_PCT,
    regime_lookback_td: int = DEFAULT_REGIME_LOOKBACK_TD,
    thin_bucket_threshold: int = DEFAULT_THIN_BUCKET_THRESHOLD,
    cvar_fraction: float = DEFAULT_CVAR_FRACTION,
    entry_date_col: str = DEFAULT_ENTRY_DATE_COL,
    symbol_col: str = DEFAULT_SYMBOL_COL,
    pnl_col: str = DEFAULT_PNL_COL,
) -> RegimeIvpBreakdown:
    """F19 — 2-D diagnostic: per-trade P&L stats by
    (regime_state, IVP_decile).

    For each row in ``trades_df``:
      1. Look up regime_state at entry_date using
         ``analytics.regime.regime_state``.
      2. Look up the symbol's IVP at entry_date via
         ``ivp_series_per_symbol[symbol].asof(entry_date)``.
      3. Bucket the IVP value into deciles (with quintile fallback
         per the §F19 thin-bucket caveat).
      4. Group by (regime_state, ivp_bucket); aggregate
         count / mean / median / CVaR-5%.

    Args:
        trades_df: per-trade frame with ``entry_date``, ``symbol``,
            ``net_pnl`` columns.
        regime_signal_series: the universe-wide regime signal
            series (e.g., avg_single_name_rv or India VIX),
            ascending DatetimeIndex.
        ivp_series_per_symbol: ``{symbol: pd.Series}`` where each
            series is the symbol's IVP history (e.g., from
            ``analytics.ivp.time_series_ivp`` applied over time).
            Symbols absent from the dict produce NaN IVP →
            dropped.
        n_buckets: target deciles (10) per memoir §F19. Auto
            falls back to quintiles (5) if any bucket has fewer
            than ``thin_bucket_threshold`` trades.
        regime_threshold_pct / regime_lookback_td: forwarded to
            ``analytics.regime.regime_state``.
        thin_bucket_threshold: min trades per bucket before
            quintile fallback fires (memoir §F19: ~50).
        cvar_fraction: tail fraction for CVaR-5% (default 0.05).
        entry_date_col / symbol_col / pnl_col: sweep schema
            overrides.

    Returns:
        ``RegimeIvpBreakdown`` with the table + diagnostic
        metadata.

    NaN handling: trades with NaN IVP at entry, NaN regime state,
    or entry_date before the regime/IVP series start are EXCLUDED
    from bucketing (counted in ``n_trades_dropped``). The UI is
    expected to surface this count.
    """
    if not isinstance(trades_df, pd.DataFrame):
        raise TypeError(
            f"trades_df must be pd.DataFrame, got "
            f"{type(trades_df).__name__}"
        )
    required = {entry_date_col, symbol_col, pnl_col}
    missing = required - set(trades_df.columns)
    if missing:
        raise ValueError(
            f"trades_df missing required columns: {sorted(missing)}; "
            f"got {list(trades_df.columns)}"
        )
    if not isinstance(regime_signal_series, pd.Series):
        raise TypeError(
            "regime_signal_series must be pd.Series"
        )

    n_total = len(trades_df)
    if n_total == 0:
        return RegimeIvpBreakdown(
            table=_empty_table(),
            n_trades_used=0, n_trades_dropped=0,
            n_buckets=0, fallback_to_quintiles=False,
        )

    # Build (regime, ivp) labels per row.
    entry_dates = pd.to_datetime(trades_df[entry_date_col])
    symbols = trades_df[symbol_col].astype(str).str.upper()
    pnls = trades_df[pnl_col].astype("float64")

    # Per-row regime lookup. Memoize: many rows share the same
    # entry_date so cache by unique date for speed.
    unique_dates = entry_dates.unique()
    regime_cache: dict[pd.Timestamp, str | None] = {}
    for d in unique_dates:
        state = regime_state(
            regime_signal_series,
            pd.Timestamp(d).date() if hasattr(d, "date") else d,
            threshold_pct=regime_threshold_pct,
            lookback_td=regime_lookback_td,
        )
        regime_cache[pd.Timestamp(d)] = state
    regime_labels = entry_dates.map(
        lambda d: regime_cache.get(pd.Timestamp(d))
    )

    # Per-row IVP lookup. No memoization opportunity here (each
    # (symbol, date) is potentially distinct).
    ivp_values = pd.Series(
        [
            _ivp_at_entry(ivp_series_per_symbol, sym, pd.Timestamp(d))
            for sym, d in zip(symbols, entry_dates)
        ],
        index=trades_df.index, dtype="float64",
    )

    # Drop NaN-bearing rows from bucketing. Keep regime label "OFF"
    # — that's a valid state per memoir F9 (NaN-regime → OFF guard).
    valid_mask = ivp_values.notna() & regime_labels.notna()
    n_dropped = int((~valid_mask).sum())
    if not valid_mask.any():
        return RegimeIvpBreakdown(
            table=_empty_table(),
            n_trades_used=0, n_trades_dropped=n_dropped,
            n_buckets=0, fallback_to_quintiles=False,
        )

    ivp_valid = ivp_values[valid_mask]
    regime_valid = regime_labels[valid_mask]
    pnls_valid = pnls[valid_mask]

    # Bucket IVP with thin-bucket fallback.
    ivp_bucket, n_buckets_used, fallback_fired = _bucket_with_thin_fallback(
        ivp_valid,
        n_buckets=n_buckets,
        thin_threshold=thin_bucket_threshold,
        fallback_n=DEFAULT_QUINTILE_FALLBACK,
    )

    # Aggregate.
    grouped_df = pd.DataFrame({
        "regime_state": regime_valid.values,
        "ivp_bucket": ivp_bucket.values,
        "net_pnl": pnls_valid.values,
    })
    grouped_df = grouped_df.dropna(subset=["ivp_bucket"])
    # Cast bucket to int after dropna (qcut returns float-with-NaN).
    grouped_df["ivp_bucket"] = grouped_df["ivp_bucket"].astype(int)

    if grouped_df.empty:
        return RegimeIvpBreakdown(
            table=_empty_table(),
            n_trades_used=0, n_trades_dropped=n_dropped + int(valid_mask.sum()),
            n_buckets=n_buckets_used,
            fallback_to_quintiles=fallback_fired,
        )

    n_used = len(grouped_df)
    table = grouped_df.groupby(
        ["regime_state", "ivp_bucket"], sort=True,
    )["net_pnl"].agg([
        ("count", "size"),
        ("mean", "mean"),
        ("median", "median"),
        ("cvar_5", lambda x: _cvar_5(x, fraction=cvar_fraction)),
    ])

    return RegimeIvpBreakdown(
        table=table,
        n_trades_used=n_used,
        n_trades_dropped=n_dropped + (len(ivp_valid) - n_used),
        n_buckets=n_buckets_used,
        fallback_to_quintiles=fallback_fired,
    )


def _empty_table() -> pd.DataFrame:
    """Schema-shaped empty result table for zero-bucket cases."""
    return pd.DataFrame(
        {
            "count": pd.Series(dtype="int64"),
            "mean": pd.Series(dtype="float64"),
            "median": pd.Series(dtype="float64"),
            "cvar_5": pd.Series(dtype="float64"),
        },
        index=pd.MultiIndex.from_tuples(
            [], names=["regime_state", "ivp_bucket"],
        ),
    )
