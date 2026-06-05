"""Tests for src/web/inspect.py — Phase 9.5 skeleton (memoir §24).

Coverage:
  - Cascading-validity snap on the 5-tuple selector contract (§24.8)
  - URL-param read-on-mount: full deeplink + partial-fallback (§24.9)
  - Default selection lands on a real sweep row (cascading defaults)
  - Stat-strip values round-trip from a fixture sweep row
  - IV in→out reads from the ``iv_materializer`` cache (NOT BS) by
    monkeypatching ``load_iv_history``
  - Reviewer-grep gate per CONSTRAINT 1: ZERO Black-Scholes call
    patterns anywhere in src/web/inspect.py OR this test file

See PORTFOLIO_MEMOIR.md §24 for the spec being tested.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pandas as pd
import pytest


REPO = Path(__file__).resolve().parent.parent


# ============================================================
# Fixture sweep — a tiny in-memory DataFrame with the shape the
# production sweep parquet exposes (subset of columns Inspect reads).
# ============================================================

def _leg(side="SELL", typ="CE", strike=2500.0, entry_px=18.0, exit_px=2.0,
         lot=300, qty=1) -> dict:
    return {
        "side": side, "option_type": typ, "strike": strike,
        "entry_px": entry_px, "entry_px_realized": entry_px,
        "exit_px": exit_px, "exit_px_realized": exit_px,
        "entry_volume": 100000, "exit_volume": 50000,
        "entry_oi": 200000, "exit_oi": 150000,
        "entry_turnover": 100.0, "exit_turnover": 50.0,
        "lot_size": lot, "qty_lots": qty,
        "gross_pnl": (entry_px - exit_px) * qty * lot,
    }


def _row(
    strategy="short_straddle", symbol="RELIANCE",
    expiry="2026-04-28", entry_date="2026-04-07", exit_date="2026-04-25",
    entry=15, exit_=3,
    net_pnl=4500.0, roi_pct=2.5, roi_pct_annualized=120.0,
    entry_spot=1400.0, exit_spot=1420.0,
    margin=180000.0, hold_td=12,
    legs=None,
) -> dict:
    legs = legs or [_leg("SELL", "CE", 1400.0, 30.0, 5.0),
                    _leg("SELL", "PE", 1400.0, 28.0, 2.0)]
    return {
        "run_id": "test_run",
        "strategy": strategy, "symbol": symbol,
        "expiry": pd.Timestamp(expiry),
        "entry_date": pd.Timestamp(entry_date),
        "exit_date": pd.Timestamp(exit_date),
        "entry_offset_td": entry, "exit_offset_td": exit_,
        "params_json": "{}",
        "legs_json": json.dumps(legs),
        "gross_pnl": net_pnl + 200.0,
        "costs": 200.0,
        "costs_breakdown_json": "{}",
        "net_pnl": net_pnl,
        "margin_at_entry": margin,
        "margin_breakdown_json": "{}",
        "roi_pct": roi_pct,
        "hold_trading_days": hold_td,
        "roi_pct_annualized": roi_pct_annualized,
        "entry_spot_vwap": entry_spot, "exit_spot_vwap": exit_spot,
        "entry_spot_close": entry_spot, "exit_spot_close": exit_spot,
        "notional_at_entry_vwap": entry_spot * 1000.0,
    }


@pytest.fixture
def fixture_sweep() -> pd.DataFrame:
    """3 strategies × 2 symbols × 2 expiries × 4 entry × 3 exit grid
    (subset, ensuring entry > exit always)."""
    rows = []
    for strat in ("short_straddle", "short_strangle", "iron_condor"):
        for sym in ("RELIANCE", "PNB"):
            for exp in ("2026-03-30", "2026-04-28"):
                for en in (5, 10, 15, 20):
                    for ex in (0, 3, 7):
                        if ex >= en:
                            continue
                        rows.append(_row(
                            strategy=strat, symbol=sym, expiry=exp,
                            entry=en, exit_=ex,
                            net_pnl=(en - ex) * 100.0,
                            roi_pct_annualized=10.0 * en,
                        ))
    return pd.DataFrame(rows)


# ============================================================
# Cascading-validity snap (memoir §24.8)
# ============================================================

def test_snap_picks_first_when_strategy_invalid(fixture_sweep):
    from src.web.inspect import _snap_to_valid
    out = _snap_to_valid(
        fixture_sweep, strategy="bogus", symbol="RELIANCE",
        expiry=pd.Timestamp("2026-04-28"), entry=15, exit_=3,
    )
    assert out is not None
    strat, sym, exp, en, ex = out
    # First sorted strategy is iron_condor (alphabetical).
    assert strat == "iron_condor"
    # All downstream snapped to valid combination.
    assert sym in fixture_sweep["symbol"].unique()
    assert ex < en


def test_snap_picks_most_recent_expiry_when_invalid(fixture_sweep):
    from src.web.inspect import _snap_to_valid
    out = _snap_to_valid(
        fixture_sweep, strategy="short_straddle", symbol="RELIANCE",
        expiry=pd.Timestamp("2099-01-01"), entry=15, exit_=3,
    )
    assert out is not None
    _, _, exp, _, _ = out
    # Most recent in the fixture is 2026-04-28.
    assert exp == pd.Timestamp("2026-04-28")


def test_snap_enforces_entry_gt_exit(fixture_sweep):
    """Per the sweep grid: exit < entry. If a proposed (entry, exit)
    violates this, the snap must repair it."""
    from src.web.inspect import _snap_to_valid
    out = _snap_to_valid(
        fixture_sweep, strategy="short_straddle", symbol="RELIANCE",
        expiry=pd.Timestamp("2026-04-28"), entry=3, exit_=7,
    )
    assert out is not None
    _, _, _, en, ex = out
    assert ex < en


def test_snap_returns_none_on_empty_df():
    from src.web.inspect import _snap_to_valid
    assert _snap_to_valid(pd.DataFrame()) is None


def test_default_tuple_lands_on_a_real_sweep_row(fixture_sweep):
    """Default-cascading 5-tuple must address an actual row in the
    sweep grid (replacement for the status=taken test removed in the
    builder-prompt pin since the sweep parquet has no status column —
    Phase 9.2 forward-dependency)."""
    from src.web.inspect import _snap_to_valid
    out = _snap_to_valid(fixture_sweep)
    assert out is not None
    strat, sym, exp, en, ex = out
    matches = fixture_sweep[
        (fixture_sweep["strategy"] == strat)
        & (fixture_sweep["symbol"] == sym)
        & (fixture_sweep["expiry"] == exp)
        & (fixture_sweep["entry_offset_td"] == en)
        & (fixture_sweep["exit_offset_td"] == ex)
    ]
    assert len(matches) == 1, (
        f"default tuple {(strat, sym, exp, en, ex)} doesn't map to "
        f"exactly one sweep row (got {len(matches)})"
    )


# ============================================================
# URL-param read (memoir §24.9)
# ============================================================

def _stub_query_params(monkeypatch, **params):
    """Patch st.query_params with a simple dict-like wrapper."""
    import src.web.inspect as ins
    monkeypatch.setattr(ins.st, "query_params", params)


def test_read_url_params_full_5_tuple(monkeypatch):
    from src.web.inspect import _read_url_params
    _stub_query_params(
        monkeypatch,
        strategy="short_strangle", symbol="RELIANCE",
        expiry="2026-04-28", entry_offset_td="15", exit_offset_td="3",
    )
    out = _read_url_params()
    assert out["strategy"] == "short_strangle"
    assert out["symbol"] == "RELIANCE"
    assert out["expiry"] == pd.Timestamp("2026-04-28")
    assert out["entry_offset_td"] == 15
    assert out["exit_offset_td"] == 3


def test_read_url_params_partial_missing_are_absent(monkeypatch):
    from src.web.inspect import _read_url_params
    _stub_query_params(monkeypatch, strategy="short_strangle", symbol="PNB")
    out = _read_url_params()
    assert out == {"strategy": "short_strangle", "symbol": "PNB"}


def test_read_url_params_drops_unparseable_int(monkeypatch):
    """Garbage entry_offset_td should NOT raise — it's just absent."""
    from src.web.inspect import _read_url_params
    _stub_query_params(monkeypatch, entry_offset_td="not_an_int")
    out = _read_url_params()
    assert "entry_offset_td" not in out


