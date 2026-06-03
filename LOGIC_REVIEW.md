# LOGIC REVIEW — formula / data-column / webapp-correctness audit

**Reviewer:** logic-review agent (separate from the architectural reviewer who owns `comments.md`).
**Scope:** Are the numbers shown on the webapp + MCP surface *true* and *best* — correct formulas, right columns from the right tables, faithfully derived from NSE data?
**Method:** code read (engine/data/analytics myself; web/mcp/analytics line-cited via sub-agent mapping cross-checked behaviorally) **+ empirical reproduction against the live cache and the on-disk sweep `sweep_5f199d6984f2.parquet`** (113,801 trade rows; symbols BHEL/PNB/RELIANCE/SBIN; strategies short_straddle/short_strangle/iron_condor; expiries 2024-05 → 2026-05).

**Bottom line:** Every formula *downstream of the fill price* is correct and reproduces exactly (gross P&L, costs, net, margin, ROI, annualization, heatmap median, CVaR, win-rate — all reproduced 100%). The data **currently displayed** was generated with the *correct* premium-VWAP fill and is faithfully derived. **BUT** there is one live, load-bearing unit-mismatch bug in the fill-price layer that (a) makes the displayed sweep **non-reproducible** — re-running today silently re-prices every fill to `close` — and (b) makes two `data_quality` MCP diagnostics emit wrong/nonsensical output. Lead finding below.

---

## 🚨 FINDINGS REQUIRING ATTENTION

### 🚨 F1 — `TURNOVER_SCALE_FACTOR` unit mismatch: VWAP fill is silently dead (100% close fallback) and the displayed sweep is no longer reproducible

