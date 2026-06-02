# Manual NSE_FO_contract snapshots

Four NSE_FO_contract snapshots committed as repo fixtures for the
regime B (Apr 15 → Jul 7 2024) lot-size lookup. The
bhavcopy-only architecture's unified `data/cache/lot_sizes.parquet`
is built from BOTH these committed sidecar files AND the cached
UDiff bhavcopies (regime C, post-Jul-8-2024).

See [MIGRATION.md](../../../MIGRATION.md) — specifically the
[§Cross-source lot-size policy](../../../MIGRATION.md#cross-source-lot-size-policy)
and [§Phase 0](../../../MIGRATION.md#phase-0--operator-fixtures--unified-lookup-build)
sections — for the architectural role of these files.

## Files

| File | Snapshot date | Expiry coverage |
|---|---|---|
| `NSE_FO_contract_16042024.csv.gz` | 2024-04-16 | Apr / May / Jun 2024 expiries |
| `NSE_FO_contract_16052024.csv.gz` | 2024-05-16 | May / Jun / Jul 2024 expiries |
| `NSE_FO_contract_12062024.csv.gz` | 2024-06-12 | Jun / Jul / Aug 2024 expiries |
| `NSE_FO_contract_05072024.csv.gz` | 2024-07-05 | Jul / Aug / Sep 2024 expiries |

Each snapshot is ~80-90k rows × 150 columns covering ~204 distinct
F&O-listed symbols. Total committed size: ~6.7MB gzipped.

## Provenance

These files came from the NSE archives bundled-download UI at
<https://www.nseindia.com/all-reports-derivatives> via the
"Reports-Archives-Multiple-DDMMYYYY.zip" wrapper format. The outer
ZIP wrappers are NOT committed — only the inner `.csv.gz` files
that NSE distributes natively.

Operator-side fetch flow (one-time setup per snapshot):
1. Navigate to <https://www.nseindia.com/all-reports-derivatives>.
2. Pick a date in the calendar (4 dates needed for regime B coverage —
   see "Files" table above).
3. Select "F&O-MII - Contract File (.gz) (NSE Exclusive contract)"
   from the report dropdown.
4. Download the resulting `Reports-Archives-Multiple-DDMMYYYY.zip`.
5. `unzip` and place the inner `NSE_FO_contract_DDMMYYYY.csv.gz`
   here.

The NSE archive API is Akamai-protected (see
[MIGRATION.md §Non-goals](../../../MIGRATION.md#non-goals): "No
Akamai bot-challenge integration"). Programmatic fetching is
**explicitly not supported** — operator does this manually via
browser when coverage needs to expand.

## Why committed (not gitignored like the rest of `data/`)

`data/manual/` is the **only** subfolder of `data/` that is NOT
gitignored — see [.gitignore](../../../.gitignore) for the explicit
allowlist. The rationale:

- `data/cache/` — auto-fetched (jugaad) or auto-derived (lot_sizes
  parquet); gitignored. `rm -rf data/cache/` is the canonical
  "force re-derive everything" path; safe because nothing in here
  is irrecoverable.
- `data/results/` — engine-computed; gitignored. Same reasoning.
- `data/manual/` — operator-curated source data with no automatic
  derivation path. Without this in the repo, a fresh clone CANNOT
  rebuild the regime B portion of the unified lot-size lookup
  (Akamai blocks programmatic re-fetch). Committed for
  reproducibility.

## Pre-commit verification

Each file was schema-validated before commit (150 columns including
`TckrSymb`, `StockNm`, `NewBrdLotQty`, `StrkPric`, `OptnTp`) and
cross-checked for PNB OPTSTK lot size consistency (= 8000 across
all 4 snapshots, matching the operator's earlier PNB CSV inspection
referenced in [DATA_PRODUCTS.md](../../../DATA_PRODUCTS.md)).

## Re-derivation

If coverage needs to expand (e.g., further into regime A or beyond
Jul 2024), the operator follows the same manual flow above. **Do
not commit additional snapshots without updating MIGRATION.md's
§Inputs available coverage table** — silent fixture drift between
the doc and the on-disk files would be a real bug source.
