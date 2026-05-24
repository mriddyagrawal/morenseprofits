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

Each phase ends with **tests passing** + **at least one commit** + a status note added to this file. Commits inside a phase should each be small and stand alone. The reviewer reviews every commit; blocking issues are addressed before the next commit.

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

Commits:
1. `feat(p1): spot_loader — cached stock_df wrapper with parquet store`
2. `feat(p1): options_loader — cached derivatives_df wrapper`
3. `feat(p1): expiry_calendar — monthly expiries per symbol, with caching`
4. `feat(p1): trading_calendar — NSE trading days from spot series`
5. `test(p1): data layer unit tests — schema, caching, no-network-on-hit`

Exit criteria:
- Second call to any loader is < 50ms (disk hit, no network).
- All returned DataFrames conform to schemas in SPECS.md.
- `pytest tests/test_data.py` green.

### Phase 2 — Universe selection
**Goal:** Reproducible stock-category definitions.

Commits:
1. `feat(p2): blue_chip universe — Nifty 50 snapshot list with source citation`
2. `feat(p2): momentum-based bullish / non-bullish classifier`
3. `feat(p2): universe CLI — `python -m src.universe.cli --as-of 2024-01-01``
4. `test(p2): universe membership stability + classifier determinism`

Exit criteria:
- Re-running classifier with the same `as_of` date yields identical membership.
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
2. `chore(p7): cache-hit telemetry; flag any uncached data fetches`
3. `chore(p7): final commit — Phase 7 complete — project final`

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
