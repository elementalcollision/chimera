"""Stateful behaviour characterization — the differential, for classes.

The pure-function differential (ADR 0159) drives a function over a single-string
corpus; the stateful validation (2026-06-01) proved it is BLIND on a class whose
behaviour depends on the SEQUENCE of method calls — it found no top-level
single-arg function, reported zero deltas, and the stateful accumulation bug was
pinned only by the human-written sequence test.

This module is the complement. It drives a class through a corpus of call
SEQUENCES (a `Scenario` = an ordered list of `(method, args)` calls) and records
a behaviour TRACE: each mutating call's return value, then a snapshot of every
zero-arg read-only ("observer") method. Comparing the trace between the
pre-change and post-change source surfaces stateful behaviour deltas the
pure-function corpus cannot see. Contract-free: the trace comes from running the
code, not a spec.

Observers are auto-discovered (zero-arg, non-dunder methods); the call sequences
are caller-provided (their args are type-specific, like the pure corpus). Charter:
never raise — a call/observer that errors is captured as part of the trace.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field


@dataclass
class Scenario:
    name: str
    calls: list[tuple[str, tuple]]   # ordered (method_name, args) sequence


def observer_methods(source: str, class_name: str) -> list[str]:
    """Zero-arg, non-dunder methods of ``class_name`` — the readable state to
    snapshot after a scenario (e.g. count(), mean())."""
    names: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    a = item.args
                    only_self = len(a.args) == 1 and not a.vararg and not a.kwonlyargs
                    if only_self and not item.name.startswith("_"):
                        names.append(item.name)
    return names


def _sample_args(arg_count: int, annotations: list[str | None], step: int) -> tuple:
    """Sample args for one call of a mutating method. Numeric annotations →
    increasing numbers (so accumulation bugs surface); str → letters; else int."""
    out: list[object] = []
    for ann in annotations:
        a = (ann or "").lower()
        if "str" in a:
            out.append(chr(ord("a") + (step % 26)))
        elif "float" in a:
            out.append(float(step + 1))
        else:  # int / unknown → small increasing ints
            out.append(step + 1)
    return tuple(out[:arg_count])


def auto_scenarios(source: str, class_name: str, *, repeats: int = 3) -> list[Scenario]:
    """Generate call-sequence scenarios: for each mutating method (args beyond
    self), a scenario that calls it ``repeats`` times with increasing sample args
    — enough to surface accumulation / order-dependent bugs. Best-effort; returns
    [] on parse failure or no mutating methods."""
    scenarios: list[Scenario] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return scenarios
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name == class_name):
            continue
        for item in node.body:
            if not isinstance(item, ast.FunctionDef) or item.name.startswith("__"):
                continue
            params = item.args.args[1:]  # drop self
            if not params:
                continue  # zero-arg → an observer, not a mutator
            anns = [
                (ast.unparse(p.annotation) if p.annotation is not None else None)
                for p in params
            ]
            calls = [
                (item.name, _sample_args(len(params), anns, k))
                for k in range(repeats)
            ]
            scenarios.append(Scenario(name=f"{item.name}x{repeats}", calls=calls))
    return scenarios


def _trace(source: str, class_name: str, scenario: Scenario,
           observers: list[str]) -> str:
    """Run one scenario against the class and return a stable trace string:
    each call's return + a final snapshot of the observer methods. Never raises."""
    try:
        ns: dict = {}
        exec(compile(source, "<stateful>", "exec"), ns)  # noqa: S102
    except Exception as exc:
        return f"error:{type(exc).__name__}"
    cls = ns.get(class_name)
    if cls is None:
        return f"error:no-class-{class_name}"
    try:
        obj = cls()
    except Exception as exc:
        return f"error:ctor:{type(exc).__name__}"
    parts: list[str] = []
    for method, args in scenario.calls:
        fn = getattr(obj, method, None)
        if not callable(fn):
            parts.append(f"{method}:missing")
            continue
        try:
            parts.append(f"{method}->{fn(*args)!r}")
        except Exception as exc:
            parts.append(f"{method}->raised:{type(exc).__name__}")
    for obs in observers:
        fn = getattr(obj, obs, None)
        try:
            parts.append(f"@{obs}={fn()!r}" if callable(fn) else f"@{obs}=n/a")
        except Exception as exc:
            parts.append(f"@{obs}=raised:{type(exc).__name__}")
    return " | ".join(parts)


@dataclass
class StatefulDelta:
    scenario: str
    before: str
    after: str


@dataclass
class StatefulReport:
    class_name: str
    total: int = 0
    changed: list[StatefulDelta] = field(default_factory=list)

    @property
    def behaviour_changed(self) -> bool:
        return bool(self.changed)

    def summary(self) -> str:
        if not self.changed:
            return (f"NO STATEFUL DELTA — {self.class_name}: identical over "
                    f"{self.total} scenario(s)")
        lines = [f"STATEFUL DELTA — {self.class_name}: {len(self.changed)}/"
                 f"{self.total} scenario(s) changed (each must be a change a "
                 f"failing test demanded, else a silent regression):"]
        for d in self.changed:
            lines.append(f"  [{d.scenario}] {d.before}  →  {d.after}")
        return "\n".join(lines)


def stateful_delta(
    base_source: str,
    changed_source: str,
    class_name: str,
    scenarios: list[Scenario],
    *,
    observers: list[str] | None = None,
) -> StatefulReport:
    """Compare ``class_name``'s observable behaviour over call sequences between
    two source versions. Observers default to the auto-discovered zero-arg
    read-only methods of the CHANGED source. Never raises."""
    obs = observers if observers is not None else observer_methods(changed_source, class_name)
    report = StatefulReport(class_name=class_name, total=len(scenarios))
    for sc in scenarios:
        before = _trace(base_source, class_name, sc, obs)
        after = _trace(changed_source, class_name, sc, obs)
        if before != after:
            report.changed.append(StatefulDelta(scenario=sc.name, before=before, after=after))
    return report
