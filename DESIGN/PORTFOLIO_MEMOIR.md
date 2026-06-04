# PORTFOLIO_MEMOIR.md — Portfolio & Inspect tabs design log

> A long-form record of the design conversation that produced the Portfolio tab + Inspect tab plan. Captures decisions taken, decisions deferred, decisions rejected, open empirical questions, and the rationale behind each. Read this AFTER `DESIGN_SPEC.md` (which captures the Phase-6 UI), and BEFORE writing builder prompts for the new tabs.
>
> Author: Claude, in conversation with the operator. Dates 2026-06-01 → 2026-06-04. Style: "memoir" — preserves the trail of reasoning, not just the final state, because future-you will want to see WHY we chose what we chose.

---

## 0. The fundamental shift

Everything that came before was **per-cell research** — given a (strategy, symbol, entry_offset, exit_offset) cell, what's its historical edge? The Leaderboard, Per-stock, Heatmap, and Trends tabs are all variants of "look at one cell, look at many cells, look at it over time."

This new tab is **portfolio backtesting** — given a SET of rules for which positions to open and when, what would my account balance have done? The unit of analysis changes from per-trade ROI on margin (a normalized %) to **portfolio P&L per cycle in rupees**. The risk metrics change from per-cell median to **portfolio Calmar, Ulcer, max-drawdown-in-rupees**. The drilldown changes from "see the 24 trades that built this cell" to "see which 5 stocks I traded in this cycle, and why."

This is the transition from backtesting individual ideas to **simulating an actual trading book**.

---

## 1. Decisions taken (final, frozen for v1)

