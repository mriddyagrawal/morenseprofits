# morenseprofits — Indian options-strategy backtest research platform

Build a personal multi-strategy options backtester + interactive research tool over
historical NSE F&O data. Discover which strategy configurations (entry timing, exit
timing, strike selection, market regime) historically paid across the Indian universe,
and ship the findings as a runnable web report.

## What it does

Backtest these strategies on historical NSE data, then aggregate and rank the results:

- **Short straddle / Long straddle** — sell or buy ATM CE + PE
- **Short strangle / Long strangle** — sell or buy OTM wings with a configurable
  `strike_offset_pct`
- **Iron condor** — 4-leg credit spread with `inner_offset_pct` + `outer_offset_pct`

For each `(strategy, symbol, expiry, entry_offset, exit_offset)` cell, the engine
prices the trade end-to-end against real NSE bhavcopy + options data and emits a
SPECS §2.5 result row: gross P&L, costs, net P&L, margin blocked, holding-period
ROI, annualized ROI.

The Phase-5 analytics layer then aggregates the per-trade table four ways:

| Aggregator | Group keys | Answers |
|---|---|---|
| `summarize_by_stock_strategy` | (strategy, symbol) | Headline leaderboard |
| `summarize_by_year` | (strategy, symbol, year) | "Is this strategy decaying?" |
| `summarize_by_month` | (strategy, symbol, month) | "Which months pay best?" |
| `pivot_window` / `pivot_counts` | (entry_offset × exit_offset) | Heatmap for one pair |

A ranker on top sorts by `median_roi_pct_annualized` (or any configurable metric)
and filters thin samples per the project's statistical-honesty discipline.

## What's done

| Phase | Description | Status |
|---|---|---|
| 0 — Skeleton | repo layout, SPECS, PLAN | ✅ done |
| 1 — Data | spot loader, options loader, F&O bhavcopy loader (legacy + UDiff cutover), trading calendar, expiry calendar | ✅ done |
| 2 — Universe | 40-blue-chip stock list, monthly-expiry list | ✅ done |
| 3 — Engine | per-trade pricing kernel, slippage 1% asymmetric, costs (Zerodha-style ₹20 brokerage + STT + stamp duty + exchange fees), Tier-B margin (SPAN portfolio offset + vol-derived per-symbol SPAN%), no-lookahead enforcement | ✅ done |
| 4 — Sweep | parameter sweep over `(strategy × symbol × expiry × entry × exit)`, deterministic run-id, results parquet + skip-log persistence, 5 strategy implementations + shared `_strikes` picker, spot-based margin notional for asymmetric structures | ✅ done |
| 5 — Analytics | per-pair / per-year / per-month aggregators, `(entry × exit)` heatmap pivot, ranker with min-N filter + multiple-comparisons caveat | ✅ done |
| 6 — Web UI | Streamlit dashboard rendering all the above | 🚧 next |
| 7 — Polish / docs | TBD | 📋 planned |
| 8 — MCP research API | agent-callable read-only tools over the dataset | 🔒 deferred |
| 9 — Paper trading | live positions + mark-to-market | 🔒 deferred |
| 10 — Live trading | broker integration, hard-gated on paper validation | 🔒 deferred |

**Current state**: Phase 5 ships with 365/365 tests passing. Live verify dataset
is RELIANCE Q1 2024 × 6 (entry, exit) windows = 18 trades. Real numbers visible
at the CLI via `python scripts/verify_p5.py` — example output (verify dataset):

```
rank=1  short_straddle × RELIANCE  N=18  win=83.3%  median=247.92%/yr
        std=242.97%  Sharpe-like=0.683  total_net_pnl=₹124,613
Seasonality: Jan 251.78 / Feb 269.25 (std 94.29 ← tightest) / Mar 106.46
Heatmap: 6 cells × N=3 each → ALL MASKED at MIN_N=5 (honest under-sampling)
Pipeline timing: ~30ms end-to-end
```

## How it's structured

```
src/
  config.py                  shared paths + flags
  data/                      NSE data loaders + cache layer
  universe/                  blue_chip_40 + monthly expiries
  strategies/                Strategy classes; _strikes shared picker
  engine/                    price_trade, sweep_one/sweep_grid, results, margin
  analytics/                 aggregate, heatmap, rank
  web/                       (Phase 6 — empty)
tests/                       pytest; ~365 tests as of Phase 5
scripts/                     verify_p1 ... verify_p5; capture_bhavcopy_fixtures
data/                        gitignored — parquet cache + sweep results
SPECS.md                     contracts: schemas, sign conventions, error taxonomy
PLAN.md                      phase plan + change log
DESIGN/
  DESIGN_SPEC.md             Phase-6 frozen UI decisions + change log
  image*.png                 mockups for all 4 tabs
comments.md                  reviewer feedback (parallel agent posts here)
PROJECT_DESCRIPTION.md       this file
```

## How it's built

- **Builder + Reviewer dual-agent workflow**: a parallel REVIEWER agent watches each
  commit and posts feedback to `comments.md`. The Builder agent (this one) reads
  feedback, addresses blocking flags immediately, judges next-commit suggestions.
- **Nuclear commits**: every phase is decomposed into the smallest atomic step that
  can be independently reviewed. Phase 4 alone spans ~20 commits.
- **No silent filtering**: where there's a tradeoff between transparency and
  convenience, transparency wins. Sample sizes surface alongside every aggregate
  metric; rankings expose what was suppressed; caveats are constants Phase-6 must
  render verbatim.
- **Honest data first**: every percentage shown to the user has slippage applied
  (1% per side), Tier-B SPAN margin computed (not naive), and trading-day-exact
  annualization (no 252/365 calendar approximation that biased short-window cells
  2×).

## Tech stack

- Python 3.11, pandas 3, pyarrow ≥15 — see [`requirements.txt`](requirements.txt) for exact pins.
- [`jugaad-data`](https://github.com/jugaad-py/jugaad-data) 0.33 for NSE EOD + bhavcopy
  (with a local in-repo override for legacy bhavcopy timeouts + post-2024-07-08 UDiff
  cutover)
- Streamlit ≥1.32 (+ Plotly added in Phase 6.0) for the upcoming web UI
- pytest for the test suite

## How to run

```bash
# One-time setup
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Live data verification scripts — exercise the full pipeline against NSE
python scripts/verify_p3.py   # one canonical short-straddle trade
python scripts/verify_p4.py   # multi-cell sweep on RELIANCE Q1 2024
python scripts/verify_p5.py   # the aggregate → rank composition

# Test suite
python -m pytest -q
```

`scripts/verify_p4.py` writes a `data/results/sweep_<run_id>.parquet`; `verify_p5.py`
reads the largest such parquet and exercises every aggregator + the ranker.

Phase 6 will add `app.py` at the repo root + `streamlit run app.py` as the
operator-facing entry point.

## Why "morenseprofits"

The "morense" stands for nothing in particular — it's the working title of the
research initiative. Once Phase 6 ships, the artifact is a Streamlit report
the operator runs to find historically-profitable strategy windows on NSE
stocks. The name will outlive its origin if the report proves useful.
