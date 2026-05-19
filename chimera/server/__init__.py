"""Chimera as an MCP server — peer-callable surface (v2.0)."""

from .mcp_server import ChimeraMCPServer, build_server, exposed_tool_names, serve_stdio

__all__ = [
    "ChimeraMCPServer",
    "build_server",
    "exposed_tool_names",
    "serve_stdio",
]
