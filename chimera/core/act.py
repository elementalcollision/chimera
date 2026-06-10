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
import subprocess
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
    extract_target_paths,
    normalize_tool_input,
    select_tool_schemas,
)

logger = logging.getLogger(__name__)


def _forced_anthropic_rung(model_id: str) -> LadderRung:
    """A synthetic tool-capable rung pinned to the Anthropic provider + ``model_id``
    (CHIMERA_ACT_FORCE_MODEL). Reuses a known tier's limits/costs when the model
    matches one; otherwise applies conservative defaults. Always Anthropic, since
    the OpenRouter rungs are the unreliable ones this knob exists to bypass."""
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


def _group_already_on_disk(
    group: "frozenset[str] | list[str]", base_dir: Path | str | None,
) -> bool:
    """True iff any path in ``group`` exists on disk as a non-empty file.

    v46 fix: such a path WAS written (this cycle, a prior cycle, or phase 1)
    — the deliverable is present, so the agent committing/finishing is not
    scope-evasion. Disabled (False) when ``base_dir`` is None, preserving
    the legacy blob-only behavior for the pure unit tests.
    """
    if base_dir is None:
        return False
    base = Path(base_dir)
    for p in group:
        try:
            fp = base / p
            if fp.is_file() and fp.stat().st_size > 0:
                return True
        except OSError:
            continue
    return False


def check_scope_evasion(
    intended: "Sequence[str | frozenset[str]]",
    tool_call_history: list[ToolCall],
    write_targets: list[str],
    *,
    base_dir: Path | str | None = None,
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

    v46 fix: a group is also satisfied when one of its paths already
    EXISTS on disk as a non-empty file (``base_dir`` given). The two-phase
    soak's phase-2 INBOX names the target file to COMMIT; the agent then
    runs ``git add``/``git commit`` (not an edit), so the path may not
    surface in this cycle's tool args — but the file IS present (written in
    phase 1). Without this guard scope_evasion false-fires in the commit
    phase, derailing it into a three-strikes stall (v46). The real catch is
    preserved: an intended file that was genuinely never written does not
    exist on disk → still flagged. ``base_dir=None`` keeps the legacy
    blob-only behavior (unit tests, non-soak runs).
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
        if any(p in blob for p in group):
            continue
        if _group_already_on_disk(group, base_dir):
            continue
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
        # v46 (ADR 0149): a path is a write target only when it is the
        # DESTINATION of a write op — NOT merely mentioned in the CONTENT
        # being written. Scraping every path-shaped token out of the call
        # args dragged a *documented* source path into write_targets: the
        # phase-1 postmortem task writes `…postmortem.md` whose PROSE names
        # `chimera/soak_report.py`, that path got scraped in, should_witness()
        # then surfaced the UNRELATED module to the witness panel under the
        # postmortem charter, and the panel rejected it — phase-1
        # no_forward_progress across the v46 re-soaks. When a write idiom is
        # found we trust those destinations; otherwise we conservatively fall
        # back to the legacy whole-blob scrape (keeps write_targets populated
        # for exotic write styles that other gates + the honesty fallback
        # depend on).
        dests = _code_write_destinations(blob)
        candidate = (
            extract_target_paths(" ".join(dests)) if dests
            else extract_target_paths(blob)
        )
        for path in candidate:
            if path not in out:
                out.append(path)
    return out


# Write-DESTINATION idioms in a code_exec snippet (the only registered
# writing tool). A path counts as a write target when it is the argument of
# a write operation — `open('p','w'/'a'/'x'…)`, `Path('p').write_text/bytes(…)`,
# or `Path('p').open('w'…)` — NOT when it merely appears inside the content
# being written. See extract_write_targets_from_calls (ADR 0149).
_WRITE_DEST_RE = re.compile(
    r"""
        open\s*\(\s*['"](?P<a>[^'"\n]+)['"]\s*,\s*['"][^'"\n]*[wax][^'"\n]*['"]
      | Path\s*\(\s*['"](?P<b>[^'"\n]+)['"]\s*\)\s*\.\s*write_(?:text|bytes)
      | Path\s*\(\s*['"](?P<c>[^'"\n]+)['"]\s*\)\s*\.\s*open\s*\(\s*['"][^'"\n]*[wax]
    """,
    re.VERBOSE,
)


