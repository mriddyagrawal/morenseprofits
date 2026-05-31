"""MCP server skeleton + cross-sub-arc tool registration.

The actual tool catalog lands across the p8.mcp sub-arc:
  - p8.mcp.universe        : list_universe / expiries_for / list_strategies
  - p8.mcp.spot_options    : get_spot_series / get_option_series / get_options_chain
  - p8.mcp.cell_summary    : cell_summary
  - p8.mcp.heatmap         : heatmap
  - p8.mcp.query_sweep     : list_runs / query_sweep
  - p8.mcp.backtest_one    : backtest_one
  - p8.mcp.sweep_windows   : sweep_windows
  - p8.mcp.skip_summary    : skip_summary
  - p8.mcp.data_quality    : data_quality
  - p8.mcp.compare_cells   : compare_cells (no-p-values constraint enforced)
  - p8.mcp.bootstrap       : bootstrap_ci

This file owns the server-construction contract: ``build_server()``
returns a fully-configured ``mcp.server.Server`` instance with every
landed tool registered. Each tool sub-arc adds a ``register_*_tools``
function call below — single-place visibility into "what tools exist".

Why a ``build_server`` factory rather than a module-level singleton:
tests can call ``build_server()`` to construct an isolated server
instance, register / inspect tools, and tear down without polluting
each other's state. Production (the ``__main__`` entry point) calls
the same factory.

Why a single ``@server.list_tools()`` + ``@server.call_tool()`` pair
rather than per-sub-arc decorators: the MCP SDK's decorators REPLACE
the handler on each call. Aggregating into one pair via the
``ToolEntry`` registry is the canonical pattern for multi-sub-arc
tool catalogs.
"""
from __future__ import annotations

import json
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from src.mcp._models import ToolEntry
from src.mcp.backtest_one import register_backtest_one_tools
from src.mcp.cell_summary import register_cell_summary_tools
from src.mcp.heatmap import register_heatmap_tools
from src.mcp.skip_summary import register_skip_summary_tools
from src.mcp.spot_options import register_spot_options_tools
from src.mcp.sweep_query import register_sweep_query_tools
from src.mcp.sweep_windows import register_sweep_windows_tools
from src.mcp.universe import register_universe_tools


SERVER_NAME = "morenseprofits"


def _collect_tool_entries() -> dict[str, ToolEntry]:
    """Aggregate every sub-arc's ToolEntry list into a single
    name → entry dict. Failure on duplicate names is intentional —
    catches a copy-paste accident across sub-arcs at server-build
    time rather than at runtime."""
    all_entries: list[ToolEntry] = []
    all_entries.extend(register_universe_tools())
    all_entries.extend(register_spot_options_tools())
    all_entries.extend(register_sweep_query_tools())
    all_entries.extend(register_cell_summary_tools())
    all_entries.extend(register_heatmap_tools())
    all_entries.extend(register_backtest_one_tools())
    all_entries.extend(register_sweep_windows_tools())
    all_entries.extend(register_skip_summary_tools())
    # Future sub-arcs append here:
    # all_entries.extend(register_data_quality_tools())
    # ... etc.

    registry: dict[str, ToolEntry] = {}
    for entry in all_entries:
        if entry.name in registry:
            raise ValueError(
                f"duplicate MCP tool name {entry.name!r} — two "
                f"sub-arcs registered the same name"
            )
        registry[entry.name] = entry
    return registry


def build_server() -> Server:
    """Construct the MCP Server with every landed tool registered.

    Tool registration happens here (not at module import time) so
    each ``build_server()`` call returns a fresh, isolated Server
    instance. Tests rely on this for non-singleton semantics.
    """
    server: Server = Server(SERVER_NAME)
    registry = _collect_tool_entries()

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name=entry.name,
                description=entry.description,
                inputSchema=entry.input_model.model_json_schema(),
            )
            for entry in registry.values()
        ]

    @server.call_tool()
    async def _call_tool(
        name: str, arguments: dict[str, Any] | None,
    ) -> list[TextContent]:
        if name not in registry:
            raise ValueError(
                f"unknown tool {name!r}. Available: "
                f"{sorted(registry.keys())}"
            )
        entry = registry[name]
        # Pydantic does the input-schema validation; an invalid
        # arguments dict raises ValidationError which the SDK
        # surfaces to the consumer as a tool-error response.
        parsed = entry.input_model(**(arguments or {}))
        result = entry.impl(parsed)
        # Output is a Pydantic model; serialize to JSON string for
        # the TextContent payload. ``mode="json"`` ensures date
        # fields round-trip as ISO strings (the natural form for
        # consumers reading JSON).
        payload = json.dumps(result.model_dump(mode="json"), default=str)
        return [TextContent(type="text", text=payload)]

    return server
