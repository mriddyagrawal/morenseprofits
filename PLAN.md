# PLAN — NSE Options Strategy Research Platform

> Living document. Phases and commits are planned in advance; improvisations land here with a `[REVISED YYYY-MM-DD]` note explaining why.

## 0. Mission

Build a **multi-strategy options backtesting + research platform** for the Indian NSE market. The platform discovers, by sheer iteration over historical data, which option strategies (entry rules, leg structure, expiry timing, strike selection, exit rules) produce favorable outcomes on which stocks under which conditions. Findings surface as a local web app with bar charts and trend visualizations.

The original ask centered on the **short straddle**; that remains the canonical first strategy and the validation target for the engine, but the architecture is strategy-agnostic from day one.

## 1. Non-goals

- Live trading. Order routing. Broker integration. **Backtest only.**
- Tick-level intraday simulation. We work on daily OHLC/settle from NSE EOD data.
- Index options (NIFTY / BANKNIFTY) — out of scope for v1. Stock options only. (Easy to add later — `derivatives_df` supports both via `instrument_type`.)
- Greeks-based analytics (delta hedging, vega exposure decomposition). Out of scope for v1; revisit if it would meaningfully change strategy ranking.

## 2. Architecture (one diagram, in words)

```
   ┌──────────────────────────────────────────────────────────┐
   │  jugaad-data  (NSE historical EOD: equity + derivatives) │
   └──────────────────────────┬───────────────────────────────┘
                              │ fetched once, cached forever
                              ▼
        data/cache/parquet/   ◄── disk cache (parquet)
                              │
                              ▼
        DATA LAYER  (src/data/)
          - spot_loader, options_loader, expiry_calendar, lot_sizes
          - returns clean pandas DataFrames with documented schema
                              │
                              ▼
        UNIVERSE LAYER  (src/universe/)
          - blue_chip, bullish, non_bullish — reproducible rules
                              │
                              ▼
        STRATEGY LAYER  (src/strategies/)
          - each strategy is a class implementing the Strategy protocol
          - generates Trade objects (legs, entry_date, exit_date, params)
                              │
                              ▼
        ENGINE  (src/engine/)
          - backtester: prices trades using cached data, applies costs,
            returns per-trade P&L; respects no-lookahead
          - sweeper: cartesian sweep over (strategy, stock, year, month,
            entry_offset, exit_offset, strike_offset, ...)
                              │
                              ▼
        RESULTS STORE  (data/results/)
          - one parquet per (strategy, run_id) with all trades
          - aggregations computed lazily
                              │
                              ▼
        REPORT UI  (src/web/)
          - streamlit; bar charts + trend lines
          - per-stock, per-strategy, per-category, per-month, per-year views
          - ranks winning configurations; surfaces decay / seasonality
```

## 3. Phase plan

### Granularity doctrine ("nuclear steps")

A phase is a *goal*. A phase contains *steps*. A step maps to **exactly one commit** and is the smallest atomic change that still leaves the repo in a sensible state. Prefer many small commits over few large ones. After every commit the builder polls `comments.md` for new reviewer blocks before starting the next step. Reviewer **blocking** issues are addressed in the *very next* commit — no piling on new functionality first. Reviewer **non-blocking** suggestions are addressed opportunistically but no later than the end of the current phase; if deferred past the phase boundary they get an entry in the open-questions section so they aren't lost.

Each phase ends with **tests passing** + every planned step committed + a status note added to this file.

### Phase 0 — Scaffolding `[in progress]`
**Goal:** Establish the project skeleton, dependencies, planning docs, and pass a smoke test.

Commits:
1. `chore(p0): scaffolding — PLAN, SPECS, .gitignore, requirements, src/ skeleton`

Exit criteria:
- `PLAN.md` + `SPECS.md` checked in and reviewed.
- `requirements.txt` pinned to versions that produced a passing smoke test.
- `.gitignore` excludes `.venv/`, `data/cache/`, `data/results/`, `__pycache__/`.
- `src/` directory tree exists with empty `__init__.py` files.
- `scripts/smoke_test.py` fetches one day of RELIANCE spot + one ATM option series and prints shapes.

### Phase 1 — Data layer
**Goal:** Read-through cached data access for spot, options, expiry calendar, NSE trading calendar.

