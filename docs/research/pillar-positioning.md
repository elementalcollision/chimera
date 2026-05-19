# Pillar: Environmental Positioning in Village

**Phase 0 Research Spike | Task 0.5 — Environmental Adaptation Patterns**

## TL;DR

Village agents position themselves in their environment through three coordinated mechanisms:

1. **Sensing via Activity Log + Clerk API**: Each agent probes its topology position (buildings, capabilities, KFM state) through synchronous REST calls to Clerk, then records work proof via `POST /agents/{id}/activity` with cycle-scoped claims (one cycle per `(cycle_number, cell_id)` PK to prevent collision).
2. **Signal-Driven Lifecycle**: SIGTERM/SIGINT handlers (via `install_drain_handlers`) flip an `asyncio.Event` drain flag, triggering graceful shutdown of background tasks (work loops, message consumers) within a 30s timeout before resource teardown.
3. **Operator Lifecycle (KFM + Clerk)**: Three operator types (F/M/K) manage agent state transitions (NEW → EXPERIMENTAL → CANDIDATE → STABLE → DEPRECATED → ARCHIVED → KILLED). Each transition is stateless-checked by `clerk.kfm` module (no DB access) then committed atomically with event publication, authorizing state changes to specific operators only.

Resilience comes from **idempotent cycle claims** (PK collision detection), **circuit-breaker clients** (exponential backoff on Clerk/peer unavailability), **background task drains** (graceful SIGTERM handling), and **activity-log audit trails** (proof of work across cycles).

---

## Patterns Adopted from Village

### Pattern 1: Activity Log as Primary Heartbeat

**Source**: `services/clerk/src/clerk/routers/activity.py` + `services/clerk/alembic/versions/0004_agent_activity_log.py`

**What it does**: Instead of periodic ping/pong health checks, agents record **work output** to a queryable activity log. M-Operator probes this log to assess agent liveness and validate role-based coverage.

Schema (Sprint 15, §9.7):
- Table: `agent_activity_log(id, agent_id, activity_type, cycle, layer, cell_ref, details, created_at)`
- Index: `(agent_id, cycle)` for O(1) range queries
- Writes are non-blocking: activity rows inserted *during* work tick, not as separate health probe

M-Operator Evaluation (M-BASE-01):
```
GET /agents/{agent_id}/activity?current_cycle=C&last_n_cycles=3
→ { activity_count, active_cycles_in_window, layer_counts, distinct_cells_per_layer, activities[...] }
```

Decision logic:
- `active_cycles_in_window == 0` over last 3 cycles → agent is **failing** → K-Operator triggers STABLE → DEPRECATED transition
- `active_cycles_in_window >= 2` AND `distinct_cells_per_layer` matches role requirements → agent is **viable** → stays STABLE

