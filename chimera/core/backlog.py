"""CRAWL backlog — operator-curated task specs (ADR 0182, phase 1).

The first renewable work source for daily autonomous production: a folder
the operator drops Markdown task specs into. Each spec is a small, real,
low-risk maintenance task the picker feeds to ``real_task_soak.sh`` (whose
``TASK_*`` env this module maps to verbatim), producing a draft PR for
batch review. One task/day to begin.

A spec is YAML frontmatter + a free-form body:

    ---
    goal: One-line task description (→ TASK_GOAL)
    files: tests/test_x.py chimera/foo.py   # allowlist (→ TASK_FILES)
    test: tests/test_x.py                    # gate target (→ TASK_TEST), optional
    base: main                               # → TASK_BASE, optional (default main)
    ---
    Free-form context / acceptance notes for the agent.

Selection is oldest-unclaimed-first. "Claimed" = a `done:` marker in the
spec, or an open soak branch for it. Gate-visibility (ADR 0182) is enforced
at pick time by the caller via ``chimera.core.repo_verify.verify_at_ref``:
a spec whose gate is already GREEN on its base proves nothing and is
rejected before the agent is dispatched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*\n?(.*)$", re.DOTALL)

#: Default backlog directory, relative to the mind dir.
BACKLOG_DIRNAME = "backlog"


@dataclass
class BacklogSpec:
    """One parsed, validated backlog task spec."""

    path: Path
    goal: str
    files: tuple[str, ...]
    test: str | None = None
    base: str = "main"
    body: str = ""
    done: bool = False
    # Provenance: "owner/repo#N" when this spec was ingested from a GitHub
    # issue (WALK, ADR 0182 phase 2); None for an operator-authored MD spec.
    issue: str | None = None
    # Multi-repo (ADR 0186 B.1). `repo` = "owner/name" of a FOREIGN target repo;
    # `verify_cmd` = that repo's own gate command (pytest / npm test / cargo test
    # / …) since `chimera verify` can't express it. Both None → self-repo spec,
    # byte-identical to pre-0186 behaviour. A spec with `repo` MUST set `verify_cmd`.
    repo: str | None = None
    verify_cmd: str | None = None
    # Optional BROADER suite for the foreign no-pass-to-pass-regression gate
    # (ADR 0186 B.4i). When set, emitted as CHIMERA_FOREIGN_REGRESSION_CMD so the
    # daily run protects a green base suite per-task (for source-editing tasks).
    regression_cmd: str | None = None
    # Optional DETERMINISTIC characterization driver for the behaviour-preservation
    # gate (ADR 0186 B.4k). For a behaviour-PRESERVING task (refactor/optimize), its
    # stdout must be byte-identical on base vs HEAD; emitted as
    # CHIMERA_FOREIGN_BEHAVIOR_CMD. Only set this when the change MUST NOT alter
    # observable behaviour (a feature/bugfix legitimately changes it → leave unset).
    behavior_cmd: str | None = None
    errors: tuple[str, ...] = field(default=())

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def slug(self) -> str:
        """Stable identifier derived from the filename (no extension)."""
        return self.path.stem

    def task_env(self) -> dict[str, str]:
        """Map to the ``TASK_*`` env real_task_soak.sh consumes."""
        env = {
            "TASK_GOAL": self.goal,
            "TASK_FILES": " ".join(self.files),
            "TASK_BASE": self.base,
        }
        if self.test:
            env["TASK_TEST"] = self.test
        # Multi-repo (ADR 0186 B.1): only emitted for a foreign-repo spec, so a
        # self-repo spec's env is byte-identical to pre-0186.
        if self.repo:
            env["TASK_REPO"] = self.repo
            # A foreign-repo backlog spec exists to produce a foreign DRAFT PR — that
            # is its entire purpose in the daily loop. Opt into the foreign-PR path
            # (graduated past the approval floor; still allowlist- + scope-gated by
            # B.4f/g/h, DRAFT-only) so the daily run actually OPENS the PR rather than
            # leaving the branch in the clone. Self specs never set this (env stays
            # byte-identical to pre-0186) — activation is scoped to foreign specs.
            env["CHIMERA_FOREIGN_PR"] = "1"
        if self.verify_cmd:
            env["TASK_VERIFY_CMD"] = self.verify_cmd
        # Per-spec regression suite (B.4i) — the foreign-pr submit CLI reads this as
        # its --regression-cmd default, so the daily loop can gate pass-to-pass
        # regressions per-task. Only emitted when the spec opts in.
        if self.regression_cmd:
            env["CHIMERA_FOREIGN_REGRESSION_CMD"] = self.regression_cmd
        # Per-spec behaviour-preservation driver (B.4k) — the foreign-pr submit CLI
        # reads this as its --behavior-cmd default, so the daily loop can gate that a
        # behaviour-preserving change did not alter observable output. Opt-in.
        if self.behavior_cmd:
            env["CHIMERA_FOREIGN_BEHAVIOR_CMD"] = self.behavior_cmd
        return env


def parse_spec(path: Path) -> BacklogSpec:
    """Parse + validate one spec file. Never raises — a malformed spec is a
    :class:`BacklogSpec` with ``errors`` populated and ``valid is False``."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return BacklogSpec(path=path, goal="", files=(), errors=(f"unreadable: {exc}",))

    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return BacklogSpec(
            path=path, goal="", files=(),
            errors=("no YAML frontmatter (expected a leading `---` block)",),
        )
    try:
        data = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        return BacklogSpec(path=path, goal="", files=(), errors=(f"invalid YAML: {exc}",))
    if not isinstance(data, dict):
        return BacklogSpec(path=path, goal="", files=(), errors=("frontmatter is not a mapping",))

    body = match.group(2).strip()
    errors: list[str] = []

    goal = str(data.get("goal") or "").strip()
    if not goal:
        errors.append("missing required `goal`")

    files_raw = data.get("files")
    files: tuple[str, ...]
    if isinstance(files_raw, str):
        files = tuple(f for f in files_raw.split() if f)
    elif isinstance(files_raw, list):
        files = tuple(str(f).strip() for f in files_raw if str(f).strip())
    else:
        files = ()
    if not files:
        errors.append("missing required `files` (space-separated allowlist)")

    test = data.get("test")
    test = str(test).strip() if test else None

    base = str(data.get("base") or "main").strip() or "main"

    done = bool(data.get("done"))

    issue = data.get("issue")
    issue = str(issue).strip() if issue else None

    # Multi-repo (ADR 0186 B.1). A foreign-repo spec carries `repo` (owner/name)
    # and its own `verify_cmd` gate. `repo` without `verify_cmd` is rejected (we
    # have no gate for it); `verify_cmd` without `repo` is allowed (override the
    # self-repo gate). Absent both → self-repo spec, unchanged.
    repo = data.get("repo")
    repo = str(repo).strip() if repo else None
    verify_cmd = data.get("verify_cmd")
    verify_cmd = str(verify_cmd).strip() if verify_cmd else None
    if repo and not verify_cmd:
        errors.append("`repo` is set but `verify_cmd` is missing (a foreign repo needs its own gate)")

    # Optional broader regression suite for the no-pass-to-pass gate (B.4i).
    regression_cmd = data.get("regression_cmd")
    regression_cmd = str(regression_cmd).strip() if regression_cmd else None

    # Optional characterization driver for the behaviour-preservation gate (B.4k).
    behavior_cmd = data.get("behavior_cmd")
    behavior_cmd = str(behavior_cmd).strip() if behavior_cmd else None

    return BacklogSpec(
        path=path, goal=goal, files=files, test=test, base=base,
        body=body, done=done, issue=issue, repo=repo, verify_cmd=verify_cmd,
        regression_cmd=regression_cmd, behavior_cmd=behavior_cmd, errors=tuple(errors),
    )


