"""Tests for src.mcp.spot_options — feat(p8.mcp.spot_options).

Layered coverage mirrors test_mcp_universe.py:
  - Schema layer: input/output models reject malformed payloads.
  - Behavior layer: each tool returns the right rows / caveats.
  - Registry layer: sub-arc returns 3 entries with no collisions.
  - JSON round-trip: dispatcher-path serialization preserves dates.

Strategy: tests inject in-memory frames via monkeypatching the
underlying loaders (load_spot, load_option, load_bhavcopy_fo). This
avoids depending on operator cache state and keeps the test surface
deterministic.
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest
from pydantic import ValidationError

from src.data.errors import OfflineCacheMiss
from src.mcp import spot_options
from src.mcp.spot_options import (
    GetOptionSeriesInput,
    GetOptionsChainInput,
    GetSpotSeriesInput,
    get_option_series_impl,
    get_options_chain_impl,
    get_spot_series_impl,
    register_spot_options_tools,
)


# ============================================================
# get_spot_series
# ============================================================

def _spot_frame(dates_and_closes: list[tuple[date, float]]) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.to_datetime([d for d, _ in dates_and_closes]),
        "open": [c - 1 for _, c in dates_and_closes],
        "high": [c + 2 for _, c in dates_and_closes],
        "low": [c - 2 for _, c in dates_and_closes],
        "close": [c for _, c in dates_and_closes],
        "volume": [1000 for _ in dates_and_closes],
    })


def test_get_spot_series_returns_rows_in_window(monkeypatch):
    """Happy path: loader returns a 3-row frame; the impl wraps each
    row in a SpotRow with date converted from Timestamp."""
    frame = _spot_frame([
        (date(2024, 1, 2), 100.0),
        (date(2024, 1, 3), 102.0),
        (date(2024, 1, 4), 101.0),
    ])
    monkeypatch.setattr(spot_options, "load_spot",
                        lambda *a, **kw: frame)
    out = get_spot_series_impl(GetSpotSeriesInput(
        symbol="RELIANCE", from_date=date(2024, 1, 1), to_date=date(2024, 1, 31),
    ))
    assert out.n_rows == 3
    assert out.rows[0].close == 100.0
    assert out.rows[0].date == date(2024, 1, 2)
    # Symbol uppercased.
    assert out.symbol == "RELIANCE"
    # Raw lookup → empty caveats.
    assert out.caveats == []


def test_get_spot_series_uppercases_symbol(monkeypatch):
    monkeypatch.setattr(spot_options, "load_spot", lambda *a, **kw: _spot_frame([(date(2024, 1, 2), 100.0)]))
    out = get_spot_series_impl(GetSpotSeriesInput(
        symbol="reliance", from_date=date(2024, 1, 1), to_date=date(2024, 1, 31),
    ))
    assert out.symbol == "RELIANCE"


def test_get_spot_series_caps_rows_at_max_and_caveats(monkeypatch):
    """When the loader returns >MAX_ROWS_PER_RESPONSE rows, the impl
    truncates AND surfaces an explicit caveat so the consumer Claude
    can't accidentally treat the partial frame as complete."""
    rows = [(date(2020, 1, 1) + pd.Timedelta(days=i).to_pytimedelta(),
             100.0 + i * 0.01)
            for i in range(spot_options.MAX_ROWS_PER_RESPONSE + 50)]
    frame = _spot_frame(rows)
    monkeypatch.setattr(spot_options, "load_spot", lambda *a, **kw: frame)
    out = get_spot_series_impl(GetSpotSeriesInput(
        symbol="X", from_date=date(2020, 1, 1), to_date=date(2030, 1, 1),
    ))
    assert out.n_rows == spot_options.MAX_ROWS_PER_RESPONSE
    assert any("truncated" in c.lower() for c in out.caveats)


def test_get_spot_series_propagates_offline_cache_miss(monkeypatch):
    """``offline=True`` is forced inside the impl; a cache miss raises
    OfflineCacheMiss. The MCP layer doesn't swallow it — surfaces to
    the consumer as a tool-error response."""
    def raise_miss(*a, **kw):
        raise OfflineCacheMiss("no spot for X")
    monkeypatch.setattr(spot_options, "load_spot", raise_miss)
    with pytest.raises(OfflineCacheMiss):
        get_spot_series_impl(GetSpotSeriesInput(
            symbol="X", from_date=date(2024, 1, 1), to_date=date(2024, 1, 31),
        ))


# ============================================================
# get_option_series
# ============================================================

