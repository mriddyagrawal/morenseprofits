# Migration plan — bhavcopy-only option data architecture

This is the full plan for retiring the per-contract NSE option API
(`src/data/options_loader.py`, "Source 3") as the engine's primary
data path, replacing it with daily F&O bhavcopy ingestion. Scope:
4-year backtest window starting 2024-04-15, per the operator's D2
decision. Regime A (pre-Apr-15-2024) is out of scope.

Companion to [DATA_PRODUCTS.md](DATA_PRODUCTS.md) — read that first
for the regime model + coverage matrix. This doc encodes WHAT we
build, in WHAT order, with WHAT exit gates between phases.

## Contents
- [Goals + non-goals](#goals--non-goals)
- [Inputs available](#inputs-available)
- [Architectural target](#architectural-target)
- [Phase 0 — Operator fixtures](#phase-0--operator-fixtures-pre-coding)
- [Phase 1 — Regime C migration](#phase-1--regime-c-migration-headline-win)
- [Phase 2 — Regime B extension](#phase-2--regime-b-extension)
- [Test plan](#test-plan)
- [Risk + rollback](#risk--rollback)
- [Decisions encoded](#decisions-encoded)

---

## Goals + non-goals

### Goals
1. Replace ~125k per-contract API requests with ~500 daily-bhavcopy
   requests across the 4-year window. Two orders of magnitude less
   NSE WAF pressure.
2. Eliminate the strike-drift `OfflineCacheMiss` problem — every
   traded strike is naturally present in the daily bhavcopy.
3. Unify the engine's data source: one cache layout, one normalized
   schema, one fetch path per regime.
4. Make the sweep run untouched. Cell-granular batching in
   [sweeper.py:304-312](src/engine/sweeper.py#L304-L312) stays as-is.

### Non-goals
- **No engine logic changes.** Pricing math, fill-source classification,
  CVaR semantics — all unchanged.
- **No sweep batching refactor.** Sweep workers continue reading
  per-contract parquets at cell granularity. We pre-materialize them
  from bhavcopy data.
- **No regime A coverage.** Pre-Apr-15-2024 backtests are out of
  scope. The 4-year window starting Apr 15 2024 is the floor.
- **No Akamai bot-challenge integration.** Historical
  `NSE_FO_contract` files are committed as repo fixtures, not
  fetched at runtime. Avoids the `_abck` / sensor_data hell entirely.
- **No `fo_mktlots.csv` parser.** Discontinued by NSE 2024-04-15 and
  unneeded since regime A is out of scope.

---

## Inputs available

### Live data paths (already working)
- jugaad's bhavcopy fetcher ([bhavcopy_fo_loader.py](src/data/bhavcopy_fo_loader.py)) for both UDiff (post-Jul-8-2024) and legacy (pre-Jul-8-2024) ZIPs
- jugaad's spot loader ([spot_loader.py](src/data/spot_loader.py)) — regime-stable
- Engine pricing machinery ([pnl.py](src/engine/pnl.py)) — already does VWAP recovery via `turnover × 10⁵ / volume − strike`

### Operator-provided fixtures (in `ONE OFF REPORTS/`)
Four NSE_FO_contract snapshots in `Reports-Archives-Multiple-DDMMYYYY.zip` format, each containing one `NSE_FO_contract_DDMMYYYY.csv.gz`:

| File | Snapshot date | Expiry coverage |
|---|---|---|
| `Reports-Archives-Multiple-16042024.zip` | 2024-04-16 | Apr/May/Jun 2024 expiries |
| `Reports-Archives-Multiple-16052024.zip` | 2024-05-16 | May/Jun/Jul 2024 expiries |
| `Reports-Archives-Multiple-12062024.zip` | 2024-06-12 | Jun/Jul/Aug 2024 expiries |
| `Reports-Archives-Multiple-05072024.zip` | 2024-07-05 | Jul/Aug/Sep 2024 expiries |

Each snapshot is ~80-90k rows covering ~204 distinct symbols.

**Coverage per regime-B expiry month** (per reviewer grill #4 on e0bc85a):

| Expiry month | Snapshots covering it | Cross-validation possible? |
|---|---|---|
| Apr 2024 (settles Apr 25) | 2024-04-16 only — **1 snapshot** | **No** — single-snapshot coverage; operator should manually spot-check Apr-expiry lot sizes against a known source (e.g. the operator's earlier PNB CSV inspection) |
| May 2024 (settles May 30) | 2024-04-16 + 2024-05-16 — 2 snapshots | Yes |
| Jun 2024 (settles Jun 27) | 2024-04-16 + 2024-05-16 + 2024-06-12 — 3 snapshots | Yes |
| Jul 2024 (settles Jul 25) | 2024-05-16 + 2024-06-12 + 2024-07-05 — 3 snapshots | Yes |

**Regime B is fully covered** (every expiry has ≥ 1 snapshot), but Apr 2024 expiry has no second-snapshot fallback for cross-validation. If the Apr-16 snapshot is buggy for that expiry, the bug surfaces silently. May/Jun/Jul expiries are cross-validatable across 2-3 snapshots each.

### Known schemas
- NSE_FO_contract column mapping decoded in [DATA_PRODUCTS.md](DATA_PRODUCTS.md#source-6--lot-size-sidecar-regimes-a--b--nse_fo_contract_ddmmyycsvgz)
  - `TckrSymb` → symbol
  - `StockNm` → human-readable contract name (parseable for expiry-month)
  - `NewBrdLotQty` → lot size (shares)
  - `StrkPric` → strike (× 100 from rupees, i.e. paise)
  - Use `StockNm` regex for expiry — `XpryDt` is in NSE proprietary epoch and not worth decoding
- UDiff + legacy bhavcopy column mappings already in
  [bhavcopy_fo_loader.py](src/data/bhavcopy_fo_loader.py); only the
  parsers' OUTPUT column selection needs extension (3 cols UDiff, 1 col legacy).

### Turnover column verification (load-bearing for P1.1/P1.2/P1.3)

The bhavcopy carries EXACTLY ONE turnover field per format. Verified
empirically against [BhavCopy_NSE_FO_0_0_0_20260602_F_0000.csv](BhavCopy_NSE_FO_0_0_0_20260602_F_0000.csv) header
and [tests/fixtures/bhavcopy_fo_legacy_20240125.csv](tests/fixtures/bhavcopy_fo_legacy_20240125.csv):

| Format | Turnover column | Units | Volume column (DON'T confuse) |
|---|---|---|---|
| UDiff (post-Jul-2024) | `TtlTrfVal` | lakhs of rupees, underlying notional | `TtlTradgVol` (contract units, NOT rupees) |
| Legacy (pre-Jul-2024) | `VAL_INLAKH` | lakhs of rupees, underlying notional | `CONTRACTS` (contract units) |

Both convention-confirmed by 8c2c517's empirical verification +
strike-correction recovery formula. No other "turnover-like" field
exists in either format (no separate "Premium Turnover" column —
that's a different NSE product, the website's historical CSV
download UI, NOT the bhavcopy). Cross-check before writing P1.1 /
P1.2 / P1.3 code: grep the parser file for `Trf|Trd|Val|InLakh`
on the actual raw header strings.

---

## Architectural target

```
                        ┌──────────────────────────────────────┐
                        │     ONE OFF REPORTS/ (fixtures)     │
                        │  NSE_FO_contract_DDMMYYYY.csv.gz    │
                        └──────────────┬───────────────────────┘
                                       │ (regime B only)
                                       ▼
              ┌─────────────────────────────────────────┐
              │  nse_fo_contract loader                 │
              │  → lot_size lookup by (sym, exp_month)  │
              └─────────────────────┬───────────────────┘
                                    │
        ┌───────────────────────────┴──────────────────────────────┐
        │                                                          │
        ▼                                                          ▼
  ┌───────────────────────────┐                      ┌────────────────────────────┐
  │  data/cache/bhavcopy_fo/  │                      │  data/cache/options/        │
  │  per-day parquets         │ ─── transform ────▶ │  per-(sym,exp,strike,type) │
  │  (already exists)         │  bhavcopy_to_       │  parquets                  │
  │                           │  contract_          │  (already exists)          │
  └───────────────────────────┘  timeseries()       └────────────┬───────────────┘
                                                                  │
                                                                  ▼
                                                       ┌──────────────────────┐
                                                       │  sweep_grid (unchanged) │
                                                       └──────────────────────┘
```

Same on-disk path layout as today (`options_loader` writes to it). Sweep workers don't care which path produced the parquet. The cutover is transparent to the engine.

---

## Phase 0 — Operator fixtures (pre-coding)

**Operator action** (no commit):
1. Unzip each ZIP into `data/manual/contracts/`, keeping the inner `.csv.gz`:
   ```
   data/manual/contracts/NSE_FO_contract_16042024.csv.gz
   data/manual/contracts/NSE_FO_contract_16052024.csv.gz
   data/manual/contracts/NSE_FO_contract_12062024.csv.gz
   data/manual/contracts/NSE_FO_contract_05072024.csv.gz
   ```
2. Verify each file decompresses to a valid CSV (one quick `zcat | head -1`).

**Then commit fixtures**:

### P0.1 — `chore(data.fixtures.nse_fo_contract_2024_h1)`
- Add `data/manual/contracts/*.csv.gz` (4 files, ~2MB each = ~8MB total)
- Add `data/manual/contracts/README.md` documenting provenance + manual-fetch nature
- Update `.gitignore` to NOT exclude `data/manual/` (the rest of `data/` is gitignored)
- Tests: none — pure data add

---

## Phase 1 — Regime C migration (headline win)

Replaces per-contract API calls with daily bhavcopy ingestion for the 2024-07-08 → today window (~23 months, the majority of the 4-year scope). Each sub-commit is nuclear; the phase has internal cutover safety so we can validate before stripping the safety net.

### P1.1 — `chore(data.bhavcopy_fo.parse_udiff_extension)`

Extend `parse_udiff` to carry 3 additional columns:
- `LastPric` → `ltp` (float64, rupees per share, NaN-tolerant)
- `NewBrdLotQty` → `lot_size` (int64, shares)
- `TtlTrfVal` → `turnover` (float64, lakhs of rupees, underlying-notional)

**Output column count**: 13 → 16 (matches options_loader's normalized schema for these fields).

**Tests** (`tests/test_bhavcopy_fo_loader.py`):
- `test_parse_udiff_carries_ltp_lot_size_turnover` — using existing `tests/fixtures/bhavcopy_fo_udiff_20240829.csv` fixture, assert the 3 new columns appear with non-NaN values for at least one OPTSTK row.
- `test_parse_udiff_ltp_is_nan_tolerant` — assert NaN passes through.
- `test_parse_udiff_lot_size_matches_known_value` — RELIANCE 2024-08-29 should have lot_size=250.

**Reviewer ask**: column dtype + the units claim (turnover in lakhs of rupees, underlying-notional convention).

### P1.2 — `chore(data.bhavcopy_fo.parse_legacy_extension)`

Extend `parse_legacy` to carry `VAL_INLAKH → turnover` (1 line).

Legacy bhavcopy does NOT carry `ltp` or `lot_size` — those stay NaN. The lot_size gap is closed in Phase 2 via the sidecar.

**Tests** (`tests/test_bhavcopy_fo_loader.py`):
- `test_parse_legacy_carries_turnover` — using existing `tests/fixtures/bhavcopy_fo_legacy_20240125.csv` fixture, assert `turnover` column appears with positive values for traded rows.
- `test_parse_legacy_ltp_is_absent` — assert `ltp` column either doesn't exist or is all-NaN (negative-space test, codifies the regime-A/B gap).

**Reviewer ask**: same as P1.1 plus confirmation that the ltp absence is correctly framed (not a parser bug — actually missing in legacy NSE format).

### P1.3 — `feat(data.contract_timeseries.bhavcopy_path)`

New function in `src/data/bhavcopy_to_contract.py`:

```python
def bhavcopy_to_contract_timeseries(
    symbol: str, expiry: date, strike: float, option_type: str,
    *, from_date: date, to_date: date,
) -> pd.DataFrame:
    """Reconstruct per-contract EOD time series from cached bhavcopies.

    Walks data/cache/bhavcopy_fo/*.parquet in [from_date, to_date],
    filters each to the requested (symbol, expiry, strike, option_type),
    concatenates, returns the same 16-col normalized schema that
    options_loader.load_option produces.

    For UDiff-era rows: volume = TtlTradgVol × NewBrdLotQty.
    For legacy-era rows: lot_size is NaN here; volume left as NaN.
    The legacy lot_size join lands in Phase 2.
    """
```

**Tests** (`tests/test_bhavcopy_to_contract.py`):
- Synthesize a 3-day bhavcopy cache fixture with known values for one contract; assert the function returns the expected per-day rows in correct schema.
- LOAD-BEARING: compare against `options_loader.load_option` output for the same (symbol, expiry, strike, option_type) over a 5-day period. Equivalence spec (tightened per reviewer grill #1 on e0bc85a):
  - **Same row count** between the two outputs (no missing or extra rows)
  - **Same column names** (all 16 normalized columns)
  - **Same dtypes per column** (float64 stays float64; Int64 stays Int64)
  - **Per-row VALUE equality** across all 16 columns after sorting both frames by `date`
  - Worked example to pin: RELIANCE 2024-08-29 2840-CE fixture row must produce byte-identical normalized output across the bhavcopy-derived and api-derived paths (modulo float64 last-bit jitter).
- Assert empty-date-range returns empty DataFrame.
- Assert missing-bhavcopy-day raises a clean error (not a silent skip).

**Reviewer ask**: equivalence to `load_option` output, volume-units conversion correctness.

### P1.4 — `feat(engine.cache.contract_path_writes)`

New function `materialize_contract_from_bhavcopy(symbol, expiry, strike, option_type, *, from_date, to_date, force=False)`:
- Calls `bhavcopy_to_contract_timeseries` and writes the result to the same disk path `options_loader` uses (`data/cache/options/{SYMBOL}/{EXPIRY:YYYYMMDD}/{STRIKE_INT}-{CE|PE}.parquet`).
- Idempotent — skips if the parquet exists, unless `force=True`.

**Tests** (`tests/test_bhavcopy_materialize.py`):
- After materialization, `options_loader.load_option` reading the same path returns the same data (with offline=True so it doesn't refetch).
- Idempotency: second call without `force` is a no-op.
- `force=True` rewrites.

**Reviewer ask**: write-path semantics; idempotency-guard correctness.

### P1.5 — `feat(prefetch.bhavcopy_first_mode)`

Update `scripts/prefetch_universe.py`:

1. Add `--engine-source` flag with choices `bhavcopy` (default) and `api`.
2. When `--engine-source bhavcopy` (default):
   - Step A: fetch all bhavcopies in `[from_date, to_date]` (1 per trading day) — via existing `load_bhavcopy_fo`.
   - Step B: enumerate every `(symbol, expiry, strike, option_type)` tuple actually present in the cached bhavcopies for the operator's symbol list.
   - Step C: call `materialize_contract_from_bhavcopy` for each tuple.
3. When `--engine-source api`: fall back to current per-contract loop (legacy mode for cutover safety).
4. Drop the strike_planner pre-enumeration step in bhavcopy mode — every traded strike is in the bhavcopy naturally.

**Note** on the cutover-safety toggle: it's intended for ONE round of validation against the legacy path; after Phase 1 ships and is verified on the 4-stock smoke universe, the `api` mode goes away in P1.8.

**Tests** (`tests/test_prefetch_universe.py` extension):
- Smoke test the `--engine-source bhavcopy` path against a synthesized 3-day bhavcopy cache fixture for 2 symbols.
- Assert per-contract parquets get written to the expected paths.

**Reviewer ask**: cutover-safety flag semantics; what conditions warrant flipping to `api`.

### P1.6 — `feat(p7.smoke_test.4sym_regime_c)`

Operator-action commit (likely a `scripts/smoke_post_migration.py` runner):
1. Wipe `data/cache/options/` for the 4-stock smoke universe (PNB, SBIN, BHEL, RELIANCE).
2. Run `prefetch_universe.py --symbols PNB SBIN BHEL RELIANCE --workers 4 --engine-source bhavcopy --from-date 2024-07-08 --to-date 2026-06-02`.
3. Run `p7_wide_sweep.py --symbols PNB SBIN BHEL RELIANCE --workers 4`.
4. Diff metrics against the current production sweep on the same universe (cell counts, skip rates, headline median ROI).

**Acceptance criterion** (per reviewer grill #2 on e0bc85a):

- **Primary**: per-cell, `|bhavcopy_median_roi_pct - api_median_roi_pct| < 0.01` (absolute delta on the cell's median per-trade ROI, in percentage points).
- **Backup**: per-trade, no individual ROI delta exceeds 0.5 percentage points absolute. Catches the scenario where one or two trades are wildly off but the median smooths them.

If EITHER fails on any cell, **halt and investigate before P1.7**.

**Reviewer ask**: smoke results table; correctness verdict.

### P1.7 — `feat(engine.pnl.missing_turnover_skip)`

Per operator's clarification (2026-06-02): in the bhavcopy-only
world, missing turnover ISN'T a hard failure — it's a per-cell
**skip** with a distinct, named reason. Skips already flow through
the sweeper's existing machinery to `sweep_<run_id>_skipped.parquet`
and the dashboard's drill-down + the MCP `skip_summary` tool, so
operators see exactly how many cells were dropped for missing
turnover vs other reasons.

**Changes**:

1. Add new exception `MissingTurnoverError(MissingDataError)` in
   [src/data/errors.py](src/data/errors.py) — mirrors the
   `IlliquidLegError(MissingDataError)` prior-art pattern at line 59.
   Subclass relationship means it's automatically caught by
   `_SKIPPABLE_ERRORS = (MissingDataError, NoLiquidStrikeError)` at
   [sweeper.py:56](src/engine/sweeper.py#L56) without sweeper
   changes. The exception class NAME becomes the `skip_reason`
   token in the skip parquet (per sweeper's reason-extraction at
   line 322-326).
2. In `_pick_fill_price` ([pnl.py:198-216](src/engine/pnl.py#L198-L216)),
   strip the `if vwap is None: fill_px = close` graceful-degrade
   branch. Replace with:
   ```python
   if vwap is None:
       raise MissingTurnoverError(
           f"{context}: turnover missing on {target}; cannot recover "
           f"premium VWAP. close={close:.2f}, strike={strike}, "
           f"volume={volume}."
       )
   ```
   Engine path: raise → sweeper catches via `_SKIPPABLE_ERRORS` →
   skip parquet row with `skip_reason="MissingTurnoverError"`,
   `skip_detail` carrying the context string.

3. NO change needed in:
   - `sweeper.py` — `MissingTurnoverError` is a `MissingDataError`,
     already in `_SKIPPABLE_ERRORS`.
   - `pnl.py:_compute_vwap` — still returns None on missing turnover.
   - MCP `skip_summary` — automatically picks up the new reason name.

**Test updates required**:
- Audit every `_pick_fill_price` test that relied on close-fallback
  semantics. Classify each:
  - **(a) Needs turnover added** — the test was supplying minimal
    fixture data and accidentally exercising the fallback. Fix:
    add a realistic turnover value.
  - **(b) Was testing the fallback intentionally** — replace the
    assertion with `pytest.raises(MissingTurnoverError)`.
- New test: `test_pick_fill_price_skips_when_turnover_missing` —
  hand-curated row with `turnover=None`; assert
  `MissingTurnoverError` raised; assert it's still a
  `MissingDataError` subtype (so `_SKIPPABLE_ERRORS` catches it).
- New test: `test_sweep_records_missing_turnover_as_skip_reason` —
  run a 1-cell sweep with a no-turnover fixture; assert the skip
  parquet has a row with `skip_reason="MissingTurnoverError"`.

**External-caller audit** (per reviewer grill #5 on e0bc85a):
`_pick_fill_price` is called via `price_trade` from
`src/engine/sweeper.py` AND from MCP tools that invoke `price_trade`.
After P1.7, these external callers see the new skip semantics:

- **MCP `backtest_one`**: calls `price_trade` directly for single-
  trade replay. After P1.7, calls against a pre-migration cache
  (one without turnover) raise `MissingTurnoverError`, which the
  MCP layer's error response surfaces to the consumer Claude.
  **Operator action**: re-prefetch any stale single-trade-replay
  caches before P1.7 lands. Otherwise, expect the tool to start
  failing on pre-migration data.
- **MCP `cell_summary` / `heatmap` / `sweep_windows`**: read sweep
  parquets (already-priced). Don't call `price_trade`. **Unaffected
  by P1.7.**
- **Dashboard drill-down** (`src/web/heatmap.py`): doesn't call
  `price_trade`. **Unaffected by P1.7.**
- **Future callers**: any new caller of `price_trade` needs to
  expect `MissingTurnoverError` as a possible exception. Document
  in `price_trade`'s docstring.

**Why this beats both prior framings**:
- Closer to operator's mental model: missing data is a data-quality
  signal, not a structural failure. Treat it as a skip; operator
  sees the count in skip_summary; operator decides whether to
  re-prefetch or accept the gap.
- Doesn't lump all missing-data cases into one generic reason — the
  named subtype is distinct from `IlliquidLegError`, plain
  `MissingDataError`, `OfflineCacheMiss`, etc. Same precedent
  `IlliquidLegError` set when it was introduced.
- Adds zero sweeper code. The skippable-subtype pattern is the
  cheapest possible integration with the existing machinery.

**Reviewer ask**: confirm the subtype-as-skip-reason pattern is the
right precedent to follow. Confirm `skip_reason` extraction in
sweeper correctly picks up the new class name. Audit completeness
of the test-suite classification — are there callers outside the
test suite (dashboard drill-down? MCP backtest_one?) that depended
on the close-fallback semantics?

### P1.8 — `chore(data.options_loader.deprecation_header)`

Per operator D1 decision: keep `options_loader.py` as dead code with a deprecation comment block at the top of the file. Remove the `--engine-source api` fallback from prefetch (added in P1.5). The loader stays functional for ad-hoc audit calls but is no longer wired into prefetch or the engine path.

**Tests**: existing options_loader tests stay green (the code still works); add `test_options_loader_marked_deprecated` reading the file header for the deprecation marker.

**Reviewer ask**: deprecation framing; is the file ready to delete in a future major version, or is there a long-tail need?

### P1.9 — `docs(plan.regime_c_migration_complete)`

PLAN.md history entry summarizing what landed. Update [DATA_PRODUCTS.md](DATA_PRODUCTS.md) to mark Source 3 as deprecated + reflect the new flow diagram. Commit the migration's measured wins (e.g. "fetch time reduced from 4hr to 6min on 4-stock smoke").

---

## Phase 2 — Regime B extension

Adds 3-month historical coverage (Apr 15 → Jul 7 2024) to the bhavcopy-only architecture. Sub-commits smaller than Phase 1.

### P2.1 — `feat(data.nse_fo_contract.loader)`

New `src/data/nse_fo_contract_loader.py`:
- `load_lot_sizes(snapshot_date: date) -> dict[tuple[str, date], int]` — reads the snapshot's `.csv.gz`, returns `{(symbol, expiry_date): lot_size}` mapping.
- `lot_size_for(symbol: str, expiry: date) -> int | None` — checks all 4 committed snapshots, returns the lot size found in the earliest snapshot that lists this `(symbol, expiry)`, or None if no snapshot covers it.
- Implementation: parse `StockNm` regex `{SYMBOL}(\d{2})([A-Z]{3})` to extract expiry year+month; cross-reference against the queried expiry date's month.

**Tests** (`tests/test_nse_fo_contract_loader.py`):
- Against the 4 committed fixtures: assert PNB May 2024 expiry has lot_size=8000 (hand-verified from the operator's earlier CSV inspection).
- Assert the function returns the same lot size across different snapshot dates that both cover the contract (stability check).
- Assert None for a contract not in any snapshot.

**Reviewer ask**: StockNm regex robustness; cross-snapshot consistency policy.

### P2.2 — `feat(data.contract_timeseries.legacy_path)`

Extend `bhavcopy_to_contract_timeseries` to handle pre-Jul-8-2024 rows:
- For each legacy-era row, call `nse_fo_contract_loader.lot_size_for(symbol, expiry)` to derive `lot_size`.
- Compute `volume = contracts × lot_size`.
- Leave `ltp` as NaN (legacy bhavcopy doesn't carry it).
- Mark `_legacy_ltp_unavailable: True` in the output's row metadata (or via a sidecar column) for downstream caveat-triggering.

**Tests**:
- Synthesize a legacy bhavcopy day in cache, run the transform, assert volume = contracts × known-lot-size for a known (symbol, expiry).
- Assert ltp is NaN for legacy rows.
- Assert UDiff-era rows (when from_date/to_date span the cutover) still get ltp directly.

**Reviewer ask**: cutover-handling semantics; what happens for contracts whose listing spans the Jul-8 boundary.

### P2.3 — `feat(prefetch.regime_b_extension)`

Update `prefetch_universe.py` to also process pre-Jul-8-2024 dates back to 2024-04-15:
- Same flow as P1.5 but the bhavcopy parser auto-routes by date via the existing format-discriminator in [bhavcopy_fo_loader.py:74-75](src/data/bhavcopy_fo_loader.py#L74-L75).
- The materialize step now needs the sidecar lookup for legacy-era contracts.

**Tests**:
- Synthesize a mixed-regime 30-day bhavcopy cache fixture (15 days legacy + 15 days UDiff). Run prefetch, assert all per-contract parquets get written with correct lot_size for both eras.

**Reviewer ask**: end-to-end correctness across the regime boundary.

### P2.4 — `feat(mcp.get_options_chain.legacy_caveat)`

Per operator D3 decision: when `get_options_chain` returns rows from a pre-2024-07-08 trade date, surface a caveat naming the `ltp: None` field explicitly.

**Tests**:
- `tests/test_mcp_spot_options.py` extension: assert the new caveat string appears in the response when ANY returned chain row has trade_date < 2024-07-08.

**Reviewer ask**: caveat wording + trigger condition.

### P2.5 — `feat(p7.smoke_test.regime_b_extension)`

Operator-action commit: rerun the smoke sweep on a backtest window that crosses the regime B/C boundary (e.g., 2024-05-01 → 2024-09-30 on the 4-stock universe). Validate that:
- Pre-Jul-8 trades have correct fill prices (using bhavcopy + sidecar)
- Post-Jul-8 trades match Phase 1's results
- No regression on cell counts or skip rates near the boundary

**Reviewer ask**: smoke results + cross-boundary correctness.

### P2.6 — `docs(plan.regime_b_migration_complete)`

PLAN.md history entry. Update DATA_PRODUCTS.md to mark the full 4-year window as supported.

---

## Test plan

### Synthetic fixtures used across phases
- `tests/fixtures/bhavcopy_fo_udiff_20240829.csv` — existing
- `tests/fixtures/bhavcopy_fo_legacy_20240125.csv` — existing
- `data/manual/contracts/*.csv.gz` (4 files) — committed in P0.1
- New: `tests/fixtures/synthetic_bhavcopy_cache_3day.py` — programmatic builder used by P1.3 transform tests
- New: `tests/fixtures/synthetic_mixed_regime_30day.py` — programmatic builder used by P2.3 prefetch tests

### LOAD-BEARING tests (anti-regression backbone)

| Phase | Test | What it pins |
|---|---|---|
| P1.1 | `test_parse_udiff_carries_ltp_lot_size_turnover` | Column-set contract for UDiff parser |
| P1.2 | `test_parse_legacy_carries_turnover` | Turnover availability in legacy regime |
| P1.3 | `test_bhavcopy_transform_matches_load_option_output` | Engine-equivalence check |
| P1.7 | `test_pick_fill_price_skips_when_turnover_missing` | New MissingTurnoverError(MissingDataError) subtype; auto-skippable per _SKIPPABLE_ERRORS; distinct skip_reason |
| P1.7 | `test_sweep_records_missing_turnover_as_skip_reason` | End-to-end: sweep emits skip parquet row with named reason |
| P2.1 | `test_lot_size_lookup_against_4_snapshots` | Sidecar correctness |
| P2.2 | `test_legacy_volume_derived_from_contracts_times_lotsize` | Volume derivation contract |
| P2.4 | `test_get_options_chain_surfaces_legacy_ltp_caveat` | MCP caveat trigger |

### Smoke tests (manual operator action, gating P1.7 + Phase 2 close)
- P1.6: 4-stock universe, 23-month regime C window. Acceptance: results match API-derived to float precision.
- P2.5: 4-stock universe, 5-month cross-boundary window. Acceptance: no regression at the boundary.

---

## Risk + rollback

### Per-commit reversibility
- All commits up to and including P1.6 are net-additive — `options_loader` still works, `--engine-source api` is the fallback.
- P1.7 (strip graceful-degrade) is the first irreversible commit. Run smoke test P1.6 first.
- Phase 2 is gated on Phase 1 being verified end-to-end. If Phase 1's smoke test fails, halt the entire migration and root-cause before continuing.

### Known risk areas

| Risk | Mitigation |
|---|---|
| Bhavcopy + per-contract numerical divergence (rounding, NaN handling, units bug) | P1.3 LOAD-BEARING equivalence test + P1.6 smoke test before P1.7 |
| Materialized parquet schema drift from `options_loader`'s output | P1.4 idempotency tests; column-equality check on a sample contract |
| Lot-size sidecar miss for a regime B contract | P2.1 returns None → P2.2 propagates NaN volume → engine raises MissingDataError → operator sees loud failure and can add a sidecar row OR widen the snapshot coverage |
| Sweep cells silently producing different results across the cutover | P2.5 cross-boundary smoke test; if it fails, the graceful-degrade strip in P1.7 might have been premature |

### Rollback paths
- **Mid-Phase-1, pre-P1.7**: flip prefetch to `--engine-source api`; all caches stay valid; no code revert needed.
- **Post-P1.7, pre-Phase-2**: revert P1.7 commit; re-prefetch with `api` mode; tests that asserted `MissingTurnoverError` (skip-with-reason) need updating back to graceful-degrade.
- **Phase 1 issue discovered AFTER Phase 2 has landed** (per reviewer grill #3 on e0bc85a): Phase 2's sidecar loader + transform extensions assume the bhavcopy-only architecture; Phase 2's tests depend on P1.7's skip-with-reason semantics. **Reverting P1.7 alone breaks Phase 2's test contracts.** Required path: full revert through Phase 2 (P2.6 → P2.1 in reverse order), then standard P1.7 revert, then re-prefetch with `api` mode. The "Phase 2 is gated on Phase 1 verification end-to-end" rule makes this scenario unlikely in practice, but the dependency ordering means a Phase-1 graceful-degrade restoration cascades through any Phase 2 work that landed on top.
- **Phase 2 issue (Phase 1 healthy)**: skip P2.x commits; engine still works on regime C only via Phase 1.

---

## Decisions encoded

This plan embeds the operator's D1-D4 decisions from
[DATA_PRODUCTS.md §Decision points](DATA_PRODUCTS.md#decision-points):

- **D1**: bhavcopy-only is the primary path; `options_loader` kept as deprecated dead code (P1.8). No production fallback after P1.7. Graceful-degrade in `pnl.py` removed.
- **D2**: 4-year window starting 2024-04-15. Regime A skipped. Phases 1 + 2 cover the full target window.
- **D3**: `ltp` is NaN for regime B rows; caveat surfaces in `get_options_chain` per P2.4.
- **D4**: `options_loader.py` kept as dead code with deprecation header (P1.8); graceful-degrade removed (P1.7). **Refinement (2026-06-02 operator clarification)**: missing turnover triggers a per-cell SKIP (via new `MissingTurnoverError(MissingDataError)` subtype, auto-caught by `_SKIPPABLE_ERRORS`) rather than a loud failure that crashes the sweep. Operator sees missing-turnover skips as a distinct reason in skip_summary / drill-down — closer to "this is a data-quality signal" than "this is a code bug." Pattern follows `IlliquidLegError(MissingDataError)` precedent.

Plus three implicit decisions:
- **All strikes**: no strike_planner pre-filtering. Every traded strike in the bhavcopy becomes a contract. **Disk cost note** (per reviewer grill #6 on e0bc85a): with `strike_planner` removed, per-cell strike count goes from ~13 (`DEFAULT_STRIKES_PER_SIDE = 6` + ATM = 13 per option_type) to all-traded (~30-100+ per option_type for active underlyings). Estimated **~3-5× cache growth** over current `data/cache/options/` footprint. **Verify storage capacity before Phase 1 prefetch run**.
- **0-volume disqualifies**: handled by existing `IlliquidLegError` gate in [pnl.py](src/engine/pnl.py). No new logic.
- **Sweep batching unchanged**: cell-granular tuples per [sweeper.py:304-312](src/engine/sweeper.py#L304-L312).
