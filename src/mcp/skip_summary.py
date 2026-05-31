"""MCP tool — skip_summary (sub-arc 3.5, tool 1 of 2).

Returns the skip-by-reason breakdown for one sweep run, with optional
grouping (by strategy / symbol / entry_offset_td / expiry) for finer
slicing. The companion to ``query_sweep`` for skipped cells — answers
"where did the gate fire, and how often."

The data lives in ``data/results/sweep_{run_id}_skipped.parquet``,
written alongside the main results parquet by the sweeper. When no
skip companion exists (a clean sweep with zero skips), the tool
returns an empty-group summary explicitly rather than raising.

Caveats fire for pre-pricing-arc runs the same way as the other
sweep-query tools — a pre-arc parquet's skip distribution reflects
the OLD engine's behavior (mostly OfflineCacheMiss + corporate-action
skips), so a consumer can't compare a pre-arc skip breakdown
1-to-1 with a post-arc one (the post-arc adds IlliquidLegError as a
dominant new skip class).
"""
from __future__ import annotations

from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field

from src.engine.results import (
    ENGINE_VERSION,
    read_results,
    read_run_metadata,
    read_skips,
)
from src.mcp._models import (
    PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT,
    CaveatedResponse,
    ToolEntry,
)


# Hard cap on the number of examples per group. Each example is one
# row from the skip log; consumer Claude doesn't need 50 examples to
# understand "what does an IlliquidLegError on T-42 look like."
DEFAULT_MAX_EXAMPLES = 3
MAX_MAX_EXAMPLES = 20


SkipGroupBy = Literal[
    "reason", "strategy", "symbol", "entry_offset_td", "expiry",
]


# ============================================================
# Models
# ============================================================

class SkipExample(BaseModel):
    """One representative row from the skip log."""
    strategy: str
    symbol: str
    expiry: str = Field(..., description="ISO date string of the expiry.")
    entry_offset_td: int
    exit_offset_td: int
    skip_reason: str
    skip_detail: str


class SkipGroupSummary(BaseModel):
    """One bucket of the requested group_by dimension."""
    key: str = Field(
        ...,
        description=(
            "The grouped value as a string (e.g. 'IlliquidLegError', "
            "'short_straddle', '42', '2024-01-25')."
        ),
    )
    count: int
    examples: list[SkipExample] = Field(
        ...,
        description=(
            "First N rows of this group's skips. Capped per the "
            "request's ``max_examples`` argument."
        ),
    )


class SkipSummaryInput(BaseModel):
    run_id: str
    group_by: SkipGroupBy = Field(
        default="reason",
        description=(
            "Which column to bucket skips by. 'reason' (the default) "
            "answers 'what kinds of failures occurred'. 'strategy' / "
            "'symbol' / 'entry_offset_td' / 'expiry' surface where the "
            "failures concentrate."
        ),
    )
    max_examples: int = Field(
        default=DEFAULT_MAX_EXAMPLES,
        ge=0, le=MAX_MAX_EXAMPLES,
        description=(
            f"How many example rows per group to surface. Default "
            f"{DEFAULT_MAX_EXAMPLES}; hard cap {MAX_MAX_EXAMPLES}. Set "
            f"to 0 for counts-only output."
        ),
    )


class SkipSummaryOutput(CaveatedResponse):
    run_id: str
    total_cells_attempted: int = Field(
        ...,
        description=(
            "Priced cells + skipped cells in the sweep. Computed as "
            "len(results parquet) + len(skips parquet)."
        ),
    )
    total_cells_priced: int
    total_cells_skipped: int
    skip_rate_pct: float = Field(
        ...,
        description="100 × total_cells_skipped / total_cells_attempted.",
    )
    groups: list[SkipGroupSummary] = Field(
        ...,
        description=(
            "Sorted by count DESC — biggest bucket first so the "
            "consumer Claude reads the dominant failure mode at the "
            "top of the list."
        ),
    )


# ============================================================
# Helpers
# ============================================================

def _column_for_group_by(group_by: SkipGroupBy) -> str:
    """Translate the input enum to the skip-frame column name."""
    if group_by == "reason":
        return "skip_reason"
    return group_by  # strategy / symbol / entry_offset_td / expiry match