def test_read_url_params_drops_unparseable_date(monkeypatch):
    from src.web.inspect import _read_url_params
    _stub_query_params(monkeypatch, expiry="not-a-date")
    out = _read_url_params()
    assert "expiry" not in out


# ============================================================
# Stat strip — values round-trip from a known sweep row
# ============================================================

def test_net_credit_at_entry_signs_and_sums():
    """SELL legs add credit, BUY legs subtract — per CONSTRAINT 1's
    'observed entry premium' contract sourced from legs_json."""
    from src.web.inspect import _net_credit_at_entry
    row = _row(legs=[
        _leg("SELL", "CE", 1400.0, 30.0, 5.0, lot=300, qty=1),  # +9000
        _leg("BUY",  "CE", 1500.0, 10.0, 1.0, lot=300, qty=1),  # -3000
    ])
    credit = _net_credit_at_entry(row["legs_json"])
    assert credit == pytest.approx(30.0 * 300 - 10.0 * 300, abs=1e-6)


def test_fmt_inr_lakhs_crores():
    from src.web.inspect import _fmt_inr
    assert "Cr" in _fmt_inr(1.5e7)
    assert "L" in _fmt_inr(2.4e5)
    assert "K" in _fmt_inr(4500.0)
    assert _fmt_inr(-2.5e5).startswith("−")  # using minus glyph


