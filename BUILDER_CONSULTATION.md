# Builder consultation — pricing & validity arc

End-of-arc consultation cycle, per the reviewer-approved cadence (one
file per arc, deleted/replaced at the next arc). This one is the
**pricing & validity** arc: how the engine decides which cells are
real trades, and how it picks a fill price for the ones that are.

The operator-builder discussion that led to this plan happened
2026-05-27 / 2026-05-28; key decisions captured in §3 below.

---

## 1. State of the codebase

- 563/563 tests pass at HEAD (`f9da84d`).
- Just-landed UX surfaces: CVaR-5% right pane (`9703c1a`), median/mean
  toggle (`f9da84d`), regex-decoupled compare-cells caveat (`2175167`).
- BUILDER's mean-bias-direction grill on the latest review: reviewer
  flagged mean as "less conservative"; operator/builder math disagreed
  (short-vol P&L is LEFT-skewed → mean < median → mean is the more
  honest long-run EV). No caveat caption added; reviewer's grill #1
  rejected on the math.
- In-flight prefetch run at ~52% (BHEL universe addition + log-width
  fix uncommitted in working tree; both lined up to ship before
  prefetch restart).

## 2. The two problems

### Problem A — Pricing: which field gives a true fill price?

Status quo: every leg fills at the day's `close`. For thinly-traded
strikes this is a fiction — close is the last trade of the day, which
on a near-zero-volume day might be a single small print far from where
the bulk of volume cleared (or where any reasonable bid/ask would have
been). The 1% slippage haircut partially compensates for ATM blue-chip
spreads but wildly under-charges for thin strikes.

Operator framing (verbatim, abbreviated):

> "EOD bhavcopy can't give you a real fill price because a fill is
> min(ask) or max(bid) at the moment you cross, and bhavcopy has
> neither. So the question reframes to: which proxy is least wrong?"
>
> Ranking: VWAP > close-with-liquidity-gate > settle_price > ltp.

### Problem B — Validity: was this cell even tradeable?

Status quo: zero validity filter on volume/OI. Engine books a trade
whenever the loader returns a row with `close` + `lot_size` + `volume`
populated. NSE often publishes a close even when zero contracts
traded (theoretical fallback) — these "fills" inflate the result.

Operator framing:

> "A 10k-cell sweep with 7k valid trades is more informative than a
> 10k-cell sweep with 10k 'trades' of which 3k are model fictions."

## 3. Decisions locked

Discussed and resolved before drafting this plan:

| Decision | Outcome | Reason |
|---|---|---|
| `close == settle_price AND volume == 0` as separate skip reason? | **Drop**. Single `IlliquidLegError` for the whole gate. | Telemetry loss is small; operator wants to avoid over-conservatism in skip-reason labels. The cell skips either way; the label-only subdivision is complexity for marginal data-quality measurement. |
| DTE cap (e.g. `dte > 60 → skip` for stocks) | **Drop**. | Liquidity gates do the work — past-T-43-stock-options-have-no-volume IS what the gates will surface. Cap is structurally redundant. |
| Fill price proxy choice | **VWAP** (with `close` fallback) | Operator confirmed: VWAP is the closest EOD-only proxy to a fillable price; midrange/midpoint are NOT tradeable (worked example in chat showed 18% over-promise on a quiet ITC strike). |
| Volume units verification | **shares (lot_size-multiplied)** — verified against real cached RELIANCE 1500-CE parquet (volume=5000, lot_size=500 → 10 lots) | Threshold formula `volume_shares >= K * lot_size` is correct. |
| Turnover field availability | **Already in NSE response**, dropped at `_normalize` because `_RENAMES` doesn't carry `"PREMIUM VALUE"` forward. One-line ingest fix. | Verified via `grep FH_TOT_TRADED_VAL` in `src/data/options_loader.py:121`. |

## 4. Commit plan (nuclear, in order)

### Commit 1 — `feat(p7.pricing.liquidity_gate)`

**Goal**: refuse to book a trade whose entry or exit leg had zero
trading activity.

