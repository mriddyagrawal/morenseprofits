# morenseprofits

Personal NSE options-strategy backtesting & research platform. Read [PLAN.md](PLAN.md) and [SPECS.md](SPECS.md) before contributing.

## Quickstart

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/smoke_test.py     # verifies jugaad-data + cache works
```

## Status

Phase 0 (scaffolding) in progress. See PLAN.md §3 for phase tracking.

## How it works (one paragraph)

We pull NSE historical EOD spot and options data via [`jugaad-data`](https://github.com/jugaad-py/jugaad-data), cache it to disk as parquet, then run parameter sweeps across multiple option strategies (short straddle, long straddle, strangles, iron condor, ...) on a curated universe of stocks. The sweep produces a results table that the Streamlit app turns into bar charts, trend lines, and rankings. Everything is deterministic and reproducible; nothing is run in production / live trading.
