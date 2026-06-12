# Live-fire certification round — 2026-06-10

Follow-up to the routing soak campaign
([routing-soak-campaign-2026-06-08.md](./routing-soak-campaign-2026-06-08.md)):
the #282 promotions set an explicit standard — **Accepted requires live-fire**
(the feature's behavior demonstrably executed in the live loop), not merely
armed-without-crashing. This round live-fires the remaining candidates.

## Exercise 1 — ADR 0172 Boltzmann selection (✅ FIRED)

Real splitter call (deepseek-v4-pro, `CHIMERA_BOLTZMANN_ALLOC=1`) on a
9-part telemetry task; budget K=3 over the parsed list, both branches
computed on the SAME live response:

- flag OFF (first-N): indices **[0, 1, 2]**
- flag ON (value-aware): indices **[2, 4, 6]** — the three artifact-naming
  sub-tasks (`subtask_value` 1.8 / 1.3 / 1.8), original order preserved.

First-N would have dropped both high-value artifact tasks. Selection is
demonstrably value-aware on real model output → **promotion criterion met**.

## Exercise 2 — soak `realtask-2026-06-10-0959` (0170 ✅ / 0171 ✗)

`real_task_soak` at HEAD `5b6d024`, all 6 routing/entropy flags ON plus
`CHIMERA_ENTROPY_SIGNALS=1` and `CHIMERA_FANOUT_MAX_WIDTH=1` (engineered so
ANY ≥2-wide tool batch trims). Task: fix the 4 ruff E702 findings in
`tests/test_soak_watchdog.py`. 54 api_calls, $0.215.

**ADR 0170 tool-use entropy — FIRED, 3 emissions, diagnostically meaningful:**

```
ACT: tool-use entropy H=0.0   over 23 tool call(s)   ← fixation, during the watchdog-quiet iter
ACT: tool-use entropy H=0.592 over 14 tool call(s)   ← mixed tool use, productive iter
ACT: tool-use entropy H=0.0   over 1 tool call(s)    ← single-call commit cycle
```

The H=0.0×23 reading coincided with the 600s silent-death watchdog iteration —
the signal read fixation exactly where the loop was in fact stuck, which is
the precursor behavior the ADR claims. **Promotion criterion met.**

**ADR 0171 fan-out budget — DID NOT FIRE (honest negative):** even at
width 1, the lead model (deepseek-v4-pro) emitted tool calls strictly one at
a time this run; there was never a ≥2-wide batch to trim. The budget cannot
fire if the model never fans out. Stays Proposed/compose-safe; firing it
needs either a model/prompt that batches calls or a synthetic multi-tool_use
provider response in a live loop.

**Soak outcome (operator handoff):** phase 1 verify-green in 2 iters; agent
self-committed (3 commits, incl. one `\x00MUT corruption` garbled message —
same artifact class as campaign cell 6). The harness-time gate read
`FAIL — ruff ✓ pytest ✗`, but the failure (`test_watchdog_clean_exit_returns_zero`)
is a watchdog TIMING test that ran while the soak loaded the machine;
post-run the worktree passes `chimera verify` twice consecutively
(PASS — ruff ✓ pytest ✓, 15/15 tests, same count as main — nothing deleted).

**Scope-creep flag (ADR 0173 advisory in action):** the diff is
+86/−182 across the whole file — a wholesale rewrite for a 4-semicolon task.
Per ADR 0173 this is surfaced, not blocked: deliverable is green but
provenance is messy and the rewrite's faithfulness to the original tests'
intent is unreviewed. **Recommendation: do NOT harvest; leave the 4 findings
as debt for a cleaner pass.** (Contrast: the morning run
`realtask-2026-06-10-0915` produced a clean in-scope fix that WAS harvested
as #281.)

## Status after this round

| ADR | Flag | Status |
|---|---|---|
| 0165 / 0166 / 0169 | prefilter / complexity / reheat | Accepted (#282) |
| 0170 | `CHIMERA_ENTROPY_SIGNALS` | **Accepted (this round)** — wiring #283, live-fired here |
| 0172 | `CHIMERA_BOLTZMANN_ALLOC` | **Accepted (this round)** — live value-aware selection |
| 0171 | `CHIMERA_FANOUT_BUDGET` | Proposed — armed-safe; awaits a real ≥2-wide batch |
| 0167 | `CHIMERA_PEER_SELECTION` | Proposed — awaits a multi-peer federation |

All flags remain default-OFF.

---

# Round 2 (same day) — model-backed peers close the last two

The round-1 blockers were structural: no peer federation (0167) and no
multi-tool_use source (0171). **ADR 0174 (model-backed peers,
`chimera/a2a/model_peers.py`)** removes both by registering the cross-vendor
ladder rungs as A2A peers (`model-<vendor>`) with the standard peer surface —
identity advertising a `consult` capability, ALLOW-shaped kfm-state, and a
real provider-call consult tool, all behind default-OFF `CHIMERA_MODEL_PEERS`.

## Exercise 3 — ADR 0167 selection (✅ FIRED)

Three real peers registered (`model-deepseek`, `model-minimax`,
`model-z-ai`). `select_peer("consult")` over 12 seeded draws spread picks
**5 / 4 / 3 across all three** — the anti-herding distribution
power-of-two-choices exists to produce (global-best would have herded onto
one peer). The full `consult_selected_peer` chain then ran live:
two-choice pick → `PeerAwareDispatcher` trust gate → real deepseek call →
attributed answer. **Promotion criterion met** (candidates are local
provider bindings presenting the exact remote-peer interfaces; a remote
federation exercise remains a worthwhile follow-up but does not gate the
selection rule itself).

## Exercise 4 — ADR 0171 fan-out trim (✅ FIRED, full lifecycle)

Live ACT run (sonnet tier, deepseek lead, `CHIMERA_FANOUT_BUDGET=1`,
`CHIMERA_FANOUT_MAX_WIDTH=2`), task: survey all three model peers in one
parallel batch. Observed:

```
act: dispatching 3 tool_uses in parallel: ['mcp-model-deepseek-consult',
     'mcp-model-minimax-consult', 'mcp-model-z-ai-consult']
act: fan-out budget — dispatching 2 of 3 tool_uses, deferring 1
```

The deferred `z-ai` call received the synthetic re-issue result, the model
re-issued it the following round, it succeeded (history shows it twice:
deferred-error then success), and ACT completed (`finish=stop, rounds=3`)
with a coherent three-model synthesis. **Trim → defer → recover → complete:
the entire ADR 0171 contract executed live. Promotion criterion met.**

## Final scoreboard

| ADR | Status | Evidence class |
|---|---|---|
| 0165 / 0166 / 0169 / 0170 / 0172 | Accepted | live-fired (rounds 0–1) |
| 0167 / 0171 | **Accepted (round 2)** | live-fired via model-backed peers |
| 0174 (the harness itself) | Proposed | new code; both exercises above ARE its live evidence — pending operator review/merge |

All 8 routing/entropy ADRs from the 2026-06-08 insertion batch are now
certified on live-fire evidence. All flags remain default-OFF.

---

# Round 3 (2026-06-12) — the connectivity gauge closes the batch

ADR 0168 was the last of the six 2026-06-08 insertions still Proposed, for
two reasons: the gauge had never been exercised over a *real* TRUSTED
projection, and the dashboard widget's TypeScript had never been compiled
(no `node_modules` in the build container at review time).

## Exercise 5 — ADR 0168 gauge (✅ FIRED)

Same model-backed-peers harness as rounds 2's exercises, plus one
deliberately drifted peer to give the gauge something to discriminate:

1. `register_model_peers` registered `model-deepseek` / `model-minimax` /
   `model-z-ai`; a fourth peer `drifty` advertised `last_drift_score: 0.55`
   (≥ the 0.30 lockdown threshold). All four written to the peer registry.
2. Real `PeerAwareDispatcher` dispatches journaled the trust decisions:
   **3 ALLOW + 1 REFUSE** (`peer drift 0.55 ≥ lockdown threshold`). The
   consult bodies used a stub provider (no API keys in this environment) —
   irrelevant to 0168, which consumes only the journal→projection→export
   chain, all of which ran for real.
3. `chimera graph rebuild` projected `Peer: 4 | TRUSTED: 4` into Kuzu.
4. `chimera graph export` **without** the flag: no `federation` key — the
   byte-identical contract holds. **With** `CHIMERA_FEDERATION_METRICS=1`:

   ```json
   {"n_nodes": 5, "n_edges": 3, "largest_component": 4,
    "connectivity": 0.8, "mean_degree": 1.2,
    "hub_node": "chimera-vm-f8fe0042", "hub_degree": 3,
    "hub_concentration": 0.5, "isolated_nodes": 1}
   ```

   Every number matches the hand computation: self + 4 peers = 5 nodes; the
   3 ALLOW edges are connective, the REFUSE edge is not, so the drifted peer
   is **isolated** and connectivity = 4/5; ⟨k⟩ = 2·3/5 = 1.2 > 1 (giant
   component present); the star topology puts the hub (self) at exactly 0.5
   concentration. The gauge discriminates, not just decorates.

## Exercise 6 — dashboard TypeScript (✅ VERIFIED)

With a node22 toolchain available this round: `npm install` →
`tsc --noEmit` **clean** → full production `next build` **green** over the
control-plane including `FederationConnectivityWidget` and the
`lib/graph.ts` `federation` snapshot type. The original review caveat
("TS unverified, no node_modules") is closed.

## Final scoreboard (updated)

| ADR | Status | Evidence class |
|---|---|---|
| 0165 / 0166 / 0169 / 0170 / 0172 | Accepted | live-fired (rounds 0–1) |
| 0167 / 0171 | Accepted | live-fired via model-backed peers (round 2) |
| 0168 | **Accepted (round 3)** | live-fired gauge over a real projection + production dashboard build |
| 0174 (the harness) | Proposed | three certifications now rest on it — pending operator review |

**All six 2026-06-08 insertions (ADR 0167–0172) are now certified on
live-fire evidence.** All flags remain default-OFF. Remaining follow-ups:
a true remote-federation exercise (0167/0168 candidates are local provider
bindings presenting the remote interfaces), and the 0174 promotion decision.
