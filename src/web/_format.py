"""Indian-number formatting + percentage helpers for the Phase-6 UI.

DESIGN_SPEC §2.7 contract — every card + table column that renders a
rupee value or percentage calls one of these two helpers. One source
of truth so "AVG ROI ₹25.76 L" mockup-style bugs (rupees mislabeled
as percentage) become a code-enforced contract: rupees go through
``format_inr``, percentages go through ``format_pct``.

Pure functions; no streamlit imports (testable in regular pytest).

Indian lakhs/crores convention:
  - <  ₹1 lakh   → ₹X,XXX     nearest rupee, comma-grouped
  - ₹1-99 lakh   → ₹X.XX L    2 decimals
  - ≥ ₹1 crore   → ₹X.XX Cr   2 decimals
  - negatives    → minus sign prefixes the ₹: -₹1.25 L
  - zero         → ₹0

Note: India uses 1 lakh = 100,000 and 1 crore = 10,000,000 = 100 lakh.
The "8-digit lakh comma" convention (₹1,25,000 not ₹125,000) is NOT
used here for sub-lakh values because:
  (a) Streamlit's monospace tables read more cleanly with western
      thousands grouping at this scale;
  (b) Lakh/crore notation kicks in at exactly the point where 8-digit
      grouping starts to matter (≥ ₹1 L), so the convention is preserved
      where it's useful.
"""
from __future__ import annotations

# Internal constants — Indian numbering boundaries.
_LAKH: int = 100_000           # 1 L = 10^5
_CRORE: int = 10_000_000       # 1 Cr = 10^7 = 100 lakh


def format_inr(x: float | int) -> str:
    """Format a rupee amount per DESIGN_SPEC §2.7.

    Examples:
        format_inr(6923)        → '₹6,923'
        format_inr(125_000)     → '₹1.25 L'
        format_inr(2_580_000)   → '₹25.80 L'
        format_inr(25_800_000)  → '₹2.58 Cr'
        format_inr(-6923)       → '-₹6,923'
        format_inr(0)           → '₹0'

    Special cases:
      - 0 → '₹0' (no decimals; the bare zero reads as "no money")
      - negatives carry a leading '-' BEFORE the '₹' so columnar tables
        stay aligned at the rupee glyph
      - NaN / inf are returned as the string literal (caller renders
        an em-dash or 'N/A' in their column-config formatter if they
        want a different empty representation)
    """
    if x is None:
        return "—"
    try:
        # NaN check via the standard "self-inequality" trick — avoids
        # an import on math.isnan.
        if x != x:
            return "—"
    except TypeError:
        return str(x)

    if x == 0:
        return "₹0"

    sign = "-" if x < 0 else ""
    mag = abs(x)

    if mag >= _CRORE:
        return f"{sign}₹{mag / _CRORE:.2f} Cr"
    if mag >= _LAKH:
        return f"{sign}₹{mag / _LAKH:.2f} L"
    # Sub-lakh → western thousands grouping
    return f"{sign}₹{int(round(mag)):,}"


def format_pct(
    x: float | int,
    *,
    signed: bool = False,
    annualized: bool = False,
) -> str:
    """Format a percentage per DESIGN_SPEC §2.7.

    Args:
      x: the percentage value as already-scaled-to-100 (i.e. 4.6 means
        4.6%, not 0.046). Matches the convention used everywhere else
        in the codebase (roi_pct, win_rate_pct).
      signed: prepend a '+' on positives (e.g. "+4.6%"). Used for
        per-trade ROI columns where the sign carries information.
        Default False → "4.6%" (used for win rates, where everything
        is non-negative by construction).
      annualized: append "/yr" suffix. Used for `roi_pct_annualized`
        and any annualized chart axis label.

    Examples:
        format_pct(4.6)                            → '4.6%'
        format_pct(4.6, signed=True)               → '+4.6%'
        format_pct(-3.24, signed=True)             → '-3.24%' (sign auto)
        format_pct(247.9, signed=True,
                   annualized=True)                → '+247.9%/yr'
        format_pct(83.33)                          → '83.3%'   (win rate)

    NaN / None → '—' for graceful table rendering.
    """
    if x is None:
        return "—"
    try:
        if x != x:  # NaN
            return "—"
    except TypeError:
        return str(x)

    sign_char = ""
    if signed and x > 0:
        sign_char = "+"
    # Negative sign comes naturally from the f-string; explicit sign
    # is only needed on the positive branch.
    body = f"{sign_char}{x:.1f}%"
    if annualized:
        body += "/yr"
    return body
