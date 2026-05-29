"""morenseprofits MCP server — read-only research API exposing the
sweep dataset, time-series cache, and analytical helpers to external
Claude instances.

Design + scope locked in 2026-05-30 consultation:
  - 16 read-only tools across 7 sub-arc groupings
  - stdio transport only (Claude Code CLI integration); no HTTP
  - Every aggregated tool returns ``caveats: list[str]`` enforced via
    Pydantic schema validators
  - No-p-values constraint on ``compare_cells`` enforced via the
    same banned-phrase regex pattern as the dashboard

This commit (chore(p8.mcp.skeleton)) ships only the bare server
boots. Tool implementations land in subsequent commits per the
nuclear-commits roadmap.

Run: ``python -m src.mcp``  (or via Claude Code's MCP config; see
``docs(p8.mcp.contract)`` once it lands).
"""
from __future__ import annotations

from src.mcp.server import build_server

__all__ = ["build_server"]
