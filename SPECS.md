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

> Caller's ``[from_date, to_date]`` only filters the *return* — the
> *fetch* always spans full contract lifetime. The 120-day buffer
> comfortably covers NSE's ~90-day listing window for stock options.

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
| `gross_pnl` | `float64` | sum of (entry_px − exit_px) × side × qty × lot_size per SPECS §3a |
| `costs` | `float64` | total frictional fees per `cost_model` (see §4) |
| `costs_breakdown_json` | `string` | per-component map: brokerage/stt/exchange/gst/sebi/stamp_duty/total |
| `net_pnl` | `float64` | `gross_pnl − costs` |
| `margin_at_entry` | `float64` | capital deposited per `margin_model` (see §4a). Indian options: BUY legs = premium paid; SELL legs = ~20% × strike × shares (SPAN+Exposure approx.) |
| `margin_breakdown_json` | `string` | per-component map: sell_leg_margin/buy_leg_premium/total |
| `roi_pct` | `float64\|null` | `100 × net_pnl / margin_at_entry`. Phase-5 ranking depends on this — absolute P&L is misleading when margins differ across strategies |
| `notional_at_entry` | `float64` | underlying spot × total lot exposure (added by sweeper, not the kernel) |
| `entry_spot` | `float64` | spot close on entry_date (added by sweeper) |
| `exit_spot` | `float64` | spot close on exit_date (added by sweeper) |

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
    """Return the date that is n trading days BEFORE anchor (n>=0).

    Anchor semantics — pinned per Phase-1.5 design:
      - If `anchor` IS a trading day, n=0 returns `anchor` itself.
      - If `anchor` is NOT a trading day (weekend or NSE holiday), n=0
        returns the most recent trading day STRICTLY before `anchor`
        (round-down). Backtests anchored on monthly expiries are always
        anchored on a trading day so this branch rarely fires in
        practice, but the rule is unambiguous.
      - n=1 returns "one trading day before anchor" (which is the same
        as the previous trading day, regardless of whether anchor itself
        is a trading day) — and so on.
      - n < 0 raises ValueError; "trading days after" is a separate API.
      - If NSE history doesn't go back far enough to satisfy `n`,
        raises ValueError.

    Bootstrap source: `load_spot(CALENDAR_SYMBOL, ...)` (RELIANCE per
    SPECS §6). Cross-validated against `jugaad_data.holidays` in tests
    — any date returned by `trading_days` that's also in `holidays()`
    is a bug somewhere upstream."""

# src/universe/blue_chip.py
def blue_chip(as_of: date) -> list[str]:
    """Sorted list of blue-chip symbols as of the given date. v1 returns
    a single 2024-07-01 snapshot regardless of as_of; see SPECS §6b."""

# src/universe/momentum.py
def classify_momentum(
    as_of: date,
    universe: list[str],
    *,
    lookback_trading_days: int = 126,
    today_fn: Callable[[], date] = date.today,
    offline: bool = False,
) -> dict[str, list[str]]:
    """Returns {"bullish": [...], "neutral": [...], "non_bullish": [...]}.
    Each list sorted alphabetically. Tercile split (top-heavy for n=40:
    bullish=14, neutral=13, non_bullish=13). Lookback in *trading days*
    via offset_trading_days to dodge the calendar-month holiday trap.
    Delisted symbols dropped with a warning. See SPECS §6b.2."""

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

## 3a. Trade / P&L sign convention (frozen)

A trade is a bundle of legs. Each leg has a `side` ∈ {`"SELL"`, `"BUY"`}.
The per-leg gross P&L is:

```python
side_sign = +1 if side == "SELL" else -1   # SELL profits from price falls
gross_pnl_per_leg = (entry_price - exit_price) * side_sign * qty_lots * lot_size
```

A short straddle has two SELL legs (one CE, one PE) so `side_sign = +1`
for both — if the option premiums fall to expiry, both entry > exit and
P&L is positive (the seller keeps the decayed premium).

Aggregate trade P&L:
```
gross_pnl = sum(gross_pnl_per_leg over all legs)
net_pnl = gross_pnl - costs  # costs always positive — see §4
```

**This sign convention is load-bearing.** A single sign flip in the
engine inverts every backtest result by 100%. The Phase-3.2 P&L test
exercises a SELL leg with `entry > exit` and asserts `gross_pnl > 0`.

## 3b. No-look-ahead enforcement (frozen)

PLAN.md §4 hard rule #1 implemented at the engine layer: the trade
pricing kernel for entry/exit dates `e, x` (with `e <= x`) MUST NOT
consult any market data with `date > x`. Specifically:

- `load_spot(symbol, entry_date, exit_date)` — fine; `to_date <= x`.
- `load_option(..., from_date=entry_date, to_date=exit_date)` — fine.
- Anything that even *could* read past `exit_date` is rejected at the
  engine boundary with a `LookaheadError` (new entry in §8).

