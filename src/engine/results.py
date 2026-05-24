"""Sweep results persistence + canonical schema.

Single source of truth for what columns end up in
``data/results/{name}_{run_id}.parquet`` and its companion
``data/results/{name}_{run_id}_skipped.parquet``. Phase-5 ranker and
Phase-6 UI read through this module so a schema change is one edit.

The skip-log companion file is new in Phase 4 — operators running a
7500-task sweep need a way to see "200 tasks dropped, reasons: 180×
MissingData, 20×NoLiquidStrike" without diffing row counts manually.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.config import RESULTS_DIR


# ============================================================
# Canonical columns
# ============================================================

# SPECS §2.5 results columns the price_trade kernel emits, plus the
# sweep-specific decorations the sweeper adds.
RESULTS_COLUMNS: tuple[str, ...] = (
    # Identity
    "run_id",
    "strategy",
    "symbol",
    "expiry",
    "entry_date",
    "exit_date",
    # Offsets (sweep-level)
    "entry_offset_td",
    "exit_offset_td",
    # Trade params
    "params_json",
    "legs_json",
    # P&L stack
    "gross_pnl",
    "costs",
    "costs_breakdown_json",
    "net_pnl",
    # Margin / ROI
    "margin_at_entry",
    "margin_breakdown_json",
    "roi_pct",
    "hold_trading_days",
    "roi_pct_annualized",
    # Underlying context
    "entry_spot",
    "exit_spot",
    "notional_at_entry",
)

# Skip-log columns — the parallel file recording cells that were tried
# but produced no result row (MissingData / NoLiquidStrike).
SKIPS_COLUMNS: tuple[str, ...] = (
    "run_id",
    "strategy",
    "symbol",
    "expiry",
    "entry_offset_td",
    "exit_offset_td",
    "skip_reason",
)


# ============================================================
# Empty-frame builders (preserve column schema on no-data sweeps)
# ============================================================

def empty_results_frame() -> pd.DataFrame:
    """Empty results frame WITH the canonical column schema. Downstream
    code that does ``df["roi_pct"].mean()`` won't KeyError on a no-row
    sweep — it just gets NaN. The reviewer flagged this on 185a9cb."""
    return pd.DataFrame({col: pd.Series(dtype=_inferred_dtype(col)) for col in RESULTS_COLUMNS})


def empty_skips_frame() -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series(dtype=_inferred_dtype(col)) for col in SKIPS_COLUMNS})


def _inferred_dtype(col: str) -> str:
    """Best-effort dtype per column name. Datetime cols become
    datetime64[us] (matches §2.0 convention); known-int cols become
    int64; string-like cols become StringDtype (matches §2.1 — upstream
    loaders emit pd.StringDtype, so empty frames should too to avoid
    object/string mixing on pd.concat); everything else float64.

    The StringDtype mapping closes the 1a5cf01 review flag: previously
    text columns defaulted to ``"object"``, which meant a concat of
    an empty results frame with a real-data frame could yield either
    object or string dtype depending on pandas version. Consistency-
    over-version-drift is the right discipline."""
    if col in ("expiry", "entry_date", "exit_date"):
        return "datetime64[us]"
    if col in ("entry_offset_td", "exit_offset_td", "hold_trading_days"):
        return "int64"
    if col in ("gross_pnl", "costs", "net_pnl", "margin_at_entry",
               "roi_pct", "roi_pct_annualized", "entry_spot", "exit_spot",
               "notional_at_entry"):
        return "float64"
    # Text columns — strategy, symbol, run_id, params_json, legs_json,
    # *_breakdown_json, skip_reason. All pd.StringDtype upstream.
    return "string"


# ============================================================
# Path helpers
# ============================================================

def results_path(run_id: str, name: str = "sweep") -> Path:
    return RESULTS_DIR / f"{name}_{run_id}.parquet"


def skips_path(run_id: str, name: str = "sweep") -> Path:
    return RESULTS_DIR / f"{name}_{run_id}_skipped.parquet"


# ============================================================
# Write / read with schema validation
# ============================================================

def canonical_column_order(df: pd.DataFrame) -> pd.DataFrame:
    """Reorder columns to RESULTS_COLUMNS first, extras (forward-compat)
    at the tail, AND coerce date-typed columns (``expiry``, ``entry_date``,
    ``exit_date``) to ``datetime64[us]`` per SPECS §2.0.

    Pure — returns a new frame. Used both by ``write_results`` before
    persist AND by the sweeper so the in-memory frame it returns has
    the same shape as the parquet it writes (re-reading the file yields
    ``assert_frame_equal``-clean output).

    Why the dtype coercion: ``price_trade`` returns trade dates as
    Python ``datetime.date`` objects; concatenating them via
    ``pd.DataFrame(rows)`` produces object-typed columns that round-trip
    through parquet as object, so a filter like
    ``df["expiry"] == pd.Timestamp("2024-01-25")`` silently returns no
    matches. Normalizing here is the single fix for both the in-memory
    frame and the persisted parquet."""
    reordered = df[
        list(RESULTS_COLUMNS) + [c for c in df.columns if c not in RESULTS_COLUMNS]
    ].copy()
    for col in ("expiry", "entry_date", "exit_date"):
        if col in reordered.columns and reordered[col].dtype == object:
            reordered[col] = pd.to_datetime(reordered[col]).astype("datetime64[us]")
    return reordered


def write_results(df: pd.DataFrame, run_id: str, name: str = "sweep") -> Path:
    """Persist results frame to its canonical path. Asserts the frame
    has at least the RESULTS_COLUMNS schema before writing — better to
    fail loud on the writer than to corrupt the on-disk format."""
    missing = set(RESULTS_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(
            f"results frame missing required columns: {sorted(missing)}; "
            f"got {sorted(df.columns)}"
        )
    path = results_path(run_id, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical_column_order(df).to_parquet(path, index=False)
    return path


def write_skips(skip_rows: list[dict], run_id: str, name: str = "sweep") -> Path | None:
    """Persist the skip log as a companion parquet. Returns None if no
    skips (no point writing an empty file)."""
    if not skip_rows:
        return None
    df = pd.DataFrame(skip_rows)
    missing = set(SKIPS_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(
            f"skips frame missing required columns: {sorted(missing)}"
        )
    path = skips_path(run_id, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    df_ordered = df[list(SKIPS_COLUMNS)]
    df_ordered.to_parquet(path, index=False)
    return path


def read_results(run_id: str, name: str = "sweep") -> pd.DataFrame:
    """Read a results parquet + validate schema. Raises ValueError if a
    column the schema requires is missing (e.g. an older parquet from
    before a column was added — loud failure beats silent NaN
    propagation in Phase-5 ranker)."""
    path = results_path(run_id, name)
    if not path.exists():
        raise FileNotFoundError(f"no results parquet at {path}")
    df = pd.read_parquet(path)
    missing = set(RESULTS_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(
            f"results parquet at {path} is missing columns "
            f"{sorted(missing)} — was it written under an older schema?"
        )
    return df


def read_skips(run_id: str, name: str = "sweep") -> pd.DataFrame:
    """Read the skip-log companion parquet. Returns empty_skips_frame()
    if no companion file exists (= zero skips)."""
    path = skips_path(run_id, name)
    if not path.exists():
        return empty_skips_frame()
    return pd.read_parquet(path)
