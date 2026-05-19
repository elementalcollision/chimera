"""MCP client — discover and dispatch external Model Context Protocol tools.

Per ADR 0001 §"MCP client": uses the official ``mcp`` Python SDK. Discovers
tools from configured stdio servers and registers them under an ``mcp-<server>``
toolset; the dispatcher routes calls back to the originating server.

Connection lifetime is per-call (ephemeral) at MVP. The persistent-session
optimization is a follow-up — measured cost first, then optimization.

Config shape (``CHIMERA_MCP_SERVERS`` env var, JSON):

.. code-block:: json

    {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/mind"]
      },
      "github": {
        "command": "gh-mcp-server",
        "env": {"GITHUB_TOKEN": "..."}
      }
    }

Any failure during discovery is logged and the affected server's tools
are simply absent from the registry. Chimera keeps running.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from .dispatch import DispatchContext
from .registry import ToolRegistry, default_registry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MCPServerConfig:
    """One configured MCP server."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)


def parse_mcp_config(raw: str | None) -> dict[str, MCPServerConfig]:
    """Parse ``CHIMERA_MCP_SERVERS`` JSON into a name → config map.

    Empty/missing input → empty dict. Malformed JSON → empty dict + warning.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("CHIMERA_MCP_SERVERS is not valid JSON: %s", exc)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("CHIMERA_MCP_SERVERS must be a JSON object")
        return {}
    out: dict[str, MCPServerConfig] = {}
    for name, body in parsed.items():
        if not isinstance(body, dict) or not body.get("command"):
            logger.warning("CHIMERA_MCP_SERVERS[%s]: missing 'command'", name)
            continue
        out[name] = MCPServerConfig(
            name=name,
            command=str(body["command"]),
            args=tuple(str(a) for a in body.get("args") or ()),
            env={str(k): str(v) for k, v in (body.get("env") or {}).items()},
        )
    return out


async def _open_session(config: MCPServerConfig):
    """Open an MCP stdio session and return (cm, session) — caller must aclose."""
    # Imports kept lazy so the module loads even when the MCP SDK is missing.
    from mcp import ClientSession, StdioServerParameters  # type: ignore
    from mcp.client.stdio import stdio_client  # type: ignore

    env = {**os.environ, **config.env}
    params = StdioServerParameters(
        command=config.command,
        args=list(config.args),
        env=env,
    )
    cm = stdio_client(params)
    read, write = await cm.__aenter__()
    session_cm = ClientSession(read, write)
    session = await session_cm.__aenter__()
    await session.initialize()
    return cm, session_cm, session


async def discover_tools(config: MCPServerConfig) -> list[dict[str, Any]]:
    """Connect to an MCP server, list its tools, then close.

    Returns OpenAI-shaped schemas (so the existing registry/dispatcher just
    work). Errors are logged and yield an empty list.
    """
    try:
        cm, session_cm, session = await _open_session(config)
    except Exception as exc:
        logger.warning("MCP discover failed for %s: %s", config.name, exc)
        return []
    try:
        tools_resp = await session.list_tools()
        out: list[dict[str, Any]] = []
        for t in tools_resp.tools:
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": f"mcp-{config.name}-{t.name}",
                        "description": t.description or f"{config.name}.{t.name}",
                        "parameters": t.inputSchema
                        or {"type": "object", "properties": {}},
                    },
                }
            )
        return out
    except Exception as exc:
        logger.warning("MCP list_tools failed for %s: %s", config.name, exc)
        return []
    finally:
        try:
            await session_cm.__aexit__(None, None, None)
        except Exception:
            pass
        try:
            await cm.__aexit__(None, None, None)
        except Exception:
            pass


def _make_handler(config: MCPServerConfig, remote_name: str):
    """Build an async handler that opens a fresh MCP session per call."""

    async def _handler(args: dict[str, Any], context: DispatchContext) -> str:
        try:
            cm, session_cm, session = await _open_session(config)
        except Exception as exc:
            return f"mcp[{config.name}.{remote_name}]: connection failed: {exc}"
        try:
            result = await session.call_tool(remote_name, arguments=args)
        except Exception as exc:
            await session_cm.__aexit__(None, None, None)
            await cm.__aexit__(None, None, None)
            return f"mcp[{config.name}.{remote_name}]: call failed: {exc}"
        finally:
            try:
                await session_cm.__aexit__(None, None, None)
            except Exception:
                pass
            try:
                await cm.__aexit__(None, None, None)
            except Exception:
                pass
        # Result content is a list of {type, text|...} blocks per MCP spec.
        parts: list[str] = []
        for block in getattr(result, "content", []) or []:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
            else:
                parts.append(str(block))
        return "\n".join(parts) or "(no content)"

    return _handler


async def register_mcp_servers(
    configs: dict[str, MCPServerConfig],
    registry: ToolRegistry | None = None,
) -> dict[str, int]:
    """Discover + register all configured servers' tools.

    Returns a per-server count of tools registered. Failures are logged and
    yield ``0`` for that server.
    """
    reg = registry or default_registry()
    out: dict[str, int] = {}
    for name, cfg in configs.items():
        schemas = await discover_tools(cfg)
        for schema in schemas:
            local_name = schema["function"]["name"]
            remote_name = local_name[len(f"mcp-{cfg.name}-") :]
            reg.register(
                name=local_name,
                toolset=f"mcp-{cfg.name}",
                schema=schema,
                handler=_make_handler(cfg, remote_name),
                description=schema["function"].get("description", ""),
                override=True,
            )
        out[name] = len(schemas)
        logger.info("MCP %s: registered %d tool(s)", name, len(schemas))
    return out


async def register_mcp_servers_from_env(
    registry: ToolRegistry | None = None,
) -> dict[str, int]:
    return await register_mcp_servers(
        parse_mcp_config(os.environ.get("CHIMERA_MCP_SERVERS")),
        registry,
    )
