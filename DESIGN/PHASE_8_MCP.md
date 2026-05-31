# Phase 8 — MCP server contract

Authoritative reference for the morenseprofits MCP (Model Context
Protocol) server. The server exposes the project's read-only analytical
surface to any MCP-capable agent (Claude Code is the v1 client) over
stdio.

Closes the Phase 8 MCP arc per [BUILDER_CONSULTATION.md](../BUILDER_CONSULTATION.md)
(commit `513f88a`). The 16-tool catalog is frozen at v1.

> **Scope reminder.** This server is READ-ONLY. It surfaces existing
> sweep results + cached time-series; it does NOT run new sweeps, write
> to disk, or trigger any data fetch. New sweeps are still operator-
> initiated via `scripts/`. Trading actions land in Phase 9 (paper) and
> Phase 10 (live) as separate surfaces — those phases will add MUTATING
> tools with their own approval gates.

---

## 1. Transport

- **stdio only.** No HTTP, no socket. Claude Code's MCP-config registers
  the server as a stdio subprocess; the SDK handles JSON-RPC framing
  over stdin/stdout.
- **Entry point.** `python -m src.mcp` invokes
  [src/mcp/\_\_main\_\_.py](../src/mcp/__main__.py), which constructs
  the server via `build_server()` and runs it under
  `mcp.server.stdio.stdio_server`.
- **Session lifecycle.** One session = one stdio subprocess. The
  server exits when Claude Code closes the streams.

## 2. Operator-side configuration

Add the server to Claude Code's MCP config (`~/.claude/mcp.json` or
project-local `.mcp.json`):

```json
{
  "mcpServers": {
    "morenseprofits": {
      "command": "/Users/mriddy/Documents/GitHub/morenseprofits/.venv/bin/python",
      "args": ["-m", "src.mcp"],
      "cwd": "/Users/mriddy/Documents/GitHub/morenseprofits"
    }
  }
}
```

After Claude Code reloads, the 16 tools appear in the tool catalog
under the `morenseprofits` server name. Each tool's name is
unprefixed in the JSON-RPC layer (Claude Code adds the
`morenseprofits__` prefix when surfacing them to the model).

`cwd` is required because the tool implementations import from
`src.*` and read parquet data from `data/results/`. Adjust both
absolute paths to match the operator's clone.

## 3. The 16-tool catalog

The full catalog is pinned in
[tests/test_mcp_bootstrap_ci.py::test_server_registry_now_exposes_bootstrap_ci_and_all_16_tools](../tests/test_mcp_bootstrap_ci.py)
— a LOAD-BEARING test that fails if a future commit adds, removes,
or renames a tool without updating the expected set. See §6 below
for how the tripwire works.

| Sub-arc | Tool | One-liner |
|---|---|---|
| 3.1 universe | `list_universe` | Enumerate the 50-symbol universe + per-symbol coverage. |
| 3.1 universe | `expiries_for` | Cached expiries for one symbol over a date range. |
| 3.1 universe | `list_strategies` | Strategy registry (names + parameter schemas). |
| 3.2 time-series | `get_spot_series` | Spot OHLCV for one symbol over a date range. |
| 3.2 time-series | `get_option_series` | Per-leg option series (one strike, one expiry, range). |
| 3.2 time-series | `get_options_chain` | Full chain (all strikes, one expiry, one date). |
| 3.3 sweep queries | `list_runs` | Sweep-run inventory + pre-arc detection. |
| 3.3 sweep queries | `query_sweep` | Filtered + paginated trade-level query against one run. |
| 3.3 sweep queries | `cell_summary` | Per-cell stats + per-trade list + bootstrap CI on the median. |
| 3.3 sweep queries | `heatmap` | Pivot table over a strategy×symbol grid for one metric. |
| 3.4 backtest replay | `backtest_one` | Re-run one (strategy, symbol, expiry, entry/exit) from cache. |
| 3.4 backtest replay | `sweep_windows` | Stat block across all entry/exit windows for one cell. |
| 3.5 diagnostics | `skip_summary` | Skip-by-reason breakdown for one sweep run. |
| 3.5 diagnostics | `data_quality` | Three diagnostics: liquidity-by-entry / VWAP-fallback / VWAP-vs-close divergence. |
| 3.6 research helpers | `compare_cells` | Side-by-side 2-4 cells: stats + raw deltas + ROI distributions. |
| 3.6 research helpers | `bootstrap_ci` | Pure-compute percentile-bootstrap CI on a consumer-supplied values array. |