def _option_frame(rows: list[dict], *, with_turnover: bool = True) -> pd.DataFrame:
    """Build a §2.2-shaped option frame. ``with_turnover=False`` simulates
    a legacy parquet from before the p7.pricing_arc ingest fix."""
    base = {
        "date": pd.to_datetime([r["date"] for r in rows]),
        "open": [r.get("open", 0.0) for r in rows],
        "high": [r.get("high", 0.0) for r in rows],
        "low": [r.get("low", 0.0) for r in rows],
        "close": [r["close"] for r in rows],
        "ltp": [r.get("ltp") for r in rows],
        "settle_price": [r.get("settle_price") for r in rows],
        "lot_size": [r.get("lot_size", 250) for r in rows],
        "volume": [r.get("volume", 1000) for r in rows],
        "oi": [r.get("oi", 500) for r in rows],
    }
    if with_turnover:
        base["turnover"] = [r.get("turnover", 1.0) for r in rows]
    return pd.DataFrame(base)


def test_get_option_series_carries_turnover_when_present(monkeypatch):
    frame = _option_frame([
        {"date": date(2024, 1, 5), "close": 100.0, "turnover": 12.5},
        {"date": date(2024, 1, 6), "close": 95.0, "turnover": 9.8},
    ], with_turnover=True)
    monkeypatch.setattr(spot_options, "load_option", lambda *a, **kw: frame)
    out = get_option_series_impl(GetOptionSeriesInput(
        symbol="RELIANCE", expiry=date(2024, 1, 25),
        strike=2600.0, option_type="CE",
    ))
    assert out.n_rows == 2
    assert out.rows[0].turnover == 12.5
    assert out.rows[1].turnover == 9.8
    # No pre-pricing-arc caveat since turnover is present.
    assert not any("pre-pricing" in c.lower() or "pre-arc" in c.lower() for c in out.caveats)


def test_get_option_series_carries_pre_arc_caveat_when_turnover_absent(monkeypatch):
    """LOAD-BEARING: legacy parquets cached before the p7.pricing_arc
    don't have a turnover column. The MCP tool surfaces an explicit
    caveat so the consumer Claude can't accidentally try to compute
    VWAP from incomplete data."""
    frame = _option_frame([
        {"date": date(2024, 1, 5), "close": 100.0},
        {"date": date(2024, 1, 6), "close": 95.0},
    ], with_turnover=False)
    monkeypatch.setattr(spot_options, "load_option", lambda *a, **kw: frame)
    out = get_option_series_impl(GetOptionSeriesInput(
        symbol="X", expiry=date(2024, 1, 25), strike=100.0, option_type="CE",
    ))
    assert any("p7.pricing_arc" in c or "vwap" in c.lower() for c in out.caveats)


def test_get_option_series_input_rejects_bad_option_type():
    """Literal['CE','PE'] catches typos at the schema layer."""
    with pytest.raises(ValidationError):
        GetOptionSeriesInput(
            symbol="X", expiry=date(2024, 1, 25),
            strike=100.0, option_type="XX",  # type: ignore[arg-type]
        )


def test_get_option_series_default_window_is_expiry_minus_120_days(monkeypatch):
    """When from_date / to_date are omitted, the impl defaults to the
    contract's typical full lifetime (expiry - 120d → expiry)."""
    captured: dict = {}

    def capture(*a, **kw):
        captured["from"] = a[4]
        captured["to"] = a[5]
        return _option_frame([{"date": date(2024, 1, 5), "close": 100.0, "turnover": 1.0}])

    monkeypatch.setattr(spot_options, "load_option", capture)
    expiry = date(2024, 1, 25)
    get_option_series_impl(GetOptionSeriesInput(
        symbol="X", expiry=expiry, strike=100.0, option_type="CE",
    ))
    from datetime import timedelta
    assert captured["from"] == expiry - timedelta(days=120)
    assert captured["to"] == expiry


# ============================================================
# get_options_chain
# ============================================================

def _bhavcopy_frame(symbol: str, expiry: date, strikes_types: list[tuple[float, str, float]]) -> pd.DataFrame:
    """Build a §2.4-ish bhavcopy with OPTSTK rows for the given
    symbol/expiry. ``strikes_types`` is a list of (strike, option_type, close).
    Includes the columns get_options_chain reads."""
    return pd.DataFrame({
        "instrument": ["OPTSTK"] * len(strikes_types),
        "symbol": [symbol] * len(strikes_types),
        "expiry": [pd.Timestamp(expiry)] * len(strikes_types),
        "option_type": [t for _, t, _ in strikes_types],
        "strike": [s for s, _, _ in strikes_types],
        "open": [c - 1 for _, _, c in strikes_types],
        "high": [c + 1 for _, _, c in strikes_types],
        "low": [c - 2 for _, _, c in strikes_types],
        "close": [c for _, _, c in strikes_types],
        "settle_price": [c for _, _, c in strikes_types],
        "contracts": [100 for _ in strikes_types],
        "oi": [1000 for _ in strikes_types],
        "oi_change": [10 for _ in strikes_types],
        "trade_date": [pd.Timestamp(date(2024, 1, 5))] * len(strikes_types),
    })


