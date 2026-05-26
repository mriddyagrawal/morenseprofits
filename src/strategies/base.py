"""Strategy / Trade / Leg primitives.

A Strategy is a callable that turns a (symbol, expiry, entry_date,
exit_date, spot_at_entry, params) tuple into a list of Trade objects.
Trades are immutable bundles of Legs. Legs are immutable single-instrument
orders priced by the engine.

The pricing kernel lives in ``src/engine/pnl.py`` and consumes Trade
objects produced by Strategy implementations.

Sign convention (SPECS §3a) is enforced at the Leg layer via
``side_sign``: SELL=+1, BUY=-1, so per-leg P&L is uniformly
``(entry - exit) * side_sign * qty_lots * lot_size``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Protocol


Side = Literal["SELL", "BUY"]
OptionType = Literal["CE", "PE"]


def side_sign(side: Side) -> int:
    """+1 for SELL (profit from price falls), -1 for BUY (profit from
    price rises). Used as a multiplier in the per-leg P&L formula —
    see SPECS §3a."""
    if side == "SELL":
        return +1
    if side == "BUY":
        return -1
    raise ValueError(f"side must be 'SELL' or 'BUY', got {side!r}")


@dataclass(frozen=True)
class Leg:
    """One option contract leg of a trade. Immutable.

    A Leg names WHAT to trade (option_type + strike) and HOW
    (side + qty_lots). The engine looks up prices via
    ``load_option(symbol, expiry, strike, option_type, ...)``.
    """
    option_type: OptionType
    strike: float
    side: Side
    qty_lots: int = 1

    def __post_init__(self):
        if self.option_type not in ("CE", "PE"):
            raise ValueError(f"option_type must be 'CE' or 'PE', got {self.option_type!r}")
        if self.side not in ("SELL", "BUY"):
            raise ValueError(f"side must be 'SELL' or 'BUY', got {self.side!r}")
        if self.qty_lots <= 0:
            raise ValueError(f"qty_lots must be > 0, got {self.qty_lots}")
        if float(self.strike) != int(self.strike):
            # Mirror cache.option_path's strike-int guard (SPECS §5):
            # whole-rupee NSE strikes only.
            raise ValueError(
                f"strike {self.strike!r} is not a whole rupee; NSE stock-option "
                f"strikes are integer. Pass an int or a float with no fractional part."
            )


@dataclass(frozen=True)
class Trade:
    """A complete trade: one or more legs entered on entry_date, exited
    on exit_date, against a single underlying contract (symbol + expiry).

    Immutable. Strategies emit Trades; the engine prices them.
    """
    symbol: str
    expiry: date
    entry_date: date
    exit_date: date
    legs: tuple[Leg, ...]
    strategy: str
    params: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.legs:
            raise ValueError("Trade must have at least one leg")
        if self.entry_date > self.exit_date:
            raise ValueError(
                f"entry_date {self.entry_date} > exit_date {self.exit_date}"
            )
        if self.exit_date > self.expiry:
            raise ValueError(
                f"exit_date {self.exit_date} > expiry {self.expiry}; "
                f"can't hold a contract past expiry"
            )


class Strategy(Protocol):
    """A strategy generates Trade objects for a given (symbol, expiry,
    entry_date, exit_date, spot_at_entry, params) context.

    Implementations live in ``src/strategies/`` (one file per strategy
    name) and are registered by name in a future strategy registry
    (Phase 4). For Phase 3 we only need the protocol so the engine can
    type-check Trade producers."""
    name: str

    def generate_trades(
        self,
        symbol: str,
        expiry: date,
        entry_date: date,
        exit_date: date,
        spot_at_entry: float,
        params: dict,
    ) -> list[Trade]: ...

    def display_strike_rule(self, params: dict | None = None) -> str:
        """One-line, human-readable description of the strike(s) this
        strategy picks at entry. Surfaced under the strategy selectbox
        on the Heatmap tab so the analyst can see WHICH STRIKES the
        historical trades used (otherwise buried in source defaults).

        ``params`` reflects the same overrides ``generate_trades`` would
        apply (e.g. ``{"strike_offset_pct": 0.03}`` for a strangle).
        ``None`` → use the strategy's default offsets."""
        ...
