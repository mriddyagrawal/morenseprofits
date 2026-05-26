"""Strike-window planner for prefetch coverage decisions.

Distinct from ``src/strategies/_strikes.py`` (which picks the *one* strike
a strategy will trade): this module decides which RANGE of strikes the
prefetch should download so the strategy's later pick is guaranteed to
hit cache.

Rule: ``max(N strikes per side, X% range around spot)``. Self-adapting:
  - Tight-spaced symbols (e.g. SBIN @ ₹10 spacing): "N per side" tends
    to win because 5% covers only ~4 strikes.
  - Wide-spaced indices (e.g. BANKNIFTY @ ₹100 spacing): "X% range"
    wins because N=6 covers only ~0.7% of spot.

Pure function, no I/O, no globals — easy to unit test.
"""
from __future__ import annotations


def strikes_around_spot_hybrid(
    grid: list[int],
    spot: float,
    per_side: int = 6,
    pct_window: float = 0.05,
) -> list[int]:
    """Pick strikes from ``grid`` covering the wider of:

      (a) ``per_side`` strikes on each side of the ATM (so 2*per_side+1 total)
      (b) every strike within ``spot * (1 ± pct_window)``

    Returns sorted ascending. ATM is the strike nearest to ``spot``;
    SPECS §5 lower-strike tiebreaker applies when two strikes tie on
    distance.

    Args:
        grid: sorted-ascending list of available strikes (ints from the
            bhavcopy; SPECS §5 enforces whole-rupee values).
        spot: current spot price of the underlying.
        per_side: minimum number of strikes to keep on each side of ATM.
        pct_window: minimum %-of-spot range to keep on each side of ATM.

    Returns:
        Subset of ``grid``, sorted ascending. Empty if ``grid`` is empty.

    Raises:
        ValueError: ``per_side < 0`` or ``pct_window < 0`` (both must
        be non-negative; zero on either degenerates to the other rule).
    """
    if per_side < 0:
        raise ValueError(f"per_side must be ≥ 0, got {per_side}")
    if pct_window < 0:
        raise ValueError(f"pct_window must be ≥ 0, got {pct_window}")
    if not grid:
        return []

    sorted_grid = sorted(grid)
    n = len(sorted_grid)

    # ATM = argmin |K − spot|, tie-break to lower strike (SPECS §5).
    atm_idx = min(
        range(n),
        key=lambda i: (abs(sorted_grid[i] - spot), sorted_grid[i]),
    )

    # Rule (a): per_side strikes on each side of ATM.
    lo_via_count = max(0, atm_idx - per_side)
    hi_via_count = min(n - 1, atm_idx + per_side)

    # Rule (b): every strike within [spot * (1 - pct), spot * (1 + pct)].
    low_bound = spot * (1.0 - pct_window)
    high_bound = spot * (1.0 + pct_window)
    # Find leftmost strike >= low_bound (could be ATM itself, in which
    # case this rule degenerates to "no extra coverage").
    lo_via_pct = next(
        (i for i, k in enumerate(sorted_grid) if k >= low_bound),
        atm_idx,  # nothing >= low_bound → fall back to ATM
    )
    # Find rightmost strike <= high_bound.
    hi_via_pct = next(
        (i for i in range(n - 1, -1, -1) if sorted_grid[i] <= high_bound),
        atm_idx,
    )

    # Union = widest of the two on each side.
    lo = min(lo_via_count, lo_via_pct)
    hi = max(hi_via_count, hi_via_pct)
    return sorted_grid[lo : hi + 1]
