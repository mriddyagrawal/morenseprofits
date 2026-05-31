# MCP server — tool catalog

`src/mcp/` exposes the morenseprofits dataset as an MCP server so any Claude
instance (or other MCP client) can run its own research against the local
cache + sweep parquets without going through the Streamlit dashboard.

The server is **read-only and cache-first** — no NSE network calls, no writes
to the results store. Tools that need fresh NSE data raise an error rather
than fetching.

---

## Running it

```bash
.venv/bin/python -m src.mcp
```

Speaks JSON-RPC over stdio (the MCP SDK default transport). Claude Code
registers it through `~/.claude/mcp.json` (global) or `.mcp.json`
(project-local) — see `DESIGN/PHASE_8_MCP.md` §2 for the canonical
config block. For one-off testing the same `python -m src.mcp` command
works.

Tools live in `src/mcp/`, one module per sub-arc, registered into one
catalog by `build_server()` in `src/mcp/server.py`. Each tool has a
Pydantic input model and a Pydantic output model — the server's
`call_tool` handler does dict-from-MCP → input model parsing and
output model → JSON serialization, so type-safety is enforced at
both edges.

**16 tools, grouped by purpose below.** Required params marked ✓.

---

## 1. Discovery / metadata

### `list_runs`

> Enumerate sweep run_ids available in `data/results/`. Use this first
> to discover which run_id to pass to the sweep-querying tools.

No parameters.

### `list_strategies`

> Names + display strike rules for every strategy registered in
> `src.strategies.registry`. Mirrors what the Heatmap tab's selector
> caption shows.

No parameters.

### `list_universe`

> Returns the project's stock universe (Nifty-50-derived blue chips +
> PNB + BHEL).

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `as_of` | string \| null | | `None` | Date to query the universe as-of. v1 returns the same mid-2024 snapshot regardless. |

### `expiries_for`

> Monthly F&O expiries between two dates for a given symbol, sourced
> from `expiry_calendar.monthly_expiries`.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `symbol` | string | ✓ | | NSE trading symbol (uppercase, no exchange suffix). Examples: `RELIANCE`, `BAJAJ-AUTO`, `M&M`. |
| `from_date` | string | ✓ | | Inclusive lower bound (ISO date). |
| `to_date` | string | ✓ | | Inclusive upper bound (ISO date). |

---

## 2. Raw market-data passthrough

### `get_spot_series`

> Spot OHLC for a symbol over a date window. Reads `data/cache/spot/`.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `symbol` | string | ✓ | | Uppercased internally. |
| `from_date` | string | ✓ | | Inclusive lower bound. |
| `to_date` | string | ✓ | | Inclusive upper bound. |

### `get_option_series`

> Full lifetime (or a window of it) for a specific contract. Reads
> `data/cache/options/{SYMBOL}/{EXPIRY:yyyymmdd}/{STRIKE}-{CE|PE}.parquet`.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `symbol` | string | ✓ | | |
| `expiry` | string | ✓ | | ISO date. |
| `strike` | number | ✓ | | Whole-rupee NSE strike. |
| `option_type` | string | ✓ | | `"CE"` or `"PE"`. |
| `from_date` | string \| null | | `None` | Default = `expiry - 120 days` (full contract lifetime). |
| `to_date` | string \| null | | `None` | Default = `expiry`. |

### `get_options_chain`

> Single-day options chain for a symbol (all strikes + types) from the
> F&O bhavcopy for `on_date`.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `symbol` | string | ✓ | | |
| `on_date` | string | ✓ | | Trading date for the snapshot. |
| `expiry` | string \| null | | `None` | Optional filter — only return rows for this contract expiry. `None` = all expiries traded that day. |

---

## 3. Sweep result querying

### `query_sweep`

> SQL-ish flat-filter query over a sweep parquet. The workhorse for
> "give me the rows that match X."

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `run_id` | string | ✓ | | The run_id of the sweep parquet to query. Use `list_runs` to discover. |
| `filters` | object | ✓ | | Flat filter dict. Keys are column names; suffix with `__gte`, `__lte`, `__gt`, `__lt` for range comparisons. |
| `columns` | array[string] \| null | | `None` | Subset of columns to return. `None` = all. |
| `sort_by` | string \| null | | `None` | Column to sort by. Prefix with `-` for descending (`-net_pnl` returns biggest P&L first). |
| `limit` | integer | | `10000` | Max rows. Hard cap = 10,000. Truncation surfaces in `caveats`. |

