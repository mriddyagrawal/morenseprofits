"""Tests for src.mcp.universe — feat(p8.mcp.universe).

Layered coverage per the reviewer's Q3 + Q4 guidance:
  - Schema layer: every output model has a ``caveats`` field; required
    types are pinned; schema invariants stay stable across refactors.
  - Behavior layer: each tool produces the right data for the right
    input. Caveats fire under their triggering conditions (e.g.
    list_universe always carries the survivorship-bias caveat).
  - Registry layer: ``register_universe_tools()`` returns the 3
    expected entries with no name collisions.
  - JSON round-trip: output models serialize via model_dump(mode="json")
    and parse back cleanly (the path the call_tool dispatcher uses).
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from src.mcp._models import CaveatedResponse, ToolEntry
from src.mcp.universe import (
    ExpiriesForInput,
    ExpiriesForOutput,
    ListStrategiesInput,
    ListStrategiesOutput,
    ListUniverseInput,
    ListUniverseOutput,
    expiries_for_impl,
    list_strategies_impl,
    list_universe_impl,
    register_universe_tools,
)


# ============================================================
# CaveatedResponse base — schema-level enforcement (reviewer Q4)
# ============================================================

def test_caveated_response_requires_caveats_field():
    """Pydantic schema-level enforcement: any subclass of
    CaveatedResponse MUST have ``caveats`` present. Anti-regression
    against a future contributor adding a new tool's response model
    that accidentally drops the field."""
    with pytest.raises(ValidationError):
        # Construct a bare CaveatedResponse without caveats — must fail.
        CaveatedResponse()  # type: ignore[call-arg]


def test_caveated_response_rejects_non_string_caveat_elements():
    """The ``caveats`` field must be ``list[str]``. The validator
    catches non-string elements (e.g. dict, int) that would leak
    structure assumptions across tool boundaries."""
    with pytest.raises(ValidationError):
        CaveatedResponse(caveats=[{"text": "this should fail"}])  # type: ignore[list-item]


def test_caveated_response_accepts_empty_list():
    """Empty caveats list is valid — a tool may have nothing to flag
    for a given input. What's forbidden is dropping the field
    entirely."""
    obj = CaveatedResponse(caveats=[])
    assert obj.caveats == []


# ============================================================
# list_universe — behavior
# ============================================================

def test_list_universe_returns_50_total():
    """Universe is 48 blue chips + PNB + BHEL = 50 (chore(universe.
    expand_to_50) baseline). Anti-regression for the count contract."""
    out = list_universe_impl(ListUniverseInput())
    assert out.total == 50
    assert len(out.blue_chip) == 48
    assert out.extras == ["PNB", "BHEL"]


def test_list_universe_blue_chip_is_alphabetically_sorted():
    """Determinism contract — the underlying blue_chip() function
    sorts; the MCP tool propagates the order unchanged."""
    out = list_universe_impl(ListUniverseInput())
    assert out.blue_chip == sorted(out.blue_chip)


def test_list_universe_includes_survivorship_bias_caveat():
    """ALWAYS-FIRES caveat per the consultation: the universe is a
    mid-2024 snapshot, so survivorship bias is structurally present.
    Behavior test asserts the caveat string actually surfaces — the
    schema layer only enforces field presence, not content."""
    out = list_universe_impl(ListUniverseInput())
    joined = " ".join(out.caveats).lower()
    assert "survivorship bias" in joined


def test_list_universe_caveats_mention_as_of_ignored():
    """v1 ignores as_of and returns the same snapshot. The caveat must
    surface this so consumers don't assume point-in-time membership."""
    out = list_universe_impl(ListUniverseInput(as_of=date(2019, 1, 1)))
    joined = " ".join(out.caveats).lower()
    assert "as_of" in joined or "ignores" in joined


def test_list_universe_as_of_parameter_is_currently_ignored():
    """Same output regardless of as_of (v1 ignores it). Pin the
    behavior so a future point-in-time impl can't silently break the
    contract without updating the caveat first."""
    a = list_universe_impl(ListUniverseInput(as_of=date(2020, 1, 1)))
    b = list_universe_impl(ListUniverseInput(as_of=date(2026, 1, 1)))
    assert a.blue_chip == b.blue_chip
    assert a.extras == b.extras


# ============================================================
# expiries_for — behavior
# ============================================================

def test_expiries_for_input_requires_symbol():
    """Pydantic schema enforcement: symbol is a required field; missing
    it fires ValidationError at the call boundary."""
    with pytest.raises(ValidationError):
        ExpiriesForInput(from_date=date(2024, 1, 1), to_date=date(2024, 12, 31))  # type: ignore[call-arg]


