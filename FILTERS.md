# FILTERS.md — trade gates & portfolio filters

**Purpose.** A single reference for *every* condition that affects whether a trade/cell
(a) can be **priced at all**, or (b) is **selected into a portfolio / view**. These are two
fundamentally different kinds of filter and this file keeps them separate on purpose:

| | **Part A — Disqualification gates** | **Part B — Portfolio-construction filters** |
|---|---|---|
| Question | *Can this trade even be priced from the data?* | *Of the trades we CAN price, which do we keep?* |
| When | During the sweep / materialize / heatmap-render | **After** a cell is priced and passes `min_n` |
| Effect | No P&L row exists (skip / silent-drop / mask) | The trade exists & has P&L; we include or exclude it |
| Owner | Data + engine correctness (loud, mechanical) | Strategy / portfolio construction (a research choice) |
| Reversible? | No — absence of data is absence of data | Yes — change the filter, re-select, no re-sweep |

The cardinal rule that follows from the split: **a gated trade (Part A) has no P&L; a filtered
trade (Part B) has P&L we chose not to use.** "absence ≠ loss" for Part A; "excluded ≠ bad" for Part B.

**How this file is maintained.** Part A must stay in lockstep with the engine — each gate cites a
`file:func` so it can be re-verified; if the engine adds/removes a gate, edit Part A in the same
commit. Part B is a growing catalog of *opt-in* selection criteria — add one with the template in
§B.0 (don't implement here; this file is the registry + spec, the logic lives in `src/`).

Provenance: Part A was empirically verified against sweep `16277b27e2a8` and the raw NSE bhavcopies
during the 2026-06 logic review (see `LOGIC_REVIEW.md` F11/F12 for the audit + sample evidence).

---

## Part A — Trade disqualification gates (current, authoritative)

Every way a *planned* cell `(strategy, symbol, expiry, entry_offset_td, exit_offset_td)` fails to
produce a usable value. Tag legend: **[logged]** lands in `sweep_*_skipped.parquet` with a
`skip_reason`; **[silent]** returns `None`, appears in *neither* parquet; **[fatal]** is not in
`_SKIPPABLE_ERRORS` and aborts the sweep; **[mask]** the trade priced but is hidden at render.

### Layer I — pre-pricing (`src/engine/sweeper.py::sweep_one`)
| # | Condition | Result |
|---|---|---|
| 1 | entry/exit date can't resolve — `trading_calendar.offset_trading_days` cache-miss | `OfflineCacheMiss` **[logged]** |
| 2 | entry spot missing — `spot_loader.load_spot(entry).empty` | `return None` **[silent]** (spot cache-miss → `OfflineCacheMiss` **[logged]**) |
| 3 | no OPTSTK chain for `(symbol, expiry)` on the **entry-day** bhavcopy — `strategies/_strikes.load_available_strikes` | `NoLiquidStrikeError` **[logged]** (entry bhavcopy uncached → `OfflineCacheMiss`) |
| 4 | strategy returns no trades | `return None` **[silent]** |

### Layer II — per-leg pricing (`src/engine/pnl.py`, EACH leg: straddle 2, strangle 2, condor 4)
| # | Condition | Result |
|---|---|---|
| 5 | contract parquet absent / never materialized (cache-only sweep) — `options_loader.load_option` | `OfflineCacheMiss` **[logged]** |
| 6 | contract exists but **no row on the entry OR exit date** — `_pick_fill_price` | `MissingDataError` "no traded row" **[logged]** |
| 7 | empty frame returned | `MissingDataError` "empty frame" **[logged]** |
| 8 | **zero/missing turnover OR volume on entry OR exit day** — `_pick_fill_price` | `MissingTurnoverError` **[logged]** — *dominant far-from-expiry killer* |
| 9 | recovered premium VWAP ≤ 0 (deep-OTM ill-conditioning) | `MissingTurnoverError` **[logged]** |
| 10 | **`oi == 0` AND `contracts_traded < 20`** (thin contract nobody held overnight) — `_pick_fill_price:332` | `MissingTurnoverError` **[logged]** — **F7**, RE-ADDED `a1b74e2` (closes my own F7 finding; this gate is *active*, not removed) |
| 11 | thin contract (`contracts_traded = volume // lot_size < 20`) **with oi > 0** and VWAP outside `[0.5×, 2×]` close band — `_pick_fill_price:343` | `MissingTurnoverError` **[logged]** |
| 12 | `lot_size` changed entry→exit (split / bonus / merger / corp action) — `_price_one_leg` | `MissingDataError` "lot_size changed mid-contract" **[logged]** |
| 13 | duplicate-date row, OR frame rows past `exit_date` (look-ahead) — `_pick_fill_price` / `_price_one_leg` | `LookaheadError` **[fatal]** (parser-bug tripwire — aborts, never silently picks) |

**Option C — the PASS gate (not a disqualifier, shown for context):** `contracts_traded = volume // lot_size ≥ 20` (`_VWAP_LIQUIDITY_BYPASS_CONTRACTS`, `pnl.py:136`, `_pick_fill_price:318`) → VWAP trusted **unconditionally**, bypassing both #10 (oi gate) and #11 (band check). Recalibrated **100k shares → 20 contracts** in `817d4e5` so the threshold is symbol-invariant (lot_size spans 75 NIFTY … 8000 PNB). The oi gate (#10) and band-reject (#11) therefore only ever apply to **thin (<20-contract)** legs.

### Layer III — post-pricing aggregation / render (`src/analytics/heatmap.py`, `src/mcp/heatmap.py`, `MIN_N_FOR_RANKING`)
| # | Condition | Result |
|---|---|---|
| 14 | cell has **< `min_n` (default 5) priced expiries** | **[mask]** — cell hidden (black) even though some trades priced |
| 15 | invalid pair `entry_offset_td ≤ exit_offset_td` | never planned (the upper-left black triangle) |

### Layer IV — upstream materialize-time (`src/data/bhavcopy_to_contract.py`) — these *cause* #5
| # | Condition | Result |
|---|---|---|
| 16 | contract `contracts == 0` on **every** cached day (never traded) | not materialized → later `OfflineCacheMiss` |
| 17 | `lot_size` excluded (cross-source sidecar↔bhavcopy mismatch) | not materialized → later `OfflineCacheMiss` |

### The multiplicative-liquidity insight (why multi-leg strategies empty out far from expiry)
A trade prices only if **every leg has non-zero volume on BOTH entry AND exit days**:
short-straddle/strangle = **4 leg-days**, iron-condor = **8 leg-days** — all must be liquid (#8).
Far from expiry, each OTM leg-day's P(liquid) is low, so the AND collapses fast; then Layer III #14
still requires ≥5 of the available expiries to clear or the cell is masked. Net: coverage on a
`(strategy, symbol)` is gated by its **thinnest leg**, and the heatmap's empty regions are a
*liquidity-geography* map, not a P&L signal. (Worked example: BAJAJFINSV strangle 56% filled vs
SBIN 83% — `LOGIC_REVIEW.md` F12.)

### Known gap
Conditions #2 and #4 are **[silent]** — they drop a planned cell into *neither* output parquet, so
`planned ≠ priced + skipped` (768 cells / 0.034% on sweep `16277b27e2a8`). Candidate fix: raise a
`MissingSpotError` / `NoTradesError` so they become **[logged]** skips and the accounting closes.

---

## Part B — Portfolio-construction filters (planned — registry + spec)

Selection criteria applied to **already-priced** cells/trades to build a portfolio or shape a view.
They never re-gate pricing; they choose a subset of valid trades. Implemented filters should live in
the analytics / web / MCP query layer (e.g. alongside `src/web/_filter.py` or as MCP query params),
**not** in the pricing engine. Changing a Part-B filter never requires a re-sweep.

### B.0 — Template for adding a filter
When you implement one, add an entry here with:

```
### B.n — <name>
- Type:       include | exclude | rank-threshold | rank-top-k
- Stage:      where applied (post-sweep analytics | web sidebar | MCP query param | ranker)
- Inputs:     columns / data it reads — and whether they exist yet (✅ available | ⛏ needs new computation)
- Parameter:  knob + default + range
- Direction:  what passes vs what's filtered out (pin this explicitly — short-vol intuition cuts both ways)
- Rationale:  the research reason
- Status:     planned | implemented (commit <sha>)
- Caveat:     1-line honesty note (selection bias, look-ahead risk, data dependency)
```

Two cross-cutting rules for any Part-B filter:
1. **No look-ahead.** The filter may only use information available on/before `entry_date` (e.g. an
   entry-day percentile computed from a *trailing* window — never a forward or full-sample one).
2. **Surface the count it removes.** Like `min_n`, a portfolio filter should report how many priced
   cells it excluded, so "filtered" never silently reads as "didn't exist."

### B.1 — IV-Percentile (IVP) filter — PLANNED (math built, wire-in pending in Phase 9.4)
- **Type:**       rank-top-k (cross-sectional rank within candidate universe)
- **Stage:**      portfolio candidate selection (post-sweep analytics; runs AFTER B.4 liquidity floor
                  per memoir §11 — IVP rank only operates on names that already cleared the floor).
- **Inputs:**     ✅ available. `data/cache/iv/{SYMBOL}.parquet` (per-symbol 30D CMI ATM IV history,
                  Series C `iv_cmi30_excl7` is the operator-locked default — built by
                  `src.data.iv_materializer.materialize_iv_history`, commit `9d65809`).
                  Time-series IVP rank computed by `src.analytics.ivp.compute_ivp`
                  (commit `52a9036`); cross-sectional top-N selector
                  `src.analytics.ivp.top_n_by_ivp`.
- **Parameter:**  `lookback_td=252` (default; memoir F5); `series="iv_cmi30_excl7"` (default;
                  operator-locked); cutoff/range knob on the Portfolio tab.
- **Direction:**  HIGH IVP passes (rich vol → favorable for premium sellers). Memoir §2: the
                  standard short-vol thesis. Sensitivity strip on the Portfolio tab will let the
                  operator scan deciles (0-9, 10-19, …, 90-99) to find the empirical sweet spot per
                  memoir §2.5.
- **Rationale:**  High percentile = "this name's vol is rich vs its own 1-year history." Combined
                  with regime gate (B.2) and earnings filter (B.3), forms the 3-layer risk
                  framework per memoir §3.7 — IVP captures per-name idiosyncratic vol mispricings
                  that the universe-level regime gate is structurally blind to.
- **Status:**     planned (wire-in). Math: `feat(p9.1.iv_materializer)` `9d65809`,
                  `feat(p9.1.analytics.ivp)` `52a9036`. Sweep wire-in: Phase 9.4.
- **Caveat:**     No look-ahead — `compute_ivp(symbol, as_of)` uses a TRAILING 252-TD window with
                  explicit NaN guards on today's value (closes the F5 silent-rank-NaN-as-0 bug per
                  memoir §21.4). ATM-IV built from thin far-OTM legs (see Part A #8) would be noisy
                  on low-liquidity names — the B.4 liquidity floor running first mitigates.

### B.2 — Regime gate filter — PLANNED (math built, wire-in pending in Phase 9.4)
- **Type:**       universe-wide ON/OFF (skips the entire cycle when OFF)
- **Stage:**      cycle entry decision (BEFORE candidate selection — when OFF the universe doesn't
                  matter, no positions open this cycle).
- **Inputs:**     ✅ available. v1: `avg_single_name_realized_vol` over the candidate universe via
                  `src.analytics.regime.regime_percentile` + `regime_state` (already shipped). v2:
                  India VIX series via `src.data.india_vix_loader` →
                  `data/cache/india_vix.parquet` (Phase 9.0 deliverable). Phase 9.6 swaps v1 → v2.
- **Parameter:**  `threshold_pct=75.0` (default per memoir §3.1; production may use 90 for
                  less-aggressive sit-out); `lookback_td=252`.
- **Direction:**  Cycle opens when percentile ≤ threshold ("ambient vol is in the lower three
                  quartiles" → trade). Cycle skips when percentile > threshold ("ambient vol
                  elevated" → sit out). NaN percentile → OFF per memoir §21.4 F9's
                  skip-when-uncertain convention.
- **Rationale:**  Per memoir §3.1: short-vol strategies systematically lose in vol-elevated
                  regimes (single-name mean-reversion correlations collapse, tail risk inflates).
                  Skipping high-vol cycles is the cleanest mitigation — better than per-name
                  filtering which is structurally blind to systematic risk.
- **Status:**     planned (wire-in). Math: pre-Phase-9 in `src.analytics.regime`; Phase 9.6 v1→v2
                  swap. Sweep wire-in: Phase 9.4 banner + cycle entry.
- **Caveat:**     No look-ahead — `regime_percentile` uses a trailing 252-TD window. v1's
                  `avg_single_name_realized_vol` reads from `engine.vol.realized_vol`, which returns
                  0.0 on insufficient data (NOT NaN); the regime path filters `rv == 0.0` as
                  "missing." Phase 9.6 v2 (India VIX) is the cleaner forward-looking signal vs the
                  v1 backward-looking realized proxy per memoir §3.7.

### B.3 — Earnings filter — PLANNED (math built, wire-in pending in Phase 9.4)
- **Type:**       exclude (universe-level; drops symbols with in-window Financial Results event)
- **Stage:**      portfolio candidate selection (BEFORE the IVP rank — drops feed the Portfolio
                  banner's "X candidates dropped: earnings in window" counter).
- **Inputs:**     ✅ available. `data/cache/events.parquet` (NSE Corporate Events feed, parsed
                  from `CF-Event-equities-*.csv`; built by `src.data.events_loader.load_events`,
                  commit `182cf1d` + case-norm fix `d824ef8`). Filter via
                  `src.analytics.earnings_filter.filter_universe_by_earnings` (commit `c7563d7`).
- **Parameter:**  Window = `[entry_date, exit_date + 1 calendar day]`. The `+1` buffer catches
                  the case where exit is the day BEFORE announcement per memoir §21.4 F10. No
                  knob; operator either trusts the filter or doesn't run it.
- **Direction:**  Symbols with any Financial Results event in window are DROPPED. Multi-category
                  PURPOSE rows (e.g. "Financial Results/Dividend") substring-match → dropped.
                  Non-Financial-Results events (Dividend, Fund Raising, Stock Split alone) DO
                  NOT trigger the filter per memoir §17.5.
- **Rationale:**  Per memoir §3.7 (Layer 2 of the 3-layer risk framework): earnings announcements
                  are scheduled per-name catalysts that the regime gate (universe-wide) is
                  structurally blind to. A name at high IVP because the MARKET knows its earnings
                  are coming will look "rich" to a naive IVP filter; the earnings filter intercepts
                  before the catalyst hits.
- **Status:**     planned (wire-in). Math: `feat(p9.0.events_loader)` `182cf1d`,
                  `feat(p9.2.analytics.earnings_filter)` `c7563d7`. Sweep wire-in: Phase 9.4.
- **Caveat:**     **5-14 day lookahead documented and accepted** per memoir §17.7 — the events
                  CSV's DATE column is the board-meeting date, but Reg 29(1)(a) notice is filed
                  5-14 days BEFORE the meeting (= publicly knowable). Operator-accepted ("avoid
                  the earnings event, not model exact lead-time"); not a silent bug. Cold-cache
                  pass-through (`events_df=None`) keeps the universe intact when the CSV hasn't
                  been downloaded — the banner can detect via `events_df is None` AND
                  `n_dropped == 0`.

### B.4 — Liquidity floor (universe pre-filter) — PLANNED (math built, wire-in pending in Phase 9.4)
- **Type:**       rank-top-k (universe pre-filter; runs FIRST in candidate selection per memoir §11)
- **Stage:**      portfolio candidate selection — BEFORE B.1 IVP and B.3 earnings. Memoir §11
                  intent: only spend IVP-compute on names that already cleared the floor.
- **Inputs:**     ✅ available. Trailing-21-TD OPTSTK bhavcopy data via
                  `src.data.bhavcopy_fo_loader.load_bhavcopy_fo`. Score computed by
                  `src.analytics.liquidity.compute_liquidity_scores`; selector
                  `src.analytics.liquidity.top_n_by_liquidity` (commit `61c3fe9`).
- **Parameter:**  `lookback_td=21` (default; memoir F11); `n` = how many top-liquid names to
                  carry forward to the IVP rank (typical: ~25-50 from a universe of ~150-200).
- **Direction:**  Top N PASS (most-liquid names survive). Per memoir §11.b: "the most-traded
                  symbols" — high score = high daily total OPTSTK contracts averaged across the
                  21-TD window.
- **Rationale:**  Per memoir §11: the universe at backtest date D = `{symbol where bhavcopy_fo[D]
                  has OPTSTK rows}` ≈ 150-200 names. Most are too thin to support a 5-stock
                  portfolio cycle without each leg hitting Part-A's `volume==0` gate. The
                  liquidity floor pre-filters to names where the strategy can actually clear Part
                  A on entry day.
- **Status:**     planned (wire-in). Math: `feat(p9.2.analytics.liquidity_rank)` `61c3fe9`.
                  Sweep wire-in: Phase 9.4 candidate selection. Surface-the-count: caller reports
                  `len(universe) - len(top_n_by_liquidity_output)` to the banner.
- **Caveat:**     **Documented deviation from the memoir's code sketch**: implemented per-day
                  total → mean across days (matches English description "average contracts
                  traded"), NOT the sketch's `sub['contracts'].mean()` per-row mean (which would
                  punish symbols with a fat ATM + many skinny OTM strikes). Reviewer challenge
                  surface left open in the commit message. OPTSTK-only — OPTIDX (index options)
                  out of scope through Phase 11. NaN score when symbol has fewer than 50% of
                  lookback distinct trade dates (insufficient sampling); NaN scores EXCLUDED from
                  top-N ranking.

### B.5 — Sector concentration cap — PLANNED (no math yet; placeholder for Phase 9.4)
- **Type:**       cap-per-bucket (limits N per sector after IVP rank)
- **Stage:**      final candidate selection — AFTER B.1 IVP and B.3 earnings have produced a
                  ranked list. Re-orders / drops to honor the cap.
- **Inputs:**     ⛏ **Sector mapping not yet wired.** Needs a per-symbol sector assignment table
                  (NSE Industry Code → sector bucket). The 50-symbol universe is dominated by
                  Financials + Energy + IT; a 5-stock cycle with no cap can end up 3-of-5
                  Financials on any given day.
- **Parameter:**  `max_per_sector` (typical: 2 — cycle of 5 with max 2 per sector forces at least
                  3 sectors represented).
- **Direction:**  Names PASS subject to the cap; once a sector hits cap, lower-ranked names in
                  that sector are skipped and the next-ranked name in any other sector takes the
                  slot.
- **Rationale:**  Per memoir §3.7 + Phase 9.4 `feat(p9.4.concentration_correlation)` — short-vol
                  P&L is highly correlated within sectors when sector-wide volatility events hit
                  (rate moves for Financials, oil shocks for Energy, etc.). The 3-layer risk
                  framework's structural-risk layer (Layer 1) is the regime gate; sector
                  concentration is the soft constraint that prevents the candidate-selection
                  step from concentrating risk WITHIN a single trading cycle.
- **Status:**     placeholder. No math built; lands inside Phase 9.4 cycle drilldown / final
                  selection commit, not as its own analytics module.
- **Caveat:**     Sector mapping itself becomes a maintained data artifact (NSE periodically
                  reclassifies names); cold-cache pass-through (no mapping → no cap applied) keeps
                  the v1 backtest from failing when the table is absent.

### Other likely Part-B filters (placeholders — describe when scoped)
- **Higher `min_n`** — require more than 5 expiries for portfolio inclusion (stability over coverage).
- **Dispersion / tail caps** — exclude cells with `std_roi` or `CVaR-5%` beyond a threshold
  (portfolio risk control). Inputs ✅ available from per-cell stats.
- **Cost/slippage realism floor** — exclude cells whose edge is within the cost band.
