"""LoCoMo adapter — Chimera's second evaluation surface (ADR 0144).

Where LongMemEval (ADR 0135) gives us a curated user/assistant
single-actor benchmark, LoCoMo (snap-research/locomo, ACL 2024) gives
us 10 simulated peer-to-peer conversations averaging ~28 sessions
each, with ~1,986 QA pairs across five categories (single-hop,
multi-hop, temporal, open-domain, adversarial).

The two together let us tell apart "Chimera-the-dialectic is robust"
from "Chimera-overfits-to-LongMemEval-shape." See the locked-design
note ``mind/research/locomo-design-2026-05-26.md``.

This module mirrors :mod:`chimera.evals.longmemeval` 1:1 in API and
behaviour. The key shape delta: one LoCoMo conversation (``sample_id``)
produces many QA items, all sharing identical history. The adapter
detects this and **caches ingest** across sibling QAs so we don't
rewrite ~30 sessions × ~100 markdown files per conversation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .hybrid_retrieval import EmbedFn, select_top_k_sessions


logger = logging.getLogger(__name__)


AnswerFn = Callable[[str], str]


# ── Category taxonomy ────────────────────────────────────────────

# Upstream uses integer category labels 1..5. We canonicalise to
# strings so the grader and summariser can share prompt templates with
# LongMemEval (whose categories are already string-named). See the
# locked-design note §"Question categories" for the mapping rationale.

CATEGORY_INT_TO_LABEL: dict[int, str] = {
    1: "single-hop",
    2: "multi-hop",
    3: "temporal-reasoning",
    4: "open-domain",
    5: "adversarial",
}

CATEGORY_LABEL_TO_INT: dict[str, int] = {
    v: k for k, v in CATEGORY_INT_TO_LABEL.items()
}


def canonical_category(category_int: int | str) -> str:
    """Map an upstream category (int 1..5 or already-canonical string)
    to the canonical adapter label. Unknown values become
    ``"(uncategorised)"`` rather than raising — we never want a single
    bad item to kill a sweep.
    """
    if isinstance(category_int, str):
        if category_int in CATEGORY_LABEL_TO_INT:
            return category_int
        try:
            return CATEGORY_INT_TO_LABEL.get(int(category_int), "(uncategorised)")
        except (TypeError, ValueError):
            return "(uncategorised)"
    if isinstance(category_int, int):
        return CATEGORY_INT_TO_LABEL.get(category_int, "(uncategorised)")
    return "(uncategorised)"


# ── Typed schema ──────────────────────────────────────────────────


@dataclass(frozen=True)
class LoCoMoItem:
    """One question pulled out of one LoCoMo conversation.

    Field names mirror the relevant subset of upstream
    ``data/locomo10.json`` shape. ``sessions`` is the flattened
    list-of-turn-lists derived from ``conversation.session_<N>`` keys
    in chronological order; ``session_dates`` is the matching
    list of ``session_<N>_date_time`` strings.

    ``category`` is the canonical string label (single-hop, multi-hop,
    temporal-reasoning, open-domain, adversarial); ``category_int`` is
    the original 1..5 for upstream parity.
    """

    item_id: str
    question: str
    answer: str
    category: str
    category_int: int
    evidence: list[str] = field(default_factory=list)
    sessions: list[list[dict[str, str]]] = field(default_factory=list)
    session_dates: list[str] = field(default_factory=list)
    speaker_a: str = ""
    speaker_b: str = ""
    sample_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def question_date(self) -> str:
        """Latest session's date_time, used as the "today" anchor."""
        for d in reversed(self.session_dates):
            if d:
                return d
        return ""


@dataclass(frozen=True)
class AnswerResult:
    """One adapter answer + provenance, JSON-serialisable.

    Mirrors :class:`chimera.evals.longmemeval.AnswerResult` so the
    grader and summariser can be shared down the road.
    """

    item_id: str
    question: str
    answer: str
    sources_used: list[str]
    category: str = ""
    expected_answer: str = ""
    sample_id: str = ""
    error: str | None = None
    hypothesis: str | None = None
    question_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── Conversation → items ingestion ────────────────────────────────


