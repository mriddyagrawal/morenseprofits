"""Entry point: ``python -m src.mcp`` runs the MCP server over stdio.

Claude Code's MCP-config registers this command; the SDK handles
JSON-RPC framing over stdin/stdout. The server runs until the parent
process closes the streams (Claude Code session ends).

Async runtime (asyncio) is the SDK's requirement — the actual tool
handlers can be either sync or async, the runtime adapts.
"""
from __future__ import annotations

import asyncio

from mcp.server.stdio import stdio_server

from src.mcp import build_server


async def _run() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(_run())
