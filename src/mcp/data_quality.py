"""MCP tool — data_quality (sub-arc 3.5, tool 2 of 2).

Three diagnostic dimensions, one tool. The analyst's path to
quantifying the data-quality artifacts the pricing arc was designed
to address:

1. ``liquidity_by_entry_offset``  — the table that surfaced the
   phantom-fill bias on 2026-05-30. Buckets per-trade ROI + zero-
   volume rate + mean entry volume by entry-depth band. Pre-arc
   data shows the +10.9% T-41..T-45 spike here; post-arc (with the
   gate) should show the deep-entry rows compressed because the
   zero-volume cells are skipped.

2. ``theoretical_fallback_rate`` — what fraction of priced legs used
   close (engine fell back because turnover was missing) vs VWAP.
   Critical for the operator's "hybrid VWAP coverage" awareness
   (see 2026-05-31 prefetch audit): symbols cached pre-turnover-
   ingest will show 100% close fallback even when their data is
   otherwise clean.

3. ``vwap_vs_close_divergence`` — for legs that fell back to close
   AND have turnover data (close used because of band-reject, not
   missing data), how much VWAP would have differed from close.
   Measures the size of the fix VWAP would have applied. Empty when
   all close fallbacks were due to missing turnover.

Closes sub-arc 3.5 (diagnostics). Companion to ``skip_summary`` for
quantifying NSE/ingest health rather than gate health.
"""
from __future__ import annotations

import json
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from src.engine.pnl import (
    TURNOVER_SCALE_FACTOR,
    classify_fill_source,
)
from src.engine.results import (
    ENGINE_VERSION,
    read_results,
    read_run_metadata,
)
from src.mcp._models import (
    PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT,
    CaveatedResponse,
    ToolEntry,
)


# Cap on rows scanned per data_quality call. For very large sweeps
# (~2M trades), parsing every legs_json blob would blow the SDK's
# response-time budget. Sampling at 200K trades preserves
# distributional fidelity at < 30 seconds wall-clock.
MAX_TRADES_SAMPLED = 200_000


# Entry-offset banding for the liquidity_by_entry_offset table.
# Matches the bands used in the 2026-05-30 analysis so consumer
# Claudes can compare the post-arc result directly against the
# pre-arc baseline numbers preserved in PLAN.md.
ENTRY_OFFSET_BANDS = [
    (1, 5), (6, 10), (11, 20), (21, 30), (31, 40), (41, 45),
]


DataQualityDimension = Literal[
    "liquidity_by_entry_offset",
    "theoretical_fallback_rate",
    "vwap_vs_close_divergence",
]


# ============================================================
# Models
# ============================================================

class DataQualityInput(BaseModel):
    run_id: str
    dimension: DataQualityDimension = Field(
        default="liquidity_by_entry_offset",
        description=(
            "Which diagnostic to surface. The default "
            "'liquidity_by_entry_offset' answers 'is the gate fixing "
            "the phantom-fill bias'; 'theoretical_fallback_rate' "
            "answers 'is my universe's VWAP coverage uniform'; "
            "'vwap_vs_close_divergence' answers 'how much would VWAP "
            "have changed the fill prices'."
        ),
    )


class DataQualityOutput(CaveatedResponse):
    run_id: str
    dimension: str
    n_trades_sampled: int = Field(
        ...,
        description=(
            "Number of trades whose legs_json was parsed for this "
            "analysis. Capped at MAX_TRADES_SAMPLED for runs larger "
            "than that — caveats flag the sampling when it fires."
        ),
    )
    summary: str = Field(
        ...,
        description=(
            "One-paragraph human-readable summary of what the table "
            "shows. Consumer Claudes should READ this before "
            "interpreting the table — it names the right comparison "
            "to make."
        ),
    )
    table: list[dict[str, Any]] = Field(
        ...,
        description=(
            "Per-row analysis output. Schema depends on dimension; "
            "see the per-dimension docstrings."
        ),
    )


# ============================================================
# Helpers — sampling + leg extraction
# ============================================================