Each tool's full input/output schema lives in its source file's
Pydantic models. Surface area is intentionally small (one tool per
analytical question) — composition happens at the consumer Claude's
prompt layer, not inside the server.

## 4. Cross-cutting policies

### 4.1 The caveats contract

Every aggregated tool response inherits from
[`CaveatedResponse`](../src/mcp/_models.py), which requires a
`caveats: list[str]` field. Missing-field accidents fire at Pydantic
validation time. Empty list is valid (no caveats for this input);
missing field is a schema bug.

**Cross-cutting reusable caveat constants** are defined once and
re-emitted verbatim by every tool that triggers them:

| Constant | Defined in | Triggers when |
|---|---|---|
| `PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT` | [src/mcp/_models.py](../src/mcp/_models.py) | Run was generated before the p7.pricing_arc engine version landed; result may be inflated by phantom-fill artifact. |
| `MULTIPLE_COMPARISONS_CAVEAT` | [src/analytics/rank.py](../src/analytics/rank.py) | Tool returns a ranked / picked subset that invites top-K cherry-picking (heatmap with >100 cells, compare_cells output). |
| `NO_P_VALUES_CAVEAT` | [src/mcp/compare_cells.py](../src/mcp/compare_cells.py) | Always emitted by `compare_cells` — re-states the no-significance-test framing inline. |

Wording is load-bearing. Consumer Claudes parse for these strings
by identity; updating the wording in one source file flows to every
tool automatically.

### 4.2 No p-values / no significance-test machinery

[`compare_cells`](../src/mcp/compare_cells.py) carries a LOAD-BEARING
constraint:

> **NO p-values, NO "statistically significant" language, NO
> statistical-test machinery anywhere in the response.**

Reason: with N ≈ 24 per-trade observations per cell, ~5% of
identical-distribution pairs return p<0.05 by chance. An analyst
Claude making hundreds of pair-comparisons in a session would see
dozens of false-positive "significant differences" that compound
into noise-disguised-as-signal.

Enforcement is a regex scan against the serialized JSON output in
[tests/test_mcp_compare_cells.py::test_no_p_values_in_serialized_output](../tests/test_mcp_compare_cells.py).
Banned patterns:

```
\bp[-_ ]?values?\b
\bstatistical(?:ly)? significan(?:t|ce)\b
\bp\s*[<>=]\s*0?\.\d+\b
\bt[-_ ]?test\b
\bchi[-_ ]?square\b
\bmann[-_ ]?whitney\b
\bkolmogorov\b
\bwilcoxon\b
```

Same constraint pattern is enforced on the dashboard's Compare-cells
mode ([tests/test_web_e2e.py::test_compare_cells_renders_no_p_values](../tests/test_web_e2e.py)).
Both the MCP and dashboard surfaces re-emit `MULTIPLE_COMPARISONS_CAVEAT`
verbatim from `src.analytics.rank` — the consumer-facing language is
identical across surfaces.

### 4.3 Pre-pricing-arc detection

The engine stamps each `results.parquet` with `engine_version` in
the parquet KV metadata
([src/engine/results.py](../src/engine/results.py)). Tools that read
sweep results check the stamp via `read_run_metadata(run_id)` and
emit `PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT` when the stamp doesn't
equal `ENGINE_VERSION`.

`list_runs` surfaces the same detection up-front so the consumer
Claude can pick a post-arc run before drilling in.

### 4.4 ENTRY-side scope on data_quality

[`data_quality`](../src/mcp/data_quality.py)'s three dimensions
classify the ENTRY leg only:

- `liquidity_by_entry_offset` — ENTRY leg by definition.
- `theoretical_fallback_rate` — VWAP / close classification on
  ENTRY-side fill prices only. Exit-side classification is not
  surfaced.
- `vwap_vs_close_divergence` — ENTRY-side fill divergence only.

Consumers needing exit-side counterparts derive them from
`cell_summary` (full per-trade list) or `backtest_one` (single
trade with both legs). The `DataQualityInput.dimension` Field
description names the scope explicitly so this is visible in the
tool-discovery JSON schema.

