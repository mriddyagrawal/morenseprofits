# Builder consultation — Phase 8 MCP server (research-API)

Replaces the now-closed pricing-validity arc consultation. **Pre-code
design review**: operator explicitly directed "Get it reviewed first!"
before any commits land.

The motivation arrived organically. Today (2026-05-30) we confirmed
via empirical analysis of `sweep_5c336519a7dc.parquet` that the
analyst's #1 hypothesis (phantom-fill prices on illiquid deep-dated
contracts) was the dominant source of inflated short-vol ROI:

- T-1..T-5  : 0.3% zero-entry-volume rate → mean ROI -0.06%
- T-31..T-40: 75.1% zero-entry-volume rate → mean ROI +6.40%
- T-41..T-45: **91.1%** zero-entry-volume rate → mean ROI **+10.90%**

The IlliquidLegError gate (commit 94d535f, just-shipped pricing-arc)
will eliminate this artifact on the next sweep — but the analyst who
diagnosed it is an external Claude, NOT a person looking at this
codebase. **That's the operator's actual ask**: enable external
Claudes to do research against this dataset without manual data export.

---

## 1. Decisions locked (per operator direction in 2026-05-30 chat)

| Decision | Choice | Rationale |
|---|---|---|
| Transport | **stdio only** | Claude Code (CLI) integration; local-only; no auth complexity. HTTP+SSE explicitly deferred. |
| Run scoping | **per-tool `run_id` argument** | Consumer Claude can compare across runs in one session — the analyst pattern from today needs A/B between pre-arc + post-arc sweeps. |
| Read/write | **read-only** | Per PLAN.md Phase-8 spec; matches "6 read-only tools" framing. Writes (positions, sweep execution) belong to Phase 9/10. |
| Honesty contract | Every aggregated tool returns `caveats: list[str]` | Forces every consumer (current + future Claudes, future React UI) to see the same epistemic warnings the dashboard surfaces. |
| no-p-values | Banned-phrase regex test on `compare_cells` output | Same enforcement pattern as the dashboard (tests/test_web_e2e.py::test_compare_cells_renders_no_p_values). |

---

## 2. Scope & non-goals

**In scope (Phase 8.x):**
- 16 read-only tools exposing universe / time-series / sweep-query /
  backtest-replay / diagnostics / research-helpers
- Cache-only `backtest_one` and `sweep_windows` (never hits NSE)
- Pydantic schemas auto-generate the tool JSON schemas Claude sees
- All tools delegate to existing `src/analytics`, `src/engine`,
  `src/data` modules — the MCP layer is a transport, not new analytics

**Explicit non-goals:**
- Phase 9 paper-trading writes (positions, mark-to-market)
- Phase 10 live-broker integration
- Sweep-grid execution behind a tool (sweep_grid stays a script —
  10-15 min wall-clock is too heavy for an interactive API)
- Strategy authoring (strategies stay code-defined; no `add_strategy`)
- Schema migration / cache invalidation tools (operator-only)
- Authentication (stdio = trust by process ownership; HTTP deferred)

---

## 3. Endpoint catalog (16 tools, 7 sub-arc groupings)

### 3.1 Universe & calendar (3)
- `list_universe(as_of?) → {blue_chip, extras, total, caveats}`
- `expiries_for(symbol, from_date, to_date) → list[date]`
- `list_strategies() → list[{name, params, strike_rule, margin_offset_pct, deployment_spec}]`

### 3.2 Time-series (3 — parquet reads)
- `get_spot_series(symbol, from_date, to_date) → list[OHLCV]`
- `get_option_series(symbol, expiry, strike, option_type, from_date?, to_date?) → list[contract_row]` (now includes turnover + vwap_inferred per the just-landed pricing arc)
- `get_options_chain(symbol, on_date, expiry?) → list[strike_row]`

### 3.3 Sweep queries (4)
- `list_runs() → list[{run_id, mtime, n_cells, strategies, symbol_count, date_range, pricing_arc_applied: bool}]`
  → The `pricing_arc_applied` flag is load-bearing: tells consumers whether the gate + VWAP fixes are baked into the parquet.