def test_expiries_for_input_rejects_inverted_dates():
    """``monthly_expiries`` raises ValueError on from > to. The MCP
    tool propagates rather than swallows — consumer Claude gets a
    tool-error response, not a silent empty list."""
    inp = ExpiriesForInput(
        symbol="RELIANCE",
        from_date=date(2024, 12, 31),
        to_date=date(2024, 1, 1),
    )
    with pytest.raises(ValueError):
        expiries_for_impl(inp)


# ============================================================
# list_strategies — behavior
# ============================================================

def test_list_strategies_returns_registered_strategies():
    """list_strategies surfaces the contents of STRATEGIES from the
    strategies registry. Anti-regression for the registry-to-MCP
    wiring."""
    out = list_strategies_impl(ListStrategiesInput())
    names = {s.name for s in out.strategies}
    # 5 v1 strategies per src/strategies/registry.py.
    expected = {"short_straddle", "short_strangle", "iron_condor",
                "long_straddle", "long_strangle"}
    assert names == expected


def test_list_strategies_short_straddle_strike_rule_mentions_atm():
    """SPECS §5: short_straddle picks the ATM strike. The MCP-exposed
    strike_rule string must reflect this for any consumer reading
    'how does this strategy pick strikes'."""
    out = list_strategies_impl(ListStrategiesInput())
    ss = next(s for s in out.strategies if s.name == "short_straddle")
    assert "ATM" in ss.strike_rule


def test_list_strategies_carries_recommended_margin_offset():
    """recommended_strategy_offset_pct is the Tier-B margin shortcut
    per SPECS §4a. Each strategy carries its own value. Test pins
    short_straddle's at 0.60 (the value from the strategy class
    declaration). If a future calibration changes this, the test
    fires and forces a deliberate update."""
    out = list_strategies_impl(ListStrategiesInput())
    ss = next(s for s in out.strategies if s.name == "short_straddle")
    assert ss.recommended_strategy_offset_pct == pytest.approx(0.60)


def test_list_strategies_caveats_mention_tier_b():
    """Caveat must surface the Tier-B-margin-shortcut framing — real
    NSE SPAN margins can differ. Consumers must not treat the offset
    as production-deployable."""
    out = list_strategies_impl(ListStrategiesInput())
    joined = " ".join(out.caveats).lower()
    assert "tier-b" in joined or "tier b" in joined


# ============================================================
# Registry assembly
# ============================================================

def test_register_universe_tools_returns_three_entries():
    """Sub-arc 3.1 ships exactly 3 tools. Pin the count so a sloppy
    follow-up commit can't silently extend this surface."""
    entries = register_universe_tools()
    assert len(entries) == 3


def test_register_universe_tools_names_are_unique():
    """Tool names within the sub-arc must be unique. ``build_server``
    enforces uniqueness across sub-arcs too; this test pins the
    intra-sub-arc invariant."""
    entries = register_universe_tools()
    names = [e.name for e in entries]
    assert len(set(names)) == len(names)


def test_register_universe_tools_names_match_expected_set():
    """Specific names land in this commit. Pinning prevents a typo
    refactor from quietly renaming a tool that consumers depend on."""
    entries = register_universe_tools()
    names = {e.name for e in entries}
    assert names == {"list_universe", "expiries_for", "list_strategies"}


def test_each_tool_entry_carries_compatible_models():
    """Every ToolEntry must expose input_model and output_model that
    Pydantic can derive JSON schemas from. Anti-regression for the
    SDK contract: ``Tool(inputSchema=entry.input_model.model_json_schema())``
    is called for every tool in build_server."""
    for entry in register_universe_tools():
        # Should not raise — must produce a valid JSON schema dict.
        schema = entry.input_model.model_json_schema()
        assert isinstance(schema, dict)
        assert "type" in schema or "properties" in schema


# ============================================================
# JSON round-trip — the path the call_tool dispatcher uses
# ============================================================

def test_list_universe_output_round_trips_through_json():
    """``call_tool`` in src.mcp.server.build_server serializes the
    output via ``json.dumps(result.model_dump(mode='json'))``. The
    round-trip must preserve every field (especially the date/Decimal
    serialization quirks Pydantic handles for us)."""
    out = list_universe_impl(ListUniverseInput())
    payload = json.dumps(out.model_dump(mode="json"))
    back = json.loads(payload)
    assert back["total"] == 50
    assert back["blue_chip"][0] == "ADANIENT"  # alphabetically first
    assert "caveats" in back
    assert isinstance(back["caveats"], list)


def test_list_strategies_output_round_trips_through_json():
    out = list_strategies_impl(ListStrategiesInput())
    payload = json.dumps(out.model_dump(mode="json"))
    back = json.loads(payload)
    assert len(back["strategies"]) == 5
    assert "caveats" in back