Steps (one commit each):
1. `feat(p1.1): data/cache.py — parquet read/write/exists helpers + CACHE_VERSION dir guard`
2. `test(p1.1): cache helpers — round-trip + version-guard test (no network)`
3. `feat(p1.2): data/spot_loader.py — load_spot() with year-keyed parquet cache`
4. `test(p1.2): spot_loader schema test against tests/fixtures/spot_reliance_2024.parquet`
5. `feat(p1.3.0): SPECS §2.4 — bhavcopy_fo cache type + cache.bhavcopy_fo_path helper`
6. `test(p1.3.0): cache.bhavcopy_fo_path unit test`
7. `feat(p1.3.1): data/bhavcopy_fo_loader.py — cached F&O bhavcopy fetch + parse`
8. `test(p1.3.1): bhavcopy_fo_loader tests (mocked jugaad)`
9. `feat(p1.3.2): data/expiry_calendar.py — monthly_expiries() sourced from cached bhavcopies`
10. `test(p1.3.2): determinism + RELIANCE Jan 2024 = 2024-01-25 hand-check + sorted-unique + cache-hit`
11. `chore(p1.3.verify): end-to-end live-NSE verification on one symbol×month`
12. `feat(p1.4): data/options_loader.py — load_option() with (symbol/expiry/strike-type) parquet cache`
13. `test(p1.4): options_loader schema + cache-hit test against fixture`
14. `feat(p1.5): data/trading_calendar.py — trading_days() + offset_trading_days() built on RELIANCE spot + jugaad holidays overlay`
15. `test(p1.5): trading_calendar correctness — offset(expiry, 0) == expiry, monotonic, etc.`
16. `chore(p1.6): offline-mode kwarg on every loader (behavior contract per SPECS §6a)`
17. `chore(p1.7): cache-hit telemetry — warn when a sweep accidentally hits the network`

Exit criteria:
- Second call to any loader is < 50ms (disk hit, no network).
- All returned DataFrames conform to schemas in SPECS.md §2.
- `pytest tests/` green with default markers (network tests skipped).

### Phase 2 — Universe selection
**Goal:** Reproducible stock-category definitions.

Steps (one commit each per nuclear doctrine):
1. `chore(p2.0): SPECS for universe — survivorship-bias policy + schema`
2. `feat(p2.1): src/universe/blue_chip.py — single Nifty-50 snapshot`
3. `test(p2.1): blue_chip determinism + as_of + count`
4. `feat(p2.2): src/universe/momentum.py — trailing 6-month return classifier`
5. `test(p2.2): momentum determinism + bullish/non-bullish split`
6. `chore(p2.verify): live verify on a small universe slice (computes momentum on 5 stocks via load_spot)`

Exit criteria:
- Re-running classifier with the same `as_of` date yields byte-identical membership.
- Membership snapshots cached so we can audit later runs.

### Phase 3 — Single-strategy backtest engine (short straddle)
**Goal:** Compute P&L for one well-defined trade end-to-end. The validation crucible — bugs caught here save us in Phase 4.

Steps (one commit each per nuclear doctrine):
1. `chore(p3.0): SPECS for engine — Trade/Leg schemas, sign convention, no-lookahead rule, ATM selection`
2. `feat(p3.1): src/strategies/base.py — Trade, Leg dataclasses + Strategy protocol`
3. `feat(p3.2): src/engine/pnl.py — per-trade gross P&L kernel with no-lookahead + missing-data enforcement`
4. `test(p3.2): gross P&L hand-checked on fixture (signs + arithmetic + no-lookahead trip)`
5. `feat(p3.3): src/engine/costs.py — COST_MODEL_V1 (STT sell-side, brokerage, exchange, GST, stamp duty, SEBI)`
6. `test(p3.3): cost model hand-checked on a few legs`
7. `feat(p3.4): src/strategies/short_straddle.py — picks ATM CE+PE per SPECS §5`
8. `test(p3.4): short_straddle.generate_trades schema + ATM rule`
9. `chore(p3.verify): live short straddle on RELIANCE Jan-2024 (T-15 → T-1) — first real ₹P&L number`

