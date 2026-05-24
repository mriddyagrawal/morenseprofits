"""Tests for src.strategies.registry."""
from __future__ import annotations

import pytest

from src.strategies.registry import STRATEGIES, get_strategy, list_strategies
from src.strategies.short_straddle import ShortStraddle


def test_short_straddle_registered():
    s = get_strategy("short_straddle")
    assert isinstance(s, ShortStraddle)
    assert s.name == "short_straddle"


def test_each_registered_strategy_has_required_attrs():
    """Every registered strategy must expose the contract per SPECS §6c.1."""
    for name, strat in STRATEGIES.items():
        assert strat.name == name, f"{name}: strat.name = {strat.name!r}"
        assert hasattr(strat, "recommended_strategy_offset_pct")
        offset = strat.recommended_strategy_offset_pct
        assert 0.0 < offset <= 1.0, (
            f"{name}: recommended_strategy_offset_pct={offset} out of range"
        )
        assert hasattr(strat, "generate_trades")
        assert callable(strat.generate_trades)


def test_short_straddle_offset_is_0_60():
    """SPECS §4a calibration: short straddle real-broker SPAN offset
    is 0.60. Pin via the registry."""
    assert STRATEGIES["short_straddle"].recommended_strategy_offset_pct == 0.60


def test_unknown_strategy_raises_with_available_list():
    """Misspelled lookup should be useful, not opaque."""
    with pytest.raises(KeyError, match="not registered"):
        get_strategy("short_stradle")  # typo


def test_list_strategies_sorted():
    """Determinism: iteration order is name-asc. Sweepers rely on this."""
    names = list_strategies()
    assert names == sorted(names)


def test_list_strategies_includes_short_straddle():
    assert "short_straddle" in list_strategies()
