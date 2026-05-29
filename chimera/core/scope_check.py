"""Pre-commit scope check — confabulation defense (ADR 0146).

Closes the gap surfaced by v35 soak attempt #3 (see PR #106 postmortem):
the agent honestly committed "I didn't do the work" and then ~2 minutes
later committed a fabricated diagnosis citing percentages it never
computed. Existing engine guards (``scope_evasion``,
``degenerate_loop_abort``, ``witness_rejected``) detected the
off-charter behavior but could not undo a commit that already landed.

This module fills the commit-time vs detect-time gap. It is invoked
from :mod:`chimera.tools.shell` immediately before ``git commit``
reaches subprocess. The check:

1. Finds the active chip's design note under ``mind/research/`` (latest
   ``*-design.md`` by mtime).
2. Parses its ``## READY-FOR-REMEDIATION`` section.
3. Extracts the locked recommendation (R1 / R2 / R3 / file-path
   allowlist / "no code change" signals).
4. Compares the staged diff against that recommendation.
5. Refuses the commit (raises) when the diff scope clearly contradicts
   the locked recommendation.

Conservative defaults: any parse error, missing design note, missing
``READY-FOR-REMEDIATION`` section, or ambiguous classification yields
a warn-only result — the witness panel + engine guards remain.

Override knob: ``CHIMERA_ALLOW_OFF_CHARTER_COMMIT=1`` allows the
commit through with a logged override (same pattern as
``CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1`` from ADR 0141).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# Files always allowed regardless of recommendation — docs, ADRs,
# postmortems, the chip's own design note. Adversarial confabulation
# *also* corrupting the design note can escape (acknowledged
# trade-off; the witness panel still catches that path).
_DOCS_ONLY_PREFIXES: tuple[str, ...] = (
    "docs/",
    "mind/",
    "CHANGELOG.md",
    "README.md",
)

# Path-shaped backtick tokens (used to extract a recommended allowlist
# from the READY-FOR-REMEDIATION section). Conservative: must contain a
# slash AND a recognized source/test extension.
_PATH_TOKEN_RE = re.compile(
    r"`([A-Za-z0-9_./-]+\.(?:py|md|sh|yml|yaml|toml|cfg|json|txt))`"
)

# "no code change" / "docs only" / "no-op" recommendation signals.
_NO_CODE_RE = re.compile(
    r"\b(?:no\s+code\s+change|no[\s-]?op|docs?[\s-]?only|"
    r"documentation[\s-]?only)\b",
    re.IGNORECASE,
)

# R1/R2/R3-style tags.
_R_TAG_RE = re.compile(r"\bR([1-9])\b")


@dataclass(frozen=True)
class Recommendation:
    """Parsed recommendation from a design note's READY-FOR-REMEDIATION section."""

    section_text: str
    r_tag: str | None  # e.g. "R1", "R2", or None when no tag found
    allowed_paths: tuple[str, ...] = field(default_factory=tuple)
    no_code_change: bool = False

    @property
    def is_ambiguous(self) -> bool:
        """True when no actionable scope signal was extracted."""
        return (
            not self.no_code_change
            and not self.allowed_paths
            and self.r_tag is None
        )


@dataclass(frozen=True)
class ScopeCheckResult:
    """Outcome of a single scope check evaluation."""

    verdict: str  # "allow" | "refuse" | "warn"
    reason: str
    design_note: str | None = None
    recommendation: Recommendation | None = None
    staged_paths: tuple[str, ...] = field(default_factory=tuple)
    offending_paths: tuple[str, ...] = field(default_factory=tuple)
    override_used: bool = False


class ScopeCheckRefusal(PermissionError):
    """Raised when the staged diff contradicts the locked recommendation."""

    def __init__(self, result: ScopeCheckResult):
        self.result = result
        super().__init__(result.reason)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def extract_ready_for_remediation(text: str) -> str | None:
    """Return the body under ``## READY-FOR-REMEDIATION``, or None if absent.

    The body runs from the heading to the next ``## `` heading or EOF.
    Trailing whitespace is stripped. Returns ``""`` when the heading
    exists but the section is empty (e.g. v35 attempt #3's failure
    mode); callers must distinguish empty-string from None.
    """
    # Anchor to start of line; tolerate trailing whitespace on heading.
    m = re.search(
        r"(?m)^##\s+READY-FOR-REMEDIATION\s*$",
        text,
    )
    if m is None:
        return None
    start = m.end()
    # Find next top-level "## " heading (not "### ").
    tail = text[start:]
    n = re.search(r"(?m)^##\s+(?!#)", tail)
    body = tail if n is None else tail[: n.start()]
    return body.strip()