Exit criteria:
- One hand-checked trade matches the engine output to within ₹1.
- Engine refuses to price if any required data is missing (no silent interpolation).
- No-look-ahead enforced by code: any access to `data[date > exit_date]` raises.

### Phase 4 — Parameter sweep + multi-strategy framework
**Goal:** Run thousands of backtests across the cartesian grid; add 4 more strategies.

Steps (one commit each per nuclear doctrine):
1. `chore(p4.0): SPECS for sweep — registry, results store, determinism contract`
2. `feat(p4.1): src/strategies/registry.py — name → Strategy mapping`
3. `feat(p4.2): src/engine/sweeper.py — single-threaded sweep_one() + sweep_grid()`
4. `feat(p4.3): src/engine/results.py — write/read sweep parquet per SPECS §2.5`
5. `feat(p4.4.a): src/strategies/long_straddle.py — mirror of short_straddle`
6. `feat(p4.4.b): src/strategies/short_strangle.py — strike_offset_pct param`
7. `feat(p4.4.c): src/strategies/long_strangle.py`
8. `feat(p4.4.d): src/strategies/iron_condor.py — fixes caveat #1 (spot-based margin for asymmetric)`
9. `perf(p4.5): multiprocessing.Pool — preserves determinism`
10. `test(p4.5): sweep byte-identical regardless of worker count`
11. `chore(p4.verify): live small sweep on RELIANCE × 3 months × 5 windows`

Exit criteria:
- A full sweep on 5 blue-chip stocks × 12 months × 5 entry × 5 exit offsets × 5 strategies completes in < 10 min on the user's laptop after warm cache.

### Phase 5 — Aggregation + trend analytics
**Goal:** Turn raw trade tables into the insights the user actually wants.

Commits:
1. `feat(p5): per-stock × strategy summary stats (mean, median, win-rate, max-DD, sample N)`
2. `feat(p5): entry/exit heatmap matrix — avg P&L by (entry_offset, exit_offset)`
3. `feat(p5): year-over-year trend (is strategy X decaying?)`
4. `feat(p5): month-of-year seasonality breakdown`
5. `feat(p5): ranking — top configurations per stock, with multiple-comparisons caveat surfaced`

Exit criteria:
- Aggregates reproducible from results parquet alone; no re-running backtests.

### Phase 6 — Web report UI
**Goal:** The user's actual deliverable.

**Scope frozen 2026-05-25 to 4 tabs for v1**: Leaderboard, Per-stock,
Heatmap, Trends. Detailed UI architecture + 26-sub-commit nuclear
breakdown is in [DESIGN/DESIGN_SPEC.md](DESIGN/DESIGN_SPEC.md) §4 —
PLAN.md keeps only the headline goal here to avoid drift.

Exit criteria:
- `streamlit run app.py` opens a working report on the cached results.
- Every number in the UI is traceable to a row in the results parquet.
- All four tabs render against the verify-set parquet without crashes;
  thin-data UX paths exercised per DESIGN_SPEC §2.6.
- Tagged `v0.6-ui` at completion.

### Phase 7 — Polish, drill-down, deferred-tab additions
**Goal:** Close the per-trade evidence loop + ship the polish + docs.

Commits:
1. `feat(p7.1): trade-level drill-down tab — pick a (strategy, symbol, entry, exit, expiry) cell, render its ~3-30 actual trades with entry spot, exit spot, per-leg premiums, gross/net P&L. Closes the "show me the evidence behind the median" loop. Most defensible Phase-6-deferred addition per 2026-05-25 scope freeze.`
2. `feat(p7.2): diagnostics tab — full skip-log breakdown ("180×MissingDataError, 20×NoLiquidStrike"), bhavcopy/options coverage map, run_id history. Operator-tooling complement to the researcher-facing tabs.`
3. `feat(p7.3): export buttons — CSV + PNG via st.download_button on every tab. DESIGN_SPEC §9 open Q resolved here.`
4. `feat(p7.4): regime drill-down — surface the classify_momentum output itself (which months are bullish, trailing-return distribution). Useful for trust-building once multi-year data lands.`
5. `chore(p7): README — quickstart, data refresh, how to add a strategy`
6. `feat(p7): user-curated-universe skill — operator supplies their own stock list per session, overriding blue_chip(); satisfies SPECS §6b.3 mitigation #2 (point-in-time membership) at the source. Deferred per change-log 2026-05-24.`
7. `feat(p7): BLUE_CHIP_BY_QUARTER point-in-time membership for true survivorship-bias-free backtests.`
8. `chore(p7): final commit — Phase 7 complete`