- `query_sweep(run_id, filters, columns?, sort_by?, limit?) → list[trade_row]` (capped at 10K rows; cursor-based pagination for larger)
- `cell_summary(run_id, strategy, symbol, entry_offset_td, exit_offset_td) → {stats, per_trade, bootstrap_ci, observations, caveats}`
- `heatmap(run_id, strategy, symbol, value_col, agg_fn, min_n?) → {grid, axes, caveats}`

### 3.4 Backtest replay (2 — cache-only)
- `backtest_one(strategy, symbol, expiry, entry_date, exit_date, params?) → {trade_result, legs_breakdown, gate_status, vwap_vs_close_divergence, caveats}`
- `sweep_windows(strategy, symbol, expiry_range, entry_offset_range, exit_offset_range) → list[cell_summary]`

### 3.5 Diagnostics (2 — the analyses we just ran today)
- `skip_summary(run_id, group_by?) → {counts_by_reason, examples, total_cells, skip_rate}`
- `data_quality(run_id, dimension?) → {table, summary, caveats}`
  → `dimension ∈ {liquidity_by_entry_offset, theoretical_fallback_rate, vwap_vs_close_divergence}`. The liquidity-by-entry-offset table is exactly the analysis that confirmed the phantom-fill bias.

### 3.6 Research helpers (2)
- `compare_cells(run_id, cell_keys[]) → {stats_table, diff_table, distribution_overlay, caveats: ["No p-values..."]}`
- `bootstrap_ci(values[], B?, alpha?, seed?) → {lo, median, hi, n_iterations}`

Total: **16 tools**.

---

## 4. Honesty contract (cross-cutting requirement)

Every tool that returns aggregate data MUST return a `caveats: list[str]`
field alongside the data. The reasons a caveat fires:

1. **Survivorship bias**: any query touching the universe pre-2024.
2. **Below-min_n cells included**: warns the consumer that some cells in
   the result have <5 trades.
3. **Pre-pricing-arc parquet**: if `list_runs(...).pricing_arc_applied`
   is False, every cell-summary / heatmap on that run carries a
   "phantom-fill bias likely" caveat.
4. **Multiple-comparisons surface large**: any heatmap covering
   >100 cells surfaces a caveat about pick-the-best-cell selection
   bias (same content as the existing `MULTIPLE_COMPARISONS_CAVEAT`
   from `src/analytics/rank.py`).
5. **No-p-values enforcement** on `compare_cells`: explicit caveat in
   the response naming the REVIEWER CONSTRAINT.

Tests will assert the caveat-presence invariants via Pydantic schema
validators, so a future contributor can't accidentally drop a caveat.

---

## 5. Implementation roadmap (~13 commits)

| Sub-arc | Commits | Purpose |
|---|---|---|
| 8.1 Scaffold | `chore(p8.mcp.skeleton)` (1) | Bare server boots, no tools yet. Pydantic infra. `python -m morenseprofits.mcp` runs. |
| 8.2 Universe | `feat(p8.mcp.universe)` (1) | list_universe, expiries_for, list_strategies. Exercises the caveats-contract pattern. |
| 8.3 Time-series | `feat(p8.mcp.spot_options)` (1) | spot, option series, chain. Pure cache reads. |
| 8.4 Sweep queries | `feat(p8.mcp.cell_summary)`, `feat(p8.mcp.heatmap)`, `feat(p8.mcp.query_sweep)` (3) | Biggest analytical surface; one commit per tool given complexity. |
| 8.5 Replay | `feat(p8.mcp.backtest_one)`, `feat(p8.mcp.sweep_windows)` (2) | Cache-only price_trade invocations. |
| 8.6 Diagnostics | `feat(p8.mcp.skip_summary)`, `feat(p8.mcp.data_quality)` (2) | Surface the gate + VWAP + units artifacts as first-class APIs. |
| 8.7 Research | `feat(p8.mcp.compare_cells)`, `feat(p8.mcp.bootstrap)` (2) | no-p-values failing-test reused from dashboard pattern. |
| 8.8 Docs | `docs(p8.mcp.contract)` (1) | Claude Code config example + tool-reference. |

**13 commits total. 1-2 days of focused nuclear-style work.**

---

## 6. Open questions for REVIEWER