### `cell_summary`

> The analyst's heaviest single-cell tool: stats + 95% bootstrap CI on
> median ROI + auto-detected structural observations + per-trade list.
> Pre-pricing-arc caveat fires when the run lacks the `engine_version`
> stamp.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `run_id` | string | ✓ | | |
| `strategy` | string | ✓ | | |
| `symbol` | string | ✓ | | |
| `entry_offset_td` | integer | ✓ | | |
| `exit_offset_td` | integer | ✓ | | |
| `include_per_trade` | boolean | | `True` | If False, `per_trade` is omitted. Use for lightweight stat-only queries. |

### `heatmap`

> Pivot a sweep parquet into a 2D (entry_offset_td × exit_offset_td)
> grid, masked at `min_n`. Matches what the dashboard renders.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `run_id` | string | ✓ | | |
| `strategy` | string | ✓ | | |
| `symbol` | string | ✓ | | |
| `value_col` | string | | `"roi_pct"` | Per-trade value to aggregate. Also accepts `"cvar_5"` (head-vs-tail diagnostic). |
| `agg_fn` | string | | `"median"` | `"median"` (robust, default) or `"mean"` (sensitive to tail). |
| `min_n` | integer | | `5` | Cells with n < min_n are masked. Matches dashboard default. |

### `skip_summary`

> Bucket the sweep's `*_skipped.parquet` by a column and surface
> example rows. The diagnostic for "what kinds of failures occurred."

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `run_id` | string | ✓ | | |
| `group_by` | string | | `"reason"` | `"reason"` (default) / `"strategy"` / `"symbol"` / etc. |
| `max_examples` | integer | | `3` | Examples per group. Hard cap 20. Set to 0 for counts-only. |

### `compare_cells`

> Side-by-side comparison of 2-4 cells: per-cell stats + raw deltas
> vs the first (baseline) cell + per-cell ROI distributions.
>
> **LOAD-BEARING constraint**: NO p-values or significance-test
> machinery. Sample sizes too small for that to be honest; raw deltas
> are directional signals only. (Same constraint as the dashboard's
> Compare-cells mode.)

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `run_id` | string | ✓ | | |
| `cell_keys` | array[CompareCellKey] | ✓ | | 2-4 cells. The first is the baseline; `diff_vs_baseline` has one entry per non-first cell. |

### `data_quality`

> Three diagnostic dimensions in one tool:
> - `liquidity_by_entry_offset` — the gate's phantom-fill-bias fix
> - `theoretical_fallback_rate` — per-symbol VWAP vs close fill mix
> - `vwap_vs_close_divergence` — size of the correction VWAP would have applied
>
> Sample-capped at 200,000 trades for large sweeps.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `run_id` | string | ✓ | | |
| `dimension` | string | | `"liquidity_by_entry_offset"` | Which diagnostic to surface. |

### `sweep_windows`

> Replay a small (entry × exit) grid across N expiries against the
> local cache. Returns one stat block per (entry, exit) pair + per-cell
> skip breakdown. **Hard-capped at 500 total trades** — for wider
> grids, run `scripts/p7_wide_sweep.py` then query via `cell_summary` /
> `heatmap`.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `strategy` | string | ✓ | | |
| `symbol` | string | ✓ | | |
| `expiry_from` | string | ✓ | | Inclusive lower bound for expiry sampling. |
| `expiry_to` | string | ✓ | | Inclusive upper bound. |
| `entry_offset_min` | integer | ✓ | | Inclusive lower bound for entry offset (trading days). |
| `entry_offset_max` | integer | ✓ | | Inclusive upper bound. |
| `exit_offset_min` | integer | ✓ | | Inclusive lower bound for exit offset. |
| `exit_offset_max` | integer | ✓ | | Inclusive upper bound. |
| `params` | object \| null | | `None` | Optional strategy-specific overrides. |

---

## 4. Compute helpers

### `backtest_one`

> Replay a single trade against the local cache. Returns full per-leg
> breakdown including VWAP-vs-close fill-source classification + costs
> + margin + ROI. Cache-only (no NSE calls); failures surface as
> `gate_status` rather than exceptions.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `strategy` | string | ✓ | | Name from `list_strategies` output. |
| `symbol` | string | ✓ | | |
| `expiry` | string | ✓ | | ISO date. |
| `entry_date` | string | ✓ | | |
| `exit_date` | string | ✓ | | |
| `params` | object \| null | | `None` | Strategy-specific overrides, e.g. `{"strike_offset_pct": 0.03}` for a strangle. |