def test_get_options_chain_filters_by_symbol_and_instrument(monkeypatch):
    """Chain must only return OPTSTK rows for the requested symbol;
    other symbols / futures rows are filtered out."""
    bc = _bhavcopy_frame("RELIANCE", date(2024, 1, 25), [
        (2600.0, "CE", 100.0),
        (2600.0, "PE", 95.0),
        (2700.0, "CE", 50.0),
    ])
    # Inject a foreign symbol row that should be filtered.
    other = _bhavcopy_frame("INFY", date(2024, 1, 25), [(1500.0, "CE", 30.0)])
    full = pd.concat([bc, other], ignore_index=True)
    monkeypatch.setattr(spot_options, "load_bhavcopy_fo", lambda *a, **kw: full)
    out = get_options_chain_impl(GetOptionsChainInput(
        symbol="RELIANCE", on_date=date(2024, 1, 5),
    ))
    assert out.n_rows == 3
    # Sorted by (strike, option_type).
    assert out.rows[0].strike == 2600.0
    assert out.rows[0].option_type == "CE"
    assert out.rows[1].option_type == "PE"


def test_get_options_chain_filters_by_expiry_when_provided(monkeypatch):
    """``expiry`` filter narrows the result to one contract series."""
    frame_jan = _bhavcopy_frame(
        "RELIANCE", date(2024, 1, 25), [(2600.0, "CE", 100.0)],
    )
    frame_feb = _bhavcopy_frame(
        "RELIANCE", date(2024, 2, 29), [(2600.0, "CE", 90.0)],
    )
    combined = pd.concat([frame_jan, frame_feb], ignore_index=True)
    monkeypatch.setattr(
        spot_options, "load_bhavcopy_fo", lambda *args, **kw: combined,
    )
    out = get_options_chain_impl(GetOptionsChainInput(
        symbol="RELIANCE", on_date=date(2024, 1, 5),
        expiry=date(2024, 2, 29),
    ))
    assert out.n_rows == 1
    assert out.rows[0].close == 90.0


# ============================================================
# Registry assembly
# ============================================================

def test_register_spot_options_tools_returns_three_entries():
    """Pin sub-arc 3.2's count at 3."""
    entries = register_spot_options_tools()
    assert len(entries) == 3


def test_register_spot_options_tools_names_match_expected():
    entries = register_spot_options_tools()
    names = {e.name for e in entries}
    assert names == {"get_spot_series", "get_option_series", "get_options_chain"}


def test_register_spot_options_tools_names_unique():
    entries = register_spot_options_tools()
    names = [e.name for e in entries]
    assert len(set(names)) == len(names)


def test_server_assembles_universe_and_spot_options_without_collision():
    """Cross-sub-arc assembly: build_server() concats universe + spot_options
    tool lists; no name collisions allowed. Anti-regression for
    _collect_tool_entries' duplicate-detection."""
    from src.mcp.server import _collect_tool_entries
    registry = _collect_tool_entries()
    # Should include all 6 tools (3 from universe + 3 from spot_options).
    expected = {
        "list_universe", "expiries_for", "list_strategies",
        "get_spot_series", "get_option_series", "get_options_chain",
    }
    assert set(registry.keys()) == expected


# ============================================================
# JSON round-trip
# ============================================================

def test_get_spot_series_output_round_trips_through_json(monkeypatch):
    """call_tool dispatcher's path: ``json.dumps(out.model_dump(mode='json'))``
    must preserve date fields as ISO strings."""
    frame = _spot_frame([(date(2024, 1, 5), 100.0)])
    monkeypatch.setattr(spot_options, "load_spot", lambda *a, **kw: frame)
    out = get_spot_series_impl(GetSpotSeriesInput(
        symbol="X", from_date=date(2024, 1, 1), to_date=date(2024, 1, 31),
    ))
    payload = json.dumps(out.model_dump(mode="json"))
    back = json.loads(payload)
    assert back["rows"][0]["date"] == "2024-01-05"
    assert back["n_rows"] == 1
    assert "caveats" in back
