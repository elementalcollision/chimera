"""Self-origination (thrust ②, chip 1) — scan the repo for real maintenance work.

Today a human hand-writes ``TASK_GOAL`` / ``TASK_FILES`` / ``TASK_TEST`` for
``scripts/real_task_soak.sh``. This module derives those triples from the repo
itself, so Chimera can originate its own work — the "WHAT" leg of no-contract
autonomy (see ``mind/research/self-origination-design-2026-05-31.md`` and
``docs/adr/0161-self-origination-proposal.md``).

PROPOSAL-ONLY. ``scan_repo`` emits a *ranked list of candidate task triples* for
a human to pick from — it launches nothing. This first cut covers ONLY the two
behaviour-neutral, auto-enforceable sources:

  - **ruff debt** (source A): lint findings → "fix the lint in <file>"
    (mechanical, behaviour-preserving).
  - **mutation survivors** (source E): a function whose behaviour the suite does
    not pin → "add tests that kill the survivors" (a TEST-only change, no source
    behaviour touched).

Both are ``risk_flag=""`` (safe). Behaviour-CHANGING sources (failing tests, dead
code, TODOs) are deliberately out of this chip; they need the risk flag and the
not-yet-trusted critic.

Charter: never raise; a missing tool (e.g. ruff absent) yields no candidates from
that source — fail-open, inheriting ``verify_change``'s posture. Finders are
injectable so unit tests need no real ruff/pytest.
"""

from __future__ import annotations

import json
import subprocess
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Source weights — both behaviour-neutral; test-only (mutation) ranks above
# source-editing (ruff) per the design's value × inverse-risk × scope ordering.
_SOURCE_WEIGHT = {"mutation": 1.0, "ruff": 0.9}


@dataclass
class TaskCandidate:
    goal: str
    files: list[str]
    test: str | None
    source: str            # "ruff" | "mutation"
    score: float
    risk_flag: str = ""    # "" = behaviour-neutral/safe; non-empty = needs adjudication
    detail: str = ""

    @property
    def single_file(self) -> bool:
        return len(self.files) == 1

    def soak_command(self, base: str = "main") -> str:
        """A copy-pasteable real_task_soak.sh invocation for this candidate."""
        parts = [f'TASK_GOAL="{self.goal}"', f'TASK_FILES="{" ".join(self.files)}"']
        if self.test:
            parts.append(f'TASK_TEST="{self.test}"')
        parts.append(f'TASK_BASE="{base}"')
        parts.append("bash scripts/real_task_soak.sh")
        return " ".join(parts)


def _score(source: str, value: int, files: list[str]) -> float:
    """Deterministic rank score: source weight (safety) + a small value bonus,
    penalised for multi-file scope. Higher is better."""
    weight = _SOURCE_WEIGHT.get(source, 0.5)
    value_bonus = min(value, 10) / 100.0          # 0.00–0.10 tiebreaker
    scope_penalty = 0.0 if len(files) <= 1 else 0.2
    return round(weight + value_bonus - scope_penalty, 4)


def rank(candidates: list[TaskCandidate]) -> list[TaskCandidate]:
    """Stable deterministic ranking: by score desc, then source, then first file."""
    return sorted(
        candidates,
        key=lambda c: (-c.score, c.source, c.files[0] if c.files else ""),
    )


# ── default finders (real, best-effort, fail-open) ───────────────────


def default_ruff_finder(repo_root: Path | str) -> dict[str, int]:
    """Map ``relative source path -> ruff finding count`` via
    ``ruff check --output-format json``. Fail-open: ruff missing / error → {}."""
    root = Path(repo_root)
    try:
        proc = subprocess.run(
            ["uv", "run", "ruff", "check", "--output-format", "json", "."],
            cwd=str(root), capture_output=True, text=True, timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return {}
    try:
        findings = json.loads(proc.stdout or "[]")
    except (json.JSONDecodeError, ValueError):
        return {}
    counts: Counter[str] = Counter()
    for f in findings:
        filename = f.get("filename")
        if not filename:
            continue
        try:
            rel = str(Path(filename).resolve().relative_to(root.resolve()))
        except ValueError:
            rel = filename
        counts[rel] += 1
    return dict(counts)


# ── candidate builders ───────────────────────────────────────────────


def _ruff_candidates(finding_counts: dict[str, int]) -> list[TaskCandidate]:
    out: list[TaskCandidate] = []
    for path, n in finding_counts.items():
        if n <= 0:
            continue
        out.append(TaskCandidate(
            goal=f"fix the {n} ruff lint finding(s) in {path}",
            files=[path], test=None, source="ruff",
            score=_score("ruff", n, [path]),
            risk_flag="",  # lint fixes are mechanical / behaviour-preserving
            detail=f"{n} ruff finding(s)",
        ))
    return out


def _mutation_candidates(
    survivors: list[tuple[str, str, int]],
) -> list[TaskCandidate]:
    """survivors: list of (test_file, source_file, surviving_mutant_count)."""
    out: list[TaskCandidate] = []
    for test_file, source_file, n in survivors:
        if n <= 0:
            continue
        out.append(TaskCandidate(
            goal=(f"add tests to {test_file} that kill the {n} surviving "
                  f"mutant(s) in {source_file} (behaviour unpinned)"),
            files=[test_file], test=test_file, source="mutation",
            score=_score("mutation", n, [test_file]),
            risk_flag="",  # the change is to the TEST only — no source behaviour
            detail=f"{n} surviving mutant(s) in {source_file}",
        ))
    return out


def scan_repo(
    repo_root: Path | str,
    *,
    ruff_finder: Callable[[Path | str], dict[str, int]] | None = default_ruff_finder,
    mutation_finder: Callable[[Path | str], list[tuple[str, str, int]]] | None = None,
) -> list[TaskCandidate]:
    """Return ranked, behaviour-neutral maintenance candidates for the repo.

    ``ruff_finder`` defaults to the real (fail-open) ruff scan. ``mutation_finder``
    is opt-in (None → skipped) because mutation testing the whole repo is
    expensive; callers/tests inject it. Both finders are pure ``(repo_root) ->
    findings`` callables, so unit tests need no real tooling. Never raises.
    """
    candidates: list[TaskCandidate] = []
    if ruff_finder is not None:
        try:
            candidates += _ruff_candidates(ruff_finder(repo_root))
        except Exception:  # a finder bug must not crash the scan
            pass
    if mutation_finder is not None:
        try:
            candidates += _mutation_candidates(mutation_finder(repo_root))
        except Exception:
            pass
    return rank(candidates)


# Exported for callers assembling their own finders.
__all__ = [
    "TaskCandidate",
    "scan_repo",
    "rank",
    "default_ruff_finder",
]
