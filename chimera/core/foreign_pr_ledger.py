"""Foreign-PR governance ledger (ADR 0186 B.4c).

Two append-only records, separate from the soak outcome ledger
(``crawl_ledger.py``) because they govern *whether a foreign PR may open*, not
the outcome of a soak:

1. **verify_cmd review** (per repo) — the operator has reviewed a foreign repo's
   ``verify_cmd`` for network / secrets / arbitrary-download risk BEFORE it is
   ever executed-and-PR'd (ADR 0186 B.4 M4). ``maybe_foreign_pr`` is fail-closed
   on an unreviewed repo.
2. **foreign PR opened** (global) — one record per foreign draft PR successfully
   opened, so the first-5-need-approval gate (M4) can count the track record.

Append-only JSONL at ``state/crawl/foreign_pr_governance.jsonl``; every read is
**fail-soft** (missing file / bad line / unreadable dir → safe default, never
raises) so a governance-ledger problem can never crash a soak.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_KIND_REVIEW = "verify_cmd_review"
_KIND_PR = "foreign_pr_opened"


def governance_path(state_dir: Path) -> Path:
    return Path(state_dir) / "crawl" / "foreign_pr_governance.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append(state_dir: Path, rec: dict) -> Path:
    p = governance_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return p


def _read(state_dir: Path) -> list[dict]:
    """All well-formed records; fail-soft (missing/unreadable → [])."""
    p = governance_path(state_dir)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("kind"):
            out.append(obj)
    return out


# ── verify_cmd review (per repo, fail-closed gate) ──────────


def record_verify_cmd_review(state_dir: Path, repo: str, *, ts: str | None = None) -> Path:
    """Mark ``repo``'s ``verify_cmd`` as operator-reviewed (ADR 0186 B.4 M4)."""
    return _append(state_dir, {
        "kind": _KIND_REVIEW, "repo": repo, "ts": ts or _now_iso(),
    })


def is_verify_cmd_reviewed(state_dir: Path, repo: str) -> bool:
    """True iff ``repo`` has a verify_cmd-review record. Fail-soft → False."""
    if not repo:
        return False
    return any(
        r.get("kind") == _KIND_REVIEW and r.get("repo") == repo
        for r in _read(state_dir)
    )


# ── foreign PR opened (global count, approval gate) ─────────


def record_foreign_pr_opened(
    state_dir: Path, repo: str, run_id: str, *,
    pr_url: str | None = None, ts: str | None = None,
) -> Path:
    """Record one successfully-opened foreign draft PR (ADR 0186 B.4c)."""
    return _append(state_dir, {
        "kind": _KIND_PR, "repo": repo, "run_id": run_id,
        "pr_url": pr_url or "", "ts": ts or _now_iso(),
    })


def count_foreign_prs_opened(state_dir: Path) -> int:
    """How many foreign draft PRs have been opened so far (global track record,
    across all foreign repos). Fail-soft → 0. Drives the first-5 approval gate."""
    return sum(1 for r in _read(state_dir) if r.get("kind") == _KIND_PR)
