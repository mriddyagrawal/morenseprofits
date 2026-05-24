# DESIGN_SPEC — Phase 6 UI + frozen design decisions

> Companion to PLAN.md and SPECS.md. PLAN says *what and why*; SPECS pins *data + engine contracts*; this file pins **UI architecture, visualization choices, and workflow decisions** so the next ~18 commits don't relitigate them.
>
> Decided 2026-05-24. Departures from any decision below land here with a `[REVISED YYYY-MM-DD]` note explaining why, mirroring PLAN.md §7 discipline.

## 0. Status going in

- Phases 0–5 complete: data layer, universe, 5 strategies, engine (P&L + costs + slippage + Tier-B margin), sweeper, aggregator trio (per-pair / per-year / per-month), heatmap pivots, ranker.
- Phase 6 (Streamlit UI) is next. `src/web/` currently contains only `__init__.py`.
- 5 sweep parquets exist on disk; the canonical small-set dev target is the 18-row Q1-2024 RELIANCE short-straddle parquet from `chore(p4.verify)`.

### 0.1 Load-bearing constraints carried over from prior reviews

These are not new design choices — they are non-blocking-but-load-bearing items the reviewer flagged in Phases 4-5 that the Phase-6 skeleton MUST honor from commit p6.1.app onward (not bolted on later):

| origin | constraint | where addressed |
|---|---|---|
| 416719f | small-N sweeps exhaust every cell at default `min_n=5`; UI must expose the threshold | §1.2 sidebar slider; §2.2 heatmap masking driven by same slider |
| 955d0f3 | `rank_strategies` lex tiebreaker is defensible only if `n_trades` is visually prominent | §2.2 leaderboard: `n_trades` own column, right of `rank`, equal weight |
| 955d0f3 | `rank_strategies` single-table output silently drops thin samples | §4 commit `feat(p6.2.thin)` — explicit "Thin samples — not ranked" sidecar |
| 416719f | `min_n=0` used by `verify_p5` is verify-only; Phase 6 must default to 5 | §1.2 default = `MIN_N_FOR_RANKING = 5` |
| afdd56e | `std_roi_pct` is observed-sample dispersion (ddof=0), not a population estimate | §2.2 tooltip copy below |
| afdd56e | Sharpe-like ≠ real Sharpe (real subtracts ~6.5% Indian risk-free) | §2.4 — Sharpe-like excluded from v1 leaderboard sort menu |

## 1. Phase 6 — UI architecture

### 1.1 App shell — `st.tabs`, NOT `pages/`

**Decision:** single `app.py` at repo root, 4 tabs via `st.tabs`.

**Why:** Streamlit's `pages/` multi-page nav loses cross-page state unless every selection is wired through `session_state`. Research-tool ergonomics demand "same strategy / symbol / sweep, different lens" — tabs keep state automatic; pages don't. Migrating tabs → pages later is a one-hour move if it ever gets crowded.

**Tab order (left → right):**

1. **Leaderboard** — landing tab; sortable rank table + thin-sample sidecar.
2. **Per-stock** — single-symbol dashboard (all strategies × windows).
3. **Heatmap** — `(entry_offset × exit_offset)` matrix for one (strategy, symbol).
4. **Trends** — YoY decay line + MoY seasonality bars for one (strategy, symbol).

### 1.2 Sidebar — single source of cross-cutting state

Every tab reads filters from `st.session_state`; controls live in the sidebar.

| control | type | default | feeds |
|---|---|---|---|
| sweep picker | selectbox | most-recent-by-mtime under `data/results/sweep_*.parquet` | every tab |
| strategy filter | multiselect | all strategies in the sweep | every tab |
| symbol filter | multiselect | all symbols in the sweep | every tab |
| min N slider | int slider | `MIN_N_FOR_RANKING` = 5 | leaderboard ranker + heatmap masking |
| regime filter | radio | "all" / bullish / neutral / non_bullish | symbol filter post-classification |

Sweep picker caption shows `run_id` + row count + mtime so the operator can switch deliberately.

