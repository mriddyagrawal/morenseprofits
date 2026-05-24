"""Project-wide pytest fixtures.

Currently: an autouse fixture that resets `cache._root_verified` between
tests so the module-level memoization (added in fix(p1.1.a)) can't leak
state across test cases. The first test to redirect `cache.CACHE_DIR`
would otherwise leave a stale `True` flag visible to later tests, and
debugging that one day would be miserable. Belt + suspenders.
"""
from __future__ import annotations

import pytest

from src.data import cache


@pytest.fixture(autouse=True)
def _reset_cache_root_memo():
    cache._reset_root_memo()
    yield
    cache._reset_root_memo()
