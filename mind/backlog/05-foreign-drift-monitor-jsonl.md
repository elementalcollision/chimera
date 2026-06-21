---
goal: "Add tests/test_storage_jsonl.py covering the JSONL helpers in drift_monitor/storage.py: a write_jsonl -> read_jsonl round-trip preserves records; read_jsonl returns [] for a missing file; and read_jsonl skips blank and corrupt (non-JSON) lines. Read the functions first and assert their ACTUAL behavior; use a tmp file for all I/O."
files: tests/test_storage_jsonl.py
repo: elementalcollision/drift-monitor
verify_cmd: "uv run --extra dev pytest tests/test_storage_jsonl.py -q"
base: main
---
Foreign-repo daily-loop task (ADR 0186). Low-risk, purely ADDITIVE test coverage
for the deterministic JSONL storage helpers in `drift_monitor/storage.py`
(`write_jsonl`, `read_jsonl`) — currently untested. The change touches ONLY the
new test file; no source behavior changes. The agent should read the helpers and
assert the behavior it actually observes (round-trip, missing-file -> [], and the
documented "skip corrupt lines" tolerance), using `tmp_path`/`tmp` files so the
test is self-contained and deterministic.

drift-monitor's verify_cmd is operator-reviewed; the foreign-PR path is graduated
(DRAFT-only, allowlist- + scope-gated). Deliverable: one draft PR for review.
