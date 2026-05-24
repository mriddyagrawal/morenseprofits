# SPECS — Data schemas, interfaces, conventions

Companion to PLAN.md. PLAN says *what* and *why*; SPECS pins down *exactly how*. Anything code-level that future commits will rely on lives here so reviewer + builder agree on contracts.

**Canonical jugaad-data reference:** a local clone with improved docs lives at `/Users/mriddy/Documents/GitHub/jugaad-data` (the user maintains it). The PyPI 0.33.1 docs are thin; when in doubt about jugaad behavior, read `docs/guides/nse_historical.rst`, `docs/guides/caching.rst`, or the source in `jugaad_data/nse/archives.py` and `jugaad_data/holidays.py`. **Important**: jugaad has its own internal pickle disk cache (via `appdirs`, overridable via `J_CACHE_DIR`) — this can mask whether OUR loader hit the network during testing.

## 1. Repository layout

```
morenseprofits/
├── PLAN.md
├── SPECS.md
├── README.md
├── comments.md                  # reviewer-owned; builder never edits
├── requirements.txt
├── .gitignore
├── pytest.ini
├── app.py                       # streamlit entrypoint (Phase 6)
├── scripts/
│   └── smoke_test.py            # Phase 0
├── src/
│   ├── __init__.py
│   ├── config.py                # paths, constants, cost model defaults
│   ├── data/
│   │   ├── __init__.py
│   │   ├── cache.py             # parquet read/write helpers
│   │   ├── spot_loader.py
│   │   ├── options_loader.py
│   │   ├── expiry_calendar.py
│   │   └── trading_calendar.py
│   ├── universe/
│   │   ├── __init__.py
│   │   ├── blue_chip.py
│   │   └── momentum.py
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── base.py              # Strategy protocol, Trade, Leg
│   │   ├── short_straddle.py
│   │   ├── long_straddle.py
│   │   ├── short_strangle.py
│   │   ├── long_strangle.py
│   │   └── iron_condor.py
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── pnl.py               # per-trade pricing kernel
│   │   ├── costs.py             # STT/brokerage/exchange fee model
│   │   ├── backtester.py
│   │   └── sweeper.py
│   ├── analytics/
│   │   ├── __init__.py
│   │   ├── aggregate.py
│   │   └── ranking.py
│   └── web/
│       ├── __init__.py
│       └── components.py
├── tests/
│   ├── test_data.py
│   ├── test_strategies.py
│   ├── test_engine.py
│   └── fixtures/
├── data/
│   ├── cache/                   # gitignored
│   │   ├── spot/{symbol}/{year}.parquet
│   │   ├── options/{symbol}/{expiry}/{strike}-{type}.parquet
│   │   └── expiries/{symbol}.parquet
│   └── results/                 # gitignored
│       └── {strategy}_{run_id}.parquet
└── .venv/                       # gitignored
```

## 2. Cached data schemas (parquet on disk)

### 2.0 Date-dtype convention (applies to every schema below)

Every column documented as `date` in the schemas below is stored on disk as
`datetime64[us]` (pandas 3.0 + pyarrow round-trip lands here) and exposed via
`.dt.date` in any public API that promises a Python `date`. Microsecond
precision is far more than daily data needs; tests assert
`pd.api.types.is_datetime64_any_dtype(col)` rather than pinning a specific unit.

Per-schema columns named below use `date` as shorthand for "follows §2.0".

### 2.1 Spot — `data/cache/spot/{SYMBOL}/{YEAR}.parquet`
Columns (subset of jugaad `stock_df`, normalized):
| col | dtype | notes |
|---|---|---|
| `date` | `date` (see §2.0) | trading date, naive IST, midnight |
| `symbol` | `string` | uppercase |
| `series` | `string` | always `"EQ"` for v1 |
| `open`, `high`, `low`, `close` | `float64` | INR |
| `vwap` | `float64` | INR |
| `volume` | `int64` | shares |
| `prev_close` | `float64` | INR |

