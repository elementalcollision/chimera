"""LongMemEval adapter — Chimera-side answer surface (ADR 0135, Proposed).

Phase 4 #8 integration chip. The upstream LongMemEval harness
(https://github.com/xiaowu0162/LongMemEval) iterates 500 manually
curated question/history pairs across five categories and grades
answers with a judge model. This module is the **adapter** the
upstream harness — or our own CLI verb — calls into.

What this module does:

  * :class:`LongMemEvalItem` typed schema (question, history,
    expected, category, item_id).
  * :class:`LongMemEvalAdapter` — bulk-ingest a history into the
    Chimera memory surfaces it can reach today (FTS5 wiki + chronicle
    fallback), then answer the question via the dialectic API path
    from ADR 0133.
  * :func:`load_items` reads JSONL items; :func:`run_batch` iterates
    an adapter over a list of items and returns
    :class:`AnswerResult` rows.

What this module does NOT do:

  * Run the upstream judge model. Grading is the harness's job; we
    produce answers + ``sources_used`` provenance and let the
    operator pipe results to whichever grader they're paying for.
  * Re-implement the upstream prompt. We call the dialectic API
    which assembles its own grounding; the upstream harness gets
    the answer string back.
  * Persist results long-term. Results land in ``mind/evals/<file>.jsonl``;
    cadence / dashboards / regression tracking are named follow-ups
    in ADR 0135.

The adapter is :class:`Proposed` until a baseline run validates it
end-to-end. See ADR 0135 §"Status".
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


logger = logging.getLogger(__name__)


# ── Typed schema ──────────────────────────────────────────────────


@dataclass(frozen=True)
class LongMemEvalItem:
    """One question + history pair from the upstream benchmark.

    Field names mirror the upstream JSON shape so a JSONL pipe-in
    works without re-keying. ``category`` is one of LongMemEval's
    five labels (single-session-user / single-session-assistant /
    multi-session / knowledge-update / temporal-reasoning /
    abstention).

    ``history`` is a list of *sessions*; each session is a list of
    ``{"role", "content"}`` turn dicts. The upstream shape uses
    ``sessions`` keyed under ``haystack_sessions``; we accept either
    via :meth:`from_dict`.
    """

    item_id: str
    question: str
    history: list[list[dict[str, str]]]
    expected_answer: str = ""
    category: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> LongMemEvalItem:
        history = (
            obj.get("history")
            or obj.get("haystack_sessions")
            or []
        )
        return cls(
            item_id=str(obj.get("item_id") or obj.get("id") or ""),
            question=str(obj.get("question", "")),
            history=list(history),
            expected_answer=str(obj.get("expected_answer")
                                or obj.get("answer", "")),
            category=str(obj.get("category", "")),
            extra={
                k: v for k, v in obj.items()
                if k not in {
                    "item_id", "id", "question", "history",
                    "haystack_sessions", "expected_answer", "answer",
                    "category",
                }
            },
        )


@dataclass(frozen=True)
class AnswerResult:
    """One adapter answer + provenance, JSON-serialisable."""

    item_id: str
    question: str
    answer: str
    sources_used: list[str]
    category: str = ""
    expected_answer: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Adapter ───────────────────────────────────────────────────────


class LongMemEvalAdapter:
    """Bulk-ingest history then answer the question via the dialectic API.

    The adapter is **stateful** for the duration of one item: ingest
    writes per-session markdown into a scratch wiki directory; answer
    runs the dialectic pipeline against the populated mind dir; reset
    truncates the scratch dir between items so cross-item leakage is
    impossible.

    Parameters
    ----------
    mind_dir:
        Scratch ``mind/`` to populate. Tests should pass a tmp_path;
        operators run with their real ``CHIMERA_MIND_DIR``.
    ingest_subdir:
        Subdirectory under ``mind/wiki/`` to write session markdown
        into. Defaults to ``"longmemeval"`` so the operator can `rm`
        it without losing wiki content.
    """

    def __init__(
        self,
        *,
        mind_dir: Path,
        ingest_subdir: str = "longmemeval",
    ) -> None:
        self._mind_dir = Path(mind_dir)
        self._ingest_subdir = ingest_subdir
        self._scratch_dir = self._mind_dir / "wiki" / ingest_subdir
        self._self_card_path = self._mind_dir / "peers" / "self.md"

    # ── ingest / reset ─────────────────────────────────────

    def reset(self) -> None:
        """Truncate the scratch ingest dir + remove the synthetic self
        card. Idempotent.
        """
        if self._scratch_dir.exists():
            for child in self._scratch_dir.iterdir():
                if child.is_file():
                    child.unlink()
        if self._self_card_path.exists():
            self._self_card_path.unlink()

    def ingest_history(self, item: LongMemEvalItem) -> int:
        """Bulk-ingest ``item``'s history into two surfaces:

        * A **synthetic self peer card** at ``mind/peers/self.md`` that
          concatenates every session's turns. This is what the
          dialectic API reads (ADR 0133 §"gather_dialectic_context");
          it's the load-bearing surface today.
        * **Per-session markdown** under ``mind/wiki/longmemeval/`` so
          a future hybrid-search-enabled adapter (Phase 4 #6.b) can
          retrieve by FTS5 + vector once that path is wired.

        Returns the number of session files written.
        """
        # Synthetic self card — load-bearing.
        self._self_card_path.parent.mkdir(parents=True, exist_ok=True)
        card_lines = [f"# Peer card — self", "", "## History", ""]
        for i, session in enumerate(item.history):
            card_lines.append(f"### Session {i}")
            for turn in session:
                role = str(turn.get("role", "user"))
                content = str(turn.get("content", "")).strip()
                if not content:
                    continue
                card_lines.append(f"- **{role}**: {content}")
            card_lines.append("")
        self._self_card_path.write_text(
            "\n".join(card_lines).rstrip() + "\n", encoding="utf-8",
        )

        # Per-session scratch for future hybrid search.
        self._scratch_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for i, session in enumerate(item.history):
            path = self._scratch_dir / f"{item.item_id or 'item'}-s{i:03d}.md"
            lines = [f"# Session {i} — {item.item_id}", ""]
            for turn in session:
                role = str(turn.get("role", "user"))
                content = str(turn.get("content", "")).strip()
                if not content:
                    continue
                lines.append(f"**{role}**: {content}")
                lines.append("")
            path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            count += 1
        return count

    # ── answer ─────────────────────────────────────────────

    def answer(self, item: LongMemEvalItem) -> AnswerResult:
        """Produce an :class:`AnswerResult` for ``item``.

        Today the adapter uses the dialectic API's
        :func:`chimera.a2a.dialectic.gather_dialectic_context` plus
        :func:`build_dialectic_prompt` to assemble grounding from the
        ingested wiki sessions. The assembled prompt is what the
        upstream harness would pass to a judge; we return it as
        ``answer`` so the operator can pipe through their grader.

        Errors are captured into :attr:`AnswerResult.error` rather
        than raised, so a single bad item doesn't kill a sweep.
        """
        try:
            from ..a2a.dialectic import (
                build_dialectic_prompt,
                gather_dialectic_context,
            )

            # The dialectic API expects a peer name. For LongMemEval
            # we always answer about "self" — the question is about
            # Chimera's own (synthetic) history.
            ctx = gather_dialectic_context("self", mind_dir=self._mind_dir)
            prompt = build_dialectic_prompt(ctx, item.question)
            return AnswerResult(
                item_id=item.item_id,
                question=item.question,
                answer=prompt,
                sources_used=list(ctx.sources_used),
                category=item.category,
                expected_answer=item.expected_answer,
            )
        except Exception as exc:  # noqa: BLE001 — never fail a sweep
            logger.warning(
                "longmemeval: adapter failed on %s: %s",
                item.item_id or "?", exc,
            )
            return AnswerResult(
                item_id=item.item_id,
                question=item.question,
                answer="",
                sources_used=[],
                category=item.category,
                expected_answer=item.expected_answer,
                error=str(exc),
            )


# ── JSONL I/O ─────────────────────────────────────────────────────


def load_items(path: Path) -> list[LongMemEvalItem]:
    """Read a JSONL of LongMemEval items. Skips malformed lines."""
    p = Path(path)
    if not p.exists():
        return []
    out: list[LongMemEvalItem] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        out.append(LongMemEvalItem.from_dict(obj))
    return out


def default_results_path(mind_dir: Path) -> Path:
    """``mind/evals/longmemeval-<ts>.jsonl`` — operator-grep-able results."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(mind_dir) / "evals" / f"longmemeval-{ts}.jsonl"


def write_results(results: Iterable[AnswerResult], path: Path) -> Path:
    """Append-style write of a result batch to ``path``. Creates dirs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
    return p


# ── Batch runner ──────────────────────────────────────────────────


def run_batch(
    adapter: LongMemEvalAdapter,
    items: Iterable[LongMemEvalItem],
    *,
    limit: int | None = None,
    subset: str | None = None,
) -> list[AnswerResult]:
    """Iterate ``items`` through ``adapter``; reset between items.

    ``subset`` filters by ``category`` (case-insensitive substring).
    ``limit`` caps the count after filtering. Both default to no-op.
    """
    results: list[AnswerResult] = []
    sub = subset.lower() if subset else None
    n = 0
    for item in items:
        if sub is not None and sub not in item.category.lower():
            continue
        if limit is not None and n >= int(limit):
            break
        adapter.reset()
        adapter.ingest_history(item)
        results.append(adapter.answer(item))
        n += 1
    adapter.reset()
    return results


__all__ = [
    "AnswerResult",
    "LongMemEvalAdapter",
    "LongMemEvalItem",
    "default_results_path",
    "load_items",
    "run_batch",
    "write_results",
]