### 4.5 Truncation policy on compare_cells

`compare_cells` returns each cell's per-trade ROI distribution
(capped at `MAX_DISTRIBUTION_ROWS = 200`). Truncation keeps the
LOWEST N by ROI — the right tail is dropped.

Consistent with the tool's tail-risk emphasis (CVaR-5%). Consumers
plotting the distribution as a histogram MUST NOT generalize a
left-shifted shape to mean "cell is worse than it looks". Field
description + truncation caveat string both name the policy
explicitly. Use `cell_summary` for the full per-trade list (no
truncation, includes right-tail trades).

Pinned by
[tests/test_mcp_compare_cells.py::test_compare_cells_truncation_keeps_lowest_n_by_roi](../tests/test_mcp_compare_cells.py).

### 4.6 CVaR-α field-name lock

The shared
[`CellStatsBlock`](../src/analytics/cell_stats.py)'s
`cvar_5_roi_pct` field name encodes the 5% commitment by contract.
`compute_cell_stats` raises `ValueError` if a non-default
`cvar_alpha` is passed — preventing a stat block whose field name
disagrees with its value. Callers needing a different tail fraction
use the alpha-agnostic `bottom_alpha_mean` helper directly.

Pinned by
[tests/test_analytics_cell_stats.py::test_compute_cell_stats_locks_cvar_alpha_to_default](../tests/test_analytics_cell_stats.py).

### 4.7 Schema-layer input validation

All input caps and ranges are enforced at the Pydantic SCHEMA
layer (Field constraints), not in the impl. Two consequences:

- The cap appears in the tool-discovery JSON schema that consumer
  Claudes read at startup — discoverable without calling the tool.
- Rejection fires at deserialization, before any impl code runs.

Notable schema-layer caps:

- `bootstrap_ci.values`: `max_length=5000` (matrix-size budget).
- `compare_cells.cell_keys`: `min_length=2, max_length=4` (compare
  needs ≥2; >4 is too noisy to reason about).
- `bootstrap_ci.B`: `ge=1, le=10_000`.
- `bootstrap_ci.alpha`: `ge=0.0, lt=1.0`.

## 5. Honesty contract per-tool surface

Cross-tool consistency means every tool that touches sweep data
surfaces the same caveat-emission pattern:

```python
caveats: list[str] = []
# Tool-specific caveats first.
if some_tool_specific_condition:
    caveats.append(LOCAL_CAVEAT_STRING)
# Then cross-cutting.
if all_cells_empty:
    caveats.append("All requested cells are empty in this run. ...")
stamp = read_run_metadata(inp.run_id)
if stamp.get("engine_version") != ENGINE_VERSION:
    caveats.append(PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT)
return ToolOutput(..., caveats=caveats)
```

Same shape across the 11 sweep-touching tools. A future contributor
adding a new tool reading sweep parquets copies this pattern and
the pre-arc caveat is automatic.

## 6. The registry-pin test (forward-compat tripwire)

[tests/test_mcp_bootstrap_ci.py::test_server_registry_now_exposes_bootstrap_ci_and_all_16_tools](../tests/test_mcp_bootstrap_ci.py):

```python
def test_server_registry_now_exposes_bootstrap_ci_and_all_16_tools():
    from src.mcp.server import _collect_tool_entries
    registry = _collect_tool_entries()
    expected = {
        # Sub-arc 3.1 universe (3)
        "list_universe", "expiries_for", "list_strategies",
        # Sub-arc 3.2 time-series (3)
        "get_spot_series", "get_option_series", "get_options_chain",
        # Sub-arc 3.3 sweep queries (4)
        "list_runs", "query_sweep", "cell_summary", "heatmap",
        # Sub-arc 3.4 backtest replay (2)
        "backtest_one", "sweep_windows",
        # Sub-arc 3.5 diagnostics (2)
        "skip_summary", "data_quality",
        # Sub-arc 3.6 research helpers (2)
        "compare_cells", "bootstrap_ci",
    }
    assert set(registry.keys()) == expected
    assert len(registry) == 16
```

This is the v1 catalog. Adding, removing, or renaming a tool
without updating the expected set fires the test. The grouping
comments are deliberate — a maintainer adding a new tool sees
exactly where it fits.