### 2.2 Options — `data/cache/options/{SYMBOL}/{EXPIRY:yyyymmdd}/{STRIKE_INT}-{CE|PE}.parquet`

One parquet per (symbol, expiry, strike, option_type). On the first
fetch, the loader pulls the **full lifetime** of the contract (~120
calendar days back from expiry, or up to ``today_fn()`` if expiry is
in the future) — so narrow-window callers later don't re-fetch.

| col | dtype | notes |
|---|---|---|
| `date` | `date` (see §2.0) | trading date. *No IST shift needed* — unlike `stock_df`, `derivatives_df` returns DATE at `00:00:00` naive (already midnight IST). |
| `symbol` | `string` | underlying, uppercase |
| `expiry` | `date` (see §2.0) | contract expiry |
| `strike` | `float64` | INR strike (whole-rupee per SPECS §5; `cache.option_path` enforces) |
| `option_type` | `string` | `"CE"` or `"PE"` |
| `open`, `high`, `low`, `close` | `float64` | premium INR |
| `ltp` | `float64` | last traded price |
| `settle_price` | `float64` | NSE daily settlement of the option |
| `lot_size` | `int64` (plain) | from `MARKET LOT` — historical per row per §4 rule 3; never absent in jugaad output |
| `volume` | `int64` (plain) | from `TOTAL TRADED QUANTITY` — in **share units**, NOT contract units. ``contracts = volume // lot_size`` if needed |
| `oi` | `Int64` (nullable) | from `OPEN INTEREST`. jugaad emits float64 with occasional NaN; cast to nullable per §2.0/§2.4 convention |
| `oi_change` | `Int64` (nullable) | from `CHANGE IN OI`. Same nullable reasoning |

