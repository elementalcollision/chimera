# v30 (sub-soak E): End-to-End Coverage Test for `charter_file_count` Pipeline

## Context

v26–v28 wired the `charter_file_count` finish-reason through three
layers of the Chimera feedback pipeline:

| Sub-soak | Layer | What it does |
|---|---|---|
| v26 (B) | Call site (`chimera/core/act.py`) | Invokes `check_charter_file_count` on each completed ACT cycle, demotes `completed=False` and sets `finish_reason="charter_file_count"` on violation |
| v27 (C) | Escalation set (`chimera/core/escalation.py`) | Adds `"charter_file_count"` to `ESCALATING_FINISH_REASONS` so `record_failure` counts it toward the three-strikes auto-skip |
| v28 (D) | Trust delta (`chimera/trust/manager.py`) | Adds `"charter_file_count": 1` to `FINISH_REASON_TRUST_DELTAS` so each violation demotes the agent's trust tier by one level |

Each sub-soak has its own unit/integration tests covering the layer in
isolation. **What's missing: a single test that exercises the entire
pipeline end-to-end.** A test that:

1. Creates a real git repository with an [agent] commit whose
   cumulative diff violates the charter's file enumeration.
2. Runs the real `check_charter_file_count` (not monkeypatched).
3. Verifies the violation list, finish_reason, and `completed=False`
   on the resulting `ActResult`.
4. Verifies `record_failure` accepts the finish_reason (i.e. it's
   in `ESCALATING_FINISH_REASONS`).
5. Verifies `FINISH_REASON_TRUST_DELTAS` maps it to `1`.

This is the **coverage capstone** — the test that proves the three
layers integrate correctly and that no layer was forgotten.

## Existing coverage gaps (before v30)

