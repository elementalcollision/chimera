# Charter — numstat_parser (self-authored)

**Goal**: Add a pure function parse_numstat(line) that parses a git 'diff --numstat' line into a (added:int, removed:int, path:str) tuple, treating '-' counts (binary files) as 0

## Design

Parse a single line from `git diff --numstat` output into a tuple of (added_lines:int, removed_lines:int, path:str) while treating the '-' sentinel (binary files) as 0. This module provides a pure, easily-testable building block for scripts that process diff summaries, enabling clear counting and filtering without special-casing binary markers.

## The target (ONE new file)

`chimera/numstat_parser.py` — built to pass the pre-written acceptance test
`tests/test_numstat_parser.py` (imports `chimera.numstat_parser`). The test was
teeth-validated (ADR 0152/0153) before this charter was approved.

## READY-FOR-REMEDIATION

R3 build. The single allowed code path is `chimera/numstat_parser.py` — create it,
importing only what the test requires. The acceptance test is read-only
input. The postmortem and other mind/ files are auto-allowed. The commit
message MUST begin with the literal `[agent]` token.
