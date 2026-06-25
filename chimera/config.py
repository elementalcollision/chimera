"""Central registry of CHIMERA_* environment flags (ADR 0176).

Chimera grew ~90 feature flags read ad-hoc via ``os.environ`` across ~60
modules. That sprawl has no single source of truth and no validation of
flag *interactions* — which is exactly how the CHIMERA_FANOUT_BUDGET
zero-API-calls interaction bug escaped to live runs (found by a 12-cell
characterization campaign, not by tests).

This module is **declarative**: call sites keep reading ``os.environ``
directly (migrating 150+ reads in one sweep would be high-risk churn for
no behavioural gain). What the registry provides:

- one authoritative table of every flag: kind, default, description;
- ``validate_env()`` — startup-callable validation of flag values and the
  documented cross-flag interactions, returning human-readable warnings;
- the data that drives the flag-combination test matrix
  (``tests/test_flag_matrix.py``) and the registry-completeness test
  (``tests/test_flag_registry.py``), which fails CI when a new
  ``CHIMERA_*`` read appears in the package without a declaration here.

Adding a flag? Declare it in :data:`REGISTRY` (the completeness test will
remind you), and if it interacts with existing flags, encode the rule in
:func:`validate_env` and add the pair to ``HIGH_IMPACT_FLAGS`` /
``KNOWN_INTERACTIONS`` so the matrix exercises it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

FlagKind = Literal["bool", "int", "float", "str", "path", "csv", "json"]

#: Truthy spellings accepted by the bool-ish flags (the dominant call-site
#: idiom, shared by the whole ADR 0165–0174 flag family). A few legacy
#: sites vary (some test ``== "1"``, one tests ``== "0"`` to *disable*);
#: those keep their own parsers until individually migrated.
TRUTHY = ("1", "true", "yes", "on")


@dataclass(frozen=True)
class FlagSpec:
    name: str
    kind: FlagKind
    default: str | None  # None = unset (feature off / built-in fallback)
    description: str
    # Flags whose behaviour this one modifies or is modified by.
    interacts_with: tuple[str, ...] = field(default=())


def _f(
    name: str,
    kind: FlagKind,
    default: str | None,
    description: str,
    interacts_with: tuple[str, ...] = (),
) -> tuple[str, FlagSpec]:
    return name, FlagSpec(name, kind, default, description, interacts_with)


#: Dynamic flag-name prefixes — names are completed at runtime
#: (per-proposer thresholds, per-tier token caps). The completeness test
#: treats any name starting with one of these as declared.
DYNAMIC_FLAG_PREFIXES: tuple[str, ...] = (
    "CHIMERA_PROPOSER_",        # CHIMERA_PROPOSER_<NAME>_THRESHOLD
    "CHIMERA_ACT_MAX_TOKENS_",  # CHIMERA_ACT_MAX_TOKENS_<TIER>
)


REGISTRY: dict[str, FlagSpec] = dict(
    (
        # ── core layout / identity ────────────────────────────
        _f("CHIMERA_MIND_DIR", "path", None, "Mind (knowledge) directory; default ./mind."),
        _f("CHIMERA_STATE_DIR", "path", None, "State (db/journal) directory; default ./state."),
        _f("CHIMERA_FOREIGN_REPO", "str", None,
           "Foreign target repo 'owner/name' for a multi-repo soak (ADR 0186 B.3); "
           "set by real_task_soak.sh's foreign block. When set, the agent's system "
           "prompt uses a neutral repo-framed voice instead of Chimera's self-identity."),
        _f("CHIMERA_GATE_SANDBOX", "bool", "1",
           "Gate sandbox (ADR 0186 B.4 M1): strip provider secrets from the "
           "ruff/pytest gate subprocess (self + foreign). Default-on; set 0 to "
           "disable (escape hatch). The agent keeps its keys — only the gate is stripped."),
        _f("CHIMERA_AGENT_ID", "str", None, "Stable agent identity override."),
        _f("CHIMERA_VOICE", "str", None, "Persona/voice selector for prompts."),
        _f("CHIMERA_LOG_LEVEL", "str", None, "Python logging level."),
        _f("CHIMERA_LOG_JSON", "bool", None, "Emit structured JSON logs."),
        # ── loop / cycle ──────────────────────────────────────
        _f("CHIMERA_CYCLE_SECONDS", "int", None, "Cycle cadence for daemon mode."),
        _f("CHIMERA_SESSION_MAX_HOURS", "float", None, "Hard session wall-clock cap."),
        _f("CHIMERA_PLAN_MAX_OPEN_TASKS", "int", None, "PLAN queue-depth gate."),
        _f("CHIMERA_SUPPRESS_PROPOSALS", "bool", None,
           "Suppress engine proposals only (ADR 0151).",
           ("CHIMERA_ENGINES_ENABLED",)),
        _f("CHIMERA_ACT_BUDGET_SECONDS", "int", None, "Soft ACT-phase time budget."),
        _f("CHIMERA_ACT_MAX_TOKENS", "int", None,
           "Global ACT max-tokens; per-tier CHIMERA_ACT_MAX_TOKENS_<TIER> wins."),
        _f("CHIMERA_ACT_FORCE_MODEL", "str", None, "Pin ACT to one model id."),
        _f("CHIMERA_ACT_TIER", "str", None,
           "Base ACT tier when the loop doesn't pass one (default haiku; CRAWL sets 'code')."),
        _f("CHIMERA_OPUS_PLAN_EVERY_N", "int", None, "Escalate PLAN to opus tier every N cycles."),
        _f("CHIMERA_ANSWER_TIMEOUT_S", "float", None, "Peer answer timeout."),
        _f("CHIMERA_TASK_GOAL", "str", None, "Current task goal (set by runner; read by gates)."),
        # ── engines ───────────────────────────────────────────
        _f("CHIMERA_ENGINES_ENABLED", "bool", "1",
           "Master engine kill-switch; '0' disables engines AND blocks git commit/push "
           "in the shell tool (investigation-only phase).",
           ("CHIMERA_SUPPRESS_PROPOSALS",)),
        _f("CHIMERA_ENGINE_GATES_ENABLED", "bool", None, "Engine guard-gates toggle."),
        _f("CHIMERA_ENGINE_SESSION_MODE", "str", None, "Engine rotation session mode."),
        _f("CHIMERA_DISCOVERY_ENABLED", "bool", None, "Discovery engine toggle."),
        _f("CHIMERA_DISCOVERY_HOUR", "int", None, "Discovery engine rotation hour."),
        _f("CHIMERA_DISCOVERY_MIN_API_CALLS", "int", None, "Discovery minimum API-call gate."),
        _f("CHIMERA_CURIOSITY_HOUR", "int", None, "Curiosity engine rotation hour."),
        _f("CHIMERA_CURIOSITY_REQUIRE_DISCOVERY", "bool", None,
           "Curiosity requires a prior discovery."),
        _f("CHIMERA_REFLECTION_HOUR", "int", None, "Reflection engine rotation hour."),
        _f("CHIMERA_REFLECTION_MIN_CYCLES", "int", None, "Reflection minimum-cycle gate."),
        _f("CHIMERA_REFLECTION_DERIVER", "bool", None, "Reflection deriver opt-in (ADR 0125)."),
        _f("CHIMERA_REFLECTION_REASONING_TIER", "str", None,
           "ReasoningTier for reflection (ADR 0127)."),
        _f("CHIMERA_EMERGENCE_AUTORECORD", "bool", None, "Auto-record emergence observations."),
        # ── memory / graph / search ───────────────────────────
        _f("CHIMERA_GRAPH_ENABLED", "bool", None,
           "Kuzu graph projection opt-in (ADR 0081).",
           ("CHIMERA_AUTO_GRAPH_UPDATE_DISABLED",)),
        _f("CHIMERA_AUTO_GRAPH_UPDATE_DISABLED", "bool", None,
           "LEGACY: forces graph auto-refresh off even when CHIMERA_GRAPH_ENABLED is set.",
           ("CHIMERA_GRAPH_ENABLED",)),
        _f("CHIMERA_AUTO_WIKI_INDEX_DISABLED", "bool", None, "Disable FTS5 wiki auto-index."),
        _f("CHIMERA_AUTO_ARCHIVE_DISABLED", "bool", None,
           "Disable DEPRECATED-entity auto-archive.",
           ("CHIMERA_AUTO_ARCHIVE_AFTER_CYCLES",)),
        _f("CHIMERA_AUTO_ARCHIVE_AFTER_CYCLES", "int", None,
           "Cycles before a DEPRECATED entity is auto-archived; ignored when "
           "CHIMERA_AUTO_ARCHIVE_DISABLED is set.",
           ("CHIMERA_AUTO_ARCHIVE_DISABLED",)),
        _f("CHIMERA_HYBRID_SEARCH", "bool", None, "BM25+dense hybrid wiki retrieval."),
        _f("CHIMERA_ADAPTIVE_TOPK_TEMPORAL", "bool", None,
           "Adaptive top-k + temporal weighting in retrieval."),
        _f("CHIMERA_EMBED_MODEL", "str", None, "Embedding model for dense retrieval."),
        _f("CHIMERA_EMBED_TIMEOUT_S", "float", None, "Embedding call timeout."),
        _f("CHIMERA_OLLAMA_URL", "str", None, "Ollama endpoint for local embeddings."),
        _f("CHIMERA_LOCOMO_TRACE", "bool", None, "LoCoMo eval trace output."),
        # ── cost discipline ───────────────────────────────────
        _f("CHIMERA_CYCLE_COST_CAP_USD", "float", None, "Per-cycle hard cost cap (ADR 0072)."),
        _f("CHIMERA_ROLLING_HOUR_CAP_USD", "float", None, "Rolling-60m cost cap (ADR 0076)."),
        _f("CHIMERA_TASK_BUDGET_USD", "float", None, "Per-task cost cap (ADR 0079)."),
        # ── ACT routing / sub-tasking (the entropy family) ────
        _f("CHIMERA_TOOL_PREFILTER", "bool", "1", "Semantic tool pre-filter (ADR 0165; default-ON via ADR 0184)."),
        _f("CHIMERA_COMPLEXITY_ROUTING", "bool", "1",
           "Lexical task-complexity model selection (ADR 0166; default-ON via ADR 0185)."),
        _f("CHIMERA_PEER_SELECTION", "bool", None,
           "Power-of-two-choices peer selection (ADR 0167).",
           ("CHIMERA_MODEL_PEERS",)),
        _f("CHIMERA_FANOUT_BUDGET", "bool", None,
           "Subcriticality fan-out budget (ADR 0171).",
           ("CHIMERA_FANOUT_MAX_WIDTH",)),
        _f("CHIMERA_FANOUT_MAX_WIDTH", "int", None,
           "Max parallel tool fan-out width when CHIMERA_FANOUT_BUDGET is on.",
           ("CHIMERA_FANOUT_BUDGET",)),
        _f("CHIMERA_ENTROPY_SIGNALS", "bool", "1",
           "Tool-use entropy observability signals (ADR 0170). Default-ON "
           "since ADR 0180 (second graduation): pure observability — one "
           "entropy computation + one phase-log line per cycle, no dispatch/"
           "provider/cost effect. Set 0 to disable."),
        _f("CHIMERA_ANNEAL_REHEAT", "bool", None,
           "Decorrelated reheat-on-stuck (ADR 0169)."),
        _f("CHIMERA_BOLTZMANN_ALLOC", "bool", None,
           "Boltzmann max-entropy proposal/split allocation (ADR 0172).",
           ("CHIMERA_BOLTZMANN_TEMP",)),
        _f("CHIMERA_BOLTZMANN_TEMP", "float", None,
           "Temperature for Boltzmann allocation.",
           ("CHIMERA_BOLTZMANN_ALLOC",)),
        _f("CHIMERA_TASK_SPLITTER_ENABLED", "bool", None, "Heuristic multi-section task splitter."),
        # ── witness / critic ──────────────────────────────────
        _f("CHIMERA_WITNESS_ENABLED", "bool", None, "Witness review of ACT results."),
        _f("CHIMERA_WITNESS_TIER", "str", None, "Witness model tier."),
        _f("CHIMERA_WITNESS_PANEL_SIZE", "int", None, "Witness panel size."),
        _f("CHIMERA_WITNESS_VOTING", "bool", None, "Witness panel voting mode."),
        _f("CHIMERA_WITNESS_REQUIRE_CROSS_PROVIDER", "bool", None,
           "Witness must come from a different provider than the actor."),
        _f("CHIMERA_SHADOW_ARBITER", "bool", None,
           "Log-only arbiter on a CONTESTED witness panel (ADR 0187 #5); records "
           "into the B.4l ledger, never changes the gate. Inert unless set."),
        _f("CHIMERA_SHADOW_ARBITER_PROVIDER", "str", None,
           "Provider for the shadow arbiter (default sakana).",
           ("CHIMERA_SHADOW_ARBITER",)),
        _f("CHIMERA_SHADOW_ARBITER_MODEL", "str", None,
           "Model id for the shadow arbiter (default fugu-ultra).",
           ("CHIMERA_SHADOW_ARBITER",)),
        _f("CHIMERA_CRITIC_ENFORCE", "bool", None,
           "In-loop critic commit gate (ADR 0162); inert by default.",
           ("CHIMERA_ALLOW_CRITIC_REJECT",)),
        _f("CHIMERA_ALLOW_CRITIC_REJECT", "bool", None,
           "Permit the critic to hard-reject (test/ops knob).",
           ("CHIMERA_CRITIC_ENFORCE",)),
        _f("CHIMERA_CRITIC_ESCALATOR_MODEL", "str", None, "Critic escalation model id."),
        # ── scope / commit gates ──────────────────────────────
        _f("CHIMERA_ALLOW_OFF_CHARTER_COMMIT", "bool", None,
           "Operator override for the pre-commit scope check (ADR 0146); single-use intent."),
        _f("CHIMERA_ALLOW_UNSCOPED_RUFF", "bool", None,
           "Operator override for the ruff charter-scope guard (ADR 0186 B.4h); single-use intent."),
        _f("CHIMERA_ALLOW_MAIN_BRANCH_DRIFT", "bool", None,
           "Permit main-branch drift in repo verification."),
        _f("CHIMERA_SOURCE_PATH_PATTERN", "str", None, "Charter source-path allowlist pattern."),
        _f("CHIMERA_ARXIV_FEED", "path", None,
           "Path to the arXiv chimera feed JSON for `chimera arxiv-digest` ingestion "
           "(ADR 0186); unset disables the daily-driver digest step."),
        _f("CHIMERA_SELF_PR", "bool", None, "Trust-gated self-PR (ADR 0163)."),
        _f("CHIMERA_REPO_ALLOWLIST", "str", None,
           "Allowlist of foreign repo owners or 'owner/name' for multi-repo soaks "
           "(ADR 0186); space/comma-separated; operational default 'elementalcollision'. "
           "Fail-closed: a non-allowlisted target is refused (shell pre-clone AND the "
           "foreign-PR gate)."),
        _f("CHIMERA_FOREIGN_PR", "bool", None,
           "Trust-gated DRAFT PR against a FOREIGN repo (ADR 0186 B.4b). Separate "
           "opt-in from CHIMERA_SELF_PR (never implied). Off by default."),
        _f("CHIMERA_FOREIGN_PR_REQUIRE_APPROVAL", "bool", "1",
           "Require explicit per-PR operator approval for the first 5 foreign PRs "
           "even at T4 (ADR 0186 B.4c / M4); graduates after. Default-on."),
        _f("CHIMERA_FOREIGN_PR_APPROVED", "bool", None,
           "Per-run operator approval grant for THIS foreign PR (ADR 0186 B.4c). "
           "Set =1 to approve one PR while the first-5 approval gate is active."),
        _f("CHIMERA_FOREIGN_REGRESSION_CMD", "str", None,
           "Optional BROADER test suite for the foreign-PR no-pass-to-pass-regression "
           "gate (ADR 0186 B.4i, from Phoenix): if GREEN on base it must stay GREEN at "
           "HEAD. Unset → gate skipped (additive-test tasks can't regress)."),
        _f("CHIMERA_FOREIGN_BEHAVIOR_CMD", "str", None,
           "Optional DETERMINISTIC characterization driver for the foreign-PR "
           "behaviour-preservation gate (ADR 0186 B.4k): its stdout must be "
           "byte-identical on base vs HEAD. Set only for behaviour-PRESERVING tasks "
           "(refactor/optimize); unset → gate skipped (a feature/bugfix changes "
           "behaviour legitimately)."),
        _f("CHIMERA_FOREIGN_PROPERTY_CMD", "str", None,
           "Optional operator-trusted PROPERTY/fuzz test for the foreign-PR property "
           "gate (ADR 0186 B.4k stage 2b): must PASS at HEAD (exits nonzero on a "
           "counterexample), catching code that satisfies the fixed-input verify_cmd "
           "but is wrong on un-tested inputs. Unset → gate skipped."),
        # ── A2A / federation ──────────────────────────────────
        _f("CHIMERA_PEER_TOKEN", "str", None, "Shared bearer token for the HTTP MCP server."),
        _f("CHIMERA_PEER_TOKENS", "json", None, "Per-peer token map {token: peer-name}."),
        _f("CHIMERA_ALLOW_INSECURE_HTTP", "bool", None,
           "Permit non-loopback HTTP bind without token+TLS (dangerous; dev only).",
           ("CHIMERA_TLS_CERT", "CHIMERA_TLS_KEY")),
        _f("CHIMERA_TLS_CERT", "path", None,
           "TLS certificate (PEM) for the HTTP MCP server (ADR 0178); requires "
           "CHIMERA_TLS_KEY. Mandatory with a bearer token for non-loopback binds.",
           ("CHIMERA_TLS_KEY",)),
        _f("CHIMERA_TLS_KEY", "path", None,
           "TLS private key (PEM) for the HTTP MCP server (ADR 0178); requires "
           "CHIMERA_TLS_CERT.",
           ("CHIMERA_TLS_CERT",)),
        _f("CHIMERA_PEER_EXPOSED_TOOLS", "csv", None, "Tools exposed to peers."),
        _f("CHIMERA_PEER_REGISTRY_DIR", "path", None, "Peer registry directory."),
        _f("CHIMERA_PEER_TRUST_JOURNAL_DIR", "path", None, "Peer trust journal directory."),
        _f("CHIMERA_PROTOCOL_JOURNAL_DIR", "path", None, "A2A protocol journal directory."),
        _f("CHIMERA_REMOTE_PEERS", "json", None, "Remote peer endpoints."),
        _f("CHIMERA_MCP_SERVERS", "json", None, "Mounted MCP server configs."),
        _f("CHIMERA_PEER_CARD_LLM", "bool", None, "LLM-generated peer cards."),
        _f("CHIMERA_PEER_CARDS_ON_ROTATE", "bool", None, "Regenerate peer cards on rotation."),
        _f("CHIMERA_PEER_BELIEFS_ON_ROTATE", "bool", None, "Refresh peer beliefs on rotation."),
        _f("CHIMERA_FEDERATION_METRICS", "bool", "1",
           "Federation connectivity gauge (ADR 0168). Default-ON (ADR 0179): "
           "pure observability — adds a 'federation' block to the graph-export "
           "snapshot; no hot-path effect. Set =0 to disable."),
        _f("CHIMERA_MODEL_PEERS", "bool", None,
           "Model-backed peers from the vendor ladder (ADR 0174).",
           ("CHIMERA_MODEL_PEER_VENDORS", "CHIMERA_PEER_SELECTION")),
        _f("CHIMERA_MODEL_PEER_VENDORS", "csv", None,
           "Vendor override list for model-backed peers.",
           ("CHIMERA_MODEL_PEERS",)),
        _f("CHIMERA_GLOBAL_TOOL_DENY", "csv", None, "Globally denied tool names."),
        # ── proposer scoring ──────────────────────────────────
        _f("CHIMERA_PROPOSER_SCORING_ENABLED", "bool", None, "Proposer scoring toggle."),
        _f("CHIMERA_PROPOSER_SCORE_WINDOW", "int", None, "Proposer scoring window."),
        _f("CHIMERA_PROPOSER_SCORE_THRESHOLD", "float", None, "Proposer score threshold."),
        # ── soak / doctor / ops ───────────────────────────────
        _f("CHIMERA_SOAK_RUN_ID", "str", None, "Active soak run id (enables soak ledgers)."),
        _f("CHIMERA_SOAK_FORCE_STALL", "bool", None,
           "R5 forced-stall knob (ADR 0151); inert unless CHIMERA_SOAK_RUN_ID is also set.",
           ("CHIMERA_SOAK_RUN_ID",)),
        _f("CHIMERA_PHASE1_VERIFY_CMD", "str", None, "Soak phase-1 verify command."),
        _f("CHIMERA_DOCTOR_WORKTREE_AGE_HOURS", "float", None, "Doctor: stale-worktree age."),
        _f("CHIMERA_DOCTOR_SOAK_LOG_STALE_MIN", "float", None, "Doctor: stale soak-log minutes."),
    )
)


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in TRUTHY


# ── registry-backed read path (incremental migration target) ─────────
#
# Call sites migrate to these accessors instead of hand-rolled
# ``os.environ.get(...)`` parsing. Each accessor refuses undeclared flag
# names (KeyError), so a migrated read can never silently bypass the
# registry. Reads happen at CALL time (not import time) — tests that
# monkeypatch.setenv keep working unchanged.


def _require_declared(name: str) -> None:
    if name in REGISTRY:
        return
    if any(name.startswith(p) for p in DYNAMIC_FLAG_PREFIXES):
        return
    raise KeyError(
        f"{name} is not declared in chimera.config.REGISTRY — declare it "
        f"(kind, default, description) before reading it through the registry"
    )


def flag_enabled(name: str, *, env: dict[str, str] | None = None) -> bool:
    """Bool flag read: truthy when the value is 1/true/yes/on
    (case-insensitive, stripped).

    When the flag is **unset**, the registry's declared ``default`` is used
    (ADR 0179): a flag declared default-on (``default="1"``) reads True until
    explicitly overridden, while every flag declared ``default=None`` (the
    overwhelming majority) stays off-when-unset exactly as before. An explicit
    empty/`0`/`false`/anything-non-truthy value still reads False, so
    ``CHIMERA_X=0`` always disables — even a default-on flag."""
    _require_declared(name)
    source = os.environ if env is None else env
    raw = source.get(name)
    if raw is None:
        spec = REGISTRY.get(name)
        raw = spec.default if (spec is not None and spec.default is not None) else ""
    return raw.strip().lower() in TRUTHY


def flag_int(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    env: dict[str, str] | None = None,
) -> int:
    """Int flag read: unset or malformed → ``default``; clamped to
    ``minimum`` when given."""
    _require_declared(name)
    source = os.environ if env is None else env
    raw = source.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def flag_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    env: dict[str, str] | None = None,
) -> float:
    """Float flag read: unset or malformed → ``default``; clamped to
    ``minimum`` when given."""
    _require_declared(name)
    source = os.environ if env is None else env
    raw = source.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def validate_env(env: dict[str, str] | None = None) -> list[str]:
    """Validate flag values + documented interactions; return warnings.

    Side-effect free. Call at startup (or from tests) and surface the
    returned strings to the operator. An empty list means no known
    misconfiguration.
    """
    e: dict[str, str] = dict(os.environ if env is None else env)
    warnings: list[str] = []

    # Kind checks: numeric flags must parse.
    for name, spec in REGISTRY.items():
        raw = e.get(name)
        if raw is None or raw == "":
            continue
        if spec.kind == "int":
            try:
                int(raw)
            except ValueError:
                warnings.append(f"{name}={raw!r} is not an integer")
        elif spec.kind == "float":
            try:
                float(raw)
            except ValueError:
                warnings.append(f"{name}={raw!r} is not a number")
        elif spec.kind == "json":
            import json as _json

            try:
                _json.loads(raw)
            except ValueError:
                warnings.append(f"{name} is not valid JSON")

    # Interaction rules (each mirrors documented behaviour at the call site).
    if _is_truthy(e.get("CHIMERA_GRAPH_ENABLED")) and _is_truthy(
        e.get("CHIMERA_AUTO_GRAPH_UPDATE_DISABLED")
    ):
        warnings.append(
            "CHIMERA_GRAPH_ENABLED is set but legacy "
            "CHIMERA_AUTO_GRAPH_UPDATE_DISABLED forces the graph projection OFF"
        )

    if _is_truthy(e.get("CHIMERA_AUTO_ARCHIVE_DISABLED")) and e.get(
        "CHIMERA_AUTO_ARCHIVE_AFTER_CYCLES"
    ):
        warnings.append(
            "CHIMERA_AUTO_ARCHIVE_AFTER_CYCLES is ignored while "
            "CHIMERA_AUTO_ARCHIVE_DISABLED is set"
        )

    if _is_truthy(e.get("CHIMERA_FANOUT_BUDGET")):
        width = e.get("CHIMERA_FANOUT_MAX_WIDTH")
        if width is not None:
            try:
                if int(width) < 1:
                    warnings.append(
                        "CHIMERA_FANOUT_MAX_WIDTH < 1 with CHIMERA_FANOUT_BUDGET on "
                        "would defer every parallel tool call"
                    )
            except ValueError:
                pass  # already reported by the kind check

    if _is_truthy(e.get("CHIMERA_SOAK_FORCE_STALL")) and not e.get("CHIMERA_SOAK_RUN_ID"):
        warnings.append(
            "CHIMERA_SOAK_FORCE_STALL=1 is inert without CHIMERA_SOAK_RUN_ID "
            "(double-gated soak knob)"
        )

    if e.get("CHIMERA_MODEL_PEER_VENDORS") and not _is_truthy(e.get("CHIMERA_MODEL_PEERS")):
        warnings.append(
            "CHIMERA_MODEL_PEER_VENDORS is ignored without CHIMERA_MODEL_PEERS=1"
        )

    if e.get("CHIMERA_BOLTZMANN_TEMP") and not _is_truthy(e.get("CHIMERA_BOLTZMANN_ALLOC")):
        warnings.append(
            "CHIMERA_BOLTZMANN_TEMP is ignored without CHIMERA_BOLTZMANN_ALLOC=1"
        )

    if bool(e.get("CHIMERA_TLS_CERT")) != bool(e.get("CHIMERA_TLS_KEY")):
        warnings.append(
            "CHIMERA_TLS_CERT and CHIMERA_TLS_KEY must be set together — "
            "a half-configured pair refuses to serve (ADR 0178)"
        )

    return warnings


#: The flags the combination matrix (tests/test_flag_matrix.py) exercises
#: pairwise. Criteria: default-OFF behaviour togglers that sit on or near
#: the ACT hot path, where an interaction bug means silent task failure
#: (the CHIMERA_FANOUT_BUDGET class). Value = the env setting used to turn
#: the feature ON in the matrix.
HIGH_IMPACT_FLAGS: dict[str, str] = {
    "CHIMERA_FANOUT_BUDGET": "1",
    "CHIMERA_FANOUT_MAX_WIDTH": "2",
    "CHIMERA_ENTROPY_SIGNALS": "1",
    "CHIMERA_ANNEAL_REHEAT": "1",
    "CHIMERA_BOLTZMANN_ALLOC": "1",
    "CHIMERA_TOOL_PREFILTER": "1",
    "CHIMERA_COMPLEXITY_ROUTING": "1",
    "CHIMERA_PEER_SELECTION": "1",
    "CHIMERA_HYBRID_SEARCH": "1",
    "CHIMERA_TASK_SPLITTER_ENABLED": "1",
}
