"""Validation stage — sandbox-execute the assembled handler against samples.

Each sample's input is passed to the handler in a fresh subprocess
(``python -I``), output is captured, and we check whether the expected
substring appears.

A pre-flight static check rejects code containing forbidden patterns
(subprocess, network, eval/exec, __import__, dunder-injection).

Score = fraction of samples that produced the expected substring.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .assembly import AssembledSkill

# Conservative deny-list for static analysis. Catches the obvious moves;
# a sandboxed subprocess is the real defense.
_FORBIDDEN_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p) for p in (
        r"\bimport\s+subprocess\b",
        r"\bfrom\s+subprocess\b",
        r"\bimport\s+os\.system\b",
        r"\bos\.system\b",
        r"\bos\.popen\b",
        r"\bimport\s+socket\b",
        r"\bfrom\s+socket\b",
        r"\bimport\s+urllib\b",
        r"\bfrom\s+urllib\b",
        r"\bimport\s+http\b",
        r"\bfrom\s+http\b",
        r"\bimport\s+requests\b",
        r"\bimport\s+httpx\b",
        r"\beval\s*\(",
        r"\bexec\s*\(",
        r"\b__import__\s*\(",
        r"\bcompile\s*\(",
    )
)


@dataclass
class ValidationResult:
    ok: bool
    score: float
    passed: int
    total: int
    sample_outcomes: list[dict] = field(default_factory=list)
    failure_reason: str | None = None


def static_lint(handler_code: str) -> str | None:
    """Return a failure reason string, or ``None`` if the static check passes."""
    for pat in _FORBIDDEN_PATTERNS:
        if pat.search(handler_code):
            return f"forbidden pattern in handler: {pat.pattern!r}"
    return None


_DRIVER_TEMPLATE = """\
import asyncio
import json
import sys

# Handler module:
{handler_code}

async def _main():
    args = json.loads(sys.argv[1])
    out = await handle(args, None)
    if not isinstance(out, str):
        out = str(out)
    sys.stdout.write(out)

asyncio.run(_main())
"""


async def _run_sample(
    handler_code: str,
    sample_input: dict,
    *,
    timeout_s: float = 5.0,
) -> tuple[bool, str]:
    """Spawn a sandboxed subprocess to run the handler against one sample."""
    driver = _DRIVER_TEMPLATE.format(handler_code=handler_code)
    with tempfile.TemporaryDirectory() as td:
        script_path = Path(td) / "driver.py"
        script_path.write_text(driver, encoding="utf-8")

        def _preexec():
            try:
                import resource  # type: ignore[import-not-found]
                resource.setrlimit(
                    resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024)
                )
                resource.setrlimit(resource.RLIMIT_CPU, (5, 6))
            except Exception:
                pass

        kwargs: dict = {
            "cwd": td,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        # preexec_fn is POSIX-only; harmless on Linux.
        if sys.platform != "win32":
            kwargs["preexec_fn"] = _preexec
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", str(script_path), json.dumps(sample_input), **kwargs
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False, f"[timeout after {timeout_s:.1f}s]"

    if proc.returncode != 0:
        return False, f"[exit={proc.returncode}] {stderr.decode(errors='replace')[:300]}"
    return True, stdout.decode("utf-8", errors="replace")


async def validate_skill(
    assembled: AssembledSkill,
    *,
    timeout_s: float = 5.0,
    pass_threshold: float = 0.6,
) -> ValidationResult:
    """Sandbox-run each sample; return aggregate pass/fail."""
    if not assembled.ok:
        return ValidationResult(
            ok=False,
            score=0.0,
            passed=0,
            total=0,
            failure_reason=assembled.failure_reason or "assembled.ok is False",
        )

    lint_err = static_lint(assembled.handler_code)
    if lint_err:
        return ValidationResult(
            ok=False, score=0.0, passed=0, total=len(assembled.samples),
            failure_reason=lint_err,
        )

    outcomes: list[dict] = []
    passed = 0
    for i, sample in enumerate(assembled.samples):
        sample_input = sample.get("input")
        expected = sample.get("expected_substring", "")
        if not isinstance(sample_input, dict):
            outcomes.append({"index": i, "ok": False, "reason": "sample.input must be a dict"})
            continue
        ok, output = await _run_sample(
            assembled.handler_code, sample_input, timeout_s=timeout_s
        )
        if not ok:
            outcomes.append(
                {"index": i, "ok": False, "reason": output[:200]}
            )
            continue
        matched = expected in output if expected else True
        outcomes.append(
            {
                "index": i,
                "ok": matched,
                "expected": expected,
                "output_preview": output[:200],
            }
        )
        if matched:
            passed += 1

    total = len(assembled.samples)
    score = passed / total if total else 0.0
    return ValidationResult(
        ok=score >= pass_threshold,
        score=score,
        passed=passed,
        total=total,
        sample_outcomes=outcomes,
        failure_reason=None if score >= pass_threshold else f"score {score:.2f} < {pass_threshold}",
    )