def _flatten_conversation(conv: dict[str, Any]) -> tuple[
    list[list[dict[str, str]]], list[str]
]:
    """Pull session_<N> + session_<N>_date_time out of a LoCoMo
    ``conversation`` dict in chronological order.

    Returns ``(sessions, session_dates)`` where ``sessions`` is a list
    of per-session turn-dict lists with normalised ``{role, speaker,
    content}`` keys, and ``session_dates`` is a parallel list of
    date_time strings.
    """
    speaker_a = str(conv.get("speaker_a") or "")
    speaker_b = str(conv.get("speaker_b") or "")
    # Find every session_<int> key, sorted numerically.
    session_keys: list[tuple[int, str]] = []
    for key in conv:
        if not key.startswith("session_"):
            continue
        # Skip session_<N>_date_time / _summary / _observation suffixes.
        tail = key[len("session_"):]
        if "_" in tail:
            continue
        try:
            n = int(tail)
        except ValueError:
            continue
        session_keys.append((n, key))
    session_keys.sort()

    sessions: list[list[dict[str, str]]] = []
    dates: list[str] = []
    for _, key in session_keys:
        raw = conv.get(key) or []
        date = str(conv.get(f"{key}_date_time") or "")
        turns: list[dict[str, str]] = []
        for turn in raw:
            if not isinstance(turn, dict):
                continue
            speaker = str(turn.get("speaker") or "")
            text = str(turn.get("text") or "").strip()
            if not text:
                continue
            # Map peer-to-peer speakers onto user/assistant so the
            # existing dialectic prompt machinery ingests cleanly. The
            # speaker's real name is preserved in the "speaker" field
            # and emitted by ingest_history() so the answerer can refer
            # to them by name.
            if speaker == speaker_a:
                role = "user"
            elif speaker == speaker_b:
                role = "assistant"
            else:
                role = "user"
            turns.append({"role": role, "speaker": speaker, "content": text})
        sessions.append(turns)
        dates.append(date)
    return sessions, dates


def items_from_sample(sample: dict[str, Any]) -> list[LoCoMoItem]:
    """Expand one upstream ``locomo10.json`` sample into a list of items.

    The sample's QA list is the unit of iteration; the conversation
    history is shared by reference across every item from the same
    sample. The adapter's ingest cache (see :class:`LoCoMoAdapter`) is
    what avoids re-writing markdown across sibling QAs.
    """
    sample_id = str(sample.get("sample_id") or "")
    conv = sample.get("conversation") or {}
    speaker_a = str(conv.get("speaker_a") or "")
    speaker_b = str(conv.get("speaker_b") or "")
    sessions, dates = _flatten_conversation(conv)
    qa_list = sample.get("qa") or []
    out: list[LoCoMoItem] = []
    for idx, qa in enumerate(qa_list):
        if not isinstance(qa, dict):
            continue
        cat_raw = qa.get("category")
        try:
            cat_int = int(cat_raw) if cat_raw is not None else 0
        except (TypeError, ValueError):
            cat_int = 0
        out.append(LoCoMoItem(
            item_id=f"{sample_id}::qa{idx}",
            question=str(qa.get("question") or ""),
            answer=str(qa.get("answer") if qa.get("answer") is not None else ""),
            category=canonical_category(cat_int),
            category_int=cat_int,
            evidence=[str(e) for e in (qa.get("evidence") or [])],
            sessions=sessions,
            session_dates=dates,
            speaker_a=speaker_a,
            speaker_b=speaker_b,
            sample_id=sample_id,
            extra={k: v for k, v in qa.items()
                   if k not in {"question", "answer", "category", "evidence"}},
        ))
    return out


def load_items(path: Path) -> list[LoCoMoItem]:
    """Read ``locomo10.json`` (a JSON array of conversations) and
    expand to a flat list of per-QA items.

    Returns ``[]`` if the file does not exist, matching
    :func:`chimera.evals.longmemeval.load_items`.
    """
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[LoCoMoItem] = []
    for sample in data:
        if isinstance(sample, dict):
            out.extend(items_from_sample(sample))
    return out


# ── Adapter ───────────────────────────────────────────────────────


