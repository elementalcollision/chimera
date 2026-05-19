---
cycle: 0
session_started_at: null
trust_tier: T0
status: dormant
model_usage:
  anthropic_calls: 0
  openrouter_calls: 0
last_drift_score: null
---

# Chimera — Heartbeat

The current operational state of Chimera. Frontmatter is the canonical record;
narrative below is human-facing.

This file is the source of truth for cycle state. The WRITE phase updates the
frontmatter every cycle; WAKE restores it on container restart.
