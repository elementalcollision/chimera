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
import re
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..memory import record_api_call, record_ladder_outcome
from ..prompts import build_system_prompt
from .witness import (
    capture_diff_for_witness,
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
    extract_target_paths,
    normalize_tool_input,
)

logger = logging.getLogger(__name__)


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
    # v4.113 (ADR 0113): test_claim_invalid — pytest claims the task
    # made (`uv run pytest tests/X.py`) that re-running from the
    # operator side actually fails. Soak v16 surfaced agents shipping
    # NameError-at-runtime regressions with confident "tests pass"
    # claims. Populated only when finish_reason == "test_claim_invalid".
    test_claim_failures: list[str] = field(default_factory=list)
    # v4.102 (ADR 0106): witness review concerns. Populated only when
    # finish_reason == "witness_rejected". Each entry is a one-sentence
    # concern naming the file and the structural / correctness defect
    # the witness model flagged. Capped at 5 by parse_verdict().
    witness_concerns: list[str] = field(default_factory=list)


_ARTIFACT_PATTERN = re.compile(r"`((?:state|mind|docs)/[A-Za-z0-9_./-]+)`")

# v4.79 (ADR 0093): natural-language "write X to <path>" phrasing. Soak
# tests showed tasks like "Write all of the above to mind/research/x.md"
# slip past validation when the model emitted stop_reason="stop" without
# producing the file. We catch un-backticked paths too, but restrict to
# the same trusted roots as the backtick pattern to limit false
# positives. Verbs are anchored at a word boundary so we don't catch
# "overwrite" or "rewriter".
_NL_ARTIFACT_PATTERN = re.compile(
    r"\b(?:write|writes|save|saves|put|puts|store|stores|create|creates|"
    r"emit|emits|output|outputs|append|appends|persist|persists)\b"
    r"[^.\n`]{0,120}?"
    r"\b(?:to|at|into|in)\s+`?((?:state|mind|docs)/[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,6})`?",
    re.IGNORECASE,
)


# v4.82 (ADR 0096): code-root paths the INBOX explicitly names. These
# are SOURCE files the task is asking the agent to modify — distinct
# from expected_artifacts() (which catches synthesis outputs under
# state/mind/docs). Soak v4 surfaced agents reading the path, then
# writing a spec under mind/research/ instead of touching the file.
# Disjoint from the artifact roots to keep the two checks independent.
#
# v4.85 (ADR 0096 amendment): the union of two passes. The first is the
# legacy "path-shaped string anywhere in the text" regex — it already
# catches most layouts, including the multi-line "Most likely files:
# `X` OR `Y`" wrap that soak v5 surfaced. The second is an explicit
# backtick-only harvest that documents the intent of the disjunctive-
# list shape and gives us a guard against future regex regressions.
_INTENDED_CODE_PATH_PATTERN = re.compile(
    r"`?((?:chimera|tests|scripts)/[A-Za-z0-9_./-]+"
    r"\.(?:py|md|ts|sh|toml|yaml|yml|json))`?"
)
_BACKTICK_CODE_PATH_PATTERN = re.compile(
    r"`((?:chimera|tests|scripts)/[A-Za-z0-9_./-]+"
    r"\.(?:py|md|ts|sh|toml|yaml|yml|json))`"
)


def intended_code_paths(task_text: str) -> list[str]:
    """Return code-root paths the task names. Stable-ordered, deduped.

    Union of the loose path-shape pattern and the strict backtick-only
    pattern. The strict pass exists so the multi-line, parenthetical,
    and OR-list layouts seen in soak v5 fixture 1.b are exercised by
    their own dedicated regex — independent of the loose pass.
    """
    seen: list[str] = []
    for pattern in (_INTENDED_CODE_PATH_PATTERN, _BACKTICK_CODE_PATH_PATTERN):
        for m in pattern.finditer(task_text):
            p = m.group(1)
            if p not in seen:
                seen.append(p)
    return seen


# v4.105 (ADR 0109): OR-disjunction detection. Soak v12 surfaced
# scope_evasion firing on a task that read "Most likely files: `X` OR
# `Y`" — the agent correctly satisfied the disjunction by editing one
# branch, but the strict check at max_rounds required BOTH paths in
# write_targets and demoted max_rounds→scope_evasion. The fix groups
# paths joined by "or"/"OR" between path tokens into a single
# frozenset; the scope checks then require AT LEAST ONE path per group
# to be touched, not every path.
_OR_BETWEEN_PATHS_RE = re.compile(r"\bor\b", re.IGNORECASE)
# A sentence break between two paths means they're separate
# requirements ("Edit `X`. Then update `Y`."). Recognize ``.``/``!``/
# ``?`` followed by whitespace + capital, or a blank line.
_SENTENCE_BREAK_RE = re.compile(r"[.!?]\s+(?=[A-Z`])|\n\s*\n")