class LoCoMoAdapter:
    """Bulk-ingest LoCoMo conversation then answer a question.

    Shape mirrors :class:`chimera.evals.longmemeval.LongMemEvalAdapter`.
    Two differences:

    * **Ingest cache by sample_id**: sibling QAs from the same
      conversation share identical history. We track the
      most-recently-ingested ``sample_id`` and skip re-ingest when the
      next item matches.
    * **Speaker preservation**: the synthetic peer card surfaces the
      real speaker names (Caroline/Melanie/…) so the answerer can
      refer to them in the answer string (the gold answers do).

    Parameters
    ----------
    mind_dir:
        Scratch ``mind/`` to populate.
    ingest_subdir:
        Subdirectory under ``mind/wiki/`` for session markdown.
        Defaults to ``"locomo"``.
    hybrid_retrieval / retrieval_top_k / embed_fn:
        Pass-through to :mod:`chimera.evals.hybrid_retrieval`, same
        semantics as the LongMemEval adapter (ADR 0142). Default off;
        because LoCoMo conversations are uniformly long (19–32 sessions),
        every item is above the default top-k threshold, so this flag is
        meaningful from day one.
    """

    def __init__(
        self,
        *,
        mind_dir: Path,
        ingest_subdir: str = "locomo",
        hybrid_retrieval: bool = False,
        retrieval_top_k: int = 8,
        embed_fn: "EmbedFn | None" = None,
    ) -> None:
        self._mind_dir = Path(mind_dir)
        self._ingest_subdir = ingest_subdir
        self._scratch_dir = self._mind_dir / "wiki" / ingest_subdir
        self._self_card_path = self._mind_dir / "peers" / "self.md"
        self._hybrid_retrieval = bool(hybrid_retrieval)
        self._retrieval_top_k = int(retrieval_top_k)
        self._embed_fn = embed_fn
        self._embed_cache: dict[str, list[float]] = {}
        # Tracks (sample_id, hybrid_retrieval_indexes_key) so reset() is
        # a no-op for sibling QAs of the same conversation.
        self._last_ingest_key: tuple[str, str] | None = None

    # ── ingest / reset ─────────────────────────────────────

    def reset(self, *, force: bool = False) -> None:
        """Truncate scratch dir + remove the synthetic self card.

        When ``force=False`` (the default), reset is a no-op so the
        next ``ingest_history`` call can decide whether the cached
        ingest is reusable. The CLI batch runner forces a reset
        between distinct conversations.
        """
        if not force:
            return
        if self._scratch_dir.exists():
            for child in self._scratch_dir.iterdir():
                if child.is_file():
                    child.unlink()
        if self._self_card_path.exists():
            self._self_card_path.unlink()
        self._last_ingest_key = None

    def _ingest_key_for(self, item: LoCoMoItem) -> tuple[str, str]:
        """Cache key — distinguishes (a) different conversations and
        (b) the same conversation seen under different
        hybrid-retrieval session selections (which depend on the
        question text).
        """
        if not self._hybrid_retrieval:
            return (item.sample_id, "full")
        # Question-text-dependent selection — re-ingest per question.
        return (item.sample_id, f"hybrid:{hash(item.question):016x}")

    def ingest_history(self, item: LoCoMoItem) -> int:
        """Write the synthetic self-card + per-session scratch markdown.

        Idempotent for sibling QAs from the same sample (cached by
        ``sample_id``). Returns the number of session files written
        this call — 0 when the cached ingest was reused.
        """
        key = self._ingest_key_for(item)
        if self._last_ingest_key == key:
            return 0

        # New conversation (or new retrieval selection) — full reset.
        if self._scratch_dir.exists():
            for child in self._scratch_dir.iterdir():
                if child.is_file():
                    child.unlink()
        if self._self_card_path.exists():
            self._self_card_path.unlink()

        # Synthetic self card — load-bearing surface for the dialectic API.
        self._self_card_path.parent.mkdir(parents=True, exist_ok=True)
        card_lines: list[str] = [
            f"# Peer card — self",
            "",
            f"**Conversation:** {item.sample_id} "
            f"(speakers: {item.speaker_a} and {item.speaker_b})",
            "",
        ]
        if item.question_date:
            card_lines += [f"**Today's date:** {item.question_date}", ""]
        card_lines += ["## History", ""]

        selected_indexes = self._select_session_indexes(item)
        for i in selected_indexes:
            session = item.sessions[i]
            card_lines.append(f"### Session {i + 1}")
            if i < len(item.session_dates) and item.session_dates[i]:
                card_lines.append(f"**Session date:** {item.session_dates[i]}")
            for turn in session:
                speaker = str(turn.get("speaker") or turn.get("role", "user"))
                content = str(turn.get("content", "")).strip()
                if not content:
                    continue
                card_lines.append(f"- **{speaker}**: {content}")
            card_lines.append("")
        self._self_card_path.write_text(
            "\n".join(card_lines).rstrip() + "\n", encoding="utf-8",
        )

        # Per-session scratch for future hybrid-search.
        self._scratch_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for i, session in enumerate(item.sessions):
            path = self._scratch_dir / f"{item.sample_id}-s{i:03d}.md"
            lines = [f"# Session {i + 1} — {item.sample_id}", ""]
            if i < len(item.session_dates) and item.session_dates[i]:
                lines += [f"**Session date:** {item.session_dates[i]}", ""]
            for turn in session:
                speaker = str(turn.get("speaker") or turn.get("role", "user"))
                content = str(turn.get("content", "")).strip()
                if not content:
                    continue
                lines.append(f"**{speaker}**: {content}")
                lines.append("")
            path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
            count += 1

        self._last_ingest_key = key
        return count

    # ── retrieval ──────────────────────────────────────────

    def _select_session_indexes(self, item: LoCoMoItem) -> list[int]:
        """Pick which session indexes go into the self-card.

        Default (``hybrid_retrieval=False``): every session, original
        order — matches upstream paper's full-context evaluation.

        Hybrid retrieval (``hybrid_retrieval=True``): BM25 + dense
        fused via RRF, identical to the LongMemEval path (ADR 0142).
        """
        n = len(item.sessions)
        if not self._hybrid_retrieval:
            return list(range(n))
        if n <= self._retrieval_top_k:
            return list(range(n))
        session_texts = [_session_to_text(s) for s in item.sessions]
        return select_top_k_sessions(
            session_texts,
            item.question,
            top_k=self._retrieval_top_k,
            embed_fn=self._embed_fn,
            embed_cache=self._embed_cache,
        )

    # ── answer ─────────────────────────────────────────────

    def answer(
        self,
        item: LoCoMoItem,
        *,
        answer_fn: "AnswerFn | None" = None,
    ) -> AnswerResult:
        """Produce an :class:`AnswerResult` for ``item``.

        Same contract as :meth:`LongMemEvalAdapter.answer`: assemble
        prompt via dialectic API, optionally pipe through ``answer_fn``,
        capture errors into :attr:`AnswerResult.error` rather than
        raising.
        """
        try:
            from ..a2a.dialectic import (
                build_dialectic_prompt,
                gather_dialectic_context,
            )

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
                expected_answer=item.answer,
                sample_id=item.sample_id,
                hypothesis=hypothesis,
                question_id=item.item_id if hypothesis is not None else None,
            )
        except Exception as exc:  # noqa: BLE001 — never fail a sweep
            logger.warning(
                "locomo: adapter failed on %s: %s",
                item.item_id or "?", exc,
            )
            return AnswerResult(
                item_id=item.item_id,
                question=item.question,
                answer="",
                sources_used=[],
                category=item.category,
                expected_answer=item.answer,
                sample_id=item.sample_id,
                error=str(exc),
            )