| # | Decision | Rationale |
|---|---|---|
| 1 | Two new tabs: **Portfolio** + **Inspect** | Different mental models; Inspect doubles as a standalone contract viewer not just a drilldown destination |
| 2 | **Monthly cycle cadence** | Open all positions at T-N before each monthly expiry, close at T-M before, dead between. Matches existing sweep grid. No daily decision overhead. |
| 3 | Universe = **all stocks present in the bhavcopies** | Eliminates survivorship bias (user's choice). The point-in-time liquid filter then narrows from there per-cycle. |
| 4 | Strategies in scope for v1: **short_strangle, short_straddle** | Short-vol family. Iron condor stays in the existing sweep but isn't the focus for portfolio v1. |
| 5 | Sizing default: **equal-margin (option b)** | Each position blocks ~the same rupee margin. Works with integer-lot constraint. Easy to defend. |
| 6 | **Drop stop-loss + stop-profit entirely** | EOD-only stop simulation is right-biased; tastytrade empirics suggest stops HURT short-vol Calmar; stops are emotional management, not return improvement. See §8 for full rationale. |
| 7 | **STT on options moved to 0.15%** *[REVISED 2026-06-04: framing pending web verification]* | The original framing claimed 0.0625% was "stale pre-2023" and the 2023 Finance Act reduced STT. A subsequent reviewer flagged this as **likely backwards** — the 2023 Finance Act may have RAISED options-sell STT from 0.05% → 0.0625% (eff. 2023-10-01), making the code's existing 0.000625 the **current statutory rate**, not stale. **HOLD the STT commit until the rate is web-verified.** Two possible commit messages: (a) if reviewer is right → `chore(p8.cost.stt_conservatism_buffer)` with rationale "deliberate ~2.4× conservative buffer over statutory 0.0625%"; (b) if my original claim was right → `fix(p8.cost.stt_correction)` with original rationale. Same code change, different rationale, different commit. See §9 for the full pending-resolution writeup. |
| 8 | **IVP filter via Black-Scholes IV inversion** (NOT realized-vol proxy) | The operator vetoed the realized-vol proxy. Real IVP needs real implied volatility from option premiums. See §2 for the implementation plan. |
| 9 | **IVP buckets as a range-slider with deciles** (0–9, 10–19, …, 90–99) | Lets the operator scan across IVP windows and see how each metric behaves. Tunable sensitivity analysis, not a single fixed cutoff. |
| 10 | **Earnings filter IS in v1** — data acquired 2026-06-04 | Operator delivered the NSE Corporate Events CSV (`CF-Event-equities-06-09-2023-to-04-06-2026.csv`) covering the entire backtest window. 28,215 events / 2,390 symbols / coverage = 208 of 209 F&O symbols. Filter logic: skip `(symbol, expiry)` if any `PURPOSE` containing "Financial Results" lands in `[entry_date, exit_date + 1d]`. See §17 for full data spec. Originally planned as banner-only; promoted to v1 once data was in hand because (a) the layer-2 argument (see §18) makes earnings filtering structurally co-equal with the regime gate, not a v1.1 polish item, AND (b) the data is now available so the deferral reason evaporated. |
| 11 | Drilldown structure: **Portfolio → cycle table → 5 stocks → Inspect tab (contract trajectory)** | Three levels deep, each reveals a finer view. Inspect also accessible standalone via its own selectors. |
| 12 | **Slippage stays at 1% per side** for v1 | Operator's concern: 1% of a ₹5 premium is ₹0.05/share, which is tighter than realistic for thin Indian options. Concern noted; per-symbol tiering deferred. |
| 13 | **No tax modeling**, no capital opportunity cost modeling | The operator's reasoning: tax is a scaling factor on the back end and any investor should be carrying it in their head, not having it baked into the backtest. Same for the 7% risk-free opportunity cost. |

---

## 2. IVP computation — the standard methodology

The operator asked: "what window do you use for IVP? is there a standard way?" Here's what I know from training data; treat as "directionally right, verify before shipping":

### 2.1 The two terms operators often conflate

- **IV (Implied Volatility)** — the volatility number that, plugged into Black-Scholes, makes the BS price match the actual market premium. Different at every strike (vol smile) and every expiry (term structure).
- **IVP (Implied Volatility Percentile)** — for a chosen IV series, where does TODAY sit in its trailing-window history? E.g., "RELIANCE's 30D ATM IV today is at the 72nd percentile of its trailing-252-day history."
- **IV Rank** — tastytrade variant: `(IV_today − IV_min_52wk) / (IV_max_52wk − IV_min_52wk) × 100`. More volatile than IVP; common in retail tools.

**For our portfolio strategy: use IVP, not IV Rank.** Percentile is more robust to single-day extremes (one COVID-day IV spike doesn't dominate the next 52 weeks of IV Rank readings).

### 2.2 Constructing the daily IV series *[REVISED 2026-06-04 — forward-based BS + near-expiry exclusion]*

The previous Claude was right and I had this loose:

> **You can't rank today's 28-DTE ATM IV against last month's 7-DTE ATM IV.** The numbers aren't comparable because IV term structure inflates near expiry.

Standard fix: **30-day constant-maturity ATM IV**, constructed daily, using **forward-based Black-76 inversion** and **excluding near-expiry contracts** (CBOE VIX convention):

1. Each trading day, find the two listed MONTHLY expiries that bracket 30 calendar days from today.
2. **Skip the front-month contract if its DTE < 7.** Numerical-stability rule, per CBOE VIX practice. A 1-DTE ATM option has tiny vega (~21 per share at S=1000) so 1 rupee of premium noise → 5 vol-points of IV swing — the reading is unreliable. When front is dying (<7 DTE), use the next two monthlies instead and interpolate 30D from those.
3. For each used expiry, find the **ATM strike** (closest listed strike to spot at close).
4. **Extract the synthetic forward via put-call parity at the ATM strike** *[REVISED 2026-06-04]*: `F = K_atm + (C_atm − P_atm) · exp(r·T)`. This absorbs dividends, borrow costs, and any carry implicitly — cleaner than guessing `q` per-stock-per-day (Indian companies don't pre-announce dividends uniformly).
5. **Invert with Black-76 on F**, not Black-Scholes on spot+rate:
   - `C = exp(−r·T) · [F·Φ(d1) − K·Φ(d2)]` for calls
   - `d1 = (ln(F/K) + σ²·T/2) / (σ·√T)`, `d2 = d1 − σ·√T`
   - Solve for σ via Newton-Raphson. Vega for Black-76: `exp(−r·T)·F·√T·φ(d1)`.
6. **Linear interpolation in variance space** between the two used expiries to the 30-day target:
   - `var_30 = var_near × (DTE_far - 30) / (DTE_far - DTE_near) + var_far × (30 - DTE_near) / (DTE_far - DTE_near)`
   - `IV_30 = sqrt(var_30)`
7. Methodology note: this interpolates **annualized σ²** linearly in DTE. CBOE VIX convention interpolates **total variance σ²·T** linearly in T. Sub-1% difference for ~28D + ~58D brackets; documented choice, not a bug.
8. That's your single number for the day (per symbol).

This gives one IV value per symbol per trading day. Across a year you have ~250 values per symbol. Then IVP = "where does today's value sit as a percentile of these trailing 252 values?"

#### Why forward-based (not spot+rate)

For single-stock options, the BS formula on (spot + rate) ignores dividends and borrow costs. For Indian single stocks the dividend yield isn't a clean daily input (dividends are board-decision events, not continuously priced). Extracting the **synthetic forward** from the observed option chain itself via `F = K + (C − P)·e^(rT)` at ATM bypasses the missing-input problem — the option market already prices the forward, you just read it off. Then Black-76 (which is Black-Scholes on a forward) gives the cleanest IV.

ATM minimizes (but doesn't fully remove) residual term-structure mis-specification. Across-strike smile fitting is a Phase 8.2+ refinement.

#### Why skip near-expiry

Near-expiry ATM options have:

| DTE | sqrt(T) | Vega (S=1000) | 1₹ premium noise → IV swing |
|---:|---:|---:|---:|
| 1 | 0.052 | ~21/share | **5.0 vol points** ← chaos |
| 7 | 0.138 | ~55/share | 1.8 vol points |
| 28 | 0.277 | ~110/share | 0.9 vol points |
| 60 | 0.405 | ~160/share | 0.6 vol points |

5× more noisy at 1 DTE vs 28 DTE. CBOE VIX excludes anything below ~23 DTE for the index calculation. For our 30D-target with Indian monthly-only single stocks, the 7-DTE threshold is the pragmatic choice — drops the truly-chaotic readings without throwing away too much of the front-month coverage.

### 2.3 The lookback window for the percentile rank

Standard choices, with trade-offs:

| Window | Pros | Cons |
|---|---|---|
| **252 trading days (1 year)** | Standard institutional choice. Captures full annual cycle including earnings seasons. | Slow to react to regime shifts. |
| 126 TD (6 months) | More responsive. | Earnings seasons skew the distribution. |
| 63 TD (3 months) | Quickly captures recent regime. | Too noisy; today often sits at extremes purely from recency. |

**My pick: 252 trading days.** Match the standard. Make it a tunable parameter (252 / 126 / 63) but default to 252.

### 2.4 What we need to build

This is real infrastructure work, not a casual addition. The plan:

**`src/engine/iv.py`** — new module:
- `bs_implied_vol(premium, spot, strike, time_to_expiry, rate, option_type)` — Newton-Raphson root-finder on the Black-Scholes price. ~50 lines including the convergence guards.
- `compute_atm_iv(symbol, date)` — finds ATM strike on `date`, queries option premium from cache, inverts to IV. Returns NaN if premium is bad (zero volume, deep OTM, etc. — uses the Part A gates from `FILTERS.md`).
- `constant_maturity_iv(symbol, date, target_dte=30)` — interpolates between bracketing expiries.

**`src/engine/iv_materializer.py`** — script that builds the per-symbol IV history:
- Iterates over `(symbol, trading_day)` in the bhavcopy cache.
- Computes the 30D constant-maturity ATM IV per row.
- Writes to `data/cache/iv/{SYMBOL}.parquet` with columns `(date, iv_30d_atm, iv_source_near_expiry, iv_source_far_expiry, status)`.
- Status column carries any FILTERS-style skip reason ("premium_zero", "no_bracket", "inversion_failed") for honesty.

**`src/analytics/ivp.py`** — the percentile-rank computation:
- `compute_ivp(symbol, as_of_date, lookback_td=252)` — reads the IV history, computes the percentile rank of today's IV against the trailing window. Returns NaN if insufficient history.

**Estimated build cost: 3-5 days.** This is the biggest single piece of new infrastructure for the Portfolio tab.

### 2.5 IVP buckets in the UI

Per the operator's request, the Portfolio tab will have an **IVP range slider**:

```
IVP filter range:
[0 ─────●═════●──────── 100]
        60    80
```

And a **sensitivity strip** below the equity curve — a line chart showing how each key metric (Calmar, median cycle return, CVaR-5%, max DD) evolves as the IVP window slides across:

```
IVP window: 0-20  20-40  40-60  60-80  80-100
Calmar:     ─●────●─────●─────●──────●─
CAGR:       ─●────●─────●──●──────●──
CVaR-5%:    ─●────●─────●──────●─────●─  ← collapses at top
```

**This is the diagnostic that will tell the operator whether the IVP edge is real, monotonic, or just earnings-tail noise.** If 80-100 has the best CAGR but worst CVaR, that's the earnings concentration biting. If 60-80 is the sweet spot, ship that as the default.

---

## 3. Regime gate — the operator's questions answered

The operator pushed hard on the regime gate design. Most of the pushback was right.

### 3.1 "75% means we won't be trading 25% of cycles. Is that real?"

Yes — and it's actually on the AGGRESSIVE side, not conservative. A 75th-percentile threshold means the gate flips OFF when ambient single-name vol sits in the top quartile of its trailing-year distribution. That includes:

- Genuine market crises (March 2020, Adani-Hindenburg week, election result days)
- Macro shocks (RBI surprise hike, US Fed surprise)
- Earnings season aggregate IV pop (April-May, October-November)
- Some periods that are just elevated for no clear reason

For a research v1, 25% sit-out is acceptable. For a deployment-grade tool, many shops use **90th percentile** (sit only 10% of cycles out, the truly extreme ones).

**v1 decision: make the threshold a slider, default to 75th, let the operator scan.** Lower thresholds = more sit-outs = smoother equity curve but potential missed-edge cost. The metric-vs-threshold chart should show this trade-off empirically.

### 3.2 "Could the gate fire for reasons we WANT in the backtest?"

YES. This is the operator's sharpest catch. A regime gate based on trailing realized vol fires on:

- ✅ Things we want to skip: market crashes, vol blowups, post-event panic
- ❌ Things we DO want in the backtest: routine quarter-end rebalancing volatility, FII outflow days, sector rotation periods, election uncertainty that resolves favorably

There's no way to distinguish these from a backward-looking vol signal alone. The gate WILL throw away some good cycles. The empirical question is: does it throw away more good cycles than bad ones?

**Test in v1: build the gate, run with it ON and OFF, compare equity curves.** If the gate substantially improves Calmar without hurting CAGR much, ship it. If it costs more in foregone gains than it saves in avoided losses, drop it. The mockup's "regime-gated days" gray vertical bars on the equity chart already visualize when the gate fired — perfect for this comparison.

### 3.3 "Are board meetings on different days for each symbol?"

YES — completely different. Each Indian listed company files its own NSE Reg 29(1)(a) board-meeting notice 5-14 days before its own quarterly results meeting. RELIANCE Q4 might be mid-May, HDFCBANK might be late April, INFY mid-April. There's some seasonal clustering (most names report in the same calendar weeks within each quarter) but the exact dates differ.

**Implication for the regime gate**: the regime gate is NOT about dodging earnings. Earnings are a per-SYMBOL event, handled by the per-symbol **earnings filter** (deferred to v1.1). The regime gate is about MARKET-WIDE vol regimes — moments when ambient single-name vol is elevated across the universe, regardless of which specific company has news.

These are two separate signals, two separate gates, addressing two different risks. The operator's instinct to question them together was right; the answer is "they're different problems."

### 3.4 "Shouldn't the regime gate be a check across the entire 50-stock universe?"

YES — that's exactly right. The regime gate is a market-wide signal computed across the WHOLE candidate universe, not per-symbol. Per-symbol is the IVP filter's job.

### 3.5 The "average across 50" correction (load-bearing)

I had this loose. The previous Claude was right:

> **"Average across 50 → portfolio-wide vol" is mislabeled.** The average of 50 single-name realized vols is **average single-name vol**, NOT portfolio vol. True portfolio vol depends on the correlation matrix; the average equals portfolio vol ONLY when all pairwise correlations = 1.
>
> For a regime signal your average is actually the right thing to use — it measures ambient single-name turbulence undiluted by diversification, which is precisely what threatens a book of single-name straddles — **so keep the construction, just call it "average single-name realized vol."** (The distinction will bite you later when you do portfolio-level sizing, where the covariance genuinely matters and the average is wrong.)
>
> Also note the cheaper standard alternative: just read India VIX off the screen — implied, market-wide, no 50-stock computation needed.

**Locked-in correction:** the regime gate signal is **"average single-name realized vol across the universe."** Not "portfolio vol." For sizing, where covariance matters, use a different calculation (TBD when sizing-by-portfolio-risk lands).

### 3.6 "Volume? Spot volume or strike volume?"

The operator asked about volume here; I think the intent was about which VOLATILITY signal to use (vol = volatility, not volume, as we established three turns back).

**Answer:** the regime gate uses VOLATILITY computed from **spot price returns** (close-to-close log returns of the underlying). Volume (= trading turnover) is a Part A liquidity gate, not a regime signal.

- Spot vol input: daily close prices of each symbol, log returns, 21-TD rolling stdev annualized.
- Aggregated across the universe to a single regime number per day.

### 3.7 "Should we just use India VIX?"

**YES — that's the right v2 answer.** India VIX is NSE's daily-published implied-vol index based on NIFTY index options. It IS the market-implied 30-day vol forecast. No need to compute it from 50 stocks; it's a single number per day, published since 2008.

#### 3.7.1 Top-quartile = skip — sanity check on the logic

**Sane but heuristic, not a theorem.** Honest decomposition:

**Why it tends to work** — when India VIX is in the top quartile, three things usually correlate:
- (a) the market is anticipating something specific (RBI meet, US Fed surprise, election results)
- (b) realized vol on stocks compresses correlations toward 1, so diversification fails
- (c) VRP itself compresses because the implied price IS warranted by upcoming realized moves

**When it's wrong** — there are documented periods (post-March-2020, post-Volmageddon Feb 2018 in US, and likely Indian analogues we haven't checked) where high-VIX environments produced the BEST short-vol returns. The market was paying you extra premium AFTER the panic, and realized vol came in LOWER than implied. The gate would have made you sit out those cycles too.

**Net read**: the gate trades "missed-good-cycles" for "avoided-bad-cycles." The empirical test is whether the trade is net positive on YOUR data. The metric-vs-threshold sensitivity strip on the Portfolio tab will answer this directly — if 75th percentile substantially improves Calmar without hurting CAGR much → ship. If it costs more in foregone gains than it saves → drop or loosen the threshold.

Default to 75th for v1; let the operator scan empirically. **Don't bake it in as a theorem.**

**Implementation:**
- Scrape India VIX historical from NSE's website (no jugaad-data wrapper exists; needs a custom fetcher). ~half day of scrape work.
- Cache as `data/cache/india_vix.parquet` with columns `(date, india_vix_close, india_vix_high, india_vix_low)`.
- Regime gate reads this in v2 and uses the trailing-percentile-rank approach against actual market-implied vol.

**For v1:** ship with average-single-name-realized-vol as the proxy, deliver India VIX scraper as the immediate next commit. Banner the regime gate panel: "v1 uses average-single-name-realized-vol; India VIX integration in v1.1."

### 3.8 What strikes us about deltas in this context

The operator asked: "do we need to find delta so that we can compare the correct strikes to each other?" Yes — for IVP construction we need to pick a CONSISTENT strike to read IV from, and that strike is **ATM** (delta-50 calls, delta-50 puts). Without picking a consistent strike, you'd be reading different points on the vol smile each day and the IVP series would be polluted by smile-shape variation.

We do NOT need delta for the regime gate itself (which is a realized-vol or India-VIX signal, not an option-derived per-strike thing). We DO need delta for:
- IVP construction (pick ATM)
- Delta-25 strangle strike selection (deferred — see §6)
- Delta-hedging (deferred — see §6)

---

## 4. What's in DESIGN ∧ in IMPLEMENTATION PLAN

The intersection — what we'll actually build in the next 2-3 weeks of nuclear commits:

| Feature | Implementation note |
|---|---|
| Portfolio tab skeleton | `src/web/portfolio.py`, route via app.py tab nav |
| Cycle aggregator | `src/analytics/portfolio.py::build_portfolio_history(trades_df, rules)` — pure function returning monthly cycle P&L series |
| Equity curve + underwater drawdown chart | Plotly 2-panel; equity line + drawdown red-shaded subplot |
| Regime-gated days as gray vertical bars on equity chart | Visual showing when gate fired |
| Headline metrics strip (Total return, Calmar, Ulcer, Sortino, Max DD ₹, Win days %, Avg positions, Worst day) | One row of `st.metric` cards |
| Year-by-year stability table | Return / Calmar / max DD ₹ / Ulcer per year |
| Worst-10-days panel with attribution | Date / portfolio P&L / "what blew up" text |
| Concentration bar chart | per-name share of margin, equal-margin sizing |
| Pairwise correlation matrix | 5×5 (or N×N for top-N) of daily P&L correlations |
| **Strategy config block** with universe N, strategy, entry/exit, sizing, regime gate toggle+window+threshold, IVP filter toggle+window, earnings filter banner | Sidebar/in-tab controls |
| IVP range slider + sensitivity strip | Tunable + the metric-vs-IVP-range chart |
| Cycle drilldown table | Click a cycle → see which 5 stocks were traded with their per-cycle P&L |
| Stock drilldown → opens Inspect tab pre-filtered | Deeplink |
| Inspect tab (contract trajectory) | Standalone selectors + 5-line Plotly chart per FILTERS.md gap handling |
| `fix(p8.cost.stt_correction)` STT 0.0625% → 0.15% | Pre-Portfolio commit |
| `src/engine/iv.py` (BS inversion) | Real IV, not realized-vol proxy |
| `src/engine/iv_materializer.py` (build per-symbol IV history) | Required upstream of IVP |
| `src/analytics/ivp.py` (percentile rank) | Consumes the IV history |
| India VIX scraper + cache | Regime gate v2 signal (v1 ships with realized-vol proxy) |

**Estimated total: 7-10 days of nuclear-commit work**, sequenced roughly as:
1. STT fix (~10 min)
2. Cycle aggregator + Portfolio tab skeleton (~2 days)
3. Equity curve + underwater + metrics strip (~1 day)
4. BS IV inversion + materializer (~2-3 days)
5. IVP percentile + filter wire-in (~1 day)
6. India VIX scrape + regime gate v2 (~1 day)
7. Inspect tab (~1-2 days)
8. Drilldown wiring (~half day)

---

## 5. What's in DESIGN but NOT in implementation plan

These appear in the mockup or in our design discussion but aren't yet committed to a Phase-8 nuclear commit:

| Item | Why not in plan, what's needed |
|---|---|
| **Vol-targeted sizing (option c)** | See §7 for the practical issue. Fractional lots make this not directly tradeable. Listed as "proposed change to explore" but NOT in v1 implementation. Implementing would require a round-to-tradeable-lots step and the drilldown would need to show "intended vs actual" position size. |
| **Delta-25 strangle selection** | Mockup strategy-config caption shows "short_strangle (Δ-25)" but the current strategy picks strikes via `strike_offset_pct=0.02`. Requires the same delta computation as the BS-IV work (sub-product of the same BS code) so it's nearly free once IV inversion exists. But not in the v1 plan; ships as `feat(p8.strategy.delta_25_strangle)` follow-on. |
| **Sector concentration constraint** | "Max 2 from any sector" rule. Needs a sector mapping (we have stock tickers, not sector labels). Add to deferred list. |
| **Iron condor with equal-delta wings** | Currently uses equal-%-offset wings. Better in skew-asymmetric markets. Needs delta computation; sibling of Δ-25 strangle. Deferred. |
| **Strategy comparison view (overlay equity curves)** | Inside Portfolio tab, a radio toggle to overlay short_straddle vs short_strangle vs iron_condor equity curves. Useful but not v1. |

---

## 6. Deferred / proposed — not building this phase

Real, valuable ideas that we're consciously NOT pursuing in Phase 8 v1. They go to a "Proposed Phase 9+ extensions" list:

### 6.1 Tier-3 strategy flavors

- **Calendar spread** (sell front month, buy back month). Lower margin, lower P&L per trade, typically higher Calmar. Needs new strategy class with both-leg-different-expiry support — the engine currently assumes single-expiry trades.
- **Earnings vol-crush trade** (~4-day window before earnings, close day after). The highest-Sharpe variant of single-name vol selling per the original analysis. Completely different timeframe; would be its own tab and probably its own sweep. Requires the earnings calendar to be working.
- **Iron condor with equal-delta wings** (vs current equal-%-offset wings). Fixes the skew asymmetry. Shares the BS infrastructure with Δ-25 strangle.

### 6.2 Tier-4 institutional-grade

- **Delta-hedged short vol** (daily futures hedge to isolate vega + theta). The professional baseline for vol trading. Keeps ~half to two-thirds of raw return but Sharpe is 2-3× higher (per the original analysis — magnitudes are US-equity-derived and need empirical Indian verification). **The operator wants this in the proposed list** — explicitly mentioned as something to look into eventually. Listed as a serious deferred phase, not silently dropped.
- **Dispersion trade** (short NIFTY index straddle + long basket of single-name straddles). Profits when implied correlation > realized correlation. Pure VRP play, immune to market direction. Needs index option pricing in our pipeline + correlation tracking.
- **Variance-swap replication** (specific weighted portfolio of OTM options whose payoff is linear in realized variance). The cleanest VRP exposure; what hedge funds actually deploy. Path-independent. Heaviest infrastructure — needs strike-weighted option strips per the variance-swap formula.

### 6.3 Filter / risk additions

- **Sector concentration constraint** (max N from any sector). Requires sector mapping. One-line addition once mapping exists.
- **Per-symbol slippage tiering** (e.g., blue chips 0.5%, mid-cap 1.5%, small-cap 3%). Operator's concern about 1% being unrealistic is real — but per-symbol calibration needs intraday data. Tiered version is a half-day commit.

### 6.4 Tax / opportunity cost

- **Tax modeling** — explicitly out of scope per operator's instruction. "Modeling that will just reduce the profits by a set amount or by a scaling factor and nothing else. I truly don't care."
- **Capital opportunity cost (risk-free rate)** — same. "Any investor should have it in their mind. They shouldn't need that to be a part of the backtest itself."

---

## 7. The sizing trilemma (with operator's resolution)

When two short-vol books trade the same 5 names, the WAY positions are sized can completely change the resulting equity curve. Three options were on the table:

### Option (a) — Equal lots: 1 lot per name, always

- Pro: simplest, always tradeable (integer lots)
- Con: high-priced names (HDFCBANK ₹250K margin) dominate vs low-priced (PNB ₹105K margin). Your "diversified" book is actually concentrated in expensive stocks.

### Option (b) — Equal margin: each position blocks ~the same rupee margin

- Pro: each name is roughly equal capital deployed → equal P&L contribution per unit margin
- Pro: tradeable (round to nearest whole lot)
- Con: approximate (NSE lots are indivisible; "equal margin" usually devolves to "1 lot each except skip the most expensive")
- **OPERATOR'S PICK FOR V1**

### Option (c) — Vol-targeted: weight ∝ 1/realized_vol

- Pro: equalizes each position's contribution to portfolio P&L *variance*
- Pro: typically produces smooth equity curves; institutional standard
- Con: **fractional lots**. To put "27% of book in HDFCBANK" you'd need to hold 0.27 lots, which doesn't exist on NSE. Real implementations round to nearest whole lot, but the rounding error is large with 5-position books.
- Con: requires per-symbol realized vol (~free if we have spot cache)
- **Listed as proposed/deferred** in v1.1. If implemented, the drilldown needs to show "intended weight vs actual rounded weight" so the operator isn't surprised.

### The line the operator flagged for posterity

> "Most institutional short-vol books use vol-targeted because investors hate lumpy P&L. Retail-style 'sell premium where it's juiciest' uses equal-margin or carry-targeted."

**Plain-language gloss for future-you reading this:**

When a fund manager is showing returns to investors, lumpy P&L (big up months, big down months) looks worse than smooth P&L of the same average return. Investors anchor on "what was your worst month" more than "what was your average." So institutional managers SIZE FOR SMOOTHNESS — they accept lower headline returns in exchange for tighter month-to-month variation. Vol-targeted sizing accomplishes that.

A retail trader sizing their own book doesn't have an investor to impress and isn't optimizing for smoothness — they want maximum yield. So they put more capital where the premium-per-margin is highest, which often means high-IV (high-vol) names. That's "carry-targeted" — chasing the carry (yield).

You'll feel this in your bones once you've run a portfolio for a few months and your "best name" turns out to be the one that gave you the worst single bad day.

---

## 8. Why we DROPPED stop-loss and stop-profit (with reasons)

This was a real decision, not a casual omission. The reasons, for the record:

### 8.1 The empirical case from short-vol research

The largest published study of stop-loss policies on short premium strategies (tastytrade, n>50,000 backtests on US equity index and single-name options, ~2018-2022) found that **typical 2-3× credit-received stop-losses produce WORSE Calmar than no stops at all** on short straddles and short strangles.

Mechanism: most "would-be losers" recover via theta decay before expiry. A stop CRYSTALLIZES paper losses into realized losses, removing the very mechanism (time decay) that turns those losses around.

### 8.2 The simulation honesty case

Our sweep is end-of-day only. Simulating "stop fires at 1:47 PM when underlying crossed level" requires intraday option price data we don't have. The cheap proxy — "check at close, exit at next open" — is known to be **right-biased** (looks better than reality). On gap days, real stops blow through their intended level by 30-50% before fills happen.

So even if stops DID help in theory, the EOD-only backtest would falsely confirm them via simulation bias. We'd ship a feature whose backtest numbers were optimistic.

### 8.3 The "stops aren't risk management" framing

Risk management on a short-vol book is:
1. **Position sizing** — don't size any single position so large that a 3-sigma move kills the book
2. **Diversification** — N uncorrelated positions reduce single-name tail
3. **Regime gating** — don't open positions when ambient vol is in the top quartile
4. **Earnings filtering** — don't open positions across known event windows

Per-trade stops are **emotional management** — they give the operator a sense of "controlling" each trade. They're not actually return-improving in the empirical record on short-vol.

### 8.4 The honest statement

**v1 doesn't model stops. v2 won't either, unless empirical Indian-market evidence shows them helping.** If a future operator wants to test stops, the right move is a sensitivity analysis: run the backtest with stops at 1.5×, 2×, 2.5×, 3× credit received and see how Calmar changes. If Calmar improves at some stop level on Indian data despite the EOD bias, that's evidence worth following up.

---

## 9. STT change — rationale pending web verification *[REVISED 2026-06-04]*

`src/engine/costs.py::COST_MODEL_V1.stt_sell_options_pct` is currently `0.000625` (0.0625% of premium turnover, sell-side options).

**Operator's decision: update to 0.0015 (0.15%).** The code change itself is unambiguous and a single-line edit. **The RATIONALE for that change is contested and needs external verification before the commit lands.**

### 9.1 The two competing rationales

**Original framing (mine, 2026-06-04 morning):** The 0.0625% in the code was "stale pre-2023." The 2023 Finance Act REDUCED options-sell STT to 0.05%. The operator's 0.15% is a deliberate conservative overstate over the actual 0.05%. Commit type: `fix(p8.cost.stt_correction)`.

**Reviewer's framing (2026-06-04 afternoon):** The 2023 Finance Act RAISED options-sell STT from 0.05% → 0.0625% (effective 2023-10-01). So the code's existing 0.000625 IS the current statutory rate (not stale). The operator's 0.15% is then a deliberate ~2.4× conservative buffer OVER the statutory 0.0625%. Commit type: `chore(p8.cost.stt_conservatism_buffer)`.

### 9.2 Why this matters

Same code change either way. But:

- If the reviewer is right, the original framing is factually inverted and would ship under a wrong story. The "fix" framing would confuse future readers who'd look at the diff and see "0.000625 → 0.0015" without understanding it's not a correction of a stale rate but a deliberate buffer.
- If my original framing is right, the existing memoir wording stands.

A fix-every-backtest commit landing with the wrong rationale is worse than no fix yet. **HOLD the commit until verified.**

### 9.3 How to verify

Web Claude (with internet access) can verify in 30 seconds — look up the current statutory STT on options-sell in India under Finance Act 2023. Specifically:

- What was the options-sell STT rate before 2023-10-01?
- What was it changed to, and in which direction?
- What is the current statutory rate as of 2026?

Once verified, update §1 decision #7, this section, and the commit message accordingly.

### 9.4 What's certain regardless of which framing wins

- The current code value `0.000625` will become `0.0015` (single-line change).
- Affects every backtest in the project, not just the Portfolio tab. Net P&L and median ROI/yr on every cell will move slightly. The portfolio equity curve in the mockup (₹24.6L, +23%) is overstated by the (0.15% − statutory_rate) × turnover gap.
- Should land BEFORE any Portfolio tab work so all subsequent metrics inherit consistent costs.

---

## 10. Slippage at 1% — concern noted, retained

The operator raised the practical concern:

> "1% of the premium is if the premium is 5 rupees, then 1% is just 5 paisa out of that."

This is a real point. On a ₹5 deep-OTM option, 1% slippage = ₹0.05 per share haircut, which is TIGHTER than realistic for thin Indian options. Real bid-ask on thin strikes can be ₹0.50-1.00 per share, which is more like 10-20% slippage on a ₹5 premium.

**v1 decision: keep uniform 1% slippage.** Real per-symbol calibration needs intraday data we don't have. The Part A `MissingTurnoverError` gates (#8, #10, #11 in FILTERS.md) already drop the worst illiquidity cases before pricing happens, so the realized 1% applies to legs that DID clear the liquidity bar — for those, 1% is roughly defensible on blue-chip ATM strikes.

**Deferred follow-up:** tiered slippage by liquidity bucket (e.g., 0.5% top-50, 1.5% mid-cap, 3% small-cap). Half-day commit. Not blocking the Portfolio tab.

---

## 11. Survivorship bias — selection logic is right, but pricing coverage is the real blocker *[REVISED 2026-06-04]*

Operator's call: **universe = all stocks present in the bhavcopies**, not a fixed 50-stock list.

The SELECTION logic this implies is correct and survivorship-bias-free: the universe at any backtest date D is `{symbol where bhavcopy_fo[D].symbol unique values intersect OPTSTK rows}`. Filter by liquidity gate → candidate set → IVP rank within that set.

### 11.1 But — the "no code change" claim was glossy

Original wording said "no code change to the universe; just query the bhavcopy." That understates the problem. **Selecting a symbol point-in-time and pricing trades on it are different operations.**

- **Selecting** a 2024-Q1 trade on `RCOM` (Reliance Communications, delisted ~2019 — hypothetical for this example) only needs RCOM's row in the 2024-Q1 bhavcopies.
- **Pricing** that trade needs RCOM's option-chain parquets MATERIALIZED on disk for those expiries: `data/cache/options/RCOM/{EXPIRY}/{STRIKE}-{CE|PE}.parquet`.
- The materialized options/ cache currently covers **~50 survivor blue-chips** (plus PNB, BHEL — the prefetched universe). Delisted/merged names from 2023-2024 are NOT materialized.

So in practice, the Portfolio tab can SELECT delisted names via the bhavcopy query but won't be able to PRICE trades on them — they'd silently fail Part A gates (`OfflineCacheMiss` for the contract parquet) and drop out, leaving the same survivor-only set. Selection logic is right; coverage isn't.

### 11.2 Genuinely survivorship-free needs a data-expansion commit

The full point-in-time F&O universe across 2023-2026 is approximately 180-220 distinct symbols (some persisted across the window, some entered, some exited). To honestly claim survivorship-free backtests, all of those need to be materialized.

That's a real data-expansion: extend `scripts/prefetch_universe.py` to enumerate every symbol appearing in any bhavcopy over the window, then run the standard options prefetch over that wider set. Probably ~2-3× current prefetch runtime and disk usage.

**v1 ships with the current ~50-survivor cache**, but the survivorship banner on the Portfolio tab should be honest: "Universe is 50 survivor blue-chips; delisted/merged names from the period are excluded → returns are biased upward by the dropouts. Full survivorship-free analysis requires Phase 8.2 universe-expansion commit."

This is a meaningfully different claim than the original "no code change needed." Walking it back honestly.

---

## 12. The research vs ML philosophical question (memoir) *[REVISED 2026-06-04 — sample size restated]*

The operator raised: should we be deciding constraints by hand and testing them ("research"), or letting ML figure out constraints from signals?

**For predicting trade P&L directly: ML is a trap on this dataset.**

- Sample size *(REVISED)*: the current sweep is **1,103,923 priced rows** (verified empirically against `sweep_16277b27e2a8.parquet`), not the "~3,800" originally written. The "too few rows for ML" argument doesn't survive at 1.1M as originally stated. The argument still holds, but for a different reason: **rows are heavily correlated** (same contract priced across multiple (entry, exit) offsets, same expiry across many cells). The effective number of independent draws is closer to `expiries × symbols × strategies ≈ 24 × 50 × 5 ≈ 6,000` across the 3-year window. Still small for the dimensionality of any non-trivial ML model, but the correct framing is "correlated samples inflate the apparent N," not "N is tiny."
- Regime non-stationarity: 2023 patterns don't predict 2026; backtest performance overstates live
- The backtest-vs-live gap on ML strategies is notorious: typical 1.5 Sharpe backtest → 0.4 live

**For research / feature discovery: ML is useful.**

- Train a model on cell features → P&L; look at feature importance
- The model says "IVP, avg_volume, days_to_expiry matter most"
- You then make those hand-crafted filters that you can defend, audit, explain
- Model = hypothesis generator, not deployment artifact

**For per-trade explanation: LLMs are the killer use case.**

- For each cell, an LLM looks at strikes, premiums, spot path, IV path, volume, news
- Generates a 2-3 sentence narrative ("PNB Dec-2025 strangle lost because vol expanded 35 → 48 IV over the hold window, despite spot moving only 2%")
- This is "AI-assisted analyst," NOT "ML-as-trader"
- The operator's MCP plan IS this — contract trajectory chart + LLM reasoning = research partner
- This is genuinely novel and worth building

**Keep current research framework** (you choose constraints). Add MCP for per-cell explainability. Treat any future ML as a feature-discovery tool, not a trader.

---

## 13. The honest unknowns / open empirical questions

Things we genuinely don't know and shouldn't pretend to:

1. **Does the IVP edge exist on Indian single-name options?** Hypothesis. The sensitivity strip will show empirically whether high-IVP cells produce higher CAGR. If they don't, the IVP filter is theater.
2. **Does the regime gate at 75th percentile help or hurt Calmar on Indian data?** Run with-vs-without comparison once it ships.
3. **What's the actual statutory STT in 2026?** We used 0.15% conservatively; real may be 0.05% post-2023 Finance Act. Verify before deploying real-money calculations.
4. **What's the realistic slippage on Indian thin options?** 1% is a guess. Per-symbol calibration needs intraday data.
5. **Are the US-derived magnitudes (delta-hedging 2-3× Calmar, tastytrade stops hurt) valid on Indian single-names?** Probably directionally yes, magnitudes unverified. Don't quote these in operator-facing copy until verified locally.
6. **What's the correct IVP lookback?** 252 TD is my pick; could be 126 or 63. Test on the sensitivity strip once IVP infrastructure ships.

---

## 14. The chronological decision list

For the record, decisions taken over this conversation in the order they happened (revisions noted):

1. **Build a Portfolio tab.** Backtest framework moves from per-cell to portfolio-level.
2. **Drop stop-loss / stop-profit.** Empirical case + simulation bias + reframing risk management.
3. **Universe = all bhavcopy stocks.** Survivorship bias addressed.
4. **Cycle cadence = monthly.** Matches existing sweep grid.
5. **Sizing default = equal-margin.** Tradeable with integer lots; v1 simplest defensible choice.
6. **IVP via Black-Scholes inversion (not realized-vol proxy).** Real signal, not approximation.
7. **IVP range as a slider with bucket sensitivity strip.** Tunable + diagnostic.
8. ~~**Earnings filter as banner only for v1.** Real calendar deferred to v1.1.~~ **REVISED 2026-06-04: Earnings filter IS in v1.** Operator delivered the NSE Corporate Events CSV covering the entire backtest window. Data acquired → blocker removed. See §17 for data spec, §18 for the structural argument that earnings filter is co-equal with the regime gate (not v1.1 polish).
9. **STT 0.0625% → 0.15%.** Conservative cost overstatement.
10. **Drop tax + opportunity-cost modeling.** Operator carries these in their head.
11. **Slippage stays at 1%, per-symbol tiering deferred.** Concern noted.
12. **Regime gate = average single-name realized vol** (NOT portfolio vol — that's a different number). India VIX integration deferred to v1.1.
13. **Two new tabs: Portfolio + Inspect.** Inspect doubles as a standalone contract viewer.
14. **Contract trajectory chart with per-leg gaps.** Days where a leg fails FILTERS gates render as line breaks; other leg continues.
15. **2-D diagnostic table on Portfolio tab — gate ON/OFF × IVP decile, with per-bucket tail statistics.** Non-negotiable empirical test of whether IVP adds signal beyond the regime gate. See §18.4.
16. **Cross-sectional IVP as an alternative signal — noted, deferred.** Time-series IVP is the v1 pick; cross-sectional joins later if the 2-D diagnostic suggests it. See §19.

---

## 15. Glossary (for future-you reading this cold)

| Term | Meaning |
|---|---|
| **VRP** | Variance Risk Premium — the systematic gap between implied vol (what options price in) and subsequent realized vol (what actually happened). Source of short-vol edge. |
| **IV** | Implied Volatility — the vol value that makes the Black-Scholes model price the option at its observed market premium. |
| **IVP** | Implied Volatility Percentile — for a chosen IV series, where today's value sits as a percentile of its trailing-window history. |
| **IV Rank** | tastytrade-style metric: `(IV_today − IV_min_52wk) / (IV_max_52wk − IV_min_52wk) × 100`. More volatile than IVP. |
| **ATM / OTM / ITM** | At-the-money / Out-of-the-money / In-the-money. ATM = strike closest to spot. OTM call = strike above spot. ITM call = strike below spot. Reverse for puts. |
| **DTE** | Days to Expiry |
| **Constant-maturity IV** | IV interpolated to a fixed days-to-expiry (e.g., 30D), so today's number is comparable to last month's. |
| **Calmar** | Annual return ÷ max drawdown. Risk-adjusted return that punishes the tail, not just variance. |
| **Ulcer Index** | Measures depth × duration of drawdowns. Penalizes long underwater periods. |
| **Sortino** | Sharpe variant; only downside volatility in the denominator. |
| **CVaR-5%** | Mean of the worst 5% of trade outcomes. Tail-loss expectation. |
| **Equal margin** | Sizing where each position blocks roughly the same rupee margin. |
| **Vol-targeted** | Sizing where positions are weighted ∝ 1/realized_vol. Equalizes contribution to portfolio P&L variance. |
| **Carry-targeted** | Sizing where positions are weighted ∝ option carry (premium-per-margin). Maximizes yield, accepts lumpier returns. |
| **Delta-25 strangle** | A strangle whose strikes are chosen at the strikes whose delta equals ±0.25, rather than at fixed % from spot. Skew-aware sizing. |
| **Dispersion trade** | Short index vol + long basket of single-name vol. Profits from gap between implied and realized correlation. |
| **Variance swap** | Derivative whose payoff is linear in realized variance over a window. Path-independent. Replicable via a weighted strip of OTM options. |

---

## 17. Earnings calendar — data spec (added 2026-06-04)

### 17.1 Source

`CF-Event-equities-06-09-2023-to-04-06-2026.csv` at repo root, delivered by the operator. Source: NSE Corporate Events feed export.

### 17.2 Schema

| Column | Type | Notes |
|---|---|---|
| `SYMBOL` | string | NSE trading symbol — matches our bhavcopy symbol exactly |
| `COMPANY` | string | Full company name (for human reference, not used by filter) |
| `PURPOSE` | string | Multi-category, slash-separated. Examples: "Financial Results", "Financial Results/Dividend", "Bonus", "Stock Split", "Fund Raising" |
| `DETAILS` | string | Free-text description of the meeting agenda |
| `DATE` | date | Format `DD-Mon-YYYY`. **This is the BOARD MEETING date**, not the announcement date (typically the same day for results, but the notice was filed 5-14 days earlier). |

### 17.3 Coverage check

- **Total rows**: 28,215
- **Unique symbols**: 2,390
- **Date range**: 2023-09-06 → 2026-06-04 (covers entire portfolio backtest window)
- **F&O coverage**: 208 of 209 OPTSTK symbols from the most recent bhavcopy have entries (only `MCX` is missing — acceptable; it's the exchange entity, doesn't file the same way)
- **Per-symbol "Financial Results" event count**: 9-14 over the 33-month window for our typical names — consistent with quarterly reporting cadence

### 17.4 Known data quirk — TATAMOTORS restructuring

The legacy `TATAMOTORS` ticker has been restructured. The events file shows:
- `TMPV` (Tata Motors Passenger Vehicles Limited) — 13 events
- `TMCV` (Tata Motors Limited Commercial Vehicles) — 3 events
- `TATAMTRDVR` (legacy DVR share) — 4 events

`src/universe/blue_chip.py` includes "TATAMOTORS" in its hardcoded list. **Action item**: audit the blue_chip list against current bhavcopy tickers; replace `TATAMOTORS` with the appropriate successor (likely `TMPV` for the standard passenger-vehicles trading entity). The universe-widening to all bhavcopy symbols (per §11 / §1 decision #3) self-corrects this for the Portfolio tab, but the standalone `blue_chip(as_of)` function still returns the stale ticker.

### 17.5 Filter logic

```python
def has_earnings_in_window(events_df, symbol, entry_date, exit_date):
    sub = events_df[
        (events_df['SYMBOL'] == symbol)
        & events_df['PURPOSE'].str.contains('Financial Results', na=False)
        & (events_df['DATE'] >= entry_date)
        & (events_df['DATE'] <= exit_date + pd.Timedelta(days=1))
    ]
    return len(sub) > 0
```

Rules:
- **Filter ONLY on "Financial Results"** in PURPOSE. Don't skip on Dividend, Bonus, Fund Raising, Stock Split — those don't move IV the way earnings do.
- **+1 day buffer** after exit catches the case where exit is the day before announcement (vol is still elevated, gap risk still present).
- **No look-back buffer before entry** — IV starts pricing in earnings ~1-2 weeks before, but our entry T-N offset already accounts for hold-window-to-expiry spacing. Adding pre-entry buffer would be conservative; deferred decision.

### 17.6 Implementation plan

- `feat(p8.data.events_loader)` — `src/data/events_loader.py` reads the CSV, normalizes column whitespace and date parsing, caches as `data/cache/events.parquet`. ~half-day commit including tests.
- `feat(p8.portfolio.earnings_filter)` — wire `has_earnings_in_window` into the Portfolio tab's per-cycle candidate selection. Adds an "X candidates dropped: earnings in window" counter to the regime banner. ~half-day commit.

Combined ~1 day of work. **Not deferred. v1 ships with earnings filter active.**

### 17.7 Look-ahead bias verification

The DATE column is the BOARD MEETING date. The notice of the meeting (NSE Reg 29(1)(a)) is filed 5-14 days BEFORE the meeting. So at backtest date D, an algo trader would know about meetings scheduled in approximately [D+5, D+14] from the notice feed.

Using the actual meeting date in our filter is looking ahead by 5-14 days relative to strictly-public-knowledge. **This is acceptable** — the operator's intent is "avoid the earnings event," not "model exact lead-time of public knowledge." The 5-14 day lookahead matches realistic algo-trader behavior (who would be subscribed to the notice feed and acting on it). For statistical rigor, a future commit could subtract 7 days as a conservative proxy for notice-publication; for now, use the meeting date directly.

---

## 18. The three-layer risk-management framework (added 2026-06-04)

Synthesized from the conversation with the operator and the other reviewer. Resolves the question "is IVP alone enough?"

### 18.1 The decomposition

Realized vol of any single stock splits into two structurally different components:

- **Systematic vol** = β × market vol. Driven by the same forces moving the whole universe.
- **Idiosyncratic vol** = name-specific. Disconnected from market vol.

VRP (variance risk premium) exists when IV > E[RV], where RV has both components. To avoid getting caught by elevated RV, you need to forecast BOTH parts. And the forecasting mechanisms are completely different:

| Layer | What it catches | Prediction mechanism |
|---|---|---|
| **1. Regime gate** (India VIX or avg single-name realized vol) | Systematic vol spikes (March 2020, election week, RBI surprise) | Volatility CLUSTERING — recent market vol predicts near-future market vol |
| **2. Earnings/event filter** (calendar-based) | Scheduled idiosyncratic jumps (each company's quarterly results) | CALENDAR — you know the date in advance regardless of recent vol |
| **3. IV − E[RV] spread** (per-stock vol forecast model) | Persistent diffusive idiosyncratic vol elevation that's neither calendar-driven nor market-wide | PER-STOCK RV FORECAST — econometric (HAR, GARCH) or ML |

### 18.2 Why the regime gate alone is insufficient

The regime gate is structurally BLIND to the idiosyncratic channel. A single name can sit at 90th-percentile IVP because the market knows ITS earnings or M&A announcement is coming — while India VIX is calm and the gate says ON. Naive IVP filter then says "rich premium, sell!" and you walk into the catalyst.

The gate can't see this because it's based on recent vol clustering, and **calendar events are predictable from the calendar, not from recent vol**. A stock can be dead calm right up until the earnings gap.

**Implication**: shipping IVP filter WITHOUT the earnings filter leaves the most catastrophic single failure mode wide open. This isn't a polish-it-later issue — it's structurally incomplete risk management.

### 18.3 Why the earnings filter changes the v1 plan

With earnings filter in place (now possible per §17), layers 1 and 2 are both covered. IVP's remaining job is the third-layer residual — and even a crude IVP proxy is "good enough for v1" because the two predictable failure modes (systematic clustering, scheduled events) are caught by other mechanisms.

**Before earnings data**: IVP without earnings filter was unsafe — the operator was walking into earnings concentration unprotected. The deferral plan was problematic.

**After earnings data (now)**: IVP filter is one of three layers, each doing its own job, none load-bearing alone. v1 ships safely.

This is why earnings filter moved from "deferred" (§1 decision #10 original) to "v1 — data in hand" (§1 decision #10 revised). The data delivery removed the blocker.

### 18.4 The 2-D diagnostic (load-bearing UI element)

Per the other reviewer's recommendation — and now non-negotiable:

The Portfolio tab MUST surface a **2-D table breaking out (gate ON/OFF) × (IVP decile or quintile)**, with each cell showing:
- Median ROI
- A tail statistic (5th-percentile P&L OR per-bucket Calmar OR per-bucket CVaR-5%)
- N trades

This empirically answers:
- Does IVP add signal beyond the gate? → look at the gate-ON column. If decile spread on tail-stat survives → yes. If it collapses → IVP is mostly redundant with the gate.
- Does the gate prevent the worst tail outcomes? → compare top-IVP row across gate ON/OFF columns. If gate-OFF has much worse tail at same median → gate is doing its job.
- Are high-IVP buckets "real edge" or "earnings concentration"? → if median is high AND tail is brutal at the top decile, that's the earnings-concentration signature (mean-only views would lie about it).

### 18.5 Three caveats on the 2-D diagnostic

From the other reviewer, all valid:

1. **Judge each bucket on the tail, not just the median.** Short-vol is left-skewed; a bucket can have higher median AND fatter left tail simultaneously. Mean-only displays mis-call this as "good bucket."
2. **Use constant-maturity IV for the IVP construction.** If IVP is built on raw front-month IV, the deciles are partly sorting on DTE instead of richness — contaminating the variable being tested. (Already in our plan per §2.2.)
3. **Watch bucket counts.** With our universe size and monthly cadence, deciles may be thin (~60 trades per bucket). Quintiles (~120 per bucket) might be more defensible for the initial diagnostic. Switch granularity as the universe widens.

### 18.6 Future Tier-3 layer: IV − E[RV] spread directly

If the 2-D diagnostic shows IVP is doing weak work even after the gate + earnings filter, the right escalation is **HAR (Heterogeneous Autoregressive) vol model per stock** — uses daily, weekly, monthly RV components to forecast next-N-day RV. Standard econometric baseline; well-published; cheap to implement.

Then the filter becomes `IV − HAR_forecast(RV)` directly, which is the cleanest VRP signal achievable without proprietary infrastructure. Replaces IVP entirely. Deferred to Phase 8.2.

---

## 19. Three "IVP" operations — disambiguation (added 2026-06-04, revised after operator clarification)

The operator clarified their original IVP-trap question — they were not describing pure cross-sectional raw IV (which I initially documented). They were describing a TWO-LEVEL ranking: per-stock time-series IVP first, then a cross-sectional rank of those time-series IVPs across the universe. That's actually what our v1 plan already does. Disambiguating:

| Operation | Construction | What it picks | In plan? |
|---|---|---|---|
| **A. Time-series IVP threshold filter** | Each stock's IV today ranked vs its OWN trailing 252-day history. Keep stocks above some absolute threshold (e.g., 60th percentile). | All stocks whose self-comparison clears the bar | ✓ v1 (e.g., "hold names above own 60th pct") |
| **B. Rank-of-ranks (cross-section of TS-IVPs)** | Compute each stock's TS-IVP today. Then rank ALL stocks by their TS-IVP values. Take top-N. | The N stocks whose self-comparison is most extreme today | ✓ v1 — this IS what "top-5 by IVP" means after the threshold filter |
| **C. Pure cross-sectional raw IV** | Today's raw IV across stocks; top stocks have highest raw IV. | High-vol stocks structurally (ADANIENT at 35% will always rank above HDFCBANK at 15%) | ✗ — bad signal, just sorts by structural vol |

### 19.1 The operator's clarification

Quote: "PNB's IV is rich in December 2025 compared to itself MUCH MORE than how rich others' IVs are compared to themselves."

That IS operation B — pick the stock whose own-history-comparison is most extreme. It's already the v1 plan: the threshold filter (A) drops stocks below the bar; selecting top-N by TS-IVP (B) picks the most anomalously elevated of the survivors. Same two-step pipeline as before, just made precise.

### 19.2 Why operation C is mostly redundant

Operation C — comparing today's raw IV across stocks — fails because raw IV is dominated by structural vol differences. ADANIENT's raw IV is structurally higher than HDFCBANK's by ~2× regardless of "richness." Sorting by raw IV would just select high-vol names every cycle, which is not the signal we want.

Operation B (rank-of-ranks of TS-IVPs) eliminates this bias because each stock is FIRST self-normalized by its own history — the cross-sectional rank then reflects relative anomaly, not structural vol.

### 19.3 What about Phase-8.2 future variants?

If the 2-D diagnostic (§18.4) shows TS-IVP is doing weak work even after the gate + earnings filter, the right next-tier signal is **IV − E[RV] computed via per-stock HAR vol forecast** (per §18.6) — not operation C. Direct VRP signal, structurally cleanest. That's the upgrade path, not "add cross-sectional raw IV."

### 19.4 An earlier draft of this section incorrectly conflated B and C

Noted for the record. The first version of §19 described operation C and called it "cross-sectional IVP" — that was imprecise. The operator's intuition was operation B, which is the rank-of-ranks already in our v1 plan. Operation C is a separate (and weaker) signal not worth chasing.

---

## 21. Data dependencies + calculation formulas (added 2026-06-04)

Single registry of every data input and every derived quantity the Portfolio + Inspect tabs depend on. Reading this end-to-end tells you what we have, what we still need to acquire, and what we need to compute from scratch.

### 21.1 The full list (general — what we need)

For the Portfolio + Inspect tabs to function, we need access to or computation of:

1. Spot price (close, high, low, open) per (symbol, trading day)
2. Option premium (close, OHLC, settle, volume, OI, lot size) per (symbol, expiry, strike, type, trading day)
3. F&O bhavcopy per trading day (already includes 2-3 in normalized form)
4. India VIX daily values across the backtest window
5. NSE corporate-events calendar (board meeting dates + purpose) per (symbol, date)
6. Trading-day calendar (NSE holidays + weekends)
7. Lot size per (symbol, expiry) — actually historically-varying, read per-row from bhavcopy
8. Risk-free rate for Black-Scholes inversion (Indian 10-year G-Sec yield or fixed-constant proxy)
9. Implied volatility per (symbol, expiry, strike, type, trading day) — DERIVED
10. ATM strike per (symbol, expiry, trading day) — DERIVED
11. 30-day constant-maturity ATM IV per (symbol, trading day) — DERIVED
12. Time-series IVP (trailing 252-TD percentile rank of #11) per (symbol, trading day) — DERIVED
13. Realized volatility (21-day, annualized) per (symbol, trading day) — DERIVED
14. Average single-name realized vol across the universe per (trading day) — DERIVED (regime gate v1 proxy)
15. Earnings-event flag: does (symbol, day-range) overlap a scheduled "Financial Results" event — DERIVED (filter)
16. Liquidity rank (trailing 21-TD average daily traded contracts) per (symbol, trading day) — DERIVED
17. Per-trade margin estimate (already in src/engine/margin.py)
18. Per-trade gross P&L, costs, net P&L (already in src/engine/pnl.py + costs.py + slippage.py)
19. Portfolio cycle P&L = sum of per-trade net P&Ls per cycle — DERIVED
20. Cumulative equity curve = cumsum(cycle P&Ls) + starting capital — DERIVED
21. Underwater drawdown series = equity - running_max(equity) — DERIVED
22. Portfolio metrics: Calmar, Ulcer Index, Sortino, max DD ₹, win days %, avg positions, worst day — DERIVED

### 21.2 What to DOWNLOAD (data acquisition)

External data that we don't compute — must be fetched and cached.

| # | Item | Source | Status | Effort |
|---|---|---|---|---|
| D1 | Spot OHLC per symbol per trading day | `jugaad_data.nse.stock_df` | ✅ have, cached at `data/cache/spot/{SYMBOL}/{YEAR}.parquet` | done |
| D2 | Option premium + volume + OI per contract per day | `jugaad_data.nse.derivatives_df` | ✅ have, cached at `data/cache/options/{SYMBOL}/{EXPIRY}/{STRIKE}-{TYPE}.parquet` | done |
| D3 | F&O bhavcopy per trading day | `jugaad_data.nse.archives.bhavcopy_fo_raw` + direct UDiff URL post-2024-07-08 | ✅ have, cached at `data/cache/bhavcopy_fo/{YYYYMMDD}.parquet` | done |
| D4 | NSE corporate-events calendar | Operator-provided CSV: `CF-Event-equities-06-09-2023-to-04-06-2026.csv` | ✅ have (delivered 2026-06-04). Loader needs writing → `feat(p8.data.events_loader)`. | ~half day |
| D5 | India VIX daily history (OHLC) | TBD — see §21.5 for the research prompt sent to web Claude | ⏳ research in progress | TBD until source confirmed |
| D6 | Trading-day calendar | Derived from RELIANCE spot series (already cached) via `src/data/trading_calendar.py` | ✅ have | done |
| D7 | Risk-free rate proxy | Constant 6.5% (Indian short-term G-Sec ~) for v1 BS inversion. Real time-series of 10Y G-Sec or 91-day T-Bill is a possible v1.1 add. | ⏳ fixed constant for v1 | trivial |

Total remaining downloads: India VIX (D5) is the only outstanding research blocker. Events CSV (D4) needs a loader commit but data is in hand.

### 21.3 What to CALCULATE (derived quantities)

Computed from the downloaded data. Each row references the formula in §21.4.

| # | Quantity | Inputs | Formula ref | Where it lands |
|---|---|---|---|---|
| C1 | ATM strike per (symbol, expiry, date) | spot at date, available strikes from bhavcopy on date | F1 | reused from `src/strategies/_strikes.py::pick_nearest` |
| C2 | Black-Scholes implied vol per (symbol, expiry, strike, type, date) | option premium, spot, strike, time-to-expiry, rate | F2 + F3 | new `src/engine/iv.py::bs_implied_vol` |
| C3 | 30-day constant-maturity ATM IV per (symbol, date) | two bracketing-expiry ATM IVs from C2 | F4 | new `src/engine/iv.py::constant_maturity_iv` |
| C4 | Time-series IVP per (symbol, date) | trailing 252 days of C3 values | F5 | new `src/analytics/ivp.py::time_series_ivp` |
| C5 | Cross-sectional rank of TS-IVPs (for top-N selection) | C4 across universe on day D | F6 | new `src/analytics/ivp.py::top_n_by_ivp` |
| C6 | 21-day realized vol per (symbol, date) | trailing 22 daily closes from spot cache | F7 | new `src/analytics/realized_vol.py` (or reuse `src/engine/vol.py` with windowing) |
| C7 | Average single-name realized vol (regime gate v1 proxy) | C6 averaged across universe on day D | F8 | new `src/analytics/regime.py::avg_single_name_rv` |
| C8 | Regime gate signal (percentile rank of C7 or India VIX vs trailing 252) | C7 series or India VIX series | F9 | new `src/analytics/regime.py::regime_percentile` |
| C9 | Earnings-event flag per (symbol, entry, exit) | events CSV from D4 | F10 | new `src/analytics/earnings_filter.py::has_earnings_in_window` |
| C10 | Liquidity rank per (symbol, date) | trailing 21-day avg contracts traded from bhavcopy | F11 | new `src/analytics/liquidity.py` |
| C11 | Per-trade net P&L | already implemented | — | `src/engine/pnl.py::price_trade` |
| C12 | Per-trade margin | already implemented | — | `src/engine/margin.py::MarginModelV1.estimate` |
| C13 | Cycle P&L | sum of C11 over the 5 stocks traded in the cycle | F12 | new `src/analytics/portfolio.py::cycle_pnl` |
| C14 | Cumulative equity curve | cumsum(C13) + starting capital | F13 | new `src/analytics/portfolio.py::equity_curve` |
| C15 | Underwater drawdown series | equity − running_max(equity) | F14 | new `src/analytics/portfolio.py::drawdown_series` |
| C16 | Calmar ratio | CAGR / max_drawdown_pct | F15 | new `src/analytics/portfolio.py::calmar` |
| C17 | Ulcer Index | sqrt(mean(DD%²)) over period | F16 | new `src/analytics/portfolio.py::ulcer_index` |
| C18 | Sortino ratio | excess_return / downside_std, annualized | F17 | new `src/analytics/portfolio.py::sortino` |
| C19 | Max DD ₹ | absolute rupee peak-to-trough | F18 | new `src/analytics/portfolio.py::max_drawdown_inr` |
| C20 | 2-D diagnostic table | C13 grouped by (regime_state, IVP_decile) | F19 | new `src/analytics/portfolio.py::regime_x_ivp_breakdown` |

### 21.4 Formula reference (canonical math)

**F1 — ATM strike picker** (SPECS §5, already implemented):

```python
atm_strike = min(available_strikes, key=lambda K: (abs(K - spot), K))
# tiebreaker: lower strike
```

**F2 — Forward-based Black-76 price (European)** *[REVISED 2026-06-04 — was spot-based BS with dividend slot; now extracts synthetic forward via put-call parity at ATM]*:

```
Step 1: Extract the synthetic forward at the ATM strike from observed
        call and put premia via put-call parity:

    F = K_atm + (C_atm − P_atm) · exp(r·T)

This bypasses the missing dividend / borrow / carry inputs — the
option market is already pricing the forward; we just read it.

Step 2: Invert with Black-76 (Black-Scholes on a forward, no q term):

For a CALL:
    C = exp(−r·T) · [F·Φ(d1) − K·Φ(d2)]

For a PUT:
    P = exp(−r·T) · [K·Φ(−d2) − F·Φ(−d1)]

Where:
    d1 = (ln(F/K) + σ²·T/2) / (σ·√T)
    d2 = d1 − σ·√T

F = synthetic forward (from step 1), K = strike,
T = time to expiry in years (252 TD per year), r = risk-free rate (use 0.065),
σ = volatility (the unknown), Φ = cumulative standard-normal CDF.
```

Why forward-based: per §2.2 — spot+rate inversion ignores dividends and borrow costs, both of which are real for single-stock options and hard to source per-stock-per-day in India. The synthetic forward IS observable in the option chain itself.

**F3 — Newton-Raphson implied-volatility inversion (Black-76 vega)** *[REVISED 2026-06-04 — vega now consistent with the forward-based F2; was missing the discount factor and dividend term]*:

```python
def bs_implied_vol(market_price, forward, strike, T, r, option_type,
                   sigma_init=0.30, tol=1e-4, max_iter=50):
    """Black-76 IV inversion. `forward` is the synthetic F from F2 Step 1.
    Vega is consistent with the F2 Black-76 price formula:
        vega = exp(-r*T) * F * sqrt(T) * φ(d1)
    Mis-matched vega (e.g. omitting exp(-r*T)) makes Newton-Raphson
    over- or under-shoot and may fail to converge for r != 0.
    """
    sigma = sigma_init
    for _ in range(max_iter):
        bs_price = black76(forward, strike, T, r, sigma, option_type)
        d1 = (log(forward / strike) + sigma**2 * T / 2) / (sigma * sqrt(T))
        vega = exp(-r * T) * forward * sqrt(T) * norm_pdf(d1)
        diff = bs_price - market_price
        if abs(diff) < tol: return sigma
        if vega < 1e-8: break  # converged but not at solution; flag failed
        sigma = sigma - diff / vega
        if sigma <= 0: sigma = 1e-4  # clamp
    return NaN  # failed to converge
```

For Indian stocks: `r = 0.065` (constant proxy for 91-day T-Bill / overnight rate). No `q` term needed — the forward absorbs all carry.

**F4 — 30-day constant-maturity ATM IV (linear in annualized variance, with near-expiry exclusion)** *[REVISED 2026-06-04 — added 7-DTE near-expiry exclusion + explicit interpolation-convention note]*:

```python
def constant_maturity_iv_with_exclusion(
    today_iv_per_expiry: dict,  # {expiry_date: (iv, dte)}
    target_dte: int = 30,
    min_dte_threshold: int = 7,
):
    """30D constant-maturity ATM IV with industry-standard near-expiry
    exclusion. If the nearest expiry has DTE < min_dte_threshold, skip
    it (its IV reading is too vega-noisy to trust) and use the next
    two monthlies instead. See §2.2 for the empirical justification.
    """
    # Sort expiries by DTE ascending
    sorted_exp = sorted(today_iv_per_expiry.items(), key=lambda kv: kv[1][1])
    # Drop dying contracts
    usable = [(exp, iv_dte) for exp, iv_dte in sorted_exp
              if iv_dte[1] >= min_dte_threshold]
    if len(usable) < 2:
        return NaN  # not enough usable expiries
    # Pick the two that bracket target_dte (or the two closest)
    (exp_near, (iv_near, dte_near)), (exp_far, (iv_far, dte_far)) = usable[:2]
    # Linear interpolation in ANNUALIZED variance
    var_near, var_far = iv_near**2, iv_far**2
    w_near = (dte_far - target_dte) / (dte_far - dte_near)
    w_far  = (target_dte - dte_near) / (dte_far - dte_near)
    var_target = w_near * var_near + w_far * var_far
    return sqrt(max(var_target, 0.0))
```

**Interpolation convention (documented choice, not a bug)**: this interpolates **annualized σ² linearly in DTE**. CBOE VIX convention interpolates **total variance σ²·T linearly in T**. For our typical ~28D + ~58D brackets the two differ by < 1%; we picked annualized-σ² for simplicity and consistency across symbols regardless of DTE bracket width.

Linear interpolation in VARIANCE, NOT in volatility — interpolating σ directly is wrong (the vol surface is approximately linear in variance with respect to time, not in volatility).

**F5 — Time-series IVP (trailing 252-TD percentile rank)** *[REVISED 2026-06-04 — explicit NaN guard on today's value]*:

```python
def time_series_ivp(iv_series, today_idx, lookback=252):
    today = iv_series.iloc[today_idx]
    if pd.isna(today):
        return float('nan')  # don't silently rank NaN as 0th percentile
    window = iv_series.iloc[max(0, today_idx - lookback + 1) : today_idx + 1]
    valid = window.dropna()
    if len(valid) < 0.5 * lookback:
        return float('nan')  # insufficient history → undefined IVP
    rank = (valid < today).sum() / len(valid) * 100.0
    return rank
```

Reports as percentage [0, 100]. NaN propagates if today's IV is unavailable. **Original bug**: `(window < NaN).sum()` silently returns 0, so a missing-IV day rendered as 0th percentile ("cheapest vol ever"). Fixed by guarding `today` for NaN before computing the rank.

**F6 — Cross-sectional rank of TS-IVPs (selecting top-N stocks today)**:

```python
def top_n_by_ivp(ivp_today_per_symbol, n=5):
    # ivp_today_per_symbol: dict {symbol: TS-IVP value today}
    sorted_symbols = sorted(ivp_today_per_symbol.items(),
                            key=lambda x: -x[1])  # descending
    return [sym for sym, _ in sorted_symbols[:n]]
```

The "rank-of-ranks" operation per §19 — same as `pandas.Series(ivp_today).nlargest(n).index`.

**F7 — 21-day annualized realized volatility (close-to-close log returns)**:

```python
def realized_vol_21d(close_series_22_days):
    # 22 prices yields 21 log returns
    log_returns = np.log(close_series_22_days[1:] / close_series_22_days[:-1])
    daily_std = np.std(log_returns, ddof=1)  # sample std (not population)
    return daily_std * np.sqrt(252)  # annualized
```

Note `ddof=1` (sample std) not `ddof=0`. With small windows (21 obs) the difference is ~2.5%.

**F8 — Average single-name realized vol across universe**:

```python
def avg_single_name_rv(rv_series_per_symbol_on_date):
    # rv_series_per_symbol_on_date: dict {symbol: RV21d on date}
    values = [rv for rv in rv_series_per_symbol_on_date.values() if not isnan(rv)]
    return mean(values)
```

NOT portfolio realized vol (which depends on covariance). Per §3.5, the simple mean is the correct "ambient single-name turbulence" signal for the regime gate.

**F9 — Regime gate percentile rank** *[REVISED 2026-06-04 — explicit NaN→OFF guard added per reviewer d8620f8 GRILL 2]*:

```python
def regime_percentile(signal_series, today_idx, lookback=252):
    # signal_series can be C7 (avg single-name RV) v1
    # or India VIX v2
    return time_series_ivp(signal_series, today_idx, lookback)  # same math

def regime_state(signal_series, today_idx, threshold_pct=75):
    pct = regime_percentile(signal_series, today_idx)
    if pd.isna(pct):
        # "Skip when uncertain" — see explanation below.
        return "OFF"
    return "ON" if pct <= threshold_pct else "OFF"
```

**NaN-handling convention** (added 2026-06-04): when `regime_percentile`
returns NaN (cold cache, insufficient history, today's signal value
NaN), `regime_state` returns `"OFF"`. The naive spec `"OFF" if pct >
threshold else "ON"` would let `NaN > 75 → False → "ON"` short-circuit
through, admitting cycles under unknown regime conditions. Conservative
"skip when uncertain" is the right risk-management bias for a
research-then-trade pipeline; the explicit `if pd.isna` guard pins
the behavior in code (and in spec, here) rather than relying on the
implicit-and-easy-to-miss NaN-comparison semantic.

**F10 — Earnings-event filter**:

```python
def has_earnings_in_window(events_df, symbol, entry_date, exit_date):
    sub = events_df[
        (events_df['SYMBOL'] == symbol)
        & events_df['PURPOSE'].str.contains('Financial Results', na=False)
        & (events_df['DATE'] >= entry_date)
        & (events_df['DATE'] <= exit_date + pd.Timedelta(days=1))
    ]
    return len(sub) > 0
```

Per §17.5 — filter only on "Financial Results"; +1 day buffer after exit.

**F11 — Liquidity rank (trailing 21-day average contracts traded)**:

```python
def liquidity_rank(symbol, as_of_date, bhavcopy_df, lookback_td=21):
    sub = bhavcopy_df[
        (bhavcopy_df['symbol'] == symbol)
        & (bhavcopy_df['instrument'] == 'OPTSTK')
        & (bhavcopy_df['trade_date'] >= as_of_date - 21_trading_days)
        & (bhavcopy_df['trade_date'] <= as_of_date)
    ]
    return sub['contracts'].mean()  # avg contracts/day across all OPTSTK rows
```

Then `top_N_liquid_today = sorted(universe, key=liquidity_rank, reverse=True)[:N]`.

**F12 — Cycle P&L (sum of trade net P&Ls per cycle)**:

```python
def cycle_pnl(trades_df, cycle_expiry_date):
    cycle_trades = trades_df[trades_df['expiry'] == cycle_expiry_date]
    return cycle_trades['net_pnl'].sum()
```

**F13 — Cumulative equity curve (additive — correct for equal-margin no-reinvest book)**:

```python
def equity_curve(cycle_pnl_series, starting_capital):
    """Additive: capital deployed is FIXED per cycle (equal-margin
    sizing, no reinvestment of profits). The P&L stream is therefore
    arithmetic, not geometric. F15 below uses SIMPLE annualized return
    to stay consistent with this — don't mix additive equity with
    geometric CAGR.
    """
    return starting_capital + cycle_pnl_series.cumsum()
```

**F14 — Underwater drawdown series**:

```python
def drawdown_series(equity_curve):
    running_max = equity_curve.cummax()
    return equity_curve - running_max  # ≤ 0 always; 0 at new highs
```

**F15 — Calmar ratio (SIMPLE annualized return, not CAGR)** *[REVISED 2026-06-04 — was geometric CAGR, mismatched with additive equity]*:

```python
def simple_annualized_return(equity_curve, periods_per_year=12):
    """For equal-margin no-reinvest books, total return is the sum of
    cycle returns; annualization is simple scaling, not compounding."""
    n_periods = len(equity_curve) - 1
    total_return_pct = (equity_curve.iloc[-1] - equity_curve.iloc[0]) / equity_curve.iloc[0]
    return total_return_pct * (periods_per_year / n_periods)

def calmar(equity_curve, periods_per_year=12):
    """Calmar = simple annualized return / max drawdown%.
    With equal-margin sizing (§7), positions don't compound; the equity
    stream is arithmetic. Using geometric CAGR here would inflate the
    apparent return on a book that's not actually reinvesting.
    """
    annual_return = simple_annualized_return(equity_curve, periods_per_year)
    dd = drawdown_series(equity_curve)
    peak_at_trough = equity_curve.cummax().loc[dd.idxmin()]
    max_dd_pct = abs(dd.min() / peak_at_trough)
    if max_dd_pct == 0: return float('inf')
    return annual_return / max_dd_pct
```

**Original bug**: F13 built equity additively (correct for equal-margin), F15 then computed `cagr = (equity[-1]/equity[0])^(12/n) − 1` (geometric compounding). Mismatched — the additive stream implies simple annualization, not CAGR. Using geometric CAGR on a non-compounding book overstates the headline return and propagates the overstatement into Calmar / Sortino / every ratio that consumes it. Fixed by using simple annualization consistent with additive equity.

If the operator later decides to compound positions (size ∝ current equity), F13 changes to geometric and F15 reverts to CAGR. Until then, additive + simple is the consistent pair.

**F16 — Ulcer Index**:

```python
def ulcer_index(equity_curve):
    running_max = equity_curve.cummax()
    dd_pct = ((equity_curve - running_max) / running_max) * 100  # negative values
    return np.sqrt(np.mean(dd_pct ** 2))
```

Penalizes BOTH depth and duration of drawdowns. Lower is better.

**F17 — Sortino ratio (target-downside-deviation per Sortino/Satchell standard)** *[REVISED 2026-06-04 — original formula divided by downside-only N; standard divides by total N]*:

```python
def sortino(returns_series, target=0, periods_per_year=12):
    """Standard Sortino/Satchell target-downside-deviation:
        TDD = sqrt( sum( min(0, r - target)^2 ) / N_total )
    Note: N_total, NOT N_downside. And the squared term is 
    (downside - target)^2, not downside^2 (harmless at target=0 
    but wrong if target is non-zero).
    """
    excess_return_annualized = (returns_series.mean() - target) * periods_per_year
    
    # min(0, r - target)^2 over ALL observations, summed and divided by N_total
    deviations_below_target = (returns_series - target).clip(upper=0)
    downside_dev_sq = (deviations_below_target ** 2).mean()  # mean over ALL N
    target_downside_deviation = np.sqrt(downside_dev_sq * periods_per_year)
    
    if target_downside_deviation == 0:
        return float('inf')
    return excess_return_annualized / target_downside_deviation
```

**Original bug**: divided the squared downside sum by `len(downside)` (downside-only count) instead of `len(returns_series)` (total N). This UNDERSTATES downside deviation and OVERSTATES Sortino. And squared `downside` directly instead of `(downside − target)²` — harmless at the default `target=0` but wrong if anyone passes a non-zero target (e.g., the risk-free rate as a target). Fixed to standard Sortino/Satchell.

Higher is better.

**F18 — Max DD ₹** (rupee value):

```python
def max_drawdown_inr(equity_curve):
    return abs(drawdown_series(equity_curve).min())
```

Reports as positive rupee amount.

**F19 — 2-D diagnostic table** (regime × IVP decile, per §18.4):

```python
def regime_x_ivp_breakdown(trades_df, regime_signal_series, ivp_series_per_symbol):
    # For each trade, look up the regime_state at entry_date
    # and the trading symbol's TS-IVP at entry_date.
    # Bucket IVP into deciles (or quintiles for thin data).
    trades_df['regime_state'] = trades_df['entry_date'].map(
        lambda d: regime_state_at(regime_signal_series, d)
    )
    trades_df['ivp_decile'] = pd.qcut(
        trades_df['ivp_at_entry'], q=10, labels=False
    )
    grouped = trades_df.groupby(['regime_state', 'ivp_decile'])
    return grouped['net_pnl'].agg([
        'count',
        'mean',
        'median',
        ('cvar_5', lambda x: x.nsmallest(max(1, len(x)//20)).mean()),
    ])
```

Per the other reviewer's caveats: judge each bucket by both median AND tail (CVaR-5% column above), use constant-maturity IV upstream so deciles aren't sorting on DTE, switch to quintiles if any bucket has < ~50 trades.

**⚠ Look-ahead caveat on `qcut`** *[ADDED 2026-06-04]*: `pd.qcut(...)` here computes decile boundaries from the **full retrospective sample** — that's fine for THIS retrospective diagnostic (we WANT to see how trades grouped by their TRUE IVP percentile performed). But the resulting boundaries **MUST NOT** be used for LIVE trade selection. Live filtering needs **trailing-only** quantile boundaries (e.g., at each cycle entry, compute deciles from the trailing 252 days of cross-sectional IVP values, then bucket today's candidates against those trailing-window boundaries). Using full-sample boundaries live = peeking at future periods = backtest fraud. The diagnostic and the filter are two different operations; the formula above is the diagnostic version only.

### 21.5 The India VIX research prompt (saved for posterity)

Verbatim prompt sent to web Claude on 2026-06-04 to determine the best download method:

> *(See the prompt in the conversation log; reproduced in full at top of this turn.)*

Update §21.2 row D5 with the answer once research returns.

### 21.6 Sequencing — order of new commits

In dependency order (each commit depends on the ones above it):

1. `fix(p8.cost.stt_correction)` — STT 0.0625% → 0.15%. No dependencies. ~10 min.
2. `feat(p8.data.events_loader)` — Reads `CF-Event-equities-*.csv` → `data/cache/events.parquet`. Provides `load_events()` API. ~half day.
3. `feat(p8.data.india_vix_loader)` — Pending D5 research. Fetches + caches India VIX history. ~half day after source confirmed.
4. `feat(p8.engine.iv)` — Black-Scholes inversion: F2, F3. Plus tests against known-good IV examples (e.g., RELIANCE Jan-2024 ATM straddle). ~1 day.
5. `feat(p8.engine.iv_materializer)` — Builds the per-symbol constant-maturity-30D IV history using F4. Iterates over the bhavcopy cache; writes `data/cache/iv/{SYMBOL}.parquet`. ~1 day.
6. `feat(p8.analytics.ivp)` — F5, F6. Reads from the IV cache. ~half day.
7. `feat(p8.analytics.realized_vol)` — F7. ~half day.
8. `feat(p8.analytics.regime)` — F8, F9. ~half day.
9. `feat(p8.analytics.earnings_filter)` — F10. Wire into portfolio selection. ~half day.
10. `feat(p8.analytics.liquidity_rank)` — F11. ~half day.
11. `feat(p8.analytics.portfolio)` — F12 through F19. The portfolio aggregator + metrics. ~1-2 days.
12. `feat(p8.portfolio.tab)` — Streamlit UI: equity curve + drawdown + headline strip + 2-D diagnostic + worst-10-days + concentration bars + correlation matrix + drilldown wiring. ~2 days.
13. `feat(p8.inspect.tab)` — Contract trajectory chart with per-leg gaps. ~1 day.

**Total estimated: ~11-13 days of nuclear-commit work.** Roughly 2.5 weeks of focused effort. India VIX (D5/3) is the only sequencing risk — if web research returns "scrape is painful," push v1 with the avg-single-name-RV proxy and ship India-VIX integration as a v1.1 add.

---

## 22. Pre-build IV visualization research step *[ADDED 2026-06-04]*

Before building `src/engine/iv_materializer.py` (the production IV history materializer), build a research notebook to verify the methodology empirically on Indian single-stock data. **Don't bake the 7-DTE exclusion, the forward-PCP construction, or the interpolation convention into production code until they're visually validated.**

### 22.1 The notebook spec

`scripts/research_iv_visualization.ipynb` (or `.py`):

For 2-3 representative stocks (suggest RELIANCE, PNB, HDFCBANK — spanning low/mid/high-vol):

1. **Pull data**: bhavcopy F&O cache → ATM call + put premium per (date, expiry) for the last ~6 months.
2. **Extract forward** per (date, expiry) via F2 step 1 (PCP at ATM).
3. **Invert IV** per (date, expiry) via F3 (Black-76 Newton-Raphson).
4. **Build four time series** for each stock, on the same axes:
   - **Series A**: front-month ATM IV (raw, no exclusion — includes the 1-DTE spikes)
   - **Series B**: 30D constant-maturity IV including all bracketing expiries (the naive version)
   - **Series C**: 30D constant-maturity IV with 7-DTE exclusion (the methodology in F4)
   - **Series D**: Series C's trailing-252-day IVP (rank, 0-100)
5. **Vertical markers** at each monthly expiry date.

### 22.2 What we're looking for

- **Series A**: smooth most days, with sharp spikes/dips on T-1, T-2 (the 1-DTE vega-noise the 7-DTE rule is designed to remove)
- **Series B**: less spiky than A but still shows monthly periodicity from front-month inclusion near expiry
- **Series C**: smooth across expiry transitions — no monthly bumps; THIS is the "true" IV time series we want
- **Series D**: ranges 0-100, with peaks around real events (earnings periods, market shocks)

### 22.3 The decision the chart drives

- If **Series B ≈ Series C visually**: the 7-DTE exclusion is theoretical hygiene; a flat interpolation is fine for v1, simpler code.
- If **Series B has obvious monthly seasonality that Series C doesn't**: the exclusion is load-bearing; commit to it in F4.

You CANNOT decide this from first principles — only from the chart. **Build the notebook before the materializer.**

### 22.4 Build cost

~1 day. ~150 lines of notebook code. Throwaway artifact, but the decision it surfaces is permanent.

Optionally promote to a permanent Inspect-tab page later if the visualization stays useful for ongoing per-symbol drilldown.

---

## 23. Triage carryover items — minor but tracked *[ADDED 2026-06-04]*

Items from the reviewer's analysis that don't need code/spec changes but should be documented somewhere so they're not silently lost.

### 23.1 G5 — equal-margin ≈ equal-lots for 5-name books (empirical)

With NSE's indivisible lot sizes and a 5-position book, equal-margin sizing (option b per §7) likely produces the SAME lot counts as equal-lots (option a) most cycles. The "more defensible" benefit over equal-lots may be mostly cosmetic at small N.

**Action**: instrument the portfolio aggregator (when built) to LOG how often `equal_margin_lots` differs from `equal_lots` across the backtest. If < 10% of cycles, accept that equal-margin is effectively equal-lots and document it. If > 30%, the distinction is real and worth keeping. Resolve after the aggregator runs against real data.

### 23.2 G7 — European BS valid for NSE single stocks (confirmed)

Indian single-stock options have been European-style since 2011 (NSE rule change). European BS inversion is correct; no American-style adjustment needed. Document in `src/engine/iv.py` docstring; no other action.

If any future variant is American-style (some commodity options on MCX are American), flag in the materializer.

### 23.3 G8 — Idle-capital drag during dead-between-cycles periods

The portfolio deploys capital only during N − M trading days each cycle (entry to exit). Capital sits idle between cycles. Calmar / Sortino / etc. computed on the calendar timeline DIFFER from the same metrics computed on a deployed-capital basis (annualizing only over deployed days).

**Action**: report metrics on BOTH bases in the Portfolio tab. Calendar basis = "what your account compounded over the year" (relevant for personal-finance comparison); deployed-capital basis = "what you earned per rupee-day of capital actually at risk" (relevant for capital-efficiency comparison). Two cards next to each other in the headline strip.

Per §1 decision #13, capital opportunity cost is NOT modeled. But surfacing both bases doesn't require an opportunity-cost rate — just two different normalizations.

### 23.4 Two std conventions — ddof=1 vs ddof=0 (documented)

The codebase uses:
- **ddof=1 (sample std)** for `realized_vol_21d` (F7) and other statistical-estimator contexts. The bias correction matters at small samples (~2.5% adjustment at n=21).
- **ddof=0 (population std)** for per-cell dispersion in the existing `cell_stats` module. Descriptive of the observed sample as a population in itself; no inference about a larger population intended.

Both correct for their respective purposes. The dual-convention isn't a bug. Document this in `src/engine/iv.py` (or wherever the next std-using module lands) as a one-line comment so future readers don't read it as inconsistency.

### 23.5 G6 — Sample-size restatement absorbed into §12

Per the reviewer, the "~3,800 priced trades" line in §12 was stale (current sweep is 1,103,923 rows). §12 has been updated to restate the ML-overfit argument via correlated samples (effective independent N ≈ 6,000, not row count). The conclusion survives, just under a different argument.

### 23.6 G4 — Survivorship walk-back absorbed into §11

§11 originally framed widening to bhavcopy as "no code change needed" → genuinely survivorship-free. Reviewer correctly flagged that pricing needs the contracts MATERIALIZED, and the cache is currently ~50 survivor blue-chips. §11 has been rewritten to walk this back honestly: v1 ships with 50-survivor cache + honest banner; full survivorship-free requires a Phase-8.2 universe-expansion commit.

### 23.7 G1 — STT direction (PENDING — hard blocker on the cost commit)

Web verification needed before `fix(p8.cost.*)` lands. Two possible rationales; same code change either way; commit message and §9 wording depend on which is right. See §9 for the full pending-resolution writeup.

---

## 24. What this document is NOT

- Not the final builder prompt — those come next as `feat(p8.portfolio.*)` and `feat(p8.inspect.*)` commits.
- Not the testable spec — `DESIGN_SPEC.md §P` will have the testable contracts.
- Not the engineering roadmap — `PLAN.md` carries the phase order.

This is the **why and how** behind the next phase. Builder prompts will reference this for rationale; reviewer will read this when a future commit seems to contradict an earlier choice. If you ever wonder "why did we drop stops?" or "why is sizing equal-margin?" — section 8 and 7 respectively. If you wonder "what about delta-hedging?" — §6.2.

---

*Last updated: 2026-06-04, in conversation between the operator and Claude. Sections 3.5 and 3.7 incorporate the previous Claude's correction on "average across 50 ≠ portfolio vol" and the India VIX recommendation. Section 2 reflects the operator's veto of the realized-vol-proxy approach. All decisions in §1 are taken; all items in §6 are explicitly deferred, not silently dropped.*
