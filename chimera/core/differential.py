"""Differential behaviour check — catch behaviour the change DELETED.

The faithfulness gate (ADR 0159) catches under-tested *logic* via mutation, but
the AST mutator has no site for a removed method-call clause — so it cannot see
the exact regression the first live soak produced: the agent dropped
`or s[i-1].isdigit()` from `to_snake`, passing the (incomplete) suite by
*removing* untested behaviour.

This module is the complement. It runs the touched function over an input corpus
under BOTH the pre-change and post-change source, and reports every input where
the output differs — the "behaviour delta". A delta is only legitimate if a test
demanded it (the failing test the fix repaired); a delta on an input no test
covers is an UNJUSTIFIED behaviour change the agent must explain (pin with a
test) or revert. Contract-free: the deltas come from running the code, not a
human spec.

Honest scope. (1) It needs an input corpus; `default_string_corpus()` covers the
common single-string-argument case (including digit-adjacent inputs that exercise
the strcase regression). General input generation for arbitrary signatures is a
separate problem. (2) It exec's the supplied source — intended for the agent's
OWN code in a soak worktree (already trusted enough to run under pytest), in an
isolated namespace, never as a sandbox boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _evaluate(source: str, fn_name: str, args: tuple) -> str:
    """Run ``fn_name(*args)`` defined in ``source``; return a stable repr of the
    result, or a ``raised:<Type>`` / ``error:<reason>`` marker. Never raises."""
    try:
        ns: dict = {}
        exec(compile(source, "<differential>", "exec"), ns)  # noqa: S102
    except Exception as exc:  # source itself won't compile/exec
        return f"error:{type(exc).__name__}"
    fn = ns.get(fn_name)
    if not callable(fn):
        return f"error:no-callable-{fn_name}"
    try:
        return repr(fn(*args))
    except Exception as exc:  # the call raised — that IS its observable behaviour
        return f"raised:{type(exc).__name__}"


@dataclass
class DeltaItem:
    args: tuple
    before: str
    after: str


@dataclass
class DifferentialReport:
    fn_name: str
    total: int = 0
    changed: list[DeltaItem] = field(default_factory=list)

    @property
    def behaviour_changed(self) -> bool:
        return bool(self.changed)

    def summary(self) -> str:
        if not self.changed:
            return (
                f"NO BEHAVIOUR DELTA — {self.fn_name}: identical over "
                f"{self.total} inputs"
            )
        lines = [
            f"BEHAVIOUR DELTA — {self.fn_name}: {len(self.changed)}/{self.total} "
            f"inputs changed (each must be a test-demanded change, not a "
            f"silent regression):"
        ]
        for d in self.changed:
            shown = d.args[0] if len(d.args) == 1 else d.args
            lines.append(f"  {shown!r}: {d.before} → {d.after}")
        return "\n".join(lines)


def behavioral_delta(
    base_source: str,
    changed_source: str,
    fn_name: str,
    inputs: list[tuple],
) -> DifferentialReport:
    """Compare ``fn_name``'s output over ``inputs`` between two source versions.

    Returns a :class:`DifferentialReport` listing every input whose observable
    output differs. Each delta must be a change a test demanded (the fix's
    intent); a delta on an untested input is a candidate silent regression.
    Never raises — a call that errors is captured as part of its behaviour.
    """
    report = DifferentialReport(fn_name=fn_name, total=len(inputs))
    for args in inputs:
        before = _evaluate(base_source, fn_name, args)
        after = _evaluate(changed_source, fn_name, args)
        if before != after:
            report.changed.append(DeltaItem(args=args, before=before, after=after))
    return report


def default_string_corpus() -> list[tuple[str]]:
    """Representative single-string inputs for case/format functions, including
    digit-adjacent and acronym cases (which exercise the branch the strcase
    regression silently dropped)."""
    return [
        ("",), ("a",), ("A",), ("CamelCase",), ("snake_case",),
        ("HTTPServer",), ("getHTTPResponseCode",), ("already_snake",),
        ("ALLCAPS",), ("foo2Bar",), ("v2Point",), ("a1B2c3",),
        ("mixedCase2Word",), ("trailing2",), ("2leading",),
    ]
