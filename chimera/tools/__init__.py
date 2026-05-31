"""Chimera tools: registry, dispatch pipeline, built-in tools."""

from .dispatch import (
    DispatchContext,
    Dispatcher,
    PolicyDecision,
    PolicyResult,
    ToolDenied,
    ToolError,
    ToolNotFound,
    ToolUnavailable,
    add_global_deny,
    clear_global_deny,
)
from .loop_guard import LoopVerdict, ToolCall, detect_degenerate_loop, detect_ping_pong, normalize_tool_input
from .registry import ToolEntry, ToolRegistry, default_registry
from .code_exec import register_code_exec_tool
from .mcp_client import (
    MCPServerConfig,
    parse_mcp_config,
    register_mcp_servers,
    register_mcp_servers_from_env,
)
from .git_commit import register_git_commit_tool
from .mind_search import register_mind_search
from .shell import SAFE_COMMANDS, register_shell_tool
from .subagent import SubAgentConfig, SubAgentRunner, register_sub_agent_tool
from .web import register_web_tools, web_search_available
from .write_intent import (
    extract_target_paths,
    requires_write_intent,
    silent_failure,
    write_intent_satisfied,
)

__all__ = [
    "DispatchContext",
    "Dispatcher",
    "PolicyDecision",
    "PolicyResult",
    "ToolDenied",
    "ToolError",
    "ToolNotFound",
    "ToolUnavailable",
    "ToolEntry",
    "ToolRegistry",
    "default_registry",
    "MCPServerConfig",
    "SAFE_COMMANDS",
    "parse_mcp_config",
    "register_code_exec_tool",
    "register_core_tools",
    "register_git_commit_tool",
    "register_mcp_servers",
    "register_mcp_servers_from_env",
    "register_mind_search",
    "register_shell_tool",
    "register_sub_agent_tool",
    "register_web_tools",
    "SubAgentConfig",
    "SubAgentRunner",
    "web_search_available",
    "add_global_deny",
    "clear_global_deny",
    "LoopVerdict",
    "ToolCall",
    "detect_degenerate_loop",
    "detect_ping_pong",
    "normalize_tool_input",
    "extract_target_paths",
    "requires_write_intent",
    "silent_failure",
    "write_intent_satisfied",
]


def register_core_tools(registry=None) -> None:
    """Register every built-in tool against the (default) registry.

    Idempotent — safe to call multiple times. New built-ins should be added
    here so the loop picks them up automatically.
    """
    register_shell_tool(registry)
    register_web_tools(registry)
    register_code_exec_tool(registry)
    # R4 (ADR 0150): atomic stage+commit affordance — collapses the commit
    # ritual the agent reliably under-executes into one gated tool call.
    register_git_commit_tool(registry)
    # v4.61: mind_search exposes the FTS5 wiki index to the agent.
    register_mind_search(registry)
