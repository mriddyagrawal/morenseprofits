"""Tests for src.web._format — Indian rupee + percentage formatters.

Load-bearing per DESIGN_SPEC §2.7:
  - Boundary cases at ₹1 L and ₹1 Cr (correct unit chosen on either side)
  - Negative sign placement (-₹1.25 L, not ₹-1.25 L) for columnar alignment
  - Zero rendered as bare "₹0" (no decimals, no L/Cr)
  - NaN / None → "—" so a single column-config formatter handles missing data
  - Sub-lakh comma grouping (₹6,923 not ₹6923)
  - format_pct sign + /yr toggles
  - format_pct base case has NO sign (used for win rates where there's nothing
    to compare against — everything is non-negative by construction)
"""
from __future__ import annotations

import math

import pytest

from src.web._format import format_inr, format_pct


# ============================================================
# format_inr — boundaries + sign + zero + empty
# ============================================================

def test_inr_zero_is_bare_rupee():
    assert format_inr(0) == "₹0"


def test_inr_sub_lakh_uses_comma_thousands():
    """< ₹1 L → nearest rupee, western thousands grouping."""
    assert format_inr(6923) == "₹6,923"
    assert format_inr(1) == "₹1"
    assert format_inr(99_999) == "₹99,999"


def test_inr_sub_lakh_rounds_to_nearest_rupee():
    assert format_inr(6923.49) == "₹6,923"
    assert format_inr(6923.50) == "₹6,924"  # banker's rounding aside; nearest
    assert format_inr(6923.99) == "₹6,924"


def test_inr_boundary_at_one_lakh_uses_L():
    """LOAD-BEARING: exactly ₹1 L flips to L notation; ₹99,999 stays
    in rupee notation. Pin both sides of the boundary."""
    assert format_inr(99_999) == "₹99,999"
    assert format_inr(100_000) == "₹1.00 L"


def test_inr_lakh_range_uses_two_decimals():
    assert format_inr(125_000) == "₹1.25 L"
    assert format_inr(2_580_000) == "₹25.80 L"
    assert format_inr(99_99_999) == "₹100.00 L"  # rounded up; almost ₹1 Cr


def test_inr_boundary_at_one_crore_uses_Cr():
    """LOAD-BEARING: ₹99,99,999 stays in L; ₹1,00,00,000 flips to Cr.
    Indian convention: 1 Cr = 100 L = 10^7."""
    assert format_inr(9_999_999) == "₹100.00 L"  # 99.99...L rounds to 100.00 L
    assert format_inr(10_000_000) == "₹1.00 Cr"


def test_inr_crore_range_uses_two_decimals():
    assert format_inr(12_500_000) == "₹1.25 Cr"
    assert format_inr(25_800_000) == "₹2.58 Cr"
    assert format_inr(258_000_000) == "₹25.80 Cr"


def test_inr_negative_sign_prefixes_rupee_glyph():
    """LOAD-BEARING for table alignment: '-' BEFORE '₹', not after.
    Columnar tables align on the rupee glyph; a trailing minus would
    visually disconnect from the magnitude."""
    assert format_inr(-6923) == "-₹6,923"
    assert format_inr(-125_000) == "-₹1.25 L"
    assert format_inr(-25_800_000) == "-₹2.58 Cr"


def test_inr_none_returns_em_dash():
    """None → '—' so column-config formatters render missing data
    consistently without per-cell NoneType crashes."""
    assert format_inr(None) == "—"


def test_inr_nan_returns_em_dash():
    """NaN → '—' (same reasoning as None)."""
    assert format_inr(float("nan")) == "—"


# ============================================================
# format_pct — base / signed / annualized
# ============================================================

def test_pct_base_no_sign_no_yr_suffix():
    """Default: 1 decimal, no sign. Used for win rates where the
    metric is non-negative by construction (no sign to display)."""
    assert format_pct(4.6) == "4.6%"
    assert format_pct(83.33) == "83.3%"
    assert format_pct(0.0) == "0.0%"


def test_pct_signed_prepends_plus_on_positives():
    """LOAD-BEARING for per-trade ROI columns: sign is informational.
    Positive → explicit '+'; negative → natural '-' from f-string."""
    assert format_pct(4.6, signed=True) == "+4.6%"
    assert format_pct(-3.24, signed=True) == "-3.2%"
    assert format_pct(0.0, signed=True) == "0.0%"  # zero is unsigned


def test_pct_annualized_appends_yr_suffix():
    assert format_pct(247.9, annualized=True) == "247.9%/yr"
    assert format_pct(247.9, signed=True, annualized=True) == "+247.9%/yr"
    assert format_pct(-89.1, signed=True, annualized=True) == "-89.1%/yr"


def test_pct_none_returns_em_dash():
    assert format_pct(None) == "—"


def test_pct_nan_returns_em_dash():
    assert format_pct(float("nan")) == "—"


def test_pct_already_scaled_to_100():
    """LOAD-BEARING convention: x=4.6 means 4.6%, NOT 0.046. Matches
    roi_pct + win_rate_pct semantics across the codebase. A change to
    "x is a fraction" would silently 100× every percentage in the UI."""
    # Spot-check that 1 means 1%, not 100%
    assert format_pct(1) == "1.0%"
    assert format_pct(100) == "100.0%"


# ============================================================
# format_pct + format_inr both NaN-safe in the same row
# ============================================================

def test_both_formatters_handle_nan_same_way():
    """A row with both a NaN net_pnl AND a NaN roi_pct renders as
    '— / —' in the UI — consistent missing-data presentation."""
    nan = float("nan")
    assert format_inr(nan) == format_pct(nan) == "—"
