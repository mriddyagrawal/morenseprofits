"""Tests for src.mcp — Phase-8 MCP server skeleton.

This module pins the boot-contract invariants for the bare server
that ships in chore(p8.mcp.skeleton): factory function exists,
returns the right shape, server has the right name. Subsequent
p8.mcp.* commits add per-tool tests in companion modules.
"""
from __future__ import annotations

from mcp.server import Server

from src.mcp import build_server
from src.mcp.server import SERVER_NAME


def test_build_server_returns_mcp_server_instance():
    """Factory contract: build_server() must return an instance of
    the SDK's Server class so the __main__ runner can hand it to
    stdio_server(). Anti-regression against accidentally returning
    something duck-typed but not actually a Server."""
    server = build_server()
    assert isinstance(server, Server)


def test_server_name_is_canonical():
    """Server name is the identifier Claude Code uses in its MCP
    config + the prefix in tool addressing. Pin it so a future rename
    can't drift the operator's config silently."""
    assert SERVER_NAME == "morenseprofits"
    # Also assert the constructed instance carries the name through.
    server = build_server()
    assert getattr(server, "name", None) == SERVER_NAME


def test_server_registers_call_tool_dispatcher():
    """``build_server`` registers a single ``@server.call_tool()``
    dispatcher that routes by tool name into the per-sub-arc impl
    via the ToolEntry registry. This test pins the wiring contract:
    after build, the SDK's request_handlers dict carries a
    CallToolRequest entry. Anti-regression against a future refactor
    that accidentally drops the dispatcher decoration.

    Note: the original p8.mcp.skeleton test asserted the OPPOSITE
    (zero tools registered). Once feat(p8.mcp.universe) landed the
    first 3 tools, the dispatcher became load-bearing — flipped the
    assertion to reflect the new contract."""
    server = build_server()
    from mcp.types import CallToolRequest, ListToolsRequest
    # Both list_tools and call_tool decorators must have fired in
    # build_server. The SDK's request_handlers dict carries one entry
    # per registered request type.
    assert CallToolRequest in server.request_handlers
    assert ListToolsRequest in server.request_handlers


def test_build_server_is_idempotent_across_calls():
    """Each build_server() call must construct a fresh instance —
    not return a cached singleton. Tests rely on this to construct
    isolated servers without polluting each other's state."""
    a = build_server()
    b = build_server()
    assert a is not b