Tests exercise the rule by constructing a fixture whose spot/option
frames contain rows post-`exit_date`, monkeypatching the loaders to
return them, and asserting the engine raises rather than silently
including them.

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

## 4a. Margin model (Indian options-specific, frozen)

Margin is **capital that must be deposited as collateral** while a
position is open. Distinct from costs (frictional outflows). The trade's
P&L is *unrelated* to margin; ROI = `net_pnl / margin_at_entry` is
how cross-strategy comparison happens (Phase 5 ranking depends on this).

NSE F&O rules drive the asymmetry between BUY and SELL legs:

- **BUY leg** (long option): pay the full premium upfront. That premium
  IS the max possible loss, and serves as the margin. No additional
  block. `margin_per_buy_leg = entry_premium × qty_lots × lot_size`.
- **SELL leg** (short option, naked): receive the premium as credit
  but block **SPAN + Exposure margin** because losses are theoretically
  unlimited. Real SPAN math depends on volatility + NSE's daily SPAN
  file; we approximate with a constant fraction of underlying notional.
  `margin_per_sell_leg ≈ SPAN_PCT × strike × qty_lots × lot_size`
  where `SPAN_PCT ≈ 0.20` (covers SPAN ~13-18% + Exposure ~3-5%).

For multi-leg strategies (short straddle, iron condor, ...) real SPAN
benefits from the partial offset between legs — a true short straddle
margin is LESS than the sum of two naked-short margins because one
leg's gain caps the other's loss. **Our v1 approximation sums per-leg
margins**, which is **conservative** (overstates margin slightly,
making backtests look slightly worse than real, which is the
safer direction for a paper-trade-then-live-trade pipeline).

`MARGIN_MODEL_V1`:

| concept | rule |
|---|---|
| BUY leg | `entry_premium × qty × lot_size` (max loss = premium paid) |
| SELL leg | `0.20 × strike × qty × lot_size` (SPAN + Exposure approx.) |
| trade total | sum of per-leg margins (conservative for multi-leg) |

**Calibration hand-check**: RELIANCE 2600 short straddle, lot 250, 1 lot
each side → SELL CE: `0.20 × 2600 × 250 = ₹1,30,000`. SELL PE: same
₹1,30,000. Sum = **₹2,60,000**. Real broker block for this position
is typically ₹1.4–1.7L (one-leg-offset benefit applies in SPAN),
so our ₹2.6L approximation is ~1.6× generous. Acceptable for v1.

**Margin estimation tiers (v1 ships Tier B):**

Real NSE SPAN requires their daily SPAN file, archived only for the
recent day-or-two. For *backtesting* historical dates, SPAN files are
not available, so any margin number is approximate. Three tiers of
approximation, each more accurate than the last:

- **Tier A** — sum of per-leg (20% × strike × shares). v1 starting point.
- **Tier B** ← *current v1*. Adds (1) `strategy_offset_pct` reducing
  multi-leg margin per the strategy's real SPAN offset benefit (short
  straddle 0.60, short strangle 0.70, iron condor 0.35, naked 1.0,
  long-only 1.0), and (2) `symbol_margin_pct` derived from each
  symbol's 6-month realized volatility via `src/engine/vol.py`. Both
  optional kwargs to `MarginModelV1.estimate` — defaults preserve
  Tier-A behavior so existing callers don't break.
- **Tier C** — parse NSE's `FO-SPAN-END-DAY` file (only available for
  today/yesterday). Reserved for Phase 9 paper trading where today's
  margin is what matters; impossible for historical backtests because
  the files aren't archived.

Tier B brings cross-strategy ranking bias from ~60% to ~10-15% (per
the calibration analysis below). It is the realistic ceiling for
backtest accuracy; ranking conclusions are sound.

`symbol_margin_pct` formula (in `src/engine/vol.py`):
  `margin_pct = clamp(0.10 + 0.40 × annualized_vol, 0.10, 0.30)`
  Calibration: HDFCBANK ~15% vol → 16% margin (real: ~14%);
  RELIANCE ~22% vol → 19% margin (real: ~16%);
  ADANIENT ~35% vol → 24% margin (real: ~22%).

**Known v1 simplifications (cross-strategy ranking caveats — operators must understand these before drawing conclusions from Phase 5 results):**

1. **Strike-based, not spot-based.** Real SPAN derives margin from
   worst-case spot moves applied to the contract, so the natural
   basis is `spot_at_entry`, not `strike`. v1 uses `strike` for
   reproducibility (strike is contract-invariant; spot fluctuates).
   For symmetric short-vol strategies (short straddle, symmetric
   strangle) the strike-vs-spot divergence partially cancels because
   put-strike < spot < call-strike. For asymmetric strategies
   (single-leg shorts, asymmetric wings, iron condors with uneven
   wings) the bias is material (~20-25% off in either direction
   depending on strike-vs-spot offset). Phase 4 multi-strategy may
   revisit by passing `spot_at_entry` into margin estimation.

