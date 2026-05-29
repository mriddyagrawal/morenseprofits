"""MCP server skeleton — zero tools registered at this stage.

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
landed tool registered. Each tool sub-arc adds a ``_register_<topic>``
function called from ``build_server`` — single-place visibility into
"what tools exist".

Why a ``build_server`` factory rather than a module-level singleton:
tests can call ``build_server()`` to construct an isolated server
instance, register / inspect tools, and tear down without polluting
each other's state. Production (the ``__main__`` entry point) calls
the same factory.
"""
from __future__ import annotations

from mcp.server import Server


SERVER_NAME = "morenseprofits"


def build_server() -> Server:
    """Construct the MCP Server with every landed tool registered.

    Currently empty — chore(p8.mcp.skeleton) lands the boot contract
    without any tools. Subsequent commits in the p8.mcp arc each add
    a ``_register_*`` call below.
    """
    server: Server = Server(SERVER_NAME)
    # No tools registered yet. Tool-registration calls land in the
    # subsequent p8.mcp.* commits.
    return server
