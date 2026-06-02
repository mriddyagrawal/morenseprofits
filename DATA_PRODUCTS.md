# Data products — regime-aware coverage analysis

This document is an architectural reference, NOT just a column dump.
It catalogues every dataset we download, then traces which subset of
those sources covers the engine's required schema across NSE's three
distinct data-publishing regimes.

The driving question: **can we get rid of the per-contract option
loader by reading exclusively from the daily F&O bhavcopy?** The
answer is "yes for the current backtest window, mostly yes for an
expansion to ~3 months of additional history, and partially-with-a-
sidecar for a deep historical expansion." This doc spells out which
gap appears in which regime so the architectural call is clear.

## Contents
- [Engine's required schema](#engines-required-schema) — the canonical column set the engine must hydrate per row
- [The three regimes](#the-three-regimes) — what NSE publishes on which dates
- [Coverage matrix](#coverage-matrix) — per-column availability per source per regime
- [Sources in detail](#sources-in-detail) — column tables per download product
- [What's done / what's left](#whats-done--whats-left) — gap analysis vs current loaders
- [Decision points](#decision-points) — open architectural calls

---

## Engine's required schema

The engine consumes two kinds of normalized frames: per-option-contract
EOD rows (one per `(symbol, expiry, strike, option_type, date)`) and
per-symbol EOD spot rows (one per `(symbol, date)`). The two schemas
are stable across all regimes — the engine doesn't need to know which
source the rows came from.

**Per-contract option EOD schema** (post-loader column names per
[src/data/options_loader.py:302-319](src/data/options_loader.py#L302-L319)):

| Column | Dtype | Units | Notes |
|--------|-------|-------|-------|
| date | datetime64[us] | naive IST midnight | per trading day |
| symbol | string | — | uppercased ticker |
| expiry | datetime64[us] | naive IST midnight | actual settlement date (holiday-shifted) |
| option_type | string | — | "CE" or "PE" |
| strike | float64 | whole rupees | integer-enforced |
| open / high / low / close | float64 | rupees per share | premium |
| ltp | float64 | rupees per share | last traded |
| settle_price | float64 | rupees per share | clearing |
| lot_size | int64 | shares | contract multiplier |
| volume | int64 | shares | total traded shares (NOT contracts) |
| turnover | float64 | lakhs of rupees, underlying notional | `(strike + premium) × shares / 10⁵`; **NOT** premium turnover. Engine recovers per-share premium VWAP via `turnover × 10⁵ / volume − strike` ([options_loader.py:284-301](src/data/options_loader.py#L284-L301)). |
| oi | Int64 | contracts | nullable |
| oi_change | Int64 | contracts | nullable |

**Per-symbol spot EOD schema** (post-loader column names per
[src/data/spot_loader.py:47-58](src/data/spot_loader.py#L47-L58)):

| Column | Dtype | Units | Notes |
|--------|-------|-------|-------|
| date | datetime64[us] | naive IST midnight | per trading day |
| symbol | string | — | uppercased |
| series | string | — | always "EQ" |
| open / high / low / close / vwap / prev_close | float64 | rupees | |
| volume | int64 | shares | |

These are the targets. The rest of this doc asks which sources can
hydrate them, per regime.

---

## The three regimes

NSE's options-segment publishing changed twice in 2024. Two cutover
dates, three regimes:

| Regime | Date range | F&O bhavcopy format | Lot-size sidecar |
|---|---|---|---|
| **A** | up to **2024-04-14** | Legacy ZIP (`BHAVDATA-FULL` shape) | `fo_mktlots.csv` |
| **B** | **2024-04-15 → 2024-07-07** | Legacy ZIP (same as A) | `NSE_FO_contract_DDMMYY.csv.gz` (new, replaces `fo_mktlots.csv`) |
| **C** | **2024-07-08** onwards | UDiff CSV (BhavCopy_NSE_FO_*) | **none needed** — `NewBrdLotQty` is per-row in the bhavcopy itself |

Why two cutovers:
- **2024-04-15** — per NSE circular [NSE/FAOP/61157](FAOP61157.pdf)
  dated 2024-03-15: `fo_mktlots.csv` and `Qtyfreeze.csv` discontinued,
  consolidated into a new daily file `NSE_FO_contract_DDMMYY.csv.gz`.
- **2024-07-08** — NSE F&O bhavcopy format migrated from the legacy
  ZIP shape (`INSTRUMENT, SYMBOL, EXPIRY_DT, ...` etc.) to the UDiff
  CSV format (`TradDt, FinInstrmTp, TckrSymb, FininstrmActlXpryDt, ...`).
  Cutover wired into [bhavcopy_fo_loader.py:74-75](src/data/bhavcopy_fo_loader.py#L74-L75)
  via the `_LEGACY_MARKERS` / `_UDIFF_MARKERS` discriminators.

**Current backtest window** is 2024-05-01 onwards (per PLAN.md history)
— so the live system spans regimes B and C only. Regime A only
becomes relevant if/when the universe expands further back.

---

## Coverage matrix

For each engine-required column, which source supplies it in each
regime? "✓" = direct, "derive" = computable from sibling columns,
"sidecar" = needs the lot-size sidecar (regime A/B only).

### Per-contract option EOD columns

| Column | Regime A (legacy bhavcopy) | Regime B (legacy bhavcopy) | Regime C (UDiff bhavcopy) |
|---|---|---|---|
| date | ✓ `TIMESTAMP` | ✓ `TIMESTAMP` | ✓ `TradDt` |
| symbol | ✓ `SYMBOL` | ✓ `SYMBOL` | ✓ `TckrSymb` |
| expiry | ✓ `EXPIRY_DT` | ✓ `EXPIRY_DT` | ✓ `FininstrmActlXpryDt` |
| option_type | ✓ `OPTION_TYP` | ✓ `OPTION_TYP` | ✓ `OptnTp` |
| strike | ✓ `STRIKE_PR` | ✓ `STRIKE_PR` | ✓ `StrkPric` |
| open / high / low / close | ✓ `OPEN/HIGH/LOW/CLOSE` | ✓ `OPEN/HIGH/LOW/CLOSE` | ✓ `OpnPric/HghPric/LwPric/ClsPric` |
| ltp | **✗ MISSING** | **✗ MISSING** | ✓ `LastPric` |
| settle_price | ✓ `SETTLE_PR` | ✓ `SETTLE_PR` | ✓ `SttlmPric` |
| **lot_size** | **sidecar** (`fo_mktlots.csv`) | **sidecar** (`NSE_FO_contract.csv.gz`) | ✓ `NewBrdLotQty` |
| volume (shares) | **derive** (`CONTRACTS × lot_size`, needs sidecar) | **derive** (`CONTRACTS × lot_size`, needs sidecar) | **derive** (`TtlTradgVol × NewBrdLotQty`) |
| turnover | ✓ `VAL_INLAKH` | ✓ `VAL_INLAKH` | ✓ `TtlTrfVal` |
| oi | ✓ `OPEN_INT` | ✓ `OPEN_INT` | ✓ `OpnIntrst` |
| oi_change | ✓ `CHG_IN_OI` | ✓ `CHG_IN_OI` | ✓ `ChngInOpnIntrst` |

**Per-regime gap summary:**

- **Regime C (current era)**: every engine column is bhavcopy-sourceable.
  No sidecar needed. **The bhavcopy-only architecture works
  end-to-end here with zero per-contract API calls.**
- **Regime B**: same as A — needs the sidecar AND a parse layer for the
  new `NSE_FO_contract_DDMMYY.csv.gz` file. Plus `ltp` is missing
  (soft loss — engine rarely uses it).
- **Regime A**: needs the legacy `fo_mktlots.csv` sidecar. Plus `ltp`
  missing.

### Per-symbol spot EOD columns

The spot loader is regime-agnostic — `jugaad_data.nse.stock_df` hits
the equity history API which has been stable across all three regimes.
No regime gap for spot.

| Column | Source | Field |
|---|---|---|
| All 7 columns | jugaad `stock_df` | unchanged across regimes |

---

## Sources in detail

### Source 1 — NSE F&O bhavcopy (UDiff format, regime C)

- **URL**: `https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip`
- **Cache path**: `data/cache/bhavcopy_fo/{YYYYMMDD}.parquet`
- **Granularity**: one row per F&O instrument per trade date (~38k rows/day)
- **Parser**: [bhavcopy_fo_loader.py::parse_udiff](src/data/bhavcopy_fo_loader.py)

**Raw columns** (34 total, [confirmed via header of test fixture](tests/fixtures/bhavcopy_fo_udiff_20240829.csv)):

```
TradDt, BizDt, Sgmt, Src, FinInstrmTp, FinInstrmId, ISIN, TckrSymb,
SctySrs, XpryDt, FininstrmActlXpryDt, StrkPric, OptnTp, FinInstrmNm,
OpnPric, HghPric, LwPric, ClsPric, LastPric, PrvsClsgPric,
UndrlygPric, SttlmPric, OpnIntrst, ChngInOpnIntrst, TtlTradgVol,
TtlTrfVal, TtlNbOfTxsExctd, SsnId, NewBrdLotQty, Rmks, Rsvd1, Rsvd2,
Rsvd3, Rsvd4
```

**Currently extracted by `parse_udiff`** (13 columns, leaving 21 on
the table — see [parse_udiff at line 233-294](src/data/bhavcopy_fo_loader.py#L233-L294)):
`instrument, symbol, expiry, strike, option_type, open, high, low,
close, settle_price, contracts, oi, oi_change, trade_date`.

**Columns dropped by current parser that the engine wants:**
`LastPric (→ ltp), NewBrdLotQty (→ lot_size), TtlTrfVal (→ turnover)`.
All three would need to be added to the parser to make the bhavcopy
the canonical option-data source.

**Bonus columns dropped that could be useful**: `UndrlygPric` (would
let us cross-check `spot_loader`), `PrvsClsgPric`, `TtlNbOfTxsExctd`
(microstructure signal), `FinInstrmNm` (human-readable name).

### Source 2 — NSE F&O bhavcopy (legacy format, regimes A + B)

- **URL**: `jugaad_data.nse.archives.NSEArchives.bhavcopy_fo_raw` →
  `https://nsearchives.nseindia.com/content/historical/DERIVATIVES/{yyyy}/{MMM}/fo{dd}{MMM}{yyyy}bhav.csv.zip`
- **Cache path**: `data/cache/bhavcopy_fo/{YYYYMMDD}.parquet` (same cache as Source 1)
- **Granularity**: one row per F&O instrument per trade date
- **Parser**: [bhavcopy_fo_loader.py::parse_legacy](src/data/bhavcopy_fo_loader.py)

**Raw columns** (15 total, [confirmed via header of test fixture](tests/fixtures/bhavcopy_fo_legacy_20240125.csv)):

```
INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP, OPEN, HIGH, LOW,
CLOSE, SETTLE_PR, CONTRACTS, VAL_INLAKH, OPEN_INT, CHG_IN_OI, TIMESTAMP
```

**Currently extracted by `parse_legacy`** (13 columns — see
[parse_legacy at line 194-230](src/data/bhavcopy_fo_loader.py#L194-L230)):
same shape as parse_udiff above. **Drops `VAL_INLAKH`** (turnover)
even though it exists in the raw — adding it requires one extra line
in the parser.

**Missing from raw entirely** (NOT in legacy file under any column
name): `lot_size`, `ltp`. These force the sidecar requirement for
regimes A and B.

### Source 3 — NSE per-contract option EOD (direct API)

- **URL**: `https://www.nseindia.com/api/historicalOR/foCPV`
- **Cache path**: `data/cache/options/{SYMBOL}/{EXPIRY:YYYYMMDD}/{STRIKE_INT}-{CE|PE}.parquet`
- **Granularity**: one row per trading day for one specific contract
- **Loader**: [options_loader.py::load_option](src/data/options_loader.py)
- **Carries every engine-required column natively** (lot_size, volume,
  turnover all included). This is the current canonical path.
- **Cost**: one HTTP request per `(symbol, expiry, strike, option_type)`
  tuple. For 50 syms × ~25 expiries × ~50 strikes × 2 ≈ **~125k requests**
  for full backtest coverage. NSE WAF risk on bulk fetches.

### Source 4 — NSE spot EOD

- **URL**: jugaad `stock_df` → NSE equity history endpoint (series="EQ")
- **Cache path**: `data/cache/spot/{SYMBOL}/{YEAR}.parquet`
- **Granularity**: one row per symbol per trading day
- **Loader**: [spot_loader.py](src/data/spot_loader.py)
- **Regime-stable** — no migration on the equity side.

### Source 5 — Lot-size sidecar (regime A) — `fo_mktlots.csv`

- **Status: NOT YET WIRED.** Discontinued by NSE 2024-04-15 per
  [circular NSE/FAOP/61157](FAOP61157.pdf).
- **Historical URL (likely still archived)**: `https://archives.nseindia.com/content/fo/fo_mktlots.csv`
- **Expected schema** (from memory; verify before wiring): one row per
  underlying, columns for each upcoming expiry month (lot size per month).
- **Use only for regime A** (pre-2024-04-15 backtests).

### Source 6 — Lot-size sidecar (regimes A + B) — `NSE_FO_contract_DDMMYY.csv.gz`

- **Status: NOT YET WIRED.** Replacement for `fo_mktlots.csv` per
  [circular NSE/FAOP/61157](FAOP61157.pdf), effective 2024-04-15.
- **Public location**: https://www.nseindia.com/all-reports-derivatives
  (direct-download URL needs to be captured from the page's network
  tab — operator action).
- **Expected schema** (per circular): MII contract file consolidating
  quantity-freeze + market-lot + contract metadata. One row per
  listed `(symbol, expiry, strike, option_type)` per trading day.
- **Use for regimes A + B** (one fetch per month is sufficient — lot
  sizes are stable per `(symbol, expiry)`, only change between
  expiries, never within).

---

## What's done / what's left

### Done (live, in production)

- [x] **Source 1 parser** (UDiff bhavcopy → 13 cols)
- [x] **Source 2 parser** (legacy bhavcopy → 13 cols)
- [x] **Source 3 loader** (per-contract API → 16 cols, full engine schema)
- [x] **Source 4 loader** (spot via jugaad)
- [x] Daily-bhavcopy cache layer ([cache.py](src/data/cache.py))
- [x] Auto-format-detection between UDiff and legacy ([bhavcopy_fo_loader.py:74-75](src/data/bhavcopy_fo_loader.py#L74-L75))
- [x] Per-contract → cache layout with strike planner pre-enumeration ([strike_planner.py](src/data/strike_planner.py))

### Left (gaps blocking a bhavcopy-only architecture)

1. **Source 1 column extension** — extract `LastPric`, `NewBrdLotQty`,
   `TtlTrfVal` from UDiff bhavcopy parser. Tiny: ~3 lines in
   `parse_udiff`. **No new HTTP path needed.**

2. **Source 2 column extension** — extract `VAL_INLAKH` (turnover)
   from legacy bhavcopy parser. Tiny: ~1 line in `parse_legacy`. **No
   new HTTP path needed.**

3. **`bhavcopy_to_contract_timeseries` transform** — new function
   that walks the daily-bhavcopy cache, filters to `(symbol, expiry,
   strike, option_type)`, returns the same normalized 16-column frame
   that `options_loader.load_option` produces today. For regime C,
   this is self-contained. For regimes A + B, it needs the sidecar
   join (see #5/#6).

4. **Optional: per-contract cache materialization** — cache the
   transform output at the same path layout `options_loader` writes
   to, so downstream code is unchanged. Or skip and rebuild on demand.

5. **Source 5 loader** (`fo_mktlots.csv`) — only if we ever expand
   backtests pre-2024-04-15. Skip until needed.

6. **Source 6 loader** (`NSE_FO_contract_DDMMYY.csv.gz`) — for regime
   B coverage if we expand backtests to Apr-15 → Jul-7 2024. Schema
   needs to be captured from a sample download first.

### Overlap

- Sources 1 and 2 cover the same role (daily F&O bhavcopy), just in
  different schemas across the Jul-2024 cutover. The dispatcher
  in [bhavcopy_fo_loader.py:74-75](src/data/bhavcopy_fo_loader.py#L74-L75)
  already handles selection automatically.
- Sources 5 and 6 cover the same role (lot-size sidecar) across the
  Apr-2024 cutover. We'd need a similar dispatcher if we wire both.
- Source 3 (per-contract API) **overlaps with the bhavcopy path in
  every regime where the bhavcopy has the needed columns.** In
  regime C that's full overlap — Source 3 is replaceable with
  Source 1 + the transform. In regimes A + B, partial overlap that
  closes when the sidecar is wired.

---

## Decision points

These are the calls that affect what we build next.

### D1 — Migrate to bhavcopy-only architecture for regime C?

The largest win: replace ~125k per-contract HTTP requests with ~250
daily-bhavcopy fetches (500× reduction in NSE WAF pressure) and
eliminate the strike-drift OfflineCacheMiss problem (every traded
strike is naturally in the bhavcopy — no `strike_planner` pre-guess
needed).

Cost: build gaps #1 (UDiff column extension) and #3 (transform).
Total maybe 50-100 LOC + tests. No new HTTP path.

**Open**: do we kill Source 3 entirely, or keep it as a fallback for
specific edge cases (single-contract drilldown, missing bhavcopy
day)?

### D2 — How far back do we want backtest coverage to support?

- **2024-07-08 onwards (regime C only)**: no sidecar work needed.
  Just build #1 and #3 and the migration is complete for the current
  window.
- **2024-04-15 onwards (regimes B + C)**: also wire Source 6
  (`NSE_FO_contract_DDMMYY.csv.gz`) — operator captures the URL,
  builder writes the loader and the sidecar-join.
- **Pre-2024-04-15 (all three regimes)**: also wire Source 5
  (`fo_mktlots.csv`) IF NSE still archives it. Otherwise pre-Apr-15
  backtests can't get lot sizes from any free public source — would
  need a hand-curated lookup table.

### D3 — `ltp` gap in regimes A + B

`ltp` (last-traded price) is not in either legacy or UDiff bhavcopy
under any column name. Regime C has it (`LastPric`); regimes A + B
don't.

The engine's fill-price machinery uses `close` as the canonical
signal and falls back to settlement price when close is missing.
`ltp` isn't on the critical path. **Recommendation: drop `ltp` for
regime A + B coverage.** Mark the column NaN for those rows; flag in
caveats if any downstream consumer relies on it.

### D4 — Keep per-contract loader (Source 3) as a fallback?

Pros: edge-case rescue, test fixtures depend on minimal frames it
emits, defensive layer if NSE drops a bhavcopy day.
Cons: 500× HTTP cost, two parallel code paths to maintain.

**Recommendation**: keep but mark deprecated; mirror the
graceful-degrade pattern the legacy-parquet path uses
([pnl.py:194-203](src/engine/pnl.py#L194-L203)).

---

## TL;DR for the operator

- **Current backtest window (2024-05+) sits entirely in regime C.**
  Migrating to bhavcopy-only requires only ~3 extra parser lines + one
  transform function. No sidecar, no new HTTP path.
- **A 10-year backtest expansion crosses both cutovers** and would
  require wiring two sidecar loaders (Sources 5 + 6) plus an `ltp` gap
  acknowledgement.
- **Sources 5 and 6 are not yet wired**; URLs need operator verification
  before code can land.
