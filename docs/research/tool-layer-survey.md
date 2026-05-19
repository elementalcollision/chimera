# Tool-Layer Survey

Multi-LLM agent reference architecture comparison across Hermes (NousResearch) and OpenClaw (legacy); clawdbot absent from `.clawdbot/`. Two-column comparison provided.

## TL;DR

- **Dispatcher:** Hermes uses async-bridged registry lookup with TTL-cached availability checks; OpenClaw applies multi-layer policy pipeline (global/agent/group/scope) at resolution time before dispatch.
- **Schema:** Both use OpenAI-compatible JSON; Hermes declares via `registry.register()` at module-import time; OpenClaw computes from tool factory objects at boot.
- **Sandbox/Trust:** Hermes gates via in-process `check_fn()` probes + subprocess safety for execution tools. OpenClaw enforces policy-pipeline filtering across scopes + default gateway HTTP deny-list before handler invocation.

## Comparison Table

| Aspect | hermes-agent | openclaw |
|--------|---|---|
| **Tool schema format** | OpenAI JSON (`{"type": "function", "function": {...}}`) declared via Python dict | OpenAI JSON (identical) computed from tool object properties |
| **Schema declaration** | Module-level `registry.register(name, toolset, schema, handler, ...)` at import time; auto-discovered by AST scan | Declarative tool factory (`createOpenClawTools()`) returns tool objects with `.name`, `.description`, `.input_schema`; frozen at boot |
| **Tool module layout** | `tools/*.py` each calls `registry.register()` once at module top; auto-discovered via AST parse of `registry.register()` calls | `src/agents/openclaw-tools.js` factory + `src/channels/*/tools/*.ts` per-channel implementations |
| **Dispatch entry point** | `handle_function_call(tool_name, args, task_id)` → registry lookup → sync/async bridge → handler | HTTP POST `/tools/invoke` → `resolveGatewayScopedTools()` → policy-scoped tool list → `invokeGatewayTool()` or WebSocket `tools/call` frame → handler |
| **Async/sync handling** | Persistent event loop per thread (`_get_tool_loop()`, `_get_worker_loop()`); async handlers unified via `_run_async()` with 300s timeout; swappable via `asyncio.get_running_loop()` detection | Native async/await; all handlers Promise-based; timeouts via AbortController + request.once("close") signals |
| **Streaming** | Tools return full result string; streaming handled by agent loop, not tool-level | Tools return full result; MCP protocol (`tools/call`) returns result in response frame; loopback server batches JSON-RPC responses |
| **Parallel execution** | `delegate_task` tool spawns ThreadPoolExecutor workers; each worker gets per-thread persistent loop to avoid "Event loop is closed" errors on cached clients | No built-in parallel; policy-filtered tools returned to model; model picks next tool (serial); kanban workflow for true multi-agent coordination |
| **Permission/trust model** | `check_fn()` per toolset (probes Docker/Modal SDK/playwright binary availability); TTL-cached 30s to amortize external probes; `requires_env` list; gating on env vars/config flags | Multi-layer policy pipeline: global + provider + agent + group + subagent + inherited rules; toolset profile allowlist/denylist; platform-scoped `DEFAULT_GATEWAY_HTTP_TOOL_DENY` (8 tools) |
| **Permission enforcement** | At schema-build time in `get_definitions()`; unavailable tools silently excluded via `_check_fn_cached()` TTL cache | At resolution time (pre-dispatch) via `applyToolPolicyPipeline()` + `excludeToolNames` filtering; policy can block after tool init passes |
| **Toolset/skill system** | Composable toolsets via nested `includes` dict; `resolve_toolset(name)` recursion with cycle detection; platform-specific aliases (`hermes-cli`, `hermes-telegram`, `hermes-slack`, etc.); MCP toolsets injected with `mcp-<server>` prefix | Profile-based tool policy (allow/deny lists); provider policy overlay; subagent capability store inheritance; no runtime composition; frozen at boot after config load |
| **Tool availability checks** | `check_fn()` per toolset; e.g., `check_terminal_requirements()` probes Docker socket, Modal SDK, playwright binary; cached and re-evaluated at `hermes tools enable` commands | No global check_fn; policy filtering is the availability gate; plugin capability checks embedded in tool init; no external probes |
| **Sandbox boundary** | In-process Python; terminal/process tools spawn subprocess with safety rules; vision calls external API; browser manages Playwright subprocess; MCP runs as stdio/SSE client to external servers | In-process Node.js; HTTP tools call external services; plugin tools (Telegram, Discord, etc.) own sandbox policy; MCP protocol delegates to external servers via HTTP loopback |
| **Tool result size limits** | `max_result_size_chars` per tool; enforced during schema build and result truncation | No per-tool limit; compression/truncation delegated to model context window management |
| **Dynamic schema updates** | MCP tools auto-refresh on `notifications/tools/list_changed`; old tools deregistered via `deregister(name)`, new tools registered; registry generation counter bumps on mutation | No dynamic schema refresh; tools frozen at boot after config load; config changes require restart or explicit reload |
| **MCP integration** | Full MCP SDK client in Python; `mcp_serve.py` exposes Hermes conversations as MCP server (stdio + SSE); registers MCP server tools via `discover_mcp_tools()` side effect; auto-refresh on server signals; tools registered with `toolset="mcp-<server>"` | MCP HTTP loopback server (`mcp-http.ts`); auth via bearer token (owner/non-owner); caches scoped tool schema per request; native JSON-RPC 2.0 protocol handler; MCP as external transport, not tight coupling |
| **Plugin system** | Plugin discovery via `hermes_cli/plugins.py`; plugins register tools via registry at import time; bundled plugins own providers (web via Firecrawl/Exa/Tavily, Discord, Spotify, etc.); plugin tool override with `override=True` opt-in | MCP servers as plugins; plugin SDK via `openclaw/plugin-sdk/*` barrels; channels as internal implementation (not plugins); tool policy inherited from owner plugin config; no registration collision |
| **Default toolset** | `_HERMES_CORE_TOOLS` (40+ tools: web_search, terminal, vision, browser, skills, todo, memory, delegate_task, kanban, etc.); platform-specific variants (`hermes-cli`, `hermes-telegram`, `hermes-slack`, `hermes-discord`, etc.) | None global; resolved per-session via policy + scope; `DEFAULT_GATEWAY_HTTP_TOOL_DENY` (8 tools: pin_message, create_thread, set_topic, etc.) filtered from HTTP surface; gateway config allow/deny overrides |
| **Configuration source** | `config.yaml` per platform; `hermes tools` CLI for enable/disable; toolset aliases in registry; profile-based tool gating via env vars / credential files | YAML config in `src/config/types.openclaw.ts`; policy per global/agent/provider/group; session-scoped inheritance via `resolveEffectiveToolPolicy()`; subagent capability store |

