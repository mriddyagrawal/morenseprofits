"""Tests for src.analytics.earnings_filter.

Tests synthesize the events DataFrame in-memory (canonical
events_loader schema: SYMBOL string, PURPOSE string, DATE
datetime64[us]); no parquet I/O.

LOAD-BEARING tests:
  - parity with ``has_earnings_in_window`` per symbol (the batch
    wrapper MUST agree with the single-symbol kernel on every
    case — drift here would mean the Portfolio banner and the
    backtester disagree on what's in/out)
  - cold-cache pass-through (None events_df → all symbols kept)
  - in-window detection on the [entry, exit+1d] boundary (per
    F10's +1 day buffer)
  - non-Financial-Results events ignored (per §17.5)
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.analytics.earnings_filter import (
    DroppedSymbol,
    EarningsFilterResult,
    filter_universe_by_earnings,
)
from src.data.events_loader import has_earnings_in_window


# ============================================================
# Fixtures
# ============================================================

def _events_frame(rows: list[dict]) -> pd.DataFrame:
    """Build a canonical events frame (matches events_loader's
    output schema exactly: SYMBOL string, PURPOSE string, DATE
    datetime64[us])."""
    df = pd.DataFrame(rows)
    df["SYMBOL"] = df["SYMBOL"].astype("string")
    df["PURPOSE"] = df["PURPOSE"].astype("string")
    df["DATE"] = pd.to_datetime(df["DATE"]).astype("datetime64[us]")
    return df


# ============================================================
# Basic shape + kept/dropped partition
# ============================================================

def test_no_events_in_window_keeps_all_symbols():
    """Earnings events exist but fall outside [entry, exit+1d] →
    universe is intact, n_dropped=0."""
    df = _events_frame([
        {"SYMBOL": "RELIANCE", "PURPOSE": "Financial Results",
         "DATE": "2024-01-15"},
        {"SYMBOL": "INFY", "PURPOSE": "Financial Results",
         "DATE": "2024-10-20"},
    ])
    res = filter_universe_by_earnings(
        ["RELIANCE", "INFY", "TCS"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.kept == ["RELIANCE", "INFY", "TCS"]
    assert res.dropped == []
    assert res.total == 3
    assert res.n_dropped == 0


def test_single_in_window_event_drops_one_symbol():
    """RELIANCE has a Financial Results event mid-window → drop.
    INFY + TCS clean → kept."""
    df = _events_frame([
        {"SYMBOL": "RELIANCE", "PURPOSE": "Financial Results",
         "DATE": "2024-05-15"},
        {"SYMBOL": "INFY", "PURPOSE": "Financial Results",
         "DATE": "2024-01-15"},
    ])
    res = filter_universe_by_earnings(
        ["RELIANCE", "INFY", "TCS"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.kept == ["INFY", "TCS"]
    assert res.dropped == [
        DroppedSymbol(
            symbol="RELIANCE",
            event_date=date(2024, 5, 15),
            purpose="Financial Results",
        )
    ]


def test_preserves_input_symbol_order():
    """Deterministic kept order matches the input iterable's order
    (drop+keep partition stable; not alphabetical)."""
    df = _events_frame([
        {"SYMBOL": "TCS", "PURPOSE": "Financial Results",
         "DATE": "2024-05-15"},
    ])
    res = filter_universe_by_earnings(
        ["RELIANCE", "INFY", "TCS", "HDFCBANK"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.kept == ["RELIANCE", "INFY", "HDFCBANK"]


def test_total_property_sums_kept_and_dropped():
    df = _events_frame([
        {"SYMBOL": "A", "PURPOSE": "Financial Results",
         "DATE": "2024-05-15"},
    ])
    res = filter_universe_by_earnings(
        ["A", "B", "C"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.total == 3
    assert res.n_dropped == 1


# ============================================================
# Window boundary — F10's +1 day buffer
# ============================================================

def test_event_on_entry_date_drops_symbol():
    """Event on the entry date itself → in-window → drop."""
    df = _events_frame([
        {"SYMBOL": "RELIANCE", "PURPOSE": "Financial Results",
         "DATE": "2024-05-01"},
    ])
    res = filter_universe_by_earnings(
        ["RELIANCE"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.n_dropped == 1


def test_event_on_exit_plus_one_drops_symbol():
    """LOAD-BEARING F10 buffer test: event on (exit + 1 calendar
    day) → in-window → drop. Catches the case where exit is the
    day BEFORE announcement."""
    df = _events_frame([
        {"SYMBOL": "RELIANCE", "PURPOSE": "Financial Results",
         "DATE": "2024-05-31"},  # = exit_date + 1 day
    ])
    res = filter_universe_by_earnings(
        ["RELIANCE"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.n_dropped == 1


def test_event_on_exit_plus_two_does_not_drop():
    """Event 2+ days after exit is outside the buffer → keep."""
    df = _events_frame([
        {"SYMBOL": "RELIANCE", "PURPOSE": "Financial Results",
         "DATE": "2024-06-01"},  # = exit_date + 2 days
    ])
    res = filter_universe_by_earnings(
        ["RELIANCE"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.kept == ["RELIANCE"]
    assert res.n_dropped == 0


def test_event_before_entry_date_does_not_drop():
    df = _events_frame([
        {"SYMBOL": "RELIANCE", "PURPOSE": "Financial Results",
         "DATE": "2024-04-30"},
    ])
    res = filter_universe_by_earnings(
        ["RELIANCE"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.kept == ["RELIANCE"]


# ============================================================
# PURPOSE filter — §17.5 says only Financial Results count
# ============================================================

def test_non_financial_results_event_does_not_drop():
    """Per §17.5 the cache holds only Financial Results rows;
    defensive belt-and-braces: a hand-built frame with Dividend
    rows must NOT trigger the filter."""
    df = _events_frame([
        {"SYMBOL": "RELIANCE", "PURPOSE": "Dividend",
         "DATE": "2024-05-15"},
        {"SYMBOL": "RELIANCE", "PURPOSE": "Fund Raising",
         "DATE": "2024-05-20"},
    ])
    res = filter_universe_by_earnings(
        ["RELIANCE"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.kept == ["RELIANCE"]


def test_multi_category_purpose_with_financial_results_drops():
    """Real NSE rows can be multi-category ('Financial
    Results/Dividend'); substring match per §17.5 → drop."""
    df = _events_frame([
        {"SYMBOL": "RELIANCE",
         "PURPOSE": "Financial Results/Dividend",
         "DATE": "2024-05-15"},
    ])
    res = filter_universe_by_earnings(
        ["RELIANCE"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.n_dropped == 1
    assert res.dropped[0].purpose == "Financial Results/Dividend"


# ============================================================
# Cold-cache + edge inputs
# ============================================================

def test_none_events_df_is_cold_cache_passthrough():
    """LOAD-BEARING UX contract: fresh clone with no CSV → ALL
    symbols kept (conservative pass-through), no exception."""
    res = filter_universe_by_earnings(
        ["RELIANCE", "INFY", "TCS"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=None,
    )
    assert res.kept == ["RELIANCE", "INFY", "TCS"]
    assert res.dropped == []


def test_empty_events_df_is_cold_cache_passthrough():
    """Same as None: events_df.empty → pass-through."""
    df = pd.DataFrame({
        "SYMBOL": pd.Series(dtype="string"),
        "PURPOSE": pd.Series(dtype="string"),
        "DATE": pd.Series(dtype="datetime64[us]"),
    })
    res = filter_universe_by_earnings(
        ["RELIANCE"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.kept == ["RELIANCE"]


def test_empty_symbols_returns_empty_result():
    df = _events_frame([
        {"SYMBOL": "RELIANCE", "PURPOSE": "Financial Results",
         "DATE": "2024-05-15"},
    ])
    res = filter_universe_by_earnings(
        [],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.kept == []
    assert res.dropped == []


def test_inverted_window_raises():
    """entry > exit is a programmer error — fail loudly."""
    with pytest.raises(ValueError, match="entry_date.*exit_date"):
        filter_universe_by_earnings(
            ["RELIANCE"],
            entry_date=date(2024, 5, 30), exit_date=date(2024, 5, 1),
            events_df=None,
        )


def test_lowercase_input_symbol_matches_uppercase_cache():
    """Defensive: input symbol case-normalized to uppercase to
    match the events_loader's case-normalized SYMBOL column
    (closes the same asymmetry the events_loader fixed at
    d824ef8 — applied here on the input side, not the cache
    side)."""
    df = _events_frame([
        {"SYMBOL": "RELIANCE", "PURPOSE": "Financial Results",
         "DATE": "2024-05-15"},
    ])
    res = filter_universe_by_earnings(
        ["reliance"],  # lowercase input
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.n_dropped == 1
    assert res.dropped[0].symbol == "RELIANCE"


# ============================================================
# Multi-event dedup — first event wins
# ============================================================

def test_multiple_in_window_events_for_symbol_picks_earliest():
    """Degenerate two-events-same-quarter case (rare; happens at
    annual + quarterly overlap). Earliest by date wins."""
    df = _events_frame([
        {"SYMBOL": "RELIANCE", "PURPOSE": "Financial Results",
         "DATE": "2024-05-20"},
        {"SYMBOL": "RELIANCE", "PURPOSE": "Financial Results",
         "DATE": "2024-05-15"},
    ])
    res = filter_universe_by_earnings(
        ["RELIANCE"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.n_dropped == 1
    assert res.dropped[0].event_date == date(2024, 5, 15)


# ============================================================
# Parity with the single-symbol kernel
# ============================================================

@pytest.mark.parametrize("entry,exit_d,event_date,expected_dropped", [
    # Inside window
    (date(2024, 5, 1), date(2024, 5, 30), "2024-05-15", True),
    # Boundary: entry day
    (date(2024, 5, 1), date(2024, 5, 30), "2024-05-01", True),
    # Boundary: exit+1
    (date(2024, 5, 1), date(2024, 5, 30), "2024-05-31", True),
    # Boundary: exit+2 (outside)
    (date(2024, 5, 1), date(2024, 5, 30), "2024-06-01", False),
    # Before entry
    (date(2024, 5, 1), date(2024, 5, 30), "2024-04-30", False),
    # Way after
    (date(2024, 5, 1), date(2024, 5, 30), "2024-12-31", False),
])
def test_batch_wrapper_agrees_with_single_symbol_kernel(
    entry, exit_d, event_date, expected_dropped,
):
    """LOAD-BEARING. The batch wrapper and
    ``has_earnings_in_window`` MUST agree on every boundary case
    — drift would mean the Portfolio banner and the backtester's
    own filter return different verdicts on the same trade."""
    df = _events_frame([
        {"SYMBOL": "RELIANCE", "PURPOSE": "Financial Results",
         "DATE": event_date},
    ])
    # Single-symbol kernel.
    kernel_says = has_earnings_in_window(df, "RELIANCE", entry, exit_d)
    # Batch wrapper.
    res = filter_universe_by_earnings(
        ["RELIANCE"], entry, exit_d, events_df=df,
    )
    batch_says = res.n_dropped == 1
    assert kernel_says == batch_says == expected_dropped


# ============================================================
# banner_text — the Portfolio banner contract
# ============================================================

def test_banner_text_empty_when_no_drops():
    """Render-skip contract: empty string lets caller do
    ``if result.banner_text(): show_it``."""
    res = filter_universe_by_earnings(
        ["RELIANCE"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=None,
    )
    assert res.banner_text() == ""


def test_banner_text_when_drops():
    df = _events_frame([
        {"SYMBOL": "RELIANCE", "PURPOSE": "Financial Results",
         "DATE": "2024-05-15"},
        {"SYMBOL": "INFY", "PURPOSE": "Financial Results",
         "DATE": "2024-05-20"},
    ])
    res = filter_universe_by_earnings(
        ["RELIANCE", "INFY", "TCS"],
        entry_date=date(2024, 5, 1), exit_date=date(2024, 5, 30),
        events_df=df,
    )
    assert res.banner_text() == "2 candidates dropped: earnings in window"
