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
| 10 | thin contract (vol < 100k) with VWAP outside `[0.5×, 2×]` close band | `MissingTurnoverError` **[logged]** |
| 11 | `lot_size` changed entry→exit (split / bonus / merger / corp action) — `_price_one_leg` | `MissingDataError` "lot_size changed mid-contract" **[logged]** |
| 12 | duplicate-date row, OR frame rows past `exit_date` (look-ahead) — `_pick_fill_price` / `_price_one_leg` | `LookaheadError` **[fatal]** (parser-bug tripwire — aborts, never silently picks) |
| — | *(removed in P1.7: the old `oi==0` IlliquidLegError gate no longer disqualifies — `volume>0` ⟹ a fill exists)* | — |

### Layer III — post-pricing aggregation / render (`src/analytics/heatmap.py`, `src/mcp/heatmap.py`, `MIN_N_FOR_RANKING`)
| # | Condition | Result |
|---|---|---|
| 13 | cell has **< `min_n` (default 5) priced expiries** | **[mask]** — cell hidden (black) even though some trades priced |
| 14 | invalid pair `entry_offset_td ≤ exit_offset_td` | never planned (the upper-left black triangle) |

### Layer IV — upstream materialize-time (`src/data/bhavcopy_to_contract.py`) — these *cause* #5
| # | Condition | Result |
|---|---|---|
| 15 | contract `contracts == 0` on **every** cached day (never traded) | not materialized → later `OfflineCacheMiss` |
| 16 | `lot_size` excluded (cross-source sidecar↔bhavcopy mismatch) | not materialized → later `OfflineCacheMiss` |

### The multiplicative-liquidity insight (why multi-leg strategies empty out far from expiry)
A trade prices only if **every leg has non-zero volume on BOTH entry AND exit days**:
short-straddle/strangle = **4 leg-days**, iron-condor = **8 leg-days** — all must be liquid (#8).
Far from expiry, each OTM leg-day's P(liquid) is low, so the AND collapses fast; then Layer III #13
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

### B.1 — IV-Percentile (IVP) filter — PLANNED (stub, not yet implemented)
- **Idea (operator, 2026-06):** filter cells by the entry-day implied-volatility percentile of the
  underlying — e.g. exclude entries whose IVP is outside a chosen band.
- **Inputs:** ⛏ **IVP is not currently computed anywhere.** The engine has *realized* vol
  (`src/engine/vol.py`, close-to-close, from the spot cache) but **no implied-vol inversion**.
  Implementing IVP requires: (a) invert option premium → IV (Black-Scholes/Black-76) per
  contract/day, (b) build an ATM-IV series per symbol, (c) rank each entry-day IV against a trailing
  window → percentile. That's a real new compute step (its own spec + tests), upstream of this filter.
- **Direction — PIN BEFORE IMPLEMENTING:** the standard short-vol thesis sells premium when IV is
  *rich* (high IVP), so "filter out high IVP" is the *opposite* of the usual edge — decide whether
  the intent is to avoid event-driven IV spikes (which often precede large moves that hurt short
  strangles/straddles) or something else, and write the rationale in when it lands.
- **Status:** planned. **Caveat:** IVP needs a clean, no-look-ahead trailing window; an
  ATM-IV built from thin far-OTM legs (see Part A #8) would itself be noisy on low-liquidity names.

### Other likely Part-B filters (placeholders — describe when scoped)
- **Liquidity floor** — exclude cells whose legs are below a min entry volume / OI (a softer,
  portfolio-level version of the Part-A `volume>0` gate; lets you demand *meaningful* liquidity, not
  just non-zero). Inputs ✅ available (`entry_volume`/`entry_oi` in `legs_json`).
- **Higher `min_n`** — require more than 5 expiries for portfolio inclusion (stability over coverage).
- **Regime filter** — include only bullish / neutral / non-bullish regime entries. A session-state
  key (`mp_regime_filter`) already exists in the web app but is **not yet wired**; needs an entry-day
  regime label per symbol.
- **Dispersion / tail caps** — exclude cells with `std_roi` or `CVaR-5%` beyond a threshold
  (portfolio risk control). Inputs ✅ available from per-cell stats.
- **Cost/slippage realism floor** — exclude cells whose edge is within the cost band.