2. **`roi_pct` is HOLDING-PERIOD return, not annualized.** A 30-day
   trade looks ~6× better than a 5-day trade at the same daily rate.
   Phase-5 ranking should normalize via `roi_pct_annualized ≈
   roi_pct × 252 / hold_trading_days` when comparing strategies with
   different (entry_offset, exit_offset) windows.

3. **Uniform 20% across symbols.** Real SPAN varies by underlying
   volatility — low-vol HDFCBANK ≈ 14%, high-vol ADANIENT ≈ 25%.
   v1's uniform 0.20 makes high-vol stocks look more profitable than
   real (margin understated) and low-vol stocks look less profitable
   (margin overstated). Phase-7 SPAN-file parsing eliminates the
   bias; until then any cross-symbol ranking should be read with
   "rankings rotate by symbol vol" in mind.

4. **Multi-leg conservatism asymmetry.** Real SPAN gives a big
   offset credit for short straddles (real-margin ≈ 60% of
   sum-of-legs) and a small credit for calendar spreads
   (real-margin ≈ 90% of sum-of-legs). Ranking via v1 will silently
   favor calendar-style strategies because their margin estimate is
   closer to real, while short straddle's is ~60% over. Phase-5 UI
   must surface this caveat alongside any ROI-based ranking.

Phase 7 backlog: parse NSE's daily SPAN file for accurate margin.
Until then, `MARGIN_MODEL_V1` is what every backtest uses, and the
four caveats above are baked into the engine's documentation so no
downstream consumer can claim ignorance.

## 4b. Slippage model (frozen)

Bid-ask spread on NSE blue-chip options is ~1-2% of premium. Backtesting
at the daily close (which is the LAST traded price, not where bids/asks
sat) systematically over-promises: you don't actually transact at close.

Slippage MOVES the price *against you* regardless of direction:

  - When you BUY (opening long or closing short): you pay UP — close × (1 + slippage_pct)
  - When you SELL (opening short or closing long): you receive DOWN — close × (1 − slippage_pct)

So for our canonical short straddle (SELL CE + SELL PE; close = BUY both):

  - entry CE (SELL): realized = close × (1 − pct) (less premium received)
  - exit  CE (BUY):  realized = close × (1 + pct) (more premium paid to close)
  - same for PE

Net effect on gross P&L is *asymmetric in the right direction*:
- Winning trades shrink slightly (entry credit smaller, exit debit larger)
- Losing trades shrink MORE (same effect, but on a bigger loss base)

This is the "asymmetric conservatism" the user asked about. Margin
overstate alone is symmetric (smaller wins AND smaller losses in %), so
it can't deliver this — slippage can.

`SlippageModelV1`:

| param | default | meaning |
|---|---|---|
| `slippage_pct` | 0.01 (1% per side) | Realistic for NSE blue-chip options. Thinner names should override upward. |

Per-leg realized-price formula:

```python
side_at_open  = leg.side                                 # SELL or BUY
side_at_close = {"SELL": "BUY", "BUY": "SELL"}[leg.side]
entry_realized = entry_close × (1 - pct if side_at_open  == "SELL" else 1 + pct)
exit_realized  = exit_close  × (1 - pct if side_at_close == "SELL" else 1 + pct)
```

Then `gross_pnl_per_leg = (entry_realized − exit_realized) × side_sign × qty × lot_size`.

The engine emits both `entry_px` (raw close — what the data layer
returned) and `entry_px_realized` (post-slippage — what the engine
actually transacts at). `gross_pnl` uses realized. Audit trail intact.

**Calibration**: For our canonical RELIANCE Jan-2024 short straddle
at 1% slippage, the realized P&L drops from +₹910 (no slippage) to
~+₹430 (with). The ~₹500 haircut matches the SPECS-§4 + bid-ask-spread
real-world experience for NSE blue-chip options at 0.5-1.5% wide.

Phase-7 backlog: per-symbol slippage (high-vol/thin-liquidity names get
higher pct). Until then SLIPPAGE_MODEL_V1's uniform 1% is the v1 default.

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

Every public loader (`load_spot`, `load_bhavcopy_fo`, `load_option`, `monthly_expiries`, `trading_days`, `offset_trading_days`) accepts an optional `offline: bool = False` keyword. When True (or env `MORENSE_OFFLINE=1`), a cache miss raises **`OfflineCacheMiss`** (NOT `MissingDataError`) and never touches the network.

