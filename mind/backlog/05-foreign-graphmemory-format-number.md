---
goal: "Add test_gm_format_number.py at the repository ROOT (NOT under tests/) covering format_number in dashboard/utils/formatting.py: values >= 1_000_000 render with an 'M' suffix, >= 1_000 with 'K', smaller values format plainly, the decimals argument is honored, and non-numeric input returns 'N/A'. Read the function first and assert its ACTUAL behavior."
files: test_gm_format_number.py
repo: elementalcollision/GraphMemory-IDE
verify_cmd: "uv run --no-project --with pytest python -m pytest test_gm_format_number.py -q -p no:cacheprovider"
base: main
---
Foreign-repo daily-loop task (ADR 0186). Low-risk, purely ADDITIVE test coverage
for the pure helper `format_number` in `dashboard/utils/formatting.py` — currently
untested. The change touches ONLY the new test file.

Placement note: the test goes at the repository ROOT (not `tests/`) ON PURPOSE.
GraphMemory's `tests/conftest.py` imports the full server stack (kuzu + transformers),
so a test under `tests/` would force a heavy, fragile install. A root-level test
dodges that conftest, and the verify_cmd runs it with `--no-project --with pytest`
so only pytest is installed and `dashboard.utils.formatting` (stdlib-only imports)
resolves cleanly.

GraphMemory-IDE's verify_cmd is operator-reviewed; the foreign-PR path is graduated
(DRAFT-only, allowlist- + scope-gated). Deliverable: one draft PR for review.
