"""Time-series IVP (Implied Volatility Percentile) + cross-sectional
rank-of-ranks for top-N selection.

PORTFOLIO_MEMOIR.md §2 (methodology) + §21.4 formulas F5 + F6.

The IVP edge: for a single name, "where does today's 30D constant-
maturity ATM IV sit as a percentile of its trailing 252-trading-
day (≈ 1 calendar year) history?" High percentile (e.g. 80+) = vol
is RICH vs the name's own recent history → favorable for selling
premium. Low percentile = vol is CHEAP → unfavorable. The hypothesis
under test (memoir §20 row 1, §20 row 6): does the IVP edge actually
exist on Indian single-name options, and what's the right lookback?
The sensitivity strip on the future Portfolio UI will answer empirically.

The rank-of-ranks (F6): the per-symbol TS-IVP gives "is THIS symbol
in a vol-rich regime relative to its OWN history?". Cross-sectional
rank picks the top N symbols by TS-IVP across the whole eligible
universe on a given day. Combines well with the regime gate (which
runs at the universe level — see §3) and the earnings filter
(§17, §17.5) — the three layers cover the three structural failure
modes (systematic crashes, scheduled events, per-name catalysts).

This module reads the IV history written by
``src.data.iv_materializer.materialize_iv_history`` — specifically
the ``iv_cmi30_excl7`` column (Series C, the operator-locked
methodology default per the 2026-05-31 notebook lock-in, which
empirically dominated Series A/B by avoiding the near-expiry
theta-panic / pin-risk artifacts).

Public API:

  ``time_series_ivp(iv_series, as_of, lookback_td=252) -> float``
      F5 — trailing 252-trading-day percentile rank (0-100). NaN
      on insufficient history / NaN today / pre-series as_of.
      Mirrors ``regime_percentile`` math exactly — both are the
      same load-bearing percentile-rank kernel per §21.4 F9.

  ``compute_ivp(symbol, as_of, *, series, lookback_td=252) -> float``
      Convenience wrapper: loads ``data/cache/iv/{SYMBOL}.parquet``
      via ``iv_materializer.load_iv_history``, slices the requested
      column, runs ``time_series_ivp``. Default ``series`` is
      ``iv_cmi30_excl7`` (Series C, operator-locked default).

  ``top_n_by_ivp(ivp_today_per_symbol, n=5) -> list[str]``
      F6 — descending sort by IVP, drop NaN entries, take top N.
      Ties broken by symbol-name ascending (deterministic).

NaN semantics (load-bearing — closes the spec-drift pattern the
reviewer flagged on 3fb0f05):
  - Today's IV is NaN → IVP is NaN (NOT 0th percentile —
    that's the F5 GRILL bug fix from §21.4: ``(window < NaN).sum()``
    silently returns 0, so a missing day would otherwise render
    as "cheapest vol ever").
  - Window has < 50% non-NaN observations → NaN (insufficient
    history floor; 50% of LOOKBACK_TD, NOT of the realized window).
  - Numerator uses strictly-less-than: ``(valid < today).sum()``.
  - Denominator uses ``len(valid)`` (NaN-dropped), NOT ``len(window)``
    — corrected on 3fb0f05 per reviewer d8620f8 GRILL 3.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import numpy as np
import pandas as pd

from src.data.iv_materializer import load_iv_history


# Trailing-window length per memoir §21.4 F5: 252 trading days ≈
# 1 calendar year of trade dates. Memoir §20 row 6 flags this as
# tunable (could be 63 / 126 / 252); the sensitivity strip will
# empirically pick. 252 is the v1 default.
IVP_LOOKBACK_TD = 252

# Insufficient-history floor: window must have at least 50% of
# LOOKBACK_TD non-NaN observations to compute a rank. Pinned in
# code per reviewer d8620f8 GRILL 1 (the initial 10% cited in
# 3fb0f05 was wrong; 50% is the memoir spec).
IVP_MIN_VALID_FRACTION = 0.5

# Default IV series column to rank on. Operator-locked on 2026-05-31
# per the notebook 3625f3e empirical study: Series C (30D CMI with
# DTE ≥ 7 exclusion) dominates Series A (front-month, crashes near
# expiries) and Series B (raw 30D CMI, includes the same near-expiry
# noise). Caller can override for diagnostics (e.g., to compare a
# strategy variant ranked on Series A) but should never override
# for production runs.
DEFAULT_IV_SERIES = "iv_cmi30_excl7"


def time_series_ivp(
    iv_series: pd.Series,
    as_of: date,
    lookback_td: int = IVP_LOOKBACK_TD,
) -> float:
    """Trailing-window percentile rank (0-100) of ``iv_series.loc[as_of]``
    vs the trailing ``lookback_td`` observations ending at ``as_of``.

    F5 in PORTFOLIO_MEMOIR.md §21.4. Identical kernel to
    ``regime_percentile`` (F9) — both are the same percentile-rank
    math applied to different signal series. Per the regime.py
    module docstring's spec-alignment note: keeping the kernel
    inline in two places (regime + ivp) is the deliberate choice —
    the alternative would couple regime to a deferred IVP module
    just to share four lines of arithmetic.

    Args:
        iv_series: a pd.Series of IV values (typically the
            ``iv_cmi30_excl7`` column from
            ``load_iv_history(symbol)``), indexed ascending by
            date-typed labels.
        as_of: the trading date to compute IVP for. If it's not
            on the series index (e.g., a weekend or holiday), the
            most recent date <= as_of is used.
        lookback_td: trailing-window length in observations.
            Defaults to 252 (≈ 1 calendar year of trading days).

    Returns:
        ``float`` in [0.0, 100.0] when there's enough history.
        ``np.nan`` if:
          - ``as_of`` predates the entire series, OR
          - the value at the resolved date is NaN (F5 NaN guard
            — silent-rank-NaN-as-0 is the load-bearing bug this
            avoids), OR
          - the trailing window has < ``IVP_MIN_VALID_FRACTION ×
            lookback_td`` non-NaN observations.

    Pin-points (do not drift without a memoir revision):
      - Numerator: ``(valid < today).sum()`` (strictly less than).
      - Denominator: ``len(valid)`` (NaN-dropped, NOT ``len(window)``).
      - Floor: ``< 0.5 × lookback_td`` (of REQUESTED lookback, NOT
        of REALIZED window length).
    """
    if not isinstance(iv_series, pd.Series):
        raise TypeError(
            f"iv_series must be pd.Series, got {type(iv_series).__name__}"
        )
    if lookback_td < 2:
        raise ValueError(
            f"lookback_td must be >= 2 for a stable rank, got {lookback_td}"
        )
    if iv_series.empty:
        return float("nan")

    # Locate the index position of ``as_of`` (or the latest date
    # <= as_of). Series must be sorted ascending; right-edge
    # insertion - 1 rounds a non-trading-day as_of DOWN to the
    # most recent trading day. Matches regime_percentile.
    ts_as_of = pd.Timestamp(as_of)
    idx_pos = iv_series.index.searchsorted(ts_as_of, side="right") - 1
    if idx_pos < 0:
        return float("nan")  # as_of predates the entire series

    today_value = iv_series.iloc[idx_pos]
    if pd.isna(today_value):
        # F5 load-bearing NaN guard: ``(window < NaN).sum()``
        # silently returns 0, which would render a missing-IV day
        # as 0th percentile ("cheapest vol ever") and trigger the
        # IVP filter to ENTER on a day with no signal. Memoir
        # §21.4 F5 documents this as the original bug fixed by
        # explicit ``pd.isna(today)`` guard.
        return float("nan")

    window_start = max(0, idx_pos - lookback_td + 1)
    window = iv_series.iloc[window_start : idx_pos + 1]
    valid = window.dropna()
    # Insufficient-history floor: < IVP_MIN_VALID_FRACTION of the
    # REQUESTED lookback (not of the realized window). Stops
    # short-window early periods from silently producing stable-
    # looking ranks. Pinned per reviewer d8620f8 GRILL 1.
    if len(valid) < IVP_MIN_VALID_FRACTION * lookback_td:
        return float("nan")

    # Percentile rank on the dropna'd subset. Denominator is
    # ``len(valid)`` — NaN-bearing days neither contribute to the
    # count nor to the denominator. Pinned per reviewer d8620f8
    # GRILL 3.
    return float((valid < today_value).sum()) / len(valid) * 100.0


def compute_ivp(
    symbol: str,
    as_of: date,
    *,
    series: str = DEFAULT_IV_SERIES,
    lookback_td: int = IVP_LOOKBACK_TD,
) -> float:
    """Convenience wrapper: load the per-symbol IV history parquet
    and compute the trailing-252-TD percentile of today's value.

    Reads ``data/cache/iv/{SYMBOL}.parquet`` via
    ``iv_materializer.load_iv_history`` and runs ``time_series_ivp``
    on the requested column. Raises ``FileNotFoundError`` if the
    cache hasn't been materialized for ``symbol`` (downstream
    consumers should treat that as "materialize first" — silent-
    empty would mask a missing pipeline step).

    Args:
        symbol: NSE ticker (case-insensitive; uppercased by
            ``cache.iv_path``).
        as_of: the trading date to compute IVP for.
        series: which IV column to rank on. Defaults to
            ``iv_cmi30_excl7`` (Series C, operator-locked
            methodology default). Other valid values:
            ``iv_front``, ``iv_cmi30_raw``.
        lookback_td: trailing-window length. Defaults to 252.

    Returns:
        IVP in [0.0, 100.0] or ``np.nan`` per
        ``time_series_ivp``'s NaN semantics.
    """
    df = load_iv_history(symbol)
    if series not in df.columns:
        raise ValueError(
            f"IV history for {symbol!r} has no column {series!r}; "
            f"available: {list(df.columns)}"
        )
    iv_series = df.set_index("date")[series]
    return time_series_ivp(iv_series, as_of, lookback_td=lookback_td)


def top_n_by_ivp(
    ivp_today_per_symbol: Mapping[str, float],
    n: int = 5,
) -> list[str]:
    """Cross-sectional rank: pick the top ``n`` symbols by IVP today.

    F6 in PORTFOLIO_MEMOIR.md §21.4. Memoir says "rank-of-ranks":
    the per-symbol TS-IVP gives "is THIS name's vol expensive vs
    its own history?"; this function picks the N richest names on
    that scale across the eligible universe.

    Tie-breaking: when two symbols have the same IVP, sort by
    SYMBOL name ASCENDING so the result is deterministic across
    runs. (The memoir's spec doesn't pin a tie-breaker; deterministic
    output is required for byte-identical sweep results per
    SPECS §6c.3, so we pin one here.)

    NaN handling: symbols with NaN IVP (cold cache, NaN today,
    insufficient history) are EXCLUDED from the ranking. Returning
    them would either propagate NaN through the strategy or
    require special-casing in every downstream consumer.

    Args:
        ivp_today_per_symbol: ``{symbol: IVP}`` for the eligible
            universe on a given day. Typical caller: a loop over
            today's tradable universe, calling ``compute_ivp``
            for each.
        n: number of top picks to return. If fewer than ``n``
            symbols have valid (non-NaN) IVP, returns however
            many are available.

    Returns:
        List of up to ``n`` symbols, sorted by IVP descending
        (with symbol-name ascending tiebreak). Empty list if no
        symbols have a valid IVP.
    """
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    valid: list[tuple[str, float]] = [
        (sym, v)
        for sym, v in ivp_today_per_symbol.items()
        if v is not None and not (isinstance(v, float) and np.isnan(v))
    ]
    # Deterministic tie-breaker: symbol ASCENDING. sort() is
    # stable; we apply symbol-ascending FIRST then IVP-descending
    # so equal-IVP rows come out alphabetical.
    valid.sort(key=lambda kv: kv[0])
    valid.sort(key=lambda kv: kv[1], reverse=True)
    return [sym for sym, _ in valid[:n]]
