"""MCP tool — bootstrap_ci (sub-arc 3.6, tool 2 of 2).

Pure-compute exposure of the project's percentile-bootstrap CI helper.
Useful when a consumer Claude has its own per-trade value list
(say, after combining cells from ``compare_cells``, filtering by
expiry, or pulling raw numbers from ``query_sweep``) and wants a
honest CI on a chosen statistic.

This tool ONLY computes the bootstrap. It does NOT load any sweep
data — the consumer passes the values in directly. That keeps the
input/output schema minimal and lets the same machinery serve
multiple analytic flows.

Reuses ``src.analytics.bootstrap.bootstrap_ci`` so the seed, B, and
percentile-based bound construction stay identical to the dashboard's
Median Hero card + cell_summary's bootstrap_ci_median_roi field.

Closes sub-arc 3.6 (research helpers). Last tool before the docs
commit; total tools = 16.
"""
from __future__ import annotations

from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from src.analytics.bootstrap import bootstrap_ci as _bootstrap_ci
from src.mcp._models import CaveatedResponse, ToolEntry


# Cap on input array size. The vectorised numpy resample creates a
# (B × n) integer matrix; at B=1000 and n=10K, that's 10M integers ≈
# 80MB. Hard cap at 5K to stay under 40MB even at max-B settings.
MAX_VALUES = 5_000

# Min input size below which the CI is undefined per
# src.analytics.bootstrap.bootstrap_ci (returns NaN tuple). We emit
# this as a caveat rather than raising — consumer Claudes can still
# read the empty result and react accordingly.
MIN_VALUES_FOR_CI = 2

# Same threshold the cell_summary tool uses for its small-N caveat.
# Re-exported here so the constant lives in one source of truth.
# (Imported lazily inside the impl to avoid a hard cross-module
# dependency at import time.)


SupportedStatistic = Literal["median", "mean"]


# ============================================================
# Models
# ============================================================

class BootstrapCIInput(BaseModel):
    values: list[float] = Field(
        ...,
        min_length=1,
        description=(
            "1-D numeric values to bootstrap (e.g. per-trade ROI for "
            f"one cell). Capped at {MAX_VALUES} entries. NaN values "
            "are dropped before the resample."
        ),
    )
    statistic: SupportedStatistic = Field(
        default="median",
        description=(
            "Which statistic to bootstrap. 'median' (default) matches "
            "the dashboard's Median Hero card. 'mean' is sensitive to "
            "tail events and pairs with cvar-aware analysis."
        ),
    )
    B: int = Field(
        default=1000,
        ge=1, le=10_000,
        description="Number of bootstrap resamples. Default 1000.",
    )
    alpha: float = Field(
        default=0.05,
        ge=0.0, lt=1.0,
        description=(
            "Significance level. alpha=0.05 → 95% CI. Bounds are the "
            "α/2 and 1−α/2 quantiles of the resampled-statistic "
            "distribution."
        ),
    )
    seed: int = Field(
        default=0,
        description=(
            "RNG seed for reproducibility. Same (values, B, seed) → "
            "byte-identical (lo, hi)."
        ),
    )


class BootstrapCIOutput(CaveatedResponse):
    point_estimate: float | None = Field(
        ...,
        description=(
            "``statistic(values)`` on the original sample after NaN "
            "drop. None when n < 2 (CI undefined)."
        ),
    )
    ci_lo: float | None
    ci_hi: float | None
    method: str = Field(
        ...,
        description=(
            "Self-describing method string constructed from B + seed "
            "+ alpha + statistic — single source of truth so the "
            "string can't drift from the actual call."
        ),
    )
    n_input: int = Field(
        ..., description="Original values length, pre-NaN-drop."
    )
    n_finite: int = Field(
        ..., description="Values used in the bootstrap (post-NaN-drop)."
    )


# ============================================================
# Tool impl
# ============================================================

def bootstrap_ci_impl(inp: BootstrapCIInput) -> BootstrapCIOutput:
    from src.analytics.aggregate import MIN_N_FOR_RANKING

    method = (
        f"percentile bootstrap, statistic={inp.statistic}, B={inp.B}, "
        f"seed={inp.seed}, alpha={inp.alpha}"
    )

    caveats: list[str] = []

    if len(inp.values) > MAX_VALUES:
        raise ValueError(
            f"values length {len(inp.values)} exceeds cap "
            f"{MAX_VALUES}. Pre-aggregate or sample before passing."
        )

    arr = np.asarray(inp.values, dtype=float)
    finite = arr[np.isfinite(arr)]
    n_finite = int(len(finite))

    if n_finite < MIN_VALUES_FOR_CI:
        caveats.append(
            f"n_finite={n_finite} below MIN_VALUES_FOR_CI="
            f"{MIN_VALUES_FOR_CI}; bootstrap CI is undefined. "
            f"Returning (point_estimate, ci_lo, ci_hi) all = None."
        )
        return BootstrapCIOutput(
            point_estimate=None, ci_lo=None, ci_hi=None,
            method=method,
            n_input=len(inp.values), n_finite=n_finite,
            caveats=caveats,
        )

    if n_finite < MIN_N_FOR_RANKING:
        caveats.append(
            f"n_finite={n_finite} below the conventional "
            f"MIN_N_FOR_RANKING threshold of {MIN_N_FOR_RANKING}. The "
            f"CI is still computed but the bounds are unstable at this "
            f"sample size — treat as suggestive only."
        )

    statistic_fn = np.median if inp.statistic == "median" else np.mean

    point, lo, hi = _bootstrap_ci(
        finite,
        statistic=statistic_fn,
        B=inp.B,
        alpha=inp.alpha,
        seed=inp.seed,
    )

    return BootstrapCIOutput(
        point_estimate=None if np.isnan(point) else float(point),
        ci_lo=None if np.isnan(lo) else float(lo),
        ci_hi=None if np.isnan(hi) else float(hi),
        method=method,
        n_input=len(inp.values),
        n_finite=n_finite,
        caveats=caveats,
    )


# ============================================================
# Registry export
# ============================================================

def register_bootstrap_ci_tools() -> list[ToolEntry]:
    return [
        ToolEntry(
            name="bootstrap_ci",
            description=(
                "Pure-compute percentile-bootstrap CI on a consumer-"
                "provided values array. Useful for honest uncertainty "
                "bands on median/mean of arbitrary numeric inputs. "
                "Same machinery as the dashboard's Median Hero card "
                "and cell_summary's bootstrap_ci_median_roi field. "
                f"Capped at {MAX_VALUES} input values."
            ),
            input_model=BootstrapCIInput,
            output_model=BootstrapCIOutput,
            impl=bootstrap_ci_impl,
        ),
    ]