**Why we adopt**:
- Heartbeat is proof-of-work, not overhead (agents write one row per tick anyway)
- M-Operator drives the probe (agents don't announce themselves)
- Full audit trail; per-layer granularity
- No special instrumentation: workers already call Clerk for topology data

**How it fits Chimera**:
- ADOPT directly: cycle-based activity window (with configurable ceiling) works across distributed workers
- EXTEND: add `details` JSONB for worker state (e.g., `{"buildings_processed": 5, "errors": 0}`)
- MONITOR: expose `/health` endpoint showing per-agent `last_active_cycle` for orchestrator readiness probes

---

### Pattern 2: Cycle-Scoped Uniqueness Claims (PK Collision)

**Source**: `services/miner/src/miner/work_loop.py:402–413` + `services/miner/models.py` (ProcessedCycle table)

**What it does**: Workers claim exclusive work rights for a cycle+cell by inserting a row with PK uniqueness. First writer wins; losers gracefully skip that cycle.

```python
async def _claim_cycle(cycle_number: int, cell_id: str) -> bool:
    session.add(ProcessedCycle(cycle_number=cycle_number, cell_id=cell_id))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return False
    return True
```

**Why we adopt**:
- No distributed locks: only single-node ACID (Postgres INSERT is atomic)
- Graceful backoff: collision is not an error, just "try next cycle"
- Audit trail: failed claims visible in metrics (`WORKER_SKIP_TICKS_TOTAL`)
- Prevents duplicate writes to `subsurface_cells`

**How it fits Chimera**:
- ADOPT: Same pattern, different tables per worker role
- EXTENSION: Add `claimed_by_agent_id UUID` for debugging collisions
- SCALE: In docker-compose with 3–5 workers, collisions are rare; at 50+ agents, use **partitioned strategy** (agent 0 claims cells 0–9, etc.)

---

### Pattern 3: Signal Handler + asyncio.Event Drain

**Source**: `libs/village_drain/src/village_drain/drain.py` + `services/f_operator/src/f_operator/app.py:56–58`

**What it does**: SIGTERM/SIGINT flip an `asyncio.Event` flag that work loops monitor, allowing in-flight tasks to complete gracefully before teardown.

```python
# Installation (FastAPI lifespan)
drain_flag = asyncio.Event()
install_drain_handlers(drain_flag, service_name="f_operator")

# Handler (drain.py:72–123)
def install_on_loop(loop, drain_flag, *, service_name, signals=(SIGTERM, SIGINT)):
    def _handler(sig):
        if drain_flag.is_set():
            log.info("signal_repeat", signal=sig.name)
            return
        log.info("signal_received", signal=sig.name)
        drain_flag.set()
    for sig in signals:
        loop.add_signal_handler(sig, _handler, sig)

# Work loop monitoring (work_loop.py:1142–1158)
while not self._stopping.is_set():
    cycle_number, source = await self._wait_for_clock_tick()
    if self._stopping.is_set():
        break
    try:
        result = await self._run_one_tick(cycle_number)
    except Exception as exc:
        log.exception("tick_exception", error=str(exc))

# Lifespan teardown (f_operator/app.py:108–126)
finally:
    await drain_and_wait(None, drain_flag, service_name="f_operator", timeout=30.0)
    if consumer is not None:
        await consumer.aclose()
```

Background-task draining (Sprint 93):
```python
if self._background_tasks:
    try:
        await asyncio.wait_for(
            asyncio.gather(*self._background_tasks, return_exceptions=True),
            timeout=30,
        )
    except TimeoutError:
        log.warning("forge_tick_drain_timeout", pending=len(self._background_tasks))
```

**Why we adopt**:
- Signal handlers only set flags (no blocking logic, no DB calls)
- Work loops respect event-loop semantics (await-based)
- Timeout prevents zombie tasks (30s default, configurable)
- Exception suppression on timeout prevents lifespan teardown from crashing

**How it fits Chimera**:
- ADOPT directly: same signal setup, drain flag, timeout
- EXTEND: optional callback for custom cleanup (flush metrics before exit)
- MONITOR: expose drain state on `/health`

---

### Pattern 4: Stateless KFM State Machine

**Source**: `services/clerk/src/clerk/kfm.py:1–168` + `services/clerk/src/clerk/routers/agents.py:1–78`

**What it does**: Agent lifecycle is a table-driven state machine with **no DB access** for validation. HTTP routers check transitions offline, then commit atomically with event publication.

States: `NEW → EXPERIMENTAL → CANDIDATE → STABLE → DEPRECATED → ARCHIVED → KILLED`

Authority table:
```python
TRANSITION_AUTHORITY = {
    ("NEW", "EXPERIMENTAL"): "f",         # F-Operator: Formation
    ("EXPERIMENTAL", "CANDIDATE"): "m",   # M-Operator: first review
    ("CANDIDATE", "STABLE"): "m",         # M-Operator: second review
    ("STABLE", "DEPRECATED"): "k",        # K-Operator: begin decommission
    ("DEPRECATED", "ARCHIVED"): "k",      # K-Operator: cold storage
    ("ARCHIVED", "KILLED"): "k",          # K-Operator: terminal
}
```

Pure check (no DB):
```python
def check_transition(from_state, to_state, operator_type) -> TransitionResult:
    """Pure check: legal transition by authorised operator? Does not raise. Does not touch DB."""
    if from_state not in KFM_STATES: return TransitionResult(False, "unknown_from_state")
    if to_state not in KFM_STATES: return TransitionResult(False, "unknown_to_state")
    if operator_type not in ("f", "m", "k"): return TransitionResult(False, "unknown_operator")
    legal = LEGAL_TRANSITIONS.get(from_state, frozenset())
    if to_state not in legal: return TransitionResult(False, "illegal_transition")
    authorized = TRANSITION_AUTHORITY[(from_state, to_state)]
    if operator_type != authorized:
        return TransitionResult(False, "operator_not_authorized", authorized_operator=authorized)
    return TransitionResult(True, "ok", authorized_operator=authorized)
```

Bootstrap is a privileged escape hatch (`POST /agents/_bootstrap`, `X-Bootstrap-Token`) — only path to STABLE.

**Why we adopt**:
- State machine is external spec (`docs/architecture/README.md` §1)
- Stateless check is unit-testable (no mocking, no fixtures)
- Linear transitions prevent cycles
- Authority table enforces **separation of concerns** per operator
- DB commit + event publish are atomic

**How it fits Chimera**:
- ADOPT: same linear states + authority table
- EXTEND: add intermediate states if needed (e.g., STABLE → DORMANT → AWAKENED) without breaking existing transitions
- MONITOR: expose state transition counts (per operator, per state pair)

(This pattern is canonically documented in `pillar-ontology-drift.md` as the *functional ontology*; here it is treated as a *positioning* mechanism.)

---

### Pattern 5: Circuit Breakers on Peer Service Calls

**Source**: `services/k_operator/src/k_operator/clerk_client.py` + `services/f_operator/src/f_operator/app.py:164–197`

**What it does**: All calls to peer services wrap a circuit breaker that tracks consecutive failures and fast-fails when a peer is down.

States: CLOSED (normal) → OPEN (fast-fail for 30s) → HALF_OPEN (allow 3 probes; if all succeed → CLOSED; one fails → OPEN again).

Config:
```python
clerk = ClerkClient(
    base_url=settings.clerk_url,
    circuit_failure_threshold=3,
    circuit_cooldown_seconds=30,
    circuit_half_open_max_probes=3,
)
```

Health-endpoint integration exposes circuit snapshots so orchestrators can drain traffic before a peer is truly dead. Graceful fallback example (miner `_select_url_from_frontier`, lines 657–689): on `ClerkUnavailable`/`ClerkRejection`, fall back to seed URLs.

**Why we adopt**:
- Prevents cascading failures
- HALF_OPEN allows recovery without full traffic
- Exposed on `/health` for orchestrator decisions
- Pairs naturally with graceful fallbacks

**How it fits Chimera**:
- ADOPT: wrap all peer calls (agents → services)
- EXTEND: metrics for circuit state transitions
- SCALE: monitor circuit health dashboard

---

### Pattern 6: Skip-Memo Cooldown for Capability Rejections

**Source**: `libs/village_worker_guard/src/village_worker_guard/memo.py` + `services/miner/src/miner/work_loop.py:1015–1031`

**What it does**: When Clerk rejects a capability check (403), worker enters a **cooldown** (~30s) and stops retrying that operation, avoiding hammering Clerk.

```python
class SkipTickMemo:
    def record(self, path: str, reason: str) -> None: ...
    def should_skip(self, path: str) -> bool: ...
    def active_count(self) -> int: ...

# Worker usage
if self._skip_memo.should_skip(patch_path):
    WORKER_SKIP_TICKS_TOTAL.labels(service="miner", reason="capability_rejection", path=patch_path).inc()
    return TickResult(status="skipped_capability_rejection", ...)
try:
    await self._clerk.patch_subsurface(...)
except ClerkCapabilityRejection:
    self._skip_memo.record(patch_path, reason="capability_rejection")
```

**Why we adopt**:
- Prevents tight retry loops (would cause 429 on Clerk)
- Per-path cooldown (other operations still run)
- TTL is configurable per rejection reason

**How it fits Chimera**:
- ADOPT: for capability gates on any multi-tenant resource
- EXTEND: different TTLs for transient vs permanent rejections
- MONITOR: graph active cooldowns; alert if stuck > 1 min

---

## Patterns to Reject or Rethink

### Rejection 1: Clerk as Synchronous Single Source of Truth

Village's sync-pull model works at 24 containers but becomes O(N) bottleneck at 50+. Risk: Clerk unavailability → all agents stall. Alternatives: async quorum reads, event-driven push with local cache, partitioned discovery via gossip. **Recommendation**: start with sync-pull for <30 agents; prototype event-driven caching at 30+.

### Rejection 2: Pull-Model Activity Polling by M-Operator

At 50 agents × 10ms per query, M-Operator round takes 500ms. Bottlenecks scaling. Alternatives: push-model with event aggregation, ledger tail reads, or **batch query** (`GET /agents/_activity_batch?agent_ids=...`). **Recommendation**: implement batch endpoint first; defer event push until profiling proves polling is the bottleneck.

### Rejection 3: Per-Building Isolation Without Global Circuit Breaker

Per-building try-except can silently swallow systemic failures. **Recommendation**: add circuit breaker on `list_buildings`; on open, worker enters "safe mode" (seed URLs only).

---

## Open Questions for Chimera Design

1. **Cycle definition in multi-container clusters**: Village derives cycle from local wall time + `CLOCK_CEILING_SECONDS`. Clock skew across hosts can produce divergent cycle numbers. Recommendation: server-side cycle via `GET /time` on Clerk.
2. **Position consistency during partial failures**: When Clerk is unreachable, KFM transitions hang. Stay with eventual consistency + reconciliation on recovery; emit `state_mismatch` for ops review.
3. **Operator ordering & deadlocks**: K-Operator depends on M-Operator's probes. No timeout on M-BASE-01 evaluation can stall the pipeline. Recommendation: bulk activity endpoint + operator health probes with `last_evaluation_at`.
4. **Scaling activity logging**: At 200+ agents × 50 activities/cycle = 10k QPS write load to Postgres. Recommendation: ledger-mode (append-only) for <100 agents; InfluxDB sidecar above that.
5. **Container-to-peer topology discovery**: Hardcoded URLs break in multi-host. For docker-compose, use service-name DNS; for multi-host, Consul/Envoy sidecar or Kubernetes DNS.

---

## References

**Core KFM & State Management**
- `research/_clones/village/services/clerk/src/clerk/kfm.py:1–168` — KFM state machine (pure, stateless)
- `research/_clones/village/services/clerk/src/clerk/routers/agents.py:1–78` — Agent registry & state transition routing

**Activity Log & Heartbeat**
- `research/_clones/village/services/clerk/src/clerk/routers/activity.py:40–124` — `GET /agents/{id}/activity` (M-BASE-01)
- `research/_clones/village/services/clerk/src/clerk/routers/activity.py:163–248` — `POST /agents/{id}/activity` (worker write)
- `research/_clones/village/services/clerk/alembic/versions/0004_agent_activity_log.py` — Activity log schema (Sprint 15)

**Signal Handling & Graceful Shutdown**
- `research/_clones/village/libs/village_drain/src/village_drain/drain.py:34–168` — SIGTERM/SIGINT handler + drain primitives
- `research/_clones/village/services/f_operator/src/f_operator/app.py:40–127` — Lifespan with drain integration
- `research/_clones/village/services/k_operator/src/k_operator/app.py:40–185` — K-Operator lifespan

**Worker Positioning & Cycle Claims**
- `research/_clones/village/services/miner/src/miner/work_loop.py:312–379` — WorkLoop class
- `research/_clones/village/services/miner/src/miner/work_loop.py:402–413` — `_claim_cycle()` (PK collision)
- `research/_clones/village/services/miner/src/miner/work_loop.py:1142–1206` — `run_forever()` with drain monitoring
- `research/_clones/village/services/miner/src/miner/work_loop.py:1212–1255` — Background-task spawning + draining

**Resilience & Circuit Breakers**
- `research/_clones/village/services/k_operator/src/k_operator/clerk_client.py` — Circuit breaker setup
- `research/_clones/village/services/f_operator/src/f_operator/app.py:164–197` — Health endpoint with circuit snapshot
- `research/_clones/village/libs/village_worker_guard/src/village_worker_guard/memo.py` — SkipTickMemo (cooldown)

**Bootstrap & Initialization**
- `research/_clones/village/bootstrap/runner.py:36–105` — One-shot operator bootstrap

**Building & Topology**
- `research/_clones/village/services/clerk/alembic/versions/0010_buildings_and_types.py` — Buildings schema
- `research/_clones/village/services/clerk/src/clerk/routers/topology.py` — Topology endpoints
- `research/_clones/village/libs/village_clerk_client/src/village_clerk_client/mixins/topology.py` — Topology client methods