def _code_write_destinations(blob: str) -> list[str]:
    """Return the path(s) a code_exec snippet WRITES TO (idiom-based).

    Empty when no recognized write idiom is present — the caller then falls
    back to the legacy whole-blob scrape. Deliberately conservative: better to
    occasionally over-scrape (legacy behavior) than to drag a documented but
    unwritten path into write_targets (the v46 witness false-positive).
    """
    out: list[str] = []
    for m in _WRITE_DEST_RE.finditer(blob):
        p = m.group("a") or m.group("b") or m.group("c")
        if p and p not in out:
            out.append(p)
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


def _charter_test_satisfied() -> bool:
    """H3 (v42): True when an active soak has a recorded PASSING test run.

    Build-soak charters provide the test as READ-ONLY input — the agent is
    forbidden from authoring a ``tests/`` file (the charter scope check, and
    H1, refuse it). So the fix_without_test rule ("wrote chimera/ source but
    no tests/ file in the same change") structurally false-positives on
    every build-soak cycle, even when a charter-owned test exists and PASSES
    (v42 attempts #1 and #2 churned to budget on this). A recorded passing
    gated test-run means the fix IS tested — the requirement is met. Narrow:
    only when ``CHIMERA_SOAK_RUN_ID`` is set AND the ledger shows a pass;
    outside a soak the detector is unchanged. Fail-soft.
    """
    try:
        from .soak_ledger import soak_run_id, summarize_run
        if not soak_run_id():
            return False
        summary = summarize_run()
        return bool(summary and summary.get("tests_passed_any"))
    except Exception:  # noqa: BLE001 - fail-soft
        return False


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
    if _charter_test_satisfied():  # H3: charter-provided test passed
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
    if _charter_test_satisfied():  # H3: charter-provided test passed
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


def _imported_names(node) -> list[str]:
    """Names a single Import / ImportFrom node binds into its scope.

    ``import os`` -> ["os"]; ``import os.path`` -> ["os"] (binds the head);
    ``import numpy as np`` -> ["np"]; ``from p import Path`` -> ["Path"];
    ``from p import a as b`` -> ["b"]; ``from p import *`` -> [] (ignored).
    """
    import ast  # stdlib leaf; bound nowhere else in this module

    names: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            names.append(alias.asname or alias.name.split(".")[0])
    elif isinstance(node, ast.ImportFrom):
        for alias in node.names:
            if alias.name == "*":
                continue
            names.append(alias.asname or alias.name)
    return names


def _import_shadow_scan_root() -> Path | None:
    """Return the worktree root the import-shadow gate should git-scan,
    or ``None`` to disable the fallback.

    v44 fix (#169): the ``git status`` fallback added in #164 scanned
    ``Path.cwd()`` unconditionally. Off-soak that is a bug — a real
    ``chimera run`` in a repo with uncommitted ``.py`` would fire the gate
    on the developer's working files, and (because the unit tests run in
    the repo worktree) a DIRTY worktree containing any shadowed ``.py``
    polluted unrelated ACT tests. The postmortem-honesty fallback is
    implicitly soak-scoped (its ``summarize_run()`` no-ops off-soak); the
    import-shadow fallback had no such guard. We make it explicit here:
    the cwd git-scan is enabled only inside a soak (``CHIMERA_SOAK_RUN_ID``
    set). The ``write_targets`` path — the in-loop signal — is unaffected
    and still works in every run.
    """
    from .soak_ledger import soak_run_id

    return Path.cwd() if soak_run_id() else None


