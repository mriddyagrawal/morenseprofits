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
