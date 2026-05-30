"""MCP tools — sweep query entry points (2 of the 4 sub-arc-3.3 tools).

  - list_runs()                                   : discover available sweep parquets
  - query_sweep(run_id, filters?, columns?, ...)  : filtered query against one run

``cell_summary`` and ``heatmap`` are the analytical surfaces; they land
in subsequent sub-arc-3.3 commits (feat(p8.mcp.cell_summary),
feat(p8.mcp.heatmap)).

list_runs reads only parquet file-level metadata + the engine-version
stamp the pre-arc commit chore(p8.engine.version_stamp) wrote — does
NOT load any data. Returns one row per discovered parquet so a
consumer Claude can pick which run to query.

query_sweep is the generic filtered access tool. It accepts a flat
filter dict where each entry is one of:
  - "column": value                  → equality match
  - "column": [value1, value2, ...]  → IN match
  - "column__gte" / "__lte" / "__gt" / "__lt": value  → range comparison

Output is hard-capped at MAX_ROWS_PER_RESPONSE (10K). The cap fires
with an explicit caveat so a consumer can't accidentally treat a
truncated query as exhaustive.

The pricing-arc-applied caveat ALSO surfaces here: if the requested
run lacks the engine_version stamp (legacy pre-arc parquet), every
query_sweep response carries the phantom-fill-bias warning.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import pyarrow.parquet as pq
from pydantic import BaseModel, Field

from src.config import RESULTS_DIR
from src.engine.results import (
    ENGINE_VERSION,
    read_results,
    read_run_metadata,
    results_path,
)
from src.mcp._models import (
    PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT,
    CaveatedResponse,
    ToolEntry,
)


# Hard cap on returned rows — reuse the spot_options constant indirectly
# via a separate symbol so the two surfaces can diverge later if needed.
MAX_QUERY_SWEEP_ROWS = 10_000


# ============================================================
# list_runs
# ============================================================

class RunInfo(BaseModel):
    run_id: str
    mtime_utc: datetime = Field(
        ...,
        description=(
            "Last-modified timestamp of the parquet on disk (UTC). "
            "Useful for picking the most recent run when multiple "
            "match the same grid."
        ),
    )
    n_rows: int = Field(
        ...,
        description=(
            "Total cell count in the sweep parquet. Read from "
            "parquet file metadata; does NOT load the data."
        ),
    )
    size_bytes: int
    engine_version: str | None = Field(
        ...,
        description=(
            "Value of the ``engine_version`` stamp from the parquet's "
            "KV metadata (e.g. 'p7.pricing_arc'). ``None`` for legacy "
            "parquets cached before chore(p8.engine.version_stamp) "
            "landed — those are pre-pricing-arc data with the phantom-"
            "fill bias likely present."
        ),
    )
    pricing_arc_applied: bool = Field(
        ...,
        description=(
            "True iff engine_version is set AND matches the current "
            "ENGINE_VERSION ('p7.pricing_arc'). Use this to identify "
            "which runs have the IlliquidLegError gate + VWAP fill "
            "applied, vs. which are pre-arc data."
        ),
    )


class ListRunsInput(BaseModel):
    """list_runs takes no arguments."""


class ListRunsOutput(CaveatedResponse):
    runs: list[RunInfo]
    n_runs: int


def list_runs_impl(inp: ListRunsInput) -> ListRunsOutput:
    runs: list[RunInfo] = []
    if not RESULTS_DIR.exists():
        return ListRunsOutput(runs=[], n_runs=0, caveats=[])

    for p in sorted(RESULTS_DIR.glob("sweep_*.parquet")):
        # Skip the companion *_skipped.parquet files — those aren't
        # sweep results, they're the skip-log siblings.
        if p.stem.endswith("_skipped"):
            continue
        run_id = p.stem[len("sweep_"):]
        stat = p.stat()
        try:
            meta = pq.read_metadata(p)
            n_rows = meta.num_rows
        except Exception:
            # Defensive — corrupted parquet shouldn't kill the whole
            # tool. Surface the run with n_rows=0 + a per-run caveat
            # via the top-level caveats list.
            n_rows = 0
        stamp = read_run_metadata(run_id)
        engine_version = stamp.get("engine_version")
        runs.append(RunInfo(
            run_id=run_id,
            mtime_utc=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            n_rows=n_rows,
            size_bytes=stat.st_size,
            engine_version=engine_version,
            pricing_arc_applied=(engine_version == ENGINE_VERSION),
        ))

    caveats: list[str] = []
    n_legacy = sum(1 for r in runs if not r.pricing_arc_applied)
    if n_legacy > 0:
        caveats.append(
            f"{n_legacy} of {len(runs)} run(s) lack the p7.pricing_arc "
            f"engine_version stamp. " + PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT
        )
    return ListRunsOutput(runs=runs, n_runs=len(runs), caveats=caveats)


# ============================================================
# query_sweep
# ============================================================

class QuerySweepInput(BaseModel):
    run_id: str = Field(
        ...,
        description=(
            "The run_id of the sweep parquet to query. Use "
            "``list_runs`` to discover available ones."
        ),
    )
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Flat filter dict. Keys are column names (or column with a "
            "Django-style suffix: __gte, __lte, __gt, __lt for range "
            "comparisons). Values are either scalars (equality) or "
            "lists (IN). Example: {'strategy': 'short_straddle', "
            "'symbol': ['RELIANCE', 'TCS'], 'entry_offset_td__gte': 10}."
        ),
    )
    columns: list[str] | None = Field(
        default=None,
        description=(
            "Optional subset of columns to return. None = all columns "
            "in the results schema. Keeping the column list tight helps "
            "the consumer Claude reason about the response without "
            "blowing context on legs_json / costs_breakdown_json blobs."
        ),
    )
    sort_by: str | None = Field(
        default=None,
        description=(
            "Optional column to sort by. Prefix with '-' for descending "
            "(e.g. '-net_pnl' returns biggest-P&L cells first)."
        ),
    )
    limit: int = Field(
        default=MAX_QUERY_SWEEP_ROWS,
        ge=1, le=MAX_QUERY_SWEEP_ROWS,
        description=(
            f"Max rows to return (default + hard cap = "
            f"{MAX_QUERY_SWEEP_ROWS}). Truncation surfaces in caveats."
        ),
    )


class QuerySweepOutput(CaveatedResponse):
    run_id: str
    n_rows: int
    rows: list[dict[str, Any]] = Field(
        ...,
        description=(
            "Heterogeneous trade rows. Schema depends on the ``columns`` "
            "parameter (default = full RESULTS_COLUMNS). JSON-friendly "
            "types only (dates as ISO strings, no Timestamps)."
        ),
    )


_COMPARISON_OPS = {
    "__gte": lambda s, v: s >= v,
    "__lte": lambda s, v: s <= v,
    "__gt":  lambda s, v: s >  v,
    "__lt":  lambda s, v: s <  v,
}


def _coerce_to_column_dtype(value: Any, column: str, dtype: Any) -> Any:
    """Pre-validate a filter value against the target column's dtype.
    Per reviewer Grill #1 on bacf5cf — without this, a typo like
    ``{"entry_offset_td__gte": "ten"}`` would raise an opaque pandas
    TypeError inside ``__ge__`` rather than a clean consumer-readable
    MCP tool error.

    Coerce-and-test is sufficient for the typical cases (str → int,
    str → float, str → date). When coercion fails, raise ValueError
    with the column name + dtype so the consumer Claude sees exactly
    what's wrong.
    """
    if value is None:
        return value
    # numeric types — handles int / float / Int64 / nullable
    if pd.api.types.is_numeric_dtype(dtype):
        try:
            return type(dtype.type(value))(value) if hasattr(dtype, 'type') else float(value)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"filter value {value!r} (type {type(value).__name__}) "
                f"not coercible to column {column!r}'s dtype {dtype}: {e}"
            )
    # datetime — accept ISO string or date / datetime instance
    if pd.api.types.is_datetime64_any_dtype(dtype):
        try:
            return pd.Timestamp(value)
        except Exception as e:
            raise ValueError(
                f"filter value {value!r} not coercible to datetime "
                f"for column {column!r}: {e}"
            )
    # string / object — let through unchanged
    return value


def _apply_filters(df: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    """Apply the flat filter dict to df, returning the filtered frame.
    Unknown columns or invalid suffixes raise ValueError so a typo at
    the consumer side surfaces immediately rather than silently
    returning the unfiltered frame. Per fix(bacf5cf #1), filter
    values are also pre-validated against the target column's dtype
    so a string-vs-int typo surfaces as a clean MCP tool error
    rather than an opaque pandas exception."""
    out = df
    for key, value in filters.items():
        matched_op = None
        column = key
        for suffix, op in _COMPARISON_OPS.items():
            if key.endswith(suffix):
                column = key[: -len(suffix)]
                matched_op = op
                break
        if column not in df.columns:
            raise ValueError(
                f"filter key {key!r} references unknown column {column!r}. "
                f"Available: {sorted(df.columns)}"
            )
        dtype = df[column].dtype
        if isinstance(value, list):
            # IN-list: coerce each element separately.
            coerced_values = [
                _coerce_to_column_dtype(v, column, dtype) for v in value
            ]
            out = out[out[column].isin(coerced_values)]
        else:
            coerced = _coerce_to_column_dtype(value, column, dtype)
            if matched_op is not None:
                out = out[matched_op(out[column], coerced)]
            else:
                out = out[out[column] == coerced]
    return out


def _to_json_friendly(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert pd.Timestamp / numpy scalar types in row dicts to plain
    Python types so the JSON serialization downstream can't trip on
    them. pd.Timestamp → ISO string, numpy ints/floats → native."""
    out: list[dict[str, Any]] = []
    for r in rows:
        clean: dict[str, Any] = {}
        for k, v in r.items():
            if isinstance(v, pd.Timestamp):
                clean[k] = v.date().isoformat() if v.normalize() == v else v.isoformat()
            elif pd.isna(v):
                clean[k] = None
            elif hasattr(v, "item"):  # numpy scalars
                clean[k] = v.item()
            else:
                clean[k] = v
        out.append(clean)
    return out


def query_sweep_impl(inp: QuerySweepInput) -> QuerySweepOutput:
    df = read_results(inp.run_id)
    if inp.filters:
        df = _apply_filters(df, inp.filters)
    if inp.sort_by is not None:
        ascending = True
        col = inp.sort_by
        if col.startswith("-"):
            ascending = False
            col = col[1:]
        if col not in df.columns:
            raise ValueError(
                f"sort_by {inp.sort_by!r} references unknown column "
                f"{col!r}"
            )
        df = df.sort_values(col, ascending=ascending)

    caveats: list[str] = []
    n_post_filter = len(df)
    if n_post_filter > inp.limit:
        df = df.head(inp.limit)
        caveats.append(
            f"Response truncated to {inp.limit} rows out of "
            f"{n_post_filter} matched. Narrow the filter or page via "
            f"sort_by + a range-bound filter to retrieve the rest."
        )
    if inp.columns is not None:
        missing = [c for c in inp.columns if c not in df.columns]
        if missing:
            raise ValueError(
                f"columns parameter references unknown columns: {missing}. "
                f"Available: {sorted(df.columns)}"
            )
        df = df[inp.columns]

    # Pricing-arc-applied caveat — surface at the per-call level so a
    # query against a pre-arc run flags the phantom-fill bias.
    stamp = read_run_metadata(inp.run_id)
    if stamp.get("engine_version") != ENGINE_VERSION:
        caveats.append(PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT)

    rows = _to_json_friendly(df.to_dict(orient="records"))
    return QuerySweepOutput(
        run_id=inp.run_id,
        n_rows=len(rows),
        rows=rows,
        caveats=caveats,
    )


# ============================================================
# Registry export
# ============================================================

def register_sweep_query_tools() -> list[ToolEntry]:
    """Return the 2 sub-arc-3.3 entry-point tools. ``cell_summary``
    and ``heatmap`` ship in subsequent commits."""
    return [
        ToolEntry(
            name="list_runs",
            description=(
                "Discover available sweep parquets under data/results/. "
                "Returns one entry per file with engine_version stamp "
                "and pricing_arc_applied flag — pick the right run "
                "before calling query_sweep / cell_summary / heatmap."
            ),
            input_model=ListRunsInput,
            output_model=ListRunsOutput,
            impl=list_runs_impl,
        ),
        ToolEntry(
            name="query_sweep",
            description=(
                "Filtered query against one sweep parquet's per-trade "
                "rows. Supports equality / IN / range filters via a "
                f"flat dict; capped at {MAX_QUERY_SWEEP_ROWS} rows per "
                "call. The response carries an explicit pre-pricing-arc "
                "caveat when the queried run lacks the engine stamp."
            ),
            input_model=QuerySweepInput,
            output_model=QuerySweepOutput,
            impl=query_sweep_impl,
        ),
    ]