**Where**: [`src/engine/pnl.py::_price_one_leg`](src/engine/pnl.py),
inserted AFTER the existing look-ahead + lot-size-continuity checks
and BEFORE slippage application.

**Logic** (single combined gate, no stale-close subdivision):

```python
if entry_row.volume == 0 or exit_row.volume == 0 or entry_row.oi == 0:
    raise IlliquidLegError(
        f"{context}: leg illiquid — "
        f"entry_volume={entry_volume}, exit_volume={exit_volume}, "
        f"entry_oi={entry_oi}. No fill possible."
    )
```

**New typed skip reason**: `IlliquidLegError(MissingDataError)` in
`src/data/errors.py`. Sweeper's `_SKIPPABLE_ERRORS_CACHE_ONLY` already
catches `MissingDataError`, so no engine-level changes needed.

**Tests** (`tests/test_pnl.py` extension):
- Cell with `entry_volume=0` → `IlliquidLegError` raised, sweeper
  catches → row in skip log with correct reason.
- Cell with `entry_oi=0` → same.
- Cell with `entry_volume > 0 AND exit_volume > 0 AND entry_oi > 0` →
  trade prices normally (regression test for the happy path).

**LOC estimate**: ~20 LOC engine + ~50 LOC tests. One commit.

### Commit 2 — `chore(data.options_loader.turnover)`

**Goal**: stop dropping the `"PREMIUM VALUE"` (turnover) column at
ingest so future re-fetches carry it. Lands BEFORE the in-flight
prefetch restarts (so the BHEL re-fetch populates turnover into the
cache).

**Changes** (`src/data/options_loader.py`):

1. Add `"PREMIUM VALUE": "turnover"` to `_RENAMES` (line 283).
2. The `_SPEC_COLS = list(_RENAMES.values())` derivation auto-picks
   it up; no separate change needed.
3. Add `turnover` to the dtype coercion loop in `_normalize()` so it
   lands as `float64` (rupees, can be in tens of crores per day for
   active strikes).

**Cache compatibility**: existing parquets don't have the column.
Loading them post-fix returns NaN for turnover — Commit 3's VWAP
function falls back to `close` cleanly in that case, so no regression.

**Tests** (`tests/test_options_loader.py`):
- Normalised frame from a known-good NSE response carries the
  `turnover` column with positive float values.
- Empty NSE response still normalises cleanly (no missing-column
  crash on the new schema).

**LOC estimate**: ~5 LOC code + ~20 LOC tests. One commit.

### Commit 3 — `feat(p7.pricing.vwap_fill)`

**Goal**: switch fill price from `close` to `turnover / volume` (VWAP)
when both are available; fall back to `close` otherwise.

**Where**: `src/engine/pnl.py::_pick_close_on` (rename to
`_pick_fill_price` or keep name + change semantics — TBD).

**Logic**:

```python
def _pick_fill_price(row) -> float:
    """VWAP when turnover available and volume > 0; else close."""
    if pd.notna(row.turnover) and row.volume > 0:
        return float(row.turnover) / float(row.volume)
    return float(row.close)
```

**Slippage**: unchanged. `SLIPPAGE_MODEL_V1.realized_entry_exit(...)`
takes the raw fill price (now VWAP-or-close) and applies the 1% per-
side haircut once per leg. No double-application risk — slippage is
called exactly once per leg in `_price_one_leg:150` and the change is
only to WHAT goes into that call.

**Result-row schema additions** (additive, non-breaking):
- `entry_turnover`, `exit_turnover` — per-leg telemetry for auditing
  VWAP-vs-close divergence post-hoc.
- `entry_px` redefined: now means "the fill price the engine used"
  (VWAP or close). The audit trail still works since `entry_px` was
  already the "input to slippage" semantic — just changes its source.

**Tests** (`tests/test_pnl.py`):
- Leg with `turnover=8000, volume=1000` → `entry_px == 8.0` (VWAP).
- Leg with `turnover=NaN` (legacy cache) → `entry_px == close` (fallback).
- Slippage applied exactly once per realized price (regression — the
  existing slippage tests cover this, but reaffirm post-VWAP).

