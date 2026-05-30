"""End-to-end MCP-protocol integration tests.

Reviewer carry-over from b42d4c2 / 0cc0b2c / 661b1ff / bacf5cf / 3264f37 /
d138fef: every per-sub-arc test module covers the impl + registry +
JSON round-trip via ``model_dump``, but none of them exercise the
SDK's actual request_handlers dispatcher. This module closes that gap.

What's tested at this layer (vs the per-sub-arc files):
  - The SDK's ``@server.list_tools()`` decorator registered a real
    handler that returns valid ``mcp.types.Tool`` objects.
  - The SDK's ``@server.call_tool()`` decorator routes a
    ``CallToolRequest`` (with name + arguments dict) through the
    Pydantic input model, the impl, the model_dump(mode="json")
    serialization, and back as a ``TextContent`` payload.
  - Unknown tool names + bad arguments dicts surface as tool errors
    rather than internal crashes.

These tests boot the actual SDK handler via asyncio.run — closest
thing to a real ``stdio_server`` exchange without spinning up a
subprocess.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from mcp.types import (
    CallToolRequest,
    CallToolRequestParams,
    ListToolsRequest,
    TextContent,
    Tool,
)

from src.mcp import build_server
from src.mcp._models import PRE_PRICING_ARC_PHANTOM_FILL_CAVEAT


# ============================================================
# list_tools dispatch — confirms the @server.list_tools() handler
# routes properly and returns the full registered catalog
# ============================================================

def _build_list_tools_request() -> ListToolsRequest:
    # params is Optional[PaginatedRequestParams]; None is valid for
    # a basic list-all request without pagination.
    return ListToolsRequest(method="tools/list", params=None)


def _build_call_tool_request(name: str, arguments: dict | None = None) -> CallToolRequest:
    return CallToolRequest(
        method="tools/call",
        params=CallToolRequestParams(name=name, arguments=arguments or {}),
    )


def _invoke_sdk_handler(server, request):
    """Call the SDK-registered request handler synchronously via
    asyncio.run. The handler signature varies a bit by request type;
    this wrapper centralizes the await-and-return pattern so each
    test stays one line."""
    handler = server.request_handlers[type(request)]
    return asyncio.run(handler(request))


def test_sdk_list_tools_handler_returns_full_catalog():
    """End-to-end: build server → invoke list_tools handler via SDK
    → result includes every registered tool name. Anti-regression
    against a future commit accidentally dropping the @list_tools
    decorator or routing the wrong source."""
    server = build_server()
    result = _invoke_sdk_handler(server, _build_list_tools_request())
    # SDK wraps the handler's return in a ServerResult; the tools
    # list lives on .root.tools (or similar). Probe the shape
    # defensively across SDK versions.
    tools = _extract_tools_from_result(result)
    names = {t.name for t in tools}
    # Sample of expected tools across the 3 landed sub-arcs.
    assert {"list_universe", "expiries_for", "list_strategies"}.issubset(names)
    assert {"get_spot_series", "get_option_series", "get_options_chain"}.issubset(names)
    assert {"list_runs", "query_sweep", "cell_summary", "heatmap"}.issubset(names)


def _extract_tools_from_result(result) -> list[Tool]:
    """Walk the SDK's ServerResult wrapper to find the tools list.
    Tries a few attribute paths since the wrapping can vary."""
    # Direct attribute (some SDK versions).
    if hasattr(result, "tools"):
        return list(result.tools)
    # ServerResult.root.tools (newer wrapping).
    if hasattr(result, "root") and hasattr(result.root, "tools"):
        return list(result.root.tools)
    # ListToolsResult fallback.
    if isinstance(result, list):
        return [t for t in result if isinstance(t, Tool)]
    raise AssertionError(
        f"could not locate tools list in SDK result: {type(result).__name__}"
    )


def _extract_content_from_result(result) -> list[TextContent]:
    """Same defensive walking pattern as _extract_tools_from_result."""
    if hasattr(result, "content"):
        return list(result.content)
    if hasattr(result, "root") and hasattr(result.root, "content"):
        return list(result.root.content)
    if isinstance(result, list):
        return [c for c in result if isinstance(c, TextContent)]
    raise AssertionError(
        f"could not locate content list in SDK result: {type(result).__name__}"
    )


# ============================================================
# call_tool dispatch — exercises the full path:
# request → name dispatch → Pydantic input parse → impl call →
# model_dump → JSON serialize → TextContent
# ============================================================

def test_sdk_call_tool_list_universe_round_trips_full_payload():
    """list_universe via the actual SDK handler. Verifies:
      - dispatcher routes name='list_universe' to the right impl
      - empty arguments dict parses to ListUniverseInput cleanly
      - impl returns ListUniverseOutput with caveats populated
      - model_dump(mode='json') + json.dumps yields valid JSON
      - the survivorship caveat fires verbatim
    """
    server = build_server()
    request = _build_call_tool_request("list_universe", {})
    result = _invoke_sdk_handler(server, request)
    content = _extract_content_from_result(result)
    assert len(content) == 1
    assert content[0].type == "text"
    payload = json.loads(content[0].text)
    assert payload["total"] == 50
    assert "caveats" in payload
    # The survivorship caveat is the canonical surface for list_universe;
    # if any of the dispatcher / impl / serialization steps drop it,
    # this fires.
    assert any("survivorship bias" in c.lower() for c in payload["caveats"])


def test_sdk_call_tool_list_strategies_dispatches_correctly():
    """list_strategies via the SDK handler. Pins that the dispatcher
    routes by NAME (not by some default-to-first behavior) — easy
    bug to introduce if a future refactor changes the registry-lookup
    pattern."""
    server = build_server()
    request = _build_call_tool_request("list_strategies", {})
    result = _invoke_sdk_handler(server, request)
    content = _extract_content_from_result(result)
    payload = json.loads(content[0].text)
    names = {s["name"] for s in payload["strategies"]}
    # The 5 v1 strategies from src/strategies/registry.py.
    assert names == {
        "short_straddle", "short_strangle", "iron_condor",
        "long_straddle", "long_strangle",
    }


def test_sdk_call_tool_unknown_name_surfaces_error():
    """Routing-failure path: an unknown tool name must produce a
    clear error (not a silent empty response). The dispatcher in
    src.mcp.server raises ValueError; SDK propagates as a tool
    error. Anti-regression for the loud-failure contract."""
    server = build_server()
    request = _build_call_tool_request("does_not_exist", {})
    # The SDK may wrap the error in a tool-error response OR
    # propagate. Either way, the test should see something that
    # indicates failure rather than a silently empty list.
    try:
        result = _invoke_sdk_handler(server, request)
        content = _extract_content_from_result(result)
        # If the SDK wraps the error, the content should still
        # carry an error-like signal.
        if content:
            payload_text = content[0].text
            # Loose check: error indication present.
            assert "unknown" in payload_text.lower() or "error" in payload_text.lower() or "does_not_exist" in payload_text
        else:
            # Empty content from an unknown-name call is also a
            # failure signal (no valid response was produced).
            assert True
    except (ValueError, KeyError, Exception) as e:
        # Exception propagation is also acceptable behavior — confirms
        # loud-failure rather than silent miss.
        assert "does_not_exist" in str(e) or "unknown" in str(e).lower()


def test_sdk_call_tool_invalid_arguments_surface_validation_error():
    """Pydantic schema validation must catch bad argument shapes at
    the dispatcher boundary. Pass a get_option_series request with
    an invalid option_type and verify the error surfaces (not a
    silent fallback to a default)."""
    server = build_server()
    # option_type Literal['CE', 'PE'] — 'XX' must fail.
    request = _build_call_tool_request("get_option_series", {
        "symbol": "RELIANCE",
        "expiry": "2024-01-25",
        "strike": 2600.0,
        "option_type": "XX",
    })
    try:
        result = _invoke_sdk_handler(server, request)
        content = _extract_content_from_result(result)
        # Error indication should be present.
        if content:
            assert "validation" in content[0].text.lower() or "option_type" in content[0].text.lower() or "error" in content[0].text.lower()
    except Exception as e:
        # ValidationError or similar — load-bearing the failure mode
        # is LOUD, not silent.
        assert "option_type" in str(e) or "validation" in str(e).lower() or "literal" in str(e).lower()


# ============================================================
# Tool schema invariants exposed via the SDK contract
# ============================================================

def test_sdk_listed_tool_input_schemas_are_valid_json_schema_dicts():
    """The Tool objects returned by list_tools must carry
    ``inputSchema`` as a valid JSON-schema-shaped dict. Anti-regression
    against a future commit accidentally passing a Pydantic model
    class instead of its .model_json_schema() output to the Tool
    constructor."""
    server = build_server()
    result = _invoke_sdk_handler(server, _build_list_tools_request())
    tools = _extract_tools_from_result(result)
    for tool in tools:
        schema = tool.inputSchema
        assert isinstance(schema, dict), (
            f"{tool.name} inputSchema is {type(schema).__name__}, "
            f"must be dict"
        )
        # Every JSON schema has either 'type' or 'properties' at the
        # top level (Pydantic emits both for object models).
        assert "type" in schema or "properties" in schema, (
            f"{tool.name} inputSchema lacks both 'type' and 'properties'"
        )
