"""ACT executor — the multi-turn tool-using agent loop.

Per ADR 0003 §"ACT-phase guards (all adopted at MVP)" + ADR 0001
§"Tool registry" + §"Tool dispatch policy":

For each open task:
  1. Build messages: a Chimera-flavored system prompt + the task text.
  2. Get the tools schema visible to the current dispatch context.
  3. Pick a rung from the tier ladder (cheapest-first by default).
  4. Call ``provider.complete_with_tools()``.
  5. If the model emitted tool_uses, run them through the Dispatcher
     (which enforces the OpenClaw-style policy pipeline) and feed
     results back.
  6. Repeat up to ``max_rounds``.
  7. Apply ACT guards: ``normalize_tool_input`` on every call,
     ``detect_degenerate_loop`` on the running history.

The executor records ``api_calls`` and ``ladder_outcomes`` rows so the
adaptive routing policy (a later sprint) has data to work with.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sqlite3
import subprocess  # noqa: F401 — façade: tests patch act.subprocess (ADR 0177)
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ..memory import record_api_call, record_ladder_outcome
from ..prompts import build_system_prompt
from .witness import (
    capture_diff_for_witness,
    check_charter_file_count,
    extract_charter_excerpts,
    extract_task_charter,
    should_witness,
    witness_enabled,
)
from .witness_panel import (
    aggregate_concerns,
    build_witness_panel,
    panel_decision,
    review_with_panel,
)
from .grounding import (
    check_citation_grounding,
    extract_cited_source_files,
    extract_cited_symbols,
    synthesis_guidance_for,
)
from ..providers import (
    AnthropicProvider,
    Message,
    OpenRouterProvider,
    Provider,
    ToolResultBlock,
)
from ..providers.tiers import LadderRung
from ..providers.tiers import Provider as ProviderKind
from ..providers.tiers import eligible_rungs, select_rung
from ..tools import (
    DispatchContext,
    Dispatcher,
    LoopVerdict,
    ToolCall,
    ToolDenied,
    detect_degenerate_loop,
    detect_ping_pong,
    normalize_tool_input,
    select_tool_schemas,
)

# ADR 0177: the standalone guard/check functions live in act_guards.py
# (pure move). They are re-imported here because chimera.core.act is the
# public façade — external consumers and the test suite import (and
# monkeypatch) these names on THIS module, and ActExecutor resolves them
# as act-module globals so those monkeypatches take effect.
from .act_guards import (
    _ARTIFACT_PATTERN,  # noqa: F401
    _NL_ARTIFACT_PATTERN,  # noqa: F401
    _INTENDED_CODE_PATH_PATTERN,  # noqa: F401
    _BACKTICK_CODE_PATH_PATTERN,  # noqa: F401
    intended_code_paths,  # noqa: F401
    _OR_BETWEEN_PATHS_RE,  # noqa: F401
    _SENTENCE_BREAK_RE,  # noqa: F401
    intended_code_path_groups,  # noqa: F401
    _normalize_intended_groups,  # noqa: F401
    _group_already_on_disk,  # noqa: F401
    check_scope_evasion,  # noqa: F401
    _WRITING_TOOL_NAMES,  # noqa: F401
    extract_write_targets_from_calls,  # noqa: F401
    _WRITE_DEST_RE,  # noqa: F401
    _code_write_destinations,  # noqa: F401
    _CHIMERA_SOURCE_PATH_PATTERN,  # noqa: F401
    _TEST_PATH_PATTERN,  # noqa: F401
    _FIX_WITHOUT_TEST_EXCLUDED_SOURCES,  # noqa: F401
    _charter_test_satisfied,  # noqa: F401
    check_fix_without_test,  # noqa: F401
    check_phase_fix_without_test,  # noqa: F401
    check_syntax_valid,  # noqa: F401
    _imported_names,  # noqa: F401
    _import_shadow_scan_root,  # noqa: F401
    check_import_shadowing,  # noqa: F401
    _git_changed_paths,  # noqa: F401
    _gate_targets,  # noqa: F401
    _postmortem_gate_targets,  # noqa: F401
    _PYTEST_CLAIM_PATTERN,  # noqa: F401
    _extract_claimed_pytest_files,  # noqa: F401
    _PYTEST_MISSING_STDERR,  # noqa: F401
    _run_pytest_file,  # noqa: F401
    check_test_claim_valid,  # noqa: F401
    _first_pytest_failure_tail,  # noqa: F401
    _COMMIT_CLAIM_PATH_PATTERN,  # noqa: F401
    _extract_commit_path_claims,  # noqa: F401
    check_commit_message_diff_drift,  # noqa: F401
    _AGENT_COMMIT_TASK_RE,  # noqa: F401
    _task_demands_agent_commit,  # noqa: F401
    check_commit_not_executed,  # noqa: F401
    _VERIFY_GREEN_TASK_RE,  # noqa: F401
    _task_demands_verify_green,  # noqa: F401
    check_verify_claim_invalid,  # noqa: F401
    _PROVENANCE_VERSION_PATTERN,  # noqa: F401
    _PROVENANCE_ADR_PATTERN,  # noqa: F401
    _extract_provenance_claims,  # noqa: F401
    _version_resolves,  # noqa: F401
    _adr_resolves,  # noqa: F401
    check_provenance_claim_valid,  # noqa: F401
    check_scope_evasion_strict,  # noqa: F401
    expected_artifacts,  # noqa: F401
    _CONTENT_MARKER_PATTERNS,  # noqa: F401
    expected_content_markers,  # noqa: F401
    check_content_markers,  # noqa: F401
    check_artifacts,  # noqa: F401
    _INBOX_CHECKBOX_LINE,  # noqa: F401
    _INBOX_WRITE_PATTERN,  # noqa: F401
    _is_inbox_write,  # noqa: F401
    _parse_inbox_tasks,  # noqa: F401
    _inbox_bullet_artifacts,  # noqa: F401
    check_inbox_claim_validity,  # noqa: F401
    revert_inbox_lie,  # noqa: F401
    _read_inbox_now,  # noqa: F401
    _revert_inbox_lies_on_disk,  # noqa: F401
)

logger = logging.getLogger(__name__)


def _forced_rung(model_id: str) -> LadderRung:
    """Resolve ``CHIMERA_ACT_FORCE_MODEL`` to a concrete rung.

    A known ladder model or alias (``moonshotai/kimi-k2.7-code``,
    ``deepseek/deepseek-v4-pro``, ``claude-opus-4-7``, …) resolves to its REAL
    rung — true provider (OpenRouter *or* Anthropic), real costs + capabilities.
    This lets a soak pin ACT to any ladder model for an A/B (ADR 0183 A.1) — e.g.
    the ``code`` tier's kimi lead vs. the ``sonnet`` lead deepseek — not just an
    Anthropic one. An unknown id falls back to a synthetic Anthropic rung (the
    original create/self-determine use: pin a future ``claude-*`` model)."""
    from ..providers.tiers import resolve_rung

    try:
        return resolve_rung(model_id)
    except ValueError:
        return _forced_anthropic_rung(model_id)


def _forced_anthropic_rung(model_id: str) -> LadderRung:
    """A synthetic tool-capable rung pinned to the Anthropic provider + ``model_id``.
    Reuses a known tier's limits/costs when the model matches one; otherwise applies
    conservative defaults. The fallback for an id no ladder knows — kept Anthropic
    since the original knob existed to bypass the unreliable OpenRouter rungs."""
    from ..providers.tiers import MODEL_TIERS, ModelCapabilities, ModelConfig

    base = next((c for c in MODEL_TIERS.values() if c.model_id == model_id), None)
    if base is not None:
        cfg = replace(base, provider=ProviderKind.ANTHROPIC)
    else:
        cfg = ModelConfig(
            model_id=model_id, max_calls_per_minute=50, max_calls_per_hour=1000,
            max_calls_per_day=5000, input_cost_per_mtok=3.0,
            output_cost_per_mtok=15.0, provider=ProviderKind.ANTHROPIC,
        )
    return LadderRung(config=cfg, capabilities=ModelCapabilities(supports_tools=True))


_CONTINUATION_HEAD = 800
_CONTINUATION_TAIL = 800
_CONTINUATION_INLINE_MAX = 2000  # files smaller than this embed in full
_CONTINUATION_MAX_PATHS = 6


def _continuation_context(task_text: str) -> str:
    """v4.42 / v4.43: build a "Continuation context" block for the system
    prompt summarising any artifact paths the task references that already
    exist on disk. Tells the model "the prior cycle did X — continue from
    there, do not restart from zero."

    v4.43 improvement: small files (<2KB) embed in full; larger files
    show HEAD + TAIL so the model sees both the structural top and the
    most recent progress (the tail is where partial work usually
    accumulates — appended sections, last-written paragraphs).

    Returns "" when no continuation is detected (fresh task).
    """
    expected = expected_artifacts(task_text)
    if not expected:
        return ""
    base = Path.cwd()
    blocks: list[str] = []
    for rel in expected[:_CONTINUATION_MAX_PATHS]:
        p = base / rel
        if not p.exists() or not p.is_file():
            continue
        try:
            st = p.stat()
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        n_lines = text.count("\n")
        if len(text) <= _CONTINUATION_INLINE_MAX:
            preview = text
            marker = ""
        else:
            head = text[:_CONTINUATION_HEAD].rstrip()
            tail = text[-_CONTINUATION_TAIL:].lstrip()
            elided = len(text) - _CONTINUATION_HEAD - _CONTINUATION_TAIL
            preview = (
                f"{head}\n"
                f"  ...[{elided} bytes elided from middle]...\n"
                f"{tail}"
            )
            marker = ""
        blocks.append(
            f"- `{rel}` ({st.st_size} bytes, {n_lines} lines):\n"
            f"  ```\n  {preview}{marker}\n  ```"
        )
    if not blocks:
        return ""
    body = "\n".join(blocks)
    return (
        "## Continuation context\n"
        "Prior cycle(s) produced these artifacts already. CONTINUE the work "
        "(append, finish, fix the specific gaps) — do NOT re-research, "
        "re-fetch, or re-validate content that's clearly already present. "
        "Treat existing content as authoritative unless it is obviously "
        "truncated or syntactically broken. Your goal is to land the "
        "missing pieces and STOP:\n"
        f"{body}"
    )


def _schema_hint(registry, tool_name: str, args: dict[str, Any]) -> str:
    """v4.41: render a one-line schema hint for the model on validation
    failure. Format: ``hint: <name>({required: ..., received: ...})``."""
    try:
        entry = registry.get(tool_name)
    except Exception:  # noqa: BLE001
        return ""
    if entry is None:
        return f"hint: unknown tool {tool_name!r}; check the registered tool list."
    schema = entry.schema or {}
    fn = schema.get("function") if schema.get("type") == "function" else schema
    params = (fn or {}).get("parameters") or {}
    props = params.get("properties") or {}
    required = list(params.get("required") or [])
    received = sorted(args.keys()) if isinstance(args, dict) else []
    fields: list[str] = []
    for key in required:
        prop = props.get(key) or {}
        fields.append(f"{key}: {prop.get('type', 'any')} (required)")
    optional = [k for k in props.keys() if k not in required]
    for key in optional[:4]:
        prop = props[key]
        fields.append(f"{key}: {prop.get('type', 'any')}")
    schema_line = ", ".join(fields) or "(no parameters)"
    return (
        f"hint: {tool_name}({{ {schema_line} }}). "
        f"received keys: {received or '[]'}."
    )


DEFAULT_SYSTEM_PROMPT_EXTRA = (
    "Task-specific guidance:\n"
    "- Prefer the shell tool for read-only inspection of /mind and /state.\n"
    "- Use http_fetch / web_search when the task points outside the container.\n"
    "- Use code_exec for computation, not shell `bash -c`.\n"
    "- When you have enough to answer, respond and stop.\n"
    # v4.82 (ADR 0096): explicit writable-scope grant. Across four soaks
    # the agent treated mind/ as the boundary of writable scope and
    # produced spec docs under mind/research/ when INBOX tasks named
    # source files under chimera/. Make the grant explicit so the model
    # does not infer a constraint the runtime never imposed.
    "- Writable roots in this worktree: chimera/, tests/, docs/, "
    "mind/, scripts/, state/. The chimera/ source IS your code — when "
    "an INBOX task names a path under chimera/ or tests/, edit that "
    "file directly via shell or code_exec. Do NOT write a spec under "
    "mind/ in lieu of patching the named file."
)


@dataclass
class ActResult:
    task_text: str
    completed: bool
    rounds: int
    finish_reason: str
    write_targets: list[str] = field(default_factory=list)
    tool_call_history: list[ToolCall] = field(default_factory=list)
    final_text: str = ""
    failure_reason: str | None = None
    api_call_count: int = 0
    missing_artifacts: list[str] = field(default_factory=list)
    # v4.83 (ADR 0095): symbols the synthesis text named but that don't
    # appear in any cited source file. Populated only when
    # finish_reason == "ungrounded_citation".
    ungrounded_citations: list[str] = field(default_factory=list)
    # v4.82 (ADR 0096): code-root paths the INBOX named that the agent
    # never appeared to touch. Populated only when
    # finish_reason == "scope_evasion".
    unedited_paths: list[str] = field(default_factory=list)
    # v4.90 (ADR 0099): chimera/ source paths the agent touched without
    # also writing a tests/test_*.py file. Populated only when
    # finish_reason == "fix_without_test".
    untested_fix_paths: list[str] = field(default_factory=list)
    # v4.96 (ADR 0101): ``[(path, missing_marker), ...]`` for artifacts
    # the agent wrote that exist but lack a required content marker
    # (e.g. a sentinel heading the task explicitly named). Populated
    # only when finish_reason == "artifact_incomplete".
    incomplete_artifacts: list[tuple[str, str]] = field(default_factory=list)
    # v4.100 (ADR 0104): ``[(task_text, [missing_artifact, ...]), ...]``
    # for INBOX checkbox flips ([ ] → [x]) the agent made without producing
    # the deliverable the bullet promised. Populated only when
    # finish_reason == "inbox_claim_invalid".
    invalid_inbox_claims: list[tuple[str, list[str]]] = field(default_factory=list)
    # v4.101 (ADR 0105): ``[(path, error_msg), ...]`` for *.py paths the
    # agent wrote that fail py_compile. Populated only when
    # finish_reason == "syntax_invalid". Soak v10 surfaced this: the
    # agent shipped a structurally invalid `return ActResult(...)` block
    # and the runner spun on identical SyntaxError tracebacks for 13
    # minutes before the operator killed it.
    syntax_failures: list[tuple[str, str]] = field(default_factory=list)
    # B2 (v40′ scope-creep sprint): ``[(path, msg), ...]`` for files where a
    # function-local import shadows a module-level name (the os/Path
    # UnboundLocalError class that bricked v40 attempts #2 and #4).
    # Populated only when finish_reason == "import_shadowing".
    import_shadow_failures: list[tuple[str, str]] = field(default_factory=list)
    # Sub-chip 2 (v40′ scope-creep sprint): ``[(path, msg), ...]`` for a
    # written postmortem whose READY-FOR-REMEDIATION ``tests_passing``
    # claim contradicts the test-run ledger. Populated only when
    # finish_reason == "postmortem_dishonest".
    postmortem_honesty_failures: list[tuple[str, str]] = field(default_factory=list)
    # v4.113 (ADR 0113): test_claim_invalid — pytest claims the task
    # made (`uv run pytest tests/X.py`) that re-running from the
    # operator side actually fails. Soak v16 surfaced agents shipping
    # NameError-at-runtime regressions with confident "tests pass"
    # claims. Populated only when finish_reason == "test_claim_invalid".
    test_claim_failures: list[str] = field(default_factory=list)
    # v4.115 (ADR 0115): commit_message_diff_drift — paths the most-recent
    # [agent] commit message explicitly claimed to have written (e.g.
    # ``tests/test_X.py``) that don't appear in the cumulative branch
    # diff against the base ref. Soak v20-relaunch surfaced an agent
    # committing chimera/core/act.py + a research doc, with a commit
    # message body claiming the tests file was part of the work — the
    # tests file existed on disk but was never git-add'd. Populated
    # only when finish_reason == "commit_message_diff_drift".
    commit_message_drift_claims: list[str] = field(default_factory=list)
    # v4.116 (ADR 0116): charter_file_count_violations — files exceeding charter file-count budget. Populated only when finish_reason == "charter_file_count_exceeded".
    charter_file_count_violations: list[str] = field(default_factory=list)
    # v4.118 (ADR 0118): provenance_claim_invalid — version strings
    # (``vX.Y``) or ADR numbers (``ADR NNNN``) the most-recent [agent]
    # commit message cites that don't resolve against the repo (no
    # matching tag, no source-file mention, no ``docs/adr/NNNN-*.md``).
    # Soak v20-3rd surfaced an agent shipping a commit message claiming
    # "v4.120 / ADR 0120" when the actual platform was v4.116 and ADR
    # 0120 didn't exist — fabricated authority. Populated only when
    # finish_reason == "provenance_claim_invalid".
    provenance_claim_failures: list[str] = field(default_factory=list)
    # v4.102 (ADR 0106): witness review concerns. Populated only when
    # finish_reason == "witness_rejected". Each entry is a one-sentence
    # concern naming the file and the structural / correctness defect
    # the witness model flagged. Capped at 5 by parse_verdict().
    witness_concerns: list[str] = field(default_factory=list)


_READY_TESTS_PASSING_RE = re.compile(
    r"(?im)^\s*tests_passing\s*:\s*(true|false)\b"
)
_READY_VERDICT_RE = re.compile(
    r"(?im)^\s*verdict\s*:\s*([A-Za-z_]+)\b"
)
# Numeric-honesty fields (drift chip): the READY block's act_cycles and
# spend_usd MUST be READ from ground truth, not estimated. v40′/v41/v42
# all drifted here (e.g. v42 claimed act_cycles: 3 / spend_usd: 0.02 for a
# 15-cycle / $0.16 run). These promote the two numbers to checked fields.
_READY_ACT_CYCLES_RE = re.compile(
    r"(?im)^\s*act_cycles\s*:\s*(\d+)\b"
)
_READY_SPEND_USD_RE = re.compile(
    r"(?im)^\s*spend_usd\s*:\s*\$?\s*([0-9]+(?:\.[0-9]+)?)\b"
)


def _run_spend_usd_best_effort() -> float | None:
    """Total USD spend for the current run, read from the Chimera DB, or
    ``None`` if it cannot be established.

    Reuses :func:`chimera.core.budget.rolling_spend_usd` (token-priced SUM
    over ``api_calls``) with an effectively-unbounded window, so it counts
    the whole soak. A fresh read-only connection is opened and closed; WAL
    permits concurrent readers, so this does not contend with the loop
    thread's connection. Fail-soft: any error (missing DB, locked, pricing
    gap) returns ``None`` and the spend rule no-ops — the postmortem is
    never blocked on an *unverifiable* number.
    """
    try:
        from ..memory.store import connect, default_db_path
        from .budget import rolling_spend_usd

        db_path = default_db_path()
        if not Path(db_path).exists():
            return None
        conn = connect(db_path)
        try:
            # 100-year window == total run spend (the soak DB is fresh).
            return rolling_spend_usd(conn, minutes=100 * 365 * 24 * 60)
        finally:
            conn.close()
    except Exception:
        return None


def check_postmortem_honesty(
    write_targets: list[str],
    worktree_root: Path | str | None = None,
) -> list[tuple[str, str]]:
    """Return ``[(path, msg), ...]`` for a written postmortem whose
    READY-FOR-REMEDIATION claims contradict the test-run ledger ground
    truth — either the ``tests_passing`` field, or a ``verdict``
    incoherent with it.

    Sub-chip 2 (v40′ scope-creep sprint) moved the verdict-honesty
    cross-check INTO the ACT gate: a postmortem whose ``tests_passing``
    disagrees with the ledger is rejected the moment it is written, not
    via a later manual cross-check.

    H2 (v42 scope-creep sprint) adds **verdict coherence**: a
    ``verdict: CONVERGED`` (or PARTIAL) claim must be EARNED — backed by a
    passing test-run in the ledger and by ``tests_passing: true``. v42
    attempt #1 wrote ``verdict: CONVERGED`` despite an off-charter file in
    the commit; this catches the broader "claimed converged without the
    evidence" failure at write time. (Post-H1 an off-charter file can't
    even land, so the committed diff is scope-clean by construction; this
    is the matching honesty gate on the verdict CLAIM.)

    Numeric-honesty (drift chip, post-v42) adds two more checked fields —
    the last un-closed honesty hole before the v43 parallel rung, where
    three postmortems land at once and hand-auditing numbers is hardest:

    - Rule D (``act_cycles``): must agree with the ledger's ACT-execute
      record count (``summarize_run().act_cycles``) within a small band
      (the count can tick by ~1 between the agent's read and this gate).
    - Rule E (``spend_usd``): must agree with the run's actual DB spend
      within a generous relative band. Fail-soft — skipped entirely if the
      DB spend cannot be read or is non-positive, so an *unverifiable*
      number never blocks a postmortem. This is the gate the v40′/v41/v42
      caveat asked for: ground truth is now CHECKED, not merely available.

    No-op outside a soak (``CHIMERA_SOAK_RUN_ID`` unset) or when no
    summary is available, so normal ``chimera run`` is unaffected. Only
    inspects ``.md`` targets that carry a ``tests_passing:`` line (i.e. a
    READY block). Fail-soft. One reason per file (most severe; rules are
    checked in A→E severity order).

    Target source (v43 fix): ``write_targets`` UNION the worktree's
    changed ``.md`` files when ``worktree_root`` is given. The v43 soak
    ran every write-target gate dormant because ``write_targets`` was
    empty all run (the agent wrote via ``shell``, not a captured writing
    tool); the git fallback makes the gate fire on the postmortem that is
    actually on disk, regardless of which tool wrote it. With
    ``worktree_root=None`` only ``write_targets`` is inspected (legacy
    behavior — keeps unit tests and non-soak runs hermetic).
    """
    from .soak_ledger import soak_run_id, summarize_run

    if not soak_run_id():
        return []
    summary = summarize_run()
    if summary is None:
        return []
    ground_truth = bool(summary.get("tests_passed_any"))

    failures: list[tuple[str, str]] = []
    for path in _postmortem_gate_targets(write_targets, worktree_root):
        if not path.endswith(".md"):
            continue
        p = Path(path)
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        m = _READY_TESTS_PASSING_RE.search(text)
        if m is None:
            continue  # not a postmortem with a READY block
        claimed = m.group(1).lower() == "true"
        vm = _READY_VERDICT_RE.search(text)
        verdict = vm.group(1).upper() if vm else None

        reason: str | None = None
        # Rule A (sub-chip 2): tests_passing must match the ledger.
        if claimed != ground_truth:
            reason = (
                f"postmortem claims tests_passing: {str(claimed).lower()} but "
                + ("the test-run ledger shows no passing run recorded"
                   if not ground_truth else
                   "the test-run ledger shows tests DID pass — cite the ledger")
            )
        # Rule B (H2): a CONVERGED verdict must be earned by a passing run.
        elif verdict == "CONVERGED" and not ground_truth:
            reason = (
                "postmortem verdict: CONVERGED but the test-run ledger shows "
                "no passing run — CONVERGED requires a recorded green test run"
            )
        # Rule C (H2): a CONVERGED verdict contradicts tests_passing: false.
        elif verdict == "CONVERGED" and not claimed:
            reason = (
                "postmortem verdict: CONVERGED contradicts its own "
                "tests_passing: false — an unearned verdict claim"
            )
        # Rule D (drift): act_cycles must not OVER-claim the ledger's
        # ACT-execute record count. OVER-claim only (v44 R2): the v44 soak
        # exposed a moving-target deadlock — act_cycles is a SNAPSHOT taken
        # when the agent reads summarize_run(), but the ledger keeps growing
        # every cycle (postmortem-writing churn especially), and the #163
        # git-status fallback re-scans the unchanged postmortem on EVERY
        # phase-2 cycle. Comparing a fixed claim against a monotonically
        # growing ledger means any churn makes the claim unsatisfiable, so a
        # CORRECT build (v44: 6/6) could never commit. Under-claiming is also
        # legitimate on its face (the agent may report build-cycles ⊆ all
        # ACT records). So the gate hard-blocks only OVER-claiming — claiming
        # MORE cycles than the ledger holds, which is impossible-without-
        # inflation. A growing ledger only widens the allowance, never
        # narrows it → no deadlock. (The cumulative-reporting CONVENTION
        # still stands in the template/INBOX; the gate just no longer
        # deadlocks on a conservative or stale count. tests_passing/verdict —
        # Rules A–C, the load-bearing honesty — remain hard two-sided gates.)
        else:
            cm = _READY_ACT_CYCLES_RE.search(text)
            gt_cycles = summary.get("act_cycles")
            if cm is not None and isinstance(gt_cycles, int) and gt_cycles > 0:
                claimed_cycles = int(cm.group(1))
                band = max(2, round(gt_cycles * 0.25))
                if claimed_cycles - gt_cycles > band:
                    reason = (
                        f"postmortem claims act_cycles: {claimed_cycles} but the "
                        f"ledger records only {gt_cycles} ACT-execute cycles "
                        f"(+{band} allowed) — you cannot have run more cycles than "
                        f"the ledger holds; read summarize_run().act_cycles"
                    )
            # Rule E (drift): spend_usd must not OVER-claim the run's actual
            # DB spend. OVER-claim only (v44 R2), for the same moving-target
            # reason — spend also accrues every cycle, so a fixed claim vs a
            # growing total deadlocks under churn. Fail-soft (skipped if DB
            # spend unreadable/non-positive). Flag only claiming MORE than
            # the DB shows (beyond a generous band); under-reporting a stale
            # snapshot is tolerated.
            if reason is None:
                sm = _READY_SPEND_USD_RE.search(text)
                if sm is not None:
                    actual_spend = _run_spend_usd_best_effort()
                    if actual_spend is not None and actual_spend > 0:
                        claimed_spend = float(sm.group(1))
                        if claimed_spend - actual_spend > max(0.05, actual_spend * 0.5):
                            reason = (
                                f"postmortem claims spend_usd: {claimed_spend:.2f} "
                                f"but the run DB shows only ${actual_spend:.2f} actual "
                                "spend — you cannot have spent more than the DB "
                                "records; read the `chimera cost` total"
                            )
        if reason is not None:
            failures.append((str(path), reason))
    return failures


class ActExecutor:
    """Runs the tool-using inner loop for a single task."""

    # v4.71: tier-aware output-token budget. The flat 2048 cap was
    # producing repeated ``finish=length`` truncations on opus tool_use
    # turns (recorded in cycle 27 history meta). Anthropic's published
    # output ceilings: haiku-4.5 ≈ 8k, sonnet-4.6 ≈ 64k extended
    # thinking / 8k standard, opus-4.7 ≈ 32k. We pick conservative
    # defaults below the ceilings and let operators override via
    # ``CHIMERA_ACT_MAX_TOKENS`` (global) or
    # ``CHIMERA_ACT_MAX_TOKENS_<TIER>`` (per-tier). See
    # docs/runbook.md §"Output-token budget".
    _TIER_MAX_TOKENS: dict[str, int] = {
        "haiku": 4096,
        "sonnet": 8192,
        # The code tier leads with a reasoning-then-code model (kimi) that
        # front-loads thinking tokens; give it sonnet-equivalent headroom so a
        # tight cap doesn't truncate it to an empty completion (ADR 0183 A.1).
        "code": 8192,
        "opus": 16384,
    }

    @classmethod
    def _resolve_max_tokens(cls, tier: str) -> int:
        import os
        per_tier = os.environ.get(f"CHIMERA_ACT_MAX_TOKENS_{tier.upper()}")
        if per_tier and per_tier.isdigit():
            return int(per_tier)
        glob = os.environ.get("CHIMERA_ACT_MAX_TOKENS")
        if glob and glob.isdigit():
            return int(glob)
        return cls._TIER_MAX_TOKENS.get(tier, 4096)

    def __init__(
        self,
        *,
        dispatcher: Dispatcher,
        providers: dict[ProviderKind, Provider],
        db: sqlite3.Connection,
        tier: str = "haiku",
        max_rounds: int = 12,
        max_tokens: int | None = None,
        system_prompt_extra: str = DEFAULT_SYSTEM_PROMPT_EXTRA,
        chronicle: Any = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._providers = providers
        self._db = db
        self._tier = tier
        self._max_rounds = max_rounds
        # v4.71: None → tier-aware default. Explicit ints still honoured
        # (preserves backward compatibility with existing callers/tests).
        self._max_tokens = (
            max_tokens if max_tokens is not None else self._resolve_max_tokens(tier)
        )
        self._system_prompt_extra = system_prompt_extra
        # v4.84 (ADR 0097): optional Chronicle for three-strikes warnings.
        # Loop wires it in; tests and library callers can leave None.
        self._chronicle = chronicle

    def _build_system_prompt(self, *, cycle: int) -> str:
        return build_system_prompt(
            self._db,
            cycle=max(cycle, 0),
            extra=self._system_prompt_extra,
        )

    @classmethod
    def from_env(
        cls,
        *,
        dispatcher: Dispatcher | None,
        db: sqlite3.Connection,
        tier: str | None = None,
    ) -> ActExecutor | None:
        """Construct using whichever provider env keys are available.

        Returns ``None`` if neither key is set — caller should skip ACT.

        ``dispatcher`` may be None for helpers that only need provider
        access (e.g. the skills CLI uses this just to get .providers).

        When the caller doesn't pass ``tier`` (the loop's path), the base ACT
        tier comes from ``CHIMERA_ACT_TIER`` (default ``haiku``) — the knob that
        routes CRAWL ACT at the ``code`` tier (ADR 0183 A.1). An explicit
        ``tier`` argument always wins, so callers that need a specific tier
        (e.g. the skills CLI) are unaffected.
        """
        if tier is None:
            tier = os.environ.get("CHIMERA_ACT_TIER", "haiku")
            from ..providers.tiers import TIER_LADDERS
            if tier not in TIER_LADDERS:
                logger.warning(
                    "CHIMERA_ACT_TIER=%r is not a known tier %s; using haiku",
                    tier, list(TIER_LADDERS),
                )
                tier = "haiku"
        providers: dict[ProviderKind, Provider] = {}
        try:
            providers[ProviderKind.ANTHROPIC] = AnthropicProvider()
        except RuntimeError:
            pass
        try:
            providers[ProviderKind.OPENROUTER] = OpenRouterProvider()
        except RuntimeError:
            pass
        if not providers:
            return None
        if dispatcher is None:
            # v2.5: default to PeerAwareDispatcher so cross-agent trust gating
            # is on by default for any caller that doesn't supply its own.
            from ..a2a import PeerAwareDispatcher
            dispatcher = PeerAwareDispatcher()  # uses default_registry
        return cls(dispatcher=dispatcher, providers=providers, db=db, tier=tier)

    @property
    def providers(self) -> dict[ProviderKind, Provider]:
        return self._providers

    # ── execution ──────────────────────────────────────────

    def _pick_rung(self, *, requires_tools: bool) -> LadderRung:
        # CHIMERA_ACT_FORCE_MODEL pins ACT to one ladder model instead of the
        # ladder's cheapest-first rung. Originally for the self-determination soaks
        # (the cheap OpenRouter rungs returned empty/weak completions, so the agent
        # could not converge on test-less targets) — pin a capable Anthropic model.
        # Now resolves ANY ladder model (real provider + costs), so a soak can pin
        # ACT to the code tier's kimi lead or the sonnet lead deepseek for an A/B
        # (ADR 0183 A.1) without rewiring the ladder.
        forced = os.environ.get("CHIMERA_ACT_FORCE_MODEL")
        if forced:
            return _forced_rung(forced)
        return select_rung(self._tier, requires_tools=requires_tools)

    def _provider_for(self, rung: LadderRung) -> Provider | None:
        return self._providers.get(rung.config.provider)

    def _model_id_for(self, rung: LadderRung) -> str:
        if rung.config.provider is ProviderKind.ANTHROPIC:
            return rung.config.model_id
        return rung.config.openrouter_model_id

    async def execute(
        self,
        task_text: str,
        *,
        cycle: int,
        context: DispatchContext | None = None,
    ) -> ActResult:
        # v4.46: persistent task-escalation memory. If this task's
        # signature has failed before, start at a higher tier than the
        # default — avoids re-running deepseek-flash 26 times on a job
        # that demonstrably needs sonnet.
        from .escalation import recommended_tier, record_failure
        promoted_tier = recommended_tier(
            self._db, task_text=task_text, default_tier=self._tier,
        )
        if promoted_tier != self._tier:
            logger.info(
                "act: escalating tier %s → %s based on prior failures",
                self._tier, promoted_tier,
            )
            self._tier = promoted_tier

        # v4.84 (ADR 0097): post-escalation remediation. If priors exist
        # for this signature, prepend a hint to the task text. At three
        # strikes, skip the task entirely and write an operator warning
        # to the chronicle.
        from .remediation import (
            SKIPPED_THREE_STRIKES,
            chronicle_warning_body,
            matching_escalations,
            remediation_decision,
        )
        decision = remediation_decision(self._db, task_text=task_text)
        if decision.skip:
            logger.warning(
                "act: skipping task after %d consecutive failures "
                "(three-strikes); writing chronicle warning",
                decision.matched_failures,
            )
            if self._chronicle is not None:
                try:
                    self._chronicle.upsert_section(
                        section_name="Escalation Warnings",
                        body=chronicle_warning_body(
                            task_text,
                            matching_escalations(self._db, task_text=task_text),
                        ),
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "chronicle.upsert_section raised on three-strikes warning",
                    )
            return ActResult(
                task_text=task_text,
                completed=False,
                rounds=0,
                finish_reason=SKIPPED_THREE_STRIKES,
                failure_reason=(
                    f"three-strikes auto-skip after "
                    f"{decision.matched_failures} prior failures"
                ),
            )

        result = await self._execute_inner(
            task_text,
            cycle=cycle,
            context=context,
            remediation_preamble=decision.preamble,
            matched_failures=decision.matched_failures,
        )

        # On any non-completion exit, record the failure so the NEXT
        # attempt at a similar signature picks a higher tier.
        #
        # v4.53: ``cost_cap`` is excluded — a cap trip is a *spend*
        # problem, not a *capability* problem. Promoting tier would
        # just burn the cap faster on the next attempt. The cycle
        # rotates and the task gets a fresh budget on the next cycle.
        if not result.completed and result.finish_reason not in (
            "cost_cap", "rolling_hour_cap", "task_budget",
        ):
            try:
                record_failure(
                    self._db,
                    task_text=task_text,
                    tier=self._tier,
                    finish_reason=result.finish_reason,
                    rounds_used=result.rounds,
                    cycle=cycle,
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "task_escalations record_failure raised; continuing",
                )
        return result

    async def _execute_inner(
        self,
        task_text: str,
        *,
        cycle: int,
        context: DispatchContext | None = None,
        remediation_preamble: str = "",
        matched_failures: int = 0,
    ) -> ActResult:
        ctx = context or DispatchContext()
        # v4.100 (ADR 0104): snapshot the INBOX state BEFORE the model
        # runs so check_inbox_claim_validity can diff `[ ]`→`[x]` flips
        # at the end of the task. Read-only snapshot — if the file
        # doesn't exist or is unreadable, the diff is a no-op (no
        # flips to find against an empty prior).
        prior_inbox_text = ""
        try:
            inbox_path = Path.cwd() / "mind" / "INBOX.md"
            if inbox_path.exists() and inbox_path.is_file():
                prior_inbox_text = inbox_path.read_text(
                    encoding="utf-8", errors="replace",
                )
        except OSError:
            prior_inbox_text = ""
        # v4.84 (ADR 0097): preamble surfacing prior-attempt diagnosis.
        # Prepend on the user message so it stays in the model's
        # immediate context window even after long tool sequences.
        user_message_text = (
            f"{remediation_preamble}{task_text}" if remediation_preamble
            else task_text
        )
        # v4.42: continuation-context detection. If the task text references
        # artifact paths under mind/ or state/ that already exist on disk,
        # the prior cycle made progress; surface the partial state to the
        # model so it doesn't restart from zero.
        continuation_block = _continuation_context(task_text)
        system_prompt = self._build_system_prompt(cycle=cycle)
        if continuation_block:
            system_prompt = f"{system_prompt}\n\n{continuation_block}"
        # v4.83 (ADR 0095): synthesis-task grounding guidance. When the
        # task asks to read source file(s) and produce a verdict, prepend
        # an explicit "quote before you cite" instruction. This is the
        # cheapest of the three grounding controls and tends to dominate
        # the others in practice.
        grounding_guidance = synthesis_guidance_for(task_text)
        if grounding_guidance:
            system_prompt = f"{system_prompt}\n\n{grounding_guidance}"
        messages: list[Message] = [
            Message.system(system_prompt),
            Message.user(user_message_text),
        ]
        # v4.119 (ADR 0165): semantic tool pre-filter. With
        # CHIMERA_TOOL_PREFILTER off (default) this is byte-identical to
        # registry.schemas(); on, it scopes the per-task catalog to the
        # core floor + lexically-relevant dynamic/mcp tools.
        tools_schema = select_tool_schemas(self._dispatcher.registry, task_text)
        history: list[ToolCall] = []
        write_targets: list[str] = []
        api_call_count = 0
        final_text = ""

        # v3.11: walk all eligible rungs cheapest-first. We start on the
        # cheapest; on a provider error we record retry_exhausted and
        # escalate to the next rung. Out of rungs → give up.
        #
        # ADR 0169: decorrelated reheat-on-stuck. When prior same-signature
        # failures exist (``matched_failures``, threaded in from the remediation
        # decision computed in ``execute``), rotate the cheapest-first ladder so
        # a DIFFERENT vendor leads this attempt — an annealing reheat that
        # decorrelates correlated failure modes. Off by default →
        # byte-identical cheapest-first order.
        from ..providers.tiers import anneal_reheat_enabled, decorrelated_rung_order
        if anneal_reheat_enabled() and matched_failures > 0:
            _base_rungs = decorrelated_rung_order(
                self._tier,
                reheat_count=matched_failures,
                requires_tools=True,
            )
            logger.info(
                "act: annealing reheat — rotating ladder by %d (lead vendor %s) "
                "after %d prior failures",
                matched_failures,
                _base_rungs[0].config.model_id if _base_rungs else "?",
                matched_failures,
            )
        else:
            _base_rungs = eligible_rungs(self._tier, requires_tools=True)
        rung_list = [
            r for r in _base_rungs
            if self._provider_for(r) is not None
        ]
        if not rung_list:
            return ActResult(
                task_text=task_text,
                completed=False,
                rounds=0,
                finish_reason="provider_unavailable",
                failure_reason=f"no provider available for tier {self._tier!r}",
            )
        rung_idx = 0
        rung = rung_list[0]
        provider = self._provider_for(rung)
        assert provider is not None
        last_provider_error: str | None = None

        # v4.5: per-task adaptive budget — scales with declared artifacts
        # and named tool keywords, capped at 32. v4.47: also scaled by
        # the (possibly v4.46-promoted) tier so opus gets more rounds
        # than haiku for the same task.
        from .budget import dynamic_max_rounds

        effective_max_rounds = dynamic_max_rounds(
            task_text, base=self._max_rounds, tier=self._tier,
        )
        # v4.50: wall-clock anchor used to measure round-boundary latency
        # — the time between the prior round's last tool completion and
        # this round's provider call. None on the very first round.
        import time as _time
        prior_tools_done_at: float | None = None
        from .budget import (
            check_cycle_cost_cap,
            check_rolling_hour_cost_cap,
            check_task_budget,
            CycleCostCapExceeded,
            RollingHourCostCapExceeded,
            TaskBudgetExceeded,
        )
        from .escalation import _signature as _task_signature
        # v4.60: signature for this task — used by the per-task budget
        # cap AND persisted on every api_calls row so future cycles can
        # sum cross-cycle spend for the same task.
        task_sig = _task_signature(task_text)
        for round_idx in range(effective_max_rounds):
            # v4.53: hard-stop if this cycle has spent over the cap.
            # v4.57: also hard-stop if rolling-60m spend exceeds cap.
            # v4.60: also hard-stop if THIS TASK has exceeded its budget
            # across cycles (catches the stuck-task pattern from the
            # 2026-05-19 burn where escalation re-promoted the same
            # task across 5+ cycles each blowing past the per-cycle cap).
            # All three checked BEFORE the provider call so a tripping
            # cycle exits cleanly without one final expensive request.
            try:
                check_cycle_cost_cap(self._db, cycle)
                check_rolling_hour_cost_cap(self._db)
                check_task_budget(self._db, task_signature=task_sig)
            except CycleCostCapExceeded as exc:
                logger.warning(
                    "act: cycle %d cost cap tripped at $%.2f (cap $%.2f); "
                    "exiting round loop without tier promotion",
                    exc.cycle, exc.spend_usd, exc.cap_usd,
                )
                return ActResult(
                    task_text=task_text,
                    completed=False,
                    rounds=round_idx,
                    finish_reason="cost_cap",
                    failure_reason=str(exc),
                    api_call_count=api_call_count,
                )
            except RollingHourCostCapExceeded as exc:
                logger.warning(
                    "act: rolling-60m cost cap tripped at $%.2f (cap $%.2f); "
                    "exiting round loop without tier promotion",
                    exc.spend_usd, exc.cap_usd,
                )
                return ActResult(
                    task_text=task_text,
                    completed=False,
                    rounds=round_idx,
                    finish_reason="rolling_hour_cap",
                    failure_reason=str(exc),
                    api_call_count=api_call_count,
                )
            except TaskBudgetExceeded as exc:
                logger.warning(
                    "act: task budget exhausted at $%.2f (budget $%.2f); "
                    "abandoning this task — escalation memory will not "
                    "re-promote",
                    exc.spend_usd, exc.budget_usd,
                )
                return ActResult(
                    task_text=task_text,
                    completed=False,
                    rounds=round_idx,
                    finish_reason="task_budget",
                    failure_reason=str(exc),
                    api_call_count=api_call_count,
                )
            round_boundary_ms: int | None = None
            if prior_tools_done_at is not None:
                round_boundary_ms = int(
                    (_time.perf_counter() - prior_tools_done_at) * 1000.0
                )
            try:
                response = await provider.complete_with_tools(
                    messages=messages,
                    model_id=self._model_id_for(rung),
                    tools=tools_schema,
                    max_tokens=self._max_tokens,
                )
            except Exception as exc:
                last_provider_error = str(exc)
                record_api_call(
                    self._db,
                    cycle=cycle,
                    provider=provider.name,
                    model_id=self._model_id_for(rung),
                    error=str(exc),
                    task_signature=task_sig,
                    caller="act",
                )
                record_ladder_outcome(
                    self._db,
                    cycle=cycle,
                    tier=self._tier,
                    rung_model_id=rung.label,
                    outcome="retry_exhausted",
                )
                rung_idx += 1
                if rung_idx >= len(rung_list):
                    return ActResult(
                        task_text=task_text,
                        completed=False,
                        rounds=round_idx,
                        finish_reason="provider_error",
                        failure_reason=last_provider_error,
                        api_call_count=api_call_count,
                    )
                rung = rung_list[rung_idx]
                provider = self._provider_for(rung)
                assert provider is not None
                continue

            api_call_count += 1
            # v4.57 (ADR 0076): compute and persist cost_usd at write
            # time. The dashboard widget computed cost client-side from
            # tokens × tier prices; that still works, but the DB column
            # being empty meant cycle-cost queries (and chimera doctor)
            # couldn't see real spend. Now both paths agree.
            from .budget import _price_table as _bp_price_table
            _prices = _bp_price_table()
            _in_price, _out_price = _prices.get(response.model_id, (0.0, 0.0))
            _in_tok = response.input_tokens or 0
            _out_tok = response.output_tokens or 0
            cost_usd = (
                (_in_tok / 1_000_000.0) * _in_price
                + (_out_tok / 1_000_000.0) * _out_price
            )
            record_api_call(
                self._db,
                cycle=cycle,
                provider=provider.name,
                model_id=response.model_id,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=cost_usd if cost_usd > 0 else None,
                latency_ms=response.latency_ms,
                finish_reason=response.stop_reason,
                # v4.33: parallel-tool fan-out telemetry.
                tool_uses_count=len(response.tool_uses or []),
                # v4.50: time between prior tool completion and this call.
                round_boundary_latency_ms=round_boundary_ms,
                # v4.60: in-flight task signature for per-task budget.
                task_signature=task_sig,
                # v4.69: caller scope. The CuriosityEngine wraps an
                # ActExecutor — those nested calls still get "act"
                # here; the engine_runs row tracks the count.
                caller="act",
            )
            record_ladder_outcome(
                self._db,
                cycle=cycle,
                tier=self._tier,
                rung_model_id=rung.label,
                outcome="success",
            )

            final_text = response.text

            # No tools → done. v4.3: verify any path-shaped artifacts the
            # task asked for actually exist before flipping completed=True.
            if not response.tool_uses or response.stop_reason in ("stop", "length"):
                completed = response.stop_reason == "stop"
                finish_reason = response.stop_reason
                missing: list[str] = []
                ungrounded: list[str] = []
                if completed:
                    expected = expected_artifacts(task_text)
                    missing = check_artifacts(expected)
                    if missing:
                        completed = False
                        finish_reason = "artifact_missing"
                # v4.96 (ADR 0101): content-marker check. The file
                # exists (otherwise artifact_missing fired) but the
                # task spelled out a required sentinel that the
                # agent's write omitted. Soak v8 surfaced this when
                # an investigation doc was written without the
                # `## READY-FOR-REMEDIATION` heading the task
                # demanded.
                incomplete: list[tuple[str, str]] = []
                if completed:
                    markers_by_path = expected_content_markers(task_text)
                    incomplete = check_content_markers(markers_by_path)
                    if incomplete:
                        completed = False
                        finish_reason = "artifact_incomplete"
                # v4.83 (ADR 0095): grounding check. Only runs when the
                # artifact check passed — fabricated content in a file
                # that doesn't exist is already caught upstream.
                if completed:
                    cited_files = extract_cited_source_files(task_text)
                    if cited_files:
                        cited_symbols = extract_cited_symbols(
                            response.text or ""
                        )
                        ungrounded = check_citation_grounding(
                            cited_files, cited_symbols,
                        )
                        if ungrounded:
                            completed = False
                            finish_reason = "ungrounded_citation"
                # v4.82 (ADR 0096): scope-evasion check. INBOX task named
                # a path under chimera/|tests/|scripts/ but the agent
                # produced no tool call referencing that path. Soak v4
                # surfaced agents reading the named source file then
                # writing a spec under mind/research/ instead of patching
                # it. Only fires on the clean-stop completion path; the
                # other failure modes already block the false-positive.
                unedited: list[str] = []
                if completed:
                    # v4.105 (ADR 0109): group OR-disjunctions so
                    # "edit `X` OR `Y`" is satisfied by touching either.
                    intended_groups = intended_code_path_groups(task_text)
                    # v46 fix: pass the worktree so an intended file already
                    # ON DISK (written phase 1, being committed in phase 2)
                    # is not flagged — removes the commit-phase false positive
                    # that stalled v46. SOAK-SCOPED via _import_shadow_scan_root
                    # (the #169 precedent): off-soak the on-disk guard is a
                    # no-op (base_dir=None), so a real `chimera run` and the
                    # repo-worktree unit tests keep the legacy blob-only gate
                    # and a dirty worktree can't mask a genuine evasion.
                    unedited = check_scope_evasion(
                        intended_groups, history, write_targets,
                        base_dir=_import_shadow_scan_root(),
                    )
                    if unedited:
                        completed = False
                        finish_reason = "scope_evasion"
                # v4.101 (ADR 0105): syntax-validity gate. The agent
                # may have written a *.py file that fails to compile —
                # soak v10 shipped exactly this (`return ActResult(...)`
                # interrupted by a dedented statement). Run BEFORE
                # fix_without_test: if syntax is broken, fixing that is
                # the actionable next step regardless of whether tests
                # exist. Identical-traceback spin is the prior failure
                # mode this prevents.
                syntax_failures: list[tuple[str, str]] = []
                if completed:
                    syntax_failures = check_syntax_valid(write_targets)
                    if syntax_failures:
                        completed = False
                        finish_reason = "syntax_invalid"
                # B2 (v40′): function-local import shadowing a module-level
                # name — the os/Path UnboundLocalError class that bricked
                # v40 #2/#4. AST parse-time gate; runs only when syntax is
                # valid (an unparseable file is syntax_invalid's to own).
                # v43 R2 coverage follow-up: pass the worktree so this gate
                # also falls back to `git status` when write_targets is
                # empty (same dormancy the postmortem gate hit on v43).
                # v44 fix (#169): that fallback is SOAK-SCOPED via
                # _import_shadow_scan_root() — off-soak it would fire on a
                # developer's uncommitted .py and (since unit tests run in
                # the repo worktree) let a dirty worktree pollute unrelated
                # ACT tests. The write_targets path still works every run.
                import_shadow_failures: list[tuple[str, str]] = []
                if completed:
                    import_shadow_failures = check_import_shadowing(
                        write_targets, worktree_root=_import_shadow_scan_root(),
                    )
                    if import_shadow_failures:
                        completed = False
                        finish_reason = "import_shadowing"
                # Sub-chip 2 (v40′): a written postmortem whose READY-block
                # tests_passing contradicts the test-run ledger. Catches the
                # sub-agent-draft-dishonesty class at WRITE time (before
                # acceptance), not via a later manual cross-check. No-op
                # outside a soak.
                # v43 fix: pass the worktree so the gate falls back to
                # `git status` when write_targets is empty. The v43 soak
                # ran this gate dormant on all 20 cycles because the agent
                # wrote postmortems via shell (uncaptured); the fallback
                # finds the on-disk postmortem regardless of write tool.
                postmortem_honesty_failures: list[tuple[str, str]] = []
                if completed:
                    postmortem_honesty_failures = check_postmortem_honesty(
                        write_targets, worktree_root=Path.cwd(),
                    )
                    if postmortem_honesty_failures:
                        completed = False
                        finish_reason = "postmortem_dishonest"
                # v4.113 (ADR 0113): runtime test-claim validity. Soak
                # v16 shipped a NameError-at-runtime regression with
                # the agent claiming pytest had passed — py_compile
                # caught nothing because the import was missing, not
                # malformed. Runs AFTER syntax_invalid (the cheap
                # parse-time gate) and BEFORE witness_rejected (the
                # expensive semantic gate). Operator-side subprocess
                # re-run is the ground-truth check — the agent's own
                # shell-tool exit code can be (and was) misreported.
                test_claim_failures: list[str] = []
                if completed:
                    test_claim_failures = check_test_claim_valid(
                        task_text, write_targets, Path.cwd(),
                    )
                    if test_claim_failures:
                        completed = False
                        finish_reason = "test_claim_invalid"
                # B1 W1 (ADR 0158): phase-1 build-completion gate. A real-task
                # soak's "make the change and prove `chimera verify` is green"
                # task was marked complete with no-op tool calls (gate never
                # run, file never edited). Ground-truth the claim by re-running
                # the runner-configured verify command; a red gate means the
                # build isn't done — keep the task open so the agent must
                # actually make it green instead of idling to no-progress.
                # Soak/env-scoped: no-op unless CHIMERA_PHASE1_VERIFY_CMD is set.
                verify_claim_failures: list[str] = []
                if completed:
                    verify_claim_failures = check_verify_claim_invalid(
                        task_text, _import_shadow_scan_root(),
                    )
                    if verify_claim_failures:
                        completed = False
                        finish_reason = "verify_claim_invalid"
                # v46 R2 (ADR 0147): commit-not-executed gate. The task
                # demanded an [agent] commit but none landed — the v46
                # re-soak "Problem B" (staged but never committed; the run
                # idled to no convergence). Runs BEFORE the message/diff/
                # provenance commit gates: if no commit exists at all, "go
                # run git commit" is the actionable next step and those
                # message-validators are moot (each bails on a missing
                # [agent] commit anyway). Soak-scoped via
                # _import_shadow_scan_root() — off-soak the root is None so
                # this is a no-op and a normal chimera run is never forced
                # to commit. Deterministic enforcement of the commit
                # contract the phase-2 INBOX previously stated only in prose.
                commit_not_executed: list[str] = []
                if completed:
                    commit_not_executed = check_commit_not_executed(
                        task_text, _import_shadow_scan_root(),
                    )
                    if commit_not_executed:
                        completed = False
                        finish_reason = "commit_not_executed"
                # v4.115 (ADR 0115): commit-message-vs-diff drift.
                # Soak v20-relaunch shipped an [agent] commit whose
                # message claimed the work included a tests file the
                # agent had written but never git-add'd. Run AFTER the
                # runtime test-claim gate and BEFORE the witness panel:
                # commit-text drift is a fast, deterministic check that
                # the rest of the chain can't see (everyone else looks
                # at task_text or the diff, not the commit message).
                commit_drift_claims: list[str] = []
                if completed:
                    commit_drift_claims = check_commit_message_diff_drift(
                        Path.cwd(),
                    )
                    if commit_drift_claims:
                        completed = False
                        finish_reason = "commit_message_diff_drift"
                # v4.116 (ADR 0116): charter file-count enforcement.
                # Structural cousin of v4.115's drift detector. Where
                # v4.115 catches "commit message claims X but diff
                # doesn't carry X" (lying about what happened), this
                # catches "diff carries Y but charter forbade Y"
                # (exceeding the explicit file budget). Runs after
                # the v4.115 path-drift check because both consume the
                # same git diff; ordering doesn't matter since neither
                # mutates state.
                charter_violations: list[str] = []
                if completed:
                    charter_violations = check_charter_file_count(
                        task_text,
                        Path.cwd(),
                    )
                    if charter_violations:
                        completed = False
                        finish_reason = "charter_file_count"
                # v4.118 (ADR 0118): provenance-citation validity.
                # Soak v20-3rd shipped commit e3af158 citing v4.120 /
                # ADR 0120 when neither existed (platform was v4.116).
                # Runs after the v4.115 path-drift check: same source
                # (the commit message body) but a different token class
                # (version + ADR cites instead of paths). Cheap enough
                # to run on every [agent] commit; bails out fast on
                # operator commits or empty-claim messages.
                provenance_failures: list[str] = []
                if completed:
                    provenance_failures = check_provenance_claim_valid(
                        Path.cwd(),
                    )
                    if provenance_failures:
                        completed = False
                        finish_reason = "provenance_claim_invalid"
                # v4.102 (ADR 0106): witness review for foundational
                # code changes. Runs after syntax_invalid (the cheap
                # parse-time gate) and before fix_without_test. The
                # witness READS the diff and asks the semantic
                # questions py_compile can't: structural sanity
                # ("matched parens but dangling clause"), correctness
                # vs task intent, obvious bugs, convention adherence.
                # Soak v9 + v10 both shipped diffs no second model
                # had read.
                # v4.103 (ADR 0107): replace single witness with a
                # cross-provider panel. Default panel: anthropic-sonnet
                # + openrouter:deepseek-v4-pro + openrouter:gpt-5-pro.
                # Voting: unanimous (any dissent → witness_rejected).
                # The agent's own provider can appear at most once.
                # Concerns from rejecting witnesses are tagged with
                # [provider:model] so the remediation hint surfaces
                # which witness raised what.
                witness_concerns: list[str] = []
                if completed and witness_enabled():
                    witness_paths = should_witness(write_targets)
                    if witness_paths:
                        try:
                            diff = capture_diff_for_witness(witness_paths)
                            if diff.strip():
                                rung = self._pick_rung(requires_tools=False)
                                agent_kind = rung.config.provider
                                panel = build_witness_panel(
                                    agent_kind,
                                    available=set(self._providers.keys()),
                                    # v4.111: rotate panel composition
                                    # across cycles so any one model's
                                    # idiosyncratic bias averages out
                                    # over a soak. Deterministic per
                                    # cycle for reproducibility.
                                    seed=cycle,
                                )
                                # v4.110 (ADR 0110): anchor witnesses on
                                # the modified files' leading docstrings
                                # so threshold-crossing edits (e.g. the
                                # v13 read-only-ish RAW_ALLOWLIST
                                # expansion) get flagged regardless of
                                # code-level quality.
                                # v4.112 (ADR 0112): also lift CHARTER
                                # blocks out of the INBOX task text.
                                # v14 surfaced that the operator-issued
                                # charter ("NOT on clear") lived in
                                # task_text, not in the file's HEAD
                                # docstring, so the v4.110 source alone
                                # left the panel un-anchored.
                                file_charter = extract_charter_excerpts(
                                    witness_paths,
                                )
                                task_charter = extract_task_charter(
                                    task_text,
                                )
                                charter = "\n\n".join(
                                    c for c in (task_charter, file_charter)
                                    if c
                                )
                                labelled = await review_with_panel(
                                    task_text, diff, witness_paths,
                                    panel, self._providers.get,
                                    charter_excerpts=charter,
                                )
                                if labelled and not panel_decision(
                                    v for _, v in labelled
                                ):
                                    completed = False
                                    finish_reason = "witness_rejected"
                                    witness_concerns = aggregate_concerns(labelled)
                        except Exception:
                            logger.exception(
                                "witness review crashed; treating as approved"
                            )
                # v4.90 (ADR 0099): fix-without-test detection. Agent
                # shipped a chimera/ source edit but never wrote a
                # regression test. Soak v6 surfaced this exact pattern.
                untested_fix: list[str] = []
                if completed:
                    untested_fix = check_fix_without_test(history, write_targets)
                    if untested_fix:
                        completed = False
                        finish_reason = "fix_without_test"
                # v4.100 (ADR 0104): INBOX-claim honesty. The agent
                # may have flipped a `[ ]` → `[x]` without producing
                # the deliverable that bullet promised. Run AFTER all
                # the per-task detectors so the cleaner-named failure
                # mode wins when both fire. Revert the checkbox flip
                # in the working tree so the next cycle's runner
                # doesn't act on the lie.
                invalid_inbox: list[tuple[str, list[str]]] = []
                if completed:
                    invalid_inbox = check_inbox_claim_validity(
                        prior_inbox_text,
                        _read_inbox_now(),
                        write_targets,
                    )
                    if invalid_inbox:
                        completed = False
                        finish_reason = "inbox_claim_invalid"
                        _revert_inbox_lies_on_disk(invalid_inbox)
                # v4.5 + v4.10: fragmentation is the same shape whether
                # ACT ran out of rounds OR the model said `stop` without
                # producing the artifact. Hook fires on either path.
                if missing:
                    try:
                        from .adaptation import (
                            maybe_propose_synthesis_skill,
                            record_fragmentation,
                        )
                        record_fragmentation(
                            cycle=cycle,
                            task_text=task_text,
                            rounds_used=round_idx + 1,
                            tool_call_count=len(history),
                            missing_artifacts=missing,
                        )
                        maybe_propose_synthesis_skill(
                            self._db, cycle=cycle, task_text=task_text,
                            missing_artifacts=missing,
                        )
                    except Exception:
                        logger.exception(
                            "fragmentation log / auto-proposal failed; continuing"
                        )
                if syntax_failures:
                    pretty = "; ".join(
                        f"`{path}`: {msg}" for path, msg in syntax_failures
                    )
                    failure_reason = (
                        "syntax invalid: agent wrote unparseable Python: "
                        f"{pretty}"
                    )
                elif test_claim_failures:
                    pretty = ", ".join(f"`{p}`" for p in test_claim_failures)
                    failure_reason = (
                        "test claim invalid: pytest re-run failed for "
                        f"file(s) the task said had passed: {pretty}"
                    )
                elif commit_drift_claims:
                    pretty = ", ".join(f"`{p}`" for p in commit_drift_claims)
                    failure_reason = (
                        "commit message diff drift: the commit message "
                        f"named path(s) {pretty} that don't appear in "
                        f"the branch diff (un-staged or un-written)"
                    )
                elif witness_concerns:
                    pretty = "; ".join(witness_concerns[:3])
                    failure_reason = f"witness rejected: {pretty}"
                elif invalid_inbox:
                    pretty = "; ".join(
                        f"{text[:80]!r} → missing {', '.join(m)}"
                        for text, m in invalid_inbox
                    )
                    failure_reason = (
                        "inbox claim invalid: agent flipped checkbox(es) "
                        f"without producing the deliverable: {pretty}"
                    )
                elif untested_fix and not unedited and not missing and not ungrounded and not incomplete:
                    failure_reason = (
                        f"fix without test: chimera/ source paths "
                        f"{', '.join(untested_fix)} were modified but no "
                        f"tests/test_*.py file was touched"
                    )
                elif incomplete and not missing:
                    pretty = ", ".join(
                        f"`{path}` missing `{marker}`"
                        for path, marker in incomplete
                    )
                    failure_reason = f"artifact incomplete: {pretty}"
                elif unedited and not missing and not ungrounded:
                    failure_reason = (
                        f"scope evasion: named paths {', '.join(unedited)} "
                        f"were not edited"
                    )
                elif ungrounded and not missing:
                    failure_reason = (
                        f"ungrounded citations: {', '.join(ungrounded)} "
                        f"(not found in cited source)"
                    )
                elif missing:
                    failure_reason = f"missing artifacts: {', '.join(missing)}"
                else:
                    failure_reason = None
                return ActResult(
                    task_text=task_text,
                    completed=completed,
                    rounds=round_idx + 1,
                    finish_reason=finish_reason,
                    write_targets=write_targets,
                    tool_call_history=history,
                    final_text=final_text,
                    api_call_count=api_call_count,
                    missing_artifacts=missing,
                    ungrounded_citations=ungrounded,
                    unedited_paths=unedited,
                    untested_fix_paths=untested_fix,
                    incomplete_artifacts=incomplete,
                    invalid_inbox_claims=invalid_inbox,
                    syntax_failures=syntax_failures,
                    import_shadow_failures=import_shadow_failures,
                    postmortem_honesty_failures=postmortem_honesty_failures,
                    test_claim_failures=test_claim_failures,
                    commit_message_drift_claims=commit_drift_claims,
                    charter_file_count_violations=charter_violations,
                    provenance_claim_failures=provenance_failures,
                    witness_concerns=witness_concerns,
                    failure_reason=failure_reason,
                )

            # Append assistant turn with the model's tool_use blocks.
            messages.append(Message.assistant(response.text, response.tool_uses))

            # v4.18: dispatch the batch of tool_uses concurrently. The
            # Anthropic API emits multiple tool_use blocks in a single
            # response when the model wants parallel calls; running them
            # serially throws that latency back away. We still append each
            # call to history first (so detect_degenerate_loop sees the
            # full batch before any dispatch fires).
            # Record the index where this batch's ToolCalls start so we
            # can annotate them with per-call exit/duration after dispatch
            # (v40 build-capability ledger instrumentation).
            batch_start_index = len(history)
            batch_args: list[dict[str, Any]] = []
            for tu in response.tool_uses:
                args = normalize_tool_input(tu.input)
                batch_args.append(args)
                history.append(ToolCall(name=tu.name, args=args))

            verdict = detect_degenerate_loop(history)
            if verdict is LoopVerdict.ABORT:
                return ActResult(
                    task_text=task_text,
                    completed=False,
                    rounds=round_idx + 1,
                    finish_reason="degenerate_loop_abort",
                    write_targets=write_targets,
                    tool_call_history=history,
                    final_text=final_text,
                    failure_reason="aborted after repeated identical tool calls",
                    api_call_count=api_call_count,
                )

            ping_verdict = detect_ping_pong(history)
            if ping_verdict is LoopVerdict.ABORT:
                return ActResult(
                    task_text=task_text,
                    completed=False,
                    rounds=round_idx + 1,
                    finish_reason="ping_pong_abort",
                    write_targets=write_targets,
                    tool_call_history=history,
                    final_text=final_text,
                    failure_reason="aborted after repeated alternating tool-call cycle",
                    api_call_count=api_call_count,
                )

            async def _run_one(
                tu_id: str, name: str, args: dict[str, Any]
            ) -> tuple[ToolResultBlock, float]:
                # Time each dispatch so the soak ledger can record per-call
                # duration. perf_counter is monotonic; ms is wall-clock the
                # tool spent, dominated by I/O or subprocess time.
                _t0 = _time.perf_counter()
                try:
                    output = await self._dispatcher.dispatch(name, args, ctx)
                    block = ToolResultBlock(tool_use_id=tu_id, content=output, is_error=False)
                except ToolDenied as exc:
                    block = ToolResultBlock(
                        tool_use_id=tu_id, content=f"tool denied: {exc}", is_error=True
                    )
                except (ValueError, TypeError, KeyError) as exc:
                    # v4.41: input-validation failure. Teach the model the
                    # correct shape so it can self-correct in the next
                    # round, instead of seeing only the raw exception.
                    hint = _schema_hint(self._dispatcher.registry, name, args)
                    block = ToolResultBlock(
                        tool_use_id=tu_id,
                        content=f"error: {exc}\n{hint}".rstrip(),
                        is_error=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("tool dispatch failed: %s", name)
                    block = ToolResultBlock(
                        tool_use_id=tu_id, content=f"error: {exc}", is_error=True
                    )
                duration_ms = (_time.perf_counter() - _t0) * 1000.0
                return block, duration_ms

            if len(response.tool_uses) > 1:
                logger.info(
                    "act: dispatching %d tool_uses in parallel: %s",
                    len(response.tool_uses),
                    [tu.name for tu in response.tool_uses],
                )

            # ADR 0171: subcriticality fan-out budget. Parallel tool fan-out is
            # otherwise unbounded (asyncio.gather over whatever the model
            # emits). When enabled, dispatch the first N (the model's order is
            # its priority) and defer the rest with a synthetic result that
            # tells the model to re-issue them in a later round — this keeps
            # the provider contract (every tool_use gets a tool_result) while
            # capping the branching width. Off by default → all calls
            # dispatched, byte-identical.
            from .branching import fanout_budget_enabled, fanout_max_width, fanout_split

            _pairs = list(zip(response.tool_uses, batch_args))
            if fanout_budget_enabled():
                _n_dispatch, _n_skip = fanout_split(len(_pairs), fanout_max_width())
            else:
                _n_dispatch, _n_skip = len(_pairs), 0
            if _n_skip > 0:
                logger.info(
                    "act: fan-out budget — dispatching %d of %d tool_uses, "
                    "deferring %d",
                    _n_dispatch, len(_pairs), _n_skip,
                )
            _dispatched = list(
                await asyncio.gather(
                    *[_run_one(tu.id, tu.name, args) for tu, args in _pairs[:_n_dispatch]]
                )
            )
            _skipped: list[tuple[ToolResultBlock, float]] = [
                (
                    ToolResultBlock(
                        tool_use_id=tu.id,
                        content=(
                            "deferred: parallel tool-call fan-out exceeded the "
                            f"width budget ({fanout_max_width()}). Re-issue this "
                            "call in a subsequent round."
                        ),
                        is_error=True,
                    ),
                    0.0,
                )
                for tu, _args in _pairs[_n_dispatch:]
            ]
            gathered: list[tuple[ToolResultBlock, float]] = _dispatched + _skipped
            tool_results: list[ToolResultBlock] = [g[0] for g in gathered]
            # Annotate this batch's ToolCalls (appended at batch_start_index
            # above, in tool_uses order) with per-call exit + duration for
            # the soak ledger. asyncio.gather preserves input order, so the
            # i-th gathered result maps to history[batch_start_index + i].
            for offset, (block, duration_ms) in enumerate(gathered):
                idx = batch_start_index + offset
                if idx < len(history):
                    history[idx].is_error = block.is_error
                    history[idx].duration_ms = round(duration_ms, 3)
            # v4.50: capture wall-clock at the last tool's completion so
            # the NEXT round can record the round-boundary latency.
            prior_tools_done_at = _time.perf_counter()

            # v4.92: track write_targets the agent ACTUALLY produced via
            # writing tools (code_exec etc.). Reads via shell/web_fetch are
            # excluded. See extract_write_targets_from_calls() for the soak
            # v7 root-cause analysis.
            recent_calls = history[-len(response.tool_uses):]
            write_targets[:] = extract_write_targets_from_calls(
                recent_calls, existing=write_targets,
            )

            messages.append(Message.tool_results(tool_results))

        # v4.5: max_rounds + declared artifacts missing = fragmentation.
        # Log it; if the signature recurred enough, auto-propose a
        # focused synthesis skill via the mutation queue.
        missing_at_max = check_artifacts(expected_artifacts(task_text))
        if missing_at_max:
            try:
                from .adaptation import (
                    maybe_propose_synthesis_skill,
                    record_fragmentation,
                )

                record_fragmentation(
                    cycle=cycle,
                    task_text=task_text,
                    rounds_used=effective_max_rounds,
                    tool_call_count=len(history),
                    missing_artifacts=missing_at_max,
                )
                maybe_propose_synthesis_skill(
                    self._db,
                    cycle=cycle,
                    task_text=task_text,
                    missing_artifacts=missing_at_max,
                )
            except Exception:
                logger.exception(
                    "fragmentation log / auto-proposal failed; continuing"
                )

        # v4.85 (ADR 0096 amendment): scope_evasion on the max_rounds
        # exit path. If the INBOX named source files and write_targets
        # contains none of them, the agent burned its budget without
        # editing the named scope — exactly the soak v5 "Implement the
        # fix per the sketch" failure. Surface the diagnosable signal
        # so escalation memory and the v4.84 remediation hint can use it.
        # v4.105 (ADR 0109): group OR-disjunctions. Soak v12 fired
        # false-positive scope_evasion at max_rounds on tasks like
        # "Most likely files: `X` OR `Y`" because the strict check
        # required BOTH paths in write_targets; the agent had
        # correctly written one.
        intended_at_max = intended_code_path_groups(task_text)
        unedited_at_max = check_scope_evasion_strict(
            intended_at_max, write_targets, base_dir=_import_shadow_scan_root(),
        )
        finish_reason_at_max = "max_rounds"
        failure_reason_at_max = "exhausted max rounds without final stop"
        if unedited_at_max and not missing_at_max:
            finish_reason_at_max = "scope_evasion"
            failure_reason_at_max = (
                f"scope evasion: named paths {', '.join(unedited_at_max)} "
                f"were not edited"
            )
        return ActResult(
            task_text=task_text,
            completed=False,
            rounds=effective_max_rounds,
            finish_reason=finish_reason_at_max,
            write_targets=write_targets,
            tool_call_history=history,
            final_text=final_text,
            missing_artifacts=missing_at_max,
            unedited_paths=unedited_at_max if finish_reason_at_max == "scope_evasion" else [],
            failure_reason=failure_reason_at_max,
            api_call_count=api_call_count,
        )
