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
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable


logger = logging.getLogger(__name__)


# An ``AnswerFn`` takes the assembled dialectic prompt and returns
# the model's natural-language hypothesis. Provider-agnostic by
# design — the CLI wires Chimera's ACT sonnet rung; tests pass a
# deterministic stub.
AnswerFn = Callable[[str], str]


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
    question_date: str = ""
    session_dates: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> LongMemEvalItem:
        history = (
            obj.get("history")
            or obj.get("haystack_sessions")
            or []
        )
        session_dates = obj.get("session_dates") or obj.get("haystack_dates") or []
        return cls(
            item_id=str(
                obj.get("item_id")
                or obj.get("id")
                or obj.get("question_id")  # upstream LongMemEval key
                or ""
            ),
            question=str(obj.get("question", "")),
            history=list(history),
            expected_answer=str(obj.get("expected_answer")
                                or obj.get("answer", "")),
            category=str(
                obj.get("category")
                or obj.get("question_type")  # upstream LongMemEval key
                or ""
            ),
            question_date=str(obj.get("question_date", "") or ""),
            session_dates=[str(d) for d in session_dates],
            extra={
                k: v for k, v in obj.items()
                if k not in {
                    "item_id", "id", "question_id", "question",
                    "history", "haystack_sessions", "expected_answer",
                    "answer", "category", "question_type",
                    "question_date", "haystack_dates", "session_dates",
                }
            },
        )


