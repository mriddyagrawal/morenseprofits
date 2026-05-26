"""Project-wide pytest fixtures.

Autouse fixtures keep cross-test state from leaking:
- ``cache._root_verified`` (first test to redirect CACHE_DIR could
  leave a stale True flag visible to later tests).
- The per-loader LRU caches added in the data-layer perf commit —
  tests that mock NSE fetches expect each call to hit the mock, but
  the LRU would silently serve a memoized DataFrame from a prior
  test's data instead.

Belt + suspenders on both fronts."""
from __future__ import annotations

import pytest

from src.data import cache
from src.data import bhavcopy_fo_loader, options_loader, spot_loader


@pytest.fixture(autouse=True)
def _reset_cache_root_memo():
    cache._reset_root_memo()
    yield
    cache._reset_root_memo()


@pytest.fixture(autouse=True)
def _reset_loader_lru_caches():
    """Clear data-layer LRU caches before AND after every test so a
    test's mocked fetches can't be eclipsed by a memoized result from
    a previous test."""
    spot_loader._load_year_cached.cache_clear()
    bhavcopy_fo_loader._load_bhavcopy_fo_cached.cache_clear()
    options_loader._load_full_contract_cached.cache_clear()
    yield
    spot_loader._load_year_cached.cache_clear()
    bhavcopy_fo_loader._load_bhavcopy_fo_cached.cache_clear()
    options_loader._load_full_contract_cached.cache_clear()
