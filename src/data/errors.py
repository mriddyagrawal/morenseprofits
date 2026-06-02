"""Project-wide data-layer error taxonomy. SPECS §8.

Centralized here so future modules (`options_loader`, `expiry_calendar`,
engine) can import without circular dependencies. Add new classes here as
modules need them — module-co-located error classes are fine for purely
internal exceptions (see `cache.py`), but anything callers may catch
belongs here.
"""
from __future__ import annotations


class DataError(Exception):
    """Base for all data-layer errors."""


class BhavcopyFormatError(DataError):
    """CSV header matches neither the pre-Jul-8-2024 (BHAVDATA-FULL) nor the
    ≥Jul-8-2024 (UDiff) schema. Raised loud instead of falling through to a
    permissive parser — a future NSE format change is an error, not a
    silent partial-fill."""


class OptionsFormatError(DataError):
    """`derivatives_df` returned a frame whose shape or content violates the
    options_loader's invariants (non-midnight DATE, duplicate trading dates,
    etc.). Loud-failure replacement for `assert` statements that would be
    stripped under ``python -O``."""


class LookaheadError(DataError):
    """The engine consulted market data dated past the trade's
    ``exit_date``. SPECS §3b — the kernel must NEVER read post-exit
    rows. A frame returned by a loader that contains such rows is
    treated as a code bug, not a recoverable data issue, and surfaces
    here loudly before any P&L number is produced."""


class OfflineCacheMiss(DataError):
    """``offline=True`` (or env ``MORENSE_OFFLINE=1``) was requested but
    the on-disk cache didn't have what was asked for.

    DISTINCT FROM ``MissingDataError`` by design — Phase 1.3.2's
    expiry_calendar catches ``MissingDataError`` to skip candidate
    non-trading days; under offline mode we want it to PROPAGATE so the
    operator sees "you asked offline + we don't have this cached" rather
    than the calendar quietly returning [] across the board."""


class MissingDataError(DataError):
    """Required upstream data is unavailable for the requested key. Examples:
    no F&O bhavcopy for a non-trading day (weekend, NSE holiday); no traded
    option price for a leg on a required entry/exit date; missing spot row.

    Callers iterating candidate dates (e.g. expiry-calendar building) use
    this to distinguish "no data here" from "the network blew up" — the
    latter raises `requests.RequestException` and is NOT wrapped."""


class CrossSourceLotSizeMismatchError(DataError):
    """Reserved for a future strict-mode flag on
    ``scripts/build_lot_size_parquet.py``. Not raised under the
    default per-pair-exclude policy (operator direction 2026-06-03 —
    see MIGRATION.md §Cross-source lot-size policy).

    Under the default policy, lot_size mismatches at any of the 3
    layers (sidecar-vs-sidecar / bhavcopy-internal / sidecar-vs-
    bhavcopy) cause the offending ``(symbol, expiry_month)`` pair to
    be DROPPED from the unified cache; the build still succeeds.
    Downstream pricing for cells touching those contracts skips with
    ``MissingTurnoverError`` (the lookup returns no row → transform
    can't derive volume in shares).

    Class retained in the taxonomy in case a future strict-mode flag
    needs to reactivate loud-fail behavior (e.g. for debugging an
    unexpected mismatch pattern)."""


class MissingTurnoverError(MissingDataError):
    """Raised by the bhavcopy-to-contract transform (P1.3) and by
    ``src.engine.pnl._pick_fill_price`` (P1.7) when the engine cannot
    derive ``volume = contracts × lot_size`` or compute the per-share
    premium VWAP because lot_size / turnover / volume is missing.

    Three trigger paths converge here:
    1. Lot-size unified cache miss — the ``(symbol, expiry-month)``
       pair was EXCLUDED from ``data/cache/lot_sizes.parquet`` due to
       a cross-source lot_size mismatch (per MIGRATION.md §Cross-
       source lot-size policy).
    2. Bhavcopy row has missing / NaN / zero turnover or volume
       (rare; typically NSE settlement-only rows with no actual
       trading).
    3. Deep-OTM ill-conditioning (P1.7 case (3) preservation) is
       handled SEPARATELY — falls through to close, does NOT raise.

    Subclass of ``MissingDataError`` so the sweeper's existing
    ``_SKIPPABLE_ERRORS = (MissingDataError, NoLiquidStrikeError)``
    catches it without code change. The exception class name becomes
    the ``skip_reason`` token in the skip parquet (per the sweeper's
    ``_handle`` extraction at line 322-326).

    See MIGRATION.md §Phase 1 P1.7 + the dce9a87 case-disambiguation
    commit body for the full pricing-path design."""


class IlliquidLegError(MissingDataError):
    """Raised by ``src.engine.pnl._price_one_leg`` when a leg's entry or
    exit row had ZERO traded contracts that day, or when the entry's
    open interest was zero. The engine refuses to book a trade against
    a "fill" that never happened — a published close with volume=0 is
    NSE's theoretical fallback, not a price any participant transacted
    at. Surfaces as a clean skip in ``sweep_*_skipped.parquet`` with
    skip_reason="IlliquidLegError" via the existing sweeper machinery
    that already catches ``MissingDataError``.

    NOTE: this is a research-honesty improvement, not a deploy-
    readiness signal. "Backtest skips a zero-volume cell" ≠ "a real
    broker can fill at the surviving cells' assumed prices" — the
    latter requires broker-API smoke tests before any rule is run with
    real capital."""
