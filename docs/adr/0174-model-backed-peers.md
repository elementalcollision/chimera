# ADR 0174 — Model-backed peers (multi-model engagement chain)

**Status:** Accepted (2026-06-12). The module's purpose — being the live-fire
harness for ADR 0167 and 0171 — is fulfilled and certified: round 2 of the
live-fire journal drove the full select→trust-gate→dispatch chain over three
model peers (selection spread 5/4/3, no herding) and the fan-out
trim→defer→recover→complete contract end to end; round 3 reused the harness for
ADR 0168's gauge. Unit surface: `tests/test_model_peers.py` (21 cases). A
genuinely-remote counterpart now also exists (`remote_federation_drill`, round
4) certifying 0167/0168 over real HTTP peers, so model peers are no longer the
*only* federation evidence — they remain the cheap in-process path. Default
stays OFF (`CHIMERA_MODEL_PEERS`); every consult is cost-metered. See
[live-fire-certification-2026-06-10.md](../../mind/research/live-fire-certification-2026-06-10.md)
rounds 2–4.

## Context

The live-fire certification round
([live-fire-certification-2026-06-10.md](../../mind/research/live-fire-certification-2026-06-10.md))
left ADR 0167 (power-of-two peer selection) and ADR 0171 (fan-out budget)
stuck at Proposed for the same structural reason: a single-agent deployment
never **engages multiple models at once**. `select_peer` had no candidates
(no peer federation exists), and the fan-out trim had nothing to trim (one
model emitting one tool call at a time — observed even with the width budget
engineered down to 1).

Meanwhile the pieces for genuine multi-model engagement already exist and are
individually proven: the cross-vendor tier ladders (deepseek, minimax, z-ai,
qwen, mistralai, google, anthropic — ADR 0072/0169), the A2A peer surface
(`mcp-<peer>-chimera-identity` / `-chimera-kfm-state` / capability tools), the
trust gate (`PeerTrustPolicy` / `PeerAwareDispatcher`), and ADR 0167's
selection. What's missing is only the binding: **nothing presents the ladder's
vendors as peers.**

## Decision

Register each cross-vendor ladder rung as a **model-backed peer** behind a
default-OFF flag, using the standard peer surface so the entire existing A2A
stack applies unchanged.

### Code

- `chimera/a2a/model_peers.py` — new module:
  - `model_peers_enabled()` — honours `CHIMERA_MODEL_PEERS` (default off;
    same parsing shape as `peer_selection_enabled`, ADR 0167).
  - `default_vendor_rungs()` — cheapest rung per distinct vendor from the
    SONNET ladder (the deliberate cross-vendor spread). Default: the three
    cheapest vendors (deepseek, minimax, z-ai) so the opt-in stays cheap;
    `CHIMERA_MODEL_PEER_VENDORS` (csv) overrides.
  - `register_model_peers(registry, providers, *, db, cycle_fn, ...)` — for
    each vendor with a live provider, registers peer `model-<vendor>` with:
    - `mcp-model-<vendor>-chimera-identity` — advertises `capabilities:
      ["consult"]`, `kind: "model-peer"`, the backing `model_id`;
    - `mcp-model-<vendor>-chimera-kfm-state` — honest synthetic ALLOW-shaped
      state (T5 / STABLE / drift 0.0): a *local provider binding* has no
      remote plan or drift history; the trust gate still evaluates it on
      every dispatch;
    - `mcp-model-<vendor>-consult` — a **real provider call** to that
      vendor's rung (`question` → answer, attributed `[model_id] ...`),
      metered into the `api_calls` ledger (caller `model_peer:<vendor>`)
      when a db is supplied.
  - `consult_selected_peer(dispatcher, question)` — the ADR 0167 call chain:
    `dispatcher.select_peer("consult")` (two-choice, flag-gated) →
    trust-gated dispatch of the winner's consult tool.
- `chimera/core/loop.py` — flag-gated wiring at loop construction (ACT
  required for provider access); registration failure is non-fatal.
- `chimera/a2a/__init__.py` — exports.

### How this fires 0167 and 0171

- **0167:** `select_peer(CONSULT_CAPABILITY)` now enumerates real,
  trust-eligible, capability-matched candidates and two-choice-picks among
  them; the chain ends in a live cross-vendor model call.
- **0171:** several `mcp-model-*-consult` tools sit in the ACT catalog
  together, and the consult schema explicitly invites using them "in ONE
  response batch" — giving the model a natural reason to emit
  multi-`tool_use` responses, which is the ≥2-wide fan-out the width budget
  needs to trim. (ADR 0171's promotion still requires *observing* that trim
  live; this ADR supplies the source, not the certification.)

## Tests

`tests/test_model_peers.py` — 21 cases: flag parsing; default vendor set =
three cheapest distinct vendors (deepseek leads), env override + unknown
vendors dropped; registration exposes the standard surface and the existing
`list_peer_chimeras` discovers it unmodified; vendors without a live provider
are skipped non-fatally; identity advertises `consult` and the kfm payload
evaluates ALLOW under the real `PeerTrustPolicy`; consult dispatches a real
(faked-provider) call through the trust-gated `PeerAwareDispatcher` with
model attribution; missing `question` errors cleanly; consult is metered into
`api_calls` (cycle + `model_peer:<vendor>` caller); `select_peer` two-choices
over the registered peers; the full select→consult chain returns
`(peer, answer)` and returns `None` when selection is disabled; loop wiring
registers 9 tools (3 vendors × 3) flag-on and nothing flag-off; the consult
schema names batching (the 0171 invitation).

## Non-goals

- **Auto-routing ACT through consult.** The model decides when to use the
  consult tools like any other catalog tool; no phase calls them implicitly.
- **Remote federation.** Model peers are local provider bindings presented
  through the peer abstraction; real cross-Chimera federation (ADR 0168's
  domain) is unchanged and these peers never appear in `mind/peers/`
  registry sync.
- **Council/aggregation semantics.** `consult_selected_peer` returns one
  peer's answer. Multi-peer aggregation (vote, synthesis, cross-critique
  composition) is deferred until a consumer needs it — `cross_critique`
  already covers the adjudication use-case.

## Why this shape

Reusing the peer surface — instead of inventing a parallel "multi-model
client" — means zero new trust machinery: the same policy, journal, circuit
breakers, selection, and dispatch path that will govern real remote peers
govern model peers today. That makes 0167's eventual remote-federation
certification *stronger*, not weaker: the selection rule is exercised against
the exact interfaces a remote peer presents, with the only synthetic part
(kfm-state) clearly labelled and conservative. The flag default stays OFF and
every consult is cost-metered, keeping ADR 0072's observability intact.
