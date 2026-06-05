"""Earnings-event filter for portfolio candidate selection.

PORTFOLIO_MEMOIR.md §21.4 F10 + §17.5 (filter rule) + FILTERS.md
Part B (the §B.0 template + the two cross-cutting rules: no
look-ahead, surface-the-count).

The single-symbol kernel ``has_earnings_in_window`` already lives
in ``src.data.events_loader`` (commit 182cf1d / d824ef8). This
module adds the **batch wrapper** that:

  1. Filters a universe-sized symbol list in one pass instead of
     N independent calls (the events frame is scanned once per
     symbol, not once per call).
  2. Returns a structured ``EarningsFilterResult`` carrying BOTH
     the surviving symbols AND the per-dropped-symbol reason
     (event date + purpose string) so the Portfolio banner can
     surface "X candidates dropped: earnings in window" honestly
     and the drilldown can show which symbols + which dates.
  3. Tolerates a None events frame (cold cache → no filter
     triggered, conservative pass-through) — important for the
     "fresh clone where the operator hasn't downloaded
     CF-Event-equities yet" UX.

Cross-cutting rules (FILTERS.md §B.0 + §17.7):

  - **No look-ahead**: the events frame's DATE column is the
    board-meeting date, which is the results-announcement date.
    Per memoir §17.7 this is a 5-14 day lookahead vs strictly-
    public knowledge (the Reg 29(1)(a) notice is filed 5-14 days
    BEFORE the meeting). The operator's intent is "avoid the
    earnings event, not model exact lead-time," so this is
    accepted — but the filter MUST cite the lookahead in its
    Caveat row in FILTERS.md.
  - **Surface the count**: the dropped list is the count.

Public API:

  ``filter_universe_by_earnings(symbols, entry_date, exit_date,
                                  *, events_df) -> EarningsFilterResult``
      Returns (kept, dropped) for the symbol universe.

  ``EarningsFilterResult`` dataclass:
      .kept   : list[str]            — symbols clean of in-window events
      .dropped: list[DroppedSymbol]  — symbols with their first
                                       in-window event date + purpose
      .total  : int                  — len(kept) + len(dropped)
                                       (convenience for the banner)

  ``DroppedSymbol`` dataclass:
      .symbol     : str
      .event_date : date
      .purpose    : str
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from src.data.events_loader import has_earnings_in_window


@dataclass(frozen=True)
class DroppedSymbol:
    """One symbol dropped from the universe with the reason.

    ``event_date`` is the FIRST in-window event the filter
    encountered for that symbol; in practice each symbol has at
    most one Financial Results event per quarter so this is
    unambiguous, but in the degenerate two-events-same-quarter
    case the earliest by date wins.
    """
    symbol: str
    event_date: date
    purpose: str


@dataclass(frozen=True)
class EarningsFilterResult:
    """Outcome of filtering a symbol universe against the
    earnings calendar over an entry-to-exit window.

    Shape contract: ``kept + dropped`` partition the input
    universe (no symbol appears in both; symbols not in the
    events frame land in ``kept`` per the cold-cache default).
    Order of ``kept`` and ``dropped`` mirrors the order of the
    input ``symbols`` iterable for determinism.
    """
    kept: list[str] = field(default_factory=list)
    dropped: list[DroppedSymbol] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.kept) + len(self.dropped)

    @property
    def n_dropped(self) -> int:
        return len(self.dropped)

    def banner_text(self) -> str:
        """One-liner for the Portfolio tab regime banner per
        memoir §21.4 F10. Returns empty string when no drops —
        callers can ``if result.banner_text(): show_it`` to
        skip rendering when irrelevant."""
        if not self.dropped:
            return ""
        return (
            f"{len(self.dropped)} candidates dropped: "
            f"earnings in window"
        )


def filter_universe_by_earnings(
    symbols: Iterable[str],
    entry_date: date,
    exit_date: date,
    *,
    events_df: pd.DataFrame | None,
) -> EarningsFilterResult:
    """Filter ``symbols`` to those with NO Financial Results event
    in ``[entry_date, exit_date + 1 calendar day]``.

    The +1 calendar day buffer after exit matches
    ``has_earnings_in_window`` — catches the case where exit is
    the day BEFORE announcement (vol still elevated overnight,
    gap risk present). Per memoir §21.4 F10.

    Args:
        symbols: NSE tickers (uppercased internally; case-insensitive
            input accepted defensively, though the loader writes
            uppercase per d824ef8).
        entry_date: trade entry date.
        exit_date: trade exit date.
        events_df: the events frame from
            ``events_loader.load_events()``. May be ``None`` when
            the cache is cold (no CSV downloaded yet); pass-through
            behavior keeps the universe intact rather than failing
            the entire backtest.

    Returns:
        ``EarningsFilterResult`` with deterministic order.

    Cold-cache behavior: ``events_df is None`` OR ``events_df.empty``
    → all symbols pass. Conservative for "no data" — better to
    over-include than fail loudly when the data file hasn't been
    dropped yet. The Portfolio banner can detect this case via
    ``result.n_dropped == 0`` AND ``events_df is None`` (caller's
    responsibility; this function doesn't second-guess).
    """
    if entry_date > exit_date:
        raise ValueError(
            f"entry_date {entry_date} > exit_date {exit_date}"
        )

    symbols_list = list(symbols)
    if not symbols_list:
        return EarningsFilterResult()

    # Cold-cache pass-through.
    if events_df is None or events_df.empty:
        return EarningsFilterResult(kept=symbols_list[:])

    # Single-pass build of the per-symbol Financial-Results event
    # index. Saves N scans of the events frame.
    ts_entry = pd.Timestamp(entry_date)
    ts_exit_plus = pd.Timestamp(exit_date) + pd.Timedelta(days=1)
    in_window = events_df[
        (events_df["DATE"] >= ts_entry)
        & (events_df["DATE"] <= ts_exit_plus)
        & events_df["PURPOSE"].str.contains(
            "Financial Results", na=False,
        )
    ]
    # symbol → (event_date, purpose) for the FIRST in-window event.
    first_event: dict[str, tuple[date, str]] = {}
    for sym, sub in in_window.groupby("SYMBOL", sort=False):
        row = sub.sort_values("DATE").iloc[0]
        first_event[str(sym)] = (
            pd.Timestamp(row["DATE"]).date(),
            str(row["PURPOSE"]),
        )

    kept: list[str] = []
    dropped: list[DroppedSymbol] = []
    for raw in symbols_list:
        sym = str(raw).upper()
        if sym in first_event:
            event_date, purpose = first_event[sym]
            dropped.append(DroppedSymbol(
                symbol=sym, event_date=event_date, purpose=purpose,
            ))
        else:
            # Single-symbol membership check is consistent with
            # ``has_earnings_in_window`` even though the batch
            # path already gave us the answer — but only the
            # batch index covers Financial-Results rows. A
            # non-Financial-Results event for this symbol still
            # results in kept=True, which matches §17.5.
            kept.append(sym)
    return EarningsFilterResult(kept=kept, dropped=dropped)


# Sanity-binding for the single-symbol kernel — make sure the
# batch wrapper and the single-symbol kernel remain
# behaviorally consistent. Import surface kept narrow so
# downstream callers reach the batch API by default, but the
# kernel re-export is available for tests that want to verify
# parity without crossing module boundaries.
_has_earnings_in_window = has_earnings_in_window
"""Re-exported for symmetry tests and downstream parity checks.
NOT a public API name — call ``has_earnings_in_window`` from
``src.data.events_loader`` directly if you need the single-
symbol check."""