def check_import_shadowing(
    write_targets: list[str],
    worktree_root: Path | str | None = None,
) -> list[tuple[str, str]]:
    """Return ``[(path, msg), ...]`` for any .py write target where a
    function-local import binds a name that is ALSO imported at module
    level — i.e. a shadow that makes the name function-local across the
    whole function and raises ``UnboundLocalError`` on any earlier read.

    B2 (v40′ scope-creep sprint). v40 attempts #2 and #4 both bricked
    ``chimera run`` this way: the agent added ``import os`` / a ``Path``
    import inside ``main()``, shadowing the module-level binding, so the
    branch-drift check at the top of ``main()`` hit an unbound local.
    py_compile does NOT catch it (the file parses fine); it fails only at
    runtime, on a code path the narrow per-feature test doesn't exercise.

    Deliberately narrow to keep false positives near zero: only flags a
    function-local import whose bound name is also a MODULE-LEVEL import.
    The legitimate lazy-import pattern (a function-local import of a name
    NOT imported at module level — e.g. ``from .core import LoopConfig``
    inside one branch) is NOT flagged. Non-Python / nonexistent paths and
    unparseable files are skipped (syntax_invalid owns parse failures).

    Target source (v43 R2 fix, coverage follow-up): ``write_targets``
    UNION the worktree's changed ``.py`` files when ``worktree_root`` is
    given. The v43 soak ran every write-target gate dormant because
    ``write_targets`` was empty all run (the agent wrote via ``shell``,
    not a captured writing tool); the git fallback makes THIS gate, too,
    inspect the ``.py`` files actually on disk regardless of write tool.
    With ``worktree_root=None`` only ``write_targets`` is inspected
    (legacy behavior — keeps unit tests and non-soak runs hermetic).
    """
    import ast

    failures: list[tuple[str, str]] = []
    for path in _gate_targets(write_targets, worktree_root, ".py"):
        p = Path(path)
        if not p.exists():
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError, OSError):
            continue  # syntax_invalid handles parse failures
        # Module-level imported names (top-level Import / ImportFrom only).
        module_names: set[str] = set()
        for stmt in tree.body:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                module_names.update(_imported_names(stmt))
        if not module_names:
            continue
        # Walk each top-level function/method; flag nested imports that
        # rebind a module-level name.
        for top in tree.body:
            if not isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(top):
                if inner is top or not isinstance(inner, (ast.Import, ast.ImportFrom)):
                    continue
                shadowed = sorted(set(_imported_names(inner)) & module_names)
                for name in shadowed:
                    failures.append((
                        str(path),
                        f"function-local import of '{name}' in '{top.name}' "
                        f"shadows the module-level import of '{name}' "
                        f"(UnboundLocalError risk; keep the import module-level)",
                    ))
    return failures


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


def _git_changed_paths(
    worktree_root: Path | str, suffix: str,
) -> list[str]:
    """Worktree-relative paths whose file currently differs from HEAD and
    ends with ``suffix`` — the FALLBACK source for the write-target gates.

    v43 soak (run ``v43-trio-2026-05-30-0052``) surfaced the gap this
    closes: ``write_targets`` was empty on all 20 ACT records, so the
    write-target gates (import-shadow + postmortem honesty) no-op'd the
    whole run. Root cause: ``write_targets`` is only populated from
    :data:`_WRITING_TOOL_NAMES` calls (``code_exec`` and friends), but a
    soak agent that writes via the ``shell`` tool (``python3 -c …``,
    ``git apply``) leaves no trace there — shell is deliberately excluded
    (soak v7). The honesty gate must not depend on *which* tool happened
    to do the write: ``git status`` is ground truth for "what changed in
    this worktree" regardless of the tool path.

    Covers staged, unstaged, AND untracked files (``--porcelain`` shows
    all three), so a just-written, not-yet-committed postmortem is found.
    Rename entries (``R  old -> new``) contribute their destination.
    Charter: never raise — any git/OS error returns ``[]`` (fail-soft, so
    the gate degrades to the ``write_targets``-only behavior it had
    before, never blocks on an unreadable worktree).
    """
    root = Path(worktree_root)
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return []
    if res.returncode != 0:
        return []
    out: list[str] = []
    for line in (res.stdout or "").splitlines():
        # Porcelain v1: two status chars, a space, then the path. Renames
        # render as ``old -> new`` — the destination is what was written.
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip().strip('"')
        if path.endswith(suffix) and path not in out:
            out.append(path)
    return out


