"""Test-has-teeth verifier — does a test actually pin behaviour? (S2 / ADR 0152)

The v46 arc gave Chimera end-to-end autonomous delivery, but always against a
human-written acceptance test. To let Chimera author its OWN charter (S1), the
self-written acceptance test must be trustworthy — a test that passes vacuously
(``assert True``, or one that never exercises the logic) would make autonomous
self-commit dangerous, not valuable. This module is the deterministic gate that
catches that class: a real test, run against deliberately-broken copies of the
target, should FAIL on them. A test that passes on broken code has no teeth.

Mechanism (lightweight mutation testing):
  1. Sanity: run the test against the CURRENT (correct) target — it must pass.
  2. Generate single-point source mutants of the target (one AST change each).
  3. Run the test against each mutant. A mutant the test FAILS on is "killed";
     one it still PASSES on "survived" — a blind spot.
  4. teeth_score = killed / applied. High = the test pins behaviour; ~0 = vacuous.

Safety: the target file is restored unconditionally (try/finally) — a crash
mid-run never leaves a mutant on disk. Only the target file is ever written.
"""

from __future__ import annotations

import ast
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Comparison operators and their behaviour-inverting swaps.
_CMP_SWAP: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Lt: ast.GtE, ast.GtE: ast.Lt,
    ast.Gt: ast.LtE, ast.LtE: ast.Gt,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}
_BINOP_SWAP: dict[type[ast.operator], type[ast.operator]] = {
    ast.Add: ast.Sub, ast.Sub: ast.Add,
    ast.Mult: ast.Add, ast.FloorDiv: ast.Mult,
}


@dataclass
class TeethReport:
    """Outcome of a test-has-teeth check."""

    baseline_passed: bool
    mutants_applied: int = 0
    mutants_killed: int = 0
    survived: list[str] = field(default_factory=list)

    @property
    def teeth_score(self) -> float:
        """killed / applied; 0.0 when no mutants could be applied."""
        if self.mutants_applied == 0:
            return 0.0
        return self.mutants_killed / self.mutants_applied

    def has_teeth(self, threshold: float = 0.8) -> bool:
        """True iff the baseline passed AND the score clears ``threshold``."""
        return self.baseline_passed and self.teeth_score >= threshold


def _docstring_positions(tree: ast.AST) -> set[tuple[int, int]]:
    """(lineno, col_offset) of every docstring Constant in ``tree``.

    Docstrings are not behaviour — no test can (or should) fail when one
    changes — so mutating them only adds un-killable mutants that depress the
    teeth score. Covers module / function / async-function / class docstrings.
    """
    positions: set[tuple[int, int]] = set()
    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr):
                val = body[0].value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    positions.add((val.lineno, val.col_offset))
    return positions


class _NthMutator(ast.NodeTransformer):
    """Mutate exactly the ``target``-th eligible site in a fresh tree.

    Sites are enumerated in a stable visit order, so re-running with
    target=0,1,2,… walks every single-point mutation deterministically.
    Docstring positions are skipped (passed in; not counted as sites).
    """

    def __init__(self, target: int, skip_positions: set[tuple[int, int]]) -> None:
        self._target = target
        self._skip = skip_positions
        self._k = -1
        self.applied_desc: str | None = None

    def _hit(self) -> bool:
        self._k += 1
        return self._k == self._target and self.applied_desc is None

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        new_ops: list[ast.cmpop] = []
        for op in node.ops:
            swap = _CMP_SWAP.get(type(op))
            if swap is not None and self._hit():
                new_ops.append(swap())
                self.applied_desc = f"compare {type(op).__name__}→{swap.__name__}"
            else:
                new_ops.append(op)
        node.ops = new_ops
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        swap = _BINOP_SWAP.get(type(node.op))
        if swap is not None and self._hit():
            self.applied_desc = f"binop {type(node.op).__name__}→{swap.__name__}"
            node.op = swap()
        return node

    def visit_AugAssign(self, node: ast.AugAssign) -> ast.AST:
        # Augmented-assignment (`x += y`, `x -= y`, …) — the accumulation site a
        # stateful validation showed was never probed. Swap the op so e.g.
        # `self._sum += x` becomes `self._sum -= x`: a test that pins accumulation
        # kills it, one that doesn't lets it survive (the blind spot surfaced).
        self.generic_visit(node)
        swap = _BINOP_SWAP.get(type(node.op))
        if swap is not None and self._hit():
            self.applied_desc = f"augassign {type(node.op).__name__}→{swap.__name__}"
            node.op = swap()
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        v = node.value
        # bool BEFORE int (bool is a subclass of int).
        if isinstance(v, bool):
            if self._hit():
                self.applied_desc = f"bool {v}→{not v}"
                return ast.copy_location(ast.Constant(value=not v), node)
        elif isinstance(v, int):
            if self._hit():
                self.applied_desc = f"int {v}→{v + 1}"
                return ast.copy_location(ast.Constant(value=v + 1), node)
        elif isinstance(v, str) and v != "":
            if (node.lineno, node.col_offset) in self._skip:
                return node  # docstring — not behaviour, never a mutation site
            if self._hit():
                self.applied_desc = "str→mutated"
                return ast.copy_location(ast.Constant(value=v + "\x00MUT"), node)
        return node