### Q1 — Where does the MCP server module live?

Three options:
- (a) New top-level package: `src/mcp/server.py`
- (b) Sub-module under `src/web/`: `src/web/mcp.py` (philosophy: same role as the dashboard — an analytical-surface transport)
- (c) Standalone `morenseprofits_mcp/` package (closer to MCP convention)

BUILDER lean: **(a)** — `src/mcp/` keeps it at top-level visibility,
matches the existing pattern (`src/analytics`, `src/engine`, `src/data`,
`src/web`). The dashboard isn't a "data transport" per se; the MCP
server IS. Distinct enough to warrant its own directory.

### Q2 — Pydantic version pin?

The existing codebase doesn't yet use Pydantic heavily. MCP SDK
requires Pydantic v2. Should we:
- (a) Pin Pydantic v2 in `pyproject.toml` as a hard dependency
- (b) Use only the MCP SDK's pre-bundled Pydantic (avoid the version
  spread to the rest of the codebase)

BUILDER lean: **(a)** — Pydantic is the right modeling layer for
typed API contracts; pinning it once now avoids "where does this
schema live?" drift later.

### Q3 — Schema-pinning tests at what granularity?

Each tool's request/response schema is a contract; consumers depend on
it. Options:
- (a) Per-tool snapshot test of the generated JSON schema (catches
  any field rename / dtype change)
- (b) Integration test that boots the server, calls each tool with
  known inputs, asserts shape (slower but catches end-to-end drift)
- (c) Both

BUILDER lean: **(c)** for the 4 highest-value tools (`cell_summary`,
`heatmap`, `backtest_one`, `data_quality`); **(a) only** for the
others. Full integration tests for all 16 would add ~30s to the test
suite for marginal coverage.

### Q4 — Caveat enforcement: schema-level or test-level?

The caveats-list invariant could be enforced via:
- (a) Pydantic validator: `@validator("caveats") def must_be_present`
  raises if a result type that should have caveats omits them
- (b) Test that calls each tool and asserts caveats are present in the
  response
- (c) Convention only (documented in the docstring, not enforced)

BUILDER lean: **(a)** — schema-level invariants are the strongest
defense against drift. Catches any future contributor who returns
a response dict missing the field.

### Q5 — `pricing_arc_applied` detection on `list_runs`

How does `list_runs` decide whether a sweep parquet was generated
post-pricing-arc? Three options:
- (a) Inspect the parquet's column set — if `entry_turnover` /
  `exit_turnover` are present in `legs_json` of a sample row, the run
  is post-arc.
- (b) Stamp a metadata column (`pricing_arc_version`) on every sweep
  result at write time — requires touching `src/engine/results.py`.
- (c) Heuristic: `mtime` after the pricing arc landed (cb6ad92) is
  considered post-arc. Brittle.

BUILDER lean: **(a)** for v1 (zero new infra), **(b)** added later if
the heuristic gets fragile.

---

## 7. What this does NOT fix

Per the honesty pattern from the pricing arc's §6:

- **Survivorship bias** — universe is a 2024 snapshot; MCP tools
  surface this via caveats but can't fix it (Phase-7 backlog item
  per SPECS §6b.3).
- **Slippage understatement on wings** — flat 1% per side stays;
  Phase-2 nice-to-have per the pricing-arc consultation.
- **MCP server is research-honesty plumbing, not deploy-readiness**.
  An external Claude returning "this cell looks good" is research
  output, NOT a live-trade signal. The caveats make this explicit.

---

## 8. Why this is the right thing to do now (post-pricing-arc)

The empirical finding from 2026-05-30 made the case concrete: an
external Claude looking at the pre-arc parquet would have
confidently reported "+10.9% on T-45 entries across the universe!"
without ever seeing the 91% zero-volume rate that produced it.

Phase 8's `data_quality(run_id, "liquidity_by_entry_offset")` makes
that analysis a one-tool call. Any future external research interaction
inherits the data-quality footprint by default. That's the operational
upgrade — going from "an external analyst can be misled" to "an
external analyst CAN'T avoid seeing the artifacts."

---

*Builder. Awaiting reviewer response in comments.md before commit 1.*