## Recommended Chimera Approach

**Synthesized design, taking best from both systems:**

1. **Schema Layer (unified):**
   - OpenAI-compatible JSON format (universal model acceptance, no vendor lock-in)
   - Declare via `registry.register(name, toolset, schema, handler, check_fn, ...)` at boot (Hermes model: declarative, auditable, auto-discoverable)
   - Auto-discover from plugin sources: AST scan for Python, dynamic factory for Node.js/TypeScript
   - Support `dynamic_schema_overrides()` for config-aware descriptions (delegation limits, API quotas, etc.)

2. **Dispatch (Hermes registry + OpenClaw policy):**
   - Single `dispatch(tool_name, args, context)` entry point with no branching
   - Registry-backed lookup (Hermes model: O(1) access, composable toolsets)
   - Multi-layer permission checks before handler invocation (OpenClaw model: global allow/deny → agent → group → provider → session scope)
   - Policy filtering happens pre-dispatch (never invoke a denied tool)
   - TTL-cached availability checks (`check_fn` pattern) to avoid repeated external probes (Docker socket, playwright binary, API connectivity)
   - Native async/await for all handlers; unified event-loop lifecycle (Python 3.10+, Node.js native)

3. **Sandbox & Execution (split ownership):**
   - In-process for read-only tools (web search, vision, file read, memory)
   - Subprocess/container for execution tools (terminal, code, process execution)
   - MCP as optional external transport layer (not mandatory; enables wrapping third-party agents, LLMs, or specialized services)
   - Policy enforcement at dispatch boundary (deny-list gates; allow-list in schema description)
   - Result size limits per tool; enforce via truncation before returning to model

4. **Skill/Toolset Composition (from Hermes, refined):**
   - Nested toolset resolution with cycle detection (diamond dependencies safe)
   - Platform-specific toolset aliases (`chimera-cli`, `chimera-slack`, etc.)
   - Dynamic resolution at request time, not boot (enables inheritance across scopes)
   - Runtime plugins can register new toolsets on-the-fly
   - Toolset composition graph visible in `hermes tools list` / admin UI

5. **MCP Integration (both patterns supported):**
   - Hermes pattern: Python MCP SDK client for external servers; native tool refresh on `notifications/tools/list_changed`
   - OpenClaw pattern: MCP HTTP loopback with JSON-RPC 2.0; bearer-token auth; batch request support
   - **Chimera:** Accept both patterns. External MCP servers register tools via protocol (loopback or stdio); internal plugin tools register via registry. Single dispatcher routes to both.

## Rejected Approaches

- **Per-worker persistent thread loops (Hermes detail):** Needed in Python to avoid "Event loop is closed" errors on cached httpx/AsyncOpenAI clients. Node.js has native async; Chimera on Node.js does not need this; Python agents should delegate to async pool with fresh loops per task.
- **Silent tool exclusion on unavailability:** Hermes excludes unavailable tools from schema without logging. Chimera will emit `WARN` at boot: "Tool X gated by check_fn; requires Docker socket" so operators see what's hidden.
- **Prompting toolsets as text:** OpenClaw encodes policy as structured rules; do not render toolset descriptions into system prompt. Reduces flexibility, increases token cost. Keep toolset definitions in config, schema in OpenAI format only.
- **Dynamic schema override at dispatch time (Hermes pattern):** Hermes supports `dynamic_schema_overrides()` for runtime config-aware descriptions. Clean but adds dispatch-time overhead. Chimera will use static schema + inline help text in description field.
- **Tool-level streaming (future extension):** Neither system supports it; defer to model. If tool needs streaming (e.g., tail -f logs), return full result; model can request pagination via new tool call or accept truncation.

