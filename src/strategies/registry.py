"""Strategy registry — name → instance mapping.

Phase 4 sweeper iterates strategies by name; Phase 8 MCP server exposes
strategy listing as a tool. Centralized registry lets new strategies
opt in by importing themselves here, and consumers iterate without
maintaining their own list.

Each registered strategy must expose at minimum:
  - ``name: str``                            (matches the registry key)
  - ``recommended_strategy_offset_pct: float`` (SPECS §6c.1)
  - ``generate_trades(symbol, expiry, entry_date, exit_date, spot_at_entry, params)``
    returning ``list[Trade]``.

The registry is INTENTIONALLY a flat dict (not a class hierarchy) — keeps
adding a new strategy to a single import + dict entry.
"""
from __future__ import annotations

from src.strategies.base import Strategy
from src.strategies.long_straddle import LongStraddle
from src.strategies.short_straddle import ShortStraddle
from src.strategies.short_strangle import ShortStrangle


# Registered strategies. Adding a new one = import it + add one line here.
STRATEGIES: dict[str, Strategy] = {
    "long_straddle": LongStraddle(),
    "short_straddle": ShortStraddle(),
    "short_strangle": ShortStrangle(),
}


def get_strategy(name: str) -> Strategy:
    """Look up a registered strategy by name. Raises KeyError with a
    helpful message listing the available names if the lookup fails."""
    try:
        return STRATEGIES[name]
    except KeyError as e:
        available = sorted(STRATEGIES.keys())
        raise KeyError(
            f"strategy {name!r} not registered. Available: {available}"
        ) from e


def list_strategies() -> list[str]:
    """Sorted list of registered strategy names. Sorted for determinism
    — sweep iteration order is name-asc."""
    return sorted(STRATEGIES.keys())
