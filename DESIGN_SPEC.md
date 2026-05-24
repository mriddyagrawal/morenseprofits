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

### 1.3 Default landing — Leaderboard

**Decision:** Leaderboard tab selected on launch.

**Why:** "What's worth investigating?" is the operator's first question on a fresh sweep. Drill-downs come second.

### 1.4 Caveats — one expander, open by default, top of every tab

**Decision:** a single `st.warning`-styled expander at the top of every tab, open on first render. Three sections inside:

1. **Multiple-comparisons** — imported from `src.analytics.rank.MULTIPLE_COMPARISONS_CAVEAT`. No copy-paste duplication.
2. **Survivorship-bias** — SPECS §6b.3 paragraph. v1 blue-chip is a 2024-07-01 snapshot.
3. **Margin-Tier-B asymmetry** — SPECS §4a caveats 1, 3, 4 summarized: ranking is biased toward high-vol symbols + low-offset strategies relative to a real broker SPAN file.

**Why one expander not three banners:** stacked banners → banner blindness. One labeled expander → operator reads it once, collapses, page is clean for the rest of the session. PLAN §3 Phase 6.5 exit criterion ("caveats banner always visible") is satisfied — the expander is always rendered; collapsed-state is operator choice.

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

**Tooltip copy for any `std_roi_pct*` column or hover** (leaderboard + heatmap): *"observed-sample dispersion (ddof=0), not a population estimate. Treat as a lower bound on true population variance — small-N groups understate spread by ~20% at n=5, ~2.5% at n=20."* Source: afdd56e review.

### 2.3 Color scales

- **Metric heatmap:** diverging colormap anchored at 0 (red = loss, white = breakeven, green = profit). `zmid=0` in Plotly.
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

### Phase 6.0 — Contracts + deps

1. `chore(p6.0.spec)`: SPECS §11 — web/ page contract; sweep-discovery rule; canonical caveat copy as constants.
2. `chore(p6.0.deps)`: requirements.txt — add `plotly`; drop `altair` if grep-clean.

### Phase 6.1 — Skeleton

3. `feat(p6.1.discover)`: `src/web/discover.py` — `find_latest_sweep() -> Path` + `read_sweep_with_skips(run_id) -> (results_df, skips_df)`.
4. `test(p6.1.discover)`: empty / multiple / mtime-tied / corrupt-file cases.
5. `feat(p6.1.caveats)`: `src/web/caveats.py` — three constants (multi-comparisons re-exported from `rank`; survivorship + margin written here) + `render_caveats_expander()` helper.
6. `feat(p6.1.app)`: `app.py` — sidebar (sweep picker, multi-strategy/symbol filters, min_n slider, regime radio) + 4 placeholder tabs + caveats expander at the top of every tab.
7. `chore(p6.1.verify)`: launch `streamlit run app.py` against current sweep parquets; screenshot; confirm sidebar state persists across tab switches.

### Phase 6.2 — Leaderboard tab

8. `feat(p6.2.table)`: `st.dataframe` of `rank_strategies(summarize_by_stock_strategy(df), min_n=sidebar_min_n)` with column config (rank, strategy, symbol, n_trades, win%, median_roi_ann, mean_roi_ann, std, total_net_pnl).
9. `feat(p6.2.thin)`: sidecar table below — rows with `n_trades < min_n` rendered under "Thin samples — not ranked".
10. `feat(p6.2.toggle)`: `st.radio` at top — "Within stock" (group by symbol, rank strategies per symbol) vs "Across stocks" (rank all pairs together).

### Phase 6.3 — Heatmap tab

11. `feat(p6.3.pivot)`: dual Plotly heatmaps (value + density) for the selected (strategy, symbol); thin cells masked per §2.2.
12. `feat(p6.3.hover)`: tooltip composition — `customdata=[n_trades, win_rate, std, total_net_pnl]`.

### Phase 6.4 — Trends tab

13. `feat(p6.4.yoy)`: Plotly line — `summarize_by_year(df).query("strategy==X and symbol==Y")` over years.
14. `feat(p6.4.moy)`: Plotly bar — `summarize_by_month(df).query("strategy==X and symbol==Y")` Jan-Dec.
15. `feat(p6.4.n_hover)`: every bin tooltips `n_trades` so sparse bins are visually distinguishable from dense ones.

### Phase 6.5 — Per-stock tab + polish

16. `feat(p6.5.dash)`: per-symbol dashboard — all strategies' summary stats side-by-side as small-multiples bar chart.
17. `chore(p6.5.sweep)`: live run of the §3.2 sweep; confirm cache fills cleanly.
18. `chore(p6.5.verify)`: screenshot every tab against the new sweep; record any visual-polish followups for Phase 7.
19. `chore(p6.5.tag)`: `git tag v0.6-ui`.

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
- **`verify_p5` section (b) prints unmasked heatmap + a count instead of the masked view.** Reviewer flagged 416719f. Tiny (~3 lines) opportunistic followup; lands as `chore(p5.followup): verify_p5 prints masked heatmap` whenever someone touches the script next. Not Phase-6-blocking — verify scripts are operator-facing, not UI-facing.
- **Empty-frame StringDtype** drifts to object via `_inferred_dtype` (1a5cf01). Cosmetic; deferred.

## 10. Change log

- 2026-05-24 — file created. All 17 decisions in §§1-7 frozen as of this date; departures recorded here per the discipline noted in the header.
- 2026-05-24 — added §0.1 (cross-reference to prior-review load-bearing items), §2.4 (Sharpe-like deliberately excluded from v1 sort menu), std-tooltip copy in §2.2, and `verify_p5` + StringDtype followups in §9. No behavior changes to §§1-7 decisions; this is making implicit constraints explicit.