def backlog_dir(mind_dir: Path) -> Path:
    return mind_dir / BACKLOG_DIRNAME


def list_specs(mind_dir: Path) -> list[BacklogSpec]:
    """All specs in the backlog dir, parsed, sorted oldest-file-first.

    Ordering is by filename so an operator can prefix `01-`, `02-` to
    control priority; mtime is the tiebreaker for equal names (won't occur
    in one dir, but keeps the sort total + deterministic)."""
    d = backlog_dir(mind_dir)
    if not d.is_dir():
        return []
    files = [
        p for p in d.glob("*.md")
        # The folder's own README is documentation, not a task spec; skip it
        # and any dot-prefixed files so they never show as INVALID.
        if p.name.lower() != "readme.md" and not p.name.startswith(".")
    ]
    files.sort(key=lambda p: (p.name, p.stat().st_mtime))
    return [parse_spec(p) for p in files]


def select_next(
    mind_dir: Path,
    *,
    claimed_slugs: frozenset[str] = frozenset(),
) -> BacklogSpec | None:
    """The next actionable spec: oldest valid, not-done, not already claimed.

    ``claimed_slugs`` lets the caller exclude specs that already have an open
    soak branch / PR (the picker passes the live set). Invalid specs are
    skipped here — :func:`validation_report` surfaces them separately so a
    typo doesn't silently stall the queue.
    """
    for spec in list_specs(mind_dir):
        if spec.done or not spec.valid or spec.slug in claimed_slugs:
            continue
        return spec
    return None


def validation_report(mind_dir: Path) -> list[tuple[str, tuple[str, ...]]]:
    """(`slug`, errors) for every INVALID spec — so the operator hears about
    a malformed file instead of it being silently skipped forever."""
    return [(s.slug, s.errors) for s in list_specs(mind_dir) if not s.valid]


def ready_slugs(mind_dir: Path) -> list[str]:
    """Slugs (filename stems) of every valid, not-done spec.

    Used by callers that need an allowlist of actionable task ids (for
    example, a CLI listing or a picker that fans out across runs). Order
    matches :func:`list_specs` — filename-then-mtime — so output is
    deterministic.
    """
    return [s.slug for s in list_specs(mind_dir) if s.valid and not s.done]


def count_by_status(mind_dir: Path) -> dict[str, int]:
    """Count specs keyed "ready" (valid, not done), "done", and "invalid".

    Returns ``{"ready": N, "done": N, "invalid": N}``, always with all three
    keys even if some counts are zero.
    """
    counts: dict[str, int] = {"ready": 0, "done": 0, "invalid": 0}
    for s in list_specs(mind_dir):
        if not s.valid:
            counts["invalid"] += 1
        elif s.done:
            counts["done"] += 1
        else:
            counts["ready"] += 1
    return counts