**Why a distinct class.** Phase 1.3.2's `expiry_calendar` catches `MissingDataError` to skip candidate non-trading days. If offline-mode raised `MissingDataError`, every sampled day on a cold cache would be silently treated as "non-trading" and the calendar would return `[]` with no signal. `OfflineCacheMiss` is a separate `DataError` subclass — `expiry_calendar`'s `except MissingDataError:` block ignores it, so offline + cold cache propagates loudly.

`offline=True` AND `force_refresh=True` are contradictory; **offline takes precedence**. For an open-expiry contract whose cache is stale relative to today, offline returns the stale cache rather than raising (still valid data, just not up-to-the-minute).

## 6b. Universe selection (Phase 2)

### 6b.1 Blue-chip (v1)

Single hardcoded list: **40 large-cap NSE names** derived from the
~2024-07-01 Nifty 50 snapshot, with the 10 lower-options-liquidity
members trimmed. Source citation embedded in
`src/universe/blue_chip.py`. Sized down from 50→40 per change-log
2026-05-24 — exact composition is a v1 shortcut, the reporting and
analysis quality is what matters.

The `as_of: date` argument to every universe function exists for
*future-proofing* — v1 returns the same list regardless of `as_of`,
but the parameter is required so backtests record "the list was
evaluated as-of 2024-07-01" even when run later.

### 6b.2 Momentum (v1)

`classify_momentum(as_of, universe, *, lookback_trading_days=126, today_fn=date.today, offline=False) -> dict`:

  - **Lookback expressed in trading days, not calendar months.** Default
    126 ≈ 6 calendar months × 21 trading days. This sidesteps the
    "lookback date lands on a NSE holiday → load_spot returns 0 rows →
    divide-by-zero" trap that a naive `as_of - 6 months` produces.
    Implementation: `lookback_date = offset_trading_days(as_of, lookback_trading_days)`.
  - **Anchor close.** The two closes for the return calculation come
    from `load_spot(symbol, lookback_date, as_of)`; we pick the row
    with the largest date ≤ `as_of` for the numerator and the row with
    the smallest date ≥ `lookback_date` for the denominator. Both are
    trading-day rows by construction.
  - **Trailing return**: `(close_at_as_of - close_at_lookback) / close_at_lookback`.
  - **Tercile split** (n = len(universe), e.g. 40):
    - bullish  = top `ceil(n/3)` by return descending (40 → 14)
    - non_bullish = bottom `floor(n/3)` (40 → 13)
    - neutral = the middle remainder (40 → 13)
    The top-heavy convention gives the higher-conviction bucket the
    larger sample. Ties broken by symbol-name ascending.
  - **Output**: `{"bullish": [...], "neutral": [...], "non_bullish": [...]}`,
    each list sorted alphabetically for determinism.
  - **Delisted / renamed symbols** (LOAD-BEARING): if `load_spot` raises
    `MissingDataError` for a universe symbol, the classifier **drops it
    with a `warnings.warn(...)` naming the symbol** and proceeds with
    the remaining universe. One stale name in `blue_chip` must not
    break the whole classifier. `OfflineCacheMiss` is NOT swallowed
    (per the SPECS §6a distinct-class rule) — propagates.

### 6b.3 SURVIVORSHIP BIAS (load-bearing caveat)

v1's blue-chip list is **2024-07-01 Nifty 50**. Running a backtest
against this list on 2019 prices means you've selected stocks that
*survived to 2024-07-01*. Stocks that were Nifty 50 in 2019 and got
dropped (e.g. underperformers, mergers, delistings) are absent. Returns
will look better than reality.

**Mitigations**:
1. Every UI rendering of universe-rooted backtest results MUST display
   a "Survivorship-bias note" disclaimer (Phase 5/6 plumbing).
2. Phase 7 backlog item: replace v1's single snapshot with
   `BLUE_CHIP_BY_QUARTER: dict[date, list[str]]` so backtests use the
   correct membership *as of each backtest period*.
3. Documenting this in §6b.3 itself so the limitation is impossible to
   miss when reviewing the universe layer.

### 6b.4 Cache

Universe membership is pure-Python data (no NSE fetch). Momentum
classifier uses `load_spot` for prices and inherits its parquet cache;
the classifier's per-call computation runs in <100ms on a warm cache.

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
class LookaheadError(DataError): ...              # engine consulted data past exit_date
class StrategyConfigError(ValueError): ...        # bad params dict
```

The engine prefers loud failure over silent fallback. The sweeper catches `DataError` and records skip-reason; uncaught exceptions are bugs.

## 9. Testing conventions

- `pytest` with `tests/` at repo root.
- Network-touching tests are marked `@pytest.mark.network` and skipped by default; run via `pytest -m network`.
- Fixture parquets in `tests/fixtures/` are tiny (≤ 50 rows) and committed to git.
- Determinism: `tests/test_engine.py::test_byte_identical_reruns` hashes the result parquet.