### Phase 8 (DEFERRED) — Agent-callable research API

**Goal:** Let any Claude (or other MCP-capable agent) issue its own
research queries against the backtest dataset without having to read
Python — turns the platform from "single-user web app" into "shared
research backend".

Read-only scope. No order execution.

Sketch:
1. `feat(p8): src/mcp_server/server.py — MCP server skeleton`
2. `feat(p8): tool list_universe(category)`
3. `feat(p8): tool classify_regime(symbol, as_of)`
4. `feat(p8): tool expiries_for(symbol, year)`
5. `feat(p8): tool backtest_one(strategy, symbol, expiry, entry_offset_td, exit_offset_td)`
6. `feat(p8): tool sweep_windows(strategy, symbol, expiry, entry_grid, exit_grid)`
7. `feat(p8): tool summarize(strategy, symbol_or_category, year_range, regime_filter)`
8. `chore(p8): SPECS §10 — MCP tool contracts; integration test against a local MCP client`

### Phase 9 (DEFERRED) — Paper trading

**Goal:** Simulated open-position tracker with live mark-to-market.
Validates the research outputs against real-time NSE prices without
risking capital.

Sketch:
1. `chore(p9): SPECS §11 — paper-positions schema + mark-to-market policy + close-on-expiry rule`
2. `feat(p9): src/paper/positions.py — open / close / list — parquet-backed store`
3. `feat(p9): src/paper/mtm.py — fetch live spot+option via NSELive, recompute unrealized P&L`
4. `feat(p9): MCP tools paper_open / paper_status / paper_close`
5. `chore(p9): runbook — how to interpret paper P&L vs backtest P&L`

### Phase 10 (DEFERRED — separate project scope) — Live trading

**Goal:** Real broker integration with risk controls + audit. Treat as
its own quarter of work, not as one more phase.

Hard prerequisites before any Phase-10 commit:
- ≥ 3 months of paper-trading track record matching backtest expectations
- Written runbook: order state machine, kill-switch, daily loss limit
- Per-trade approval (no autonomous execution v1) — agent proposes, human approves, system executes

