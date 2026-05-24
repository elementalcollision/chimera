# v27 (sub-soak C): Add `charter_file_count` to ESCALATING_FINISH_REASONS

## Template analysis (v4.115 entry: `commit_message_diff_drift`, line 147)

**Exact shape (4-line docstring + one string literal):**

```python
    # v4.115 (ADR 0115): commit_message_diff_drift — the agent's
    # [agent] commit message named files that don't appear in the
    # cumulative diff. Soak v20-relaunch surfaced an un-git-add'd
    # tests file claimed in the message body. Recoverable with a
    # hint that names the missing paths; routed through the same
    # three-strikes auto-skip as test_claim_invalid / syntax_invalid.
    "commit_message_diff_drift",
```

**Defaults / semantics observed:**

- All entries are `frozenset` string literals — no tuples, no flags, no extra data.
- Each entry is a 1-line string literal (no trailing comma after closing quote).
- The block is ordered newest-first (descending ADR number).
- All entries share the same frozenset — no secondary sets or conditionals.
- No entry ever raises; `record_failure` simply returns `None` if the finish_reason isn't in the set.
- The three-strikes auto-skip path is implicit: all entries in this set are counted by the caller (``ActExecutor``) toward the max-retries threshold.

**Docstring style:**

- First line: `# v<N> (ADR <NNNN>): <short_name> — <one-line description>`
- Subsequent 2–3 lines: context (what soak surfaced it), recoverability cue, routing note.
- All lines prefixed with `    # ` (8 spaces of indent: 4 for frozenset body + 4 for comment).
- No blank lines between entries. No trailing whitespace.

**Surrounding context (lines 137–155):**

- Line 137: `"test_claim_invalid",` (v4.113 entry — ends with comma, no trailing comment)
- Lines 138–146: the v4.115 docstring block
- Line 147: `"commit_message_diff_drift",`
- Lines 148–153: the v4.118 docstring block
- Line 154: `"provenance_claim_invalid",` (v4.118 entry)
- Line 155 onward: v4.102 entry `"witness_rejected"`

The new v27 entry belongs **between** `"commit_message_diff_drift"` (line 147) and the v4.118 docstring block (starting line 148).

## Integration point confirmation

- `ESCALATING_FINISH_REASONS` still defined as `frozenset({...})` at line 97.
- No structural drift — still a flat frozenset of strings.
- The new entry inserts after line 147, before line 148.
- No other set/list/collection in `escalation.py` that needs the same entry.

## Existing tests in `tests/test_charter_file_count.py`

The file already charters the v4.116 wiring path: the `charter_file_count` finish_reason is wired into `ActResult`, `ActExecutor`, the remediation hint dispatch, and `_HINT_BY_REASON`. What's **missing**: an entry for `"charter_file_count"` in `ESCALATING_FINISH_REASONS`, so the three-strikes auto-skip path never activates for this reason — it's a dead finish_reason once `record_failure` drops it.

New test (to append at end of file): assert that `"charter_file_count"` is a member of `ESCALATING_FINISH_REASONS`.

## READY-FOR-REMEDIATION

### (a) Exact code to insert

```python
    # v4.116 (ADR 0116): charter_file_count — the cumulative diff
    # carries files the charter didn't enumerate. Soak v20-relaunch
    # (PR #6) shipped an unsanctioned mind/research/ file without
    # any escalation entry, so three-strikes never triggered and the
    # runner retried 11 cycles. Recoverable with a hint that names
    # the offending paths; routed through the same three-strikes
    # auto-skip path as commit_message_diff_drift.
    "charter_file_count",
```

### (b) Placement

Insert after line 147 (`"commit_message_diff_drift",`) and before line 148 (the `# v4.118` docstring that begins the `"provenance_claim_invalid"` entry). The frozenset is unordered at runtime but the source convention is newest-first by ADR number; v4.116 postdates v4.115 and predates v4.118, so it sits between them.

### (c) Test assertion (one line pseudocode)

```
assert "charter_file_count" in ESCALATING_FINISH_REASONS
```