### 2.3 Expiry calendar — `data/cache/expiries/{SYMBOL}.parquet`
| col | dtype |
|---|---|
| `symbol` | `string` |
| `expiry_date` | `date` (see §2.0) |
| `month_anchor` | `date` (see §2.0; first calendar day of the expiry's month) |

> **jugaad-data gotcha (background):** `expiry_dates(dt, contracts=N)` is **not** "the next N expiries". It returns the set of expiries that had **more than N contracts traded** in the F&O bhavcopy for `dt` (see `archives.py:504`). With `contracts=0` (default) it returns every expiry that showed up in the F&O book on day `dt`. Crucially, it returns `list(set(dts))` — non-deterministic across runs.

**Sampling strategy (Phase 1.3.2).** `monthly_expiries(symbol, from_date, to_date)`:

1. For each calendar month spanned by `[from_date, to_date]`, iterate candidate sample days `1, 2, …, 7` and call `load_bhavcopy_fo(candidate)`. The first one that resolves (no `MissingDataError`) is the sample bhavcopy for that month — one bhavcopy lists all OPTSTK expiries listed at that point, so one sample per month is sufficient.
2. From each sample, filter `instrument == "OPTSTK"` and `symbol == <requested>`; collect the unique `expiry` values.
3. Union across all months, drop duplicates, **`sorted(...)` before return** (kills the `list(set(dts))` non-determinism upstream).
4. The result is cached at `data/cache/expiries/{SYMBOL}.parquet`. Cache invalidation: appending months extends the calendar; the cache stores `(symbol, expiry_date, month_anchor)` rows so a subsequent call for a new month range only fetches the missing months.

**Determinism contract.** Two calls to `monthly_expiries` with identical inputs return byte-identical lists. Tests pin this — the reason the module exists is to escape the upstream set-iteration order.

### 2.4 F&O bhavcopy — `data/cache/bhavcopy_fo/{YYYYMMDD}.parquet`

Per-date F&O bhavcopy, cached **once per date** and re-used by every symbol's
expiry-calendar build. A 5-symbol × 5-year sweep should fetch ~60 monthly
bhavcopies once, not 300 (one per symbol per month).

Columns (parsed from jugaad's `bhavcopy_fo_raw` CSV — the schema below is
normalized lowercase; raw upstream uses uppercase):

| col | dtype | notes |
|---|---|---|
| `instrument` | `string` | one of OPTSTK / FUTSTK / OPTIDX / FUTIDX |
| `symbol` | `string` | uppercase, underlying |
| `expiry` | `date` | contract expiry — the column we mine for the expiry calendar |
| `strike` | `float64` | INR (NaN for futures rows) |
| `option_type` | `string` | "CE" / "PE" / `<NA>` for futures |
| `open`, `high`, `low`, `close` | `float64` | premium INR |
| `settle_price` | `float64` | NSE daily settle |
| `contracts` | `int64` (plain) | number of contracts traded; **fillna(0)** because an absent value means zero traded — that's truth-preserving, not made-up |
| `oi` | `Int64` (nullable) | open interest; **legitimately unknown** is meaningful (NSE occasionally blanks OI on new contracts); preserves the distinction between 0 and missing |
| `oi_change` | `Int64` (nullable) | change in OI; same reasoning as `oi` |
| `trade_date` | `date` | the date the bhavcopy represents (== the filename) |

**Look-ahead bias contract.** The bhavcopy is dated by `trade_date`. Engine
consumers that join bhavcopy rows into a backtest **must** filter
`trade_date ≤ entry_date` at use time — Phase 3's backtester enforces this.

**Format compatibility (verified empirically — see `scripts/capture_bhavcopy_fixtures.py`).**

The §2.4 normalized schema above is the *internal* shape exposed by
`src/data/bhavcopy_fo_loader.py`. Upstream NSE serves two completely
different schemas on either side of 2024-07-08 and `bhavcopy_fo_raw`
covers only the legacy side — so the loader has to dispatch:

| upstream | source | when |
|---|---|---|
| Legacy ZIP | `jugaad_data.nse.archives.bhavcopy_fo_raw(dt)` | `dt < 2024-07-08` |
| UDiff direct URL | `https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip` | `dt ≥ 2024-07-08` (NSE's `NSEDailyReports` API exposes UDiff for today/yesterday only; historical requires direct URL construction) |

Legacy columns: `INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP`. `INSTRUMENT` codes: `OPTSTK`, `OPTIDX`, `FUTSTK`, `FUTIDX`.

UDiff columns: `TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,XpryDt,FininstrmActlXpryDt,StrkPric,OptnTp,FinInstrmNm,OpnPric,HghPric,LwPric,ClsPric,LastPric,PrvsClsgPric,UndrlygPric,SttlmPric,OpnIntrst,ChngInOpnIntrst,TtlTradgVol,TtlTrfVal,TtlNbOfTxsExctd,SsnId,NewBrdLotQty,Rmks,Rsvd1,Rsvd2,Rsvd3,Rsvd4`. `FinInstrmTp` codes: `STO` (stock option), `IDO` (index option), `STF` (stock future), `IDF` (index future). Maps to legacy `OPTSTK`/`OPTIDX`/`FUTSTK`/`FUTIDX` 1:1.

The loader normalizes both → §2.4 schema; downstream callers (`expiry_calendar`, Phase 1.4 options_loader) see one shape.

**Canonical `expiry` column.** UDiff exposes both `XpryDt` (originally
scheduled expiry) and `FininstrmActlXpryDt` (actually-settled expiry); they
agree except on holiday-shifted Thursdays (e.g. scheduled Thursday is a NSE
holiday → contract settles previous trading day). The loader maps
**`FininstrmActlXpryDt`** to our `expiry` column because that's the date a
backtest's exit price ties to. When the two diverge, the loader emits a
`warnings.warn(...)` so we know holiday shifts are happening; we never
silently coerce. (Legacy format has only `EXPIRY_DT` — no divergence to
record.)

**Browser User-Agent requirement.** The direct-URL UDiff fetch returns
HTTP 403 without a `User-Agent` header from a recent browser. The loader
ships the same `Mozilla/5.0 ... Chrome/...` UA that `scripts/capture_bhavcopy_fixtures.py`
uses. Don't strip it "to be tidy" — NSE's WAF rejects bare requests.

**Cutover date source-of-truth.** The loader imports
`jugaad_data.nse.archives.NSEArchives.udiff_start_date` rather than
hardcoding `date(2024, 7, 8)`. Keeps us in lockstep if upstream ever
shifts their view of the boundary.

**Tests use recorded byte-for-byte fixtures** at `tests/fixtures/bhavcopy_fo_legacy_*.csv` and `tests/fixtures/bhavcopy_fo_udiff_*.csv` — live tests are skipped by default per `pytest.ini`, so regression value lives in the recordings.

### 2.5 Results — `data/results/{strategy}_{run_id}.parquet`
One row per closed trade.
| col | dtype | notes |
|---|---|---|
| `run_id` | `string` | UUID |
| `strategy` | `string` | `"short_straddle"` etc. |
| `symbol` | `string` | |
| `expiry` | `date` | contract expiry the trade is anchored to |
| `entry_date` | `date` | |
| `exit_date` | `date` | |
| `entry_offset_td` | `int32` | trading days before expiry on entry (positive) |
| `exit_offset_td` | `int32` | trading days before expiry on exit (positive; 0 = expiry day) |
| `params_json` | `string` | strategy-specific knobs (e.g. strike_offset_pct) |
| `legs_json` | `string` | list of {strike, type, side, qty, entry_px, exit_px, lot_size} |
| `gross_pnl` | `float64` | sum of (entry_px − exit_px) × side × qty × lot_size |
| `costs` | `float64` | applied per cost model |
| `net_pnl` | `float64` | gross − costs |
| `notional_at_entry` | `float64` | underlying spot × total lot exposure |
| `entry_spot` | `float64` | spot close on entry_date |
| `exit_spot` | `float64` | spot close on exit_date |

## 3. Public function signatures (frozen interfaces — change requires PLAN.md change-log entry)

```python
# src/data/spot_loader.py
def load_spot(symbol: str, from_date: date, to_date: date) -> pd.DataFrame: ...

# src/data/options_loader.py
def load_option(
    symbol: str,
    expiry: date,
    strike: float,
    option_type: Literal["CE", "PE"],
    from_date: date,
    to_date: date,
) -> pd.DataFrame: ...

# src/data/expiry_calendar.py
def monthly_expiries(symbol: str, from_date: date, to_date: date) -> list[date]: ...

# src/data/trading_calendar.py
def trading_days(from_date: date, to_date: date) -> list[date]: ...
def offset_trading_days(anchor: date, n: int) -> date:
    """Return the date that is n trading days BEFORE anchor (n>=0)."""

# src/strategies/base.py
@dataclass(frozen=True)
class Leg:
    option_type: Literal["CE", "PE"]
    strike: float
    side: Literal["BUY", "SELL"]
    qty_lots: int

@dataclass(frozen=True)
class Trade:
    symbol: str
    expiry: date
    entry_date: date
    exit_date: date
    legs: tuple[Leg, ...]
    strategy: str
    params: dict  # serialized via params_json

class Strategy(Protocol):
    name: str
    def generate_trades(
        self,
        symbol: str,
        expiry: date,
        entry_date: date,
        exit_date: date,
        spot_at_entry: float,
        params: dict,
    ) -> list[Trade]: ...

# src/engine/pnl.py
def price_trade(trade: Trade) -> dict:
    """Returns dict matching results parquet row schema.
       Raises MissingDataError if any leg lacks an entry or exit price."""

# src/engine/backtester.py
def run_backtest(
    strategy: Strategy,
    universe: list[str],
    start_date: date,
    end_date: date,
    param_grid: dict[str, list],
    entry_offsets_td: list[int],
    exit_offsets_td: list[int],
) -> pd.DataFrame:  # results-parquet schema
    ...
```

## 4. Cost model (default — versioned in `src/engine/costs.py` as `COST_MODEL_V1`)

For Indian equity options, per leg, per round trip:

| component | applies to | rate |
|---|---|---|
| Brokerage | both sides | flat ₹20 per executed order (Zerodha-style discount broker baseline) |
| STT | **sell side of options** only | 0.0625% of premium (×lot_size×qty); on exercised options, 0.125% of intrinsic — v1 assumes square-off at expiry, not exercise |
| Exchange txn fee | both sides | 0.0503% of premium turnover |
| GST | on brokerage + txn fee | 18% |
| SEBI fee | both sides | ₹10 per crore of premium turnover (negligible but included) |
| Stamp duty | buy side only | 0.003% of premium turnover |

A `params: dict | None = None` argument lets the engine pass a different cost model for sensitivity analysis. Default behavior never changes silently.

## 5. ATM strike selection rule (frozen)

`ATM_strike = argmin_{K ∈ available_strikes(symbol, expiry, entry_date)} |K - spot_close(entry_date)|`

Tiebreaker (two strikes equidistant): pick the lower strike.

`available_strikes` is determined by attempting strikes at the NSE-defined step around the spot (auto-detected per symbol from observed strikes in cached data) and dropping any that have no traded data on `entry_date`.

If `available_strikes` is empty (illiquid contract), engine raises `NoLiquidStrikeError`; sweeper logs and skips.

## 6. Time / offset conventions (frozen)

- All dates are **IST trading dates**, no times, no timezone objects in the schema (we just keep `date` or naive `datetime` at midnight).
- "Entry offset = 15" means `entry_date = offset_trading_days(expiry, 15)`.
- "Exit offset = 1" means `exit_date = offset_trading_days(expiry, 1)`; offset 0 = expiry day itself.
- Trading-day calendar is derived from `load_spot("RELIANCE", ...)` dates (always-traded liquid blue chip used as the calendar source-of-truth). Cached.

## 6a. Offline mode (cache-only enforcement)

Loaders accept an optional `offline: bool = False` keyword (default off). When True, a cache miss raises `MissingDataError` rather than falling back to network. Equivalent env-var override: `MORENSE_OFFLINE=1`. Phase 1.5 wires this and adds telemetry that prints a one-line warning whenever a loader hits the network (regardless of offline mode) so sweep runs surface accidental fetches.

## 7. Cache invalidation

- Caches are **append-mostly**. We never overwrite a parquet that contains real historical data unless `--force-refresh` is passed via CLI.
- Schema changes bump a `CACHE_VERSION` constant in `src/data/cache.py`; on bump, the cache directory is moved to `data/cache.v{N-1}/` (manual cleanup, never automatic deletion).
- **Additive vs breaking.** Adding a new schema family (e.g. §2.4 bhavcopy_fo added in p1.3.0) does **not** bump `CACHE_VERSION` — existing on-disk data is unaffected. Only a change to an *existing* schema's column set or dtypes triggers a bump.

## 8. Error taxonomy

```python
class DataError(Exception): ...
class MissingDataError(DataError): ...            # leg/spot missing for required date
class NoLiquidStrikeError(DataError): ...         # no strikes traded on entry_date
class CacheCorruptError(DataError): ...
class BhavcopyFormatError(DataError): ...         # CSV header matches neither pre/post Jul-8-2024 schema
class StrategyConfigError(ValueError): ...        # bad params dict
```

The engine prefers loud failure over silent fallback. The sweeper catches `DataError` and records skip-reason; uncaught exceptions are bugs.

## 9. Testing conventions

- `pytest` with `tests/` at repo root.
- Network-touching tests are marked `@pytest.mark.network` and skipped by default; run via `pytest -m network`.
- Fixture parquets in `tests/fixtures/` are tiny (≤ 50 rows) and committed to git.
- Determinism: `tests/test_engine.py::test_byte_identical_reruns` hashes the result parquet.
