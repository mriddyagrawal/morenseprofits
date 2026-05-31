"""Tests for src.mcp.bootstrap_ci — feat(p8.mcp.bootstrap_ci).

The tool is a thin wrapper around src.analytics.bootstrap.bootstrap_ci
that adds Pydantic input validation + small-n + cap caveats + method
string construction. Tests focus on the wrapper behavior, not the
underlying numpy bootstrap (which has its own tests in test_analytics).
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from src.mcp.bootstrap_ci import (
    MAX_VALUES,
    MIN_VALUES_FOR_CI,
    BootstrapCIInput,
    bootstrap_ci_impl,
    register_bootstrap_ci_tools,
)


# ============================================================
# Happy path
# ============================================================

def test_bootstrap_ci_returns_three_finite_values_for_n_geq_2():
    """n=10 distinct values → CI is well-defined; point and bounds
    are finite floats."""
    out = bootstrap_ci_impl(BootstrapCIInput(
        values=[float(i) for i in range(1, 11)],
    ))
    assert out.point_estimate is not None
    assert out.ci_lo is not None
    assert out.ci_hi is not None
    assert out.ci_lo <= out.point_estimate <= out.ci_hi
    assert out.n_input == 10
    assert out.n_finite == 10
    assert "B=1000" in out.method
    assert "seed=0" in out.method
    assert "statistic=median" in out.method


def test_bootstrap_ci_deterministic_with_same_seed():
    """Same seed → byte-identical bounds across runs. Pin the
    reproducibility contract."""
    inp = BootstrapCIInput(values=[float(i) for i in range(1, 51)])
    out_a = bootstrap_ci_impl(inp)
    out_b = bootstrap_ci_impl(inp)
    assert out_a.ci_lo == out_b.ci_lo
    assert out_a.ci_hi == out_b.ci_hi


def test_bootstrap_ci_supports_mean_statistic():
    out = bootstrap_ci_impl(BootstrapCIInput(
        values=[float(i) for i in range(1, 11)], statistic="mean",
    ))
    # Mean of 1..10 = 5.5
    assert out.point_estimate == pytest.approx(5.5, abs=1e-9)
    assert "statistic=mean" in out.method


def test_bootstrap_ci_alpha_changes_bounds():
    """α=0.50 → 50% CI (tighter); α=0.05 → 95% CI (wider). Mean width
    increases as α decreases."""
    values = [float(i) for i in range(1, 51)]
    out_narrow = bootstrap_ci_impl(BootstrapCIInput(
        values=values, alpha=0.50,
    ))
    out_wide = bootstrap_ci_impl(BootstrapCIInput(
        values=values, alpha=0.05,
    ))
    narrow_width = out_narrow.ci_hi - out_narrow.ci_lo
    wide_width = out_wide.ci_hi - out_wide.ci_lo
    assert wide_width > narrow_width


# ============================================================
# Failure / boundary behavior
# ============================================================

def test_bootstrap_ci_n_lt_min_returns_none_with_caveat():
    """LOAD-BEARING: n=1 → CI undefined per analytics layer; bootstrap_ci
    surfaces None bounds + an explicit caveat naming MIN_VALUES_FOR_CI
    rather than raising."""
    out = bootstrap_ci_impl(BootstrapCIInput(values=[5.0]))
    assert out.point_estimate is None
    assert out.ci_lo is None
    assert out.ci_hi is None
    assert any("MIN_VALUES_FOR_CI" in c for c in out.caveats)


def test_bootstrap_ci_small_n_caveat_fires_below_min_n_for_ranking():
    """LOAD-BEARING: n=3 is above MIN_VALUES_FOR_CI (=2) but below
    MIN_N_FOR_RANKING (=5). CI computed but caveat surfaces."""
    from src.analytics.aggregate import MIN_N_FOR_RANKING
    out = bootstrap_ci_impl(BootstrapCIInput(values=[1.0, 2.0, 3.0]))
    assert out.point_estimate is not None  # CI computed
    assert any("MIN_N_FOR_RANKING" in c for c in out.caveats)


def test_bootstrap_ci_drops_nans_before_computing():
    """NaN entries don't crash and aren't counted in n_finite."""
    values_with_nans = [1.0, 2.0, float("nan"), 3.0, float("nan"), 4.0, 5.0]
    out = bootstrap_ci_impl(BootstrapCIInput(values=values_with_nans))
    assert out.n_input == 7
    assert out.n_finite == 5  # NaNs dropped
    assert out.point_estimate is not None


def test_bootstrap_ci_input_rejects_empty_values():
    """Pydantic min_length=1 enforces non-empty input at schema layer."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        BootstrapCIInput(values=[])


def test_bootstrap_ci_input_rejects_alpha_at_one_or_more():
    """Pydantic lt=1.0 enforces alpha < 1.0; alpha=1.0 is a degenerate
    CI."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        BootstrapCIInput(values=[1.0, 2.0], alpha=1.0)


def test_bootstrap_ci_input_rejects_values_exceeding_cap():
    """LOAD-BEARING: MAX_VALUES is enforced at the SCHEMA layer
    (max_length on the values Field), not the impl layer. Inputs >
    MAX_VALUES fail at BootstrapCIInput construction with
    ValidationError — same idiom as alpha < 1.0 and min_length=1
    checks. This means MCP clients see the cap in the tool-discovery
    JSON schema, and the rejection fires before any impl code runs.
    Anti-regression against a future contributor moving the check
    back into the impl as a runtime ValueError."""
    from pydantic import ValidationError
    too_many = [float(i) for i in range(MAX_VALUES + 1)]
    with pytest.raises(ValidationError):
        BootstrapCIInput(values=too_many)


# ============================================================
# Registry assembly + final tool count
# ============================================================

def test_register_bootstrap_ci_tools_returns_one_entry():
    entries = register_bootstrap_ci_tools()
    assert len(entries) == 1
    assert entries[0].name == "bootstrap_ci"


def test_server_registry_now_exposes_bootstrap_ci_and_all_16_tools():
    """LOAD-BEARING: bootstrap_ci closes sub-arc 3.6 and the MCP arc
    reaches its planned 16-tool count. Pin the full registry contents
    so this is the authoritative tool catalog."""
    from src.mcp.server import _collect_tool_entries
    registry = _collect_tool_entries()
    expected = {
        # Sub-arc 3.1 universe (3)
        "list_universe", "expiries_for", "list_strategies",
        # Sub-arc 3.2 time-series (3)
        "get_spot_series", "get_option_series", "get_options_chain",
        # Sub-arc 3.3 sweep queries (4)
        "list_runs", "query_sweep", "cell_summary", "heatmap",
        # Sub-arc 3.4 backtest replay (2)
        "backtest_one", "sweep_windows",
        # Sub-arc 3.5 diagnostics (2)
        "skip_summary", "data_quality",
        # Sub-arc 3.6 research helpers (2)
        "compare_cells", "bootstrap_ci",
    }
    assert set(registry.keys()) == expected
    assert len(registry) == 16


# ============================================================
# JSON round-trip
# ============================================================

def test_bootstrap_ci_output_round_trips_through_json():
    out = bootstrap_ci_impl(BootstrapCIInput(
        values=[float(i) for i in range(1, 21)],
    ))
    payload = json.dumps(out.model_dump(mode="json"))
    back = json.loads(payload)
    assert back["n_input"] == 20
    assert back["n_finite"] == 20
    assert "caveats" in back
    assert "B=1000" in back["method"]
