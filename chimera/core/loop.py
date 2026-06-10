"""8-phase Chimera loop.

Per ADR 0003: HOUSEKEEPING → WAKE → ASSESS → PLAN → ACT → WRITE →
FLUSH → COMMIT → ROTATE. MVP scope per the ADR's phase-by-phase table:
WAKE/ASSESS/WRITE/ROTATE carry real behaviour; the rest are stubs.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..engines import (
    ChronicleManager,
    CuriosityEngine,
    DiscoveryEngine,
    EngineScheduler,
    ReflectionEngine,
)
from ..drift import (
    DriftAction,
    DriftConfig,
    DriftDecision,
    DriftDetector,
    DriftSignal,
    Outcome,
    detect_stagnation,
    respond as drift_respond,
)
from ..memory import (
    EntityRecord,
    ensure_current_plan,
    open_and_init,
    record_activity,
    transition_entity,
)
from ..skills import load_dynamic_skills
from ..trust import TrustManager, TrustTier
from ..tools import (
    SubAgentRunner,
    ToolRegistry,
    default_registry,
    register_core_tools,
    register_mcp_servers_from_env,
    register_sub_agent_tool,
)
from . import mind
from .act import ActExecutor, ActResult
from .budget import reasoning_tier_from_env
from .soak_ledger import record_act_tools
from .strategy import Planner

logger = logging.getLogger(__name__)


_ACT_BUDGET_DEFAULT_SECONDS = 240.0

_PLAN_MAX_OPEN_TASKS_DEFAULT = 12


def _plan_max_open_tasks() -> int:
    """Backlog ceiling above which the PLAN-phase planner is skipped.

    v40′ scope-creep fix (B1): the every-Nth Opus planner emits 0..3
    proposals per cycle with no awareness of how deep the backlog already
    is. Over a long run those accumulate — the v40′ soak grew a locked
    2-task charter into 58 open tasks (release-management fantasy) across
    110 cycles. When the open-task count is already >= this cap, PLAN
    skips proposal generation (engines still run) so the planner stops
    piling onto an unworked backlog. Reads ``CHIMERA_PLAN_MAX_OPEN_TASKS``
    (default 12); <=0 or unparseable falls back to the default.
    """
    raw = os.environ.get("CHIMERA_PLAN_MAX_OPEN_TASKS")
    if raw is None:
        return _PLAN_MAX_OPEN_TASKS_DEFAULT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _PLAN_MAX_OPEN_TASKS_DEFAULT
    return value if value > 0 else _PLAN_MAX_OPEN_TASKS_DEFAULT


def _proposals_suppressed() -> bool:
    """True when PLAN must emit NO new proposals (planner + engines) this cycle.

    R5 (ADR 0151 / mechanism C). Distinct from ``CHIMERA_ENGINES_ENABLED=0``,
    which ALSO blocks ``git commit`` at the shell chokepoint (the phase-1
    investigation-only gate) — so it cannot be used for a commit-only phase.
    This knob suppresses proposal GENERATION only, leaving
    ``CHIMERA_ENGINES_ENABLED=1`` (commits allowed) and the operator INBOX
    tasks (the commit task) to run.

    The v46 re-soak #2 showed why: with the commit stuck, the discovery/
    curiosity/reflection engines filled the void with governance busywork
    ("build a pre-commit hook", "document the convention") that out-competed
    the bare commit imperative (mechanism C). In a commit-only phase there is
    nothing to propose — only the deliverable to commit. Default OFF.
    """
    return os.environ.get("CHIMERA_SUPPRESS_PROPOSALS", "0").strip() not in {
        "0", "", "false", "False", "no", "off",
    }


def _act_budget_seconds() -> float:
    """Hard ceiling for the ACT phase in seconds (v35 postmortem ladder #4).

    Reads ``CHIMERA_ACT_BUDGET_SECONDS``; defaults to 240s. The ACT phase
    is cancelled via ``asyncio.CancelledError`` at this threshold and the
    loop advances to WRITE with whatever partial results landed. The 600s
    silent-death watchdog (ADR 0120) remains the outer ceiling.
    """
    raw = os.environ.get("CHIMERA_ACT_BUDGET_SECONDS")
    if raw is None:
        return _ACT_BUDGET_DEFAULT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _ACT_BUDGET_DEFAULT_SECONDS
    if value <= 0:
        return _ACT_BUDGET_DEFAULT_SECONDS
    return value


def graph_projection_enabled() -> bool:
    """v4.62 (ADR 0081): is the Kuzu graph projection turned on?

    The graph is OPTIONAL as of v4.62. Default: OFF. Opt in by setting
    ``CHIMERA_GRAPH_ENABLED=1`` (or ``true`` / ``yes``). The legacy
    ``CHIMERA_AUTO_GRAPH_UPDATE_DISABLED=1`` still forces off even when
    the new var is enabled — back-compat for operators who pinned the
    legacy var to disable updates back when they were default-on.

    The CLI verbs (``chimera graph init/rebuild/query/snapshot``) are
    always available regardless — they're explicit operator invocations.
    This gate only controls the auto-refresh in the housekeeping phase.
    """
    enabled = os.environ.get("CHIMERA_GRAPH_ENABLED", "").lower() in (
        "1", "true", "yes",
    )
    forced_off = os.environ.get(
        "CHIMERA_AUTO_GRAPH_UPDATE_DISABLED", ""
    ).lower() in ("1", "true", "yes")
    return enabled and not forced_off


@dataclass
class LoopConfig:
    mind_dir: Path
    state_dir: Path
    heartbeat_interval_seconds: int = 900   # 15 min (Reggio default)
    opus_plan_every_n_cycles: int = 4
    max_session_hours: int = 12

    @classmethod
    def from_env(cls) -> LoopConfig:
        return cls(
            mind_dir=Path(os.environ.get("CHIMERA_MIND_DIR", "mind")),
            state_dir=Path(os.environ.get("CHIMERA_STATE_DIR", "state")),
            heartbeat_interval_seconds=int(
                os.environ.get("CHIMERA_CYCLE_SECONDS", "900")
            ),
            opus_plan_every_n_cycles=int(
                os.environ.get("CHIMERA_OPUS_PLAN_EVERY_N", "4")
            ),
            max_session_hours=int(os.environ.get("CHIMERA_SESSION_MAX_HOURS", "12")),
        )


@dataclass
class CycleReport:
    """Per-cycle observable outcome — used by tests and the CLI."""

    cycle: int
    started_at: str
    completed_at: str
    tasks_seen: int
    tasks_completed: int
    rotated: bool = False
    phase_log: list[str] = field(default_factory=list)
    drift_decision: DriftDecision | None = None
    pending_nudge: str | None = None
    plan_demoted: bool = False
    current_plan_state: str | None = None
    proposals_added: int = 0
    engine_fired: str | None = None
    engine_summary: str | None = None
    trust_tier_before: str | None = None
    trust_tier_after: str | None = None
    trust_autopromoted: bool = False
    trust_locked_down: bool = False
    phase_times_ms: dict[str, float] = field(default_factory=dict)


class ChimeraLoop:
    """The Reggio 8-phase heartbeat."""

    AGENT_ID = "chimera-main"

    def __init__(
        self,
        config: LoopConfig | None = None,
        *,
        drift_detector: DriftDetector | None = None,
        stagnation_history: list[Outcome] | None = None,
        act_executor: ActExecutor | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.config = config or LoopConfig.from_env()
        # ADR 0176: surface flag misconfiguration at startup. Warn-only —
        # a misconfigured flag must never block boot, just be visible.
        try:
            from ..config import validate_env

            for warning in validate_env():
                logger.warning("flag config: %s", warning)
        except Exception:
            logger.exception("flag validation failed; continuing")
        self._heartbeat_path = self.config.mind_dir / "HEARTBEAT.md"
        self._inbox_path = self.config.mind_dir / "INBOX.md"
        self._session_log_path = self.config.mind_dir / "SESSION_LOG.md"
        self._drift_state_path = self.config.state_dir / "drift" / "current.json"
        self._db_path = self.config.state_dir / "chimera.db"
        # SQLite connection — ontology + activity + api_calls + ladder_outcomes.
        self._db = open_and_init(self._db_path)
        # Tool registry + dispatcher. Register all built-in tools by default.
        self._registry = tool_registry or default_registry()
        register_core_tools(self._registry)
        # Load any dynamic skills previously activated under chimera/tools/dynamic/.
        try:
            loaded = load_dynamic_skills(self._registry)
            if loaded:
                logger.info("dynamic skills loaded: %s", loaded)
        except Exception:
            logger.exception("dynamic skill loader failed; continuing without them")
        # v2.5: PeerAwareDispatcher gates mcp-<peer>-* calls through the
        # cross-agent trust policy. Falls through to the base Dispatcher
        # behaviour for all non-peer tools.
        from ..a2a import PeerAwareDispatcher
        self._dispatcher = PeerAwareDispatcher(self._registry)
        # ACT executor (None when no provider keys are set).
        self._act = act_executor
        if self._act is None:
            self._act = ActExecutor.from_env(dispatcher=self._dispatcher, db=self._db)
        # spawn_sub_agent tool is only meaningful when ACT is live (it needs
        # to invoke a provider). Register it only then.
        if self._act is not None:
            sub_runner = SubAgentRunner(
                providers=self._act.providers,
                db=self._db,
                registry=self._registry,
            )
            register_sub_agent_tool(sub_runner, self._registry)
        # ADR 0174: model-backed peers. With CHIMERA_MODEL_PEERS on (and ACT
        # live for provider access), each cross-vendor ladder rung registers
        # as a peer exposing a real `consult` capability — the candidate set
        # ADR 0167's select_peer needs and the multi-tool_use fan-out source
        # ADR 0171 needs. Flag off (default) → nothing registers.
        if self._act is not None:
            from ..a2a import model_peers_enabled, register_model_peers

            if model_peers_enabled():
                try:
                    peers = register_model_peers(
                        self._registry,
                        self._act.providers,
                        db=self._db,
                        cycle_fn=lambda: (
                            self._report.cycle if self._report is not None else 0
                        ),
                    )
                    if peers:
                        logger.info("model peers registered: %s", peers)
                except Exception:
                    logger.exception(
                        "model-peer registration failed; continuing without them"
                    )
        # Per-session drift detector (persists across cycles + restarts).
        self._drift = drift_detector or DriftDetector(
            state_path=self._drift_state_path,
            config=DriftConfig(),
        )
        # Stagnation history; in-memory at MVP.
        self._stagnation_history: list[Outcome] = list(stagnation_history or [])
        # Per-cycle ephemeral state
        self._state: mind.HeartbeatState | None = None
        self._heartbeat_body: str = ""
        self._tasks: list[mind.InboxTask] = []
        self._completed_line_indices: set[int] = set()
        self._report: CycleReport | None = None
        self._force_rotation_reason: str | None = None
        self._current_plan: EntityRecord | None = None
        self._act_results: list[ActResult] = []
        self._mcp_initialized: bool = False
        self._trust = TrustManager(self.config.state_dir / "trust_state.json")
        # Planner is only constructable if ACT has providers.
        self._planner: Planner | None = None
        if self._act is not None:
            self._planner = Planner(providers=self._act.providers, db=self._db)
        # Daily engines (Discovery / Curiosity / Reflection) — same gating.
        self._chronicle = ChronicleManager(self.config.mind_dir / "CHRONICLE.md")
        # v4.84 (ADR 0097): give ACT a chronicle handle so three-strikes
        # auto-skip can surface an operator-visible warning.
        if self._act is not None:
            self._act._chronicle = self._chronicle
        self._engine_scheduler = EngineScheduler(
            self.config.state_dir / "engines" / "last_runs.json"
        )
        self._engines: dict[str, object] = {}
        if self._act is not None:
            providers = self._act.providers
            self._engines = {
                "discovery": DiscoveryEngine(
                    providers=providers,
                    db=self._db,
                    mind_dir=self.config.mind_dir,
                    chronicle=self._chronicle,
                ),
                "curiosity": CuriosityEngine(
                    providers=providers,
                    db=self._db,
                    registry=self._registry,
                    mind_dir=self.config.mind_dir,
                    chronicle=self._chronicle,
                ),
                "reflection": ReflectionEngine(
                    providers=providers,
                    db=self._db,
                    mind_dir=self.config.mind_dir,
                    chronicle=self._chronicle,
                    # ADR 0127 (amendment 2026-06-08): produce the tier the
                    # engine already consumes. Unset → None → the engine's
                    # literal ``tier="sonnet"`` default is preserved exactly
                    # (zero behavior change). Set CHIMERA_REFLECTION_REASONING_TIER
                    # to minimal/normal/deep/max to dial reflection cost+quality.
                    reasoning_tier=reasoning_tier_from_env(
                        "CHIMERA_REFLECTION_REASONING_TIER"
                    ),
                ),
            }
        # v4.75: install signal handlers so SIGTERM checkpoints WAL.
        self._install_signal_handlers()

    @property
    def drift_detector(self) -> DriftDetector:
        return self._drift

    @property
    def db(self):
        return self._db

    def close(self) -> None:
        """Release the SQLite connection. Safe to call multiple times.

        v4.75: checkpoints the WAL on close so a clean shutdown leaves
        chimera.db-wal empty. Prevents the orphan-WAL footgun where a
        second reader (the Next.js dashboard's better-sqlite3) reports
        "file is not a database" against a perfectly intact main DB.
        """
        if self._db is not None:
            try:
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception:  # noqa: BLE001
                logger.exception("wal_checkpoint on close failed; continuing")
            self._db.close()
            self._db = None  # type: ignore[assignment]

    def _install_signal_handlers(self) -> None:
        """Register SIGTERM/SIGINT handlers that checkpoint + close the DB.

        v4.75: the soak-test runner sends SIGTERM (or SIGINT) before
        escalating to SIGKILL. Catching the signal lets us run a single
        ``PRAGMA wal_checkpoint(TRUNCATE)`` before exiting, so the next
        reader sees a clean DB. SIGKILL bypasses this — which is the
        documented limitation and the reason ``chimera doctor`` still
        needs the orphan-WAL check.

        Idempotent. Skipped when not running in the main thread (some
        test harnesses import ChimeraLoop from a worker thread, where
        ``signal.signal`` raises ``ValueError``).
        """
        import threading
        if threading.current_thread() is not threading.main_thread():
            return

        def _handler(signum, _frame):  # noqa: ANN001
            logger.warning("received signal %s; checkpointing WAL and exiting", signum)
            try:
                self.close()
            finally:
                # Re-raise with the default disposition so the process exits
                # with the conventional 128+signum status.
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                # Already replaced by something else (e.g. asyncio), or
                # not supported on this platform. Best-effort only.
                pass

    # ── Public entry point ──────────────────────────────────

    async def run_one_cycle(self) -> CycleReport:
        started = mind.utc_now_iso()
        self._report = CycleReport(
            cycle=-1, started_at=started, completed_at="", tasks_seen=0, tasks_completed=0
        )
        # Reset per-cycle state.
        self._force_rotation_reason = None

        # One-shot MCP discovery — fires the first cycle only.
        if not self._mcp_initialized:
            try:
                counts = await register_mcp_servers_from_env(self._registry)
                if counts:
                    logger.info("MCP discovered: %s", counts)
            except Exception:
                logger.exception("MCP discovery failed; continuing without MCP tools")
            self._mcp_initialized = True

        async def _run(name: str, coro_fn, budget_ms: float | None = None):
            from .observability import phase_timer

            with phase_timer(f"loop.{name}", budget_ms=budget_ms) as t:
                result = await coro_fn()
            self._report.phase_times_ms[name] = t["elapsed_ms"]
            return result

        await _run("housekeeping", self._phase_housekeeping, budget_ms=500)
        await _run("wake", self._phase_wake, budget_ms=500)
        await _run("assess", self._phase_assess, budget_ms=1000)
        await _run("plan", self._phase_plan, budget_ms=240_000)
        await self._run_act_phase_with_budget()
        await _run("write", self._phase_write, budget_ms=1000)
        await _run("flush", self._phase_flush, budget_ms=2000)
        await _run("commit", self._phase_commit, budget_ms=1000)
        rotated = await _run("rotate", self._phase_rotate, budget_ms=1000)

        # Persist the per-phase timings as a small JSON for the dashboard.
        try:
            import json as _json
            timings_path = self.config.state_dir / "phase_timings.json"
            timings_path.write_text(
                _json.dumps({
                    "cycle": self._report.cycle,
                    "completed_at": mind.utc_now_iso(),
                    "phase_times_ms": self._report.phase_times_ms,
                }, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("failed to persist phase timings; continuing")

        self._report.rotated = rotated
        self._report.completed_at = mind.utc_now_iso()
        return self._report

    # ── Phases ──────────────────────────────────────────────

    async def _phase_housekeeping(self) -> None:
        """v4.24: auto-archive stale DEPRECATED entities.

        Reads ``CHIMERA_AUTO_ARCHIVE_AFTER_CYCLES`` (default 30) and
        ``CHIMERA_AUTO_ARCHIVE_DISABLED`` (default off). Each cycle,
        promotes up to 25 DEPRECATED entities that have been sitting
        for that many cycles to ARCHIVED via the K-operator.
        """
        import os as _os
        from ..memory import auto_archive_stale_deprecated

        archived: list[dict[str, Any]] = []
        if _os.environ.get("CHIMERA_AUTO_ARCHIVE_DISABLED") not in ("1", "true", "yes"):
            try:
                after = int(_os.environ.get("CHIMERA_AUTO_ARCHIVE_AFTER_CYCLES", "30"))
            except ValueError:
                after = 30
            cycle = self._report.cycle if self._report else 0
            try:
                archived = auto_archive_stale_deprecated(
                    self._db,
                    current_cycle=cycle,
                    archive_after_cycles=after,
                )
            except Exception:
                logger.exception("auto-archive failed; continuing")

        # v4.32: incremental graph projection. Append-only diffs so the
        # graph stays current between operator-triggered full rebuilds
        # without paying the 230ms clear+rebuild every cycle.
        #
        # v4.62 (ADR 0081): the graph is now an OPTIONAL projection.
        # ``graph_projection_enabled()`` returns False by default; opt in
        # with CHIMERA_GRAPH_ENABLED=1.
        graph_counts: dict[str, int] = {}
        if graph_projection_enabled():
            try:
                from ..memory import GraphStore, default_graph_dir
                store = GraphStore(default_graph_dir())
                graph_counts = store.update_from_sqlite(self._db)
            except Exception:
                logger.exception("auto-graph-update failed; continuing")

        # v4.61 (ADR 0080): refresh the FTS5 wiki index. mtime-gated
        # so unchanged files cost nothing; new/edited files re-index
        # incrementally. Skipped iff CHIMERA_AUTO_WIKI_INDEX_DISABLED=1.
        wiki_index_counts: dict[str, int] = {}
        if _os.environ.get("CHIMERA_AUTO_WIKI_INDEX_DISABLED") not in (
            "1", "true", "yes",
        ):
            try:
                from ..memory.wiki_search import update_wiki_index
                wiki_index_counts = update_wiki_index(
                    self._db, self.config.mind_dir / "wiki",
                )
            except Exception:
                logger.exception("auto-wiki-index update failed; continuing")

        details: dict[str, Any] = {}
        if archived:
            details["archived_count"] = len(archived)
        if graph_counts:
            added = sum(graph_counts.values())
            if added:
                details["graph_added"] = added
                for k, v in graph_counts.items():
                    if v:
                        details[f"graph_{k.lower()}"] = v
        if wiki_index_counts:
            churn = sum(
                v for k, v in wiki_index_counts.items() if k != "unchanged"
            )
            if churn:
                details["wiki_index_churn"] = churn
                for k, v in wiki_index_counts.items():
                    if v and k != "unchanged":
                        details[f"wiki_{k}"] = v
        self._record_phase_activity(
            "housekeeping",
            details=details or None,
        )

        parts: list[str] = []
        if archived:
            parts.append(
                f"archived {len(archived)} stale DEPRECATED "
                f"entit{'y' if len(archived) == 1 else 'ies'}"
            )
        if graph_counts and any(graph_counts.values()):
            added = sum(graph_counts.values())
            parts.append(f"projected {added} new graph row(s)")
        if parts:
            self._log_phase("HOUSEKEEPING: " + "; ".join(parts))
        else:
            self._log_phase("HOUSEKEEPING: nothing to do")

    async def _phase_wake(self) -> None:
        state, body = mind.load_heartbeat(self._heartbeat_path)
        self._state = state
        self._heartbeat_body = body
        assert self._report is not None
        self._report.cycle = state.cycle + 1  # this cycle's number
        # Ensure a STABLE plan exists; bootstrap if missing.
        self._current_plan = ensure_current_plan(self._db, cycle=self._report.cycle)
        self._report.current_plan_state = self._current_plan.kfm_state
        self._record_phase_activity("wake")
        self._log_phase(
            f"WAKE: restored cycle={state.cycle} trust_tier={state.trust_tier} "
            f"plan={self._current_plan.kfm_state}"
        )

    async def _phase_assess(self) -> None:
        tasks = mind.parse_inbox(self._inbox_path)
        open_tasks = [t for t in tasks if not t.done]
        # v4.78 (ADR 0094): operator-authored rows (source is None) sort
        # ahead of agent-proposed rows (source is "planner" / engine name)
        # so engine-appended tasks never preempt the operator's INBOX.
        # `sorted` is stable, so file order is preserved within each group.
        self._tasks = sorted(open_tasks, key=lambda t: t.source is not None)
        assert self._report is not None
        self._report.tasks_seen = len(self._tasks)
        self._record_phase_activity(
            "assess",
            details={
                "open_tasks": len(self._tasks),
                "operator_tasks": sum(1 for t in self._tasks if t.source is None),
                "agent_tasks": sum(1 for t in self._tasks if t.source is not None),
            },
        )
        self._log_phase(f"ASSESS: {len(self._tasks)} open task(s)")

    async def _phase_plan(self) -> None:
        """Strategic planner — every Nth cycle, ask Opus for 0..3 proposals.

        On non-plan cycles, ask the engine scheduler whether a daily engine
        (Discovery / Curiosity / Reflection) is due to fire.

        v4.12 / L-4: ``CHIMERA_ENGINES_ENABLED=0`` gates BOTH the Opus
        planner and the daily engines. Prior to v4.12 only the daily
        engines honored the flag — every-Nth-cycle proposals leaked
        through.
        """
        assert self._report is not None
        if os.environ.get("CHIMERA_ENGINES_ENABLED", "1") == "0":
            self._record_phase_activity("plan", details={"skipped": "engines_disabled"})
            self._log_phase("PLAN: skipped (engines disabled)")
            return
        # R5 (ADR 0151 / mechanism C): commit-only phase — suppress ALL
        # proposal generation (planner + daily engines) without disabling
        # CHIMERA_ENGINES_ENABLED (which would block the commit itself). Only
        # the operator INBOX commit task runs; no governance busywork can be
        # spawned to out-compete it. See chimera.core.loop._proposals_suppressed.
        if _proposals_suppressed():
            self._record_phase_activity(
                "plan", details={"skipped": "proposals_suppressed"},
            )
            self._log_phase("PLAN: skipped (proposals suppressed — commit-only phase)")
            return
        if self._planner is None:
            self._record_phase_activity("plan", details={"skipped": "no_providers"})
            self._log_phase("PLAN (no providers; skipped)")
            return
        open_tasks = [t.text for t in self._tasks]
        # B1 (v40′ scope-creep fix): don't let the planner pile proposals
        # onto an already-deep backlog. When open tasks >= the cap, skip
        # proposal generation this cycle; engines (which do research, not
        # task-spawning) still get their off-PLAN turn.
        max_open = _plan_max_open_tasks()
        if len(open_tasks) >= max_open:
            self._record_phase_activity(
                "plan",
                details={
                    "skipped": "backlog_full",
                    "open_tasks": len(open_tasks),
                    "cap": max_open,
                },
            )
            self._log_phase(
                f"PLAN: skipped (backlog {len(open_tasks)} ≥ {max_open} cap; "
                "planner not piling on)"
            )
            await self._maybe_run_engine()
            return
        plan_result = await self._planner.maybe_plan(
            cycle=self._report.cycle,
            every_n=self.config.opus_plan_every_n_cycles,
            open_tasks=open_tasks,
        )
        if plan_result.skipped:
            # Try the daily engines on this off-PLAN cycle.
            await self._maybe_run_engine()
            return
        if plan_result.failure_reason:
            self._record_phase_activity(
                "plan", details={"failure": plan_result.failure_reason}
            )
            self._log_phase(f"PLAN: failed — {plan_result.failure_reason}")
            return
        if plan_result.proposals:
            self._append_proposals_to_inbox(plan_result.proposals)
            self._report.proposals_added = len(plan_result.proposals)
        self._record_phase_activity(
            "plan",
            details={
                "proposals": len(plan_result.proposals),
                "api_calls": plan_result.api_call_count,
            },
        )
        self._log_phase(
            f"PLAN: {len(plan_result.proposals)} proposal(s) added"
        )

    async def _maybe_run_engine(self) -> None:
        """Off-plan cycle hook: route to a daily engine if one is due."""
        assert self._report is not None
        if not self._engines:
            self._record_phase_activity("plan", details={"skipped": True, "engine": None})
            self._log_phase("PLAN: skipped (no engines available)")
            return
        # v4.74 (ADR 0092): pass session_id so session-mode dedup works.
        due = self._engine_scheduler.pick_due(
            session_id=self._state.session_started_at,
        )
        if due is None:
            self._record_phase_activity("plan", details={"skipped": True, "engine": None})
            self._log_phase("PLAN: skipped (no engine due)")
            return
        engine = self._engines.get(due)
        if engine is None:
            self._log_phase(f"PLAN: engine {due!r} not constructed; skipping")
            return
        result = await engine.run(cycle=self._report.cycle)  # type: ignore[attr-defined]
        if not result.failure_reason and not result.skipped:
            self._engine_scheduler.mark_ran(  # type: ignore[arg-type]
                due, session_id=self._state.session_started_at,
            )
        self._report.engine_fired = due
        self._report.engine_summary = result.summary or result.failure_reason
        self._record_phase_activity(
            "plan",
            details={
                "engine": due,
                "api_calls": result.api_call_count,
                "failure_reason": result.failure_reason,
            },
        )
        outcome = result.failure_reason or result.summary or "(ok)"
        self._log_phase(f"PLAN[{due}]: {outcome[:120]}")

    async def force_run_engine(self, name: str) -> object:
        """Force a named engine to run regardless of schedule.

        Used by ``chimera engines run <name>`` for testing/operator overrides.
        """
        if name not in self._engines:
            raise ValueError(f"unknown engine: {name!r} (available: {sorted(self._engines)})")
        # Engines need a cycle number; load HEARTBEAT to get the next cycle.
        if self._state is None:
            state, body = mind.load_heartbeat(self._heartbeat_path)
            self._state = state
            self._heartbeat_body = body
        cycle = self._state.cycle + 1
        engine = self._engines[name]
        return await engine.run(cycle=cycle)  # type: ignore[attr-defined]

    def _append_proposals_to_inbox(
        self, proposals: list, *, source: str = "planner"
    ) -> None:
        """Append proposals to mind/INBOX.md as new `- [ ]` lines.

        Each row is tagged with `<!-- src: {source} -->` so ASSESS can sort
        operator-authored rows (no tag) ahead of agent-proposed ones (ADR 0094).
        """
        if not proposals:
            return
        src_tag = f"  <!-- src: {source} -->"
        new_block = "\n".join(
            f"- [ ] {p.text}"
            + (f"  <!-- {p.rationale} -->" if p.rationale else "")
            + src_tag
            for p in proposals
        )
        with self._inbox_path.open("a", encoding="utf-8") as f:
            f.write(("\n" if self._inbox_path.read_text().rstrip() else "") + new_block + "\n")

    async def _run_act_phase_with_budget(self) -> None:
        """Dispatch ``_phase_act`` under a hard wall-clock budget.

        v35 postmortem ladder #4: the historical 240s budget was decorative
        — ``phase_timer`` only logged an over-budget warning, and attempt #3
        observed ACT phases running 1.5×–8.4× over (peak 2017s on iter 4
        phase 2). This wrapper enforces ``CHIMERA_ACT_BUDGET_SECONDS`` via
        ``asyncio.wait_for``: on timeout the in-flight executor receives
        ``CancelledError``, a structured ``act_budget_exceeded`` event is
        logged, and the loop advances to WRITE with whatever results
        accumulated. ADR 0120's 600s silent-death watchdog stays as the
        outer hard ceiling.
        """
        assert self._report is not None
        from .observability import phase_timer

        budget_seconds = _act_budget_seconds()
        budget_ms = budget_seconds * 1000.0
        with phase_timer("loop.act", budget_ms=budget_ms) as t:
            try:
                await asyncio.wait_for(self._phase_act(), timeout=budget_seconds)
            except asyncio.TimeoutError:
                completed = sum(
                    1 for r in (self._act_results or []) if r.completed
                )
                total = len(self._tasks)
                logger.warning(
                    "ACT phase budget exceeded: cancelled at %.0fs "
                    "(completed=%d/%d tasks)",
                    budget_seconds, completed, total,
                    extra={
                        "event": "act_budget_exceeded",
                        "budget_seconds": budget_seconds,
                        "completed_tasks": completed,
                        "total_tasks": total,
                        "cycle": self._report.cycle,
                    },
                )
                self._log_phase(
                    f"ACT: budget exceeded ({budget_seconds:.0f}s); "
                    f"cancelled, {completed}/{total} task(s) completed"
                )
                self._record_phase_activity(
                    "act",
                    details={
                        "budget_exceeded": True,
                        "budget_seconds": budget_seconds,
                        "tasks": total,
                        "completed": completed,
                    },
                )
        self._report.phase_times_ms["act"] = t["elapsed_ms"]

    async def _phase_act(self) -> None:
        """Execute each open inbox task via the ACT executor.

        Without provider keys (no ACT executor available), this falls back to
        the stub behavior. Tasks whose ACT result has ``completed=True`` get
        flagged for WRITE to flip to ``- [x]``.

        At T0 (LOCKED), tool dispatch is skipped — Chimera runs in observer
        mode until promoted.
        """
        assert self._report is not None
        self._act_results = []
        self._report.trust_tier_before = self._trust.tier.name
        if self._act is None:
            self._record_phase_activity("act", details={"tasks": len(self._tasks), "stub": True})
            self._log_phase(f"ACT (no providers configured; {len(self._tasks)} task(s) untouched)")
            return
        if self._trust.tier is TrustTier.T0:
            self._record_phase_activity(
                "act", details={"tasks": len(self._tasks), "locked": True}
            )
            self._log_phase(
                f"ACT: LOCKED at T0; observer mode (skipping {len(self._tasks)} task(s))"
            )
            return

        for task in self._tasks:
            result = await self._act.execute(task.text, cycle=self._report.cycle)
            self._act_results.append(result)
            # v40 prereq: append this ACT cycle to the soak tool-call ledger.
            # No-op unless CHIMERA_SOAK_RUN_ID is set; fail-soft by contract,
            # so a ledger error can never break the ACT phase.
            record_act_tools(
                mind_dir=self.config.mind_dir,
                cycle=self._report.cycle,
                task_text=task.text,
                result=result,
            )
            if result.completed:
                self._completed_line_indices.add(task.line_index)
            self._log_phase(
                f"ACT: {task.text!r} → {result.finish_reason} "
                f"(rounds={result.rounds}, tools={len(result.tool_call_history)}, "
                f"completed={result.completed})"
            )
            # v4.93 (ADR 0100): graduated trust decrement keyed on
            # finish_reason. ungrounded_citation / max_rounds / length
            # demote 0 tiers; scope_evasion / silent_failure demote 2.
            if not result.completed:
                try:
                    demoted = self._trust.apply_finish_reason(
                        result.finish_reason,
                        reason_suffix=f"cycle {self._report.cycle}",
                    )
                    if demoted:
                        self._log_phase(
                            f"ACT: trust demoted {demoted} tier(s) → "
                            f"{self._trust.tier.name} "
                            f"({result.finish_reason})"
                        )
                except Exception:
                    logger.exception("trust apply_finish_reason failed; continuing")

        details: dict[str, object] = {
            "tasks": len(self._tasks),
            "completed": sum(1 for r in self._act_results if r.completed),
            "api_calls": sum(r.api_call_count for r in self._act_results),
        }
        # ADR 0170: per-cycle tool-use entropy. Low H = the agent fixated on
        # one tool (a degenerate-loop precursor, earlier than the exact-repeat
        # detector); high H = broad tool use. Flag-gated emission — with
        # CHIMERA_ENTROPY_SIGNALS unset the details dict and phase log are
        # byte-identical to the prior path.
        from .entropy_signals import entropy_signals_enabled, tool_use_entropy

        if entropy_signals_enabled():
            tool_names = [
                tc.name
                for r in self._act_results
                for tc in r.tool_call_history
            ]
            h = round(tool_use_entropy(tool_names), 3)
            details["tool_entropy"] = h
            details["tool_calls"] = len(tool_names)
            self._log_phase(
                f"ACT: tool-use entropy H={h} over {len(tool_names)} tool call(s)"
            )
        self._record_phase_activity("act", details=details)

    async def _phase_write(self) -> None:
        assert self._state is not None
        assert self._report is not None

        # Mark any tasks ACT decided are complete (none at MVP).
        flipped = mind.mark_inbox_tasks_done(self._inbox_path, self._completed_line_indices)
        self._report.tasks_completed = flipped

        # Advance cycle counter, set session_started_at on first cycle of a session.
        self._state.cycle += 1
        if self._state.session_started_at is None:
            self._state.session_started_at = self._report.started_at
        self._state.status = "running"
        mind.save_heartbeat(self._heartbeat_path, self._state, self._heartbeat_body)

        mind.append_session_log(
            self._session_log_path,
            f"- cycle {self._state.cycle} @ {self._report.started_at} — "
            f"tasks_seen={self._report.tasks_seen} flipped={flipped}",
        )
        self._record_phase_activity("write", details={"flipped": flipped})
        self._log_phase(f"WRITE: cycle now {self._state.cycle}, flipped={flipped}")

    async def _phase_flush(self) -> None:
        """Observe this cycle's text + tool footprint into the drift detector;
        assess on the configured interval; apply the policy decision.

        Stagnation detection runs every cycle (orthogonal to behavioral drift).
        Behavioral drift is skipped on the cycle we mark the boundary, since
        anchor and observed don't both have content yet.
        """
        assert self._report is not None
        observation_text = " ".join(self._report.phase_log)
        for task in self._tasks:
            observation_text += " " + task.text
        self._drift.observe(observation_text, tools=[])

        just_marked = False
        if (
            not self._drift.boundary_marked
            and self._drift.observation_count >= self._drift.config.min_observations
        ):
            self._drift.mark_boundary()
            just_marked = True
            self._log_phase("FLUSH: drift boundary marked (baseline locked)")

        # Stagnation is a separate axis; check every cycle.
        stagnation_nudge = detect_stagnation(self._stagnation_history)

        reading = None
        if not just_marked and self._drift.should_assess():
            reading = self._drift.assess()

        # Build a signal only if there's *something* to respond to.
        if reading is not None or stagnation_nudge is not None:
            signal = DriftSignal(
                composite_score=reading.composite_score if reading else 0.0,
                severity=reading.severity if reading else "low",
                fired_instruments=(
                    tuple(reading.fired_instruments) if reading else ()
                ),
                stagnation_nudge=stagnation_nudge,
                boundary_recently_crossed=False,
            )
            decision = drift_respond(
                signal,
                lockdown_threshold=self._drift.config.lockdown_threshold,
                warning_threshold=self._drift.config.warning_threshold,
            )
            self._report.drift_decision = decision
            self._apply_decision(decision)
            if reading is not None:
                try:
                    from .drift_log import record_drift

                    record_drift(
                        cycle=self._report.cycle,
                        composite_score=reading.composite_score,
                        severity=reading.severity,
                        action=decision.action.value,
                        reason=decision.reason,
                    )
                except Exception:
                    logger.exception("drift_log write failed; continuing")
                self._log_phase(
                    f"FLUSH: drift composite={reading.composite_score:.3f} "
                    f"severity={reading.severity} → {decision.action.value} "
                    f"({decision.reason})"
                )
            else:
                self._log_phase(
                    f"FLUSH: stagnation → {decision.action.value} ({decision.reason})"
                )
        else:
            self._log_phase(
                f"FLUSH: observed (count={self._drift.observation_count}; not yet assessing)"
            )

        # Persist drift state every cycle so observations survive restart.
        self._drift.save()

        # Auto-promotion check (cheap; pure decision).
        try:
            self._maybe_autopromote()
        except Exception:
            logger.exception("autopromote check failed; continuing")

        self._record_phase_activity("flush")

    def _maybe_autopromote(self) -> None:
        """Compute readiness and ask TrustManager whether to bump up a tier."""
        assert self._report is not None
        # drift_score: take the latest reading composite if available.
        latest = self._drift.readings[-1] if self._drift.readings else None
        drift_score = latest.composite_score if latest else 0.0
        # activity_rate: based on api_calls in the last 3 cycles vs 5+ expected.
        rows = self._db.execute(
            "SELECT COUNT(*) AS n FROM api_calls WHERE cycle >= ?",
            (max(0, self._report.cycle - 3),),
        ).fetchone()
        recent_calls = (rows["n"] if rows else 0) or 0
        activity_rate = min(1.0, recent_calls / 6.0)
        # failure_rate: errored api_calls / total in same window.
        fail_row = self._db.execute(
            "SELECT COUNT(*) AS n FROM api_calls WHERE cycle >= ? AND error IS NOT NULL",
            (max(0, self._report.cycle - 3),),
        ).fetchone()
        failure_count = (fail_row["n"] if fail_row else 0) or 0
        failure_rate = failure_count / max(1, recent_calls)
        # gate-approval rate: fraction of recent in-loop critic-gate decisions
        # (ADR 0162 ledger) that were ALLOWED, so trust is EARNED from a track
        # record of faithful, gate-accepted commits — not just operational health
        # (ADR 0163 follow-up). None when there's no gate history → pure
        # operational readiness (unchanged behaviour).
        gate_rate: float | None = None
        gate_log = self.config.state_dir / "critic-gate-log.jsonl"
        try:
            recent = [ln for ln in gate_log.read_text().splitlines() if ln.strip()][-20:]
            decisions = []
            for ln in recent:
                try:
                    decisions.append(json.loads(ln))
                except (json.JSONDecodeError, ValueError):
                    continue
            if decisions:
                allowed = sum(1 for d in decisions if d.get("allowed") is True)
                gate_rate = allowed / len(decisions)
        except OSError:
            pass
        readiness = self._trust.readiness(
            drift_score=drift_score,
            activity_rate=activity_rate,
            failure_rate=failure_rate,
            gate_approval_rate=gate_rate,
        )
        before = self._trust.tier.name
        if self._trust.maybe_autopromote(
            readiness=readiness, reason_suffix=f"cycle {self._report.cycle}"
        ):
            self._report.trust_autopromoted = True
            self._log_phase(
                f"FLUSH: autopromoted {before} → {self._trust.tier.name} "
                f"(readiness={readiness:.2f})"
            )
        self._report.trust_tier_after = self._trust.tier.name
        # Mirror tier into HEARTBEAT frontmatter so `chimera status` shows it.
        if self._state is not None:
            self._state.trust_tier = self._trust.tier.name

    def _apply_decision(self, decision: DriftDecision) -> None:
        """Translate a drift decision into loop state changes."""
        assert self._report is not None
        assert self._state is not None
        if decision.action is DriftAction.KILL_SESSION:
            self._force_rotation_reason = decision.reason
            # Also demote the plan AND lockdown trust.
            self._demote_current_plan(reason=f"kill_session: {decision.reason}")
            if self._trust.lockdown(reason=f"drift kill_session: {decision.reason}"):
                self._report.trust_locked_down = True
        elif decision.action is DriftAction.DEMOTE_PLAN:
            self._demote_current_plan(reason=decision.reason)
            # Demote one trust tier on severe drift (not full lockdown).
            self._trust.demote(reason=f"drift demote_plan: {decision.reason}")
        elif decision.action is DriftAction.NUDGE and decision.nudge:
            self._report.pending_nudge = decision.nudge

    def _demote_current_plan(self, *, reason: str) -> None:
        """K-Operator transition STABLE → DEPRECATED on the current plan, then
        bootstrap a fresh plan record under a new name so the next cycle has
        something to anchor to. The deprecated plan stays in the DB as audit.
        """
        assert self._report is not None
        assert self._state is not None
        if self._current_plan is None or self._current_plan.kfm_state != "STABLE":
            self._report.phase_log.append(
                f"FLUSH: DEMOTE skipped (plan state={self._current_plan.kfm_state if self._current_plan else 'none'})"
            )
            return
        transition_entity(
            self._db,
            self._current_plan.id,
            "DEPRECATED",
            "k",
            cycle=self._state.cycle + 1,
            reason=reason,
        )
        # Re-anchor: rename the deprecated plan and create a fresh one under
        # "current". We do this by deprecating-in-place; the new plan takes
        # a unique name derived from the cycle so the (kind, name) UNIQUE
        # constraint holds.
        from ..memory import create_entity
        # Rename the deprecated plan to free up "current" for the new one.
        new_name = f"deprecated-cycle-{self._state.cycle + 1}-{self._current_plan.id[:8]}"
        self._db.execute(
            "UPDATE entities SET name = ? WHERE id = ?",
            (new_name, self._current_plan.id),
        )
        # Now bootstrap a fresh STABLE plan under "current".
        new_plan = create_entity(
            self._db,
            kind="plan",
            name="current",
            cycle=self._state.cycle + 1,
            initial_state="STABLE",
            details={"reanchored_from": self._current_plan.id, "reason": reason},
        )
        self._current_plan = new_plan
        self._report.plan_demoted = True
        self._report.current_plan_state = new_plan.kfm_state

    def _record_phase_activity(
        self, phase: str, *, details: dict | None = None
    ) -> None:
        """Idempotent activity-log write per (cycle, cell_id=phase).

        Silently skips when called before WAKE has set the cycle number
        (e.g. HOUSEKEEPING runs first and doesn't yet have a cycle).
        """
        if self._report is None or self._report.cycle < 0:
            return
        record_activity(
            self._db,
            cycle=self._report.cycle,
            cell_id=phase,
            agent_id=self.AGENT_ID,
            activity_type=phase,
            layer="loop",
            details=details,
        )

    async def _phase_commit(self) -> None:
        # MVP stub. Git checkpoint lands when trust tier system does.
        self._record_phase_activity("commit")
        self._log_phase("COMMIT (stub)")

    async def _phase_rotate(self) -> bool:
        """Return True if the session should rotate.

        Two triggers: age ≥ ``max_session_hours``, or a drift-policy KILL_SESSION
        decision recorded earlier in this cycle.
        """
        assert self._state is not None

        forced = self._force_rotation_reason
        age_hours = 0.0
        if self._state.session_started_at:
            started = dt.datetime.fromisoformat(self._state.session_started_at)
            now = dt.datetime.now(dt.timezone.utc)
            if started.tzinfo is None:
                started = started.replace(tzinfo=dt.timezone.utc)
            age_hours = (now - started).total_seconds() / 3600

        if forced or age_hours >= self.config.max_session_hours:
            reason = forced or f"age_hours={age_hours:.2f}"
            self._state.status = "rotated"
            self._state.session_started_at = None  # next cycle starts a new session
            mind.save_heartbeat(self._heartbeat_path, self._state, self._heartbeat_body)
            mind.append_session_log(
                self._session_log_path,
                f"- ROTATE @ {mind.utc_now_iso()} — {reason}",
            )
            # ADR 0129: consolidate peer cards on rotation. Wrapped so a
            # peer-cards failure cannot prevent the rotation from
            # completing — rotation is the load-bearing operation.
            self._consolidate_peer_cards_safe()
            # ADR 0132: ingest observer/observed beliefs from each
            # registered peer's KFM snapshot. Independent of peer
            # cards; same failure-isolation discipline.
            self._ingest_peer_beliefs_safe()
            self._log_phase(f"ROTATE: rotated ({reason})")
            self._force_rotation_reason = None
            return True

        self._record_phase_activity("rotate", details={"age_hours": age_hours})
        if not self._state.session_started_at:
            self._log_phase("ROTATE: no session_started_at; skip")
        else:
            self._log_phase(f"ROTATE: session age {age_hours:.2f}h; continue")
        return False

    def _consolidate_peer_cards_safe(self) -> None:
        """Refresh ``mind/peers/`` on rotation (ADR 0128 / ADR 0129).

        Default-on; opt out with ``CHIMERA_PEER_CARDS_ON_ROTATE=0``.
        Failures are logged and swallowed so they cannot break the
        rotation path. KFM fetch is intentionally skipped here (sync
        only); a follow-up chip adds the async fetch.

        When ``CHIMERA_PEER_CARD_LLM=1`` and ACT providers are
        available, each card is enriched with a short narrative
        paragraph via one sonnet-tier call per card (ADR 0130).
        Narrative failures are isolated per-card.
        """
        if os.environ.get("CHIMERA_PEER_CARDS_ON_ROTATE", "1").strip().lower() in (
            "0", "false", "no", "off",
        ):
            return
        try:
            from ..a2a.peer_trust_journal import list_decisions
            from ..a2a.peers import list_peer_chimeras
            from ..engines.peer_cards import (
                build_peer_card,
                build_self_card,
                write_peer_card,
            )

            current_cycle = self._state.cycle if self._state is not None else 0
            peer_names = list_peer_chimeras(self._registry)
            narrative_enabled = os.environ.get(
                "CHIMERA_PEER_CARD_LLM", "",
            ).strip().lower() in ("1", "true", "yes", "on")

            cards = [build_self_card(trust_state=self._trust.state)]
            for name in peer_names:
                cards.append(build_peer_card(
                    name,
                    decisions=list_decisions(name),
                    current_cycle=current_cycle,
                ))

            if narrative_enabled:
                self._enrich_cards_with_narratives(cards)

            paths = [write_peer_card(self.config.mind_dir, c) for c in cards]
            suffix = " + narratives" if narrative_enabled else ""
            self._log_phase(
                f"ROTATE: peer cards refreshed ({len(paths)} files{suffix})"
            )
        except Exception as exc:  # noqa: BLE001 — never fail rotation
            logger.warning("peer cards consolidation failed: %s", exc)
            self._log_phase(f"ROTATE: peer cards failed ({exc})")

    def _enrich_cards_with_narratives(self, cards: list) -> None:
        """Best-effort narrative enrichment; per-card failures isolated (ADR 0130).

        Uses the same provider topology as the daily engines (sonnet
        tier). When ACT isn't configured (no providers) or the
        provider call fails, the affected card simply doesn't get a
        narrative — the deterministic body is still written.
        """
        if self._act is None or not getattr(self._act, "providers", None):
            self._log_phase("ROTATE: peer card narratives skipped (no providers)")
            return

        from ..engines.peer_cards import apply_narrative, build_narrative_prompt
        from ..providers import Message
        from ..providers.tiers import Provider as ProviderKind
        from ..providers.tiers import select_rung

        try:
            rung = select_rung("sonnet")
        except (ValueError, RuntimeError) as exc:
            logger.warning("peer-card narrative tier resolution failed: %s", exc)
            return
        provider = self._act.providers.get(rung.config.provider)
        if provider is None:
            self._log_phase("ROTATE: peer card narratives skipped (no provider for sonnet)")
            return
        model_id = (
            rung.config.model_id
            if rung.config.provider is ProviderKind.ANTHROPIC
            else rung.config.openrouter_model_id
        )

        async def _call(prompt: str) -> str:
            response = await provider.complete_with_tools(
                messages=[Message.user(prompt)],
                model_id=model_id,
                tools=[],
                max_tokens=256,
            )
            return response.text or ""

        from .._async_loop import run_on_persistent_loop

        for card in cards:
            try:
                prompt = build_narrative_prompt(card)
                text = run_on_persistent_loop(_call(prompt))
                apply_narrative(card, text)
            except Exception as exc:  # noqa: BLE001 — per-card isolation
                logger.warning(
                    "peer-card narrative failed for %s: %s", card.peer_name, exc,
                )

    def _ingest_peer_beliefs_safe(self) -> None:
        """Append per-peer belief records to ``mind/peer_beliefs.jsonl`` (ADR 0132).

        For each registered peer, fetch their KFM snapshot and derive
        a coarse self-belief (TRUSTS / NEUTRAL / DISTRUSTS / UNKNOWN)
        via :func:`chimera.a2a.peer_beliefs.belief_from_kfm`. Default-on;
        opt out with ``CHIMERA_PEER_BELIEFS_ON_ROTATE=0``. Failures
        per-peer are isolated; rotation always completes.
        """
        if os.environ.get("CHIMERA_PEER_BELIEFS_ON_ROTATE", "1").strip().lower() in (
            "0", "false", "no", "off",
        ):
            return
        try:
            from .._async_loop import run_on_persistent_loop
            from ..a2a.peer_beliefs import belief_from_kfm, record_belief
            from ..a2a.peers import fetch_peer_kfm, list_peer_chimeras

            peer_names = list_peer_chimeras(self._registry)
            if not peer_names:
                self._log_phase("ROTATE: peer beliefs — no peers")
                return

            recorded = 0
            for name in peer_names:
                try:
                    kfm = run_on_persistent_loop(
                        fetch_peer_kfm(name, registry=self._registry),
                    )
                    belief = belief_from_kfm(name, kfm)
                    record_belief(belief, mind_dir=self.config.mind_dir)
                    recorded += 1
                except Exception as exc:  # noqa: BLE001 — per-peer isolation
                    logger.warning(
                        "peer-belief ingest failed for %s: %s", name, exc,
                    )
            self._log_phase(
                f"ROTATE: peer beliefs recorded ({recorded}/{len(peer_names)} peers)"
            )
        except Exception as exc:  # noqa: BLE001 — never fail rotation
            logger.warning("peer beliefs ingest failed: %s", exc)
            self._log_phase(f"ROTATE: peer beliefs failed ({exc})")

    # ── helpers ────────────────────────────────────────────

    def _log_phase(self, msg: str) -> None:
        logger.info(msg)
        if self._report is not None:
            self._report.phase_log.append(msg)