**Per-stock quick-switcher** (Per-stock tab only, NOT a sidebar control): a button row at the top-right showing the symbols currently passing the sidebar filter (truncated to top-N=8 by trade count if filter is empty / wide). Clicking a button selects that symbol for the per-stock dashboard; **does NOT mutate the sidebar filter**. Sidebar filter remains canonical; switcher is a navigation convenience within the filter. Resolves the "two sources of truth" hazard.

### 1.3 Default landing — Leaderboard

**Decision:** Leaderboard tab selected on launch.

**Why:** "What's worth investigating?" is the operator's first question on a fresh sweep. Drill-downs come second.

### 1.4 Caveats — three always-visible cards with single-shot dismiss

**Decision** *[REVISED 2026-05-25 — mockup alignment; stronger honesty contract than the original expander design]*: render three side-by-side cards at the top of every tab, each holding one caveat. A "Read once, then dismiss" link collapses the row into a slim **single-line banner** ("⚠ 3 active caveats — click to expand") that stays visible until the operator re-expands or reloads.

Three cards, left → right:

1. **Multiple-comparisons** — imported from `src.analytics.rank.MULTIPLE_COMPARISONS_CAVEAT`. No copy-paste duplication.
2. **Survivorship-bias** — SPECS §6b.3 paragraph. v1 blue-chip is a 2024-07-01 snapshot.
3. **Margin-Tier-B asymmetry** — SPECS §4a caveats 1, 3, 4 summarized: ranking is biased toward high-vol symbols + low-offset strategies relative to a real broker SPAN file.

**Why cards over an expander:** an expander defaults to a single label-line that operators learn to ignore. Three always-visible cards force the caveats into the first read of every session; the slim post-dismiss banner keeps them re-callable without consuming real estate. Stronger honesty contract than the original expander design. PLAN §3 Phase 6.5 exit criterion ("caveats banner always visible") is satisfied — both expanded and dismissed states keep at least one always-rendered visual element.

**Dismiss state is session-scoped** (`st.session_state["caveats_dismissed"]=True`); a browser refresh re-expands. Never write the dismissed state to disk.

### 1.5 Data source picker — newest by mtime

**Decision:** auto-pick the most recently modified `sweep_*.parquet`. Sidebar shows row count + run_id + mtime in the caption.

**Why not "largest by row count":** a stale-but-big historical sweep would silently outrank the one the operator just produced. mtime matches the mental model "the sweep I just ran."

## 2. Visualization decisions

### 2.1 Heatmap library — Plotly

**Decision:** Plotly (`plotly.graph_objects.Heatmap` with `customdata`) for the entry × exit matrix.

**Why:** hover tooltips composing `(n_trades, win_rate_pct, std_roi_pct, total_net_pnl)` per cell is the killer feature for a research tool. Altair's tooltip composition is more limited; matplotlib has no interactivity; `st.dataframe` conditional formatting doesn't tell the (entry, exit) story visually.

**Requirements change** (lands in `chore(p6.0.deps)`):