# ============================================================
# IV in→out reads from cache, NEVER from BS (CONSTRAINT 1)
# ============================================================

def test_iv_at_date_reads_from_iv_materializer_cache(monkeypatch):
    """Stub ``load_iv_history`` to return a controlled DataFrame and
    verify ``_iv_at_date`` returns the cached value verbatim. The
    point: the read path goes through ``iv_materializer.load_iv_history``
    (which loaded a parquet built upstream by ``engine.iv`` BS work),
    NOT through any BS computation inside this module."""
    import src.web.inspect as ins
    fake_history = pd.DataFrame({
        "date": [pd.Timestamp("2026-04-07"), pd.Timestamp("2026-04-25")],
        ins._IV_COLUMN: [0.215, 0.182],
    })
    monkeypatch.setattr(ins, "load_iv_history", lambda symbol: fake_history)
    iv_in = ins._iv_at_date("RELIANCE", pd.Timestamp("2026-04-07"))
    iv_out = ins._iv_at_date("RELIANCE", pd.Timestamp("2026-04-25"))
    assert iv_in == pytest.approx(0.215)
    assert iv_out == pytest.approx(0.182)


def test_iv_at_date_returns_none_on_cache_miss(monkeypatch):
    import src.web.inspect as ins
    def _raise(symbol):
        raise FileNotFoundError(f"no IV cache for {symbol}")
    monkeypatch.setattr(ins, "load_iv_history", _raise)
    assert ins._iv_at_date("BOGUS", pd.Timestamp("2026-04-07")) is None


def test_iv_at_date_returns_none_when_date_absent(monkeypatch):
    import src.web.inspect as ins
    history = pd.DataFrame({
        "date": [pd.Timestamp("2026-04-07")],
        ins._IV_COLUMN: [0.21],
    })
    monkeypatch.setattr(ins, "load_iv_history", lambda symbol: history)
    assert ins._iv_at_date("RELIANCE", pd.Timestamp("2025-01-01")) is None


# ============================================================
# Reviewer-grep gate (CONSTRAINT 1 + cross-cutting #9 in prompt)
# ============================================================
#
# This is the load-bearing constraint of the whole Inspect cluster:
# the Inspect-side hot path computes ZERO Black-Scholes prices. All
# BS work belongs upstream in src/engine/iv.py; Inspect reads the
# materialized cache only. The gate also applies to this test file —
# we must verify the IV cache read by stubbing load_iv_history, NOT
# by re-computing IV via BS as a ground-truth oracle.

_BS_REJECT_PATTERNS = [
    r"\bbs76\b",
    r"\bbs_premium\b",
    r"\bblack_scholes\b",
    r"\bimplied_vol\b",
]


def _content_of(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_no_bs_calls_in_inspect_module():
    """CONSTRAINT 1: src/web/inspect.py must contain ZERO BS call
    patterns. A reviewer that grep-rejects this file finds nothing."""
    src = _content_of(REPO / "src" / "web" / "inspect.py")
    for pat in _BS_REJECT_PATTERNS:
        m = re.search(pat, src)
        assert m is None, (
            f"src/web/inspect.py contains banned BS-call pattern "
            f"{pat!r} (match: {m.group() if m else None!r}). "
            f"CONSTRAINT 1 + memoir §24.1 forbid Black-Scholes work in "
            f"the Inspect hot path; it belongs upstream in src/engine/iv.py."
        )


def test_no_bs_calls_in_this_test_file():
    """Mechanical uniformity per the operator's pin: the grep rule
    applies to tests too. The IV-cache read is verified by stubbing
    load_iv_history, NOT by re-computing IV via BS as ground truth."""
    src = _content_of(REPO / "tests" / "test_web_inspect.py")
    # Strip the reject-pattern literal list itself before scanning so
    # the test file's reject-rule definitions don't false-positive.
    sanitized = re.sub(
        r"_BS_REJECT_PATTERNS\s*=\s*\[.*?\]", "", src, flags=re.DOTALL,
    )
    for pat in _BS_REJECT_PATTERNS:
        m = re.search(pat, sanitized)
        assert m is None, (
            f"tests/test_web_inspect.py contains banned BS-call pattern "
            f"{pat!r}. The CONSTRAINT 1 grep gate applies mechanically "
            f"to tests too."
        )