| Gap | Detail |
|---|---|
| **No real-detector E2E** | `test_act_call_site_sets_charter_file_count_finish_reason` monkeypatches `check_charter_file_count` to always return `["mind/research/forbidden.md"]`. It never exercises the real git-diff logic. |
| **No trust-delta test** | `test_charter_file_count_in_escalating_finish_reasons` proves the escalation membership but nothing checks the trust delta. (v28's test addition will cover this in isolation.) |
| **No pipeline-through test** | No single test asserts that the finish_reason produced by the real call site is simultaneously (a) detectable, (b) escalateable, and (c) trust-demotable. |

## Proposed test: `test_charter_file_count_e2e_pipeline`

### Location

Append to `tests/test_charter_file_count.py` — the dedicated module for
this ADR family. This keeps all charter_file_count tests in one file.

### Signature and fixture

```python
def test_charter_file_count_e2e_pipeline(tmp_path: Path) -> None:
    """End-to-end: real commit violating charter → detector fires →
    finish_reason surfaces → escalation recognises it → trust delta matches."""
```

### Steps

1. **Set up a real git repo** via `_init_repo(tmp_path)` (already defined
   in the test module).
2. **Create an [agent] commit** with an unsanctioned third file via
   `_agent_commit(...)` (already defined). Use the existing
   `_CHARTER_TWO_FILES` constant that enumerates `chimera/core/act.py`
   and `tests/test_ruff_claim_invalid.py` — then commit a third file
   `mind/research/e2e-extra.md`.
3. **Call the real detector**:
   ```python
   violations = check_charter_file_count(_CHARTER_TWO_FILES, tmp_path)
   ```
4. **Assert violations** are the extra file(s) — `list[str]`, non-empty.
5. **Assert the finish_reason contract**: create a minimal `ActResult`
   with `finish_reason="charter_file_count"` and verify:
   ```python
   assert "charter_file_count" in ESCALATING_FINISH_REASONS
   ```
6. **Assert the trust delta**:
   ```python
   assert FINISH_REASON_TRUST_DELTAS.get("charter_file_count") == 1
   ```

These last two steps are *static* assertions (the sets/dicts are module-level
constants, so they don't need a live pipeline run). The value of combining
them with a real detector call in one test function is:
- One `pytest` invocation tests the full pipeline.
- Any regression that breaks the detector, the escalation set, or the trust
  delta will be caught by a single test name.
- The test documents the *complete contract* in one place.

### Full test body

```python
def test_charter_file_count_e2e_pipeline(tmp_path: Path) -> None:
    """End-to-end: real commit violating charter → detector fires →
    finish_reason surfaces → escalation recognises it → trust delta matches."""
    # Arrange: a real git commit that violates the charter enumeration.
    _init_repo(tmp_path)
    _agent_commit(
        tmp_path,
        [
            "chimera/core/act.py",
            "tests/test_ruff_claim_invalid.py",
            "mind/research/e2e-extra.md",  # unsanctioned third file
        ],
    )

    # Act: run the real detector against the real commit.
    violations = check_charter_file_count(_CHARTER_TWO_FILES, tmp_path)

    # Assert: detector catches the extra file.
    assert violations == ["mind/research/e2e-extra.md"]
    assert len(violations) > 0  # non-empty → finish_reason demotion

    # Assert: the finish_reason is recognised by the escalation layer.
    assert "charter_file_count" in ESCALATING_FINISH_REASONS

    # Assert: the finish_reason carries the correct trust delta.
    assert FINISH_REASON_TRUST_DELTAS.get("charter_file_count") == 1
```

### Imports needed

`FINISH_REASON_TRUST_DELTAS` must be imported at the top of
`test_charter_file_count.py`. Add to the existing import block:

```python
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS
```

This import is already referenced by the v28 test addition
(`test_finish_reason_trust_delta_charter_file_count`) so adding it now
serves both tests.

### What this test covers

| Layer | Coverage | Real or mocked? |
|---|---|---|
| `check_charter_file_count` | Full path: git diff → charter extraction → file set comparison → violation list | **Real** |
| Charter extraction from task text | Via `_CHARTER_TWO_FILES` — same constant used in all other tests | Real |
| Finish-reason contract (`finish_reason="charter_file_count"` → `completed=False`) | Implicit: non-empty violations in a real detector lead to the demotion path | Real detector; the ActResult construction is not re-tested here (v26 already tests that via monkeypatch) |
| `ESCALATING_FINISH_REASONS` membership | Static assertion | Module constant |
| `FINISH_REASON_TRUST_DELTAS` delta | Static assertion | Module constant |

### What this test does NOT cover (by design)

- **The ActExecutor execute() path** — that's already tested in
  `test_act_call_site_sets_charter_file_count_finish_reason` (v26).
  An E2E through `ActExecutor.execute()` with a real provider call
  would be expensive, flaky, and conflate provider integration with
  charter detection. The detector and the `ActExecutor` wiring are
  tested separately; this test proves that when the detector fires,
  the finish_reason the executor would write is correctly plumbed
  through the downstream layers.
- **The `record_failure` sqlite path** — the escalation membership
  test proves `record_failure` will accept the reason; a real sqlite
  write test would duplicate `test_act_escalation.py`'s coverage.
- **The trust manager's demotion execution** — the delta assertion
  proves the trust manager will apply the correct delta; the actual
  demotion side-effect (writing to `trust_scores` table) is tested
  in `test_trust.py`.

## Dependencies on other sub-soaks

This test can only pass after v26, v27, and v28 are all implemented:

| Sub-soak | Must be merged before v30 test passes |
|---|---|
| v26 (call site) | Yes — exports `ActResult`, `check_charter_file_count` |
| v27 (escalation) | Yes — adds `"charter_file_count"` to `ESCALATING_FINISH_REASONS` |
| v28 (trust delta) | Yes — adds `"charter_file_count": 1` to `FINISH_REASON_TRUST_DELTAS` |

The test is designed to **fail informatively** if any sub-soak is
missing — each assertion corresponds to one sub-soak's deliverable.

## READY-FOR-REMEDIATION

### (a) Exact code to insert

Append the following function and import change to
`tests/test_charter_file_count.py`.

**Import addition** (one line, inserted alphabetically in the existing
`from chimera.core.witness import (...)` block at the top of the file):

```python
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS
```

**Test function** (appended at the very end of the file, after the
`test_charter_file_count_in_escalating_finish_reasons` function):

```python
def test_charter_file_count_e2e_pipeline(tmp_path: Path) -> None:
    """End-to-end: real commit violating charter → detector fires →
    finish_reason surfaces → escalation recognises it → trust delta matches."""
    # Arrange: a real git commit that violates the charter enumeration.
    _init_repo(tmp_path)
    _agent_commit(
        tmp_path,
        [
            "chimera/core/act.py",
            "tests/test_ruff_claim_invalid.py",
            "mind/research/e2e-extra.md",  # unsanctioned third file
        ],
    )

    # Act: run the real detector against the real commit.
    violations = check_charter_file_count(_CHARTER_TWO_FILES, tmp_path)

    # Assert: detector catches the extra file.
    assert violations == ["mind/research/e2e-extra.md"]
    assert len(violations) > 0  # non-empty → finish_reason demotion

    # Assert: the finish_reason is recognised by the escalation layer.
    assert "charter_file_count" in ESCALATING_FINISH_REASONS

    # Assert: the finish_reason carries the correct trust delta.
    assert FINISH_REASON_TRUST_DELTAS.get("charter_file_count") == 1
```

### (b) Placement

- Import: add `from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS`
  near the top of `tests/test_charter_file_count.py`, alongside the existing
  imports from `chimera.core.act`, `chimera.core.escalation`, and
  `chimera.core.remediation`.
- Test function: append at the very end of the file, as the last function
  before any trailing whitespace.

### (c) Dependencies

This test cannot pass until v26, v27, and v28 have been merged.
Run order for the sub-soak suite:

```
v26 (call site) → v27 (escalation) → v28 (trust delta) → v30 (E2E test)
```

