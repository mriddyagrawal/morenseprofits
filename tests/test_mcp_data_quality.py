"""Tests for src.mcp.data_quality — feat(p8.mcp.data_quality).

Three diagnostic dimensions; tests exercise each. Same fixture pattern
as test_mcp_skip_summary — redirect RESULTS_DIR + write minimal
sweep parquets.
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from src.engine import results as r
from src.mcp._models import PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT
from src.mcp.data_quality import (
    MAX_TRADES_SAMPLED,
    DataQualityInput,
    data_quality_impl,
    register_data_quality_tools,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(autouse=True)
def _redirect_results_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(r, "RESULTS_DIR", tmp_path)


# Sentinel: "_leg(entry_turnover=None)" should explicitly mean "no
# turnover column" (legacy-cache test paths). A separate sentinel is
# needed because the fixture auto-computes turnover from
# (strike + premium) × shares by default (rupees, post-F1 parser-
# normalized convention) — the test author specifies the VWAP they
# want, not raw turnover values. Without this sentinel, "None" would
# mean both "leave it None" and "fill in the default", which the
# no-turnover tests can't disambiguate.
_AUTO = object()


def _leg(
    *, entry_px=20.0, exit_px=5.0,
    entry_volume=50000, exit_volume=40000,
    entry_turnover=_AUTO, exit_turnover=_AUTO,
    strike=2600.0,
) -> dict:
    """Build a synthetic leg dict for tests. Defaults to a healthy VWAP
    fill: ``entry_turnover`` defaults (``_AUTO``) to the value NSE
    would have reported under the (strike + premium) × shares
    convention (rupees, post-F1 — see LOGIC_REVIEW.md F1 + addendum 1)
    that recovers ``entry_px`` exactly (and likewise for exit). Pass
    explicit ``entry_turnover=N`` to override (e.g. divergence tests)
    or ``entry_turnover=None`` to model a legacy-cache leg with no
    turnover at all.

    Pre-F1 tests carried turnover values in lakhs and the engine
    multiplied by 1e5; post-F1 the parsers normalize to rupees and the
    engine multiplies by 1.0. The fixture math moves with the
    convention so test authors continue to specify the VWAP they want,
    not raw turnover."""
    if entry_turnover is _AUTO:
        entry_turnover = (
            (strike + entry_px) * entry_volume
            if entry_volume > 0 else None
        )
    if exit_turnover is _AUTO:
        exit_turnover = (
            (strike + exit_px) * exit_volume
            if exit_volume > 0 else None
        )
    return {
        "option_type": "CE", "strike": strike, "side": "SELL",
        "qty_lots": 1, "lot_size": 250,
        "entry_px": entry_px, "exit_px": exit_px,
        "entry_px_realized": entry_px * 0.99, "exit_px_realized": exit_px * 1.01,
        "entry_volume": entry_volume, "exit_volume": exit_volume,
        "entry_oi": 1000, "exit_oi": 800,
        "entry_turnover": entry_turnover, "exit_turnover": exit_turnover,
        "gross_pnl": (entry_px - exit_px) * 250,
    }


def _trade_row(
    *, strategy="short_straddle", symbol="RELIANCE",
    entry_offset=15, exit_offset=1, roi_pct=1.0,
    legs: list[dict] | None = None,
) -> dict:
    if legs is None:
        legs = [_leg(), _leg()]
    return {
        "run_id": "test",
        "strategy": strategy,
        "symbol": symbol,
        "expiry": pd.Timestamp("2024-01-25"),
        "entry_date": pd.Timestamp("2024-01-04"),
        "exit_date": pd.Timestamp("2024-01-24"),
        "entry_offset_td": entry_offset,
        "exit_offset_td": exit_offset,
        "params_json": "{}",
        "legs_json": json.dumps(legs),
        "gross_pnl": 100.0,
        "costs": 40.0,
        "costs_breakdown_json": "{}",
        "net_pnl": 100.0 * roi_pct,
        "margin_at_entry": 100000.0,
        "margin_breakdown_json": "{}",
        "roi_pct": roi_pct,
        "hold_trading_days": 14,
        "roi_pct_annualized": roi_pct * 18.0,
        "entry_spot": 2600.0,
        "exit_spot": 2650.0,
        "notional_at_entry": 1300000.0,
    }


# ============================================================
# liquidity_by_entry_offset
# ============================================================

def test_data_quality_liquidity_by_entry_offset_bands_match_expected():
    """Two trades each at three entry depths → three bands populated
    with the right counts."""
    rows = []
    # Depth band T-1..T-5 (entry=3): liquid (volume=50_000)
    rows.append(_trade_row(entry_offset=3, roi_pct=0.5))
    # Depth band T-21..T-30 (entry=25): liquid
    rows.append(_trade_row(entry_offset=25, roi_pct=2.0))
    # Depth band T-41..T-45 (entry=42): zero-volume legs
    legs_zero = [_leg(entry_volume=0), _leg(entry_volume=0)]
    rows.append(_trade_row(entry_offset=42, roi_pct=10.0, legs=legs_zero))

    r.write_results(pd.DataFrame(rows), run_id="liq")
    out = data_quality_impl(DataQualityInput(
        run_id="liq", dimension="liquidity_by_entry_offset",
    ))
    bands_by_label = {row["entry_offset_band"]: row for row in out.table}
    # All three bands populated.
    assert "T-01..T-05" in bands_by_label
    assert "T-21..T-30" in bands_by_label
    assert "T-41..T-45" in bands_by_label
    # The deep band's zero-vol fraction should be 1.0 (all 2 legs zero).
    assert bands_by_label["T-41..T-45"]["frac_legs_zero_entry_volume"] == 1.0
    # T-1..T-5 band's zero-vol fraction should be 0.0.
    assert bands_by_label["T-01..T-05"]["frac_legs_zero_entry_volume"] == 0.0
    # Summary mentions the 2026-05-30 baseline comparison
    assert "phantom-fill" in out.summary.lower() or "10.9" in out.summary or "T-41" in out.summary


def test_data_quality_liquidity_counts_all_expiries_per_cell():
    """LOAD-BEARING regression test per reviewer Grill #1 on 22104df.
    Pre-fix the impl deduplicated by (eot, xot, symbol, strategy)
    WITHOUT expiry, collapsing all expiries into ONE row. n_trades
    under-counted by a factor of len(expiries) and mean_roi was the
    FIRST expiry's roi only.

    Test construction: 2 trades with IDENTICAL (eot=15, xot=1,
    symbol=RELIANCE, strategy=short_straddle) but DIFFERENT expiries.
    n_trades MUST be 2; mean_roi MUST be the mean of both ROIs."""
    rows = [
        _trade_row(entry_offset=3, roi_pct=10.0),
        _trade_row(entry_offset=3, roi_pct=30.0),
    ]
    # Force different expiries so the trades are distinct at the
    # parquet level. (Two identical rows wouldn't actually appear in
    # a real sweep; sweep_grid produces one row per cell-expiry.)
    rows[1]["expiry"] = pd.Timestamp("2024-02-29")
    rows[1]["entry_date"] = pd.Timestamp("2024-02-04")
    rows[1]["exit_date"] = pd.Timestamp("2024-02-28")
    r.write_results(pd.DataFrame(rows), run_id="dedup_test")
    out = data_quality_impl(DataQualityInput(
        run_id="dedup_test", dimension="liquidity_by_entry_offset",
    ))
    bands_by_label = {row["entry_offset_band"]: row for row in out.table}
    # Both trades land in T-01..T-05; n_trades MUST be 2 (not 1).
    assert bands_by_label["T-01..T-05"]["n_trades"] == 2
    # Mean ROI MUST be mean(10, 30) = 20.0 (not just the first row's 10.0)
    assert bands_by_label["T-01..T-05"]["mean_roi_pct"] == pytest.approx(20.0)


def test_data_quality_summary_references_pre_post_arc_comparison():
    rows = [_trade_row(entry_offset=15)]
    r.write_results(pd.DataFrame(rows), run_id="summary")
    out = data_quality_impl(DataQualityInput(
        run_id="summary", dimension="liquidity_by_entry_offset",
    ))
    # Either "post-arc" or "skipped" or "compressed" should appear
    assert any(
        token in out.summary.lower()
        for token in ["post-arc", "skipped", "compressed", "baseline"]
    )


# ============================================================
# theoretical_fallback_rate
# ============================================================

def test_data_quality_theoretical_fallback_rate_separates_symbols():
    """Two symbols, two fill patterns: RELIANCE legs have turnover →
    VWAP path; INFY legs have no turnover → close fallback. Per-symbol
    rates should distinguish them cleanly."""
    rows = []
    # RELIANCE: 2 legs, both with turnover → VWAP (fixture auto-encodes
    # turnover = (strike + entry_px) × shares / 10⁵ so the recovered
    # premium matches entry_px exactly)
    rows.append(_trade_row(symbol="RELIANCE",
                           legs=[_leg(entry_px=20.0, entry_volume=50000)] * 2))
    # INFY: 2 legs, no turnover → close
    rows.append(_trade_row(symbol="INFY",
                           legs=[_leg(entry_px=20.0, entry_volume=50000,
                                       entry_turnover=None)] * 2))
    r.write_results(pd.DataFrame(rows), run_id="fallback")
    out = data_quality_impl(DataQualityInput(
        run_id="fallback", dimension="theoretical_fallback_rate",
    ))
    by_sym = {row["symbol"]: row for row in out.table}
    assert by_sym["RELIANCE"]["vwap_fill_rate_pct"] == 100.0
    assert by_sym["INFY"]["close_fill_rate_pct"] == 100.0
    # Sorted by close_fill_rate DESC → INFY first
    assert out.table[0]["symbol"] == "INFY"


# ============================================================
# vwap_vs_close_divergence
# ============================================================

def test_data_quality_vwap_divergence_only_counts_close_with_turnover():
    """LOAD-BEARING: divergence is only computed for legs that fell
    back to close DESPITE having turnover data (band-reject case).
    Legs that used close because turnover was missing don't have
    measurable divergence."""
    # Build a leg where:
    # - entry_px = 100 (close used by engine)
    # - turnover = 131,000,000 rupees / volume = 50,000, strike = 2600 →
    #   notional/share = 2620 → recovered premium = 20 → band-reject vs entry_px=100
    # - We CAN compute divergence: |20 - 100| / 100 = 80%
    # (Post-F1 rupees convention — pre-F1 this was 1310 lakhs.)
    band_reject_leg = _leg(entry_px=100.0, entry_volume=50000,
                            entry_turnover=131_000_000.0)
    # Build a leg where turnover is missing (no divergence measurable)
    pure_close_leg = _leg(entry_px=100.0, entry_volume=50000,
                           entry_turnover=None)

    rows = [
        _trade_row(symbol="ADANIENT", legs=[band_reject_leg]),
        _trade_row(symbol="INFY", legs=[pure_close_leg]),
    ]
    r.write_results(pd.DataFrame(rows), run_id="div")
    out = data_quality_impl(DataQualityInput(
        run_id="div", dimension="vwap_vs_close_divergence",
    ))
    # Only ADANIENT should appear — INFY has no turnover so divergence
    # can't be measured.
    syms = {row["symbol"] for row in out.table}
    assert "ADANIENT" in syms
    assert "INFY" not in syms
    by_sym = {row["symbol"]: row for row in out.table}
    # Divergence is huge: |20 - 100| / 100 = 80%
    assert by_sym["ADANIENT"]["mean_divergence_pct"] == pytest.approx(80.0, abs=0.5)


def test_data_quality_vwap_divergence_empty_table_when_no_band_rejects():
    """Sweep with no band-rejects → empty table + explicit summary
    explaining what 'no divergence measurable' means.

    Leaving ``entry_turnover`` at the fixture default makes the leg a
    clean VWAP fill (turnover encodes (strike+premium)×shares/10⁵ so
    the recovered premium equals entry_px exactly)."""
    rows = [_trade_row(legs=[_leg(entry_px=20.0, entry_volume=50000)])]
    r.write_results(pd.DataFrame(rows), run_id="no_div")
    out = data_quality_impl(DataQualityInput(
        run_id="no_div", dimension="vwap_vs_close_divergence",
    ))
    assert out.table == []
    assert "no legs" in out.summary.lower() or "no" in out.summary.lower()


# ============================================================
# Sampling
# ============================================================

def test_data_quality_does_not_sample_under_cap():
    rows = [_trade_row() for _ in range(10)]
    r.write_results(pd.DataFrame(rows), run_id="no_sample")
    out = data_quality_impl(DataQualityInput(run_id="no_sample"))
    assert out.n_trades_sampled == 10
    # No sampling caveat
    assert not any("sampled" in c.lower() and "trades" in c.lower()
                    for c in out.caveats)


def test_data_quality_sampling_caveat_fires_when_over_cap(monkeypatch):
    """LOAD-BEARING: sweeps larger than MAX_TRADES_SAMPLED get random-
    sampled with a fixed seed; the caveat names the sample size."""
    # Patch the cap to a small value so we don't have to build 200K rows
    monkeypatch.setattr("src.mcp.data_quality.MAX_TRADES_SAMPLED", 5)
    rows = [_trade_row() for _ in range(10)]
    r.write_results(pd.DataFrame(rows), run_id="sampled")
    out = data_quality_impl(DataQualityInput(run_id="sampled"))
    assert out.n_trades_sampled == 5
    assert any("sampled" in c.lower() for c in out.caveats)


# ============================================================
# Pre-arc caveat
# ============================================================

def test_data_quality_pre_arc_caveat_on_legacy_parquet():
    df = pd.DataFrame([_trade_row()])
    path = r.results_path("legacy_dq")
    path.parent.mkdir(parents=True, exist_ok=True)
    r.canonical_column_order(df).to_parquet(path, index=False)
    out = data_quality_impl(DataQualityInput(run_id="legacy_dq"))
    assert PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT in out.caveats


# ============================================================
# Registry assembly
# ============================================================

def test_register_data_quality_tools_returns_one_entry():
    entries = register_data_quality_tools()
    assert len(entries) == 1
    assert entries[0].name == "data_quality"


def test_server_registry_now_exposes_data_quality():
    from src.mcp.server import _collect_tool_entries
    registry = _collect_tool_entries()
    assert "data_quality" in registry
    # 14 tools after sub-arc 3.5 closes
    assert len(registry) >= 14


# ============================================================
# JSON round-trip
# ============================================================

def test_data_quality_output_round_trips_through_json():
    r.write_results(pd.DataFrame([_trade_row()]), run_id="json")
    out = data_quality_impl(DataQualityInput(
        run_id="json", dimension="liquidity_by_entry_offset",
    ))
    payload = json.dumps(out.model_dump(mode="json"))
    back = json.loads(payload)
    assert back["dimension"] == "liquidity_by_entry_offset"
    assert "table" in back
    assert "summary" in back
    assert "caveats" in back