**LOC estimate**: ~15 LOC code + ~40 LOC tests. One commit.

### Commit 4 (deferred until live-run validates) — `feat(p7.pricing.liquidity_gate.tighten)`

**Goal**: tighten the gate from `> 0` to `>= K * lot_size` (≥ K lots
traded). K starts at 1 (one full lot), tunable via a module constant.

**Defer reason**: ship Commits 1–3 first, run a sweep, look at what
fraction of cells were rejected by `> 0` vs would be rejected by
`>= K`. Calibrate K empirically before committing to a number.

**Rough expectation**: K=1 (one full lot) catches the rounding-error
fills the operator flagged. K=5 would also catch quiet days but might
prune some legitimate marginal cells. The right K depends on per-
symbol distribution — possibly a per-symbol map later.

## 5. Open questions for REVIEWER

### Q1 — single-gate vs stale-close subdivision

We decided to drop the `close == settle_price` subdivision and use
ONE skip reason (`IlliquidLegError`) for the volume + OI gate. Operator
was specifically worried about over-conservatism in the labels and
asked for builder judgment. Builder's call: drop it. Telemetry loss
is small; the cell skips either way; complexity drop is real.

Does reviewer see a reason to keep the subdivision? (e.g. a known
analysis path that requires the stale-close-specifically count?)

### Q2 — schema additions on the result frame

Commit 3 adds `entry_turnover` / `exit_turnover` to the result-row
schema. This is additive (backward-compat for old parquets — they
get NaN in the new column). But it bumps `RESULTS_COLUMNS` and
touches `canonical_column_order`. The schema-drift test
(`test_read_results_raises_when_schema_drifted`) would need a tweak
to handle the new optional column.

Does reviewer prefer:
- (a) Hard-require the new column → forces re-sweep of every existing
  parquet (heavy);
- (b) Soft-add as an optional column → backward-compat (preferred);
- (c) Skip the result-row addition entirely; keep VWAP in the engine's
  hot path only, no audit telemetry.

Builder lean: (b). Audit telemetry is cheap and valuable; the
backward-compat path is one boolean check in the schema validator.

### Q3 — VWAP integration ordering

Commits 1, 2, 3 in this order. Reviewer: is there a reason to do
Commit 2 (ingest fix) BEFORE Commit 1 (gate)? The gate doesn't need
turnover; it only needs volume + OI which we already have. But
Commit 2 needs to land before prefetch restart so the cache pulls
turnover going forward.

Builder lean: Commit 1 first (smallest, lowest-risk), then Commit 2
(ingest fix, no behavior change, lands before prefetch restart), then
Commit 3 (uses turnover from re-fetched cache OR falls back to close
for old cache).

### Q4 — Phase 2 nice-to-haves out of scope here

These were discussed but explicitly deferred:

- **Strike-depth-aware slippage** — `slippage = f(volume, oi, |strike−spot|)`.
  Sound idea; needs calibration; doesn't depend on the gate landing.
- **B-S theoretical cross-check** — `|close − theoretical| / theoretical > X%`
  catches outlier prints on otherwise-liquid strikes. Requires IV
  surface compute (engineering, not new data).
- **Per-symbol K calibration** — empirical-derivation path for the
  tightened gate's K factor.

Reviewer: do any of these belong in THIS arc rather than Phase 2?

## 6. What this DOES NOT fix

Honesty surface for the operator (and the reviewer):

- **Bid-ask spread modeling stays at flat 1%** — VWAP is volume-
  weighted average, not bid-ask mid. Spreads still under-represented
  for thin strikes.
- **Single bad print on a liquid strike still gets booked** — if a
  contract had real volume (passes gate) but one trade was a panicked
  outlier far from the rest, VWAP still averages it in. The B-S
  cross-check (Phase 2) is what catches this case.
- **Survivorship-bias disclaimer stays** — universe is still a mid-
  2024 NIFTY-50 snapshot; nothing in this arc changes that.

---

*Builder. Awaiting reviewer response in comments.md.*
