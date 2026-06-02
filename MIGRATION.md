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
- [Cross-source lot-size policy](#cross-source-lot-size-policy)
- [Phase 0 — Operator fixtures + unified lookup build](#phase-0--operator-fixtures--unified-lookup-build)
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

### Operator-provided fixtures (committed to `data/manual/`)
Four NSE_FO_contract snapshots are committed to the repo as
`data/manual/contracts/NSE_FO_contract_DDMMYYYY.csv.gz` (~1.7MB each gzipped,
~6.7MB total committed). The originals arrived inside
`Reports-Archives-Multiple-DDMMYYYY.zip` wrappers from the NSE
archives bundled-download UI; the outer ZIPs are not committed.

| Committed file | Snapshot date | Expiry coverage |
|---|---|---|
| `data/manual/contracts/NSE_FO_contract_16042024.csv.gz` | 2024-04-16 | Apr/May/Jun 2024 expiries |
| `data/manual/contracts/NSE_FO_contract_16052024.csv.gz` | 2024-05-16 | May/Jun/Jul 2024 expiries |
| `data/manual/contracts/NSE_FO_contract_12062024.csv.gz` | 2024-06-12 | Jun/Jul/Aug 2024 expiries |
| `data/manual/contracts/NSE_FO_contract_05072024.csv.gz` | 2024-07-05 | Jul/Aug/Sep 2024 expiries |

Each snapshot is ~80-90k rows × 150 columns covering ~204 distinct symbols (cross-snapshot row-count + PNB lot-size-stability verified pre-commit).

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
  ┌────────────────────────────────┐         ┌──────────────────────────────┐
  │  data/manual/                  │         │  data/cache/bhavcopy_fo/     │
  │  NSE_FO_contract_*.csv.gz      │         │  per-day parquets            │
  │  (committed, 4 files,          │         │  (gitignored, jugaad-fetched)│
  │   regime B sidecar)            │         │  (carries NewBrdLotQty       │
  │                                │         │   per row for regime C)      │
  └─────────────────┬──────────────┘         └────────────────┬─────────────┘
                    │                                         │
                    └────────────┬────────────────────────────┘
                                 ▼
                    ┌──────────────────────────────┐
                    │  scripts/build_lot_size_     │
                    │  parquet.py                  │
                    │  (committed; merges both     │
                    │   sources; loud-fail on      │
                    │   cross-source mismatch)     │
                    └─────────────┬────────────────┘
                                  ▼
                    ┌──────────────────────────────┐
                    │  data/cache/lot_sizes.parquet│
                    │  (gitignored; derived)       │
                    │  THE unified lookup —        │
                    │  one row per (sym, expiry)   │
                    └─────────────┬────────────────┘
                                  │ lot_size_lookup(symbol, expiry)
                                  ▼
       ┌──────────────────────────────────────────────────────────┐
       │  data/cache/bhavcopy_fo/   ────  transform  ────▶        │
       │  per-day parquets                                        │
       │                          bhavcopy_to_contract_           │
       │                          timeseries() — joins on         │
       │                          unified lot_size cache for      │
       │                          volume-in-shares derivation     │
       └──────────────────────────────┬───────────────────────────┘
                                      ▼
                    ┌──────────────────────────────┐
                    │  data/cache/options/         │
                    │  per-(sym,exp,strike,type)   │
                    │  parquets (gitignored;       │
                    │  materialized one-time)      │
                    └──────────────┬───────────────┘
                                   ▼
                       ┌──────────────────────────┐
                       │  sweep_grid (unchanged)  │
                       └──────────────────────────┘
```

Same on-disk path layout as today (`options_loader` writes to it). Sweep workers don't care which path produced the parquet. The cutover is transparent to the engine.

**Re-run discipline**: `rm -rf data/cache/` wipes bhavcopies + lot_sizes + per-contract materializations + sweep results. `data/manual/` survives (committed). Next prefetch run rebuilds everything from scratch, INCLUDING the unified lot_sizes parquet (auto-trigger on missing parquet).

---

## Cross-source lot-size policy

The unified `data/cache/lot_sizes.parquet` is populated from TWO sources:

1. **Sidecar** (`data/manual/contracts/NSE_FO_contract_*.csv.gz`) — regime B coverage; static, committed.
2. **Bhavcopies** (`data/cache/bhavcopy_fo/*.parquet` + sibling `data/cache/bhavcopy_fo_lot_sizes/*.parquet`) — regime C coverage; sibling parquets written per fetch by `bhavcopy_fo_loader.py` (extracts `NewBrdLotQty` per OPTSTK/OPTIDX row).

A given `(symbol, expiry-month)` pair can appear in BOTH sources whenever a contract listed in regime B is still tracked by a regime C bhavcopy day. NSE lot sizes are stable per `(symbol, expiry)` **for the trading life of one contract**, but NSE does biannual lot-size reviews that revise the values for upcoming contracts. Cross-source disagreement signals one of: a corporate action mid-life (split/bonus), an NSE biannual review that took effect between snapshots, or a parser bug.

**Policy: symmetric per-pair exclusion** (operator direction 2026-06-03). Three mismatch layers, all treated the SAME way:

1. **Sidecar-vs-sidecar** — `(sym, year, month)` appears in multiple NSE_FO_contract snapshots with different `lot_size` values.
2. **Bhavcopy-internal** — `(sym, year, month)` appears on multiple trade dates with different `lot_size` values.
3. **Sidecar-vs-bhavcopy** — `(sym, year, month)` is in both sources with different `lot_size` values.

For each detected mismatch:
- The build script DROPS that `(symbol, expiry-month)` from the unified cache. No silent earliest-wins, no latest-wins, no operator override.
- A diagnostic line in the operator's exact template prints inline:

      mismatch found in lot sizes between {x} and {y} for {sym} for {expiry}: {lot_x} and {lot_y}

  Where `{x}` / `{y}` are snapshot filenames, `bhavcopy-YYYY-MM-DD` trade-date stamps, or the literal `sidecar` / `bhavcopy` for the cross-source layer.
- The build returns successfully even when N pairs are excluded — the prefetch wrapper does NOT halt on mismatches (only on true errors: missing source dir, parse failure, etc.).
- Excluded pairs propagate downstream: the transform's `lot_size_lookup(sym, expiry)` returns None → it can't derive `volume = contracts × lot_size` → `MissingTurnoverError` raised → sweep skips the affected cells with `skip_reason="MissingTurnoverError"` (auto-surfaced via the existing `_SKIPPABLE_ERRORS` machinery).

**Rationale for per-pair exclusion** (vs the original loud-fail framing): if NSE revised a contract's lot_size mid-life, that contract's P&L is structurally ambiguous — entry at one lot, exit at another. Picking a "winner" value would produce a wrong P&L. Skipping is more honest. Cells touching healthy contracts still backtest correctly; the operator sees the exclusion count in the build-script output AND in the skip_summary distribution.

**Console-surfacing of verification** (preserved from earlier policy iteration):
- On EVERY run of the build script (with or without exclusions), print a `=== Lot-size verification ===` header followed by:
  - Total verified pair count + source breakdown (`sidecar_only=N | bhavcopy_only=N | both=N`).
  - If any exclusions: `=== Excluded N (symbol, expiry-month) pair(s) ===` with per-layer subsections (sidecar-vs-sidecar / bhavcopy-internal / sidecar-vs-bhavcopy) and one diagnostic line per excluded pair.
  - Footer pointer to MIGRATION.md §Cross-source lot-size policy.
- A silent successful build prints the header + summary anyway — confirms the verification step ran AND tells the operator the scale of what was checked. No ambiguity between "build succeeded with no mismatches" and "build didn't run."

**Reserved exception class**: `CrossSourceLotSizeMismatchError` stays in `src/data/errors.py` for a potential future strict-mode flag (`--strict-lot-size-verification` or similar) that would re-enable loud-fail behavior for debugging unexpected mismatch patterns. Not raised under the default per-pair-exclude policy.

**Limitation: no date dimension in unified cache**. The cache schema is `(symbol, year, month, lot_size, source)`. The per-pair-exclude policy handles mid-cycle NSE corporate actions cleanly (the contract gets dropped from the cache → cells skip). A future enhancement could add a `(symbol, expiry, effective_from)` schema with date-windowed lookups; not part of this migration.

**Reviewer ask**: confirm this is the right policy + the error-surfacing pattern (script-level loud raise + prefetch-level wrap-and-print) matches the project's error-handling discipline.

---

## Phase 0 — Operator fixtures + unified lookup build

### P0.1 — `chore(data.fixtures.nse_fo_contract_2024_h1)`

Already-staged-on-disk: `data/manual/contracts/NSE_FO_contract_*.csv.gz` (4 files, ~6.7MB total gzipped, produced from operator-downloaded NSE archive bundles).

- Add `data/manual/contracts/NSE_FO_contract_*.csv.gz` (4 files)
- Add `data/manual/contracts/README.md` documenting:
  - Provenance (NSE archives "Reports-Archives-Multiple-DDMMYYYY.zip" bundled-download UI)
  - Cadence (snapshot dates listed in §Inputs available)
  - That these are committed sources (not auto-fetched); operator manually re-derives by re-downloading from NSE if coverage needs to expand
  - Note that `data/manual/` is the ONLY subfolder of `data/` not gitignored
- Tests: none — pure data add

### P0.2 — `feat(scripts.build_lot_size_parquet)`

Two pieces of code lands together:

**(a) Sibling-cache extractor + write hook in `bhavcopy_fo_loader.py`**:

The bhavcopy-cache parquet schema is intentionally narrow (see P1.1 — no `lot_size` per row). To make `NewBrdLotQty` available to the build script without re-fetching raw bhavcopies, the loader writes a per-date sibling parquet at `data/cache/bhavcopy_fo_lot_sizes/{YYYYMMDD}.parquet` alongside the main cache write.

Sibling-cache schema:
- `symbol` (string)
- `expiry` (datetime64[us], from `FininstrmActlXpryDt`)
- `lot_size` (int64, from `NewBrdLotQty`)
- `trade_date` (datetime64[us], stamped from the fetch date)

Extractor function `_extract_lot_sizes_udiff(raw, trade_date)` lives in `bhavcopy_fo_loader.py`. Returns deduped (one row per unique `(symbol, expiry)`) frame restricted to OPTSTK + OPTIDX rows. Legacy bhavcopy dates write an EMPTY parquet (legacy raw doesn't carry lot_size — sidecar covers those expiries).

**(b) The build script `scripts/build_lot_size_parquet.py`**:

```python
def build_lot_size_parquet(
    *,
    out_path: Path | None = None,             # default: data/cache/lot_sizes.parquet
    sidecar_dir: Path | None = None,          # default: data/manual/contracts/
    bhavcopy_lot_sizes_dir: Path | None = None,  # default: data/cache/bhavcopy_fo_lot_sizes/
    verbose: bool = True,
) -> Path:
    """Build the unified (symbol, year, month) → lot_size cache.

    Loads sidecars + sibling bhavcopy parquets, detects mismatches
    at all 3 layers (sidecar-vs-sidecar, bhavcopy-internal,
    sidecar-vs-bhavcopy), EXCLUDES the offending (sym, year, month)
    pairs per the per-pair-exclude policy, and writes the unified
    parquet.

    Returns the written path. ALWAYS succeeds when sources are well-
    formed — mismatches are absorbed into the exclusion list, not
    raised. True errors (missing source dir, parse failure) propagate.

    Output schema:
        symbol     string
        year       int64
        month      int64
        lot_size   int64
        source     string  (one of {"sidecar", "bhavcopy", "both"})
    """
```

Year+month granularity (not exact expiry date) is sufficient because lot_sizes are stable per (symbol, expiry-month). The sidecar's `StockNm` regex (`{SYMBOL}(\d{2})([A-Z]{3})\d+...`) gives us year+month directly without needing to decode NSE's proprietary `XpryDt` epoch.

**Wire into `scripts/prefetch_universe.py`**:
- Step 0a: ensure bhavcopy cache exists (fetch any missing days; sibling parquets get written by the loader as part of each fresh fetch).
- Step 0b: if `data/cache/lot_sizes.parquet` is missing OR `--rebuild-lot-sizes` is passed, invoke `build_lot_size_parquet()`.
- Step 1+: proceed with materialize-contracts loop using the unified cache.

**Console-surfacing** (per the §Cross-source lot-size policy):

- On EVERY run of the build script (with or without exclusions), print `=== Lot-size verification ===` header + summary.
- If any `(symbol, expiry-month)` pairs were excluded due to mismatches: print `=== Excluded N (symbol, expiry-month) pair(s) ===` section grouped by layer (sidecar-vs-sidecar / bhavcopy-internal / sidecar-vs-bhavcopy), one operator-templated diagnostic line per excluded pair.
- A silent successful build prints the header + summary anyway — confirms verification step ran.

**Prefetch halt semantics**: under the per-pair-exclude policy, the build script ALWAYS succeeds on well-formed sources (mismatches are absorbed, not raised). The prefetch wrapper does NOT halt on mismatches. It DOES halt on true failures (missing source dir, parser exception, I/O error) — those propagate as Python exceptions and the prefetch script exits with the exception. Operator sees the traceback and fixes the underlying issue.

**Tests** (`tests/test_build_lot_size_parquet.py`):
- Sidecar-only `(sym, year, month)` (no bhavcopy entry). Assert row written with `source="sidecar"`.
- Bhavcopy-only `(sym, year, month)` (post-Jul-2024 contract). Assert row written with `source="bhavcopy"`.
- Sidecar + bhavcopy in agreement. Assert row written with `source="both"`.
- **Sidecar-vs-sidecar mismatch** — synthesize 2 sidecar files with conflicting `lot_size` for the same `(sym, year, month)`. Assert: (a) the pair is NOT in the output parquet, (b) the diagnostic message printed matches the operator's exact format, (c) the build still returns successfully.
- **Bhavcopy-internal mismatch** — synthesize 2 sibling bhavcopy parquets (different trade dates) with conflicting `lot_size` for the same `(sym, year, month)`. Same 3 assertions.
- **Sidecar-vs-bhavcopy mismatch** — synthesize 1 sidecar + 1 bhavcopy with conflicting `lot_size`. Same 3 assertions.
- Empty source dirs → empty parquet written; build succeeds.
- `prefetch_universe.py` integration test: parquet missing → auto-built. Parquet present → not rebuilt (unless `--rebuild-lot-sizes`).

**Reviewer ask**: confirm the per-pair-exclude policy implementation matches the §Cross-source lot-size policy specification. Confirm the diagnostic-message template (`mismatch found in lot sizes between {x} and {y} for {sym} for {expiry}: {lot_x} and {lot_y}`) handles the ≥3-source case sensibly (current behavior: enumerate all sources rather than picking two arbitrarily). Confirm the build script returns 0 even on excluded pairs (no false-positive prefetch halt).

---

## Phase 1 — Regime C migration (headline win)

Replaces per-contract API calls with daily bhavcopy ingestion for the 2024-07-08 → today window (~23 months, the majority of the 4-year scope). Each sub-commit is nuclear; the phase has internal cutover safety so we can validate before stripping the safety net.

### P1.1 — `chore(data.bhavcopy_fo.parse_udiff_extension)`

Extend `parse_udiff` to carry 2 additional columns:
- `LastPric` → `ltp` (float64, rupees per share, NaN-tolerant)
- `TtlTrfVal` → `turnover` (float64, lakhs of rupees, underlying-notional)

**Output column count**: 13 → 15.

**Note** on `NewBrdLotQty`: the UDiff bhavcopy DOES carry lot_size per row, but the parser does NOT extract it into the bhavcopy-cache parquet schema. Instead, `NewBrdLotQty` is consumed by the unified lot-size build script (P0.2) and persisted ONCE in `data/cache/lot_sizes.parquet`. The transform in P1.3 looks it up there. Rationale: lot_size is per-`(symbol, expiry)`-stable, so storing it per-bhavcopy-row in the bhavcopy cache duplicates the same value across ~60-90 days of EOD rows per contract. The unified lookup deduplicates.

**Anti-confusion docstring** (per reviewer grill #3 on 9b6c32b): the parser change MUST update `src/data/bhavcopy_fo_loader.py`'s module docstring to explicitly call out the decision:

> Output schema is intentionally narrow — `lot_size` is NOT carried per row. Consumers needing lot_size should call `src.data.lot_size_lookup(symbol, expiry)` against the unified `data/cache/lot_sizes.parquet` instead. Rationale: lot_size is per-(symbol, expiry) stable; per-row storage duplicates ~60-90 days of repeated values. See MIGRATION.md §Cross-source lot-size policy.

This prevents a future maintainer from "fixing" the missing column by re-adding lot_size to the parser. The docstring is the natural surface — a maintainer reading the parser for context sees the explicit decision before touching it.

**Tests** (`tests/test_bhavcopy_fo_loader.py`):
- `test_parse_udiff_carries_ltp_and_turnover` — using existing `tests/fixtures/bhavcopy_fo_udiff_20240829.csv` fixture, assert the 2 new columns appear with non-NaN values for at least one OPTSTK row.
- `test_parse_udiff_ltp_is_nan_tolerant` — assert NaN passes through.
- `test_parse_udiff_does_not_carry_lot_size` — negative-space test pinning that the bhavcopy parser output does NOT include `lot_size` (which lives in the unified cache instead).

**Reviewer ask**: column dtype + the units claim (turnover in lakhs of rupees, underlying-notional convention). Confirm the architectural decision to NOT carry lot_size in the bhavcopy-cache schema (it's lookup-resolved in the transform).

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

    lot_size is resolved ONCE per (symbol, expiry) via the unified
    cache (lot_size_lookup → data/cache/lot_sizes.parquet, built by
    P0.2's build_lot_size_parquet.py). This is regime-agnostic: the
    SAME lookup serves both UDiff-era and legacy-era rows.
    volume = contracts × lot_size (where contracts is the bhavcopy's
    TtlTradgVol/CONTRACTS column).

    For UDiff-era rows: ltp populated from LastPric.
    For legacy-era rows: ltp left as NaN (legacy bhavcopy doesn't
    carry it; flagged downstream via P2.2's caveat path).
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
   branch and replace it with case-disambiguated logic.
   `_compute_vwap` at [pnl.py:92-128](src/engine/pnl.py#L92-L128) can
   return None for THREE structurally distinct reasons:

   - **(1)** turnover/volume missing or zero
   - **(2)** NaN turnover
   - **(3)** deep-OTM ill-conditioning — turnover IS present + non-
     NaN; recovered premium goes negative due to lakh-rounding
     amplification at premium ≪ strike

   Operator's "skip when turnover missing" instruction names cases
   (1) + (2). Case (3) is the 8c2c517 design intent ("Deep-OTM
   numerical ill-conditioning — recovered premium went nonsensical
   because turnover rounding is comparable to the actual residual.
   Fall through to close.") and must be preserved as a working
   pricing path, not a skip.

   Distinguish at the call site by checking data presence:

   ```python
   if vwap is None:
       data_present = (
           turnover is not None and not pd.isna(turnover)
           and volume is not None and volume > 0
           and strike is not None
       )
       if data_present:
           # Case (3) — deep-OTM ill-conditioning. Fall through to
           # close per 8c2c517 design; not a missing-data signal.
           fill_px = close
       else:
           # Cases (1) + (2) — turnover/volume genuinely missing.
           raise MissingTurnoverError(
               f"{context}: turnover missing on {target}; cannot "
               f"recover premium VWAP. close={close:.2f}, "
               f"strike={strike}, volume={volume}, turnover={turnover}."
           )
   ```
   Engine path for cases (1) + (2): raise → sweeper catches via
   `_SKIPPABLE_ERRORS` → skip parquet row with
   `skip_reason="MissingTurnoverError"`, `skip_detail` carrying the
   context string. Engine path for case (3): unchanged from 8c2c517.

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
- New test: `test_pick_fill_price_skips_when_turnover_is_nan` —
  case (2): row with `turnover=float('nan')`; assert
  `MissingTurnoverError` raised.
- New test: `test_pick_fill_price_falls_back_to_close_on_deep_otm` —
  case (3): row with VALID turnover but premium ≪ strike such that
  recovered `premium_vwap ≤ 0`; assert NO exception; assert
  `fill_px == close`. Pins the 8c2c517 design preservation.
- New test: `test_sweep_records_missing_turnover_as_skip_reason` —
  run a 1-cell sweep with a no-turnover fixture; assert the skip
  parquet has a row with `skip_reason="MissingTurnoverError"`.
- New test: `test_sweep_does_not_skip_on_deep_otm` — run a 1-cell
  sweep with a deep-OTM ill-conditioned fixture; assert the cell
  IS priced (using close) and does NOT appear in the skip parquet.

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

Adds 3-month historical coverage (Apr 15 → Jul 7 2024) to the bhavcopy-only architecture. **Significantly simpler than originally planned** because the unified `lot_sizes.parquet` (built by P0.2) already covers regime B from the committed sidecar files — no separate sidecar loader is needed. Phase 2 is now just `parse_legacy` + `prefetch` window extension + the MCP caveat.

> **Note on the original P2.1**: the standalone `nse_fo_contract_loader.py` originally proposed in Phase 2 is **subsumed by P0.2**. The build script in P0.2 reads the same .csv.gz files; the unified lookup in `data/cache/lot_sizes.parquet` covers regime B and regime C uniformly. Phase 2's numbering below is renumbered post-collapse (P2.1 + P2.2 + P2.3 instead of the original P2.1 → P2.6).

### P2.1 — `feat(prefetch.regime_b_window)`

Update `scripts/prefetch_universe.py` to also process pre-Jul-8-2024 dates back to 2024-04-15:
- The bhavcopy fetch loop already handles regime B (jugaad's legacy ZIP path). Just extend the date-range argument.
- The unified lot_size lookup is regime-agnostic — already covers regime B from P0.2's sidecar ingestion. No additional lookup wiring.
- The materialize step in P1.4 already JOINs against the unified lookup; works for legacy-era contracts without change.

**Tests**:
- Synthesize a mixed-regime 30-day bhavcopy cache fixture (15 days legacy + 15 days UDiff). Run prefetch, assert all per-contract parquets get written with correct lot_size for both eras.

**Reviewer ask**: end-to-end correctness across the regime boundary; confirm no separate regime-B materialize logic needs to land.

### P2.2 — `feat(mcp.get_options_chain.legacy_caveat)`

Per operator D3 decision: when `get_options_chain` returns rows from a pre-2024-07-08 trade date, surface a caveat naming the `ltp: None` field explicitly.

**Tests**:
- `tests/test_mcp_spot_options.py` extension: assert the new caveat string appears in the response when ANY returned chain row has trade_date < 2024-07-08.

**Reviewer ask**: caveat wording + trigger condition.

### P2.3 — `feat(p7.smoke_test.regime_b_extension)`

Operator-action commit: rerun the smoke sweep on a backtest window that crosses the regime B/C boundary (e.g., 2024-05-01 → 2024-09-30 on the 4-stock universe). Validate that:
- Pre-Jul-8 trades have correct fill prices (using bhavcopy + sidecar)
- Post-Jul-8 trades match Phase 1's results
- No regression on cell counts or skip rates near the boundary

**Reviewer ask**: smoke results + cross-boundary correctness.

### P2.4 — `docs(plan.regime_b_migration_complete)`

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
| P1.7 | `test_pick_fill_price_skips_when_turnover_missing` | New MissingTurnoverError(MissingDataError) subtype; auto-skippable per _SKIPPABLE_ERRORS; distinct skip_reason — cases (1) + (2) only |
| P1.7 | `test_pick_fill_price_falls_back_to_close_on_deep_otm` | Pins 8c2c517 design intent — case (3) deep-OTM ill-conditioning is NOT a skip; falls through to close |
| P1.7 | `test_sweep_records_missing_turnover_as_skip_reason` | End-to-end: sweep emits skip parquet row with named reason |
| P1.7 | `test_sweep_does_not_skip_on_deep_otm` | End-to-end: deep-OTM cell IS priced, NOT in skip parquet |
| P0.2 | `test_build_lot_size_parquet_excludes_sidecar_vs_sidecar_mismatches` | Per-pair exclusion at the sidecar-vs-sidecar layer; build returns successfully |
| P0.2 | `test_build_lot_size_parquet_excludes_bhavcopy_internal_mismatches` | Per-pair exclusion at the bhavcopy-internal layer |
| P0.2 | `test_build_lot_size_parquet_excludes_sidecar_vs_bhavcopy_mismatches` | Per-pair exclusion at the sidecar-vs-bhavcopy layer |
| P0.2 | `test_build_lot_size_parquet_against_4_sidecar_fixtures` | Unified cache populates correctly from regime B sidecars (PNB May 2024 lot_size = 8000; ABBOTINDIA May 2024 EXCLUDED) |
| P0.2 | `test_build_lot_size_parquet_diagnostic_format_matches_operator_template` | Diagnostic line format = `mismatch found in lot sizes between {x} and {y} for {sym} for {expiry}: {lot_x} and {lot_y}` |
| P0.2 | `test_extract_lot_sizes_udiff_returns_deduped_triples` | Sibling-cache extractor correctness (RELIANCE 2024-08-29 = 250) |
| P0.2 | `test_load_bhavcopy_fo_writes_sibling_lot_sizes_cache` | Sibling-cache write hook fires on fresh fetch |
| P0.2 | `test_prefetch_universe_autobuilds_lot_size_parquet_if_missing` | Auto-build trigger semantics (missing → silent rebuild) |
| P2.1 | `test_prefetch_regime_b_volume_derived_via_unified_lookup` | Legacy-era bhavcopy row → volume = contracts × unified_lookup(symbol, expiry) |
| P2.2 | `test_get_options_chain_surfaces_legacy_ltp_caveat` | MCP caveat trigger |

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
- **D3**: `ltp` is NaN for regime B rows; caveat surfaces in `get_options_chain` per P2.2.
- **D4**: `options_loader.py` kept as dead code with deprecation header (P1.8); graceful-degrade removed (P1.7). **Refinement (2026-06-02 operator clarification)**: missing turnover triggers a per-cell SKIP (via new `MissingTurnoverError(MissingDataError)` subtype, auto-caught by `_SKIPPABLE_ERRORS`) rather than a loud failure that crashes the sweep. Operator sees missing-turnover skips as a distinct reason in skip_summary / drill-down — closer to "this is a data-quality signal" than "this is a code bug." Pattern follows `IlliquidLegError(MissingDataError)` precedent.

**Architectural refinement (2026-06-02 operator direction — UNIFIED LOT-SIZE LOOKUP)**:
- All lot-size resolution goes through ONE unified cache: `data/cache/lot_sizes.parquet`.
- Built by `scripts/build_lot_size_parquet.py` (P0.2) from BOTH committed sidecars (`data/manual/contracts/NSE_FO_contract_*.csv.gz`, regime B) AND a sibling per-date bhavcopy lot-size cache (`data/cache/bhavcopy_fo_lot_sizes/*.parquet`, written by `bhavcopy_fo_loader.py` on every fresh bhavcopy fetch — regime C, extracts `NewBrdLotQty` from raw UDiff CSV).
- Auto-build trigger: `prefetch_universe.py` invokes the build script when `data/cache/lot_sizes.parquet` is missing. Silent rebuild; no operator prompt.
- Bhavcopy-cache schema is NOT extended to carry `lot_size` per row (originally proposed in P1.1); instead, the transform in P1.3 looks up `(symbol, year, month) → lot_size` from the unified cache. Deduplicates ~60-90 days of repeated lot_size values per contract; engine code is regime-agnostic.
- Phase 2 collapses: the standalone `nse_fo_contract_loader.py` originally proposed (old P2.1) is subsumed by P0.2's build script. Phase 2 is now 4 sub-commits (P2.1 → P2.4) instead of 6.

**Cross-source mismatch policy refinement (2026-06-03 operator direction — PER-PAIR EXCLUSION)**:
- Initial proposal: loud-fail via `CrossSourceLotSizeMismatchError` on any sidecar-vs-bhavcopy disagreement; reviewer-extended to also cover sidecar-vs-sidecar (grill #1 on 9b6c32b).
- Smoke-test against the committed P0.1 fixtures surfaced **101 systematic sidecar-vs-sidecar mismatches** — the dominant pattern is the Apr-16 snapshot's `lot_size` being **approximately 2×** the May-16/Jun-12/Jul-5 snapshots' values (e.g. ABBOTINDIA 24MAY 40→20, ADANIPORTS 24MAY 800→400, BHARTIARTL 24MAY 950→475). The revision direction is NOT uniform: counter-examples exist where the lot_size INCREASED instead (e.g. CANBK 24MAY 2700→6750, ~2.5×), consistent with NSE's twice-yearly recalibration to keep contract notionals in the ₹5-10 lakhs range — when the underlying stock RISES, lot halves; when it FALLS, lot increases. NSE biannual lot-size review took effect at the April 2024 cutover (~Apr 25, 2024).
- Operator's revised policy: instead of loud-fail (which would block 101 pairs entirely → no Phase 1 progress), **drop the offending `(symbol, expiry-month)` pair from the unified cache**. Same treatment for ALL three mismatch types (sidecar-vs-sidecar, bhavcopy-internal, sidecar-vs-bhavcopy) — symmetric per-pair exclusion.
- Rationale: if NSE revised a contract's lot_size mid-life, that contract's P&L is structurally ambiguous (entry at one lot, exit at another). Picking a "winner" value produces wrong P&L. Skipping is more honest.
- Downstream impact: excluded `(sym, expiry-month)` → `lot_size_lookup` returns None → transform raises `MissingTurnoverError` → sweep skips those cells with `skip_reason="MissingTurnoverError"`. Operator sees the exclusion count both in the build-script output AND aggregated in the skip_summary distribution.
- `CrossSourceLotSizeMismatchError` exception class retained in `src/data/errors.py` for a potential future strict-mode flag; not raised under the default policy.
- Net impact on regime B coverage: ~25-30 symbols mostly affecting May/Jun/Jul 2024 expiries get excluded. The rest of regime B (~75% of (sym, expiry) pairs in the affected window) prices fine.

Plus three implicit decisions:
- **All strikes**: no strike_planner pre-filtering. Every traded strike in the bhavcopy becomes a contract. **Disk cost note** (per reviewer grill #6 on e0bc85a): with `strike_planner` removed, per-cell strike count goes from ~13 (`DEFAULT_STRIKES_PER_SIDE = 6` + ATM = 13 per option_type) to all-traded (~30-100+ per option_type for active underlyings). Estimated **~3-5× cache growth** over current `data/cache/options/` footprint. **Verify storage capacity before Phase 1 prefetch run**.
- **0-volume disqualifies**: handled by existing `IlliquidLegError` gate in [pnl.py](src/engine/pnl.py). No new logic.
- **Sweep batching unchanged**: cell-granular tuples per [sweeper.py:304-312](src/engine/sweeper.py#L304-L312).

**Deferred — universe expansion**:
The bhavcopy carries every F&O-listed symbol (~204 distinct symbols per snapshot), not just our 50. Expanding the sweep universe beyond the current 48 blue chips + PNB + BHEL is technically zero-extra-fetch-cost (the data is already in the bhavcopy). However, **the materialize + sweep compounds**: ~4× more symbols × the all-strikes ~3-5× cache growth = ~12-20× total cache growth + ~4× sweep compute time. Recommendation: **stay at 50 for Phase 1**, validate the migration works at current scale, expand as a separate decision after smoke confirms. This is a SCOPE decision, not a CAPABILITY question — and explicitly NOT a goal of this migration.