### `bootstrap_ci`

> Pure-compute percentile-bootstrap CI on a consumer-provided values
> array. Useful for honest uncertainty bands on median / mean of
> arbitrary numeric inputs. Same machinery as the dashboard's Median
> Hero card and `cell_summary`'s `bootstrap_ci_median_roi` field.

| Param | Type | Required | Default | Notes |
|---|---|---|---|---|
| `values` | array[number] | ✓ | | 1-D numeric values to bootstrap. Capped at 5,000 entries. |
| `statistic` | string | | `"median"` | `"median"` (default, matches Median Hero) or `"mean"` (sensitive to tail extremes). |
| `B` | integer | | `1000` | Number of bootstrap resamples. |
| `alpha` | number | | `0.05` | Significance level. `alpha=0.05` → 95% CI. |
| `seed` | integer | | `0` | RNG seed. Same `(values, B, seed)` → byte-identical `(lo, hi)`. |

---

## Cross-cutting contracts

- **Cache-only.** No tool touches the NSE network. Missing cache data
  surfaces as `MissingDataError` / `OfflineCacheMiss` in the caveats
  field, never as a silent fetch.
- **No p-values, ever.** `compare_cells` and any future
  comparison-style tool MUST NOT emit statistical-significance copy.
  Sample sizes are too small to be honest about it.
- **Pre-pricing-arc data is flagged.** Sweep runs that predate the
  `p7.pricing_arc` engine version (no `engine_version` metadata stamp)
  raise a caveat on `cell_summary`, `heatmap`, etc. — the operator
  needs to know the result might be carrying phantom-fill bias.
- **`data_quality` is ENTRY-side only.** All three diagnostics
  (`liquidity_by_entry_offset`, `theoretical_fallback_rate`,
  `vwap_vs_close_divergence`) classify and measure ENTRY-leg fills
  only — exit-leg fill quality is NOT covered. Operator interpreting
  any of these dimensions must treat them as entry-fill diagnostics,
  not whole-trade diagnostics.
- **`compare_cells.roi_distribution` keeps the LOWEST N by ROI.**
  When a cell's distribution exceeds the per-cell row cap, the right
  tail is dropped (not a random sample) — consistent with the tool's
  tail-risk emphasis (CVaR-5%). On truncation, a free-form caveat
  fires whose text begins `"At least one cell's ROI distribution was
  truncated to ..."` (substring-match for `"ROI distribution was
  truncated"` — there is no named caveat key). Operators charting
  these distributions should treat the right edge as a lower bound on
  the best trades, not a full picture.
- **Every tool's output has a `caveats` field** — a free-form list of
  strings surfacing data-quality issues, truncations, and known-bug
  exceptions. Treat empty caveats as the explicit "no concerns"
  signal; never omit the field even when empty.
- **Inputs validated by Pydantic.** Any tool returning a structurally
  invalid input gets a 422-equivalent error before the impl runs.

---

## Where the code lives

| Module | Tools |
|---|---|
| `src/mcp/universe.py` | `list_universe`, `list_strategies`, `expiries_for` |
| `src/mcp/spot_options.py` | `get_spot_series`, `get_option_series`, `get_options_chain` |
| `src/mcp/sweep_query.py` | `list_runs`, `query_sweep` |
| `src/mcp/cell_summary.py` | `cell_summary` |
| `src/mcp/heatmap.py` | `heatmap` |
| `src/mcp/skip_summary.py` | `skip_summary` |
| `src/mcp/compare_cells.py` | `compare_cells` |
| `src/mcp/data_quality.py` | `data_quality` |
| `src/mcp/sweep_windows.py` | `sweep_windows` |
| `src/mcp/backtest_one.py` | `backtest_one` |
| `src/mcp/bootstrap_ci.py` | `bootstrap_ci` |

`src/mcp/server.py` aggregates them via `_collect_tool_entries()` →
single `list_tools` + `call_tool` pair (the SDK's canonical pattern
for multi-sub-arc tool catalogs).

To regenerate this file's tool tables from the live registry:

```bash
.venv/bin/python -c "
from src.mcp.server import _collect_tool_entries
for n, e in sorted(_collect_tool_entries().items()):
    print(n, e.description)
"
```
