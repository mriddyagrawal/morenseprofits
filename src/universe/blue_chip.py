"""Blue-chip universe — 40 large-cap NSE names with liquid options.

**Why 40 (not 50)**: the user prefers a tighter universe; the dropped
10 are lower-priority for short-straddle backtests because their
options markets are thinner. Exact stock selection is explicitly a v1
shortcut — the reporting / analysis quality is what matters; Phase 7
will add a user-curated-universe skill so the operator can swap this
list out per session (PLAN §3 deferred item).

**v1 limitation** (load-bearing — see SPECS §6b.3): single point-in-
time snapshot (~mid-2024). Backtests against this list on 2019 prices
have classic survivorship bias — stocks that were in the index then
but got dropped are absent, so returns look better than reality.

Mitigations:
  1. Phase 5/6 UI MUST render a "Survivorship-bias note" disclaimer.
  2. Phase 7 backlog: per-quarter membership AND user-curated-list
     skill (see PLAN §3 deferred items).
  3. This docstring exists so the limitation is visible at the source.

**Source**: derived from the NIFTY 50 Wikipedia snapshot (retrieval
date ~2024-07-01, https://en.wikipedia.org/wiki/NIFTY_50), with the
10 lower-options-liquidity members removed. Selection is "kinda good"
per the v1 ask — not a published-research-grade composition.

NSE trading symbols (uppercase, no exchange suffix) work directly with
``jugaad_data.nse.stock_df`` / ``derivatives_df``.
"""
from __future__ import annotations

from datetime import date

# 40 large-cap NSE symbols. Alphabetically sorted for determinism +
# diff-friendliness. Spelling matches NSE conventions exactly
# (e.g. "BAJAJ-AUTO" with hyphen, "M&M" with ampersand) so they work
# directly with jugaad-data.
_BLUE_CHIP_V1: tuple[str, ...] = (
    "ADANIENT", "ADANIPORTS", "ASIANPAINT", "AXISBANK", "BAJAJ-AUTO",
    "BAJAJFINSV", "BAJFINANCE", "BHARTIARTL", "CIPLA", "COALINDIA",
    "DRREDDY", "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JSWSTEEL", "KOTAKBANK", "LT", "M&M",
    "MARUTI", "NESTLEIND", "NTPC", "ONGC", "POWERGRID",
    "RELIANCE", "SBIN", "SUNPHARMA", "TATAMOTORS", "TATASTEEL",
    "TCS", "TECHM", "TITAN", "ULTRACEMCO", "WIPRO",
)
assert len(_BLUE_CHIP_V1) == 40, (
    f"expected 40 blue-chip symbols, got {len(_BLUE_CHIP_V1)}"
)
assert len(set(_BLUE_CHIP_V1)) == 40, "duplicate symbols in list"
assert list(_BLUE_CHIP_V1) == sorted(_BLUE_CHIP_V1), (
    "list is not alphabetically sorted — fix the literal for diff hygiene"
)


def blue_chip(as_of: date) -> list[str]:
    """Sorted list of 40 blue-chip NSE symbols as-of ``as_of``.

    v1 ignores ``as_of`` and always returns the same snapshot. The
    parameter is required (not defaulted) so backtests record the
    intended evaluation date in their config even if v1 doesn't use it
    yet — a Phase-7 upgrade to point-in-time membership will need it.
    """
    return list(_BLUE_CHIP_V1)