def _generate_mutants(source: str, max_mutants: int) -> list[tuple[str, str]]:
    """Return ``[(description, mutated_source), …]`` — one single-point mutation
    each, in stable order, capped at ``max_mutants``."""
    mutants: list[tuple[str, str]] = []
    target = 0
    while len(mutants) < max_mutants:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            break
        mutator = _NthMutator(target, _docstring_positions(tree))
        new_tree = mutator.visit(tree)
        if mutator.applied_desc is None:
            break  # ran out of mutation sites
        ast.fix_missing_locations(new_tree)
        try:
            mutated = ast.unparse(new_tree)
        except Exception:  # noqa: BLE001 - skip an un-unparseable mutant
            target += 1
            continue
        if mutated != source:
            mutants.append((mutator.applied_desc, mutated))
        target += 1
    return mutants


def _run(test_cmd: list[str], cwd: Path | None, timeout: float) -> bool:
    """True iff ``test_cmd`` exits 0.

    Runs with ``PYTHONDONTWRITEBYTECODE=1`` so NO ``.pyc`` is ever cached.
    Mutation testing rewrites the target many times per second; the ``.pyc``
    header records source mtime in *seconds*, so without this a rewrite within
    the same second as the baseline run silently reuses the baseline's
    (correct) bytecode and every mutant survives. Disabling the cache forces a
    fresh compile from source on every run — the correctness-critical fix.
    """
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        proc = subprocess.run(
            test_cmd, cwd=str(cwd) if cwd else None,
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


def verify_test_teeth(
    target_path: Path | str,
    test_cmd: list[str],
    *,
    cwd: Path | str | None = None,
    max_mutants: int = 20,
    timeout: float = 120.0,
) -> TeethReport:
    """Assess whether ``test_cmd`` actually pins the behaviour of ``target_path``.

    Returns a :class:`TeethReport`. ``baseline_passed=False`` (with no mutants)
    means the test does not even pass on the correct target — assessment is
    impossible, not a teeth failure. Charter: never raise on a mutant; the target
    file is always restored.
    """
    target = Path(target_path)
    cwd_path = Path(cwd) if cwd else None
    original = target.read_text(encoding="utf-8")

    # 1. Baseline must be green, or we can't assess teeth.
    if not _run(test_cmd, cwd_path, timeout):
        return TeethReport(baseline_passed=False)

    mutants = _generate_mutants(original, max_mutants)
    killed = 0
    survived: list[str] = []
    try:
        for desc, mutated in mutants:
            target.write_text(mutated, encoding="utf-8")
            if _run(test_cmd, cwd_path, timeout):
                survived.append(desc)  # test still passed → blind spot
            else:
                killed += 1
    finally:
        target.write_text(original, encoding="utf-8")  # always restore

    return TeethReport(
        baseline_passed=True,
        mutants_applied=len(mutants),
        mutants_killed=killed,
        survived=survived,
    )
