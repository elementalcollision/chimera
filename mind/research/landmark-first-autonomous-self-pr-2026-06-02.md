# Landmark — first autonomous self-PR (2026-06-02)

Chimera opened **its own pull request** — autonomously, trust-gated, draft-only:
**[PR #254](https://github.com/elementalcollision/chimera/pull/254)**.

This is the autonomy ladder's next rung after the no-contract enforced loop (the
2026-06-02 characterization arc). The full chain ran with **no human in the loop
until the merge gate**:

1. **Self-select** — self-scan ranked maintenance tasks; the agent picked one.
2. **Build** — a clean, minimal 3-import ruff cleanup in `tests/test_locomo.py`.
3. **Gated commit** — the in-loop critic gate (ADR 0162) fired: primary
   `claude-sonnet-4-6` rejected, the independent `claude-opus-4-7` escalator
   approved, the commit landed (`87a979c`).
4. **Earned trust** — tier T5, above the T4 self-PR floor.
5. **Autonomous draft PR** — `maybe_self_pr` (ADR 0163) pushed the branch via the
   operator's git config and opened PR #254 **as a draft**.

## Evidence

```json
{"fired": true, "submit_ok": true, "branch": "chimera-soak/realtask-2026-06-02-1714",
 "pushed": true, "pr_url": "https://github.com/elementalcollision/chimera/pull/254"}
```
`gh pr view 254`: `isDraft: true`, state OPEN, title
`[agent] fix the 3 ruff lint finding(s) in tests/test_locomo.py`. Audit log:
`submit_pr.success`, commit `87a979c`, `draft: true`.

## Every safety guarantee held

- **Opt-in** — `CHIMERA_SELF_PR=1`; off by default the path is inert.
- **Trust-gated** — T4+ required (was T5).
- **Gate-gated** — only a commit the critic gate `allowed:true` can be proposed.
- **Validated** — full `submit_pr.validate()` (secret/test/honesty gates).
- **Draft, never merged** — two human actions (mark-ready + merge) still required;
  the human is the terminal authority. ADR 0102's threat model intact (no new
  credential surface — push uses the operator's git config).

## How we got here (the disciplined path)

The "validate live" step ran a **dry-run first**, which caught two integration
gaps (branch-pattern + `mind/` journal noise) with zero side effects; those were
fixed (#253) and the dry-run reached `submit.ok=True` before the real PR opened.
Falsification-honest: the gap was found and closed *before* the live firing, not
after a bad PR appeared.

## What this unlocks / open follow-up

The trust ladder now has teeth — T4 unlocks a concrete capability. The natural
follow-up is to validate trust **progression** (T0→T4 from accumulated
gate-approved commits) so self-PR eligibility is itself earned, not just present.
The next frontier is **Create**: self-authored charter → net-new code under the
same gate + self-PR machinery.
