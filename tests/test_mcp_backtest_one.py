"""Tests for src.mcp.backtest_one — feat(p8.mcp.backtest_one).

Strategy: tests monkeypatch the underlying loaders (load_spot,
load_option) and the strategy registry to avoid needing real cache
state. Pricing logic still runs through the actual price_trade path
so the integration with the engine is exercised end-to-end.
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from src.data.errors import IlliquidLegError, OfflineCacheMiss
from src.mcp import backtest_one as bt_module
from src.mcp.backtest_one import (
    BacktestOneInput,
    BacktestOneOutput,
    _classify_fill_source,
    backtest_one_impl,
    register_backtest_one_tools,
)


# ============================================================
# _classify_fill_source — mirrors dashboard helper
# ============================================================

def test_classify_fill_source_vwap_match():
    # turnover 10 lakhs × 100_000 / 50_000 volume = 20.0 = entry_px
    assert _classify_fill_source(20.0, 50000, 10.0) == "vwap"


def test_classify_fill_source_close_when_turnover_missing():
    assert _classify_fill_source(100.0, 1000, None) == "close"


def test_classify_fill_source_close_when_volume_zero():
    assert _classify_fill_source(100.0, 0, 5.0) == "close"


def test_classify_fill_source_close_when_divergent():
    # turnover/volume gives VWAP=20 but entry_px=100 → engine used close
    assert _classify_fill_source(100.0, 50000, 10.0) == "close"


def test_classify_fill_source_unknown_for_none_or_nan():
    assert _classify_fill_source(None, 1000, 5.0) == "unknown"
    assert _classify_fill_source(float("nan"), 1000, 5.0) == "unknown"


# ============================================================
# backtest_one — failure modes (LOAD-BEARING: every failure surfaces
# as gate_status rather than raising)
# ============================================================

def test_backtest_one_unknown_strategy_raises_value_error():
    with pytest.raises(ValueError, match="not registered"):
        backtest_one_impl(BacktestOneInput(
            strategy="not_a_real_strategy",
            symbol="X", expiry=date(2024, 1, 25),
            entry_date=date(2024, 1, 4), exit_date=date(2024, 1, 24),
        ))


def test_backtest_one_spot_cache_miss_surfaces_as_gate_status(monkeypatch):
    """LOAD-BEARING: spot cache missing should surface as
    gate_status='OfflineCacheMiss' rather than crashing the tool."""
    def raise_miss(*a, **kw):
        raise OfflineCacheMiss("no spot for RELIANCE 2024")
    monkeypatch.setattr(bt_module, "load_spot", raise_miss)
    out = backtest_one_impl(BacktestOneInput(
        strategy="short_straddle",
        symbol="RELIANCE", expiry=date(2024, 1, 25),
        entry_date=date(2024, 1, 4), exit_date=date(2024, 1, 24),
    ))
    assert out.gate_status == "OfflineCacheMiss"
    assert out.spot_at_entry is None
    assert any("prefetch" in c.lower() for c in out.caveats)


def test_backtest_one_empty_spot_frame_surfaces_missing_spot(monkeypatch):
    """If spot loader returns an empty frame (non-trading day), the
    tool returns gate_status='MissingSpot' with a caveat naming the
    likely cause."""
    monkeypatch.setattr(
        bt_module, "load_spot",
        lambda *a, **kw: pd.DataFrame(columns=["date", "close"]),
    )
    out = backtest_one_impl(BacktestOneInput(
        strategy="short_straddle",
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=date(2024, 1, 6),  # Saturday
        exit_date=date(2024, 1, 24),
    ))
    assert out.gate_status == "MissingSpot"
    assert any("trading day" in c.lower() for c in out.caveats)


# ============================================================
# backtest_one — successful pricing path
# ============================================================

def test_backtest_one_priced_trade_returns_full_breakdown(monkeypatch):
    """Successful pricing path: monkeypatch spot + load_option to
    return canned data, run backtest_one_impl, verify the full
    LegBreakdown is populated with VWAP fill-source classification."""
    # 1. Spot.
    monkeypatch.setattr(
        bt_module, "load_spot",
        lambda *a, **kw: pd.DataFrame({
            "date": pd.to_datetime([date(2024, 1, 4)]),
            "close": [2600.0],
        }),
    )

    # 2. Strategy's load_available_strikes for ATM picking. Use
    # short_straddle and provide a strike grid that contains 2600.
    import src.strategies._strikes as strikes_mod
    monkeypatch.setattr(
        strikes_mod, "load_available_strikes",
        lambda *a, **kw: [2400, 2500, 2600, 2700, 2800],
    )

    # 3. Option loader: return a frame with entry + exit rows where
    # close, volume, oi, turnover are all set and entry_px equals
    # turnover * 100_000 / volume so the classifier returns 'vwap'.
    entry_dt = date(2024, 1, 4)
    exit_dt = date(2024, 1, 24)
    def fake_load_option(symbol, expiry, strike, option_type,
                         from_date, to_date, **kw):
        # close=100 per share, volume=10_000 shares, turnover=10 lakhs
        # → vwap_implied = 10 × 100_000 / 10_000 = 100.0. entry_px=100
        # exit: close=20, volume=8_000, turnover=1.6 lakhs
        # → vwap_implied = 1.6 × 100_000 / 8_000 = 20.0. exit_px=20
        return pd.DataFrame({
            "date": pd.to_datetime([entry_dt, exit_dt]),
            "open": [99.0, 19.0],
            "high": [105.0, 22.0],
            "low": [95.0, 18.0],
            "close": [100.0, 20.0],
            "ltp": [100.0, 20.0],
            "settle_price": [100.0, 20.0],
            "lot_size": [250, 250],
            "volume": [10000, 8000],
            "oi": [pd.NA, pd.NA],
            "turnover": [10.0, 1.6],
        })
    # Patch options_loader.load_option at the module the engine uses.
    import src.engine.pnl as pnl_mod
    monkeypatch.setattr(pnl_mod.options_loader, "load_option", fake_load_option)

    # 4. Run.
    out = backtest_one_impl(BacktestOneInput(
        strategy="short_straddle",
        symbol="RELIANCE",
        expiry=date(2024, 1, 25),
        entry_date=entry_dt,
        exit_date=exit_dt,
    ))

    assert out.gate_status == "priced"
    assert out.spot_at_entry == 2600.0
    # Short straddle: SELL ATM CE + SELL ATM PE; both legs decay.
    assert out.gross_pnl is not None
    assert len(out.legs) == 2
    # Both legs entry @100, exit @20. VWAP implied matches entry_px.
    for leg in out.legs:
        assert leg.entry_px == 100.0
        assert leg.exit_px == 20.0
        assert leg.entry_fill_source == "vwap"
        assert leg.exit_fill_source == "vwap"
        assert leg.strike == 2600.0


# ============================================================
# Registry assembly
# ============================================================

def test_register_backtest_one_tools_returns_one_entry():
    entries = register_backtest_one_tools()
    assert len(entries) == 1
    assert entries[0].name == "backtest_one"


def test_server_registry_now_exposes_backtest_one():
    from src.mcp.server import _collect_tool_entries
    registry = _collect_tool_entries()
    assert "backtest_one" in registry
    # 11 tools total now (3 universe + 3 spot_options + 4 sweep_query +
    # 1 backtest_one).
    assert len(registry) >= 11


# ============================================================
# JSON round-trip
# ============================================================

def test_backtest_one_output_round_trips_through_json(monkeypatch):
    """The empty-cell (failure-mode) output must serialize through
    model_dump(mode='json') cleanly so consumer Claude can decode it."""
    def raise_miss(*a, **kw):
        raise OfflineCacheMiss("missing")
    monkeypatch.setattr(bt_module, "load_spot", raise_miss)
    out = backtest_one_impl(BacktestOneInput(
        strategy="short_straddle",
        symbol="X", expiry=date(2024, 1, 25),
        entry_date=date(2024, 1, 4), exit_date=date(2024, 1, 24),
    ))
    payload = json.dumps(out.model_dump(mode="json"))
    back = json.loads(payload)
    assert back["gate_status"] == "OfflineCacheMiss"
    assert back["legs"] == []
    assert "caveats" in back
