"""Chimera as an MCP server — peer-callable surface (v2.0+)."""

from .identity_tool import IDENTITY_TOOL_NAME, register_identity_tool
from .kfm_tool import KFM_STATE_TOOL_NAME, register_kfm_state_tool
from .mcp_server import ChimeraMCPServer, build_server, exposed_tool_names, serve_stdio

__all__ = [
    "ChimeraMCPServer",
    "IDENTITY_TOOL_NAME",
    "KFM_STATE_TOOL_NAME",
    "build_server",
    "exposed_tool_names",
    "register_identity_tool",
    "register_kfm_state_tool",
    "serve_stdio",
]