**Files:** [src/engine/pnl.py:77](src/engine/pnl.py#L77), [src/engine/pnl.py:117-128](src/engine/pnl.py#L117-L128), [src/engine/pnl.py:197-216](src/engine/pnl.py#L197-L216); root cause spans [src/data/bhavcopy_fo_loader.py:329](src/data/bhavcopy_fo_loader.py#L329) and [src/data/bhavcopy_to_contract.py:330](src/data/bhavcopy_to_contract.py#L330).

**Verdict: WRONG (live regression in current code+cache).**

**The formula.** `_compute_vwap` ([pnl.py:121-122](src/engine/pnl.py#L121-L122)):
```
notional_per_share = turnover * TURNOVER_SCALE_FACTOR / volume      # TURNOVER_SCALE_FACTOR = 100_000.0
premium_vwap       = notional_per_share - strike
```
This assumes `turnover` is in **lakhs of rupees** (so `×10⁵` → rupees). The docstring at [pnl.py:56-77](src/engine/pnl.py#L56-L77) asserts UDiff `TtlTrfVal`, legacy `VAL_INLAKH`, and jugaad `FH_TOT_TRADED_VAL` are "all the same NSE convention … lakhs."

**Empirical proof they are NOT the same.** The `turnover` column the engine reads (per-contract parquet, copied straight from the bhavcopy at [bhavcopy_to_contract.py:330](src/data/bhavcopy_to_contract.py#L330)) is the **raw UDiff `TtlTrfVal` in RUPEES**, verified against the operator's own documented RELIANCE 2024-08-29 2840-CE example and across all four sweep symbols:

| Contract | turnover (cache) | volume | turnover/volume | strike + premium? |
|---|---|---|---|---|
| RELIANCE 2840-CE | 19,661,050 | 6,500 | **3,024.78** | 2840 + 184.78 ✓ (spot 3041) |
| RELIANCE 2860-CE | 1,529,750 | 500 | **3,059.50** | 2860 + ~189 ✓ |
| SBIN 880-CE | 18,467,062 | 20,250 | **911.95** | 880 + ~31 ✓ |
| PNB 112.5-PE | 1,853,600 | 16,000 | **115.85** | 112.5 + ~3.25 ✓ |
| BHEL 285-PE | 2,313,281 | 7,875 | **293.75** | 285 + ~8.75 ✓ |

So the **correct** recovery is `premium = turnover / volume − strike` (scale factor **1**), exactly as the docstring's own worked example states ("notional/contract ≈ 3024" = 19,661,050 / 26, with **no** `×10⁵`). The code's `×100,000` overshoots by 5 orders of magnitude.

**Consequence in the current code.** With turnover in rupees, `_compute_vwap` returns `19,661,050 × 100,000 / 6,500 − 2,840 ≈ 3.02×10⁸` instead of 184.78. The VWAP-vs-close safety band `[0.5×, 2.0×]` ([pnl.py:88-89](src/engine/pnl.py#L88-L89), applied at [pnl.py:211-213](src/engine/pnl.py#L211-L213)) therefore **rejects every fill** and falls through to `close`. Measured directly by exercising `pnl._pick_fill_price` against the live cache:

- RELIANCE 2024-08-29, all cached contracts: **0 / 3,219** rows used VWAP.
- All four sweep symbols, all cached contracts: **0 / 24,019** rows used VWAP. **100% close fallback.**

The entire premium-VWAP feature — the band-check rationale, the "VWAP is closer to a real fill than close" docstring at [pnl.py:140-152](src/engine/pnl.py#L140-L152), the `classify_fill_source` machinery — is **inert** against today's cache.

**Why the displayed data is nonetheless correct (but un-regenerable).** The on-disk sweep `sweep_5f199d6984f2.parquet` was generated *before* the per-contract cache was re-materialized from the UDiff bhavcopy. At that time the per-contract `turnover` was lakhs-denominated (jugaad `FH_TOT_TRADED_VAL`, ≈196.6 for the RELIANCE example), so `×10⁵` produced the **correct** premium. I confirmed this: of 4,008 legs on cached expiries, **93.0% of stored `entry_px`/`exit_px` exactly match `turnover/volume − strike`** (the correct premium) and only 3.5% match raw `close` (the deep-OTM floor cases). `TURNOVER_SCALE_FACTOR = 100_000` has existed unchanged since commit `6356b90`; the units flipped underneath it when the cache source changed (jugaad lakhs → UDiff rupees) during the bhavcopy-only migration, with no compensating change to the scale factor or a unit-normalization step in [bhavcopy_to_contract.py:_assemble_output_frame](src/data/bhavcopy_to_contract.py#L297-L333).

**Operator impact:**
1. **The numbers currently on the webapp are TRUE and BEST** — correct volume-weighted premium fills, faithfully derived from NSE turnover. ✅
2. **They are NOT reproducible.** Re-running the sweep against today's cache silently prices every fill at `close` instead of VWAP, changing every P&L / ROI / heatmap value. This breaks the determinism contract (SPECS §6c.3) in spirit: same logical inputs, different output, because the cache's units changed and the engine didn't.
3. **Cross-regime latent bug:** legacy `VAL_INLAKH` genuinely *is* lakhs (the column name says so; [bhavcopy_fo_loader.py:253](src/data/bhavcopy_fo_loader.py#L253)). The single `TURNOVER_SCALE_FACTOR` cannot be correct for both a lakhs column (legacy) and a rupees column (UDiff) simultaneously. The `turnover` column carries **mixed units across regimes** and is never normalized.

**Suggested fix (for BUILDER — I make no edits):** Normalize units at parse time so `turnover` is always rupees (drop the legacy `×10⁵` from `VAL_INLAKH`, or store both as lakhs), then set `TURNOVER_SCALE_FACTOR` to match the single chosen convention. The cheapest correct change given the cache is now rupees: `TURNOVER_SCALE_FACTOR = 1.0` **and** divide legacy `VAL_INLAKH × 10⁵` at [bhavcopy_fo_loader.py:253](src/data/bhavcopy_fo_loader.py#L253) (or vice-versa). Add a regression test that asserts `_pick_fill_price` returns VWAP (not close) for the RELIANCE 2840-CE fixture, so this can never silently regress again.

---

### 🚨 F2 — `data_quality` MCP tool emits a wrong diagnosis and nonsensical divergence as a *direct consequence* of F1

**File:** [src/mcp/data_quality.py](src/mcp/data_quality.py) — dimensions `theoretical_fallback_rate` (~line 259-310) and `vwap_vs_close_divergence` (~line 313-389).

**Verdict: WRONG output (cascades from F1).**

- `theoretical_fallback_rate` classifies every leg via `classify_fill_source` ([pnl.py:239-297](src/engine/pnl.py#L239-L297)), which mirrors the same buggy `× TURNOVER_SCALE_FACTOR` formula at [pnl.py:290](src/engine/pnl.py#L290). Against the current cache it will report **~100% `close` fallback for every symbol** and the summary text attributes this to *"cached PRE-turnover-ingest"* — a **wrong root-cause diagnosis**. The real cause is the F1 scale bug; the turnover is present and valid.
- `vwap_vs_close_divergence` reconstructs `vwap_implied = entry_turnover × 100_000 / entry_volume − strike` (`data_quality.py` ~line 353-358) and reports `100 × |vwap − close| / |close|`. With the `×10⁵` bug, `vwap_implied ≈ 3×10⁸`, so this dimension reports divergences on the order of **~10⁹ %** — a number an operator would read as catastrophic data corruption when it is purely the scale bug.

**Note:** because `classify_fill_source` mirrors the engine's own (buggy) decision, the classifier is at least *internally consistent* with what the engine does today (both say "close"). The wrongness is in the *attribution* and the *divergence magnitude*, not the vwap/close label.

---

### ⚠️ F3 — Cost model ignores physical-settlement STT on expiry-ITM stock options

**File:** [src/engine/costs.py:67-90](src/engine/costs.py#L67-L90).

**Verdict: SUSPICIOUS (modeling assumption, conservative-ish, undocumented at the surface).**

The model treats every exit as a market square-off: STT 0.0625% on the SELL-side *premium* only ([costs.py:84](src/engine/costs.py#L84)). NSE stock options are **physically settled** — a position held to expiry while ITM incurs delivery STT (0.125% of the *intrinsic/settlement notional*, far larger than premium STT) plus the equity-delivery cost stack. The sweep routinely sets `exit_offset_td = 0` (exit at T-0 = expiry day; e.g. the most-populated short_straddle/RELIANCE cell is entry=1/exit=0). For those expiry-day ITM exits the real cost is **understated**. This is a defensible v1 simplification but is not surfaced as a caveat on the webapp or in `costs_breakdown_json`. Recommend a documented caveat (and ideally a settlement-STT branch when `exit_date == expiry`).

---

### ℹ️ F4 — Non-issues I checked and cleared (so the operator isn't alarmed by them)

- **`roi_pct` NaN propagation** (sub-agent flagged HIGH): `_safe_roi` returns `None` when `margin ≤ 0` ([pnl.py:431-436](src/engine/pnl.py#L431-L436)), which would NaN-poison `aggregate.py` group medians. **Verified not realized:** in the live sweep, `roi_pct` NaN count = **0 / 113,801**, `margin ≤ 0` count = **0**. Defensive only; no live impact. Hardening (`.dropna()` in aggregate) is nice-to-have, not urgent.
- **Population std (`ddof=0`)** at [aggregate.py:181](src/analytics/aggregate.py#L181) / [cell_stats.py:165](src/analytics/cell_stats.py#L165): intentional, documented as a lower bound, surfaced in UI help text. Correct as a stated convention.
- **Annualized ROI explodes for 1-day holds** (`roi × 252 / 1`): mathematically correct ([pnl.py:439-449](src/engine/pnl.py#L439-L449)); the leaderboard/heatmap default rank on per-trade `median_roi_pct`, not annualized, so this doesn't drive the displayed ranking. Fine.

---

## SECTION 1 — DATA LINEAGE MAP

Raw NSE field → bhavcopy column → per-contract parquet → engine → sweep parquet → webapp/MCP.

### 1a. Raw → bhavcopy cache (`data/cache/bhavcopy_fo/{YYYYMMDD}.parquet`)

| Engine-facing column | UDiff raw (≥2024-07-08) | Legacy raw (<2024-07-08) | Parser | Notes |
|---|---|---|---|---|
| `expiry` | `FininstrmActlXpryDt` | `EXPIRY_DT` | [bhavcopy_fo_loader.py:319](src/data/bhavcopy_fo_loader.py#L319) / [:244](src/data/bhavcopy_fo_loader.py#L244) | ✅ uses *actually-settled* date per SPECS §2.4; warns on holiday-shift divergence ([:284-291](src/data/bhavcopy_fo_loader.py#L284-L291)) |
| `strike` | `StrkPric` | `STRIKE_PR` | [:320](src/data/bhavcopy_fo_loader.py#L320)/[:245](src/data/bhavcopy_fo_loader.py#L245) | NaN for futures; fractional strikes supported ([cache.py:83-99](src/data/cache.py#L83-L99)) |
| `close` | `ClsPric` | `CLOSE` | [:325](src/data/bhavcopy_fo_loader.py#L325)/[:250](src/data/bhavcopy_fo_loader.py#L250) | the fill price actually used today (F1) |
| `ltp` | `LastPric` | *(absent)* | [:326](src/data/bhavcopy_fo_loader.py#L326) | legacy → NaN ([bhavcopy_to_contract.py:104-111](src/data/bhavcopy_to_contract.py#L104-L111)) |
| `contracts` | `TtlTradgVol` | `CONTRACTS` | [:307](src/data/bhavcopy_fo_loader.py#L307)/[:252](src/data/bhavcopy_fo_loader.py#L252) | ✅ contract units (verified: 26 contracts × lot 250 = 6,500 shares) |
| **`turnover`** | **`TtlTrfVal` (RUPEES)** | **`VAL_INLAKH` (LAKHS)** | [:329](src/data/bhavcopy_fo_loader.py#L329)/[:253](src/data/bhavcopy_fo_loader.py#L253) | **🚨 mixed units, not normalized — see F1** |
| `oi` / `oi_change` | `OpnIntrst` / `ChngInOpnIntrst` | `OPEN_INT` / `CHG_IN_OI` | [:330-331](src/data/bhavcopy_fo_loader.py#L330-L331) | drives the liquidity gate |

`lot_size` is **not** stored per-row (intentionally narrow cache); resolved via unified `data/cache/lot_sizes.parquet`.

### 1b. bhavcopy → per-contract parquet (`data/cache/options/{SYM}/{YYYYMMDD}/{strike}-{CE|PE}.parquet`)

`bhavcopy_to_contract_timeseries` / `materialize_contracts_batch` ([bhavcopy_to_contract.py:297-333](src/data/bhavcopy_to_contract.py#L297-L333)):
- `volume = contracts × lot_size` ([:329](src/data/bhavcopy_to_contract.py#L329)) where `lot_size = lot_size_lookup(symbol, expiry)` ([:170](src/data/bhavcopy_to_contract.py#L170), unified parquet, **not** a stale per-row column) ✅
- `turnover` copied through **unchanged** ([:330](src/data/bhavcopy_to_contract.py#L330)) → inherits the F1 unit problem.
- Reject only if `contracts ≤ 0` on **every** day in window ([:187-194](src/data/bhavcopy_to_contract.py#L187-L194)) — `.all()`, not `.any()` ✅; partial-zero days kept and gated per-row by the engine.
- `lot_size is None` (excluded cross-source pair) → `MissingTurnoverError` ✅ ([:170-177](src/data/bhavcopy_to_contract.py#L170-L177)).

### 1c. per-contract → engine row (`price_trade`)

`pnl._price_one_leg` ([pnl.py:322-428](src/engine/pnl.py#L322-L428)) → `price_trade` ([pnl.py:452-571](src/engine/pnl.py#L452-L571)) emits the SPECS §2.5 row. Fill price = VWAP-or-close ([pnl.py:197-216](src/engine/pnl.py#L197-L216)) → slippage ([:398](src/engine/pnl.py#L398)) → `gross = (entry_realized − exit_realized) × side_sign × qty × lot` ([:402](src/engine/pnl.py#L402)).

### 1d. engine → sweep parquet → surfaces

`sweeper.sweep_one`/`sweep_grid` decorate with `entry_offset_td`, `exit_offset_td`, `entry_spot`, `exit_spot`, `notional_at_entry`, `run_id` and persist via `results.write_results` (22-col schema, [results.py:50-79](src/engine/results.py#L50-L79); engine-version stamp `p7.pricing_arc` in parquet KV-metadata). Webapp (`app.py` + `src/web/*`) and 16 MCP tools (`src/mcp/*`) read this parquet plus the raw caches.

---

## SECTION 2 — FORMULA AUDIT

| # | Formula | Source | Math | Inputs (var→column→table) | Independent verification | Verdict |
|---|---|---|---|---|---|---|
| 1 | Premium VWAP | [pnl.py:121-122](src/engine/pnl.py#L121-L122) | `turnover × 10⁵ / volume − strike` | turnover→`turnover`→option parquet; volume→`volume`; strike→`strike` | Reproduced: correct premium needs **scale 1** (turnover is rupees). Engine uses 10⁵ → 0/24,019 fills use VWAP. | **WRONG (F1)** |
| 2 | Fill-price choice | [pnl.py:197-216](src/engine/pnl.py#L197-L216) | VWAP if in `[0.5,2.0]×close` & >0 else `close` | vwap (F#1), close | Band logic itself is sound; it's the input that's broken. Displayed sweep used correct VWAP (93% match). | CORRECT logic / WRONG input |
| 3 | Slippage | [slippage.py:46-71](src/engine/slippage.py#L46-L71) | SELL→`px×(1−0.01)`, BUY→`px×(1+0.01)`; exit is opposite side | side, fill px | Reproduced gross from realized px **300/300** ✅ | CORRECT |
| 4 | Gross P&L | [pnl.py:402](src/engine/pnl.py#L402) | `(entry_real − exit_real) × side_sign × qty_lots × lot` | per-leg | Reproduced **300/300** ✅ | CORRECT |
| 5 | Cost stack | [costs.py:81-90](src/engine/costs.py#L81-L90) | brokerage ₹20×2n; STT 0.0625% sell-prem; exch 0.0503% both; GST 18%(brk+exch); SEBI ₹10/cr; stamp 0.003% buy | per-leg `entry_px`/`exit_px`×shares | Reproduced `costs` **300/300** ✅; **but ignores expiry physical-settlement STT (F3)** | CORRECT for square-off / SUSPICIOUS at expiry |
| 6 | Net P&L | [pnl.py:516](src/engine/pnl.py#L516) | `gross − costs` | — | Reproduced **300/300** ✅ | CORRECT |
| 7 | SELL-leg margin | [margin.py:118-131](src/engine/margin.py#L118-L131) | `Σ margin_pct × (spot|strike) × shares × strategy_offset` | spot→`entry_spot`; symbol_pct→`vol.py`; offset→strategy | Sign/structure correct; conservative (sums legs, no cross-leg SPAN benefit beyond offset) | CORRECT (approx, documented) |
| 8 | BUY-leg margin | [margin.py:124-127](src/engine/margin.py#L124-L127) | `entry_px × shares` (premium paid) | entry_px | Correct: max loss for long = premium | CORRECT |
| 9 | symbol_margin_pct | [vol.py:60-86](src/engine/vol.py#L60-L86) | `clamp(0.10 + 0.40×annualized_vol, 0.10, 0.30)`; vol = `std(Δlog close)×√252`, ddof=1 | spot `close`→spot cache | Formula matches docstring/SPECS; sample-stdev correct | CORRECT |
| 10 | ROI % | [pnl.py:431-436](src/engine/pnl.py#L431-L436) | `100 × net / margin` (None if margin≤0) | net, margin | Reproduced **5/5 exact**; 0 NaN in 113,801 rows | CORRECT |
| 11 | Annualized ROI | [pnl.py:439-449](src/engine/pnl.py#L439-L449) | `roi_pct × 252 / hold_trading_days` | roi, hold_td | Reproduced **5/5 exact** | CORRECT |
| 12 | hold_trading_days | [sweeper.py:216](src/engine/sweeper.py#L216) | `entry_offset_td − exit_offset_td` (exact, no 252/365 round) | offsets | Exact by construction ✅ | CORRECT |
| 13 | notional_at_entry | [sweeper.py:237-242](src/engine/sweeper.py#L237-L242) | `entry_spot × Σ(qty_lots × lot_size)` | spot, legs_json | lot_size per-leg from bhavcopy; entry==exit lot enforced ([pnl.py:369](src/engine/pnl.py#L369)) | CORRECT |
| 14 | Liquidity gate | [pnl.py:389-394](src/engine/pnl.py#L389-L394) | skip if `entry_vol==0 OR exit_vol==0 OR entry_oi==0` | volume, oi | Matches operator-stated gate. (Asymmetric: no `exit_oi` check — defensible: you can always exit.) | CORRECT |
| 15 | Cell median ROI | [analytics/heatmap.py pivot_window] / [aggregate.py:180](src/analytics/aggregate.py#L180) | `median(roi_pct)` grouped by `(strategy,symbol,entry_offset_td,exit_offset_td)` | roi_pct | Reproduced cell median **1.8122%** by hand from parquet ✅ | CORRECT |
| 16 | CVaR-5% | [cell_stats.py:85-99](src/analytics/cell_stats.py#L85-L99) | `mean(sorted_asc[: max(1, ⌈0.05n⌉)])`, NaN-dropped | roi_pct | Reproduced `mean(worst 2 of 25) = −1.9391%` ✅ | CORRECT |
| 17 | Win rate | [aggregate.py:175](src/analytics/aggregate.py#L175) | `100 × (net_pnl>0).sum() / n` | net_pnl | Reproduced **88.0%** for the test cell ✅ | CORRECT |
| 18 | Bootstrap CI | [analytics/bootstrap.py] | percentile bootstrap, B=1000, seed=0, α=0.05; α/2 & 1−α/2 quantiles of resampled statistic | roi_pct | Standard percentile method; deterministic seed; NaN-dropped | CORRECT |
| 19 | Ranking | [analytics/rank.py] | filter `n_trades≥min_n`, sort `median_roi_pct` desc, dense rank, lex `(strategy,symbol)` tiebreak | summary | Per-trade ROI default; thin-sample suppression + caveat | CORRECT (tiebreak ≠ sample-size — documented) |

---

## SECTION 3 — TABLE-FEATURE-USAGE AUDIT

| Check | Result |
|---|---|
| Turnover from the **right table** | ✅ from `bhavcopy_fo` → per-contract `options` parquet (not cross-fed). **But wrong units vs the engine's scale constant — F1.** |
| Turnover **units → rupees conversion** | **🚨 F1:** UDiff `turnover` is already rupees; engine multiplies by 10⁵ anyway. Legacy `VAL_INLAKH` is lakhs and would need the 10⁵. Mixed/unnormalized. |
| `contracts` vs `volume` not interchanged | ✅ `volume = contracts × lot_size` ([bhavcopy_to_contract.py:329](src/data/bhavcopy_to_contract.py#L329)); engine uses `volume` (shares) for VWAP, `qty_lots×lot_size` for P&L; `contracts` only used for the zero-trade gate. Verified 26 contracts → 6,500 shares. |
| `lot_size` source | ✅ unified `data/cache/lot_sizes.parquet` via `lot_size_lookup` ([lot_size_lookup.py:59-89](src/data/lot_size_lookup.py#L59-L89)), **not** a per-row bhavcopy column; excluded pairs → `MissingTurnoverError`. |
| `expiry` = `FininstrmActlXpryDt` everywhere | ✅ parser ([bhavcopy_fo_loader.py:319](src/data/bhavcopy_fo_loader.py#L319)); all downstream groupby/filters use the normalized `expiry`. |
| dtypes | ✅ volume int64-shares, turnover float64, oi Int64, dates datetime64[us] ([bhavcopy_to_contract.py:316-333](src/data/bhavcopy_to_contract.py#L316-L333)). |
| Regime-aware columns | ✅ legacy `ltp`→NaN ([bhavcopy_to_contract.py:104-111](src/data/bhavcopy_to_contract.py#L104-L111)); pre-P1.1 14-col caches auto-refetched ([bhavcopy_fo_loader.py:469-476](src/data/bhavcopy_fo_loader.py#L469-L476)). Note: current legacy caches are still 14-col (no turnover) → would also fall back to close. |
| Lookahead bias absent | ✅ loader windowed to `[entry,exit]`; `LookaheadError` if any row `> exit_date` ([pnl.py:349-354](src/engine/pnl.py#L349-L354)); entry priced from entry-day row, exit from exit-day row ([pnl.py:355-360](src/engine/pnl.py#L355-L360)). |
| `roi_pct` unit (PP vs fraction) | ✅ stored as **percentage points** (`100 × net/margin`); webapp `format_pct(x)` appends `%` without re-scaling. Verified consistent. |

---

## SECTION 4 — WEBAPP / MCP DISPLAY AUDIT (independent reproduction)

All reproductions run against `sweep_5f199d6984f2.parquet` + the live caches.

| Surface | Displayed value | Independent reproduction | Match |
|---|---|---|---|
| **Heatmap cell** (short_straddle/RELIANCE, entry=1/exit=0) median ROI | from `pivot_window(median, roi_pct)` grouped by `(entry_offset_td,exit_offset_td)` | hand `median(roi_pct)` over 25 expiries = **1.8122%**; mean 1.8467%; win 88.0% | ✅ |
| **Heatmap CVaR-5%** same cell | `pivot_cvar(0.05)` | `mean(sorted worst ⌈0.05×25⌉=2)` = **−1.9391%** | ✅ |
| **Per-trade P&L** (300 random rows) | `gross_pnl`, `costs`, `net_pnl` in parquet | recomputed from `legs_json` + slippage + cost model | **300/300** ✅ |
| **ROI / annualized** (5 rows) | `roi_pct`, `roi_pct_annualized` | `100×net/margin`, `roi×252/hold` | **5/5 exact** ✅ |
| **Cell-key consistency** | webapp heatmap, MCP `cell_summary`, MCP `heatmap` | all key on `(strategy,symbol,entry_offset_td,exit_offset_td)`, median over expiries (6,921 cells / 113,801 rows ≈ 16.4 expiries/cell) | ✅ identical definition |
| **MCP `cell_summary` bootstrap CI** | percentile bootstrap B=1000, seed=0, α=0.05 on median `roi_pct` | matches `analytics/bootstrap.py`; deterministic | ✅ |
| **MCP `data_quality` fallback / divergence** | "% close fallback", "vwap-vs-close divergence" | **WRONG output — see F2** (reports ~100% close w/ wrong cause; ~10⁹% divergence) | ❌ |
| **Number formatting** | `format_pct` (1 dp, `%`, signed), `format_inr` (₹/L/Cr) | reads `roi_pct` as already-PP; ₹ from `net_pnl` rupees | ✅ |
| **16 MCP tools vs MCP.md** | sub-agent mapped each handler | output structures match documented contracts; cache-only (`offline=True`) enforced; no-p-values pin in `compare_cells`; pre-arc caveats wired | ✅ (except F2 data_quality) |

**The fill-price layer is the *only* place the displayed-vs-reproducible story diverges.** Confirmed: displayed `entry_px`/`exit_px` = correct premium VWAP (93% match `turnover/vol−strike`); the current engine re-derives them as `close` (0% VWAP). Everything built on top of those fills is arithmetically faithful.

---

## METHODOLOGY & LIMITS

- **Read directly:** `pnl.py`, `slippage.py`, `costs.py`, `margin.py`, `vol.py`, `results.py`, `sweeper.py`, `bhavcopy_fo_loader.py`, `bhavcopy_to_contract.py`, `cache.py`, `lot_size_lookup.py`, `short_straddle.py`.
- **Mapped via sub-agents (web/mcp/analytics) and cross-checked behaviorally** by reproducing the actual numbers from the parquet — so the *formulas* are verified even where I cite a sub-agent's line number rather than my own read. Treat `src/web/*` and `src/mcp/*` line numbers as sub-agent-sourced; the engine/data line numbers are first-hand.
- **Empirical fixtures used:** `data/cache/bhavcopy_fo/20240829.parquet`, `data/cache/options/{RELIANCE,SBIN,PNB,BHEL}/{20240725,20240829,20240926}/*.parquet`, `data/results/sweep_5f199d6984f2.parquet`.
- **Could not verify:** legacy-regime VWAP path end-to-end (current legacy caches are 14-col, no `turnover`; no pre-2024-07-08 rows in the materialized contracts sampled) — legacy "lakhs" is asserted from the column name + the commit history, not re-derived from data. `trading_calendar.offset_trading_days` and `expiry_calendar.monthly_expiries` correctness assumed (not re-derived against an external NSE calendar).

## VERDICT SUMMARY

- **Displayed data (current sweep parquet): TRUE and faithfully derived.** ✅ Correct premium VWAP fills; all downstream math reproduces 100%.
- **Current code + current cache: a live unit-mismatch regression (F1)** that silently disables VWAP (100% close fallback), makes the displayed sweep non-reproducible, and produces wrong `data_quality` diagnostics (F2). One conservative-direction cost caveat (F3).
- **One fix (normalize turnover units / correct `TURNOVER_SCALE_FACTOR`) closes F1 and F2 together.**

---

## ADDENDUM 1 (2026-06-03) — closes the F1 "could not verify jugaad regime" gap; resolves the smoke-gate risk

Triggered by the architectural reviewer's independent concurrence with F1 (commit `3aefddb`, `comments.md` only — no source change, so nothing code-level to logic-review there). They raised one load-bearing open question that maps exactly to the gap I flagged in §METHODOLOGY: **is jugaad's `FH_TOT_TRADED_VAL` actually lakhs?** If it were *rupees*, both `--engine-source` paths would fall back to `close` identically and the migration smoke gate would **vacuously pass**, shipping the broken VWAP to P1.7. I resolved it two independent ways:

**(a) Analytic proof — jugaad turnover at sweep time WAS lakhs (airtight).**
- `TURNOVER_SCALE_FACTOR = 100_000` was introduced in `6356b90` (2026-05-28) and never changed; it is an ancestor of HEAD and predates the displayed sweep (`sweep_5f199d6984f2.parquet`, mtime 2026-05-31). So the engine used `×10⁵` when the sweep ran.
- I measured: displayed `entry_px`/`exit_px` = `turnover_now/volume − strike` (93% of legs), where `turnover_now` is today's **rupee** value.
- For the `×10⁵` engine to have produced that under the jugaad cache: `jugaad_turnover × 10⁵ / vol − strike = turnover_now/vol − strike` ⟹ `jugaad_turnover = turnover_now / 10⁵` = **lakhs**. ∎

**(b) Corroboration — NSE historical API reports traded value in lakhs.** In the jugaad reference repo (`/Users/mriddy/Documents/GitHub/jugaad-data`), the equity-historical sibling column is literally named `TURNOVER_LACS` (`tests/test_bhav.py:14`); `FH_TOT_TRADED_VAL` follows the same NSE-historical-API lakhs convention. This is a *different* NSE product from the daily UDiff full bhavcopy, whose `TtlTrfVal` is in **rupees** (proven directly in F1).

**Conclusions:**
1. **The displayed sweep's VWAP is definitively CORRECT** — jugaad lakhs `× 10⁵` = rupees → correct premium (~185 for the RELIANCE 2840-CE example). The data the operator sees today is true and best. ✅
2. **The smoke-gate "both-paths-wrong" risk does NOT materialize.** Because jugaad = lakhs (correct VWAP ≈ 185) and UDiff = rupees (silent `close` fallback ≈ 201.70), `--engine-source api` vs `bhavcopy` will **diverge ~9% per fill** → the gate's 0.5-pp ROI criterion **fails loud**. The migration gate is a genuine safety net for F1, not a vacuous pass.
3. **The two regimes have genuinely different units** (jugaad/legacy = lakhs; UDiff = rupees). This is the root of F1 and confirms the fix must normalize units at parse time, not just tweak one constant. (I concur with the architectural reviewer's recommendation #3 and the anti-regression test in #4.)

Net effect on the §METHODOLOGY limits: the jugaad-regime item is now **resolved** (lakhs, proven). The legacy-bhavcopy regime remains inference-only (current legacy caches are 14-col, no `turnover`), but it is *not* the regime the displayed data or current sweeps run under, so it is not operator-facing today.