## Open Questions

1. **MCP versioning & breaking changes:** How does Chimera handle breaking MCP protocol versions? Proposed: version negotiation in loopback handshake (HTTP header `MCP-Version: 1.0`), or separate port per MCP version; fallback to stdio for legacy servers.
2. **Result streaming (future):** Should Chimera support tool-level streaming for long-running operations? Defer to Phase 1; if needed, add `result_streaming: true` schema flag + SSE/WebSocket frame type.
3. **Multi-model tool visibility:** If Chimera routes the same session across Claude, GPT, etc., do all models see the same toolset? Proposed: yes, for consistency. Add per-model rate-limiting or tool pruning at dispatch if needed.
4. **Tool versioning & deprecation:** `tool@v2` alongside `tool@v1`? Proposed: no. Single tool per name; deprecated tools removed from schema. Version handler internally, surface as single tool name.
5. **Subagent capability inheritance:** Subagent inherits parent toolset filtered via `subagent_policy`; additional tools gated via explicit config in subagent spawn RPC.

## References

### hermes-agent (NousResearch)

- **Toolsets & Composition:**
  - `research/_clones/hermes-agent/toolsets.py:76–534` — TOOLSETS dict (40+ core tools, platform-specific aliases, composite toolsets with `includes`)
  - `research/_clones/hermes-agent/toolsets.py:590–661` — `resolve_toolset(name)` recursion with cycle detection
  - `research/_clones/hermes-agent/toolsets.py:31–73` — `_HERMES_CORE_TOOLS` definition
- **Registry & Schema:**
  - `research/_clones/hermes-agent/tools/registry.py:77–107` — ToolEntry dataclass (name, toolset, schema, handler, check_fn, requires_env, is_async, emoji, max_result_size_chars, dynamic_schema_overrides)
  - `research/_clones/hermes-agent/tools/registry.py:151–331` — ToolRegistry class (register, deregister, get_definitions with check_fn caching)
  - `research/_clones/hermes-agent/tools/registry.py:121–149` — `_check_fn_cached()` TTL cache (30s)
  - `research/_clones/hermes-agent/tools/registry.py:57–74` — `discover_builtin_tools()` AST scan for `registry.register()` calls
- **Dispatch & Async Bridging:**
  - `research/_clones/hermes-agent/model_tools.py:36–172` — `_run_async()`, `_get_tool_loop()`, `_get_worker_loop()` async bridging with timeout enforcement (300s)
  - `research/_clones/hermes-agent/model_tools.py:1–34` — Public API (get_tool_definitions, handle_function_call, TOOL_TO_TOOLSET_MAP)
- **MCP Integration:**
  - `research/_clones/hermes-agent/mcp_serve.py:1–78` — MCP server exposure of Hermes conversations as tools (stdio + SSE); 9-tool channel bridge + extra channels_list tool

### OpenClaw

- **Tool Resolution & Policy:**
  - `research/_clones/openclaw/src/gateway/tool-resolution.ts:35–210` — `resolveGatewayScopedTools(params)` — multi-layer policy pipeline (global + provider + agent + group + subagent + inherited); policy filtering via `applyToolPolicyPipeline()`
  - `research/_clones/openclaw/src/gateway/tool-resolution.ts:78–138` — Policy scope composition
- **MCP Loopback Server:**
  - `research/_clones/openclaw/src/gateway/mcp-http.ts:87–234` — `startMcpLoopbackServer()`, `ensureMcpLoopbackServer()` — HTTP loopback with JSON-RPC 2.0, bearer-token auth, batch request support
  - `research/_clones/openclaw/src/gateway/mcp-http.ts:95–100` — Request validation via `validateMcpLoopbackRequest()`
- **Tool Invocation & Handlers:**
  - `research/_clones/openclaw/src/gateway/tools-invoke-http.ts` — HTTP POST `/tools/invoke` dispatch
  - `research/_clones/openclaw/src/gateway/tools-invoke-shared.ts:1–9` — `invokeGatewayTool()`, `ToolsInvokeInput` type

### External Specs

- **OpenAI Function Calling:** https://platform.openai.com/docs/guides/function-calling
- **MCP (Model Context Protocol) Specification:** https://modelcontextprotocol.io/
- **agentskills.io Standard:** Referenced in Hermes toolsets.py; likely internal Nous registry (not accessible publicly)

### Note: clawdbot

Directory `/Users/dave/uberagent/.clawdbot/` does not exist or is empty. No local clawd implementation found to survey.