def _gate_targets(
    write_targets: list[str], worktree_root: Path | str | None, suffix: str,
) -> list[str]:
    """Paths a write-target gate should inspect: the ``write_targets``
    entries ending in ``suffix`` UNION the worktree's changed files ending
    in ``suffix``, deduped by resolved path.

    ``write_targets`` is the in-loop signal (populated only when the agent
    used a tool in :data:`_WRITING_TOOL_NAMES`); the git fallback catches
    files written via any other path — notably the ``shell`` tool, which is
    deliberately excluded (soak v7) and which a soak agent uses for
    ``python3 -c …`` / ``git apply``. When ``worktree_root`` is ``None`` the
    fallback is off and behavior is exactly the legacy ``write_targets``-only
    form — keeps pure-unit tests (which pass no worktree) hermetic and a
    non-soak ``chimera run`` unaffected. v43 R2 fix (PR #163 for ``.md``;
    generalized here so the import-shadow gate gets the same coverage).
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for path in write_targets:
        if not path.endswith(suffix):
            continue
        key = str(Path(path).resolve())
        if key not in seen:
            seen.add(key)
            ordered.append(path)
    if worktree_root is not None:
        root = Path(worktree_root)
        for rel in _git_changed_paths(root, suffix):
            abs_path = root / rel
            key = str(abs_path.resolve())
            if key not in seen:
                seen.add(key)
                ordered.append(str(abs_path))
    return ordered


def _postmortem_gate_targets(
    write_targets: list[str], worktree_root: Path | str | None,
) -> list[str]:
    """``.md`` gate targets — thin wrapper over :func:`_gate_targets`."""
    return _gate_targets(write_targets, worktree_root, ".md")


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


# v4.113 / PR #6 review-round-2: invocation must distinguish
# "pytest ran and a test failed" (exit 1, real claim violation) from
# "pytest module isn't available in the resolved subprocess env"
# (also exit 1, with the stderr signature ``No module named pytest``).
# The runner prefers ``uv run pytest`` because uv resolves the
# project's dev-extras regardless of which python is on PATH; falls
# back to ``sys.executable -m pytest`` when uv isn't available; and
# returns None ("environmental, skip") when neither invocation can
# find pytest.
_PYTEST_MISSING_STDERR = "No module named pytest"


def _run_pytest_file(
    rel_path: str, cwd: Path, timeout: int = 120,
) -> tuple[int, str] | None:
    """Re-run a single test file from subprocess.

    Returns ``(returncode, combined_output)`` for a real pytest run, or
    ``None`` when the invocation environmentally failed (no pytest
    available, OS errors, timeout). Callers MUST treat None as
    "skip — don't fire."
    """
    import sys
    invocations = (
        ["uv", "run", "pytest"],
        [sys.executable, "-m", "pytest"],
    )
    last_combined = ""
    for argv_head in invocations:
        argv = [
            *argv_head, "-x", "--tb=short", "--no-header", "-q", rel_path,
        ]
        try:
            result = subprocess.run(
                argv, cwd=str(cwd),
                capture_output=True, text=True, timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        combined = (result.stdout or "") + (result.stderr or "")
        if _PYTEST_MISSING_STDERR in combined:
            last_combined = combined
            continue
        return result.returncode, combined
    logger.info(
        "test_claim_invalid: no pytest available via uv run or "
        "sys.executable -m; skipping. stderr=%s",
        last_combined[:200],
    )
    return None


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
        run = _run_pytest_file(rel, root)
        if run is None:
            # Environmental skip — no pytest available in any invocation
            # env. Don't fire; this is exactly the false-positive shape
            # PR #6 review-round-2 surfaced.
            continue
        returncode, _ = run
        # Pytest exit codes:
        #   0 — all tests passed
        #   1 — tests collected, some FAILED  ← only signal "the
        #       agent's claim was a lie"
        #   2 — interrupted / collection error (ImportError, etc.)
        #   3 — internal pytest error
        #   4 — usage error
        #   5 — no tests collected
        # Codes 2–5 are environmental ambiguities (synthetic fixtures
        # without project context, missing deps, placeholder files).
        # Only exit 1 gets reported as test_claim_invalid.
        if returncode == 1:
            failed.append(rel)
        elif returncode not in (0, 5):
            logger.info(
                "test_claim_invalid: pytest exit=%s for %s — treating "
                "as environmental, not a claim violation",
                returncode, rel,
            )
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
        run = _run_pytest_file(rel, root)
        if run is None:
            return None
        returncode, combined = run
        # Only surface tails for true test failures (exit 1). Other
        # non-zero codes are environmental and don't carry a useful
        # diagnostic.
        if returncode != 1:
            continue
        lines = [ln for ln in combined.splitlines() if ln.strip()]
        return "\n".join(lines[-max_lines:]) if lines else None
    return None


# v4.115 (ADR 0115): commit-message-vs-diff drift. Soak v20-relaunch
# surfaced an [agent] commit whose message body claimed the work
# included a tests/test_ruff_claim_invalid.py file. The diff against
# main carried chimera/core/act.py and a research doc, but NOT the
# tests file — the agent wrote the file (it passed locally) but never
# git-add'd it before committing. The structural detectors all cleared
# because the un-staged file existed on disk; the witness panel
# approved the diff without knowing the message lied about it.
#
# Path-shape extractor: looks for backtick-quoted OR bare paths under
# the same trusted roots scope_evasion uses, plus a *.py / *.md / *.sh
# / *.toml / *.json / *.yaml / *.yml suffix. The roots are deliberately
# narrow — un-rooted bare strings like "the test file" or "the README"
# would be too noisy and aren't actionable.
_COMMIT_CLAIM_PATH_PATTERN = re.compile(
    r"`?((?:tests|chimera|mind|docs|state|scripts)/"
    r"[A-Za-z0-9_/.-]+\."
    r"(?:py|md|sh|toml|json|yaml|yml|txt))`?",
)


def _extract_commit_path_claims(message: str) -> list[str]:
    """Return distinct rooted paths the commit message names."""
    seen: list[str] = []
    for m in _COMMIT_CLAIM_PATH_PATTERN.finditer(message or ""):
        p = m.group(1)
        if p not in seen:
            seen.append(p)
    return seen


def check_commit_message_diff_drift(
    worktree_root: Path | str,
    head_ref: str = "HEAD",
    base_ref: str = "main",
) -> list[str]:
    """Return paths the HEAD commit message names that aren't in the diff.

    v4.115 (ADR 0115). Soak v20-relaunch surfaced this: agent committed
    ``chimera/core/act.py`` with a message claiming the work included
    ``tests/test_ruff_claim_invalid.py``. The test file existed on disk
    and passed locally — it was just never ``git add``-ed. All
    structural detectors cleared (file present, parse clean, etc.) but
    the cumulative branch diff did not include it, and the commit's
    text-vs-reality gap is the failure mode this detector closes.

    Behavior:
      - Only fires on ``[agent]`` commits. Operator commits are
        out-of-scope (operator messages aren't an autonomous-delivery
        contract).
      - Extracts rooted path claims (``tests/...``, ``chimera/...``,
        ``mind/...``, ``docs/...``, ``state/...``, ``scripts/...``)
        from the commit message body.
      - Compares against the HEAD commit's OWN diff
        (``git show --name-only --format= <head>``). ADR 0126 corrected
        this from the prior cumulative ``<base>..<head>`` form, which
        false-fired on fresh-fork branches where ``HEAD == base_ref``
        (soak v29 smoking gun).
      - Returns claims missing from the diff. Charter: never raise;
        subprocess errors return ``[]``.
    """
    root = Path(worktree_root)
    try:
        subj = subprocess.run(
            ["git", "log", "-1", "--format=%s", head_ref],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return []
    if subj.returncode != 0:
        return []
    subject = (subj.stdout or "").strip()
    if not subject.startswith("[agent]"):
        return []
    try:
        msg = subprocess.run(
            ["git", "log", "-1", "--format=%B", head_ref],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
        touched = subprocess.run(
            ["git", "show", "--name-only", "--format=", head_ref],
            cwd=str(root), capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return []
    if msg.returncode != 0 or touched.returncode != 0:
        return []
    claimed = _extract_commit_path_claims(msg.stdout or "")
    if not claimed:
        return []
    diff_paths = {
        line.strip() for line in (touched.stdout or "").splitlines()
        if line.strip()
    }
    return [p for p in claimed if p not in diff_paths]


# v46 R2 (ADR 0147): commit-not-executed gate. The v46 re-soak confirmed
# the scope_evasion commit-phase fix (#180) and, with that mask removed,
# isolated the SECOND half of the original v46 finding: the phase-2 commit
# task self-reported completed=True after `git add`, but `git commit` never
# ran — the deliverable sat STAGED-but-uncommitted and the run idled to no
# convergence. Every existing commit gate (message-drift v4.115, provenance
# v4.118, charter-count v4.116) assumes a commit HAPPENED; none enforce that
# the commit ACTION ran. The phase-2 INBOX says "git add only stages…
# verify with git log" in PROSE — and the agent's own cycle-158 curiosity
# research found prose/trust gets ~40% adherence vs ~100% for a deterministic
# gate ("the gap is removing the ability to skip"). This is that gate.
_AGENT_COMMIT_TASK_RE = re.compile(r"\bcommit(s|ted|ting)?\b", re.IGNORECASE)


def _task_demands_agent_commit(task_text: str) -> bool:
    """True if the task instructs the agent to create an ``[agent]`` commit.

    Targets the autonomous-delivery commit contract specifically: the task
    must BOTH reference the ``[agent]`` subject token (the enforced
    commit-message marker, ADR 0122/0146) AND contain a ``commit`` imperative.
    An incidental ``commit`` mention without the ``[agent]`` token (e.g. a
    build task that says "before you commit, run the tests") does not trip it,
    and the ``[agent]`` token alone (with no commit verb) does not either.
    """
    if not task_text or "[agent]" not in task_text:
        return False
    return _AGENT_COMMIT_TASK_RE.search(task_text) is not None


def check_commit_not_executed(
    task_text: str,
    worktree_root: Path | str | None,
    base_ref: str = "main",
    head_ref: str = "HEAD",
) -> list[str]:
    """Return a one-item reason list if the task demanded an ``[agent]``
    commit but none landed; otherwise ``[]``.

    Fires only when ALL hold:
      - ``worktree_root`` is given (soak-scoped via
        :func:`_import_shadow_scan_root` — off-soak a normal ``chimera run``
        is NEVER forced to commit), AND
      - the task demands an ``[agent]`` commit
        (:func:`_task_demands_agent_commit`), AND
      - no ``[agent]``-subject commit exists in ``base_ref..head_ref``.

    This is the inverse of every other commit gate: they validate a commit
    that happened; this catches a commit that was instructed but SKIPPED
    (staged-but-uncommitted — the v46 re-soak "Problem B" signature). The
    convergence criterion mirrors the runner's external soft-sentinel
    (``soak_phase2_deliverable_landed``: ≥1 ``[agent]`` commit in
    ``main..HEAD``), brought INSIDE the loop so the agent gets the feedback
    in-cycle instead of silently idling. Charter: never raise; subprocess /
    seatbelt errors return ``[]`` (fail-open, like its sibling gates).
    """
    if worktree_root is None:
        return []
    if not _task_demands_agent_commit(task_text):
        return []
    root = Path(worktree_root)
    try:
        log = subprocess.run(
            ["git", "log", "--format=%s", f"{base_ref}..{head_ref}"],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return []
    if log.returncode != 0:
        return []
    for line in (log.stdout or "").splitlines():
        if line.strip().startswith("[agent]"):
            return []  # a commit landed — the contract is satisfied
    return [
        f"task instructed an [agent] commit but none exists in "
        f"{base_ref}..{head_ref} — work is staged but not committed; "
        f"run `git commit` and verify with `git log`"
    ]


# B1 W1 (ADR 0158): phase-1 build-completion gate. The first real-task soak
# surfaced an agent marking a "make the change and prove `chimera verify` is
# green" task COMPLETE with sub-10ms no-op tool calls — it never ran the gate
# or edited the file, yet self-reported done. Engines-off phase 1 had no
# honesty gate on the build step, so the over-claim slid; the run idled to
# no_forward_progress with the change never made. This is the build-step
# analogue of check_test_claim_valid / check_commit_not_executed: ground-truth
# the claim by RE-RUNNING the repo's real verification, not trusting the
# agent's self-report.
_VERIFY_GREEN_TASK_RE = re.compile(
    r"chimera\s+verify|verify\b[^.]*\bgreen|exits?\s+0|prints?\s+`?PASS",
    re.IGNORECASE,
)


def _task_demands_verify_green(task_text: str) -> bool:
    """True if the task instructs the agent to make the repo's real
    verification pass (the real-task soak phase-1 build task: "make the change
    and prove ``chimera verify`` is green ... until it prints ``PASS``")."""
    if not task_text:
        return False
    return _VERIFY_GREEN_TASK_RE.search(task_text) is not None


def check_verify_claim_invalid(
    task_text: str,
    worktree_root: Path | str | None,
    verify_cmd: str | None = None,
    timeout: float = 600.0,
) -> list[str]:
    """Return a one-item reason list when a build task claims the repo's real
    verification is green but it is NOT — the W1 over-claim.

    Fires only when ALL hold:
      - ``worktree_root`` is given (soak-scoped via
        :func:`_import_shadow_scan_root`; off-soak this is a no-op), AND
      - a verify command is configured — ``verify_cmd`` or the
        ``CHIMERA_PHASE1_VERIFY_CMD`` env var the real-task runner sets, AND
      - the task demands a green verification
        (:func:`_task_demands_verify_green`), AND
      - that command exits non-zero when re-run from ``worktree_root``.

    The verify command is RUNNER-controlled (an operator-set env var), never
    parsed from agent output — so this re-runs a trusted gate, not arbitrary
    text. Charter: never raise; a subprocess/seatbelt error returns ``[]``
    (fail-open, like its sibling gates) so the witness panel + engine guards
    stay authoritative.
    """
    if worktree_root is None:
        return []
    import os

    cmd = verify_cmd if verify_cmd is not None else os.environ.get(
        "CHIMERA_PHASE1_VERIFY_CMD"
    )
    if not cmd:
        return []
    if not _task_demands_verify_green(task_text):
        return []
    try:
        proc = subprocess.run(
            ["bash", "-c", cmd], cwd=str(Path(worktree_root)),
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return []
    if proc.returncode == 0:
        return []  # genuinely green — the claim holds
    return [
        f"task claimed the repo's real verification is green, but `{cmd}` "
        f"exits {proc.returncode} — the change is not done. Make the edit and "
        f"re-run the gate until it prints PASS before reporting complete"
    ]


# v4.118 (ADR 0118): provenance citations in [agent] commit messages.
# Soak v20-3rd surfaced an agent shipping commit e3af158 with message
# "[agent] Add ruff_claim_invalid detector (v4.120 / ADR 0120)" when
# the actual platform was v4.116 and ADR 0120 didn't exist. The
# v4.115 path-drift detector doesn't see non-path tokens; the
# charter-anchoring witness doesn't read the commit message body.
# Cite-then-fabricate is its own class of lie, distinct from the
# path/diff drift v4.115 closes.
_PROVENANCE_VERSION_PATTERN = re.compile(r"\bv(\d+\.\d+)(?:\.\d+)?\b")
_PROVENANCE_ADR_PATTERN = re.compile(r"\bADR[\s-]*0*(\d{1,4})\b")


def _extract_provenance_claims(message: str) -> tuple[list[str], list[str]]:
    """Return ``(versions, adrs)`` cited in a commit message.

    Versions are normalized to ``X.Y`` (the patch component is dropped
    for matching since ADR/source citations use the minor-level form).
    ADR numbers are normalized to zero-padded 4-digit strings.
    """
    versions: list[str] = []
    adrs: list[str] = []
    for m in _PROVENANCE_VERSION_PATTERN.finditer(message or ""):
        v = m.group(1)
        if v not in versions:
            versions.append(v)
    for m in _PROVENANCE_ADR_PATTERN.finditer(message or ""):
        n = m.group(1).zfill(4)
        if n not in adrs:
            adrs.append(n)
    return versions, adrs


def _version_resolves(root: Path, ver: str) -> bool:
    """True if ``vX.Y`` is named by a git tag or any source/doc file."""
    try:
        tags = subprocess.run(
            ["git", "tag", "--list", f"v{ver}", f"v{ver}.*"],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        tags = None
    if tags is not None and tags.returncode == 0 and (tags.stdout or "").strip():
        return True
    # Fall back to repo content: pyproject.toml version, chimera/__init__.py,
    # and ADR files routinely cite the minor-version form as "v4.115".
    for relpath in ("pyproject.toml", "chimera/__init__.py"):
        p = root / relpath
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            continue
        if f'version = "{ver}' in content or f'__version__ = "{ver}' in content:
            return True
    adr_dir = root / "docs" / "adr"
    if adr_dir.is_dir():
        token = f"v{ver}"
        for adr in adr_dir.glob("*.md"):
            try:
                if token in adr.read_text(encoding="utf-8", errors="replace"):
                    return True
            except (OSError, UnicodeDecodeError):
                continue
    return False


def _adr_resolves(root: Path, num: str) -> bool:
    adr_dir = root / "docs" / "adr"
    if not adr_dir.is_dir():
        return False
    return any(adr_dir.glob(f"{num}-*.md"))


def check_provenance_claim_valid(
    worktree_root: Path | str,
    head_ref: str = "HEAD",
) -> list[str]:
    """Return provenance citations in the HEAD commit that don't resolve.

    v4.118 (ADR 0118). Only fires on ``[agent]`` commits. Extracts
    version tokens (``vX.Y``) and ADR numbers (``ADR NNNN``) from the
    commit message body and validates each:

    - A version resolves if a matching ``vX.Y`` / ``vX.Y.*`` tag exists,
      or the literal ``vX.Y`` appears in ``pyproject.toml``,
      ``chimera/__init__.py``, or any ``docs/adr/*.md``.
    - An ADR resolves if ``docs/adr/NNNN-*.md`` exists.

    Returns a list of human-readable strings like ``"v4.120"`` and
    ``"ADR 0120"`` naming each unresolved claim. Charter: never raise;
    subprocess / filesystem errors return ``[]``.
    """
    root = Path(worktree_root)
    try:
        subj = subprocess.run(
            ["git", "log", "-1", "--format=%s", head_ref],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return []
    if subj.returncode != 0:
        return []
    if not (subj.stdout or "").strip().startswith("[agent]"):
        return []
    try:
        msg = subprocess.run(
            ["git", "log", "-1", "--format=%B", head_ref],
            cwd=str(root), capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return []
    if msg.returncode != 0:
        return []
    versions, adrs = _extract_provenance_claims(msg.stdout or "")
    failures: list[str] = []
    for v in versions:
        if not _version_resolves(root, v):
            failures.append(f"v{v}")
    for n in adrs:
        if not _adr_resolves(root, n):
            failures.append(f"ADR {n}")
    return failures


def check_scope_evasion_strict(
    intended: "Sequence[str | frozenset[str]]",
    write_targets: list[str],
    *,
    base_dir: Path | str | None = None,
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
        if any(p in targets for p in group):
            continue
        # v46 fix: same on-disk guard — a file already written (prior
        # cycle / phase 1) is not scope-evasion even on the max_rounds path.
        if _group_already_on_disk(group, base_dir):
            continue
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
        # Directory-shaped references (trailing slash) are NOT deliverables.
        # v45 diagnosis: a build INBOX says "fill the table from the ledgers
        # under `mind/soak/<run-id>/`", and that backtick-quoted DIRECTORY
        # path was lifted here as an expected artifact. check_artifacts then
        # flagged it missing — a directory is not a non-empty FILE — firing
        # artifact_missing on every postmortem cycle even though the real
        # .md deliverable was fine. That false positive is the postmortem
        # churn that taxed every soak since v41. A path the task asks the
        # agent to WRITE is always a file, never a directory; skip dir refs.
        if not path or path.endswith("/"):
            return
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
        # CHIMERA_ACT_FORCE_MODEL pins ACT to a specific, reliable Anthropic model
        # instead of the ladder's cheapest-first rung. The self-determination soaks
        # (create/self-determine roadmap) showed the cheap OpenRouter rungs return
        # empty/weak completions here, so the agent cannot converge on test-less
        # targets. This knob lets a soak run ACT on a capable model (e.g. the
        # critic's claude-sonnet-4-6) without rewiring the whole ladder.
        forced = os.environ.get("CHIMERA_ACT_FORCE_MODEL")
        if forced:
            return _forced_anthropic_rung(forced)
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
        stop_reason = ""

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
