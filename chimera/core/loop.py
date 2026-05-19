"""8-phase Chimera loop.

Per ADR 0003: HOUSEKEEPING → WAKE → ASSESS → PLAN → ACT → WRITE →
FLUSH → COMMIT → ROTATE. MVP scope per the ADR's phase-by-phase table:
WAKE/ASSESS/WRITE/ROTATE carry real behaviour; the rest are stubs.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

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
from ..tools import (
    Dispatcher,
    SubAgentRunner,
    ToolRegistry,
    default_registry,
    register_core_tools,
    register_mcp_servers_from_env,
    register_sub_agent_tool,
)
from . import mind
from .act import ActExecutor, ActResult
from .strategy import Planner, PlanResult

logger = logging.getLogger(__name__)


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
        self._dispatcher = Dispatcher(self._registry)
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
        # Planner is only constructable if ACT has providers.
        self._planner: Planner | None = None
        if self._act is not None:
            self._planner = Planner(providers=self._act.providers, db=self._db)

    @property
    def drift_detector(self) -> DriftDetector:
        return self._drift

    @property
    def db(self):
        return self._db

    def close(self) -> None:
        """Release the SQLite connection. Safe to call multiple times."""
        if self._db is not None:
            self._db.close()
            self._db = None  # type: ignore[assignment]

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

        await self._phase_housekeeping()
        await self._phase_wake()  # also sets self._report.cycle

        await self._phase_assess()
        await self._phase_plan()
        await self._phase_act()
        await self._phase_write()
        await self._phase_flush()
        await self._phase_commit()
        rotated = await self._phase_rotate()

        self._report.rotated = rotated
        self._report.completed_at = mind.utc_now_iso()
        return self._report

    # ── Phases ──────────────────────────────────────────────

    async def _phase_housekeeping(self) -> None:
        # MVP stub. Sweep-stale mutation logic lands when MutationQueue does.
        self._record_phase_activity("housekeeping")
        self._log_phase("HOUSEKEEPING (stub)")

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
        self._tasks = [t for t in tasks if not t.done]
        assert self._report is not None
        self._report.tasks_seen = len(self._tasks)
        self._record_phase_activity("assess", details={"open_tasks": len(self._tasks)})
        self._log_phase(f"ASSESS: {len(self._tasks)} open task(s)")

    async def _phase_plan(self) -> None:
        """Strategic planner — every Nth cycle, ask Opus for 0..3 proposals.

        Proposals are dedup'd against the current INBOX and appended as
        ``- [ ]`` lines for the next ACT cycle to pick up.
        """
        assert self._report is not None
        if self._planner is None:
            self._record_phase_activity("plan", details={"skipped": "no_providers"})
            self._log_phase("PLAN (no providers; skipped)")
            return
        open_tasks = [t.text for t in self._tasks]
        plan_result = await self._planner.maybe_plan(
            cycle=self._report.cycle,
            every_n=self.config.opus_plan_every_n_cycles,
            open_tasks=open_tasks,
        )
        if plan_result.skipped:
            self._record_phase_activity("plan", details={"skipped": True})
            self._log_phase(
                f"PLAN: skipped "
                f"(cycle={self._report.cycle} % {self.config.opus_plan_every_n_cycles})"
            )
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

    def _append_proposals_to_inbox(self, proposals: list) -> None:
        """Append proposals to mind/INBOX.md as new `- [ ]` lines."""
        if not proposals:
            return
        new_block = "\n".join(
            f"- [ ] {p.text}"
            + (f"  <!-- {p.rationale} -->" if p.rationale else "")
            for p in proposals
        )
        with self._inbox_path.open("a", encoding="utf-8") as f:
            f.write(("\n" if self._inbox_path.read_text().rstrip() else "") + new_block + "\n")

    async def _phase_act(self) -> None:
        """Execute each open inbox task via the ACT executor.

        Without provider keys (no ACT executor available), this falls back to
        the stub behavior. Tasks whose ACT result has ``completed=True`` get
        flagged for WRITE to flip to ``- [x]``.
        """
        assert self._report is not None
        self._act_results = []
        if self._act is None:
            self._record_phase_activity("act", details={"tasks": len(self._tasks), "stub": True})
            self._log_phase(f"ACT (no providers configured; {len(self._tasks)} task(s) untouched)")
            return

        for task in self._tasks:
            result = await self._act.execute(task.text, cycle=self._report.cycle)
            self._act_results.append(result)
            if result.completed:
                self._completed_line_indices.add(task.line_index)
            self._log_phase(
                f"ACT: {task.text!r} → {result.finish_reason} "
                f"(rounds={result.rounds}, tools={len(result.tool_call_history)}, "
                f"completed={result.completed})"
            )

        self._record_phase_activity(
            "act",
            details={
                "tasks": len(self._tasks),
                "completed": sum(1 for r in self._act_results if r.completed),
                "api_calls": sum(r.api_call_count for r in self._act_results),
            },
        )

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
        self._record_phase_activity("flush")

    def _apply_decision(self, decision: DriftDecision) -> None:
        """Translate a drift decision into loop state changes."""
        assert self._report is not None
        assert self._state is not None
        if decision.action is DriftAction.KILL_SESSION:
            self._force_rotation_reason = decision.reason
            # Also demote the plan: re-anchor must start from a clean slate.
            self._demote_current_plan(reason=f"kill_session: {decision.reason}")
        elif decision.action is DriftAction.DEMOTE_PLAN:
            self._demote_current_plan(reason=decision.reason)
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
            self._log_phase(f"ROTATE: rotated ({reason})")
            self._force_rotation_reason = None
            return True

        self._record_phase_activity("rotate", details={"age_hours": age_hours})
        if not self._state.session_started_at:
            self._log_phase("ROTATE: no session_started_at; skip")
        else:
            self._log_phase(f"ROTATE: session age {age_hours:.2f}h; continue")
        return False

    # ── helpers ────────────────────────────────────────────

    def _log_phase(self, msg: str) -> None:
        logger.info(msg)
        if self._report is not None:
            self._report.phase_log.append(msg)
