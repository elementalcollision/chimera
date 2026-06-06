# ADR 0165 — Semantic tool pre-filter, lexical v0 (v4.119)

**Status:** Proposed (2026-06-06)

## Context

The ACT executor hands the model **every available tool schema on every
round** — `core/act.py` called `self._dispatcher.registry.schemas()`
unconditionally before each provider turn. With the built-in `core`
toolset that is ~7 tools, but the registry also carries the
operator-approved `dynamic` skills (`chimera/tools/dynamic/`) and the
trust-gated `mcp-<peer>` peer toolsets — both **unbounded** sets that
grow as the agent federates and assembles skills.

The evaluation in
[semantic-routing-evaluation-2026-06-06.md](../research/semantic-routing-evaluation-2026-06-06.md)
compared Chimera against
[vllm-project/semantic-router](https://github.com/vllm-project/semantic-router)
and identified this as the highest value-for-effort intersection. The
vLLM Semantic Router blog (2025-09-11) states the problem directly:
*"Adding more tools … can drastically reduce accuracy. The router must
pre-filter tools and keep catalogs tight."* A fat catalog is both an
accuracy tax (the model fixates on irrelevant tools, a known
degenerate-loop trigger) and a token tax paid on every round of every
tool chain.

The evaluation's recommended **first slice** is a zero-dependency
lexical pre-filter: it captures most of the tool-chain win, ships under
the thin-core constraint (no embeddings, no torch), and lays the exact
seam an embedding-backed classifier slots into once ADR 0134 §"#6.b"
picks the embedding model. This ADR is that slice.

## Decision

A new module scopes the per-task tool catalog by lexical relevance,
behind a default-OFF flag so behaviour is byte-identical until opted in.

### Code

- `chimera/tools/tool_selection.py` — new module:
  - `tool_prefilter_enabled()` — honours `CHIMERA_TOOL_PREFILTER`
    (default off; same parsing shape as `hybrid_search_enabled`).
  - `select_tool_schemas(registry, task_text, *, always_on_toolsets)` —
    the ACT call-site replacement. Flag **off** ⇒ returns
    `registry.schemas()` unchanged. Flag **on** ⇒ returns the available
    catalog pruned to `always_on_toolsets` (default `{"core"}`) plus any
    tool whose **signal tokens** (name + toolset + description + schema
    function-description + parameter names, ≥4 chars, minus a small
    stop-word set) overlap the task's tokens.
  - Safety rails: the `core` floor is never pruned (the agent can't be
    stranded without shell/code_exec/web/mind_search); an empty or
    token-less task returns the full catalog; availability is honoured
    exactly as `registry.schemas()` does.
- `chimera/tools/__init__.py` — export `select_tool_schemas` +
  `tool_prefilter_enabled`.
- `chimera/core/act.py` — the single tool-exposure site now calls
  `select_tool_schemas(self._dispatcher.registry, task_text)`.

### CLI / dashboard

None. Operator surface is the `CHIMERA_TOOL_PREFILTER` env flag.

## Tests

`tests/test_tool_selection.py` — 9 cases:
- flag off returns the full catalog byte-identical to `registry.schemas()`;
- flag on always keeps the `core` floor even on an unrelated task;
- flag on includes a `dynamic` skill / an `mcp-*` peer tool when the task
  carries its tokens, and prunes it when it does not;
- flag on with an empty / stop-word-only task returns the full catalog;
- flag on still excludes an unavailable (failed `check_fn`) tool;
- flag parsing across the truthy/falsy spellings.

Full suite: pre-existing `test_tools.py::test_shell_search_tool_hints_posix_equivalent`
fails **only** in containers that ship `/usr/bin/rg` (environmental — the
test asserts `rg` is refused; unrelated to this change, which touches
neither `shell.py` nor `SAFE_COMMANDS`). The tool-selection + ACT +
escalation + tier suites are green (84 passing, 1 skipped on that slice).

## Non-goals

- **Embedding-backed routing.** Deferred to the ADR 0134 §"#6.b"
  embedding-model decision; this seam is designed so that upgrade is a
  drop-in replacement of `_is_relevant`, no call-site change.
- **Semantic tier / model selection.** The evaluation's §3.2 (augmenting
  `recommended_tier`) is a separate, embedding-gated follow-up.
- **Pruning the `core` toolset.** Considered and rejected: `core` is the
  agent's foundational ability to act and is small + stable; the bloat is
  the `dynamic` + `mcp-*` sets, so only those are filtered.
- **PII / jailbreak / semantic-cache** features of semantic-router — out
  of scope per the evaluation (deployment + scope mismatch for a thin
  Python agent).

## Why this shape

A lexical token-overlap rule that biases toward **inclusion** (matching
on name *and* description *and* params) keeps the failure mode safe:
over-inclusion merely forgoes some benefit, while under-inclusion (the
real risk) can only ever drop a `dynamic`/`mcp` tool the task did not
lexically reference — and even then the `core` floor (including
`sub_agent`) guarantees a path to act, with `task_escalations` memory as
the cross-cycle net. The 4-char token floor reuses the convention
already established by `core.escalation._signature`, so the two routing
heuristics stay consistent.
