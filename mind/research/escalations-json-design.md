# Escalations `--json` Flag Design

Proposed JSON output schemas for `escalations list --json` and
`escalations summary --json`, plus the argparse additions and a
pseudocode CLI test.

## READY-FOR-REMEDIATION

(a) `escalations list --json` schema:
```
list of rows, each row a dict with:
  id          int   — escalation row primary key
  signature   str   — token-bag signature (sorted, comma-joined, ≥4-char tokens)
  task_text   str   — verbatim task prompt
  tier        str   — tier at time of failure ("haiku" | "sonnet" | "opus")
  finish_reason str — machine-readable failure reason (one of ESCALATING_FINISH_REASONS)
  rounds_used int   — rounds consumed before failure
  cycle       int   — cycle ordinal
  created_at  str   — ISO-8601 UTC timestamp (seconds precision)
```

(b) `escalations summary --json` schema:
```
dict keyed by signature str -> dict keyed by tier str -> count int
i.e. {"token1,token2,...": {"haiku": 2, "sonnet": 1}, ...}
```
This is a direct serialisation of `escalation_summary()`'s return type.

(c) Exact argparse lines to add in `chimera/cli.py`:

Two edits, both localised to the existing `escalations` subparser tree:

**Edit 1 — `esc_list` (circa line 46):**
```python
    esc_list.add_argument("--json", action="store_true",
                         help="Emit rows as a JSON list.")
```

**Edit 2 — `esc_summary` (circa line 49):**
```python
    esc_summary.add_argument("--json", action="store_true",
                            help="Emit summary dict as JSON.")
```

_Note: the summary subparser is created in-line without a local
variable — the actual insertion is one line after `esc_sub.add_parser(
"summary", ...)`. The editor will need to hoist a local ref or
chain the `.add_argument()` directly off the `add_parser()` call._

Implementation notes for the `if sub_cmd == "list"` and
`if sub_cmd == "summary"` branches:

**List branch (circa line 1081):**
```python
        if sub_cmd == "list":
            rows = list_escalations(
                conn, limit=args.limit, signature_substring=args.grep,
            )
            if args.json:
                print(_json.dumps(
                    [
                        {
                            "id": r.id,
                            "signature": r.signature,
                            "task_text": r.task_text,
                            "tier": r.tier,
                            "finish_reason": r.finish_reason,
                            "rounds_used": r.rounds_used,
                            "cycle": r.cycle,
                            "created_at": r.created_at,
                        }
                        for r in rows
                    ],
                    indent=2, default=str,
                ))
                return 0
            if not rows:
                ...  # existing text path follows
```

**Summary branch (circa line 1099):**
```python
        if sub_cmd == "summary":
            summary = escalation_summary(conn)
            if args.json:
                print(_json.dumps(summary, indent=2, default=str))
                return 0
            if not summary:
                ...  # existing text path follows
```

(d) Pseudocode test that exercises both new flags via the existing CLI
test harness pattern (`subprocess.run([sys.executable, "-m", "chimera.cli", ...])`):

```python
def test_escalations_json_shapes(tmp_path: Path) -> None:
    """Seed a few escalation rows, then verify both --json flags
    produce parseable, structurally correct outputs."""
    state = tmp_path / "state"
    mind = tmp_path / "mind"
    state.mkdir()
    mind.mkdir()
    db = open_and_init(state / "chimera.db")
    # Seed two failures on different signatures.
    from chimera.core.escalation import record_failure
    record_failure(db, task_text="write a research paper based on peer-reviewed sources",
                   tier="haiku", finish_reason="max_rounds", rounds_used=12, cycle=1)
    record_failure(db, task_text="add json schema to the cli",
                   tier="sonnet", finish_reason="scope_evasion", rounds_used=8, cycle=2)
    record_failure(db, task_text="write a research paper based on peer-reviewed sources",
                   tier="sonnet", finish_reason="length", rounds_used=15, cycle=3)
    db.commit()
    db.close()

    # --- list --json ---
    rc, out, err = _run_escalations("list", "--json", state_dir=state, mind_dir=mind)
    assert rc == 0, out + err
    rows = json.loads(out)
    assert isinstance(rows, list)
    assert len(rows) == 3
    for row in rows:
        assert isinstance(row, dict)
        assert "id" in row
        assert "signature" in row
        assert "task_text" in row
        assert "tier" in row
        assert "finish_reason" in row
        assert "rounds_used" in row
        assert "cycle" in row
        assert "created_at" in row
        assert isinstance(row["id"], int)
        assert isinstance(row["rounds_used"], int)
        assert isinstance(row["cycle"], int)
    # Most recent first — last seed row should be first in output.
    assert rows[0]["finish_reason"] == "length"

    # --- summary --json ---
    rc, out, err = _run_escalations("summary", "--json", state_dir=state, mind_dir=mind)
    assert rc == 0, out + err
    summ = json.loads(out)
    assert isinstance(summ, dict)
    # Two signatures: "paper,peer,research,reviewed,sources,write" and "add,cli,schema"
    # Token-bag is sorted, comma-joined, ≥4-char tokens.
    assert len(summ) == 2
    for sig, by_tier in summ.items():
        assert isinstance(sig, str)
        assert isinstance(by_tier, dict)
        for tier, count in by_tier.items():
            assert isinstance(tier, str)
            assert isinstance(count, int)
    # research-paper signature should have haiku×1, sonnet×1
    rp_sig = next(k for k in summ if "paper" in k)
    assert summ[rp_sig] == {"haiku": 1, "sonnet": 1}


def _run_escalations(
    *extra: str, state_dir: Path, mind_dir: Path,
) -> tuple[int, str, str]:
    """Helper: invoke ``chimera escalations <subcmd> <extra>``.
    Returns (returncode, stdout, stderr).
    Uses sys.executable + -m to avoid PATH issues."""
    import subprocess, sys
    proc = subprocess.run(
        [sys.executable, "-m", "chimera.cli", "escalations", *extra],
        env={
            "PATH": "/usr/bin:/bin",
            "CHIMERA_STATE_DIR": str(state_dir),
            "CHIMERA_MIND_DIR": str(mind_dir),
        },
        capture_output=True, text=True, timeout=15,
    )
    return proc.returncode, proc.stdout, proc.stderr
```

The test follows the exact pattern established by `test_cost_cli.py`
(`_run_cost` helper, isolated tmp_path state/mind dirs, seed via
`open_and_init` + business-logic calls). The assertion on `rows[0]`
being "length" confirms the ``ORDER BY id DESC`` sort is honoured
even in JSON mode.