def _sample_trades(df: pd.DataFrame) -> tuple[pd.DataFrame, bool]:
    """Down-sample if the sweep is larger than MAX_TRADES_SAMPLED.
    Returns (sampled_df, was_sampled_flag). Random sample with a
    fixed seed for determinism — same run_id → same sample on
    repeat calls."""
    if len(df) <= MAX_TRADES_SAMPLED:
        return df, False
    return (
        df.sample(n=MAX_TRADES_SAMPLED, random_state=0).reset_index(drop=True),
        True,
    )


def _flatten_legs(df: pd.DataFrame) -> pd.DataFrame:
    """Parse legs_json across every trade row, return a flat one-leg-
    per-row DataFrame carrying the analytical fields. Trades with
    malformed legs_json are dropped silently — the schema-validation
    layer in write_results catches malformed cells at write time,
    so this should be vanishingly rare in production data."""
    leg_rows: list[dict] = []
    # Cache the columns we copy from trade-level to per-leg
    keep_trade_cols = ["entry_offset_td", "exit_offset_td", "symbol",
                       "strategy", "roi_pct", "net_pnl"]
    for _, trade in df.iterrows():
        try:
            legs = json.loads(trade["legs_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        trade_cols = {c: trade[c] for c in keep_trade_cols if c in trade}
        for leg in legs:
            row = dict(trade_cols)
            row.update({
                "entry_px": leg.get("entry_px"),
                "exit_px": leg.get("exit_px"),
                "entry_volume": leg.get("entry_volume"),
                "exit_volume": leg.get("exit_volume"),
                "entry_turnover": leg.get("entry_turnover"),
                "exit_turnover": leg.get("exit_turnover"),
            })
            leg_rows.append(row)
    return pd.DataFrame(leg_rows)


# ============================================================
# Dimension impls
# ============================================================

def _liquidity_by_entry_offset(df: pd.DataFrame) -> tuple[list[dict], str]:
    """Bucket per-trade ROI + zero-vol rate + mean entry vol by
    entry-depth band. Matches the 2026-05-30 analysis exactly."""
    # Per-trade analysis: take minimum volume across legs as the
    # "leg with worst liquidity" proxy — that's what the original
    # analysis used.
    if "legs_json" not in df.columns:
        return [], "legs_json column missing; cannot compute liquidity."

    legs_df = _flatten_legs(df)
    if legs_df.empty:
        return [], "No legs parsed; data may be missing legs_json."

    # Trade-level stats (n_trades, mean_roi, median_roi) come from
    # ``df`` directly per fix(data_quality.liquidity_dedup): the
    # original impl flattened legs first and deduplicated by
    # (eot, xot, symbol, strategy), which collapsed all expiries of
    # a cell into one row — n_trades under-counted by a factor of
    # ``len(expiries)`` and mean_roi was the FIRST expiry's roi only.
    # Computing trade-level stats from ``df`` filtered to the band
    # removes the leaky leg-multiplication round-trip entirely;
    # legs_df is now used ONLY for leg-level metrics (zero-volume
    # fraction + mean entry volume).
    table: list[dict] = []
    for lo, hi in ENTRY_OFFSET_BANDS:
        band_trades = df[
            (df["entry_offset_td"] >= lo)
            & (df["entry_offset_td"] <= hi)
        ]
        band_legs = legs_df[
            (legs_df["entry_offset_td"] >= lo)
            & (legs_df["entry_offset_td"] <= hi)
        ]
        if band_trades.empty:
            continue
        n_trades = int(len(band_trades))
        mean_roi = float(band_trades["roi_pct"].mean())
        median_roi = float(band_trades["roi_pct"].median())
        # Leg-level liquidity: fraction of LEGS with entry_volume==0
        # + mean entry volume across the band's legs.
        if band_legs.empty:
            frac_zero = None
            mean_entry_vol = None
        else:
            zero_vol_legs = (band_legs["entry_volume"] == 0).sum()
            total_legs = band_legs["entry_volume"].notna().sum()
            frac_zero = (
                float(zero_vol_legs / total_legs) if total_legs > 0 else None
            )
            mean_entry_vol = float(band_legs["entry_volume"].mean())
        table.append({
            "entry_offset_band": f"T-{lo:02d}..T-{hi:02d}",
            "entry_offset_min": lo,
            "entry_offset_max": hi,
            "n_trades": n_trades,
            "frac_legs_zero_entry_volume": frac_zero,
            "mean_entry_volume": mean_entry_vol,
            "mean_roi_pct": mean_roi,
            "median_roi_pct": median_roi,
        })

    summary = (
        "Per-trade ROI and zero-volume rate bucketed by entry-depth. "
        "Pre-pricing-arc data shows monotonic +10.9% ROI rising with "
        "zero-volume rate across T-41..T-45. Post-arc data should "
        "show the deep-entry bands either shrinking (cells skipped "
        "by the IlliquidLegError gate) OR — if still populated — "
        "showing ROI compressed toward the T-1..T-5 baseline. "
        "Direct A/B against the 2026-05-30 PLAN.md baseline."
    )
    return table, summary


def _theoretical_fallback_rate(df: pd.DataFrame) -> tuple[list[dict], str]:
    """For each leg, classify as VWAP-derived vs close-derived using
    the centralized ``classify_fill_source`` from engine.pnl. Returns
    per-symbol fallback rates."""
    if "legs_json" not in df.columns:
        return [], "legs_json column missing; cannot compute fallback rate."
    legs_df = _flatten_legs(df)
    if legs_df.empty:
        return [], "No legs parsed; data may be missing legs_json."

    # Classify each leg's entry side. (Same for exit.)
    legs_df["entry_source"] = legs_df.apply(
        lambda r: classify_fill_source(
            r["entry_px"], r["entry_volume"], r["entry_turnover"],
        ),
        axis=1,
    )

    rows: list[dict] = []
    for symbol, sub in legs_df.groupby("symbol"):
        n_total = len(sub)
        n_vwap = (sub["entry_source"] == "vwap").sum()
        n_close = (sub["entry_source"] == "close").sum()
        n_unknown = (sub["entry_source"] == "unknown").sum()
        rows.append({
            "symbol": str(symbol),
            "n_legs": int(n_total),
            "n_vwap_fills": int(n_vwap),
            "n_close_fills": int(n_close),
            "n_unknown": int(n_unknown),
            "vwap_fill_rate_pct": float(100.0 * n_vwap / n_total) if n_total else None,
            "close_fill_rate_pct": float(100.0 * n_close / n_total) if n_total else None,
        })
    # Sort by close_fill_rate DESC — symbols with highest fallback at top
    rows.sort(key=lambda r: r["close_fill_rate_pct"] or 0.0, reverse=True)

    summary = (
        "Per-symbol fraction of ENTRY-leg fills that used VWAP vs fell "
        "back to close. NOTE: classification is ENTRY-side only — "
        "exit legs may have different fill paths (different date, "
        "different turnover availability) and are not counted here. "
        "Symbols with close_fill_rate_pct near 100% were cached "
        "BEFORE the p7.pricing_arc turnover ingest landed — their "
        "fills are the pre-VWAP behavior (still gate-corrected, still "
        "post-arc engine, but VWAP refinement absent). Symbols near 0% "
        "close fallback have full VWAP coverage. Mixed coverage "
        "across the universe is the expected state after the "
        "2026-05-31 prefetch run; force-refresh those symbols if "
        "uniform VWAP coverage matters for your comparison."
    )
    return rows, summary


def _vwap_vs_close_divergence(df: pd.DataFrame) -> tuple[list[dict], str]:
    """For legs where entry_fill_source classifies as 'close' AND
    turnover/volume are non-null (so we could have computed VWAP),
    measure |vwap_implied - close| / close to estimate the size of
    the correction VWAP would have applied."""
    if "legs_json" not in df.columns:
        return [], "legs_json column missing; cannot compute divergence."
    legs_df = _flatten_legs(df)
    if legs_df.empty:
        return [], "No legs parsed; data may be missing legs_json."

    legs_df["entry_source"] = legs_df.apply(
        lambda r: classify_fill_source(
            r["entry_px"], r["entry_volume"], r["entry_turnover"],
        ),
        axis=1,
    )

    candidates = legs_df[
        (legs_df["entry_source"] == "close")
        & (legs_df["entry_turnover"].notna())
        & (legs_df["entry_volume"] > 0)
        & (legs_df["entry_px"].notna())
    ].copy()

    if candidates.empty:
        return (
            [],
            "No legs with both close-fallback AND turnover data "
            "available — VWAP divergence cannot be measured. Either "
            "all fills used VWAP cleanly OR turnover is missing wherever "
            "close was used (legacy parquets)."
        )

    candidates["vwap_implied"] = (
        candidates["entry_turnover"].astype(float)
        * TURNOVER_SCALE_FACTOR
        / candidates["entry_volume"].astype(float)
    )
    candidates["abs_divergence_pct"] = (
        100.0
        * (candidates["vwap_implied"] - candidates["entry_px"]).abs()
        / candidates["entry_px"].abs().clip(lower=1e-9)
    )

    # Per-symbol divergence stats.
    rows: list[dict] = []
    for symbol, sub in candidates.groupby("symbol"):
        rows.append({
            "symbol": str(symbol),
            "n_legs_with_band_reject": int(len(sub)),
            "median_divergence_pct": float(sub["abs_divergence_pct"].median()),
            "mean_divergence_pct": float(sub["abs_divergence_pct"].mean()),
            "p95_divergence_pct": float(
                sub["abs_divergence_pct"].quantile(0.95)
            ),
        })
    rows.sort(key=lambda r: r["mean_divergence_pct"], reverse=True)

    summary = (
        "Per-symbol VWAP-vs-close divergence for ENTRY legs where the "
        "engine had turnover data BUT used close anyway (band-reject "
        "of the units-sanity assertion). NOTE: classification is "
        "ENTRY-side only — exit-leg divergence not measured here. "
        "Large divergence values flag symbols where NSE turnover and "
        "close drift apart routinely — operator-side: investigate the "
        "contracts to see whether settlement-price noise or genuine "
        "bid-ask asymmetry is the driver."
    )
    return rows, summary


_DIMENSION_DISPATCH = {
    "liquidity_by_entry_offset": _liquidity_by_entry_offset,
    "theoretical_fallback_rate": _theoretical_fallback_rate,
    "vwap_vs_close_divergence": _vwap_vs_close_divergence,
}


# ============================================================
# Tool impl
# ============================================================

def data_quality_impl(inp: DataQualityInput) -> DataQualityOutput:
    df = read_results(inp.run_id)
    sampled_df, was_sampled = _sample_trades(df)

    caveats: list[str] = []
    if was_sampled:
        caveats.append(
            f"Sweep has {len(df):,} trades; sampled "
            f"{MAX_TRADES_SAMPLED:,} (random_state=0, deterministic). "
            f"Per-bucket / per-symbol totals are proportional rather "
            f"than absolute."
        )

    stamp = read_run_metadata(inp.run_id)
    if stamp.get("engine_version") != ENGINE_VERSION:
        caveats.append(PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT)

    dispatcher = _DIMENSION_DISPATCH[inp.dimension]
    table, summary = dispatcher(sampled_df)

    return DataQualityOutput(
        run_id=inp.run_id,
        dimension=inp.dimension,
        n_trades_sampled=len(sampled_df),
        summary=summary,
        table=table,
        caveats=caveats,
    )


# ============================================================
# Registry export
# ============================================================

def register_data_quality_tools() -> list[ToolEntry]:
    return [
        ToolEntry(
            name="data_quality",
            description=(
                "Three diagnostic dimensions in one tool: "
                "liquidity_by_entry_offset (the gate's "
                "phantom-fill-bias fix), theoretical_fallback_rate "
                "(per-symbol VWAP vs close fill mix — surfaces the "
                "hybrid VWAP coverage problem), vwap_vs_close_"
                "divergence (size of the correction VWAP would have "
                "applied where engine used close). Sample-capped at "
                f"{MAX_TRADES_SAMPLED:,} trades for very large sweeps."
            ),
            input_model=DataQualityInput,
            output_model=DataQualityOutput,
            impl=data_quality_impl,
        ),
    ]