Sketch:
1. Broker API client (Zerodha Kite or equivalent) with auth + token refresh
2. Order state machine (placed → ack'd → filled → settled) with idempotency keys
3. Risk controls (max position size, drawdown stop, daily loss limit)
4. Audit log — every order traceable to agent decision + human approval
5. Kill switch (single env var disables order placement immediately)
6. Phase-10 final commit only after the runbook + audit are reviewed

## 4. Hard correctness rules (engine must enforce, not just hope)

1. **No look-ahead.** Strategy receives only `market_data[market_data.date <= entry_date]`. Engine asserts this.
2. **Real prices only.** If an entry or exit date has no traded price for a leg, the engine raises `MissingDataError`. Caller decides whether to skip or fail.
3. **Historical lot size per trade.** Read from `MARKET LOT` column of the derivatives row, not from a constant.
4. **ATM = strike nearest to entry-day spot close.** Tiebreaker: lower strike. Documented in `SPECS.md §5`.
5. **Trading-day offsets.** "T-15" means 15 *trading* days before expiry, computed from spot calendar. Documented in `SPECS.md §6`.
6. **Cost model applied symmetrically.** Same fee schedule for every backtest; toggleable but versioned.
7. **Deterministic.** Same input → byte-identical result parquet. Strategies that need randomness must accept a `seed`.

## 5. What I'll improvise on (and how I'll record it)

Anything not explicitly nailed down above — schema field order, internal helper APIs, chart styling, which streamlit components to use — I improvise. When I make a non-trivial improvisation (changes a public interface, alters the phase plan, adds a new strategy not listed), I append a line to **§7 Change log** below before or with the commit that introduces it.

## 6. Open questions (will resolve as I go)

- Should bullish/non-bullish be defined on trailing return, on realized vol, on momentum score? → Will pick trailing 6-month total return in Phase 2; revisit if it produces a degenerate split.
- Margin / capital normalization for cross-strategy ranking? Short straddles need more margin than spreads — comparing absolute P&L is unfair. → Phase 5 will report P&L per ₹1L of SPAN margin (approximated), in addition to absolute P&L.
- How far back should backtests go? → Start with 2019-01-01 onward. Earlier NSE option data exists but liquidity is worse and lot sizes change more often.

## 7. Change log

- 2026-05-24 — Scope expanded mid-Phase-0 from "short straddle only" to "multi-strategy research platform". Architecture and Phase 4 updated; Phase 3 still uses short straddle as the validation strategy.
- 2026-05-24 — Reviewer flagged that `jugaad_data.nse.expiry_dates` returns `list(set(dts))` — non-deterministic iteration order across runs. This is why the Phase-0 smoke test printed different "first expiry" values on different invocations (Jan-25 vs Feb-29 vs Mar-28) — set iteration, not NSE. Every loader that consumes a set/dict-derived collection from jugaad must `sorted(...)` before caching or returning. Phase 1.2's spot_loader bakes in `sort_values("date")` + monotonicity assertion at the data-layer boundary so this class of bug dies once.
- 2026-05-24 — Phase-2 blue-chip universe sized down from 50 to **40** per user direction ("just kinda good is fine; reporting/analysis quality matters more than exact composition"). The 10 dropped members were the lower-options-liquidity tail of Nifty 50. Survivorship-bias caveat in SPECS §6b.3 still applies and is unchanged.
- 2026-05-24 — Deferred Phase-7 item added per user request: **user-curated-universe skill**. End-of-project, lets the operator feed in their own stock list per session (e.g. "run the same report on this 30-stock watchlist"). Until then v1 ships the hardcoded blue-chip 40.
- 2026-05-24 — Three new DEFERRED phases added (8/9/10) per user direction: **Phase 8 agent-callable research API** (MCP server with 6 read-only tools — list_universe/classify_regime/expiries_for/backtest_one/sweep_windows/summarize — so any Claude instance can do its own research against our dataset); **Phase 9 paper trading** (positions store + live mark-to-market via NSELive + 3 MCP tools); **Phase 10 live trading** (broker integration, treated as its own quarter of work with hard prerequisites — paper-trading track record, runbook, per-trade approval gate, kill switch). 8 and 9 are natural extensions of the data+analytics surface; 10 is scoped as a separate project to be undertaken only after paper-trading validation.
- 2026-05-24 — Phase 3.5 margin model upgraded mid-phase to **Tier B** (strategy_offset_pct + vol-aware per-symbol margin) per user direction ("If any of these will give me better results... you should do that"). Background: real NSE SPAN requires their daily SPAN files which are NOT archived for historical dates — so for *backtesting* (2019-2024), Tier B is the realistic accuracy ceiling. Tier C (real SPAN file parsing) is reserved for Phase 9 paper-trading where today's margin is what matters. Tier B drops cross-strategy ranking bias from ~60% to ~10-15%; rankings now sound. See SPECS §4a for the full tier explanation + calibration table.
- 2026-05-24 — Phase 4.4 IronCondor commit split into **p4.4.d.i** (caveat #1 margin fix — `spot_at_entry` kwarg on MarginModelV1) + **p4.4.d.ii** (4-leg IronCondor strategy) per nuclear-commits feedback. The margin fix is independently reviewable on synthetic asymmetric legs; IronCondor then exercises it end-to-end via sweep_one. Same overall content, two smaller commits.
- 2026-05-24 — **p4.5 (multiprocessing.Pool) deferred until per-task latency is measured.** Reasoning: at typical small-grid verification sweeps (~60 tasks × ~100ms cached = ~6s), serial is already fast. Parallel speedup only matters at the ~30k-task final-report scale, which is a Phase-6 concern. Better to do `chore(p4.verify)` first, learn the actual cache-warm latency, then decide if parallelization is worth the determinism-contract complexity. p4.5 stays in PLAN.md but is now post-p4.verify, not blocking it.
- 2026-05-24 — Added **chore(p4.4.refactor)** between p4.4.d.ii and p4.verify per reviewer's "now urgent" flag: extract `src/strategies/_strikes.py` with `NoLiquidStrikeError + load_available_strikes + pick_nearest`. The bhavcopy-querying + SPECS §5 picker was copy-pasted across 4 strategies; consolidating now means future strategy adds are ~2 lines instead of ~12.
- 2026-05-25 — **Phase 6 scope frozen to 4 tabs for v1**: Leaderboard, Per-stock, Heatmap, Trends. PLAN.md §3 Phase-6 commit list replaced with a pointer to DESIGN/DESIGN_SPEC.md §4 (which now owns the nuclear 26-sub-commit breakdown) to prevent drift between the two docs. Three considered-but-deferred tabs added to Phase 7: **trade-level drill-down** (per-cell trade list — closes the "evidence behind the median" loop; most defensible addition), **diagnostics** (full skip-log + coverage map + run_id history), **regime drill-down** (surfaces classify_momentum output). Export buttons (DESIGN_SPEC §9 open Q) also moved to Phase 7 explicitly. Compare-pairs view rejected: largely covered by Heatmap filter-switching + Leaderboard sorting; not unique enough to earn its own tab.
- 2026-05-26 — **`sweep_grid(cache_only=True)` carve-out added to SPECS §6a.** Wide sweeps (Phase-7 wide-grid) hit pathological NSE-throttle behavior when 8 workers each tried to refresh stale open-expiry caches concurrently — sweep crawled at 11-25 cells/sec instead of ~1000. Two-part fix landed: (1) added `cache_only=True` to `sweep_grid`/`sweep_one` that auto-implies `offline=True` and treats `OfflineCacheMiss` as a per-cell skip via a new `_SKIPPABLE_ERRORS_CACHE_ONLY` tuple; (2) plumbed `offline=` through `price_trade` → `_price_one_leg` → `load_option` (was previously dropped at the kernel, so workers still hit NSE despite cache_only=True). Default `_SKIPPABLE_ERRORS` unchanged; the loud-fail contract for direct callers is preserved. **Trade-off acknowledged**: skipped cells in cache_only mode rely on the analyst checking the drill-down's Skipped Expiries section. Skip-detail surfacing (commits `e5762d9` + `0b567af`) makes this honest, not silent.
- 2026-05-26 — **Prefetch strike-window planned for daily-union rewrite (Phase-7 follow-up).** Wide-sweep yielded 26% skip rate. Diagnosis (~92% of skips = `OfflineCacheMiss`): the current `prefetch_universe.py` picks `ATM ± N` strikes around ONE reference day per (sym, expiry). Sweep entries up to T-45 (~9 weeks before expiry) use the actual entry-day spot to pick strikes per SPECS §5; when spot drifts 10%+ across the entry window, the strategy picks strikes that the reference-day-anchored prefetch never cached. Replacement design: scan spot history across `[expiry − 45 TD, expiry − 1 TD]`, for each day call the strategies' own strike-picking rule against that day's bhavcopy, union the picked strikes across all days. Strike-window helper uses `max(N strikes per side, X% range)` so the rule self-adapts to symbols with wider spacing (indices) without manual per-symbol tuning. Estimated cache cost: ~2-3× current; estimated skip rate post-rewrite: <5% (mostly true corporate-action `MissingDataError`).
- 2026-05-26 — **Prefetch parallelism added (`--workers N`).** Same `mp.Pool` infrastructure as `sweep_grid`. Single-threaded prefetch was ~3 hr for the 6,240-contract universe; with the daily-union design pushing contract count to ~20k, single-thread is ~18-20 hr. Tested at 2 workers first (since 8 workers tripped NSE WAF during the sweep) before promoting to higher counts. Per-worker politeness sleep stays at 0.5s; aggregate request rate is bounded by `n_workers × 1/sleep_s`. Test command: `--symbols RELIANCE --strikes-per-side 1 --no-bulk-bhavcopies --workers 2` for a 150-contract subset.
- 2026-05-28 — **Blue-chip universe expanded from 40 to 48** ahead of the overnight prefetch run, once the prefetch pipeline + dashboard had absorbed the cost of the original 42-symbol universe (40 + PNB + BHEL extras). Reverses the 2026-05-24 entry that sized the universe down to 40 for v1. Added 8 NIFTY-50 members previously excluded as thin-options-liquidity (`APOLLOHOSP`, `DIVISLAB`, `HDFCLIFE`, `LTIM`, `SBILIFE`, `SHRIRAMFIN`, `TATACONSUM`, `TRENT`). BPCL + BRITANNIA still held out as the 2 thin-liquidity hold-outs. Total universe = **50 symbols** (48 blue chips + PNB + BHEL extras). Wide-sweep search space grows ~22% (1.85M → ~2.25M cells); the `MULTIPLE_COMPARISONS_CAVEAT` framing in any future Export-rule should reflect this scale factor. Survivorship-bias caveat in SPECS §6b.3 still applies and is unchanged.
- 2026-05-30 — **Pricing-arc completed empirical validation against the existing sweep parquet.** External-analyst hypothesis test on `sweep_5c336519a7dc.parquet` (pre-arc data, 1.69M cells) confirmed the phantom-fill bias: **91.1% zero-entry-volume rate at T-41..T-45 produced the +10.9% mean ROI gradient across all stocks**. Volume-by-entry-offset table runs monotonically from 0.3% zero-vol at T-1..T-5 → 91.1% at T-41..T-45, with mean ROI tracking -0.06% → +10.9%. The `IlliquidLegError` gate (`feat(p7.pricing.liquidity_gate)`, 94d535f) is the right intervention; first post-arc sweep is expected to collapse the gradient as zero-volume cells skip out. Recorded the analysis here so the diagnostic methodology is preserved as a reusable artifact for future calibration questions.
- 2026-05-30 — **Phase 8 MCP arc started** per BUILDER_CONSULTATION.md (513f88a). Reviewer-greenlit 13-commit roadmap across 7 sub-arcs exposing 16 read-only tools over stdio transport (Claude Code integration only; no HTTP). Decisions locked: per-tool `run_id` argument (not session-scoped), Pydantic v2 range pin `>=2.0,<3.0`, schema validator + behavior tests for caveats (Q4 both halves), metadata-stamp via parquet KV (Q5 — landed pre-arc as 5bc92f3 `chore(p8.engine.version_stamp)`). Source layout: `src/mcp/` with one file per sub-arc; tool implementations delegate to existing `src/analytics`, `src/engine`, `src/data` modules — the MCP layer is a transport, not new analytics. Honesty contract: every aggregated tool response inherits from `CaveatedResponse` with required `caveats: list[str]` field enforced via Pydantic field validator. The shared `PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT` constant (in `src/mcp/_models.py`) is the single source of truth for the load-bearing phantom-fill-bias warning emitted by every tool that touches a pre-arc parquet.
- 2026-05-30 — **MCP sub-arcs 3.1 + 3.2 + 3.3 landed** (10 of 16 planned tools). 3.1 universe (b42d4c2 skeleton, 0cc0b2c universe tools): `list_universe`, `expiries_for`, `list_strategies`. 3.2 time-series (661b1ff): `get_spot_series`, `get_option_series`, `get_options_chain` with pre-pricing-arc caveat firing when turnover column absent. 3.3 sweep queries (bacf5cf list_runs+query_sweep, 3264f37 cell_summary, d138fef heatmap): full analyst surface for sweep-result querying with MULTIPLE_COMPARISONS_CAVEAT for >100-cell grids (verbatim from `src/analytics/rank`), bootstrap CI (B=1000, seed=0) via `src.analytics.bootstrap`, auto-detected observations via `src.analytics.observations`, CVaR-5% via `pivot_cvar`. Plus 3 supporting commits: `chore(p8.mcp.consolidate)` (a98a29d — pulled the pre-arc caveat into shared constant, parameterized bootstrap method string, capped per_trade list), `fix(observations.roi_column)` (58c4d96 — closed reviewer-surfaced calibration miss from 33f19ae where observations read `roi_pct_annualized` against a per-trade-calibrated threshold), `fix(p8.mcp.heatmap.dead_comprehension)` (66ff72b — dropped O(n×m) per-cell list-build that was immediately overwritten by a try/except). Test count grew 555 → 678 over the arc; remaining MCP sub-arcs: 3.4 backtest replay (`backtest_one`, `sweep_windows`), 3.5 diagnostics (`skip_summary`, `data_quality`), 3.6 research helpers (`compare_cells`, `bootstrap_ci`), 3.7 docs.
