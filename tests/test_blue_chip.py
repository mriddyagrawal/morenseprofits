"""Tests for src.universe.blue_chip. No network — pure-Python data."""
from __future__ import annotations

from datetime import date

import pytest

from src.universe import blue_chip as bc_mod
from src.universe.blue_chip import blue_chip


def test_returns_exactly_48_symbols():
    out = blue_chip(date(2024, 7, 1))
    assert len(out) == 48, f"v1 universe is 48 stocks (NIFTY-50 minus 2 thin-liquidity hold-outs)"


def test_symbols_are_unique():
    out = blue_chip(date(2024, 7, 1))
    assert len(set(out)) == 48, "blue_chip must contain no duplicates"


def test_symbols_are_alphabetically_sorted():
    """Sort order is a determinism contract; downstream backtest sweepers
    iterate in this order, so any drift causes byte-different results."""
    out = blue_chip(date(2024, 7, 1))
    assert out == sorted(out)


def test_as_of_independence_in_v1():
    """v1 ignores as_of by design — single snapshot. Three different
    as_of dates must all return identical lists."""
    a = blue_chip(date(2020, 1, 1))
    b = blue_chip(date(2024, 7, 1))
    c = blue_chip(date(2030, 12, 31))
    assert a == b == c


def test_includes_canonical_blue_chips():
    """Smoke check — RELIANCE/HDFCBANK/INFY/TCS/ICICIBANK must be in
    any list calling itself 'blue chip'. If a future trim removes one
    of these, that's almost certainly a typo, not a design decision."""
    out = set(blue_chip(date(2024, 7, 1)))
    for canonical in ("RELIANCE", "HDFCBANK", "INFY", "TCS", "ICICIBANK"):
        assert canonical in out, f"{canonical} missing from blue_chip"


def test_returned_list_is_independent_copy():
    """Caller mutating the returned list must NOT affect subsequent
    calls — the module's internal tuple should be re-listed each call."""
    a = blue_chip(date(2024, 7, 1))
    a.append("HACKED")
    b = blue_chip(date(2024, 7, 1))
    assert "HACKED" not in b


def test_symbols_use_nse_spelling_conventions():
    """A few NSE symbols have non-obvious spellings (hyphen, ampersand).
    Pin the exact wire-compatible forms so a future "clean up" edit
    doesn't break jugaad-data lookups."""
    out = set(blue_chip(date(2024, 7, 1)))
    # NSE uses BAJAJ-AUTO with hyphen, not "BAJAJAUTO"
    assert "BAJAJ-AUTO" in out
    # NSE uses M&M with ampersand for Mahindra & Mahindra
    assert "M&M" in out


def test_internal_invariants_hold_on_import():
    """The module-level asserts in blue_chip.py would fire at import
    time if invariants broke — but if `python -O` is used, asserts get
    stripped. Re-check defensively here in tests."""
    assert len(bc_mod._BLUE_CHIP_V1) == 48
    assert len(set(bc_mod._BLUE_CHIP_V1)) == 48
    assert list(bc_mod._BLUE_CHIP_V1) == sorted(bc_mod._BLUE_CHIP_V1)