Phase 9 (paper trading) will add MUTATING tools under a new sub-arc
prefix (e.g. `paper_open` / `paper_status` / `paper_close`) and
update this test to a Phase-9 catalog. Phase 9 tools land in a new
test file with its own pinned catalog; this test remains the v1
historical record.

## 7. What the server does NOT do (non-goals reminder)

- **No mutations.** No file writes, no sweep runs, no broker calls.
- **No HTTP transport.** stdio only. v1 client is Claude Code.
- **No authentication.** stdio runs as a child of the Claude Code
  process; auth is delegated to the OS process boundary.
- **No live market data.** All time-series tools read the cached
  parquet/snapshot data under `data/`.
- **No statistical-test machinery on `compare_cells`** (see §4.2).
- **No session-scoped state.** Every tool takes `run_id` as an
  explicit argument; the server holds no per-session memory.

## 8. Provenance

| Commit | Sub-arc / artifact |
|---|---|
| `b42d4c2` | p8.mcp.skeleton — `src/mcp/` layout, ToolEntry registry, CaveatedResponse base |
| `0cc0b2c` | p8.mcp.universe — list_universe / expiries_for / list_strategies |
| `661b1ff` | p8.mcp.spot_options — get_spot_series / get_option_series / get_options_chain |
| `bacf5cf` | p8.mcp.sweep_query — list_runs / query_sweep |
| `3264f37` | p8.mcp.cell_summary — cell_summary |
| `d138fef` | p8.mcp.heatmap — heatmap |
| `a98a29d` | p8.mcp.consolidate — pre-arc caveat constant + bootstrap method string + per_trade cap |
| `66ff72b` | fix(p8.mcp.heatmap.dead_comprehension) — dropped O(n×m) per-cell list-build overwritten by try/except |
| `4d9ddc2` | test(p8.mcp.protocol_integration) — SDK-dispatcher integration tests (closed reviewer's 6-commits-deep gap) |
| `0b39030` | fix(p8.mcp.data_validation) — NaN-guard + filter dtype-coercion + chain-truncation note |
| `c3545cc` | p8.mcp.backtest_one — single-trade replay with VWAP-vs-close fill classification |
| `b29d55e` | chore(p8.fill_audit.centralize) — pulled `classify_fill_source` into `src/engine/pnl` (prereq for the c3545cc/96a506c carry-over grills) |
| `96a506c` | p8.mcp.sweep_windows — grid replay across N expiries |
| `8a44bb8` | docs(p8.mcp.sweep_windows.pre_arc_note) — named the pre-arc caveat omission in sweep_windows's docstring |
| `fc6356e` | p8.mcp.skip_summary — skip-by-reason breakdown for one sweep run |
| `f27afb7` | chore(p8.mcp.skip_summary.polish) — non-default RESULTS_DIR + examples-are-first-N (closes fc6356e grills) |
| `22104df` | p8.mcp.data_quality — three diagnostic dimensions |
| `b25f048` | fix(p8.mcp.data_quality.liquidity_dedup) — Option B (df for trade-level, legs_df for leg-level) |
| `ebe7228` | chore(p8.cell_stats.centralize) — shared CellStatsBlock + compute_cell_stats |
| `67c6d3f` | p8.mcp.compare_cells — side-by-side comparison + no-p-values pin |
| `72d06c6` | p8.mcp.bootstrap_ci — pure-compute CI tool (closes arc at 16/16) |
| `44eed75` | chore(p8.mcp.compare_cells.truncation_docs) — lowest-N policy named |
| `0a81f31` | chore(p8.mcp.bootstrap_ci.schema_cap) — MAX_VALUES moved to schema layer |
| `f4707e3` | chore(p8.mcp.data_quality.entry_side_docs) — ENTRY-side scope named in dimension field |
| `69ab7e3` | chore(p8.cell_stats.cvar_alpha_lock) — raise on non-default cvar_alpha |

The consultation roadmap projected 13 commits; the actual arc landed
24 BUILDER commits before this docs commit, driven by in-arc polish
the reviewer surfaced (the 5 fix/test/chore commits above plus the
4 post-arc polish chores closing carry-forward grills). The growth
is honest; the reviewer-builder loop catching coverage gaps and
deduplication opportunities is the value the roadmap couldn't price.
