"""CuriosityEngine — midday research with web tools.

Per Reggio: at midday Chimera picks a topic worth investigating, runs a
short research loop with ``web_search`` + ``http_fetch``, and writes the
findings to ``mind/wiki/projects/q{NNN}/`` plus a CHRONICLE pointer.

For MVP simplicity, question formulation and research happen in a single
ActExecutor run with a tool allow-list of {web_search, http_fetch}. The
separate "Opus formulates → Sonnet researches" split is a v1.2 nicety.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

from ..providers import Provider
from ..providers.tiers import Provider as ProviderKind
from ..tools import DispatchContext, Dispatcher, ToolRegistry
from .base import EngineBase, EngineResult
from .chronicle import ChronicleManager

logger = logging.getLogger(__name__)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, *, max_len: int = 48) -> str:
    """Lowercase, alphanumeric-with-dashes slug."""
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return (s[:max_len] or "untitled").rstrip("-")


def _next_question_dir(projects_root: Path) -> tuple[int, Path]:
    """Allocate the next ``q{NNN}-<slug>`` index under projects_root.

    Returns (number, path-with-slug-suffix-blank). Caller appends the
    slug after the question is generated.
    """
    projects_root.mkdir(parents=True, exist_ok=True)
    existing = [p.name for p in projects_root.iterdir() if p.is_dir()]
    nums = [
        int(m.group(1))
        for m in (re.match(r"^q(\d+)", n) for n in existing)
        if m is not None
    ]
    return (max(nums, default=0) + 1), projects_root


class CuriosityEngine(EngineBase):
    name = "curiosity"

    def __init__(
        self,
        *,
        providers: dict[ProviderKind, Provider],
        db: sqlite3.Connection,
        registry: ToolRegistry,
        mind_dir: Path,
        chronicle: ChronicleManager,
        tier: str = "sonnet",
        max_rounds: int = 6,
        seed_topic: str | None = None,
    ) -> None:
        self._providers = providers
        self._db = db
        self._registry = registry
        self._mind_dir = Path(mind_dir)
        self._chronicle = chronicle
        self._tier = tier
        self._max_rounds = max_rounds
        self._seed_topic = seed_topic

    async def run(self, *, cycle: int) -> EngineResult:
        from ..core.act import ActExecutor
        from ..core.mind import utc_now_iso
        from ..memory import finish_engine_run, start_engine_run

        # v4.69 (ADR 0088 §P1): unified engine_runs row wraps the whole
        # firing. Curiosity calls ActExecutor internally, so the
        # api_calls themselves get caller="act" — we report the
        # nested-call count from result.api_call_count below. Exact
        # ACT-vs-engine attribution for those calls is a documented
        # gap (ADR 0088 §"Non-goals").
        run_id = start_engine_run(self._db, engine=self.name, cycle=cycle)

        seed = self._seed_topic or self._derive_seed_from_chronicle()
        brief = (
            f"Investigate this topic and write a brief findings note (200-400 words).\n\n"
            f"Topic: {seed}\n\n"
            "Use web_search to find 2-3 reputable sources. Use http_fetch to read at most "
            "one of them if a snippet isn't enough. Synthesise: what's interesting, what's "
            "the state of the art, what is the most surprising thing you found.\n"
            "Cite URLs inline. Be specific. No filler."
        )

        # Allocate next q dir.
        q_num, projects_root = _next_question_dir(
            self._mind_dir / "wiki" / "projects"
        )
        q_dir = projects_root / f"q{q_num:03d}-{_slug(seed)}"
        q_dir.mkdir(parents=True, exist_ok=True)
        (q_dir / "question.md").write_text(
            f"# Question q{q_num:03d}\n\n{seed}\n", encoding="utf-8"
        )

        # Restrict the sub-loop's tool surface to web tools only.
        executor = ActExecutor(
            dispatcher=Dispatcher(self._registry),
            providers=self._providers,
            db=self._db,
            tier=self._tier,
            max_rounds=self._max_rounds,
            max_tokens=2048,
        )
        result = await executor.execute(
            brief,
            cycle=cycle,
            context=DispatchContext(
                allow=frozenset({"web_search", "http_fetch"}),
            ),
        )

        notes_path = q_dir / "notes.md"
        notes_path.write_text(
            f"# Notes — q{q_num:03d}\n\n"
            f"*Topic:* {seed}\n\n"
            f"*Cycle:* {cycle}\n\n"
            f"## Findings\n\n{result.final_text or '(no text returned)'}\n",
            encoding="utf-8",
        )

        snippet = (result.final_text or "")[:400]
        rel = q_dir.relative_to(self._mind_dir)
        body = (
            f"Investigated: **{seed}**\n\n"
            f"See [{rel}/notes.md](wiki/projects/{q_dir.name}/notes.md)\n\n"
            f"Snippet:\n\n{snippet}{'…' if len(result.final_text or '') > 400 else ''}"
        )
        self._chronicle.upsert_section(section_name="Midday Curiosity", body=body)

        # v4.69: close the engine_runs row. Status reflects whether
        # the underlying ACT call completed; failure_reason is
        # propagated from result.failure_reason.
        status = "success" if result.completed else "failed"
        finish_engine_run(
            self._db, run_id,
            status=status,
            skip_reason=result.failure_reason,
            api_calls=result.api_call_count,
            chronicle_added=len(body.splitlines()),
            summary=f"q{q_num:03d}: {seed[:160]}",
        )
        return EngineResult(
            engine=self.name,
            skipped=False,
            fired_at=utc_now_iso(),
            artifacts=[str(q_dir / "question.md"), str(notes_path), str(self._chronicle.path)],
            api_call_count=result.api_call_count,
            summary=f"q{q_num:03d}: {seed[:120]}",
            failure_reason=result.failure_reason,
        )

    # ── seed derivation ────────────────────────────────

    def _derive_seed_from_chronicle(self) -> str:
        """Pull a topic from today's Morning Discovery, falling back to a default."""
        today = self._chronicle.day_section()
        # Look for "Morning Discovery" body, pick first bullet.
        m = re.search(r"### Morning Discovery\s*\n(.*?)(?=\n### |\n## |\Z)", today, re.DOTALL)
        if m:
            for line in m.group(1).splitlines():
                line = line.strip()
                if line.startswith("- ") and len(line) > 5:
                    return line[2:].strip()
        return (
            "How are multi-LLM agent frameworks evolving in 2026? What patterns are emerging "
            "around tool-policy gating and behavioural drift?"
        )
