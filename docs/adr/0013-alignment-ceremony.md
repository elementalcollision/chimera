# ADR 0013 — Alignment ceremony (v2.8)

**Status:** Accepted. Anchors v2.8. Loosely modelled on Xenocomm's
five-strategy alignment work, specialised to Chimera's existing
identity + kfm-state data plane (no new wire format).

## Context

A peer's identity (v2.1) tells you who they say they are; their
KFM-state (v2.3) tells you how they say they're doing. Before a
non-trivial cross-agent collaboration — submitting a long-running
sub-task, sharing a mutation, opening a back-and-forth dialogue — you
want one explicit *ceremony* that checks "are we actually in a state
where this will go well?".

That's what v2.8 adds: a pure, in-memory aggregator over five
narrow strategies. No new wire calls — the ceremony consumes the
payloads the caller already fetched.

## Decision: five strategies + one aggregator

| Strategy | What it checks | FAILED vs DRIFTED |
|---|---|---|
| ``capability`` | peer advertises every required capability | missing → FAILED |
| ``version`` | peer's semver-major matches ours | different majors → DRIFTED; unparseable → DRIFTED |
| ``kfm_state`` | peer plan in OK set ({STABLE, CANDIDATE}) | terminal {DEPRECATED, ARCHIVED, KILLED} → FAILED; other → DRIFTED |
| ``schema`` | peer-side tool schema's params match ours | local missing → FAILED; peer-extra → DRIFTED |
| ``drift`` | peer drift composite below lockdown threshold | ≥ threshold → FAILED; missing → ALIGNED (treat as zero) |

The aggregator (:class:`AlignmentCeremony`) takes the peer payloads
the caller already has (typically from :func:`fetch_peer_identity` +
:func:`fetch_peer_kfm`) and runs the four mandatory strategies, plus
``schema`` if a schema pair is passed in. The verdict (:class:`CeremonyVerdict`):

  - all ALIGNED → ``aligned`` (proceed normally)
  - any FAILED → ``failed`` (refuse downstream calls)
  - else → ``drifted`` (proceed with caution / degrade trust tier)

## Why pure, not auto-wired

The dispatcher-level gating already lives in v2.5's
:class:`PeerAwareDispatcher`, which does its own REFUSE/DEGRADE
decision per call. The ceremony is a *higher-level* gate run at
deliberate moments (start of session, before a costly sub-task,
periodically as a health check), not on every dispatch. Keeping it
pure means callers can:

- Run the ceremony before committing to a long-running peer call
- Use the verdict to choose a peer from many ("pick whichever peer
  comes back aligned")
- Run it periodically and snapshot the result into the chronicle

Wiring it into the dispatcher would force it into "every-call" mode,
losing those use cases.

## Mapping back to Xenocomm

Xenocomm's actual five strategies (per its SDK) cover signed identity,
protocol negotiation, alignment-of-purpose, capability matching, and
emergence stability. v2.8's five are an approximate analog:

| Xenocomm | Chimera v2.8 |
|---|---|
| signed identity | (deferred — v2.7 attestation is unsigned) |
| protocol negotiation | ``version_alignment`` (semver-major) |
| alignment of purpose | ``capability_alignment`` |
| capability matching | ``schema_alignment`` |
| emergence stability | ``kfm_state_alignment`` + ``drift_alignment`` |

The shape (five orthogonal checks, FAILED-takes-precedence aggregation)
is the contribution from Xenocomm's research. The data each check
reads is Chimera-native (identity payload, kfm-state payload).

## What v2.8 *doesn't* do

- **No protocol evolution.** Emergence-aware change negotiation (peers
  agreeing to upgrade their wire shape together) stays v2.9.
- **No cryptographic attestation.** Signed identity claims would
  strengthen ``capability_alignment`` and the inbound attestation in
  [ADR 0012](./0012-inbound-attestation.md). Both block on a peer-registry-as-authority that doesn't
  exist yet.
- **No periodic auto-run.** Callers run the ceremony when they want.
  A future hook could schedule one per cycle's FLUSH phase.

## References

- [ADR 0005](0005-multi-agent-architecture.md) §"What v2.x will need" — alignment listed
- [ADR 0006](0006-identity-handshake.md) — identity payload input
- [ADR 0008](0008-swarm-kfm.md) — kfm-state payload input
- [ADR 0009](0009-cross-agent-trust.md) — drift threshold + REFUSE/DEGRADE pattern
- Xenocomm SDK — alignment strategies, EmergenceManager
- [chimera/a2a/alignment.py](../../chimera/a2a/alignment.py)
