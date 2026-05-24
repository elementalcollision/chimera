# ADR 0122 — Isolate unit tests from git-reading detectors

**Status**: accepted
**Date**: 2026-05-24
**Companion code**: `tests/test_act.py`, `tests/test_subagent.py`

## Context

Two recent detectors in `chimera/core/act.py` read the live git state of
the working tree from inside the ACT pipeline:

- `check_commit_message_diff_drift` (v4.115, ADR 0115) — shells out to
  `git log -1` and `git diff --name-only main..HEAD` to verify that
  rooted-path claims in an `[agent]` commit body actually appear in
  the diff.
- `check_provenance_claim_valid` (v4.118, ADR 0118) — same shape:
  reads git, validates retroactively, sets a finish_reason if a
  claim is unsupported.

Both run unconditionally inside `executor.execute(...)`. They were
shipped to catch agent self-misreporting in production, and they do
the right thing there.

In unit tests, they leak real-git state into otherwise-isolated
executor tests. `tests/test_act.py` and `tests/test_subagent.py`
build a `_FakeProvider` + fake `Dispatcher`, point them at a
`tmp_path` mind dir, and assert on the resulting `finish_reason`.
But the executor under test still runs in the real repo cwd, so when
the soak branch's HEAD is an `[agent]` commit whose message mentions
a rooted path NOT in the diff, v4.115 fires and overrides the
expected `finish_reason`.

Concrete repro from soak v25 commit `ddcd649`:

- Commit body: "Following the wiring-decomposition methodology laid
  out in **docs/wiring-decomposition-methodology.md** ..."
- `git diff --name-only main..ddcd649`: `chimera/core/act.py`,
  `tests/test_charter_file_count.py`, four `mind/*` journals. Does
  not include `docs/`.
- v4.115 extracts `docs/wiring-decomposition-methodology.md` from
  the message, sees it is not in the diff, fires.
- Seven previously-passing tests flip to failing:
  `test_act_no_tools_used_completes_immediately`,
  `test_act_runs_a_tool_then_completes`,
  `test_act_escalates_to_next_rung_on_first_rung_failure`,
  `test_act_dispatches_multiple_tool_uses_in_parallel`,
  `test_act_records_round_boundary_latency`,
  `test_sub_agent_runs_brief_and_returns_text`,
  `test_sub_agent_passes_allowed_tools_to_context`.

The tests passed on `main` only because `main`'s commit messages
happen not to trip the regex. Any future autonomous-delivery commit
whose message accidentally references a path outside its diff will
fail the auto-merge gate from this same leakage — even when the
deliverable itself is structurally correct.

## Decision

Add an `autouse=True` fixture in each affected test module that
monkeypatches both detectors to return `[]`:

```python
@pytest.fixture(autouse=True)
def _isolate_v4115_v4118_from_git_state(monkeypatch):
    from chimera.core import act as _act
    monkeypatch.setattr(
        _act, "check_commit_message_diff_drift", lambda *a, **kw: []
    )
    monkeypatch.setattr(
        _act, "check_provenance_claim_valid", lambda *a, **kw: []
    )
```

The fixture lives in `tests/test_act.py` and `tests/test_subagent.py`
— not in a shared `conftest.py` — so the isolation is explicit at
the call site. Any new test module that exercises `ActExecutor`
against a fake provider should add the same fixture; any test that
*does* want real git state (e.g. integration tests under
`tests/integration/`) leaves it off.

## Consequences

**Positive**:
- v4.115 and v4.118 keep their production semantics unchanged.
- The seven listed tests no longer depend on the shape of the
  current branch's HEAD commit message.
- Autonomous-delivery commits whose `[agent]` messages mention
  rooted paths outside the diff no longer break unrelated tests
  via the full-suite gate.

**Negative**:
- File-local fixture must be duplicated in each test module that
  uses `ActExecutor` with a fake provider. Acceptable: explicit >
  implicit for a detector that overrides finish_reason.
- A future detector that reads git state would need a parallel
  monkeypatch entry. Acceptable: same explicit-intent argument;
  the alternative (a global fixture in `conftest.py`) hides the
  isolation from anyone reading a single test file.

## Out of scope

- Changing v4.115 or v4.118 themselves — both are correct in
  production and the unit-test leakage is the bug, not the
  detector.
- Extending the isolation to integration tests that intentionally
  exercise the real git state.
- A global `conftest.py` fixture. The decision above explicitly
  rejects this in favor of file-local intent.
- Other detectors that don't read git state (e.g. v4.113
  `check_test_claim_invalid` uses `subprocess` for pytest, but
  does not read repo git state and is not affected).

## Tests

The fix is itself test-infrastructure. Verification:

- `pytest tests/test_act.py tests/test_subagent.py` — all
  previously-failing tests pass when run against a branch HEAD
  whose commit message references a path outside the diff.
- No new test file required; the seven enumerated tests above
  serve as the regression suite for this isolation.