def intended_code_path_groups(task_text: str) -> list[frozenset[str]]:
    """Return intended paths grouped by OR-disjunction.

    Each returned ``frozenset`` is a group of alternatives — the task
    is satisfied if ANY one path in the group is touched. Paths NOT
    joined by an "or" connective form singleton groups (still
    required).

    Detection: for each adjacent pair of path matches in the text,
    look at the gap between them. If the gap contains a bare ``or`` /
    ``OR`` token and no sentence break, the paths are alternatives.
    Transitive closure handles ``X or Y or Z``.
    """
    matches: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for pattern in (_INTENDED_CODE_PATH_PATTERN, _BACKTICK_CODE_PATH_PATTERN):
        for m in pattern.finditer(task_text):
            p = m.group(1)
            if p in seen:
                continue
            seen.add(p)
            matches.append((m.start(), m.end(), p))
    if not matches:
        return []
    matches.sort(key=lambda t: t[0])
    paths_in_order = [p for _, _, p in matches]
    parent = list(range(len(paths_in_order)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for idx in range(len(matches) - 1):
        _, a_end, _ = matches[idx]
        b_start, _, _ = matches[idx + 1]
        between = task_text[a_end:b_start]
        if _SENTENCE_BREAK_RE.search(between):
            continue
        if _OR_BETWEEN_PATHS_RE.search(between):
            union(idx, idx + 1)

    groups: dict[int, list[str]] = {}
    order: list[int] = []
    for i, p in enumerate(paths_in_order):
        root = find(i)
        if root not in groups:
            groups[root] = []
            order.append(root)
        groups[root].append(p)
    return [frozenset(groups[r]) for r in order]


def _normalize_intended_groups(
    intended: "Sequence[str | frozenset[str]]",
) -> list[frozenset[str]]:
    """Accept either flat ``list[str]`` (each path = singleton group)
    or pre-grouped ``list[frozenset[str]]``. Returns groups form.
    """
    out: list[frozenset[str]] = []
    for item in intended:
        if isinstance(item, frozenset):
            if item:
                out.append(item)
        else:
            out.append(frozenset({item}))
    return out


def check_scope_evasion(
    intended: "Sequence[str | frozenset[str]]",
    tool_call_history: list[ToolCall],
    write_targets: list[str],
) -> list[str]:
    """Return intended paths from unsatisfied disjunction groups.

    Heuristic: a real edit to ``chimera/x.py`` will surface the path in
    either a shell ``command`` arg (``sed -i ... chimera/x.py``), a
    code_exec snippet, or the post-write ``write_targets`` list. If
    NO path in a group appears anywhere, the agent never touched any
    branch of that requirement — that's the scope-evasion signal.

    Accepts a flat ``list[str]`` for backward compat (each path
    becomes its own singleton group). Use
    :func:`intended_code_path_groups` for OR-aware grouping.
    """
    groups = _normalize_intended_groups(intended)
    if not groups:
        return []
    blob_parts: list[str] = list(write_targets)
    for call in tool_call_history:
        for v in call.args.values():
            blob_parts.append(str(v))
    blob = " ".join(blob_parts)
    unedited: list[str] = []
    for group in groups:
        if not any(p in blob for p in group):
            unedited.extend(sorted(group))
    return unedited


# v4.90 (ADR 0099): fix-without-test detection. Soak v6 produced a
# genuine code edit (chimera/tools/loop_guard.py +43 lines) but the
# agent never wrote the regression test in tests/. Completeness — not
# orchestration, plumbing, reasoning, recovery, or tooling — is the
# next frontier. A "fix" is evidence of touching a chimera/ source
# file; the deliverable is incomplete without a corresponding
# tests/test_*.py touch.
# v4.92: only these tools can write to the filesystem. shell is argv-only
# with no shell metacharacters (no `>`, no `|`, no `-i`), so it cannot
# write even when args mention paths. web_fetch/web_search/wiki_search are
# read-only by definition. Adding a new writing tool requires extending
# this set.
_WRITING_TOOL_NAMES: frozenset[str] = frozenset({
    "code_exec",
    "write_file",
    "edit_file",
    "create_file",
})


def extract_write_targets_from_calls(
    calls: list[ToolCall],
    existing: list[str] | None = None,
) -> list[str]:
    """Extract paths the agent ACTUALLY wrote to from a batch of tool calls.

    Only calls whose tool name appears in :data:`_WRITING_TOOL_NAMES`
    contribute. shell, web_fetch, wiki_search, and friends are read-only
    and never write to the filesystem (shell is argv-only with no
    metacharacters; the rest fetch remote data).

    Pure helper — no side effects. Returns a fresh list. If ``existing``
    is provided, its entries are preserved and new paths are de-duped
    against it.

    v4.92 introduction. Soak v7 surfaced: when `shell argv=["cat",
    "chimera/X.py"]` (a READ) was treated as a write_target by the prior
    inline loop in ACT, the fix_without_test detector falsely fired on
    every investigation task. Filtering by tool name fixes the
    write_targets-is-misnamed root cause.
    """
    out: list[str] = list(existing) if existing is not None else []
    for call in calls:
        if call.name not in _WRITING_TOOL_NAMES:
            continue
        blob = " ".join(map(str, call.args.values()))
        for path in extract_target_paths(blob):
            if path not in out:
                out.append(path)
    return out


_CHIMERA_SOURCE_PATH_PATTERN = re.compile(
    r"(chimera/[A-Za-z0-9_./-]+\.py)"
)
_TEST_PATH_PATTERN = re.compile(
    r"(tests/(?:[A-Za-z0-9_./-]+/)?test_[A-Za-z0-9_.-]+\.py)"
)
# Files that don't carry implementation logic — touching them alone
# is not a "fix" and should not trigger the detector.
_FIX_WITHOUT_TEST_EXCLUDED_SOURCES = frozenset({
    "chimera/_version.py",
    "chimera/__init__.py",
})


def check_fix_without_test(
    tool_call_history: list[ToolCall],  # noqa: ARG001  (kept for ABI; v4.91 ignores it)
    write_targets: list[str],
) -> list[str]:
    """Return chimera/ source paths the agent WROTE TO if NO tests/ path
    was also written in the same task.

    v4.91 — corrected from v4.90. The original implementation scanned
    tool-call arg values for chimera/X.py paths, which falsely fired on
    READ operations (`cat chimera/core/act.py`, `read_file(...)`, even
    INBOX bullets mentioning a path). Soak v7 surfaced this by escalating
    every phase-1 investigation task as fix_without_test → all three
    auto-skipped via three-strikes → no progress made.

    The corrected detector inspects ONLY ``write_targets`` — paths the
    agent *actually wrote to* during the task. Reading a chimera/ source
    file no longer counts as a fix.

    ``chimera/_version.py`` and ``chimera/__init__.py`` are excluded
    (touching them alone is bookkeeping, not a fix).

    Returns the empty list when:
      - no chimera/ source WAS WRITTEN, OR
      - at least one tests/test_*.py path was also written.

    The ``tool_call_history`` parameter is kept for ABI compatibility
    with v4.90 callers but is no longer read.
    """
    write_blob = " ".join(write_targets)
    src_paths: list[str] = []
    for m in _CHIMERA_SOURCE_PATH_PATTERN.finditer(write_blob):
        p = m.group(1)
        if p in _FIX_WITHOUT_TEST_EXCLUDED_SOURCES:
            continue
        if p not in src_paths:
            src_paths.append(p)
    if not src_paths:
        return []
    if _TEST_PATH_PATTERN.search(write_blob):
        return []
    return src_paths


def check_phase_fix_without_test(changed_files: list[str]) -> list[str]:
    """Phase-scope variant of :func:`check_fix_without_test`.

    Takes the cumulative file list of a branch diff (e.g. the output of
    ``git diff --name-only main..HEAD``) and applies the same rule:
    if any chimera/ source was touched across the phase WITHOUT a
    tests/test_*.py file also being touched, return the offending paths.

    v4.99 (ADR 0103). Soak v9 surfaced a structural blindspot in the
    per-task v4.92 detector: a phase can split fix and test across
    separate tasks, each task individually passing v4.92, and the
    cumulative branch state violating the principle.

    Soak v9 fixture: phase 2 had task A "Implement the fix" (wrote
    `chimera/core/act.py`, no tests/ expected) and task B "Write a
    regression test in tests/test_loop_guard.py" (write_targets empty).
    Per-task v4.92 cleared both. The branch shipped a fix without a
    test. This phase-scope check fires.

    The per-task and phase-scope checks coexist: per-task catches the
    obvious case quickly (fast feedback inside the loop); phase-scope
    catches the split case at the phase boundary.

    Exclusions match :func:`check_fix_without_test` exactly:
    ``chimera/_version.py`` and ``chimera/__init__.py`` are bookkeeping
    and not flagged alone. A "test" is a path under ``tests/`` whose
    basename starts with ``test_`` (helpers don't count).
    """
    src: list[str] = []
    for p in changed_files:
        if not p.startswith("chimera/"):
            continue
        if not p.endswith(".py"):
            continue
        if p in _FIX_WITHOUT_TEST_EXCLUDED_SOURCES:
            continue
        if p not in src:
            src.append(p)
    if not src:
        return []
    has_test = any(
        _TEST_PATH_PATTERN.fullmatch(p) is not None for p in changed_files
    )
    if has_test:
        return []
    return src


def check_syntax_valid(write_targets: list[str]) -> list[tuple[str, str]]:
    """Return ``[(path, error_msg), ...]`` for any *.py path in
    ``write_targets`` that fails python compilation.

    v4.101 (ADR 0105). Soak v10 (mind/postmortems/soak-v10-2026-05-22.md)
    surfaced this gap: the agent wrote a structurally invalid
    `return ActResult(...verdict = detect_degenerate_loop(history)...)`
    block to chimera/core/act.py. The file failed to import at the next
    cycle and the runner spun on identical SyntaxError tracebacks for
    13 minutes before the operator killed it.

    Non-Python paths and nonexistent paths are ignored — we never crash
    on weird input. The check uses ``python3 -m py_compile`` so it
    catches the same SyntaxErrors the import path would.
    """
    failures: list[tuple[str, str]] = []
    for path in write_targets:
        if not path.endswith(".py"):
            continue
        p = Path(path)
        if not p.exists():
            continue
        try:
            result = subprocess.run(
                ["python3", "-m", "py_compile", str(p)],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            continue
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            msg = stderr.split("\n")[-1] if stderr else "py_compile failed"
            failures.append((str(path), msg))
    return failures


# v4.113 (ADR 0113): pytest commands the task explicitly claims to have
# run. Matches `uv run pytest <path>` and `python -m pytest <path>`,
# with optional backticks. The path must look like a tests/ file so we
# don't try to run the full suite. Only the FIRST matching path per
# command is captured; multi-target invocations get the first one (the
# common case in soak v16 was a single-file claim).
_PYTEST_CLAIM_PATTERN = re.compile(
    r"`?(?:uv\s+run\s+pytest|python\s+-m\s+pytest|pytest)\s+"
    r"(tests/[A-Za-z0-9_/.-]+\.py)`?",
)


def _extract_claimed_pytest_files(task_text: str) -> list[str]:
    """Return distinct tests/ paths the task text claims pytest ran on."""
    seen: list[str] = []
    for m in _PYTEST_CLAIM_PATTERN.finditer(task_text or ""):
        p = m.group(1)
        if p not in seen:
            seen.append(p)
    return seen


def check_test_claim_valid(
    task_text: str,
    write_targets: list[str],  # noqa: ARG001  (reserved for future use)
    worktree_root: Path | str,
) -> list[str]:
    """Return tests/ paths whose pytest run actually fails.

    v4.113 (ADR 0113). Soak v16 (PR #5) surfaced this: agent claimed
    ``uv run pytest tests/test_doctor.py`` succeeded, but the file
    raised ``NameError: name 're' is not defined`` at runtime — a
    missing import the agent didn't catch and that py_compile cannot
    catch. The existing structural-correctness detectors (parse,
    presence, paths, charter) all passed.

    Behavior:
      - Extract ``uv run pytest <tests/...>`` / ``python -m pytest <tests/...>``
        claims from ``task_text``.
      - For each claim, if the file exists under ``worktree_root``,
        re-run pytest from operator-side subprocess (NOT the agent's
        shell tool — we need ground truth).
      - Return the list of test files whose pytest exits non-zero.
      - Nonexistent files are skipped silently (artifact_missing
        covers that case).
      - Malformed/absent pytest claims → return [] (don't fire on
        unrelated tasks).
      - Subprocess errors (timeout, OSError, missing pytest binary)
        → return [] with a logged warning. Charter: never raise.
    """
    claimed = _extract_claimed_pytest_files(task_text)
    if not claimed:
        return []
    root = Path(worktree_root)
    failed: list[str] = []
    for rel in claimed:
        target = root / rel
        if not target.exists():
            continue
        try:
            result = subprocess.run(
                ["python3", "-m", "pytest", "-x", "--tb=short",
                 "--no-header", "-q", rel],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            logger.warning("test_claim_invalid: pytest invocation failed for %s", rel)
            continue
        # Exit 5 == "no tests collected": not a real failure (e.g. a
        # placeholder file or a runner-only test module). Exit 1/2/3/4
        # are real failures the agent's claim contradicted.
        if result.returncode not in (0, 5):
            failed.append(rel)
    return failed


def _first_pytest_failure_tail(
    task_text: str,
    worktree_root: Path | str,
    *,
    max_lines: int = 8,
) -> str | None:
    """Best-effort re-run capture of the first failure tail for hints.

    Returns the last ``max_lines`` lines of pytest stderr+stdout for
    the first failing claimed file, or None when nothing fails or the
    subprocess can't run. Used by the remediation hint builder so the
    model sees the actual error rather than a generic prompt.
    """
    claimed = _extract_claimed_pytest_files(task_text)
    if not claimed:
        return None
    root = Path(worktree_root)
    for rel in claimed:
        target = root / rel
        if not target.exists():
            continue
        try:
            result = subprocess.run(
                ["python3", "-m", "pytest", "-x", "--tb=short",
                 "--no-header", "-q", rel],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None
        if result.returncode in (0, 5):
            continue
        combined = (result.stdout or "") + "\n" + (result.stderr or "")
        lines = [ln for ln in combined.splitlines() if ln.strip()]
        return "\n".join(lines[-max_lines:]) if lines else None
    return None


def check_scope_evasion_strict(
    intended: "Sequence[str | frozenset[str]]",
    write_targets: list[str],
) -> list[str]:
    """Stricter variant: a group is "satisfied" only if AT LEAST ONE of
    its paths appears in ``write_targets`` (populated by the post-tool
    write-intent extractor).

    v4.85 (ADR 0096 amendment): soak v5 surfaced a task where the agent
    spent 15+ rounds reading the named files (``cat chimera/...``) but
    never edited them. The loose ``check_scope_evasion`` heuristic sees
    the path string in the read command and treats it as a touch. On
    the max_rounds exit path — where the agent failed to converge —
    we want the stricter signal: did anything *actually get written*
    to one of the named files? If not, demote the generic ``max_rounds``
    finish to ``scope_evasion`` so the escalation memory carries the
    diagnosable signal.

    v4.105 (ADR 0109): accepts disjunction groups. Soak v12 surfaced
    false-positive firings on ``X OR Y`` tasks where the agent
    correctly satisfied the disjunction by writing one branch — the
    strict check then flagged the other branch and demoted
    max_rounds→scope_evasion. Accepting groups (or a flat list, where
    each path is a singleton group) lets callers express "any one of
    these is enough."
    """
    groups = _normalize_intended_groups(intended)
    if not groups:
        return []
    targets = set(write_targets)
    unedited: list[str] = []
    for group in groups:
        if not any(p in targets for p in group):
            unedited.extend(sorted(group))
    return unedited


def expected_artifacts(task_text: str) -> list[str]:
    """Extract paths a task promises to write under state/, mind/, or docs/.

    Matches two patterns:
      1. Backtick-quoted paths (canonical form; ADR 0026).
      2. Un-backticked paths after a write-verb + preposition (ADR 0093).

    Used by ACT to verify the model's claimed completion actually
    produced the files the task asked for. Paths are returned relative;
    callers resolve as needed.
    """
    seen: list[str] = []

    def _add(path: str) -> None:
        if path not in seen:
            seen.append(path)

    for m in _ARTIFACT_PATTERN.finditer(task_text):
        _add(m.group(1))
    for m in _NL_ARTIFACT_PATTERN.finditer(task_text):
        _add(m.group(1))
    return seen


# v4.96 (ADR 0101): content-marker extraction. Soak v8 surfaced a
# failure mode where the agent wrote the named artifact but omitted a
# required content sentinel the task spelled out in formal language
# ("The file MUST end with a section whose heading is EXACTLY:
# `## READY-FOR-REMEDIATION`"). The file existed and was non-empty, so
# check_artifacts() returned []; nothing else verified the sentinel.
#
# Extraction is deliberately conservative: only formal phrasings match,
# because false-positives ("the agent MUST be careful") are worse than
# false-negatives. Patterns recognized:
#
#   1. MUST contain `<marker>`
#   2. MUST include `<marker>`
#   3. MUST end with `<marker>`
#   4. heading is EXACTLY: `<marker>`
#   5. EXACTLY: `<marker>`  (when preceded by MUST or "heading is")
#   6. the file must include `<marker>`
#
# Markers are backtick-quoted strings. We do not attempt to extract bare
# headings without backticks — the explicit quoting is the operator
# convention and the only signal we can extract without NLP heuristics.
_CONTENT_MARKER_PATTERNS: tuple[re.Pattern[str], ...] = (
    # MUST end with `marker`
    re.compile(r"MUST\s+end\s+with[^`\n]{0,80}?`([^`\n]+)`", re.IGNORECASE),
    # MUST contain `marker`
    re.compile(r"MUST\s+contain[^`\n]{0,80}?`([^`\n]+)`", re.IGNORECASE),
    # MUST include `marker` / file must include `marker`
    re.compile(r"MUST\s+include[^`\n]{0,80}?`([^`\n]+)`", re.IGNORECASE),
    # heading is EXACTLY: `marker`  (covers "heading is EXACTLY:\n`...`")
    re.compile(
        r"heading\s+is\s+EXACTLY[^`]{0,40}?`([^`\n]+)`",
        re.IGNORECASE,
    ),
    # MUST <verb> ... EXACTLY: `marker`
    re.compile(
        r"MUST[^.\n]{0,120}?EXACTLY[^`]{0,40}?`([^`\n]+)`",
        re.IGNORECASE,
    ),
)


def expected_content_markers(task_text: str) -> dict[str, list[str]]:
    """Return ``{artifact_path: [marker, ...]}`` extracted from task text.

    v4.96 (ADR 0101). The mapping is keyed by *every* artifact the
    task names (from ``expected_artifacts``); markers found via
    ``_CONTENT_MARKER_PATTERNS`` are attached to all of them. We don't
    attempt to associate a marker with a specific path in multi-artifact
    tasks because the natural-language link ("the file" → which file?)
    is ambiguous; treating the marker as a requirement on every named
    artifact is the conservative call.

    Returns ``{}`` when no markers are found, even if the task names
    artifacts. Empty list values are never produced.
    """
    markers: list[str] = []
    for pat in _CONTENT_MARKER_PATTERNS:
        for m in pat.finditer(task_text or ""):
            value = m.group(1).strip()
            if value and value not in markers:
                markers.append(value)
    if not markers:
        return {}
    paths = expected_artifacts(task_text)
    if not paths:
        return {}
    return {p: list(markers) for p in paths}


def check_content_markers(
    markers_by_path: dict[str, list[str]],
    *,
    base_dir: Path | None = None,
) -> list[tuple[str, str]]:
    """Return ``[(path, missing_marker), ...]`` for any required markers
    that are not present in the file at ``path``.

    v4.96 (ADR 0101). Only inspects files that exist and are non-empty
    (the upstream ``check_artifacts`` already catches absent/empty
    files). A path missing from disk is silently skipped — that's
    ``artifact_missing``'s job, not this detector's.
    """
    base = base_dir or Path.cwd()
    missing: list[tuple[str, str]] = []
    for rel, markers in markers_by_path.items():
        p = base / rel
        try:
            if not p.exists() or not p.is_file() or p.stat().st_size == 0:
                continue
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for marker in markers:
            if marker not in content:
                missing.append((rel, marker))
    return missing


def check_artifacts(
    expected: list[str], *, base_dir: Path | None = None
) -> list[str]:
    """Return the subset of ``expected`` paths that are missing or empty.

    v4.79 (ADR 0093): an existing zero-byte file is treated as missing.
    A model that creates the file but never writes content to it is the
    same failure mode as not creating it at all — and is something the
    soak test surfaced when shell tools were partially denied.
    """
    base = base_dir or Path.cwd()
    missing: list[str] = []
    for rel in expected:
        p = base / rel
        try:
            if not p.exists() or not p.is_file() or p.stat().st_size == 0:
                missing.append(rel)
        except OSError:
            missing.append(rel)
    return missing


# v4.100 (ADR 0104): INBOX-claim honesty check. Soak v9 surfaced a new
# failure CLASS: the agent treated mind/INBOX.md as a write target,
# flipping `[ ]` checkboxes to `[x]` without producing the deliverable
# each bullet promised. None of the prior detectors caught it because
# they check per-task completion against expected_artifacts/content
# markers; the INBOX-edit itself is "in scope" and produces a non-empty
# file. The platform treats INBOX as a *truth statement*: `[x]` means
# the task is done. Lying about that propagates: the next cycle's
# runner sees the checkbox and exits the phase.
#
# This detector compares prior vs. current INBOX state, extracts the
# bullet text for each newly-flipped `[ ]`→`[x]`, and validates that
# the bullet's expected_artifacts (v4.81) actually exist with required
# content markers (v4.96). Bullets that don't name any artifact (e.g.
# "Re-read the verdict") are unfalsifiable — they don't fire.

# Anchored: must be the start of a line (allowing leading whitespace
# for nested bullets), then the bullet marker, then the checkbox.
_INBOX_CHECKBOX_LINE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<bullet>[-*+])\s+\[(?P<state>[ xX])\]\s?(?P<rest>.*)$",
)

# Paths considered "INBOX-shaped" task-list files. mind/INBOX.md is the
# canonical one; the runner also writes to mind/inbox/*.md occasionally.
_INBOX_WRITE_PATTERN = re.compile(
    r"\bmind/(?:INBOX\.md|inbox/[A-Za-z0-9_./-]+\.md)\b"
)


def _is_inbox_write(write_targets: list[str]) -> bool:
    """True iff any write_target points at an INBOX-shaped file."""
    blob = " ".join(write_targets)
    return bool(_INBOX_WRITE_PATTERN.search(blob))


def _parse_inbox_tasks(text: str) -> list[tuple[int, str, str]]:
    """Parse an INBOX markdown body into ``[(line_idx, state, task_text), ...]``.

    ``state`` is ``" "`` (open) or ``"x"`` (done, lowercased). ``task_text``
    is the bullet's first-line text plus any indented continuation lines
    that follow (a paragraph or further bullets nested under it). The
    line index is the 0-based position of the bullet's first line, used
    so the caller can revert a specific checkbox without re-parsing.
    """
    lines = text.splitlines()
    out: list[tuple[int, str, str]] = []
    i = 0
    while i < len(lines):
        m = _INBOX_CHECKBOX_LINE.match(lines[i])
        if not m:
            i += 1
            continue
        state = m.group("state").lower()
        if state == " ":
            state = " "
        else:
            state = "x"
        # Gather continuation lines: subsequent non-empty lines indented
        # deeper than this bullet's indent, that are NOT themselves a
        # top-level checkbox at the same depth.
        bullet_indent = len(m.group("indent"))
        body_parts = [m.group("rest")]
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip():
                # blank line — peek ahead; if next non-blank is still
                # indented continuation, include the blank.
                k = j + 1
                while k < len(lines) and not lines[k].strip():
                    k += 1
                if k >= len(lines):
                    break
                # Stop continuation at the next checkbox bullet, period.
                if _INBOX_CHECKBOX_LINE.match(lines[k]):
                    break
                # Otherwise include this blank + jump to k
                body_parts.append("")
                j = k
                continue
            # If the next line is another checkbox (sibling), stop.
            if _INBOX_CHECKBOX_LINE.match(nxt):
                break
            # Continuation only if indented past the bullet.
            leading = len(nxt) - len(nxt.lstrip())
            if leading <= bullet_indent:
                break
            body_parts.append(nxt.strip())
            j += 1
        task_text = " ".join(p for p in body_parts if p).strip()
        out.append((i, state, task_text))
        i = j
    return out


# v4.100 (ADR 0104): INBOX bullets can claim deliverables under ANY
# writable root — state/, mind/, docs/ AND chimera/, tests/, scripts/.
# expected_artifacts() (v4.81) only catches the synthesis-output roots;
# intended_code_paths() catches the source roots. For INBOX-honesty
# validation we want the union: every concrete file path a bullet
# claims as a deliverable.
def _inbox_bullet_artifacts(task_text: str) -> list[str]:
    """Union of expected_artifacts + intended_code_paths for INBOX
    checkbox validation. Stable-ordered, deduped.
    """
    seen: list[str] = []
    for p in expected_artifacts(task_text):
        if p not in seen:
            seen.append(p)
    for p in intended_code_paths(task_text):
        if p not in seen:
            seen.append(p)
    return seen


def check_inbox_claim_validity(
    prior_inbox: str,
    current_inbox: str,
    write_targets: list[str],
    *,
    base_dir: Path | None = None,
) -> list[tuple[str, list[str]]]:
    """Return ``[(task_text, [missing_artifact, ...]), ...]`` for INBOX
    checkbox flips ``[ ]`` → ``[x]`` in this cycle whose deliverables
    don't actually exist on disk.

    v4.100 (ADR 0104). Pure function: no DB access, no writes.

    The check fires only when:
      - ``write_targets`` includes an INBOX-shaped path (the agent's
        recent calls touched the truth file), AND
      - The same-position bullet flipped ``[ ]`` → ``[x]`` between
        ``prior_inbox`` and ``current_inbox``, AND
      - The bullet text names at least one ``expected_artifact`` (so the
        claim is falsifiable), AND
      - That artifact is missing/empty OR is missing a required
        content marker the bullet itself spelled out.

    Bullets that are already ``[x]`` in ``prior_inbox`` are NOT
    re-validated — only newly-flipped claims trigger the check.
    Unfalsifiable bullets ("Re-read the verdict") never fire.
    """
    if not _is_inbox_write(write_targets):
        return []
    prior_tasks = _parse_inbox_tasks(prior_inbox)
    current_tasks = _parse_inbox_tasks(current_inbox)
    # Pair by line index — the agent that flips a checkbox typically
    # leaves the bullet text intact. If lines were reordered we miss
    # the pairing (a conservative miss; the false-positive cost of
    # cross-matching unrelated bullets is worse than the false-negative
    # cost of skipping a reordered flip).
    prior_by_line = {idx: (state, text) for idx, state, text in prior_tasks}
    invalid: list[tuple[str, list[str]]] = []
    for idx, cur_state, cur_text in current_tasks:
        prior = prior_by_line.get(idx)
        if prior is None:
            continue
        prior_state, prior_text = prior
        if not (prior_state == " " and cur_state == "x"):
            continue
        # Use the *current* task text — the agent may have edited the
        # bullet while flipping it; the claim attaches to what now reads
        # as "done".
        expected = _inbox_bullet_artifacts(cur_text)
        if not expected:
            # Unfalsifiable bullet — no artifact named. Skip.
            continue
        missing: list[str] = []
        # Artifact-missing check.
        missing.extend(check_artifacts(expected, base_dir=base_dir))
        # Content-marker check on artifacts that DO exist.
        markers_by_path = expected_content_markers(cur_text)
        if markers_by_path:
            incomplete = check_content_markers(
                markers_by_path, base_dir=base_dir,
            )
            for path, _marker in incomplete:
                if path not in missing:
                    missing.append(path)
        if missing:
            invalid.append((cur_text, missing))
    return invalid


def revert_inbox_lie(
    current_inbox: str,
    invalid_claims: list[tuple[str, list[str]]],
) -> str:
    """Return a copy of ``current_inbox`` with the invalid `[x]` flips
    reverted to `[ ]`.

    v4.100 (ADR 0104). The lie has to be undone in the working tree,
    not just the escalation log — otherwise the next cycle's runner
    sees the checkbox and exits the phase prematurely.

    Identifies the lines to revert by matching the bullet's task_text
    against ``_parse_inbox_tasks(current_inbox)``. Lines whose parsed
    task_text equals one of the invalid claims' task_texts are
    rewritten with the checkbox flipped back. Other lines are left
    untouched.
    """
    if not invalid_claims:
        return current_inbox
    invalid_texts = {t for t, _ in invalid_claims}
    parsed = _parse_inbox_tasks(current_inbox)
    revert_lines = {
        idx for idx, _state, text in parsed if text in invalid_texts
    }
    if not revert_lines:
        return current_inbox
    lines = current_inbox.splitlines(keepends=True)
    for idx in revert_lines:
        ln = lines[idx]
        # Rewrite the first `[x]` or `[X]` on this line back to `[ ]`.
        # Only the checkbox marker — leave the rest of the line intact.
        lines[idx] = re.sub(r"\[[xX]\]", "[ ]", ln, count=1)
    return "".join(lines)


def _read_inbox_now() -> str:
    """Read mind/INBOX.md from cwd, returning "" if absent/unreadable.

    Helper for the ACT-loop wiring of check_inbox_claim_validity (v4.100).
    """
    try:
        p = Path.cwd() / "mind" / "INBOX.md"
        if p.exists() and p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def _revert_inbox_lies_on_disk(
    invalid_claims: list[tuple[str, list[str]]],
) -> None:
    """Re-read mind/INBOX.md, apply ``revert_inbox_lie`` for each
    invalid claim, and write the result back.

    v4.100 (ADR 0104). Best-effort: any IO error is logged and ignored
    so the ACT exit path stays robust. The escalation log still
    captures the failure regardless of whether the disk revert succeeds.
    """
    if not invalid_claims:
        return
    try:
        p = Path.cwd() / "mind" / "INBOX.md"
        if not (p.exists() and p.is_file()):
            return
        current = p.read_text(encoding="utf-8", errors="replace")
        reverted = revert_inbox_lie(current, invalid_claims)
        if reverted != current:
            p.write_text(reverted, encoding="utf-8")
    except OSError:
        logger.exception(
            "failed to revert INBOX checkbox flip; escalation log "
            "still captures the invalid claim",
        )


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
        tier: str = "haiku",
    ) -> ActExecutor | None:
        """Construct using whichever provider env keys are available.

        Returns ``None`` if neither key is set — caller should skip ACT.

        ``dispatcher`` may be None for helpers that only need provider
        access (e.g. the skills CLI uses this just to get .providers).
        """
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
        tools_schema = self._dispatcher.registry.schemas()
        history: list[ToolCall] = []
        write_targets: list[str] = []
        api_call_count = 0
        final_text = ""
        stop_reason = ""

        # v3.11: walk all eligible rungs cheapest-first. We start on the
        # cheapest; on a provider error we record retry_exhausted and
        # escalate to the next rung. Out of rungs → give up.
        rung_list = [
            r for r in eligible_rungs(self._tier, requires_tools=True)
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
            stop_reason = response.stop_reason

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
                    unedited = check_scope_evasion(
                        intended_groups, history, write_targets,
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
                    test_claim_failures=test_claim_failures,
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

            async def _run_one(tu_id: str, name: str, args: dict[str, Any]) -> ToolResultBlock:
                try:
                    output = await self._dispatcher.dispatch(name, args, ctx)
                    return ToolResultBlock(tool_use_id=tu_id, content=output, is_error=False)
                except ToolDenied as exc:
                    return ToolResultBlock(
                        tool_use_id=tu_id, content=f"tool denied: {exc}", is_error=True
                    )
                except (ValueError, TypeError, KeyError) as exc:
                    # v4.41: input-validation failure. Teach the model the
                    # correct shape so it can self-correct in the next
                    # round, instead of seeing only the raw exception.
                    hint = _schema_hint(self._dispatcher.registry, name, args)
                    return ToolResultBlock(
                        tool_use_id=tu_id,
                        content=f"error: {exc}\n{hint}".rstrip(),
                        is_error=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("tool dispatch failed: %s", name)
                    return ToolResultBlock(
                        tool_use_id=tu_id, content=f"error: {exc}", is_error=True
                    )

            if len(response.tool_uses) > 1:
                logger.info(
                    "act: dispatching %d tool_uses in parallel: %s",
                    len(response.tool_uses),
                    [tu.name for tu in response.tool_uses],
                )

            tool_results: list[ToolResultBlock] = list(
                await asyncio.gather(
                    *[
                        _run_one(tu.id, tu.name, args)
                        for tu, args in zip(response.tool_uses, batch_args)
                    ]
                )
            )
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
        unedited_at_max = check_scope_evasion_strict(intended_at_max, write_targets)
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
