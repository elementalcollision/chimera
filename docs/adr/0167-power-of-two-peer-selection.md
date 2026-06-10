# ADR 0167 — Power-of-two-choices peer selection (v4.120)

**Status:** Accepted (2026-06-10). Compose-safety validated in the post-fix
all-flags soak (flag armed, no regression), then **live-fired via
model-backed peers (ADR 0174)**: with three real peers registered
(`model-deepseek` / `model-minimax` / `model-z-ai`), `select_peer("consult")`
spread its picks 5/4/3 across all three over 12 seeded draws — the
no-herding property power-of-two-choices exists for — and the full
select→trust-gate→dispatch chain ended in a real cross-vendor provider call.
The candidates are local provider bindings presenting the exact remote-peer
interfaces; a remote-federation exercise remains worthwhile but the selection
rule itself is certified. See
[live-fire-certification-2026-06-10.md](../../mind/research/live-fire-certification-2026-06-10.md)
round 2. Default remains OFF (`CHIMERA_PEER_SELECTION`).

## Context

The A2A dispatch path is **single-target**. The tool name
`mcp-<peer>-<tool>` hard-codes which peer is called, and
`PeerAwareDispatcher` (`a2a/peer_dispatch.py`) only *gates* that call —
ALLOW / DEGRADE / REFUSE on trust tier + KFM plan state + drift
(`a2a/trust_policy.py`). When two peers both advertise a capability,
**nothing chooses between them**: there is no candidate enumeration, no
scoring, no load balancing, and no randomness anywhere in the peer path.

The investigation in
[entropy-graph-subtasking-2026-06-06.md](../research/entropy-graph-subtasking-2026-06-06.md)
ranked this the **#1** insertion — highest value, lowest risk — because it
fills a genuine gap rather than tuning an existing knob. The relevant result
is Mitzenmacher's **"power of two choices"**: when several servers can handle a
request, sampling **two at random** and routing to the less-loaded one yields
an *exponential* improvement in worst-case load over uniform-random, while
avoiding the herding that "always pick the single best" causes — at near-zero
cost. The pieces it needs already exist: `list_peer_chimeras`
(`a2a/peers.py`) enumerates peers, `fetch_peer_kfm` / `fetch_peer_identity`
expose drift + capabilities, `PeerTrustPolicy` decides eligibility, and
`CircuitBreaker` (`positioning/circuit.py`) tracks per-peer health — none of
them were ever wired into a selection step.

## Decision

A new module adds peer selection behind a default-OFF flag, leaving the
dispatch path byte-identical until a caller opts in.

### Code

- `chimera/a2a/peer_selection.py` — new module:
  - `peer_selection_enabled()` — honours `CHIMERA_PEER_SELECTION` (default
    off; same parsing shape as `tool_prefilter_enabled`, ADR 0165).
  - `PeerCandidate` — a peer with its selection signals (`name`,
    `drift_score`, `healthy`); `load_key()` sorts **lower = better**, with
    healthy peers always ahead of unhealthy ones and lower drift winning
    within a health class. Unknown drift defaults to the lockdown threshold
    (0.30) so it loses to any known-lower peer but beats a known-higher one.
  - `choose(candidates, *, rng)` — the **pure** power-of-two rule: 0 → None,
    1 → it, ≥2 → sample two at random and return the better `load_key`. RNG is
    injectable for deterministic tests.
  - `select_peer(capability, *, registry, policy, breakers, rng)` — async
    orchestrator: enumerates peers, fetches state **concurrently**, drops any
    the policy would REFUSE (or that does not advertise `capability` when one
    is given), folds in circuit-breaker health, and calls `choose`. Returns
    the `<peer>` segment (ready to compose into `mcp-<peer>-<tool>`) or `None`.
    A peer whose state can't be fetched is skipped, never fatal.
- `chimera/a2a/peer_dispatch.py` — `PeerAwareDispatcher` gains a `breakers`
  dict (per-peer `CircuitBreaker`s; absent ⇒ healthy) and an additive
  `async select_peer(capability)` method that returns `None` unless the flag
  is enabled, then delegates to the module with this dispatcher's registry,
  policy, and breakers.
- `chimera/a2a/__init__.py` — export `select_peer`, `choose`,
  `PeerCandidate`, `peer_selection_enabled`.

### CLI / dashboard

None. Operator surface is the `CHIMERA_PEER_SELECTION` env flag. The dispatch
path is unchanged; `select_peer` is additive and called by no one
automatically, so default behaviour is byte-identical.

## Tests

`tests/test_peer_selection.py` — 28 cases:
- flag parsing across truthy/falsy spellings (off by default);
- pure `choose`: empty → None, single → it, two → lower-drift winner
  (deterministic — both are always sampled), healthy beats lower-drift
  unhealthy, unknown drift loses to known-lower, three-candidate sampling
  with a seeded RNG;
- `select_peer`: no peers → None, picks lower-drift among eligible, drops a
  REFUSED (high-drift) peer, all-ineligible → None, capability filter
  includes/excludes correctly, an OPEN-breaker peer loses to a healthy one,
  and an unfetchable-state peer is skipped rather than crashing;
- the dispatcher method returns None when disabled and a peer when enabled.

Full suite: the new file is 28 passing; the existing `test_peer_dispatch`
(18) and `test_peer_registry` suites stay green.

## Non-goals

- **Wiring selection into the hot dispatch path.** `select_peer` is an
  additive helper; auto-routing model-issued `mcp-<peer>-<tool>` calls through
  it (rewriting the hard-coded peer) is a separate, behaviour-changing step.
- **Populating the circuit breakers.** The `breakers` dict is the seam;
  recording per-peer call outcomes into it is follow-up. An absent breaker is
  treated as healthy, so selection is correct meanwhile.
- **Capability-cluster / SBM redundancy** (research §2b) and the
  **percolation connectivity gauge** (#2) over the Kuzu `TRUSTED` projection —
  tracked separately.

## Why this shape

The pure/async split keeps the power-of-two rule unit-testable without a live
federation, mirroring how `trust_policy` keeps `PeerTrustPolicy` pure and
isolates the cache. Selection is layered **on top of** the existing trust gate
— it only ever chooses among peers the policy already deems non-REFUSE — so it
can never widen trust, only pick more wisely within it. Sampling *two* (not
argmin over all) is deliberate: global-best routing herds every request onto
the single lowest-drift peer until it degrades, which is exactly the failure
power-of-two-choices exists to avoid.
