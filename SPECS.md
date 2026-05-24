# SPECS — Data schemas, interfaces, conventions

Companion to PLAN.md. PLAN says *what* and *why*; SPECS pins down *exactly how*. Anything code-level that future commits will rely on lives here so reviewer + builder agree on contracts.

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

### 2.1 Spot — `data/cache/spot/{SYMBOL}/{YEAR}.parquet`
Columns (subset of jugaad `stock_df`, normalized):
| col | dtype | notes |
|---|---|---|
| `date` | `datetime64[ns]` | trading date, naive IST, midnight |
| `symbol` | `string` | uppercase |
| `series` | `string` | always `"EQ"` for v1 |
| `open`, `high`, `low`, `close` | `float64` | INR |
| `vwap` | `float64` | INR |
| `volume` | `int64` | shares |
| `prev_close` | `float64` | INR |

### 2.2 Options — `data/cache/options/{SYMBOL}/{EXPIRY:yyyymmdd}/{STRIKE_INT}-{CE|PE}.parquet`
| col | dtype | notes |
|---|---|---|
| `date` | `datetime64[ns]` | trading date |
| `symbol` | `string` | underlying |
| `expiry` | `date` | contract expiry |
| `strike` | `float64` | INR strike |
| `option_type` | `string` | `CE` or `PE` |
| `open`, `high`, `low`, `close` | `float64` | premium INR |
| `ltp` | `float64` | last traded price |
| `settle_price` | `float64` | NSE daily settlement |
| `lot_size` | `int64` | from `MARKET LOT` |
| `volume` | `int64` | from `TOTAL TRADED QUANTITY` |
| `oi` | `int64` | from `OPEN INTEREST` |
| `oi_change` | `int64` | from `CHANGE IN OI` |

### 2.3 Expiry calendar — `data/cache/expiries/{SYMBOL}.parquet`
| col | dtype |
|---|---|
| `symbol` | `string` |
| `expiry_date` | `date` |
| `month_anchor` | `date` (first calendar day of expiry month) |

### 2.4 Results — `data/results/{strategy}_{run_id}.parquet`
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

## 7. Cache invalidation

- Caches are **append-mostly**. We never overwrite a parquet that contains real historical data unless `--force-refresh` is passed via CLI.
- Schema changes bump a `CACHE_VERSION` constant in `src/data/cache.py`; on bump, the cache directory is moved to `data/cache.v{N-1}/` (manual cleanup, never automatic deletion).

## 8. Error taxonomy

```python
class DataError(Exception): ...
class MissingDataError(DataError): ...            # leg/spot missing for required date
class NoLiquidStrikeError(DataError): ...         # no strikes traded on entry_date
class CacheCorruptError(DataError): ...
class StrategyConfigError(ValueError): ...        # bad params dict
```

The engine prefers loud failure over silent fallback. The sweeper catches `DataError` and records skip-reason; uncaught exceptions are bugs.

## 9. Testing conventions

- `pytest` with `tests/` at repo root.
- Network-touching tests are marked `@pytest.mark.network` and skipped by default; run via `pytest -m network`.
- Fixture parquets in `tests/fixtures/` are tiny (≤ 50 rows) and committed to git.
- Determinism: `tests/test_engine.py::test_byte_identical_reruns` hashes the result parquet.
