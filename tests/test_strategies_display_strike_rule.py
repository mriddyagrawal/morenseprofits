"""Tests for Strategy.display_strike_rule across all 5 registered
strategies. Pin the exact rendered strings + verify param overrides
flow through.

The Heatmap tab's selector renders this string as ℹ caption so the
analyst can see the strike-selection rule without digging through
src/strategies/*.py. Tests freeze the wording so a future refactor
that "improves" the copy doesn't silently change what's surfaced."""
from __future__ import annotations

from src.strategies.iron_condor import IronCondor
from src.strategies.long_straddle import LongStraddle
from src.strategies.long_strangle import LongStrangle
from src.strategies.short_straddle import ShortStraddle
from src.strategies.short_strangle import ShortStrangle


# ============================================================
# Default-params strings (pinned)
# ============================================================

def test_short_straddle_default():
    assert (
        ShortStraddle().display_strike_rule()
        == "ATM — nearest listed strike to entry-day spot close"
    )


def test_long_straddle_default():
    assert (
        LongStraddle().display_strike_rule()
        == "ATM — nearest listed strike to entry-day spot close"
    )


def test_short_strangle_default():
    assert (
        ShortStrangle().display_strike_rule()
        == "2% OTM each side — nearest listed to spot×1.02 (CE), spot×0.98 (PE)"
    )


def test_long_strangle_default():
    assert (
        LongStrangle().display_strike_rule()
        == "2% OTM each side — nearest listed to spot×1.02 (CE), spot×0.98 (PE)"
    )


def test_iron_condor_default():
    assert (
        IronCondor().display_strike_rule()
        == "Inner SELL at ±2% OTM ; Outer BUY at ±5% OTM (all nearest listed)"
    )


# ============================================================
# Params overrides flow through
# ============================================================

def test_short_strangle_override_propagates():
    s = ShortStrangle().display_strike_rule({"strike_offset_pct": 0.03})
    assert (
        s == "3% OTM each side — nearest listed to spot×1.03 (CE), spot×0.97 (PE)"
    )


def test_long_strangle_override_propagates():
    s = LongStrangle().display_strike_rule({"strike_offset_pct": 0.05})
    assert (
        s == "5% OTM each side — nearest listed to spot×1.05 (CE), spot×0.95 (PE)"
    )


def test_iron_condor_both_overrides_propagate():
    s = IronCondor().display_strike_rule(
        {"inner_offset_pct": 0.025, "outer_offset_pct": 0.06}
    )
    assert s == "Inner SELL at ±2.5% OTM ; Outer BUY at ±6% OTM (all nearest listed)"


# ============================================================
# None / empty params behave as default
# ============================================================

def test_none_params_uses_default():
    assert ShortStrangle().display_strike_rule(None) == ShortStrangle().display_strike_rule()
    assert IronCondor().display_strike_rule(None) == IronCondor().display_strike_rule()


def test_empty_dict_params_uses_default():
    assert ShortStrangle().display_strike_rule({}) == ShortStrangle().display_strike_rule()
    assert IronCondor().display_strike_rule({}) == IronCondor().display_strike_rule()
