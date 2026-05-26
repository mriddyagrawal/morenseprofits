"""Bootstrap confidence intervals for sample statistics.

Used by the heatmap drill-down to surface a 95% CI under the headline
median ROI/yr so the analyst sees the uncertainty bound directly under
the point estimate — matching the design/Complete mockup's honesty stack
(big number ▸ CI line ▸ interpretation callout).

Pure function, no I/O, deterministic given a seed."""
from __future__ import annotations

from typing import Callable

import numpy as np


def bootstrap_ci(
    values: np.ndarray | list[float],
    *,
    statistic: Callable[[np.ndarray], float] = np.median,
    B: int = 1000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Return ``(point_estimate, ci_lo, ci_hi)`` for ``statistic(values)``
    via non-parametric (percentile) bootstrap.

    Algorithm: draw ``B`` independent IID-with-replacement resamples of
    the same size as ``values``, apply ``statistic`` to each, take the
    α/2 and 1−α/2 quantiles of the resampled-statistic distribution.

    Args:
        values: 1-D numeric array. NaNs are dropped silently.
        statistic: function on a 1-D array → scalar. Defaults to median.
        B: number of resamples (B=1000 is the project default; matches
            the mockup's "bootstrap (B=1000)" annotation).
        alpha: significance level for the two-sided CI (default 0.05 →
            95% CI). 0 ≤ alpha < 1.
        seed: RNG seed for reproducibility. Same (values, B, seed) →
            byte-identical (lo, hi).

    Returns:
        Tuple of ``(point_estimate, ci_lo, ci_hi)``. All three are NaN
        when ``values`` has fewer than 2 finite entries (CI undefined
        for n<2; the caller should branch on this).

    Raises:
        ValueError: ``B < 1``, ``alpha`` out of range, or ``values`` is
        2-D (shape guard since pandas Series.values can sneak through).
    """
    if B < 1:
        raise ValueError(f"B must be ≥ 1, got {B}")
    if not (0.0 <= alpha < 1.0):
        raise ValueError(f"alpha must satisfy 0 ≤ alpha < 1, got {alpha}")
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError(f"values must be 1-D, got shape {arr.shape}")
    arr = arr[np.isfinite(arr)]
    n = len(arr)
    if n < 2:
        return float("nan"), float("nan"), float("nan")
    point = float(statistic(arr))
    rng = np.random.default_rng(seed)
    # Vectorized resample: (B, n) integer indices into arr → (B, n)
    # sample matrix.
    idx = rng.integers(0, n, size=(B, n))
    samples = arr[idx]
    # Fast-path: when statistic IS np.median, call it with axis=1 in C
    # (~10× faster than np.apply_along_axis at B=1000). Mean / max /
    # min also support axis natively. Generic callables fall back to
    # apply_along_axis since we can't introspect their axis-awareness.
    if statistic is np.median:
        stats = np.median(samples, axis=1)
    elif statistic is np.mean:
        stats = np.mean(samples, axis=1)
    elif statistic in (np.max, np.amax, np.min, np.amin):
        stats = statistic(samples, axis=1)
    else:
        stats = np.apply_along_axis(statistic, 1, samples)
    lo = float(np.quantile(stats, alpha / 2))
    hi = float(np.quantile(stats, 1 - alpha / 2))
    return point, lo, hi