- add `plotly>=5.20` to `requirements.txt`.
- drop `altair` if a repo-wide grep shows no in-tree usage (Streamlit's own charts will fall back gracefully).

### 2.2 N rendering — separate column + separate density heatmap

**Leaderboard:** `n_trades` is its own column, immediately right of `rank`. Same visual weight as `rank` (no bold/large styling on either; both are columns, not headlines).

**Heatmap:** cell text annotation is the metric value only (`247.9%`); N goes in the hover tooltip. A second small heatmap rendered side-by-side ("Sample density") shows `pivot_counts` with a sequential colormap. Cells with `n < min_n` are masked in the value heatmap via `pivot_window.where(pivot_counts >= min_n)`. Two clean visuals beat one cluttered one.

**Tooltip copy for any `std_roi_pct*` column or hover** (leaderboard + heatmap): *"observed-sample dispersion (ddof=0), not a population estimate. ddof=0 vs unbiased ddof=1 understates std by `1 − sqrt((n−1)/n)`: ~11% at n=5, ~5% at n=10, ~2.5% at n=20."*

*[REVISED 2026-05-25 — corrected from "~20% at n=5". Source review (afdd56e) cited a 20% number that was the **variance** gap; for **std** the gap is sqrt of that ≈ 11%. The tooltip is about std, so 11% is correct.]*

### 2.3 Color scales + theme

- **App theme:** dark by default (`.streamlit/config.toml` → `base = "dark"`). Matches every mockup. Operators can flip via Streamlit's hamburger menu.
- **Metric heatmap:** **diverging** colormap anchored at 0 (`colorscale="RdYlGn"` + `zmid=0` in Plotly). Reds for losses, greens for gains. **Sequential green-to-yellow is wrong** even when all visible cells are positive — first negative cell on a later sweep would render mid-green and mislead. Pin diverging unconditionally.
- **Density heatmap:** sequential (viridis or blues), 0 = white.
- **Leaderboard win_rate / std:** no inline color; rely on user scanning. Adding row coloring to a sortable table fights the sort.

### 2.4 Leaderboard sort menu — what's in, what's out

**In** (v1 leaderboard `sort_by` dropdown options):

- `median_roi_pct_annualized` *(default)* — robust + cross-window-comparable.
- `mean_roi_pct_annualized` — same axis, mean instead of median.
- `total_net_pnl` — absolute rupee P&L over the sample.
- `win_rate_pct` — fraction of profitable trades.

**Out of v1** (deliberately not in the dropdown): **Sharpe-like (`mean / std`).** It's tempting because the columns are now there (afdd56e), but a column labeled "Sharpe" that doesn't subtract the ~6.5% Indian risk-free rate mis-anchors interpretation. Three forward options, all post-v1:

1. **Real Sharpe** with a sidebar risk-free-rate input (default 0.065).
2. **Rename to "RoR / dispersion"** to avoid the Sharpe association entirely.
3. **Leave it out** — power users can always compute it via `df.assign(...)` outside the UI.

The `rank_strategies` API supports arbitrary `by=` columns, so adding any of these later is a 2-line change — keep it out of v1 to avoid teaching operators a misleading proxy first.

### 2.5 Headline stats strip — per-tab contract

*[NEW 2026-05-25 — captures the 4-card / 3-card strips visible across all mockups; pins exactly which subset feeds each card so mockup → code can't introduce labeling bugs like "AVG ROI ₹25.76L" (a rupee value mislabeled as a percentage).]*

Each tab gets a strip of 3-4 high-density cards near the top, **below the caveats row, above the main visual**. Each card = a single number + a one-line subtitle naming its denominator. Cards are pure read-only summaries of the currently-filtered sweep frame — no controls inside cards.

**Naming rule:** if the value is in rupees, the card label MUST contain "P&L" or "₹"; never "ROI". If the value is a percentage, the card label MUST end in "%" or "%/yr"; never a bare number. This is the contract that prevents the "AVG ROI ₹25.76L" mockup bug.

**Per-tab contracts:**

| tab | card | value | subtitle |
|---|---|---|---|
| Leaderboard | TOP PAIR | `rank=1` row's `strategy × symbol` | headline metric, e.g. `+247.9 %/yr median ann. ROI` |
| Leaderboard | OVERALL WIN RATE | `(net_pnl > 0).sum() / n_trades * 100`% | `X of Y trades profitable` |
| Leaderboard | TOTAL NET P&L | `sum(net_pnl)` formatted as `₹X.XX L` or `₹X.XX Cr` | `across N rank-eligible cells` |
| Leaderboard | RANKED PAIRS | `n_above_min_n / n_pairs_total` | `min_n=K from sidebar` |
| Per-stock | TOP STRATEGY | strategy with best `median_roi_pct_annualized` for selected symbol | `+X.X %/yr median ann.` |
| Per-stock | SYMBOL WIN RATE | overall win rate for the symbol | `X of Y trades` |
| Per-stock | SYMBOL TOTAL P&L | sum of `net_pnl` for the symbol | `across all strategies × windows` |
| Per-stock | STRATEGIES ABOVE BENCHMARK | count where `median_roi_pct_annualized > 0` | `out of total tested` |
| Heatmap | BEST CELL | `pivot_window.max().max()` (post-mask) | `(entry T-?, exit T-?)` |
| Heatmap | WORST CELL | `pivot_window.min().min()` (post-mask) | `(entry T-?, exit T-?)` |
| Heatmap | MEDIAN CELL | `pivot_window.stack().median()` | `across N visible cells` |
| Trends | BEST MONTH | `summarize_by_month`'s top row by median ann. ROI | `e.g. Feb +269.3 %/yr` |
| Trends | WORST MONTH | bottom row | `e.g. Mar +106.5 %/yr` |
| Trends | TIGHTEST MONTH STD | `summarize_by_month`'s `std_roi_pct.idxmin()` | `±X.X %` |
| Trends | LATEST YEAR ROI | `summarize_by_year`'s most recent year | `vs prior year ±X.X pp` |

**Empty-frame fallback:** if the current filter produces 0 rows, every card renders `—` with subtitle `no data after filters`. No `nan%` ever shown.

### 2.6 Degenerate / thin-data UX contract

*[NEW 2026-05-25 — the Q1-2024 verify set is degenerate on every axis: 1 strategy, 1 symbol, 1 year, 3 months. Every tab must handle this gracefully — the spec was silent before.]*

Each tab states one rule for "not enough data to show this visual." When the rule triggers, render an `st.info` box with the rule + the operator action, NOT an empty chart with axes:

| tab | trigger | message |
|---|---|---|
| Leaderboard | 0 rows after filters | "No (strategy, symbol) pairs match the current filters. Widen the sidebar selection or pick a different sweep." |
| Leaderboard | 0 rows pass `min_n` AND ≥1 row exists | "All N pairs have fewer than `min_n=K` trades. Lower the threshold (sidebar slider) to inspect anyway, or run a larger sweep." |
| Per-stock | 0 strategies for the selected symbol | "No trades for `SYMBOL` in this sweep. Pick another symbol." |
| Heatmap | every cell masked by `min_n` | "Heatmap is empty: every (entry, exit) cell has fewer than `min_n=K` trades. Lower the threshold or run a larger sweep." |
| Heatmap | dataset spans <2 entry offsets OR <2 exit offsets | "A heatmap needs ≥2 offsets on each axis. This sweep has E entry offsets × X exit offsets — render leaderboard cells instead." |
| Trends — YoY | dataset spans <2 distinct years | "YoY decay needs ≥2 years of trade data. This sweep covers Y year(s)." |
| Trends — MoY | dataset spans <2 distinct months | "Monthly seasonality needs ≥2 calendar months. This sweep covers M month(s)." |

Never render a `nan` axis or a one-bar bar chart and call it a trend.

### 2.7 Number formatting + rounding

*[NEW 2026-05-25 — pin once so mockup-to-code conversion is mechanical.]*

| quantity | format | example | rounding |
|---|---|---|---|
| Holding-period ROI | `+X.X%` (with sign) | `+4.6%` | 1 decimal |
| Annualized ROI | `+X.X%/yr` | `+247.9%/yr` | 1 decimal |
| Win rate | `X.X%` (no sign) | `83.3%` | 1 decimal |
| Rupee P&L < ₹1 lakh | `₹X,XXX` | `₹6,923` | nearest rupee |
| Rupee P&L ₹1 lakh — ₹99 lakh | `₹X.XX L` | `₹1.25 L` | 2 decimals |
| Rupee P&L ≥ ₹1 crore | `₹X.XX Cr` | `₹2.58 Cr` | 2 decimals |
| Counts (N, n_winning) | bare int | `18` | none |
| Strike prices | bare int | `2600` | int (SPECS §5) |

Indian lakhs/crores convention because the operator is INR-native. A `format_inr(x)` helper in `src/web/_format.py` is the single implementation; every card + table column calls it.

## 3. Pre-Phase-6 data scope

### 3.1 Build the UI on the 18-trade verify set first

**Decision:** the first 7 Phase-6 commits (p6.0.* + p6.1.*) build the skeleton against sweep parquets that already exist on disk. No new sweeps before the UI shell is wired end-to-end.

**Why:** design bugs (degenerate single-row leaderboard, single-year trend tab, sparse heatmap, every cell suppressed by `min_n=5`) surface on small data and force us to handle empty / thin cases gracefully. Visual-polish bugs surface on big data — those come after the skeleton works.

### 3.2 First "real" sweep dimensions

Run as `chore(p6.5.sweep)` between the per-stock tab and the polish commit:

| dimension | value | reason |
|---|---|---|
| symbols | RELIANCE, HDFCBANK, INFY, ICICIBANK, TCS (5) | highest-liquidity blue chips; bhavcopies reliable across full window |
| years | 2023, 2024 | enough for a YoY view; first sweep avoids the legacy-format pre-2024-07-08 boundary noise |
| strategies | short_straddle, short_strangle, iron_condor (3) | short-vol family is the research target; longs are mirrors and rank-uninteresting in low realized-vol |
| entry offsets (td) | 15, 12, 9, 6, 3 | sane window range without exploding cell count |
| exit offsets (td) | 3, 1, 0 | hold-to-near-expiry / hold-to-day-before / hold-to-expiry |
| **total cells** | 5 × ~24 expiries × 3 × 5 × 3 ≈ **5,400** | ~3-4k will price out after MissingData / NoLiquidStrike skips |

**Cold-cache fetch budget:** ~20-30 min for bhavcopies (one per month per year ≈ 24) + options (~3-4k contracts). Subsequent sweeps post-cache: ~30-60s serial.

The full 40-stock universe sweep waits until Phase 7 user-curated-universe lands, or runs overnight before any "real" share.

### 3.3 Year range — staged

- UI dev sets: whatever the existing verify parquet has (Q1-2024).
- First "real" sweep: 2023-2024 (2 years).
- 3-year sweep (2022-2024) lands when YoY decay charts start producing actionable signal — Phase 6.4 polish at the earliest.

## 4. Phase 6 nuclear commit breakdown

PLAN §3 Phase 6 lists 5 high-level commits — too coarse for the nuclear-commits doctrine. Sub-phase breakdown:

### Phase 6.0 — Contracts + deps + formatting

1. `chore(p6.0.spec)`: SPECS §11 — web/ page contract; sweep-discovery rule; canonical caveat copy as constants.
2. `chore(p6.0.deps)`: requirements.txt — add `plotly`; drop `altair` if grep-clean.
3. `feat(p6.0.format)`: `src/web/_format.py` — `format_inr(x)` + `format_pct(x, *, signed=False, annualized=False)` per §2.7.
4. `test(p6.0.format)`: rounding + ₹/L/Cr boundaries + sign handling.

### Phase 6.1 — Skeleton

5. `feat(p6.1.discover)`: `src/web/discover.py` — `find_latest_sweep() -> Path` + `read_sweep_with_skips(run_id) -> (results_df, skips_df)`.
6. `test(p6.1.discover)`: empty / multiple / mtime-tied / corrupt-file cases.
7. `feat(p6.1.caveats)`: `src/web/caveats.py` — three constants + `render_caveats_strip()` (three cards) + `render_caveats_collapsed()` (slim banner) per §1.4.
8. `feat(p6.1.empty)`: `src/web/empty_state.py` — `render_empty(tab, reason, action)` per §2.6 contract. Six pre-written messages, one per row of the §2.6 table.
9. `feat(p6.1.app)`: `app.py` — sidebar (sweep picker, multi-strategy/symbol filters, min_n slider, regime radio) + 4 placeholder tabs + caveats strip + empty-state placeholders.
10. `chore(p6.1.verify)`: launch `streamlit run app.py` against current sweep parquets; screenshot; confirm sidebar state persists across tab switches AND every tab degrades gracefully on the Q1-2024 verify set.

### Phase 6.2 — Leaderboard tab

11. `feat(p6.2.headline)`: 4-card strip per §2.5 Leaderboard row — TOP PAIR / OVERALL WIN RATE / TOTAL NET P&L / RANKED PAIRS.
12. `feat(p6.2.table)`: `st.dataframe` of `rank_strategies(summarize_by_stock_strategy(df), min_n=sidebar_min_n)` with column config (rank, strategy, symbol, n_trades, win%, median_roi_ann, mean_roi_ann, std, total_net_pnl).
13. `feat(p6.2.thin)`: sidecar table below — rows with `n_trades < min_n` rendered under "Thin samples — not ranked".
14. `feat(p6.2.toggle)`: `st.radio` at top — "Within stock" (group by symbol, rank strategies per symbol) vs "Across stocks" (rank all pairs together).

### Phase 6.3 — Heatmap tab

15. `feat(p6.3.headline)`: 3-card strip per §2.5 Heatmap row — BEST / WORST / MEDIAN cell.
16. `feat(p6.3.pivot)`: dual Plotly heatmaps (value + density) for the selected (strategy, symbol); thin cells masked per §2.2; **diverging colormap with `zmid=0`** per §2.3.
17. `feat(p6.3.hover)`: tooltip composition — `customdata=[n_trades, win_rate, std, total_net_pnl]`; std tooltip text per §2.2.

### Phase 6.4 — Trends tab

18. `feat(p6.4.headline)`: 4-card strip per §2.5 Trends row — BEST / WORST MONTH + TIGHTEST STD + LATEST YEAR.
19. `feat(p6.4.yoy)`: Plotly line — `summarize_by_year(df).query("strategy==X and symbol==Y")` median ann. ROI over years.
20. `feat(p6.4.yoy_n)`: sister chart — same x-axis, dual-axis win-rate (line) + sample-size (bars). Surfaces sparse-year diagnostic as a visual, not just a tooltip. *[replaces the original p6.4.n_hover per mockup alignment.]*
21. `feat(p6.4.moy)`: Plotly bar — `summarize_by_month(df).query("strategy==X and symbol==Y")` Jan-Dec.

### Phase 6.5 — Per-stock tab + polish

22. `feat(p6.5.headline)`: 4-card strip per §2.5 Per-stock row + per-stock quick-switcher buttons per §1.2.
23. `feat(p6.5.dash)`: per-symbol dashboard — all strategies' summary stats as small-multiples cards (one card per strategy, each with N + win% + median ann. ROI + a sparkline of per-trade `net_pnl`).
24. `chore(p6.5.sweep)`: live run of the §3.2 sweep; confirm cache fills cleanly.
25. `chore(p6.5.verify)`: screenshot every tab against the new sweep; record any visual-polish followups for Phase 7.
26. `chore(p6.5.tag)`: `git tag v0.6-ui`.

## 5. Strategy / regime decisions

### 5.1 Regime classifier — trailing 6-mo total return (already built)

**Decision:** Phase 6 regime filter uses `classify_momentum(as_of, universe)` from `src/universe/momentum.py` unchanged. Tercile split on trailing-126-trading-day return. No realized-vol or RSI parallel classifier in v1.

**Why:** already implemented + tested; a second classifier is scope creep. The momentum split answers "is this strategy biased toward bullish regimes?" — the operator's actual question.

### 5.2 Cross-stock ranker — both views via one toggle

**Decision:** `st.radio` at the top of the Leaderboard tab:

- **Within-stock** — group by symbol, rank strategies per symbol ("which window for stock X?")
- **Across-stocks** — rank all (strategy, symbol) pairs together ("which stocks pay short straddles best?")

Both views are first-class research questions; one toggle is cheap.

## 6. Workflow decisions

| topic | decision | reason |
|---|---|---|
| branching | stay on `main` | solo dev; reviewer-watches-main pattern works; branches add friction without benefit |
| tagging | tag every phase boundary — `v0.5-aggregation` retroactively at current HEAD; `v0.6-ui` at end of Phase 6 | free time-machine pin; trivial to maintain |
| type-checking | defer mypy / pyright | pytest catches almost everything in this style of code; adding a typechecker now is a yak-shave |
| dependency policy | pin in `requirements.txt` to versions that produced a passing test suite; bump deliberately | SPECS-enshrined; Phase 6 adds plotly under the same policy |

## 7. Deferred-phase ordering

| phase | when | gate |
|---|---|---|
| Phase 7 — user-curated universe + per-quarter blue-chip | after Phase 6 ships | none; purely additive |
| Phase 8 — MCP research API | strictly after Phase 6 | reduces concurrent fronts (solo dev) |
| Phase 9 — paper trading | after Phase 8 | provides the dataset the paper-trade tools consume |
| Phase 10 — live trading | after ≥3 months of paper-trade track record matching backtest expectations | PLAN.md §3 hard prerequisites enforced — kill switch, runbook, per-trade human approval |

## 8. Wiring constraints that touch existing code

Decisions here intentionally minimize Phase-7 surgery and prevent duplication:

1. **Universe accepts `list[str]` everywhere in Phase 6.** The sidebar symbol filter passes a `list[str]`; no tab module calls `blue_chip(as_of)` directly. Phase 7's "operator pastes their list" becomes a sidebar text-area → `list[str]` conversion, not a refactor.
2. **Caveat constants are re-exported, not duplicated.** `src/web/caveats.py` imports `MULTIPLE_COMPARISONS_CAVEAT` from `src.analytics.rank`; survivorship + margin caveats live in `caveats.py` as new constants (no prior canonical home). One source of truth per caveat.
3. **Sweep discovery lives in `src/web/discover.py`, not `app.py`.** Keeps `app.py` thin (UI shell only); discovery is unit-testable.
4. **Min-N filter flows top-down.** Sidebar `min_n` value is read by both the leaderboard ranker AND the heatmap masking; never hardcoded inside a tab. Moving the slider updates every view consistently.

## 9. Open questions (intentionally TBD)

- **Sweep-refresh button in UI.** Should the sidebar shell out to `sweep_grid`? **v1: no** — sweeps are a CLI affair via `scripts/verify_p*.py`; UI is a viewer. Revisit if operators ask.
- **CSV / PNG export.** Phase 6 doesn't ship export buttons. `st.download_button` is trivial to add later.
- **Compound-return projection.** SPECS §4a caveat: `total_net_pnl` is a sum, not compounded. Phase 6 reports both `mean_net_pnl` per trade and `total_net_pnl` over the sample but no compounded projection — Phase 7+ when capital-allocation modeling lands.
- **Per-symbol slippage override.** SPECS §4b backlog. Phase 6 reports under uniform 1% slippage; UI doesn't expose the knob.
- ~~**`verify_p5` section (b) prints unmasked heatmap + a count instead of the masked view.**~~ **RESOLVED in 8893b81** — `scripts/verify_p5.py` lines 120-129 now print the masked view alongside the count; on the current 18-trade dataset this surfaces a fully NaN grid (each cell n=3 < MIN_N=5).
- ~~**Empty-frame StringDtype** drifts to object via `_inferred_dtype` (1a5cf01).~~ **RESOLVED in 8893b81** — `src/engine/results.py` `_inferred_dtype` now maps string-like columns (`strategy`, `symbol`, `run_id`, `params_json`, `legs_json`, `*_breakdown_json`, `skip_reason`) to `pd.StringDtype()`.

## 10. Usefulness check — 5-minute operator journey

*[NEW 2026-05-25 — validates the design is useful, not just coherent. If this journey doesn't flow, the design is wrong even if the spec is internally consistent.]*

Operator just ran the §3.2 first-real sweep (5 stocks × 3 strategies × 2 years). Opens the app:

1. **Land on Leaderboard.** Caveats row (3 cards) demands attention; operator reads, clicks dismiss → slim banner. Headline strip shows TOP PAIR = `short_straddle × RELIANCE +247.9 %/yr`, OVERALL WIN RATE 83 %, TOTAL P&L ₹4.21 L, RANKED PAIRS 13/15. → Decides to investigate the #3 row: `iron_condor × HDFCBANK +189.4 %/yr`.
2. **Switch to Per-stock tab.** Sidebar symbol filter is still empty (= all). Quick-switcher shows the top-8 by N; operator clicks HDFCBANK. Five strategy cards render — `iron_condor` card stands out: 80 % win, sparkline of net_pnl shows 4 wins in a row. → Wants to see the offset window.
3. **Switch to Heatmap tab.** Filters carry over (HDFCBANK selected); operator picks `iron_condor` from the in-tab strategy picker. Dual heatmap: value pane shows (entry T-12, exit T-3) as the hot green cell at +312 %/yr; density pane shows that cell has N=8 (above `min_n=5` slider). → Window identified.
4. **Switch to Trends tab.** YoY line: 2023 +120 %/yr, 2024 +218 %/yr → upward drift, not decay. YoY sister chart (win-rate + N bars): N=24 in 2023, N=22 in 2024 — comparable samples, the upward drift is real not a thin-sample artifact. MoY bar: Feb is best (+295 %/yr), Aug is worst (+34 %/yr) → potential seasonality.
5. **Switch regime filter to "bullish"** in the sidebar. Every tab re-renders against the bullish-subset symbols. Leaderboard reshuffles; iron_condor × HDFCBANK is still #1 in the bullish bucket → confirms the strategy isn't just a bear-trap edge case.

**What this journey validates:**

- Cross-tab state must persist (st.tabs over pages) — used at steps 2/3/4.
- Caveats must be unmissable on first view but compressible after (3-card-then-dismiss) — used at step 1.
- Headline strip must surface the headline pair clearly enough that the operator's next click is unambiguous — used at step 1.
- The sparkline on per-stock cards is what makes step 2's "stands out" judgment fast. Plain numbers wouldn't.
- The YoY sister chart (the mockup-driven addition that replaced `n_hover`) is load-bearing for step 4's "drift is real" call. A bare YoY line would leave the operator unsure if 2024's bigger number is signal or N-fluke.
- Regime filter at step 5 only earns its keep if it ripples to every tab simultaneously; that's why it's a sidebar control, not a tab-local widget.

**Failures this journey would expose:** if the per-stock quick-switcher mutated the sidebar filter, step 2 would silently change the leaderboard the operator returns to — sidebar canonicality (§1.2) is what prevents that. If the heatmap didn't carry HDFCBANK over from per-stock, step 3 needs the operator to re-pick — friction that breaks the flow. If headline cards mislabeled rupees as ROI (the mockup bug), step 1's investigation choice would be on a misread number.

## 11. Change log

- 2026-05-24 — file created. All 17 decisions in §§1-7 frozen as of this date; departures recorded here per the discipline noted in the header.
- 2026-05-24 — added §0.1 (cross-reference to prior-review load-bearing items), §2.4 (Sharpe-like deliberately excluded from v1 sort menu), std-tooltip copy in §2.2, and `verify_p5` + StringDtype followups in §9. No behavior changes to §§1-7 decisions; this is making implicit constraints explicit.
- 2026-05-25 — **mockup-coherence pass + correctness audit**:
  - §1.2 added per-stock quick-switcher (sidebar-canonical, switcher is navigation only).
  - §1.4 replaced "expander, collapsed-state operator choice" with "three always-visible cards + dismiss-to-banner" (stronger honesty contract; matches mockup).
  - §2.2 corrected std tooltip math (~20% → ~11% at n=5; the 20% was the **variance** gap not the std gap).
  - §2.3 added dark-theme line; reinforced diverging colormap unconditionally (mockup looked sequential green — must flip to red on the first negative cell).
  - §2.5 NEW — headline stats strip per-tab contract. Forced by mockup labeling bug "AVG ROI ₹25.76L" (rupees mislabeled as percentage); now structurally prevented.
  - §2.6 NEW — degenerate / thin-data UX contract. Every tab states its "not enough data" rule with concrete operator action.
  - §2.7 NEW — number formatting / rounding contract; single `format_inr` helper.
  - §4 nuclear commits updated: added `p6.0.format` + `p6.0.format test` + `p6.1.empty` + `p6.2.headline` + `p6.3.headline` + `p6.4.headline` + `p6.5.headline`; replaced `p6.4.n_hover` with `p6.4.yoy_n` (sister chart per mockup). Total Phase-6 commit count: 19 → 26.
  - §10 NEW — 5-minute operator user journey as a usefulness check.
  - **Open mockup followups** (out of spec — for the design tooling): mockup label "AVG ROI ₹25.76L" should read "TOTAL NET P&L"; mockup "AVG ROI +264.1 %/yr" / "BEST CELL +82.3 %/yr" pair is internally inconsistent (best can't be lower than avg) — reconcile before screenshots are reused as docs.
