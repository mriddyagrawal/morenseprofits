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

Commits:
1. `feat(p3): Trade + Leg dataclasses; per-trade P&L kernel`
2. `feat(p3): ShortStraddle strategy — picks ATM CE+PE at entry_date for given expiry`
3. `feat(p3): cost model — STT, brokerage, exchange txn fees (sell side STT only on options)`
4. `feat(p3): single-trade smoke run — RELIANCE Jan 2024, entry T-15, exit T-1`
5. `test(p3): hand-computed P&L verification on 2 fixtures`

Exit criteria:
- One hand-checked trade matches the engine output to within ₹1.
- Engine refuses to price if any required data is missing (no silent interpolation).

### Phase 4 — Parameter sweep + multi-strategy framework
**Goal:** Run thousands of backtests across the cartesian grid; add 4 more strategies.

Commits:
1. `feat(p4): Strategy protocol + registry`
2. `feat(p4): sweeper — (strategy × stock × month × entry_offset × exit_offset)`
3. `feat(p4): LongStraddle, ShortStrangle, LongStrangle, IronCondor strategies`
4. `feat(p4): results store — parquet per (strategy, run_id)`
5. `perf(p4): parallelize sweep with multiprocessing.Pool`
6. `test(p4): sweep determinism — same inputs → identical results`

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

Commits:
1. `feat(p6): streamlit app skeleton — sidebar nav, stock picker, strategy picker`
2. `feat(p6): per-stock dashboard — bar charts of avg P&L by (entry, exit)`
3. `feat(p6): trend tab — YoY decay, MoY seasonality`
4. `feat(p6): cross-stock ranker — best (strategy, params) per stock category`
5. `feat(p6): caveats banner — survivorship + multiple-comparisons disclosures always visible`

Exit criteria:
- `streamlit run app.py` opens a working report on the cached results.
- Every number in the UI is traceable to a row in the results parquet.

### Phase 7 — Polish, docs, perf audit
Commits:
1. `chore(p7): README — quickstart, data refresh, how to add a strategy`
2. `feat(p7): user-curated-universe skill — operator supplies their own stock list per session, overriding blue_chip(); satisfies SPECS §6b.3 mitigation #2 (point-in-time membership) at the source. Deferred per change-log 2026-05-24.`
3. `feat(p7): BLUE_CHIP_BY_QUARTER point-in-time membership for true survivorship-bias-free backtests.`
4. `chore(p7): final commit — Phase 7 complete — project final`

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
