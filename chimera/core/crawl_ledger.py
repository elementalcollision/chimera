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
