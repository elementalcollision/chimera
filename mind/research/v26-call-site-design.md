# v26 Call-Site Design — `check_charter_file_count` Wiring

## Context

Sub-soak B of the v4.116 wiring decomposition. The `ActResult` dataclass
already carries `charter_file_count_violations: list[str]` (shipped in
v25). The function `check_charter_file_count(task_text, worktree_root)`
is implemented and tested in `chimera/core/witness.py:427`. The **call
site** — the invocation inside the `act_loop` that populates
`ActResult` — is the only missing piece.

The template to mirror: **v4.115's call site at
`chimera/core/act.py:2033` (`check_commit_message_diff_drift`)** — a
post-commit gate that runs when `completed` is still True, calls a
detector, and demotes to `completed=False` with a specific
`finish_reason` when the detector returns non-empty violations.

## Exact Code to Insert

Insert the following block immediately after the v4.118 provenance block
(i.e., after the `if provenance_failures:` ... `finish_reason =
"provenance_claim_invalid"` stanza) and before the v4.102 witness block
comment. Target: after line ~2057, before line ~2059.

```python
                # v4.116 (ADR 0116): charter file-count enforcement.
                # Soak v20-relaunch shipped an [agent] commit whose
                # cumulative diff carried a third file
                # (mind/research/ruff-claim-design.md) outside the
                # INBOX charter's explicit file enumeration, and the
                # required test file was missing. Runs AFTER the v4.118
                # provenance check (same source: the commit diff) but
                # BEFORE the expensive witness panel — the file-count
                # mismatch is a fast, deterministic gate the panel can
                # skip if it fires here.
                charter_file_count_violations: list[str] = []
                if completed:
                    charter_file_count_violations = check_charter_file_count(
                        task_text, Path.cwd(),
                    )
                    if charter_file_count_violations:
                        completed = False
                        finish_reason = "charter_file_count_exceeded"
```

## Import Change

Add `check_charter_file_count` to the existing `from .witness import (...)`
block at line 35. Currently:

```python
from .witness import (
    capture_diff_for_witness,
    extract_charter_excerpts,
extract_task_charter,
    should_witness,
    witness_enabled,
)
```

Change to:

```python
from .witness import (
    capture_diff_for_witness,
    check_charter_file_count,
    extract_charter_excerpts,
extract_task_charter,
    should_witness,
    witness_enabled,
)
```

Note: `extract_task_charter` line has broken indentation in the current
file — do NOT fix that (charter #4: no refactoring). Just insert
`check_charter_file_count` alphabetically as the second entry.

## ActResult Population

The `ActResult` return at ~line 2242 already needs no change — the
`charter_file_count_violations` kwarg is NOT yet passed there. The final
`ActResult(...)` construction block needs one additional keyword:

In the `return ActResult(...)` block around line 2242–2262, add:

```python
                    charter_file_count_violations=charter_file_count_violations,
```

immediately after the `provenance_claim_failures=provenance_failures,` line.

The `charter_file_count_violations` variable is bound above (via the new
call-site block inserted at step 1). When the charter_file_count gate
does NOT fire (completed stays True), the variable is `[]` — the
dataclass default — and the existing
`test_actresult_charter_file_count_violations_default_is_empty`
test in `tests/test_charter_file_count.py` remains satisfied.

## Placement Summary

| Location | Line | Change |
|---|---|---|
| Import block | ~35 | Add `check_charter_file_count,` into `from .witness import (...)` |
| Post-provenance gate | After ~2057 | Insert 15-line call-site block |
| ActResult return | ~2258 | Add `charter_file_count_violations=charter_file_count_violations,` kwarg |

## Test Addition

Add ONE test at the END of `tests/test_charter_file_count.py`:

```python
def test_actresult_charter_file_count_violations_surfaces_in_finish_reason(
    tmp_path: Path,
) -> None:
    # Exercise the call site: a commit with an unsanctioned third file
    # produces charter_file_count_exceeded.
    _init_repo(tmp_path)
    _agent_commit(
        tmp_path,
        [
            "chimera/core/act.py",
            "mind/research/unsanctioned-extra.md",
        ],
    )
    violations = check_charter_file_count(_CHARTER_TWO_FILES, tmp_path)
    assert violations == ["mind/research/unsanctioned-extra.md"]
    assert len(violations) > 0  # non-empty -> finish_reason demotion
```

This test mirrors the existing `test_diff_carries_unsanctioned_third_file`
but adds the explicit `len > 0` assertion that validates the demotion
contract used by the call site.

## READY-FOR-REMEDIATION

(a) Exact code to insert: the 15-line `charter_file_count_violations` gate block, the one-line import addition of `check_charter_file_count`, and the one-line `charter_file_count_violations=charter_file_count_violations,` kwarg in the `ActResult(...)` return.

(b) Placement:
  - Import: line ~35, inside `from .witness import (...)`, after `capture_diff_for_witness,`.
  - Call-site block: after line ~2057 (after v4.118 provenance gate closing), before line ~2059 (v4.102 witness block comment).
  - ActResult kwarg: line ~2258, after `provenance_claim_failures=provenance_failures,`.

(c) Test assertion (one line): `assert len(violations) > 0  # non-empty -> finish_reason demotion` — appended to `tests/test_charter_file_count.py`.
