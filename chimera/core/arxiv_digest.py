"""Recurring ingestion of the arXiv work-item feed into Chimera's memory.

The weekly scrape (Agent_Data/arxiv_feed) emits a chimera-routed feed already
pre-filtered to on-mission papers (software / coding / agent / agent-safety).
This module RANKS that feed by a transparent relevance heuristic and writes a
dated digest into ``mind/research/`` so the operator reviews a ranked shortlist
instead of the raw list. Deterministic + dependency-free on purpose: it runs in
the daily driver every day, fail-soft, and only writes once per feed run.

It is intentionally NOT an LLM call — the scraper handles gross noise, this gives
a cheap weekly shortlist, and a deep LLM triage stays an on-demand operator step.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Core software-agent categories (highest signal for an autonomous PR-solver).
_CORE_CATS = {"cs.SE", "cs.MA", "cs.PL"}
_SAFETY_CATS = {"cs.CR"}
# Substantive work items — a paper that only matched "benchmark" is weaker.
_STRONG_WI = {"algorithm", "proof", "theorem", "problem", "conjecture"}
_STRONG_TERMS = re.compile(
    r"\b(agent\w*|multi-agent|swe-?bench|pull request|repositor\w*|self-improv\w*|"
    r"self-evolv\w*|orchestrat\w*|tool[- ]?use|guardrail\w*|code\w*|software)\b",
    re.IGNORECASE,
)


def score_record(rec: dict) -> int:
    """Transparent relevance score for ranking (higher = more on-mission).

    +3 has a runnable code/OSS link; +3 core software-agent primary category
    (cs.SE/MA/PL) or +2 agent-safety (cs.CR); +2 carries a substantive work item
    (algorithm/proof/…); -1 if it ONLY matched "benchmark"; +1 per distinct strong
    term in the TITLE (capped at 3). Pure — no I/O."""
    s = 0
    if rec.get("links"):
        s += 3
    prim = rec.get("primary_category", "")
    if prim in _CORE_CATS:
        s += 3
    elif prim in _SAFETY_CATS:
        s += 2
    wi = set(rec.get("work_items", []))
    if wi & _STRONG_WI:
        s += 2
    if wi == {"benchmark"}:
        s -= 1
    title = rec.get("title", "")
    distinct = {m.group(0).lower() for m in _STRONG_TERMS.finditer(title)}
    s += min(3, len(distinct))
    return s


def rank_records(records: list[dict]) -> list[dict]:
    """Records sorted best-first by (score desc, published desc)."""
    return sorted(
        records,
        key=lambda r: (score_record(r), r.get("published", "")),
        reverse=True,
    )


def load_chimera_feed(feed_path: Path) -> tuple[str, list[dict]]:
    """Return ``(run_date, records)`` from a chimera feed JSON. Never raises on a
    missing/malformed file — yields ``("", [])`` so the daily driver fails soft."""
    try:
        data = json.loads(Path(feed_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", []
    if not isinstance(data, dict):
        return "", []
    recs = data.get("records")
    return str(data.get("run_date") or ""), recs if isinstance(recs, list) else []


def digest_path(out_dir: Path, run_date: str) -> Path:
    return Path(out_dir) / f"arxiv-digest-{run_date}.md"


def render_digest(records: list[dict], run_date: str, top_n: int = 12) -> str:
    ranked = rank_records(records)
    top, tail = ranked[:top_n], ranked[top_n:]
    lines = [
        f"# arXiv Chimera digest — {run_date}",
        "",
        f"- Feed records (post scraper-filter): {len(records)}",
        f"- Shortlisted: {min(top_n, len(ranked))}  ·  with code/OSS links: "
        f"{sum(1 for r in records if r.get('links'))}",
        "",
        "Auto-ranked by relevance heuristic (code links · core cats · substantive "
        "work items). For a deep read, run an on-demand LLM triage.",
        "",
        "## Shortlist",
        "",
    ]
    for i, r in enumerate(top, 1):
        bare = r.get("arxiv_id", "").split("v")[0]
        links = r.get("links") or {}
        link_str = ", ".join(
            f"[{k}]({u})" for k, urls in links.items() for u in urls
        ) or "—"
        lines += [
            f"### {i}. {r.get('title','(untitled)')}  ·  score {score_record(r)}",
            f"- arXiv:{bare} · `{r.get('primary_category','')}` · "
            f"work: {', '.join(r.get('work_items', [])) or '—'}",
            f"- {r.get('abs_url','')}",
            f"- code: {link_str}",
            "",
        ]
    if tail:
        lines += ["## Also matched (tail)", ""]
        for r in tail:
            bare = r.get("arxiv_id", "").split("v")[0]
            lines.append(
                f"- arXiv:{bare} · `{r.get('primary_category','')}` · "
                f"{r.get('title','')[:90]}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def _bare_id(rec: dict) -> str:
    return rec.get("arxiv_id", "").split("v")[0]


def load_seen(seen_path: Path) -> set[str]:
    """The set of bare arXiv ids already digested (the delta-dedup ledger). Missing
    or malformed → empty set (so the first run treats everything as new). Never raises."""
    try:
        data = json.loads(Path(seen_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return set(data) if isinstance(data, list) else set()


def save_seen(seen_path: Path, ids: set[str]) -> None:
    """Persist the seen-ids ledger (sorted, for stable diffs). Fail-soft."""
    try:
        p = Path(seen_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sorted(ids), indent=0), encoding="utf-8")
    except OSError:
        pass


def write_digest_if_new(
    feed_path: Path, out_dir: Path, top_n: int = 12, *, seen_path: Path | None = None
) -> dict:
    """Ingest the feed → write a digest of the GENUINELY-NEW papers (delta-dedup
    against the ``seen_path`` ledger), then record them as seen. Re-running on the
    same overlapping 7-day window therefore surfaces only fresh papers instead of
    re-emitting the whole set. Without ``seen_path`` it degrades to "write the full
    feed" (no dedup). Fail-soft; never raises."""
    run_date, records = load_chimera_feed(feed_path)
    if not run_date or not records:
        return {"status": "no-feed", "run_date": run_date, "count": 0,
                "total": 0, "path": None}
    seen = load_seen(seen_path) if seen_path else set()
    fresh = [r for r in records if _bare_id(r) not in seen]
    if not fresh:
        return {"status": "no-new", "run_date": run_date, "count": 0,
                "total": len(records), "path": None}
    out = digest_path(out_dir, run_date)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_digest(fresh, run_date, top_n), encoding="utf-8")
    if seen_path:
        save_seen(seen_path, seen | {_bare_id(r) for r in fresh})
    return {"status": "written", "run_date": run_date, "count": len(fresh),
            "total": len(records), "path": str(out)}
