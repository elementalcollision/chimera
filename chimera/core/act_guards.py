"""ACT-phase guard/check functions — moved verbatim from act.py (ADR 0177).

Pure move: every function and constant in this module was extracted
unchanged from ``chimera/core/act.py``, which re-imports all of these
names and remains the public façade — external consumers import (and
tests monkeypatch) these names on ``chimera.core.act``.
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from ..tools import ToolCall, extract_target_paths

logger = logging.getLogger(__name__)


# ───────────────────────── scope-evasion checks ─────────────────────────

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

# ────────── write-target extraction & fix-without-test checks ──────────

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

# ──────────────────── syntax & import-shadow checks ────────────────────

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

# ───── git write-target fallback (shared by the write-target gates) ─────

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

# ────────────────────────── test-claim checks ──────────────────────────

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

# ──────────── commit-diff / provenance / verify-claim checks ────────────

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

# ─────────────────── artifact & content-marker checks ───────────────────

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

# ────────────────────────── inbox-claim checks ──────────────────────────

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
