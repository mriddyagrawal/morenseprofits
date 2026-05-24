"""Offline-mode helper. SPECS §6a.

Every public loader (load_spot, load_bhavcopy_fo, load_option,
monthly_expiries, trading_days, offset_trading_days) accepts an
``offline: bool = False`` keyword. When True, a cache miss raises
``OfflineCacheMiss`` instead of falling back to network.

The env var ``MORENSE_OFFLINE=1`` flips on offline mode for every loader
in the process — useful for CI runs against a pre-populated cache, or
for reproducibility audits that must not silently re-fetch.

``offline=True`` AND ``force_refresh=True`` are CONTRADICTORY — offline
takes precedence (we never hit the network, period). Loaders document this.
"""
from __future__ import annotations

import os

_ENV_VAR = "MORENSE_OFFLINE"


def effective_offline(offline_kwarg: bool) -> bool:
    """Return whether the loader should treat itself as offline.

    Either the caller's ``offline=True`` or the env var ``MORENSE_OFFLINE=1``
    enables it. The env var lets a top-level script flip every loader
    in the process at once."""
    return bool(offline_kwarg) or os.environ.get(_ENV_VAR) == "1"
