"""Chimera as an MCP server — peer-callable surface (v2.0+)."""

from .dialectic_tool import ASK_TOOL_NAME, register_ask_tool
from .http_server import build_http_app, serve_http
from .identity_tool import IDENTITY_TOOL_NAME, register_identity_tool
from .kfm_tool import KFM_STATE_TOOL_NAME, register_kfm_state_tool
from .mcp_server import ChimeraMCPServer, build_server, exposed_tool_names, serve_stdio
from .peer_auth import current_peer, load_token_map, resolve_peer_for_token

__all__ = [
    "ASK_TOOL_NAME",
    "ChimeraMCPServer",
    "IDENTITY_TOOL_NAME",
    "KFM_STATE_TOOL_NAME",
    "build_http_app",
    "build_server",
    "current_peer",
    "exposed_tool_names",
    "load_token_map",
    "register_ask_tool",
    "register_identity_tool",
    "register_kfm_state_tool",
    "resolve_peer_for_token",
    "serve_http",
    "serve_stdio",
]
