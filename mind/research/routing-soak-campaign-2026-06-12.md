# Post-merge validation campaign — 2026-06-12 (keyed local environment)

Executes §2a/§2b of the cloud handoff
([post-merge-validation-2026-06-12.md](../handoff/post-merge-validation-2026-06-12.md))
in the keyed local environment: the all-flags behavioural envelope A/B
(the harness class that caught the ADR 0169 NameError), plus the ADR 0178
dispatch-over-TLS drill. Follow-up to
[routing-soak-campaign-2026-06-08.md](routing-soak-campaign-2026-06-08.md).

**Base:** `main` @ f87d411 (post-#291). **Harness:** `real_task_soak.sh`
(soak_lib v6). **Driver task (both cells):** replace deprecated
`datetime.utcnow()` in `tests/test_model_utilization_sql.py`
(real, one-line, behaviour-neutral; gate = ruff+pytest on that file).

## A/B cells

| | Cell A — ALL flags ON¹ | Cell B — baseline (all OFF) |
|---|---|---|
| Run ID | realtask-2026-06-12-1303 | realtask-2026-06-12-1315 |
| Gate | **PASS** (ruff ✓ pytest ✓) | **PASS** (ruff ✓ pytest ✓) |
| API calls | **18** | **27** |
| Spend | $0.0434 | $0.0163 |
| Models engaged | deepseek-v4-pro + gpt-5-nano | gpt-5-nano only |
| ACT tool calls (cycle 146) | 15 (0 errors) | — |
| Watchdog fires | 1 (600 s silent-death, phase-1 iter 1) | 0 |
| Phase-1 wall | ~10 m (incl. watchdog) | ~4.4 m |
| `tool_entropy`/`tool_calls` in act details | **present** (H=0.0 over shell-only — correct) | **absent** (byte-identical baseline) |
| Model-peer cards written | deepseek / minimax / z-ai (MODEL_PEERS live) | self only |
| Target file edited | **NO** (see Finding 1) | **NO** (see Finding 1) |

¹ `CHIMERA_PEER_SELECTION` `FANOUT_BUDGET` (`MAX_WIDTH=2`) `ANNEAL_REHEAT`
`COMPLEXITY_ROUTING` `TOOL_PREFILTER` `BOLTZMANN_ALLOC` `MODEL_PEERS`
`ENTROPY_SIGNALS`.

## §2a verdict — the handoff's invariant HOLDS

**The all-flags envelope is live-safe.** ACT made real provider calls in
both cells (18 / 27 — emphatically NOT the "0 LLM calls" failure class of
the 2026-06-08 campaign), converged, and the gate passed. No NameError, no
blocked ACT, no flag interaction pathology. The per-flag liveness matrix
(47 cells) plus this live envelope close §2a's headline question.

Flag-attributable deltas, all expected and bounded:
- **MODEL_PEERS** engaged a second vendor (deepseek consults + 3 peer
  cards) → higher per-cycle cost ($0.043 vs $0.016), inside the caps.
- **ENTROPY_SIGNALS** emitted exactly its contract: two extra `details`
  keys + one phase-log line per cycle; H=0.0 over a shell-only
  distribution is the correct fixation-precursor signal. No measurable
  latency contribution (entropy computation is a Counter over ≤15 names;
  ACT wall-time differences are watchdog/model stochasticity).
- The Cell-A watchdog fire matches the 2026-06-08 pattern (cells 1–2 fired
  with flags on AND the baseline cell took the most iterations) — model
  stochasticity, n=1, not flag-attributable.

## Findings (harness, not flags — both cells affected identically)

**Finding 1 — the deliverable never landed, and the gate could not see
the miss.** In BOTH cells the agent wrote its design note / peer cards /
journal but never edited the target file. The gate (ruff+pytest on the
target) passed because a DeprecationWarning fails neither; i.e. the driver
task was *gate-invisible*. Flag-independence is proven by the baseline
cell reproducing the miss exactly. Lesson for future drivers: the task
must be gate-visible (red→green), e.g. run the target under
`-W error::DeprecationWarning`, or use a genuinely failing test. (The
actual one-line fix is landed directly in this PR.)

**Finding 2 — `soft_sentinel_verify_green` fires on a journal-only
diff.** soak_lib v6's "mind/* journal auto-allow" satisfies the phase-1
"real in-scope diff" predicate, so the sentinel concluded phase-1 success
with zero allowlist-file changes — in both cells.

**Finding 3 — the ADR 0148 harness-autocommit message overclaims
provenance.** Both soak commits are titled with the full task description
plus "agent authored+verified; runner executed the commit" while
containing only mind/ artifacts. The autocommit should diff the TASK_FILES
allowlist and either refuse or stamp an honest "journal-only checkpoint"
message. (Chip spawned.)

## §2b verdict — dispatch-over-TLS validated (ADR 0178 closed)

The handoff's predicted gap was real: the MCP SDK's
`streamablehttp_client` hard-codes httpx's certifi verification and httpx
does **not** honour `SSL_CERT_FILE`. Fixed by threading
`MCPServerConfig.tls_ca` → an `httpx_client_factory` pinning `verify=`
(this PR). Evidence:

- `tests/test_remote_federation_tls_drill.py` — three real
  `chimera serve --http` peers serving HTTPS with an openssl self-signed
  cert; the full ADR 0167/0168 stack (trust gate, two-choice selection,
  connectivity gauge) ran over TLS; plus the negative test — an untrusted
  client **fails the handshake** rather than downgrading.
- Operator path live-fired: `CHIMERA_TLS_CERT/KEY=… chimera scenario
  remote_federation_drill` → `ok: True` over HTTPS.

## Graduation consequence (§3 ladder)

`CHIMERA_ENTROPY_SIGNALS` → **default-ON** (ADR 0180, this PR): second
rung after FEDERATION_METRICS. Evidence above — live emission verified ON
(Cell A), byte-identical baseline verified OFF (Cell B), zero hot-path
effect, explicit-disable contract tested. The remaining ladder
(COMPLEXITY_ROUTING/TOOL_PREFILTER on cost-delta; the behavioural trio on
deliverable-landing soak evidence with a gate-visible driver; the peer
pair on default-topology) stays gated.
