"""CRAWL outcome ledger — the evidence base for RUN graduation (ADR 0182).

Evidence-first: before auto-merge can be justified, the loop must show a
sustained quality bar across landed work. This ledger records one outcome
per CRAWL run — spec, gate result, commits, cost, branch, and a disposition
the operator (or a future `gh`-reconcile) updates — so the graduation
metrics (gate-pass rate, merge rate, revert rate, cost-per-landed-change)
are computed from real history, not vibes.

Append-only JSONL at ``state/crawl/outcomes.jsonl``: each line is a full
outcome dict keyed by ``run_id``; summarise/read fold to the latest line
per run_id (so a disposition update is just a re-append — no in-place
mutation, crash-safe).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

GATE_PASS = "pass"
GATE_FAIL = "fail"
DISPOSITIONS = ("pending", "merged", "reverted", "abandoned")


@dataclass
class CrawlOutcome:
    run_id: str
    ts: str
    slug: str
    gate: str                     # "pass" | "fail"
    committed: int = 0            # number of [agent] commits on the branch
    cost_usd: float = 0.0
    branch: str = ""
    base: str = "main"
    issue: str | None = None      # owner/repo#N when WALK-sourced
    disposition: str = "pending"  # pending | merged | reverted | abandoned

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items()}


def ledger_path(state_dir: Path) -> Path:
    return state_dir / "crawl" / "outcomes.jsonl"


def record_outcome(state_dir: Path, outcome: CrawlOutcome) -> Path:
    """Append a full outcome line. Returns the ledger path."""
    p = ledger_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(outcome.to_dict(), sort_keys=True) + "\n")
    return p


def _read_raw(state_dir: Path) -> list[dict]:
    p = ledger_path(state_dir)
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("run_id"):
            out.append(obj)
    return out


def read_outcomes(state_dir: Path) -> list[CrawlOutcome]:
    """Folded latest-per-run_id outcomes, in first-seen order."""
    raw = _read_raw(state_dir)
    latest: dict[str, dict] = {}
    order: list[str] = []
    for obj in raw:
        rid = obj["run_id"]
        if rid not in latest:
            order.append(rid)
        latest[rid] = obj
    return [
        CrawlOutcome(
            run_id=o["run_id"], ts=o.get("ts", ""), slug=o.get("slug", ""),
            gate=o.get("gate", GATE_FAIL), committed=int(o.get("committed", 0)),
            cost_usd=float(o.get("cost_usd", 0.0)), branch=o.get("branch", ""),
            base=o.get("base", "main"), issue=o.get("issue"),
            disposition=o.get("disposition", "pending"),
        )
        for o in (latest[r] for r in order)
    ]


def set_disposition(state_dir: Path, run_id: str, disposition: str) -> bool:
    """Re-append the run's latest outcome with an updated disposition.

    Returns False if the run_id isn't in the ledger or the disposition is
    not recognised.
    """
    if disposition not in DISPOSITIONS:
        return False
    by_id = {o.run_id: o for o in read_outcomes(state_dir)}
    cur = by_id.get(run_id)
    if cur is None:
        return False
    cur.disposition = disposition
    record_outcome(state_dir, cur)
    return True


# ── automated revert reconciliation (ADR 0186 B.4l label producer) ───
#
# The disposition field was, until now, only ever set by hand (the docstring's
# "future gh-reconcile") — so `reverted` had been recorded ZERO times and every
# B.4l calibration bound was starved of its strongest free ground-truth signal.
# These functions detect reverts of merged CRAWL work on `base` and set those runs'
# disposition automatically, so the signal accrues going forward.
#
# HONEST CAVEAT (codex q006): the match is a documented NOISY PROXY, not ground
# truth. It keys off the run's branch/slug appearing in a "Revert ..." subject, so
# it can miss reverts (squash-merge subjects vary) and a revert may fire for
# non-gate reasons (operator changed their mind). It under-counts true misses — so
# the count it produces is a LOWER bound on misses and must NOT be fed as a numerator
# into a sound FNR bound until a coverage back-test validates it (B.4l guard).


def detect_reverts(merged_outcomes: list, revert_messages: list[str]) -> set[str]:
    """Pure: return the run_ids of ``merged_outcomes`` whose work appears reverted —
    i.e. the run's ``branch`` or ``slug`` is referenced in any ``revert_messages``
    entry (a ``Revert "<original subject>"`` quotes the original PR title). Injectable
    (messages passed in) → unit-testable with no git."""
    hits: set[str] = set()
    for o in merged_outcomes:
        needles = [n for n in (getattr(o, "branch", ""), getattr(o, "slug", "")) if n]
        if needles and any(nd in msg for msg in revert_messages for nd in needles):
            hits.add(o.run_id)
    return hits


def git_revert_messages(repo_root: Path, base: str = "main", *, run=subprocess.run) -> list[str]:
    """The ``Revert ...`` commit subjects on ``base`` (best-effort; [] on any git
    error). ``run`` is injectable for tests."""
    try:
        p = run(["git", "log", base, "--format=%s"], cwd=str(repo_root),
                capture_output=True, text=True, timeout=30)
    except (subprocess.SubprocessError, OSError):
        return []
    if p.returncode != 0:
        return []
    return [ln for ln in p.stdout.splitlines() if ln.startswith("Revert ")]


def reconcile_reverts(state_dir: Path, repo_root: Path, base: str = "main",
                      *, messages_fn=git_revert_messages) -> list[str]:
    """Detect reverts of merged CRAWL work on ``base`` and set those runs'
    disposition to ``reverted`` (the B.4l automated label producer). Returns the
    newly-reverted run_ids. Noisy proxy — see the section note."""
    merged = [o for o in read_outcomes(state_dir) if o.disposition == "merged"]
    if not merged:
        return []
    hits = detect_reverts(merged, messages_fn(repo_root, base))
    newly = [rid for rid in sorted(hits) if set_disposition(state_dir, rid, "reverted")]
    return newly


def summarize_outcomes(state_dir: Path, since: str | None = None) -> dict:
    """Fold the ledger into the RUN-graduation evidence metrics."""
    outcomes = read_outcomes(state_dir)
    if since is not None:
        outcomes = [o for o in outcomes if o.ts >= since]

    total = len(outcomes)
    if total == 0:
        return {"total": 0}

    gate_pass = sum(1 for o in outcomes if o.gate == GATE_PASS)
    by_disp: dict[str, int] = {}
    for o in outcomes:
        by_disp[o.disposition] = by_disp.get(o.disposition, 0) + 1
    merged = by_disp.get("merged", 0)
    reverted = by_disp.get("reverted", 0)
    total_cost = sum(o.cost_usd for o in outcomes)

    return {
        "total": total,
        "gate_pass": gate_pass,
        "gate_pass_rate": round(gate_pass / total, 4),
        "by_disposition": by_disp,
        "merged": merged,
        "reverted": reverted,
        # revert_rate is over LANDED work — the auto-merge safety signal.
        "revert_rate": round(reverted / merged, 4) if merged else None,
        "total_cost_usd": round(total_cost, 4),
        "cost_per_run_usd": round(total_cost / total, 4),
        "cost_per_landed_usd": round(total_cost / merged, 4) if merged else None,
    }


# ── single-number RUN-graduation rates (specs 06 / 10) ───────────────


def _disposition_rate(outcomes: list, disposition: str, since: str | None = None) -> float:
    """Pure: the fraction of ``outcomes`` (those with ``ts >= since`` when ``since`` is
    set) whose ``disposition`` matches, rounded to 4 dp; ``0.0`` for an empty window.
    The pure core both rate helpers share — and the property-fuzz target (B.4k)."""
    in_window = [o for o in outcomes if since is None or o.ts >= since]
    total = len(in_window)
    if total == 0:
        return 0.0
    n = sum(1 for o in in_window if o.disposition == disposition)
    return round(n / total, 4)


def merge_rate(state_dir: Path, since: str | None = None) -> float:
    """Fraction of folded outcomes that ``merged`` — the RUN-graduation signal in one
    number (``0.0`` when there are none). Honours the ``summarize_outcomes`` ``since``
    window."""
    return _disposition_rate(read_outcomes(state_dir), "merged", since)


def revert_rate(state_dir: Path, since: str | None = None) -> float:
    """Fraction of folded outcomes that ``reverted`` — the safety counterpart to
    ``merge_rate`` (``0.0`` when there are none). NOTE: this is reverted/TOTAL (the
    spec-06/10 pair), distinct from ``summarize_outcomes``'s ``revert_rate`` which is
    reverted/merged (the auto-merge safety signal over LANDED work)."""
    return _disposition_rate(read_outcomes(state_dir), "reverted", since)


def outcomes_for_slug(state_dir: Path, slug: str) -> list:
    """The folded outcomes whose ``slug`` matches, in ``read_outcomes`` (first-seen)
    order — how one spec has fared across runs (re-dispatches, reverts). ``[]`` for an
    unknown slug."""
    return [o for o in read_outcomes(state_dir) if o.slug == slug]
