# `doctor --json` Design

## Context

`chimera doctor` currently emits a human-readable table per check:

```
  [✓] state_dir                path
  [!] ANTHROPIC_API_KEY        unset — provider unavailable
  [✗] chimera.db               cannot open …
```

Operators consuming doctor output programmatically (dashboards, soak
harnesses, CI) need a `--json` flag that emits the same data as
structured JSON.

## Proposed JSON Schema

**One line:** list of dicts, each with keys: `name`, `status`, `message` — mirroring the existing formatted output.

```json
[
  {"name": "state_dir",         "status": "ok",    "message": "/tmp/state"},
  {"name": "ANTHROPIC_API_KEY", "status": "warn",  "message": "unset — provider unavailable"},
  {"name": "chimera.db",        "status": "error", "message": "cannot open /tmp/state/chimera.db: ..."}
]
```

`status` is always one of `"ok"` | `"warn"` | `"error"`, drawn directly
from `CheckResult.status`. No flattening, no nesting — just a serialised
version of what the formatted path already prints.

## argparse Addition

In `_build_parser()`, alongside the existing `--fix` argument:

```python
    doctor_p.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of formatted text.",
    )
```

This slots in after line 29 of `chimera/cli.py` (after the `--fix`
`add_argument` call), consistent with every other subcommand that already
offers `--json` (cost, search, estimate, proposers list, etc.).

## Pseudocode Test

Fits the existing `tests/test_doctor.py` harness. It exercises the CLI
entry point via subprocess (same pattern as `tests/test_cli_trust.py`):

```python
def test_doctor_json_via_cli(tmp_path: Path) -> None:
    import json, subprocess, sys

    state_dir = tmp_path / "state"
    mind_dir = tmp_path / "mind"

    proc = subprocess.run(
        [sys.executable, "-m", "chimera.cli", "doctor", "--json"],
        env={
            "PATH": "/usr/bin:/bin",
            "CHIMERA_STATE_DIR": str(state_dir),
            "CHIMERA_MIND_DIR": str(mind_dir),
            # Unset all optional env vars so results are deterministic.
            "CHIMERA_MCP_SERVERS": "",
            "CHIMERA_PEER_TOKENS": "",
            "CHIMERA_PEER_TOKEN": "",
        },
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0, f"stderr: {proc.stderr}"

    payload = json.loads(proc.stdout)
    assert isinstance(payload, list)
    assert len(payload) >= 2  # at least state_dir + chimera.db

    for entry in payload:
        assert "name" in entry
        assert "status" in entry
        assert entry["status"] in ("ok", "warn", "error")
        assert "message" in entry

    # Spot-check: first entry is state_dir → ok.
    assert any(e["name"] == "state_dir" and e["status"] == "ok" for e in payload)
```

The test:
- launches `chimera doctor --json` as a subprocess with a clean tmp_path
- asserts JSON parses as a list
- validates every entry has the three required keys and a valid status
- spot-checks one deterministic check (state_dir → ok)
- uses the same `subprocess.run` pattern as `test_cli_trust.py`

## READY-FOR-REMEDIATION

(a) The proposed JSON schema for `doctor --json` (one line —
likely "list of dicts, each with keys: name, status,
message — mirroring the existing formatted output");
(b) the exact argparse line to add in `chimera/cli.py`
(single `add_argument` call alongside the existing
`--fix`);
(c) one pseudocode test that exercises the new flag via the
existing CLI test harness pattern.