def _row_to_example(row: pd.Series) -> SkipExample:
    expiry_str = (
        row["expiry"].date().isoformat()
        if isinstance(row["expiry"], pd.Timestamp)
        else str(row["expiry"])
    )
    return SkipExample(
        strategy=str(row["strategy"]),
        symbol=str(row["symbol"]),
        expiry=expiry_str,
        entry_offset_td=int(row["entry_offset_td"]),
        exit_offset_td=int(row["exit_offset_td"]),
        skip_reason=str(row["skip_reason"]),
        skip_detail=str(row.get("skip_detail", "")),
    )


# ============================================================
# Tool impl
# ============================================================

def skip_summary_impl(inp: SkipSummaryInput) -> SkipSummaryOutput:
    # 1. Read the main results parquet for the priced count + side-
    # effect of validating that the run_id exists at all.
    try:
        priced_df = read_results(inp.run_id)
    except FileNotFoundError as e:
        raise ValueError(
            f"run_id {inp.run_id!r} has no sweep parquet at "
            f"data/results/sweep_{inp.run_id}.parquet"
        ) from e
    n_priced = len(priced_df)

    # 2. Read the skip-log companion (may be missing if zero skips).
    skips_df = read_skips(inp.run_id)
    n_skipped = len(skips_df)
    n_attempted = n_priced + n_skipped
    skip_rate_pct = (
        100.0 * n_skipped / n_attempted if n_attempted > 0 else 0.0
    )

    # 3. Pre-arc caveat.
    caveats: list[str] = []
    stamp = read_run_metadata(inp.run_id)
    if stamp.get("engine_version") != ENGINE_VERSION:
        caveats.append(PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT)
        caveats.append(
            "Skip distribution reflects PRE-arc engine behavior — "
            "mostly OfflineCacheMiss + corporate-action skips. The "
            "post-arc engine adds IlliquidLegError as a dominant new "
            "skip class (zero-volume legs the gate rejects); the two "
            "breakdowns are NOT directly comparable."
        )

    # 4. Empty-skip-companion case.
    if n_skipped == 0:
        return SkipSummaryOutput(
            run_id=inp.run_id,
            total_cells_attempted=n_attempted,
            total_cells_priced=n_priced,
            total_cells_skipped=0,
            skip_rate_pct=0.0,
            groups=[],
            caveats=caveats,
        )

    # 5. Group + sort by count DESC.
    column = _column_for_group_by(inp.group_by)
    if column not in skips_df.columns:
        raise ValueError(
            f"group_by={inp.group_by!r} expected column {column!r} "
            f"but it's absent from the skip log; got "
            f"{sorted(skips_df.columns)}"
        )

    groups: list[SkipGroupSummary] = []
    for key, group_df in skips_df.groupby(column, sort=False):
        examples: list[SkipExample] = []
        if inp.max_examples > 0:
            head = group_df.head(inp.max_examples)
            for _, row in head.iterrows():
                examples.append(_row_to_example(row))
        # Coerce key to string — dates / ints / nans need cleanup.
        if isinstance(key, pd.Timestamp):
            key_str = key.date().isoformat()
        elif pd.isna(key):
            key_str = "<missing>"
        else:
            key_str = str(key)
        groups.append(SkipGroupSummary(
            key=key_str,
            count=int(len(group_df)),
            examples=examples,
        ))

    groups.sort(key=lambda g: g.count, reverse=True)

    return SkipSummaryOutput(
        run_id=inp.run_id,
        total_cells_attempted=n_attempted,
        total_cells_priced=n_priced,
        total_cells_skipped=n_skipped,
        skip_rate_pct=skip_rate_pct,
        groups=groups,
        caveats=caveats,
    )


# ============================================================
# Registry export
# ============================================================

def register_skip_summary_tools() -> list[ToolEntry]:
    return [
        ToolEntry(
            name="skip_summary",
            description=(
                "Return the skip-by-reason breakdown for one sweep "
                "run, optionally grouped by strategy / symbol / "
                "entry_offset_td / expiry. Sorted by count DESC so "
                "the dominant failure mode reads first. Includes "
                "examples per group; pre-pricing-arc caveat fires "
                "when the run lacks the engine_version stamp."
            ),
            input_model=SkipSummaryInput,
            output_model=SkipSummaryOutput,
            impl=skip_summary_impl,
        ),
    ]