def parse_recommendation(section_text: str) -> Recommendation:
    """Extract structured scope signals from a READY-FOR-REMEDIATION body."""

    r_match = _R_TAG_RE.search(section_text)
    r_tag = f"R{r_match.group(1)}" if r_match else None

    no_code = bool(_NO_CODE_RE.search(section_text))

    paths = tuple(sorted(set(_PATH_TOKEN_RE.findall(section_text))))

    return Recommendation(
        section_text=section_text,
        r_tag=r_tag,
        allowed_paths=paths,
        no_code_change=no_code,
    )


def _current_branch_prefix(repo_root: Path) -> str | None:
    """Return the chip prefix (e.g. ``v36``) extracted from the current branch.

    Implements Option A from the v36-postmortem follow-up C (PR #117):
    branches shaped like ``chimera-soak/v36-2026-05-28-1537`` carry the
    chip identity in the segment after the first ``/``; the leading
    alnum token of that segment is the chip prefix used to match a
    design note in ``mind/research/``.

    Returns ``None`` on detached HEAD, non-git directories, branches
    without ``/``, or any unparseable shape — the caller falls back to
    the legacy mtime heuristic on ``None``. Never raises.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse",
             "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    # Detached HEAD reports "HEAD" from --abbrev-ref.
    if not branch or branch == "HEAD":
        return None
    if "/" not in branch:
        return None
    _, rest = branch.split("/", 1)
    # Take the leading alnum token of the remainder as the chip prefix.
    m = re.match(r"([A-Za-z0-9]+)", rest)
    if m is None:
        return None
    prefix = m.group(1)
    return prefix or None


def find_active_design_note(repo_root: Path) -> Path | None:
    """Return the active design note under ``mind/research/``.

    Selection (v36-postmortem follow-up C, PR #117):

    1. If the current git branch carries a chip prefix (e.g.
       ``chimera-soak/v36-…`` → ``v36``), prefer
       ``mind/research/<prefix>-*-design.md``, then
       ``mind/research/<prefix>-*.md`` if no ``*-design.md`` match.
    2. Otherwise (main, detached HEAD, branch without ``/``, or no
       match), fall back to the legacy "latest ``*-design.md`` by
       mtime" heuristic.

    Returns ``None`` when ``mind/research`` is missing or empty.
    Never raises.
    """
    research = repo_root / "mind" / "research"
    if not research.is_dir():
        return None

    prefix = _current_branch_prefix(repo_root)
    if prefix:
        prefixed_designs = sorted(research.glob(f"{prefix}-*-design.md"))
        if prefixed_designs:
            prefixed_designs.sort(
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            return prefixed_designs[0]
        prefixed_any = [
            p for p in research.glob(f"{prefix}-*.md")
            if p.suffix == ".md"
        ]
        if prefixed_any:
            prefixed_any.sort(
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            return prefixed_any[0]
        # Prefix detected but no match — fall through to mtime fallback.

    candidates = list(research.glob("*-design.md"))
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def _is_docs_only(path: str) -> bool:
    """True if a staged path is auto-allowed (docs / research / changelog)."""
    if path.endswith(".md"):
        return True
    return any(path.startswith(prefix) for prefix in _DOCS_ONLY_PREFIXES)


def classify_diff(
    staged_paths: tuple[str, ...],
    recommendation: Recommendation,
) -> tuple[str, tuple[str, ...]]:
    """Return ``(verdict, offending_paths)`` for the given diff + scope.

    Verdict is one of ``"allow"``, ``"refuse"``, ``"warn"``. The
    ``offending_paths`` tuple is non-empty only when verdict is
    ``"refuse"``.
    """
    if not staged_paths:
        return ("allow", ())

    if recommendation.is_ambiguous:
        return ("warn", ())

    # "No code change" recommendation: only docs/research allowed.
    if recommendation.no_code_change:
        offenders = tuple(
            p for p in staged_paths if not _is_docs_only(p)
        )
        return (("refuse", offenders) if offenders else ("allow", ()))

    # Explicit path allowlist: staged code paths must be ⊆ allowlist.
    if recommendation.allowed_paths:
        offenders = tuple(
            p
            for p in staged_paths
            if not _is_docs_only(p) and p not in recommendation.allowed_paths
        )
        return (("refuse", offenders) if offenders else ("allow", ()))

    # R-tag present but no allowlist & no no-code signal — we cannot
    # safely refuse on R-tag alone (R1/R2/R3 semantics are
    # chip-specific). Conservative warn-only.
    return ("warn", ())


# ---------------------------------------------------------------------------
# Diff inspection
# ---------------------------------------------------------------------------


def resolve_repo_root(start: Path) -> Path:
    """Return the git top-level for ``start``, or ``start`` on failure.

    Fail-soft: a non-git directory simply yields ``start`` itself, which
    will cause :func:`find_active_design_note` to return None and the
    overall verdict to be warn-only.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return start
    if result.returncode != 0:
        return start
    top = result.stdout.strip()
    return Path(top) if top else start


def staged_paths(repo_root: Path) -> tuple[str, ...]:
    """Return the list of staged (``git add``-ed) paths.

    Returns an empty tuple on any git failure — the caller treats this
    as "nothing to check" which is harmless.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--cached",
             "--name-only", "--no-renames"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if result.returncode != 0:
        return ()
    return tuple(
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip()
    )


# Commit flags whose FOLLOWING argv token is a value (not a pathspec), so
# the scanner must skip that token when hunting for pathspecs.
_GIT_COMMIT_VALUE_FLAGS = frozenset({
    "-m", "--message", "-F", "--file", "-C", "--reuse-message",
    "-c", "--reedit-message", "--author", "--date", "-t", "--template",
    "--cleanup",
})
# Commit flags that move files into the commit OUTSIDE the staged index
# the scope check inspects (`git diff --cached`) — i.e. evasion vectors.
_GIT_COMMIT_INDEX_BYPASS_FLAGS = {
    "-a": "`-a`/`--all` stages tracked changes at commit time",
    "--all": "`-a`/`--all` stages tracked changes at commit time",
    "--amend": "`--amend` rewrites the prior commit outside the index",
    "-i": "`-i`/`--include` adds pathspec files at commit time",
    "--include": "`-i`/`--include` adds pathspec files at commit time",
    "-o": "`-o`/`--only` commits only the named pathspec",
    "--only": "`-o`/`--only` commits only the named pathspec",
    "--no-verify": "`--no-verify` skips commit hooks",
    "-n": "`-n`/`--no-verify` skips commit hooks",
}


def commit_bypasses_index(argv: list[str]) -> str | None:
    """Return a reason if a ``git commit`` argv commits files WITHOUT going
    through the staged index — else ``None``.

    H1 (v42 fix): :func:`check_commit_scope` inspects ``git diff --cached``
    (the staged set). A ``git commit <pathspec>`` / ``-a`` / ``--amend``
    commits files that never enter that snapshot, so the allowlist is
    evaded (v42 attempt #1 landed an off-charter ``tests/`` file this way).
    Forcing the auditable staged flow — ``git add <files>`` then a bare
    ``git commit`` — keeps the scope check authoritative. Non-commit argv
    returns ``None``.
    """
    if len(argv) < 2 or argv[0] != "git" or argv[1] != "commit":
        return None
    rest = argv[2:]
    i, n = 0, len(rest)
    while i < n:
        tok = rest[i]
        if tok == "--":
            return ("pathspec after `--` bypasses the staged index"
                    if rest[i + 1:] else None)
        if tok.startswith("--"):
            base = tok.split("=", 1)[0]
            if base in _GIT_COMMIT_INDEX_BYPASS_FLAGS:
                return _GIT_COMMIT_INDEX_BYPASS_FLAGS[base]
            if base in _GIT_COMMIT_VALUE_FLAGS and "=" not in tok:
                i += 2
                continue
            i += 1
            continue
        if tok.startswith("-") and len(tok) > 1:
            chars = tok[1:]
            for c in chars:  # combined short flags, e.g. -am
                if f"-{c}" in _GIT_COMMIT_INDEX_BYPASS_FLAGS:
                    return _GIT_COMMIT_INDEX_BYPASS_FLAGS[f"-{c}"]
            if f"-{chars[-1]}" in _GIT_COMMIT_VALUE_FLAGS:
                i += 2  # trailing value flag consumes the next token
                continue
            i += 1
            continue
        # A bare, non-flag token that isn't a flag value → a pathspec.
        return f"pathspec argument '{tok}' bypasses the staged index"
    return None


# ---------------------------------------------------------------------------
# Event logging
# ---------------------------------------------------------------------------


def _events_path() -> Path:
    state_dir = Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
    return state_dir / "scope_check_events.jsonl"


def record_event(result: ScopeCheckResult, *, path: Path | None = None) -> None:
    """Append a scope-check event to ``state/scope_check_events.jsonl``.

    Fail-soft: any write error is logged at warning level and swallowed.
    The engine guard system (witness panel, drift dashboard) consumes
    this file to demote trust.
    """
    target = path or _events_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "event": "scope_check_refusal"
            if result.verdict == "refuse" and not result.override_used
            else (
                "scope_check_override"
                if result.override_used
                else f"scope_check_{result.verdict}"
            ),
            "verdict": result.verdict,
            "reason": result.reason,
            "design_note": result.design_note,
            "staged_paths": list(result.staged_paths),
            "offending_paths": list(result.offending_paths),
            "override_used": result.override_used,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        if result.recommendation is not None:
            record["recommendation"] = {
                "r_tag": result.recommendation.r_tag,
                "allowed_paths": list(result.recommendation.allowed_paths),
                "no_code_change": result.recommendation.no_code_change,
                "ambiguous": result.recommendation.is_ambiguous,
            }
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("scope_check: failed to record event: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


_OVERRIDE_ENV = "CHIMERA_ALLOW_OFF_CHARTER_COMMIT"


def evaluate_commit_scope(
    repo_root: Path,
    *,
    staged: tuple[str, ...] | None = None,
    design_note: Path | None = None,
) -> ScopeCheckResult:
    """Pure evaluation: classify a (diff, design-note) pair.

    Does not consult the override env var and does not raise — useful
    for tests and for callers that want to inspect the verdict before
    deciding what to do.
    """
    paths = staged_paths(repo_root) if staged is None else staged
    note = design_note if design_note is not None else find_active_design_note(repo_root)

    if note is None:
        return ScopeCheckResult(
            verdict="warn",
            reason="no design note under mind/research/*-design.md — scope check skipped",
            staged_paths=paths,
        )

    try:
        text = note.read_text(encoding="utf-8")
    except OSError as exc:
        return ScopeCheckResult(
            verdict="warn",
            reason=f"could not read design note {note}: {exc}",
            design_note=str(note),
            staged_paths=paths,
        )

    section = extract_ready_for_remediation(text)
    if section is None:
        return ScopeCheckResult(
            verdict="warn",
            reason=f"design note {note.name} has no `## READY-FOR-REMEDIATION` heading",
            design_note=str(note),
            staged_paths=paths,
        )

    recommendation = parse_recommendation(section)
    verdict, offenders = classify_diff(paths, recommendation)

    if verdict == "refuse":
        reason = (
            f"staged diff contradicts locked recommendation in {note.name}: "
        )
        if recommendation.no_code_change:
            reason += (
                f"recommendation forbids code changes, but staged paths include "
                f"{', '.join(offenders)}"
            )
        else:
            reason += (
                f"staged paths {', '.join(offenders)} are outside the "
                f"recommendation's allowlist "
                f"({', '.join(recommendation.allowed_paths)})"
            )
    elif verdict == "warn":
        reason = (
            f"scope check ambiguous (no actionable signal in "
            f"`## READY-FOR-REMEDIATION` of {note.name}) — allowing commit"
        )
    else:
        reason = f"staged diff matches locked recommendation in {note.name}"

    return ScopeCheckResult(
        verdict=verdict,
        reason=reason,
        design_note=str(note),
        recommendation=recommendation,
        staged_paths=paths,
        offending_paths=offenders,
    )


def check_commit_scope(repo_root: Path) -> ScopeCheckResult:
    """Full check used by the shell tool wire-up.

    Reads the override env var; refuses (raises) when verdict=refuse
    and override is not set; otherwise records the event and returns
    the result. Callers that catch :class:`ScopeCheckRefusal` get the
    full :class:`ScopeCheckResult` on ``exc.result``.
    """
    result = evaluate_commit_scope(repo_root)

    override = bool(os.environ.get(_OVERRIDE_ENV, "").strip())
    if result.verdict == "refuse" and override:
        result = ScopeCheckResult(
            verdict=result.verdict,
            reason=result.reason + f" (overridden via {_OVERRIDE_ENV}=1)",
            design_note=result.design_note,
            recommendation=result.recommendation,
            staged_paths=result.staged_paths,
            offending_paths=result.offending_paths,
            override_used=True,
        )
        record_event(result)
        logger.warning(
            "scope_check: refusal overridden via %s — %s",
            _OVERRIDE_ENV,
            result.reason,
        )
        return result

    record_event(result)

    if result.verdict == "refuse":
        raise ScopeCheckRefusal(result)

    return result