def _session_to_text(session: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for turn in session:
        speaker = str(turn.get("speaker") or turn.get("role", "user"))
        content = str(turn.get("content", "")).strip()
        if content:
            parts.append(f"{speaker}: {content}")
    return "\n".join(parts)


# ── JSONL I/O ─────────────────────────────────────────────────────


def default_results_path(mind_dir: Path) -> Path:
    """``mind/evals/locomo-<ts>.jsonl``."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path(mind_dir) / "evals" / f"locomo-{ts}.jsonl"


def write_results(results: Iterable[AnswerResult], path: Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")
    return p


# ── Batch runner ──────────────────────────────────────────────────


def run_batch(
    adapter: LoCoMoAdapter,
    items: Iterable[LoCoMoItem],
    *,
    limit: int | None = None,
    subset: str | None = None,
    sample_id: str | None = None,
    answer_fn: "AnswerFn | None" = None,
    per_category_limit: int | None = None,
) -> list[AnswerResult]:
    """Iterate ``items`` through ``adapter`` with per-conversation ingest cache.

    Filters:
      * ``subset`` — case-insensitive substring match on ``category``.
      * ``sample_id`` — case-insensitive substring match on the
        conversation id (lets the operator scope a spike to a single
        conversation for inspection).
      * ``limit`` — overall cap after filters.
      * ``per_category_limit`` — independent cap per category.
      * ``answer_fn`` — threaded into :meth:`LoCoMoAdapter.answer`.
    """
    results: list[AnswerResult] = []
    sub = subset.lower() if subset else None
    samp = sample_id.lower() if sample_id else None
    per_cat_counts: dict[str, int] = {}
    n = 0
    for item in items:
        if sub is not None and sub not in item.category.lower():
            continue
        if samp is not None and samp not in item.sample_id.lower():
            continue
        if per_category_limit is not None:
            cat = item.category or "(uncategorised)"
            if per_cat_counts.get(cat, 0) >= int(per_category_limit):
                continue
            per_cat_counts[cat] = per_cat_counts.get(cat, 0) + 1
        if limit is not None and n >= int(limit):
            break
        # ingest_history is idempotent per sample_id — sibling QAs are cheap.
        adapter.ingest_history(item)
        results.append(adapter.answer(item, answer_fn=answer_fn))
        n += 1
    adapter.reset(force=True)
    return results


# ── Graded-result summariser ──────────────────────────────────────


def summarize_results(
    graded_jsonl_path: Path,
    *,
    correctness_field: str = "is_correct",
) -> dict[str, dict[str, float | int]]:
    """Aggregate a graded LoCoMo JSONL into per-category accuracy.

    Identical shape to :func:`chimera.evals.longmemeval.summarize_results`
    so downstream tooling (e.g. baseline notes) can render either with
    the same helper.
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
    """Render :func:`summarize_results` output as a markdown table."""
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
    "CATEGORY_INT_TO_LABEL",
    "CATEGORY_LABEL_TO_INT",
    "LoCoMoAdapter",
    "LoCoMoItem",
    "canonical_category",
    "default_results_path",
    "format_summary_table",
    "items_from_sample",
    "load_items",
    "run_batch",
    "summarize_results",
    "write_results",
]