@dataclass(frozen=True)
class AnswerResult:
    """One adapter answer + provenance, JSON-serialisable.

    Field semantics:

      * ``answer`` — in default (prompt-only) mode, this is the
        assembled dialectic prompt. With an ``answer_fn`` passed to
        :meth:`LongMemEvalAdapter.answer`, this is the LLM-generated
        hypothesis the upstream grader will judge.
      * ``hypothesis`` — alias of ``answer`` written under the key the
        upstream LongMemEval grader expects (``hypothesis``). Populated
        only when ``answer_fn`` ran.
      * ``question_id`` — alias of ``item_id`` under the upstream key.
        Same population rule.

    The aliasing avoids a post-processing rename when piping into the
    upstream grader (`src/evaluation/evaluate_qa.py` reads
    ``question_id`` + ``hypothesis``).
    """

    item_id: str
    question: str
    answer: str
    sources_used: list[str]
    category: str = ""
    expected_answer: str = ""
    error: str | None = None
    hypothesis: str | None = None
    question_id: str | None = None

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

    # Preference-signal heuristic — ADR 0138 locked design.
    # First-person assertions about taste, ownership, habit, or recent
    # behaviour ("I prefer X", "I bought Y", "my Z"). The diagnostic in
    # mind/research/implicit-preference-inference-2026-05-25.md showed
    # the signal is present in grounding but the model under-engages
    # with it; this surfaces the signal in a dedicated section above
    # the verbatim transcript so the answerer reads it first.
    _USER_CTX_VERBS_RE = re.compile(
        r"\bI\s+(?:have|own|like|prefer|use|bought|usually|recently|tried|don'?t\s+like|hate|love|avoid|am|'m)\b",
        re.IGNORECASE,
    )
    _USER_CTX_MY_RE = re.compile(r"\bmy\s+\w+\b", re.IGNORECASE)
    _USER_CTX_MAX_BULLETS = 6
    _USER_CTX_TRUNCATE = 200

    @classmethod
    def _extract_user_context(
        cls, item: LongMemEvalItem,
    ) -> list[str]:
        """Pull preference-bearing user turns out of ``item.history``.

        Heuristic (ADR 0138 §locked-design):
          * always include the first non-empty user turn (topic anchor)
          * include any subsequent user turn matching either the
            first-person-verb pattern or the "my <noun>" pattern
          * cap at 6 bullets, truncate each to 200 chars

        Returns an empty list when no signal is found — caller omits
        the section in that case, preserving pre-chip behaviour for
        items without detectable preferences.
        """
        bullets: list[str] = []
        seen: set[str] = set()
        first_user_seen = False
        for session in item.history:
            for turn in session:
                if str(turn.get("role", "")).lower() != "user":
                    continue
                content = str(turn.get("content", "")).strip()
                if not content:
                    continue
                is_anchor = not first_user_seen
                first_user_seen = True
                if not (
                    is_anchor
                    or cls._USER_CTX_VERBS_RE.search(content)
                    or cls._USER_CTX_MY_RE.search(content)
                ):
                    continue
                snippet = content.replace("\n", " ").strip()
                if len(snippet) > cls._USER_CTX_TRUNCATE:
                    snippet = snippet[: cls._USER_CTX_TRUNCATE - 1].rstrip() + "…"
                if snippet in seen:
                    continue
                seen.add(snippet)
                bullets.append(snippet)
                if len(bullets) >= cls._USER_CTX_MAX_BULLETS:
                    return bullets
        return bullets

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
        # Top-of-card "today" anchor (LongMemEval question_date) so the
        # answerer has an absolute reference for "how many days ago" arithmetic;
        # see mind/research/timestamp-grounding-design-2026-05-25.md.
        self._self_card_path.parent.mkdir(parents=True, exist_ok=True)
        card_lines: list[str] = [f"# Peer card — self", ""]
        if item.question_date:
            card_lines += [f"**Today's date:** {item.question_date}", ""]
        # ADR 0138 — surface preference-bearing user turns above the
        # verbatim transcript so the answerer engages with them before
        # skimming ## History. Omitted when the heuristic finds nothing.
        user_ctx = self._extract_user_context(item)
        if user_ctx:
            card_lines.append("## User context")
            card_lines.append("")
            for bullet in user_ctx:
                card_lines.append(f"- {bullet}")
            card_lines.append("")
        card_lines += ["## History", ""]
        for i, session in enumerate(item.history):
            card_lines.append(f"### Session {i}")
            if i < len(item.session_dates) and item.session_dates[i]:
                card_lines.append(f"**Session date:** {item.session_dates[i]}")
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
            if i < len(item.session_dates) and item.session_dates[i]:
                lines += [f"**Session date:** {item.session_dates[i]}", ""]
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

    def answer(
        self,
        item: LongMemEvalItem,
        *,
        answer_fn: "AnswerFn | None" = None,
    ) -> AnswerResult:
        """Produce an :class:`AnswerResult` for ``item``.

        The adapter always assembles the dialectic prompt from the
        ingested history (ADR 0133 grounding pipeline). When
        ``answer_fn`` is ``None`` (default), the assembled prompt is
        returned as ``answer`` and the upstream grader can't run on
        the result — ADR 0135's cost-containment default.

        When ``answer_fn`` is provided, the adapter calls it once with
        the assembled prompt; the returned string lands in both
        ``answer`` and ``hypothesis``. This produces a row the upstream
        ``src/evaluation/evaluate_qa.py`` grader can consume directly.

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

            hypothesis: str | None = None
            answer_text = prompt
            if answer_fn is not None:
                hypothesis = answer_fn(prompt)
                answer_text = hypothesis

            return AnswerResult(
                item_id=item.item_id,
                question=item.question,
                answer=answer_text,
                sources_used=list(ctx.sources_used),
                category=item.category,
                expected_answer=item.expected_answer,
                hypothesis=hypothesis,
                question_id=item.item_id if hypothesis is not None else None,
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
    """Read LongMemEval items from JSONL or a JSON array.

    The upstream HuggingFace release ships a single JSON array
    (`longmemeval_oracle.json`); operator-generated subsets are often
    JSONL. Detect which by trying JSON first (cheap; either succeeds
    on the array or raises on the first JSONL line) then falling
    back to per-line parsing. Malformed JSONL lines are skipped.
    """
    p = Path(path)
    if not p.exists():
        return []
    text = p.read_text(encoding="utf-8")
    # Try JSON-array first.
    try:
        arr = json.loads(text)
        if isinstance(arr, list):
            return [
                LongMemEvalItem.from_dict(obj)
                for obj in arr
                if isinstance(obj, dict)
            ]
    except json.JSONDecodeError:
        pass
    # Fall back to JSONL.
    out: list[LongMemEvalItem] = []
    for line in text.splitlines():
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
    answer_fn: "AnswerFn | None" = None,
    per_category_limit: int | None = None,
) -> list[AnswerResult]:
    """Iterate ``items`` through ``adapter``; reset between items.

    Filters:
      * ``subset`` — case-insensitive substring match on ``category``.
      * ``limit`` — overall cap after the subset filter.
      * ``per_category_limit`` — independent cap per category. Useful
        for "smoke" runs that want N items per category for an even
        spread (e.g. ``--n-per-category 5``).
      * ``answer_fn`` — when provided, threaded through into
        :meth:`LongMemEvalAdapter.answer` so each result gets a real
        hypothesis the upstream grader can judge.
    """
    results: list[AnswerResult] = []
    sub = subset.lower() if subset else None
    per_cat_counts: dict[str, int] = {}
    n = 0
    for item in items:
        if sub is not None and sub not in item.category.lower():
            continue
        if per_category_limit is not None:
            cat = item.category or "(uncategorised)"
            if per_cat_counts.get(cat, 0) >= int(per_category_limit):
                continue
            per_cat_counts[cat] = per_cat_counts.get(cat, 0) + 1
        if limit is not None and n >= int(limit):
            break
        adapter.reset()
        adapter.ingest_history(item)
        results.append(adapter.answer(item, answer_fn=answer_fn))
        n += 1
    adapter.reset()
    return results


# ── Graded-result summariser (operator runbook helper) ───────────


def summarize_results(
    graded_jsonl_path: Path,
    *,
    correctness_field: str = "is_correct",
) -> dict[str, dict[str, float | int]]:
    """Aggregate a graded LongMemEval JSONL into per-category accuracy.

    The upstream grader (or any local grading pass) is expected to
    annotate each row with a boolean ``is_correct`` field. This
    helper reads the JSONL and produces:

      {category: {"total": N, "correct": N, "accuracy": float},
       "_overall": {"total": N, "correct": N, "accuracy": float}}

    Items missing the correctness field are counted under
    ``total`` but not ``correct`` — they pull the accuracy down,
    which is the honest signal (an ungraded item is not a correct
    item). Malformed JSONL lines are skipped, matching :func:`load_items`.

    The function is intentionally provider-agnostic and grader-
    agnostic — pass any flag-field name via ``correctness_field``
    if the upstream harness uses a different key (e.g.
    ``"correct"``, ``"judged_correct"``).
    """
    p = Path(graded_jsonl_path)
    if not p.exists():
        return {}
    by_cat: dict[str, dict[str, int]] = {}
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
        cat = str(obj.get("category") or "(uncategorised)")
        bucket = by_cat.setdefault(cat, {"total": 0, "correct": 0})
        bucket["total"] += 1
        if bool(obj.get(correctness_field, False)):
            bucket["correct"] += 1

    out: dict[str, dict[str, float | int]] = {}
    overall_total = 0
    overall_correct = 0
    for cat, b in sorted(by_cat.items()):
        out[cat] = {
            "total": b["total"],
            "correct": b["correct"],
            "accuracy": (
                round(b["correct"] / b["total"], 4) if b["total"] else 0.0
            ),
        }
        overall_total += b["total"]
        overall_correct += b["correct"]
    out["_overall"] = {
        "total": overall_total,
        "correct": overall_correct,
        "accuracy": (
            round(overall_correct / overall_total, 4) if overall_total else 0.0
        ),
    }
    return out


def format_summary_table(summary: dict[str, dict[str, float | int]]) -> str:
    """Render :func:`summarize_results` output as a markdown table.

    Suitable for pasting into ``mind/research/longmemeval-baseline-*.md``.
    The ``_overall`` row is rendered last with a separator.
    """
    if not summary:
        return "_(no results)_\n"
    lines = [
        "| Category | Total | Correct | Accuracy |",
        "|---|---:|---:|---:|",
    ]
    overall = summary.get("_overall")
    for cat, row in summary.items():
        if cat == "_overall":
            continue
        lines.append(
            f"| {cat} | {row['total']} | {row['correct']} | "
            f"{row['accuracy']:.2%} |"
        )
    if overall is not None:
        lines.append("| | | | |")
        lines.append(
            f"| **overall** | **{overall['total']}** | "
            f"**{overall['correct']}** | **{overall['accuracy']:.2%}** |"
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "AnswerFn",
    "AnswerResult",
    "LongMemEvalAdapter",
    "LongMemEvalItem",
    "default_results_path",
    "format_summary_table",
    "load_items",
    "run_batch",
    "summarize_results",
    "write_results",
]
