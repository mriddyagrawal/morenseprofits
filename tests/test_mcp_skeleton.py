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


def test_skeleton_registers_zero_tools():
    """chore(p8.mcp.skeleton)'s scope is deliberately empty: the boot
    contract lands first, tools register in subsequent p8.mcp.*
    commits. Pin zero registered tools so a sloppy follow-up can't
    sneak undocumented tools into this commit's surface."""
    server = build_server()
    # Probe the SDK's internal handler registry. The exact attribute
    # name has shifted across SDK versions; check the canonical
    # public-ish accessor first, fall back to the registry dict.
    if hasattr(server, "request_handlers"):
        # Tool-registration adds entries to request_handlers for the
        # CallToolRequest type. Absent any tools registered, this dict
        # should not contain a CallToolRequest handler.
        from mcp.types import CallToolRequest
        assert CallToolRequest not in server.request_handlers


def test_build_server_is_idempotent_across_calls():
    """Each build_server() call must construct a fresh instance —
    not return a cached singleton. Tests rely on this to construct
    isolated servers without polluting each other's state."""
    a = build_server()
    b = build_server()
    assert a is not b
