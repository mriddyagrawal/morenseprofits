"""Cache-hit telemetry (SPECS §6a follow-up).

Phase-4 sweeps run thousands of loader calls. We want every one to hit
the parquet cache — an accidental network fetch slows the sweep by
orders of magnitude and (more importantly) can quietly inject look-ahead
bias if a refresh pulls in a row dated after the backtest's nominal
"now".

OPT-IN by design: warnings are silent unless ``MORENSE_WARN_ON_FETCH=1``.
A legitimate cold-cache run (e.g. ``verify_phase1_integration.py`` on a
fresh checkout) would otherwise emit dozens of warnings. Set the env
var inside sweep scripts to surface unexpected fetches; leave unset for
normal cache-population work.
"""
from __future__ import annotations

import os
import warnings

_ENV_VAR = "MORENSE_WARN_ON_FETCH"


def warn_on_fetch_enabled() -> bool:
    """Strict: only the literal ``"1"`` enables it."""
    return os.environ.get(_ENV_VAR) == "1"


def warn_fetch(loader_name: str, key: str) -> None:
    """Emit a single warning when a loader is about to hit the network.
    Caller invokes this AFTER the offline-check passed AND the cache-
    exists check failed — i.e. at the actual fetch-decision moment.

    No-op unless ``MORENSE_WARN_ON_FETCH=1`` is set.
    """
    if not warn_on_fetch_enabled():
        return
    warnings.warn(
        f"[{loader_name}] cache miss, fetching from NSE: {key}",
        stacklevel=3,
    )
