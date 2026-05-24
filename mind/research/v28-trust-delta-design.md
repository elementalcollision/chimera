# v28 (sub-soak D): Add `"charter_file_count"` to `FINISH_REASON_TRUST_DELTAS`

## Context

v26 wired the `charter_file_count` call site into the ACT loop. v27 added
`"charter_file_count"` to `ESCALATING_FINISH_REASONS` so the three-strikes
auto-skip path activates. **v28 adds the trust-tier demotion entry** —
without it, a `finish_reason="charter_file_count"` event is an unknown
reason in `FINISH_REASON_TRUST_DELTAS` and gets `delta=0`, meaning the
trust tier never demotes no matter how many times the agent violates
the charter file-count budget.

## Template analysis (existing entries in `FINISH_REASON_TRUST_DELTAS`)

The dict lives in `chimera/trust/manager.py` at line 48. Entries are
ordered by severity/ADR number. Each entry is:

```python
    # v4.<N> (ADR <NNNN>): <short_name> — <one-line description>
    # <2–3 lines of context: what soak surfaced it, severity rationale,
    #  recoverability cue.>
    "<finish_reason>": <int>,
```

Severity classification for `charter_file_count`: the agent committed
files the charter explicitly forbade — the cumulative diff carries
paths outside the INBOX task's file enumeration. This is an **incomplete
delivery against an explicit contract**, same bucket as
`artifact_missing` / `fix_without_test` / `syntax_invalid` /
`test_claim_invalid`.

**Proposed delta: 1 (one-tier demote).** Rationale:

- The charter is a hard structural constraint the operator writes into
  the task text — violating it means the agent ignored or misread the
  INBOX brief. That's worse than a draft-quality signal (delta=0) but
  not as bad as scope_evasion (delta=2, writing *against* intent).
- Same severity as `fix_without_test` (incomplete delivery against a
  specified contract): the agent shipped *something* but failed the
  charter's file-count guard.
- Recoverable from a remediation hint that names the violating paths
  and tells the agent to either remove the extra file or update the
  charter enumeration — the model retries within the same task.

## Exact code to insert

Insert the following block in `chimera/trust/manager.py` inside
`FINISH_REASON_TRUST_DELTAS`, **after** the `"provenance_claim_invalid"` entry
(line ~95) and **before** the `# v4.102` docstring block for
`"witness_rejected"` (line ~97). The dict is ordered by severity, then
ADR number ascending; v4.116 ADR 0116 sits between v4.118 and v4.102.

```python
    # v4.116 (ADR 0116): charter_file_count — the cumulative diff
    # carries files the charter didn't enumerate. Soak v20-relaunch
    # (PR #6) shipped an unsanctioned mind/research/ file outside the
    # INBOX charter's explicit file list. Same severity as
    # fix_without_test / syntax_invalid (one-tier demote): incomplete
    # delivery against a specified contract. Recoverable from a hint
    # that names the violating paths and tells the agent to either
    # scrub the extra file or update the charter enumeration.
    "charter_file_count": 1,
```

## Placement summary

| File | Location | Change |
|---|---|---|
| `chimera/trust/manager.py` | Inside `FINISH_REASON_TRUST_DELTAS`, after `"provenance_claim_invalid": 1,` (line ~95), before the `# v4.102` comment block (line ~97) | Insert 7-line docstring + `"charter_file_count": 1,` |

## Test addition (appended to `tests/test_charter_file_count.py`)

```python
def test_finish_reason_trust_delta_charter_file_count() -> None:
    """charter_file_count demotes exactly one trust tier."""
    from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS
    assert FINISH_REASON_TRUST_DELTAS.get("charter_file_count") == 1
```

## READY-FOR-REMEDIATION

(a) Exact code to insert: the 7-line docstring block + `"charter_file_count": 1,` entry into `FINISH_REASON_TRUST_DELTAS` in `chimera/trust/manager.py`.

(b) Placement: after `"provenance_claim_invalid": 1,` (line ~95), before the `# v4.102 (ADR 0106): witness_rejected — ...` comment block (line ~97).

(c) Test assertion: `assert FINISH_REASON_TRUST_DELTAS.get("charter_file_count") == 1` appended to `tests/test_charter_file_count.py`.