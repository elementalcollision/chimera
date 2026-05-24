# ADR index

130 architecture decision records. Listed in numeric order. "Status" is the
last column; "Accepted" means in force, "Deferred" means decided not to do
this yet (with rationale), "Superseded by N" means later ADR replaces.

| File | Title | Status |
|---|---|---|
| [0001-sdk-chimera-boundaries.md](./0001-sdk-chimera-boundaries.md) | ADR 0001 — SDK Chimera Boundaries | Accepted (pending Phase 0 sign-off) |
| [0002-memory-strategy.md](./0002-memory-strategy.md) | ADR 0002 — Memory Strategy | Accepted (pending Phase 0 sign-off) |
| [0003-reggio-loop.md](./0003-reggio-loop.md) | ADR 0003 — Reggio Loop Adoption | Proposed (recommendation; awaits user mark-up) |
| [0004-xenocomm-a2a.md](./0004-xenocomm-a2a.md) | ADR 0004 — Xenocomm / A2A integration (spike) | Proposed (spike). Closes the v2 deferral in [ADR 0001](0001-sdk-chimera-boundaries.md) |
| [0005-multi-agent-architecture.md](./0005-multi-agent-architecture.md) | ADR 0005 — Multi-agent architecture (v2.0) | Accepted. Anchors v2.0. Successor entries codify each |
| [0006-identity-handshake.md](./0006-identity-handshake.md) | ADR 0006 — Peer identity handshake (v2.1) | Accepted. Anchors v2.1. Sits between [ADR 0005](0005-multi-agent-architecture.md) |
| [0007-peer-registry.md](./0007-peer-registry.md) | ADR 0007 — Peer registry (v2.2) | Accepted. Anchors v2.2. Builds on |
| [0008-swarm-kfm.md](./0008-swarm-kfm.md) | ADR 0008 — Swarm-KFM read-only view (v2.3) | Accepted. Anchors v2.3. Sits between |
| [0009-cross-agent-trust.md](./0009-cross-agent-trust.md) | ADR 0009 — Cross-agent trust (outbound) (v2.4) | Accepted. Anchors v2.4. Builds on the data plumbing of |
| [0010-peer-aware-dispatcher.md](./0010-peer-aware-dispatcher.md) | ADR 0010 — PeerAwareDispatcher (v2.5) | Accepted. Anchors v2.5. Closes the "wire the policy in" |
| [0011-http-transport.md](./0011-http-transport.md) | ADR 0011 — HTTP/SSE transport for chimera serve (v2.6) | Accepted. Anchors v2.6. Originally listed in |
| [0012-inbound-attestation.md](./0012-inbound-attestation.md) | ADR 0012 — Inbound peer attestation (v2.7) | Accepted. Anchors v2.7. The inbound complement to |
| [0013-alignment-ceremony.md](./0013-alignment-ceremony.md) | ADR 0013 — Alignment ceremony (v2.8) | Accepted. Anchors v2.8. Loosely modelled on Xenocomm's |
| [0014-emergence-protocol-journal.md](./0014-emergence-protocol-journal.md) | ADR 0014 — Emergence-aware protocol journal (v2.9) | Accepted. Anchors v2.9. Closes the last open item on the |
| [0015-graph-store.md](./0015-graph-store.md) | ADR 0015 — LadybugDB graph store | Accepted (2026-05-18) |
| [0016-graph-powered-features.md](./0016-graph-powered-features.md) | ADR 0016 — Graph-powered features (v3.0) | Accepted (2026-05-18) |
| [0017-graph-edges-v3-1.md](./0017-graph-edges-v3-1.md) | ADR 0017 — Closing the remaining graph edges (v3.1) | Accepted (2026-05-18) |
| [0018-operational-hardening.md](./0018-operational-hardening.md) | ADR 0018 — Operational hardening (v3.3) | Accepted (2026-05-18) |
| [0019-provider-retry-backoff.md](./0019-provider-retry-backoff.md) | ADR 0019 — Provider retry/backoff (v3.5) | Accepted (2026-05-18) |
| [0020-boot-config-validator.md](./0020-boot-config-validator.md) | ADR 0020 — Boot-time config validator (v3.6) | Accepted (2026-05-18) |
| [0021-cross-host-peer-sync.md](./0021-cross-host-peer-sync.md) | ADR 0021 — Cross-host peer registry sync (v3.7) | Accepted (2026-05-18) |
| [0022-emergence-v3.md](./0022-emergence-v3.md) | ADR 0022 — Emergence v3: auto-record + cross-host journal sync | Accepted (2026-05-18) |
| [0023-multi-host-demo.md](./0023-multi-host-demo.md) | ADR 0023 — Multi-host demo scenario (v3.10) | Accepted (2026-05-19) |
| [0024-act-ladder-escalation.md](./0024-act-ladder-escalation.md) | ADR 0024 — ACT ladder escalation under retry (v3.11) | Accepted (2026-05-19) |
| [0025-v4-stability.md](./0025-v4-stability.md) | ADR 0025 — v4.0 stability promises | Accepted (2026-05-19) |
| [0026-artifact-verification.md](./0026-artifact-verification.md) | ADR 0026 — Artifact verification (v4.3) | Accepted (2026-05-19) |
| [0027-shell-default-cwd.md](./0027-shell-default-cwd.md) | ADR 0027 — Shell default cwd is the mind+state common parent (v4.4) | Accepted (2026-05-19) |
| [0028-adaptive-budgets.md](./0028-adaptive-budgets.md) | ADR 0028 — Adaptive budgets + fragmentation auto-mutation (v4.5) | Accepted (2026-05-19) |
| [0029-assembler-ladder.md](./0029-assembler-ladder.md) | ADR 0029 — Skill-assembler tier escalation (v4.6) | Accepted (2026-05-19) |
| [0030-assembler-critique-loop.md](./0030-assembler-critique-loop.md) | ADR 0030 — Assembler prompt refinement + critique-and-revise loop (v4.7) | Accepted (2026-05-19) |
| [0031-multi-witness-critique.md](./0031-multi-witness-critique.md) | ADR 0031 — Multi-witness critique + expanded opus ladder (v4.8) | Accepted (2026-05-19) |
| [0032-named-rungs-assembly-journal.md](./0032-named-rungs-assembly-journal.md) | ADR 0032 — Named-rung selection + skill-assembly journal + dashboard (v4.9) | Accepted (2026-05-19) |
| [0033-canvas-dashboard.md](./0033-canvas-dashboard.md) | ADR 0033 — Canvas dashboard shell with draggable widgets (v4.11) | Accepted (2026-05-19) |
| [0034-engines-kill-switch.md](./0034-engines-kill-switch.md) | ADR 0034 — Engines kill-switch covers planner + daily engines (v4.12) | Accepted (2026-05-19) |
| [0035-cross-provider-defaults.md](./0035-cross-provider-defaults.md) | ADR 0035 — Cross-provider witness defaults (v4.13) | Accepted (2026-05-19) |
| [0036-tiers-json-export.md](./0036-tiers-json-export.md) | ADR 0036 — `chimera tiers --json` exporter + dashboard sync (v4.14) | Accepted (2026-05-19) |
| [0037-drift-time-series.md](./0037-drift-time-series.md) | ADR 0037 — Drift composite time series + sparkline (v4.15) | Accepted (2026-05-19) |
| [0038-mlc-canvas-design.md](./0038-mlc-canvas-design.md) | ADR 0038 — Port Chimera Canvas design (MLC brand + 14 widgets) (v4.16) | Accepted (2026-05-19) |
| [0039-deferred-designer-items.md](./0039-deferred-designer-items.md) | ADR 0039 — Deferred designer items: view presets, auto-refresh, cost-over-time (v4.17) | Accepted (2026-05-19) |
| [0040-parallel-tool-dispatch.md](./0040-parallel-tool-dispatch.md) | ADR 0040 — Parallel tool dispatch in ACT (v4.18) | Accepted (2026-05-19) |
| [0041-proposer-recurrence.md](./0041-proposer-recurrence.md) | ADR 0041 — Auto-proposer recurrence + queue health (v4.19) | Accepted (2026-05-19) |
| [0042-peer-federation-drill.md](./0042-peer-federation-drill.md) | ADR 0042 — Peer federation drill (v4.20) | Accepted (2026-05-19) |
| [0043-ontology-audit.md](./0043-ontology-audit.md) | ADR 0043 — Memory / ontology audit (v4.21) | Accepted (2026-05-19) |
| [0044-ladybug-stress-test.md](./0044-ladybug-stress-test.md) | ADR 0044 — LadybugDB graph stress test (v4.22) | Accepted (2026-05-19) |
| [0045-graph-rebuild-perf.md](./0045-graph-rebuild-perf.md) | ADR 0045 — Graph rebuild perf via UNWIND batching (v4.23) | Accepted (2026-05-19) |
| [0046-auto-archive-deprecated.md](./0046-auto-archive-deprecated.md) | ADR 0046 — Auto-archive stale DEPRECATED entities (v4.24) | Accepted (2026-05-19) |
| [0047-dashboard-parity.md](./0047-dashboard-parity.md) | ADR 0047 — Dashboard parity for queue health + ontology audit (v4.25) | Accepted (2026-05-19) |
| [0048-trust-gating-drill.md](./0048-trust-gating-drill.md) | ADR 0048 — Trust-gating federation drill (v4.26) | Accepted (2026-05-19) |
| [0049-hyphenated-peer-names.md](./0049-hyphenated-peer-names.md) | ADR 0049 — Fix peer_name_from_tool for hyphenated peers (v4.27) | Accepted (2026-05-19) |
| [0050-degrade-path-drill.md](./0050-degrade-path-drill.md) | ADR 0050 — DEGRADE-path trust drill (v4.28) | Accepted (2026-05-19) |
| [0051-http-federation-drill.md](./0051-http-federation-drill.md) | ADR 0051 — HTTP transport federation drill (v4.29) | Accepted (2026-05-19) |
| [0052-reanchor-history.md](./0052-reanchor-history.md) | ADR 0052 — Re-anchor history widget (v4.30) | Accepted (2026-05-19) |
| [0053-incremental-projection.md](./0053-incremental-projection.md) | ADR 0053 — Incremental graph projection (v4.31) | Accepted (2026-05-19) |
| [0054-housekeeping-graph-update.md](./0054-housekeeping-graph-update.md) | ADR 0054 — Auto-incremental graph in housekeeping (v4.32) | Accepted (2026-05-19) |
| [0055-tool-fanout-telemetry.md](./0055-tool-fanout-telemetry.md) | ADR 0055 — Tool-fanout telemetry (v4.33) | Accepted (2026-05-19) |
| [0056-fanout-by-model-and-history.md](./0056-fanout-by-model-and-history.md) | ADR 0056 — Per-model + time-series fan-out telemetry (v4.34) | Accepted (2026-05-19) |
| [0057-mutating-row-incremental.md](./0057-mutating-row-incremental.md) | ADR 0057 — Incremental projection for mutating rows (v4.35) | Accepted (2026-05-19) |
| [0058-cost-per-fanout.md](./0058-cost-per-fanout.md) | ADR 0058 — Cost-per-fanout correlation (v4.37) | Accepted (2026-05-19) |
| [0059-skill-wiki-mtime-gate.md](./0059-skill-wiki-mtime-gate.md) | ADR 0059 — Skill/wiki incremental via mtime gate (v4.38) | Accepted (2026-05-19) |
| [0060-kill-archived-workflow.md](./0060-kill-archived-workflow.md) | ADR 0060 — ARCHIVED → KILLED operator workflow (v4.39) | Accepted (2026-05-19) |
| [0061-cross-round-parallelism-deferred.md](./0061-cross-round-parallelism-deferred.md) | ADR 0061 — Cross-round tool parallelism (v4.40, deferred design) | Deferred (2026-05-19) |
| [0062-pressure-point-remediations.md](./0062-pressure-point-remediations.md) | ADR 0062 — Pressure-point remediations (v4.41) | Accepted (2026-05-19) |
| [0063-continuation-context.md](./0063-continuation-context.md) | ADR 0063 — Cross-round continuation context (v4.42) | Accepted (2026-05-19) |
| [0064-container-bootstrap.md](./0064-container-bootstrap.md) | ADR 0064 — Container bootstrap (v4.45) | Accepted (2026-05-19) |
| [0065-task-escalation-memory.md](./0065-task-escalation-memory.md) | ADR 0065 — Persistent task-escalation memory (v4.46) | Accepted (2026-05-19) |
| [0066-tier-aware-budget.md](./0066-tier-aware-budget.md) | ADR 0066 — Tier-aware adaptive budget (v4.47) | Accepted (2026-05-19) |
| [0067-escalations-cli.md](./0067-escalations-cli.md) | ADR 0067 — `chimera escalations` CLI verb (v4.48) | Accepted (2026-05-19) |
| [0068-subagent-failure-visibility.md](./0068-subagent-failure-visibility.md) | ADR 0068 — Sub-agent failure visibility (v4.49) | Accepted (2026-05-19) |
| [0069-round-boundary-instrumentation.md](./0069-round-boundary-instrumentation.md) | ADR 0069 — Round-boundary latency instrumentation (v4.50) | Accepted (2026-05-19) |
| [0070-model-utilization-widget.md](./0070-model-utilization-widget.md) | ADR 0070 — Model utilization (engine pressure) widget (v4.51) | Accepted (2026-05-19) |
| [0071-http-bind-security.md](./0071-http-bind-security.md) | ADR 0071 — HTTP bind security guard (v4.52) | Accepted (2026-05-19) |
| [0072-cost-runaway-guards.md](./0072-cost-runaway-guards.md) | ADR 0072 — Cost-runaway guards + opus ladder inversion (v4.53) | Accepted (2026-05-19) |
| [0073-observability-tightening.md](./0073-observability-tightening.md) | ADR 0073 — Engine + cost observability tightening (v4.54) | Accepted (2026-05-20) |
| [0074-audit-and-kfm-safety.md](./0074-audit-and-kfm-safety.md) | ADR 0074 — audit.py transaction safety + KFM bootstrap scoping (v4.55) | Accepted (2026-05-20) |
| [0075-task-conventions-and-tier-floor.md](./0075-task-conventions-and-tier-floor.md) | ADR 0075 — Task conventions + research-tier floor (v4.56) | Accepted (2026-05-20) |
| [0076-rolling-cost-cap-and-cost-usd-population.md](./0076-rolling-cost-cap-and-cost-usd-population.md) | ADR 0076 — Rolling-hour cost cap + cost_usd population (v4.57) | Accepted (2026-05-20) |
| [0077-cost-cli.md](./0077-cost-cli.md) | ADR 0077 — `chimera cost` CLI verb (v4.58) | Accepted (2026-05-20) |
| [0078-cost-estimate.md](./0078-cost-estimate.md) | ADR 0078 — Pre-flight cost estimation (v4.59) | Accepted (2026-05-20) |
| [0079-task-budget.md](./0079-task-budget.md) | ADR 0079 — Per-task budget cap (v4.60) | Accepted (2026-05-20) |
| [0080-wiki-fts-search.md](./0080-wiki-fts-search.md) | ADR 0080 — mind/wiki FTS5 search (v4.61) | Accepted (2026-05-20) |
| [0081-optional-graph-projection.md](./0081-optional-graph-projection.md) | ADR 0081 — Graph projection is opt-in (v4.62) | Accepted (2026-05-20) |
| [0082-task-splitter.md](./0082-task-splitter.md) | ADR 0082 — Task splitter (v4.63) | Accepted (2026-05-20) |
| [0083-dead-entity-query-fix.md](./0083-dead-entity-query-fix.md) | ADR 0083 — Audit `dead_entity` query uses transitions, not activity log (v4.64) | Accepted (2026-05-20) |
| [0084-auto-loop-task-splitter.md](./0084-auto-loop-task-splitter.md) | ADR 0084 — Auto-loop task splitter integration (v4.65) | Accepted (2026-05-20) |
| [0085-cost-runaway-drill.md](./0085-cost-runaway-drill.md) | ADR 0085 — Cost runaway drill scenario (v4.66) | Accepted (2026-05-20) |
| [0086-doctor-cost-check.md](./0086-doctor-cost-check.md) | ADR 0086 — `chimera doctor` cost-caps check (v4.67) | Accepted (2026-05-20) |
| [0087-hot-signatures-widget.md](./0087-hot-signatures-widget.md) | ADR 0087 — Hot-signatures dashboard widget (v4.68) | Accepted (2026-05-20) |
| [0088-engine-telemetry.md](./0088-engine-telemetry.md) | ADR 0088 — Engine telemetry: `engine_runs` table + `caller` column (v4.69) | Accepted (2026-05-20) |
| [0089-engine-signal-density-gates.md](./0089-engine-signal-density-gates.md) | ADR 0089 — Engine signal-density gates (v4.70) | Accepted (2026-05-20) |
| [0090-proposer-acceptance-scoring.md](./0090-proposer-acceptance-scoring.md) | ADR 0090 — Proposer acceptance-rate scoring → demotion (v4.71) | Accepted (2026-05-20) |
| [0091-selective-engine-enable.md](./0091-selective-engine-enable.md) | ADR 0091 — Selective per-engine enable (v4.72) | Accepted (2026-05-20) |
| [0092-session-relative-engine-mode.md](./0092-session-relative-engine-mode.md) | ADR 0092 — Session-relative engine routing + code_exec cwd fix (v4.74) | Accepted (2026-05-20) |
| [0093-nl-artifact-validation.md](./0093-nl-artifact-validation.md) | ADR 0093 — NL artifact validation + non-empty check (v4.79) | Accepted (2026-05-20) |
| [0094-operator-first-assess-priority.md](./0094-operator-first-assess-priority.md) | ADR 0094 — Operator-first ASSESS priority + INBOX provenance (v4.78) | Accepted (2026-05-20) |
| [0095-synthesis-citation-grounding.md](./0095-synthesis-citation-grounding.md) | ADR 0095 — Synthesis-citation grounding check (v4.83) | Accepted (2026-05-20) |
| [0096-scope-evasion-detection.md](./0096-scope-evasion-detection.md) | ADR 0096 — Scope-evasion detection + explicit writable-scope grant (v4.82) | Accepted (2026-05-20) |
| [0097-post-escalation-remediation.md](./0097-post-escalation-remediation.md) | ADR 0097 — Post-escalation remediation hints + three-strikes auto-skip (v4.84) | Accepted (2026-05-20) |
| [0098-ping-pong-loop-detection.md](./0098-ping-pong-loop-detection.md) | ADR 0098 — Ping-pong (alternating-cycle) loop detection (v4.87, agent-authored during soak v6) | Accepted (2026-05-22) |
| [0099-fix-without-test-detection.md](./0099-fix-without-test-detection.md) | ADR 0099 — Fix-without-test detection | Accepted (2026-05-22) |
| [0100-graduated-trust-decrements.md](./0100-graduated-trust-decrements.md) | ADR 0100 — Graduated trust decrements by escalation severity | Accepted (2026-05-22) |
| [0101-artifact-incomplete-detection.md](./0101-artifact-incomplete-detection.md) | ADR 0101 — `artifact_incomplete`: content-marker verification on write | Accepted (2026-05-22) |
| [0102-operator-side-submit-pr.md](./0102-operator-side-submit-pr.md) | ADR 0102 — Operator-Side `submit-pr` Verb (v4.97) | Accepted (2026-05-22) |
| [0103-phase-scope-fix-without-test.md](./0103-phase-scope-fix-without-test.md) | ADR 0103 — Phase-scope fix-without-test detection | Accepted (2026-05-22) |
| [0104-inbox-claim-validity.md](./0104-inbox-claim-validity.md) | ADR 0104 — INBOX checkbox claims are validated as truth statements | Accepted (2026-05-22) |
| [0105-syntax-invalid-detection.md](./0105-syntax-invalid-detection.md) | ADR 0105 — syntax-invalid detection on agent writes | Accepted (2026-05-22) |
| [0106-witness-code-review.md](./0106-witness-code-review.md) | ADR 0106 — Witness review for foundational code changes | Accepted (2026-05-22) |
| [0107-cross-provider-witness-panel-for-code-review.md](./0107-cross-provider-witness-panel-for-code-review.md) | ADR 0107 — Cross-provider witness panel for ACT code review (v4.103) | Accepted (2026-05-22) |
| [0108-commit-task-remediation.md](./0108-commit-task-remediation.md) | ADR 0108 — concrete-command remediation for commit tasks | Accepted (2026-05-22) |
| [0109-or-disjunction-scope-evasion.md](./0109-or-disjunction-scope-evasion.md) | ADR 0109 — OR-disjunction grouping for scope-evasion checks | Accepted (2026-05-22) |
| [0110-witness-charter-anchoring.md](./0110-witness-charter-anchoring.md) | ADR 0110 — Charter-anchored witness review (v4.110) | Accepted (2026-05-22) |
| [0112-task-text-charter-extraction.md](./0112-task-text-charter-extraction.md) | ADR 0112 — Task-text charter extraction (v4.112) | Accepted (2026-05-22) |
| [0113-test-claim-invalid-detection.md](./0113-test-claim-invalid-detection.md) | ADR 0113 — Test-claim invalid detection (v4.113) | Accepted (2026-05-22) |
| [0114-autonomous-delivery-contract.md](./0114-autonomous-delivery-contract.md) | ADR 0114 — Autonomous-delivery contract | Accepted (2026-05-23) |
| [0115-commit-message-diff-drift-detection.md](./0115-commit-message-diff-drift-detection.md) | ADR 0115 — Commit-message-vs-diff drift detection (v4.115) | Accepted (2026-05-23) |
| [0116-charter-file-count-enforcement.md](./0116-charter-file-count-enforcement.md) | ADR 0116 — Charter file-count enforcement (v4.116) | Accepted (2026-05-23) |
| [0117-trust-state-commit-gate.md](./0117-trust-state-commit-gate.md) | ADR 0117 — Trust-state commit gate (v4.117) | Accepted (2026-05-23) |
| [0118-provenance-claim-validation.md](./0118-provenance-claim-validation.md) | ADR 0118 — Provenance-claim validation in [agent] commits (v4.118) | Accepted (2026-05-23) |
| [0119-sticky-detector-demotes.md](./0119-sticky-detector-demotes.md) | ADR 0119 — Sticky detector-finding demotes (v4.119) | Accepted (2026-05-23) |
| [0120-soak-runner-watchdog.md](./0120-soak-runner-watchdog.md) | ADR 0120 — Soak-runner watchdog for chimera-run liveness | Accepted (2026-05-23) |
| [0121-soak-lib-v4-mind-auto-allow.md](./0121-soak-lib-v4-mind-auto-allow.md) | ADR 0121 — soak_lib v4: mind/* journal auto-allow in soft sentinel | Accepted (2026-05-24) |
| [0122-isolate-tests-from-git-reading-detectors.md](./0122-isolate-tests-from-git-reading-detectors.md) | ADR 0122 — Isolate test_act + test_subagent from v4.115/v4.118 git-reading detectors | Accepted (2026-05-24) |
| [0123-honcho-inspired-enhancements.md](./0123-honcho-inspired-enhancements.md) | ADR 0123 — Honcho-inspired enhancements roadmap (Phase 1: ReasoningTier + Context.to_openai) | Accepted (2026-05-24) |
| [0124-deriver-style-extraction.md](./0124-deriver-style-extraction.md) | ADR 0124 — Deriver-style structured-output extraction (Phase 2 / item #3) | Accepted (2026-05-24) |
| [0125-wire-deriver-to-reflection.md](./0125-wire-deriver-to-reflection.md) | ADR 0125 — Wire the Deriver into ReflectionEngine (opt-in CHIMERA_REFLECTION_DERIVER) | Accepted (2026-05-24) |
| [0126-v4115-commit-only-diff.md](./0126-v4115-commit-only-diff.md) | ADR 0126 — v4.115 inspects HEAD's own commit diff, not cumulative `base..HEAD` | Accepted (2026-05-24) |
| [0127-reasoning-tier-wiring.md](./0127-reasoning-tier-wiring.md) | ADR 0127 — Wire `ReasoningTier` to `ReflectionEngine` (Phase 2 completion) | Accepted (2026-05-24) |
| [0128-peer-cards.md](./0128-peer-cards.md) | ADR 0128 — Peer Cards (Phase 3 / item #4): per-peer markdown snapshots refreshed at ROTATE | Accepted (2026-05-24) |
| [0129-peer-cards-rotate-wiring.md](./0129-peer-cards-rotate-wiring.md) | ADR 0129 — Wire Peer Cards into `_phase_rotate` (default-on; `CHIMERA_PEER_CARDS_ON_ROTATE=0` opts out) | Accepted (2026-05-24) |
| [0130-peer-card-narrative.md](./0130-peer-card-narrative.md) | ADR 0130 — Peer-Card LLM Narrative Layer (opt-in via `CHIMERA_PEER_CARD_LLM=1`) | Accepted (2026-05-24) |
| [0131-peers-cli-verb.md](./0131-peers-cli-verb.md) | ADR 0131 — `chimera peers cards` CLI verb (final Phase 3 #4 follow-up) | Accepted (2026-05-24) |
