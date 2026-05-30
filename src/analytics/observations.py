"""Auto-detect structural observations on a cell's per-trade stats.

The dashboard whispers ("mean << median by 37 pts — heavy tail") so the
analyst doesn't have to manually notice properties the data already
contains. Matches the design/Complete mockup's inline yellow-callout
pattern: any structural property the system can detect automatically
surfaces as a one-liner in the card where the property lives.

Pure function, no I/O. Returns a list of strings (0-3 typical); caller
renders via st.warning or st.info."""
from __future__ import annotations

import pandas as pd


# Threshold defaults — defended in the docstrings on each detector.
# Exposed as module constants so future tuning lands in one place.
#
# Per p7.expiry_roi: thresholds are calibrated against PER-TRADE ROI
# (not annualized). The earlier 20-pt heavy-tail threshold was tuned
# for annualized %; under per-trade scale (~1/12 of annualized for
# typical monthly holds) a 20-pt gap would essentially never fire.
# Dropped to 3.0 pts so the detector remains meaningfully responsive
# to skew on per-trade ROI distributions.
HEAVY_TAIL_MEAN_MINUS_MEDIAN_PTS = 3.0
OUTLIER_CARRY_PNL_SHARE = 0.50           # scale-invariant (ratio of |P&L|)
INSTABILITY_STD_TO_MEDIAN_RATIO = 3.0    # scale-invariant (ratio)


def interpret_cell_stats(rows: pd.DataFrame) -> list[str]:
    """Inspect a cell's per-trade frame; return any structural
    observations the analyst would want to see immediately.

    Args:
        rows: per-trade frame for ONE cell (filtered to one strategy
            × symbol × entry_offset_td × exit_offset_td). Requires
            columns: ``roi_pct_annualized``, ``net_pnl``. Empty frame
            → returns ``[]`` (no observations possible).

    Returns:
        List of human-readable observation strings, each prefixed with
        the structural finding ("mean < median", "single trade carries",
        "std > 3× |median|", …). Ordered by load-bearingness: tail-shape
        first, outlier-carry second, instability third. Up to 3 strings;
        empty list when nothing notable.

    Detectors (each implemented as a guard inside this function so the
    public surface stays tiny — one input, one output):

      1. Heavy-tail signal: ``mean − median ≥ HEAVY_TAIL_MEAN_MINUS_MEDIAN_PTS``
         (default 3.0 pts; calibrated for PER-TRADE ROI scale per
         p7.expiry_roi). For short-vol strategies, mean >> median means
         winners cluster near the mode but losers are deep — i.e. tail
         risk hidden under a benign median. The threshold is in ROI-pct
         points, not a ratio, because the absolute gap is the operator's
         intuition: "the average expected value is N pts higher than the
         typical outcome — that gap is the tail."

      2. Outlier-carry: a single trade's net_pnl is ≥ OUTLIER_CARRY_PNL_
         SHARE of the cell's TOTAL net_pnl. Threshold default 0.50 — one
         trade carrying half the strategy is "this one expiry made the
         whole strategy look good; pull it and reassess."

      3. Instability: ``std(roi_pct_annualized) > INSTABILITY_STD_TO_
         MEDIAN_RATIO × |median|``. Default 3×. Means the dispersion is
         larger than 3× the typical-magnitude move; the strategy's
         per-trade outcomes are wildly unstable relative to the median.

    Each detector logs ONLY when it fires. The dashboard surfaces these
    as inline callouts; an empty list means "no structural surprises
    detected" — silent is honest here, since false positives waste
    operator attention.
    """
    if len(rows) == 0:
        return []
    if not {"roi_pct", "net_pnl"}.issubset(rows.columns):
        return []

    # Per-trade ROI (NOT annualized). p7.expiry_roi recalibrated the
    # HEAVY_TAIL_MEAN_MINUS_MEDIAN_PTS threshold from 20 → 3 to match
    # per-trade scale; reading roi_pct_annualized with a per-trade
    # threshold was a silent miscalibration that fired the heavy-tail
    # detector on most cells (annualized gaps are ~12× larger by the
    # multiplier in _annualize_roi). Surfaced by reviewer in the
    # 3264f37 cell_summary review as a carry-over miss from 33f19ae.
    roi = rows["roi_pct"].dropna()
    pnl = rows["net_pnl"].dropna()
    out: list[str] = []

    # 1. Heavy-tail (mean >> median).
    if len(roi) >= 2:
        med = float(roi.median())
        mean = float(roi.mean())
        gap = mean - med
        if gap >= HEAVY_TAIL_MEAN_MINUS_MEDIAN_PTS:
            out.append(
                f"mean > median by {gap:.0f} pts — heavy upside tail "
                f"(rare big winners pull the mean above the typical "
                f"outcome; SPECS §6b.3 caveat applies)."
            )
        elif gap <= -HEAVY_TAIL_MEAN_MINUS_MEDIAN_PTS:
            out.append(
                f"mean < median by {abs(gap):.0f} pts — heavy downside "
                f"tail (rare big losers pull the mean below the typical "
                f"outcome; SPECS §6b.3 caveat applies)."
            )

    # 2. Outlier-carry on absolute P&L.
    if len(pnl) >= 2:
        total = float(pnl.sum())
        if abs(total) > 0:
            max_abs = float(pnl.abs().max())
            share = max_abs / abs(total)
            if share >= OUTLIER_CARRY_PNL_SHARE:
                out.append(
                    f"one trade carries {share * 100:.0f}% of the cell's "
                    f"|net P&L| — pull it and reassess whether the "
                    f"strategy stands without that single expiry."
                )

    # 3. Instability — dispersion >> typical magnitude.
    if len(roi) >= 2:
        med = float(roi.median())
        std = float(roi.std(ddof=0))
        if abs(med) > 0.01 and std > INSTABILITY_STD_TO_MEDIAN_RATIO * abs(med):
            ratio = std / abs(med)
            out.append(
                f"std/|median| ratio {ratio:.1f}× — dispersion wildly "
                f"exceeds typical move; per-trade outcomes are unstable "
                f"relative to the headline ROI."
            )

    return out
