# v32 Token Budget Design: `--answer-max-tokens` default bump

## Context

Chip T1.1 from the post-baseline priorities (PR #57). The LongMemEval
smoke baseline (PR #56, 30 items) returned 6 EMPTY hypotheses from
`openai/o4-mini` due to reasoning-token budget exhaustion at
`max_tokens=512` on deep histories. Failure mode C.

**Expected delta**: +6 hypotheses (out of 30), ~+10pp overall.

## Current state (CLI)

- Flag: `--answer-max-tokens`, type=int, **default=512** (line 653).
- Defined on the `longmemeval` subparser (line 652–655).
- Plumbed through at line 935:
  ```python
  answer_fn = _build_sonnet_answer_fn(cfg, args.answer_max_tokens) if args.answer else None
  ```
- Function: `_build_sonnet_answer_fn(cfg, max_tokens: int = 512)` (line 961).
- Inside, the inner closure calls `provider.complete(...)` with
  `max_tokens=max_tokens` (line ~993).

The setup: one flag, one function signature, one call site — the plumbing
is tight. Only two values change: the argparse default and the function's
keyword default.

## Design decision: 512 → 2048

The post-baseline priorities doc is explicit: "Raise `max_tokens` default
in `_build_openrouter_answer_fn` from 512 to 2048." The actual function
name in the codebase is `_build_sonnet_answer_fn` (the INBOX task text
references an earlier name that never landed; the live code uses
`_build_sonnet_answer_fn`). The principle is unchanged — raise the sonnet-
tier answer budget from 512 to 2048.

Why 2048 (not 4096 or 8192):
- The upstream LongMemEval expected-answer format is short — a phrase or
  sentence. 2048 leaves room for reasoning without inviting novel-length
  synthesis that would make the grader mismatch.
- The runbook's per-tier ACT output caps (v4.71) set haiku=4096,
  sonnet=8192, opus=16384. 2048 for the eval answer path sits below those
  — this is a single-turn answer, not a multi-round tool-use loop.
- The cheapest OpenRouter model on the sonnet ladder is
  `deepseek/deepseek-v4-pro` at $0.435/$0.87 per Mtok — a 2048-token
  output costs ~$0.0018 worst-case vs ~$0.00045 at 512. Negligible.

## Exact edits (Phase 2 — do NOT apply in Phase 1)

### Edit 1: argparse default (line 653)

```diff
-        "--answer-max-tokens", type=int, default=512,
+        "--answer-max-tokens", type=int, default=2048,
```

The help string on line 654–655 changes accordingly:

```diff
-        help="Max tokens for the sonnet-tier LLM answer when --answer is "
-             "set. Default 512.",
+        help="Max tokens for the sonnet-tier LLM answer when --answer is "
+             "set. Default 2048.",
```

### Edit 2: function signature default (line 961)

```diff
-def _build_sonnet_answer_fn(cfg, max_tokens: int = 512):
+def _build_sonnet_answer_fn(cfg, max_tokens: int = 2048):
```

The call site at line 935 needs no change — it already passes
`args.answer_max_tokens`, which will now default to 2048 via argparse.

### Edit 3: test assertions (tests/test_longmemeval.py)

Two new test cases in the `# --answer / answer_fn path` section:

```python
def test_build_sonnet_answer_fn_default_max_tokens_is_2048(monkeypatch):
    """When the flag is absent, the default is 2048 (was 512 pre-v32)."""
    from chimera.cli import _build_sonnet_answer_fn
    from chimera.core import LoopConfig

    cfg = LoopConfig.from_env()
    fake = object()
    monkeypatch.setattr("chimera.providers.tiers.select_rung", lambda tier, **kw: fake)
    got_tokens = None

    class _FakeProvider:
        def complete(self, messages, *, model_id, system=None, tools=None,
                     tool_choice=None, max_tokens, **_kw):
            nonlocal got_tokens
            got_tokens = max_tokens
            return type("R", (), {"content": "", "finish_reason": "stop",
                                   "tool_uses": [], "usage": {"input_tokens": 10,
                                   "output_tokens": 2}})()

    monkeypatch.setattr("chimera.providers.tiers.LadderRung", lambda *a, **kw: fake)
    monkeypatch.setattr(fake, "config", fake)
    monkeypatch.setattr(fake, "provider", "openrouter")
    monkeypatch.setattr(fake, "openrouter_model_id", "test/model")
    monkeypatch.setattr("chimera.providers.OpenRouterProvider", lambda: _FakeProvider())

    fn = _build_sonnet_answer_fn(cfg)  # no max_tokens arg → default
    fn("test prompt")
    assert got_tokens == 2048, f"expected 2048, got {got_tokens}"


def test_build_sonnet_answer_fn_explicit_max_tokens_passed_through(monkeypatch):
    """When --answer-max-tokens 4096 is provided, the value is passed to the provider."""
    from chimera.cli import _build_sonnet_answer_fn
    from chimera.core import LoopConfig

    cfg = LoopConfig.from_env()
    fake = object()
    monkeypatch.setattr("chimera.providers.tiers.select_rung", lambda tier, **kw: fake)
    got_tokens = None

    class _FakeProvider:
        def complete(self, messages, *, model_id, system=None, tools=None,
                     tool_choice=None, max_tokens, **_kw):
            nonlocal got_tokens
            got_tokens = max_tokens
            return type("R", (), {"content": "", "finish_reason": "stop",
                                   "tool_uses": [], "usage": {"input_tokens": 10,
                                   "output_tokens": 2}})()

    monkeypatch.setattr("chimera.providers.tiers.LadderRung", lambda *a, **kw: fake)
    monkeypatch.setattr(fake, "config", fake)
    monkeypatch.setattr(fake, "provider", "openrouter")
    monkeypatch.setattr(fake, "openrouter_model_id", "test/model")
    monkeypatch.setattr("chimera.providers.OpenRouterProvider", lambda: _FakeProvider())

    fn = _build_sonnet_answer_fn(cfg, max_tokens=4096)
    fn("test prompt")
    assert got_tokens == 4096, f"expected 4096, got {got_tokens}"
```

### Non-changes (explicit scoping)

- `_build_sonnet_answer_fn` **is** the correct function — the INBOX
  task text references `_build_openrouter_answer_fn` but that name does
  not exist in the current codebase. The live function is
  `_build_sonnet_answer_fn` on line 961.
- No change to the call site on line 935 — it already forwards
  `args.answer_max_tokens`.
- No change to `chimera/core/budget.py` — this is a CLI-layer parameter
  bump, not a budget-system change.
- No new ADR — parameter tuning per charter #5.
- No env knobs — flag only per charter overshoot traps.
- No retry-with-larger-budget logic — charter #7.

## Test plan

1. `uv run pytest tests/test_longmemeval.py -q` — confirms all existing
   tests still pass after the default changes.
2. The two new tests above validate:
   (i) default-when-flag-absent yields `max_tokens=2048`
   (ii) explicit value (`4096`) is passed through to the provider.

## READY-FOR-REMEDIATION

### (a) `_build_sonnet_answer_fn` signature edit

**File**: `chimera/cli.py`, line 961.

```python
# Before:
def _build_sonnet_answer_fn(cfg, max_tokens: int = 512):

# After:
def _build_sonnet_answer_fn(cfg, max_tokens: int = 2048):
```

The inner `provider.complete(..., max_tokens=max_tokens)` call at
~line 993 already uses the parameter; no change needed there.

### (b) `--answer-max-tokens` argparse flag

**File**: `chimera/cli.py`, line 652–655.

```python
# Before:
longmemeval.add_argument(
    "--answer-max-tokens", type=int, default=512,
    help="Max tokens for the sonnet-tier LLM answer when --answer is "
         "set. Default 512.",
)

# After:
longmemeval.add_argument(
    "--answer-max-tokens", type=int, default=2048,
    help="Max tokens for the sonnet-tier LLM answer when --answer is "
         "set. Default 2048.",
)
```

The call site at line 935 requires no change:

```python
answer_fn = _build_sonnet_answer_fn(cfg, args.answer_max_tokens) if args.answer else None
```

### (c) Test assertions (pseudocode)

Two tests inserted into `tests/test_longmemeval.py` in the
`# --answer / answer_fn path` section:

1. **Default 2048 when flag absent**:
   - Call `_build_sonnet_answer_fn(cfg)` with no `max_tokens` arg.
   - Assert the inner provider invocation receives `max_tokens=2048`.

2. **Explicit value passed through**:
   - Call `_build_sonnet_answer_fn(cfg, max_tokens=4096)`.
   - Assert the inner provider invocation receives `max_tokens=4096`.
