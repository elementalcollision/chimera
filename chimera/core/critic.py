"""Internal critic — adjudicate whether a change is faithful and mergeable.

The faithfulness gate (ADR 0159) proved its own boundary: mutation + differential
can DETECT a behaviour problem (surviving mutants, output deltas) but cannot
ADJUDICATE which direction is correct when the test suite is silent — that is
irreducibly a judgment call. The first live soak's `isdigit` regression is the
case in point: the differential flags that `to_snake("foo2Bar")` changed, but
only *judgment* (reading the docstring "lowercase or a digit") decides the drop
is wrong.

This module is that judgment, as a contract-free stand-in for human review: give
a (cross-model) reviewer the change's goal, the diff, the touched code's
docstring (intent), and the faithfulness report, and have it adjudicate —
approve ONLY if the change faithfully fixes the bug without silently removing or
regressing untested behaviour. Mirrors the charter generator's provider pattern.

Charter: **fail-closed**. A verdict that cannot be parsed, or omits an explicit
approval, is NOT an approval — an unreadable critic must never wave a change
through. (The mutation/verify gates remain authoritative regardless.)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

_VERDICT_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass
class CriticVerdict:
    approved: bool
    concerns: list[str] = field(default_factory=list)
    rationale: str = ""
    parsed: bool = True  # False when the model output could not be read

    def summary(self) -> str:
        head = "APPROVED" if self.approved else "REJECTED"
        if not self.parsed:
            head = "REJECTED (unparseable verdict — fail-closed)"
        if self.concerns:
            return f"{head} — " + "; ".join(self.concerns)
        return f"{head} — {self.rationale or '(no rationale)'}"


def build_review_prompt(
    diff: str,
    *,
    goal: str | None = None,
    docstring: str | None = None,
    faithfulness: str | None = None,
) -> str:
    """Construct the adjudication prompt. The reviewer must approve ONLY a change
    that faithfully fixes the bug — not one that passes the suite by deleting or
    silently regressing untested behaviour."""
    parts = [
        "You are a senior engineer reviewing an autonomous agent's code change. "
        "Your job is to ADJUDICATE faithfulness: approve ONLY if the change "
        "accomplishes its stated goal WITHOUT silently removing or regressing "
        "BEHAVIOUR that the test suite does not cover.",
        "",
        "Two kinds of change need DIFFERENT scrutiny — identify which this is:",
        "- **Behaviour-neutral maintenance** (lint/format fixes, removing "
        "genuinely-unused imports or dead code a linter flagged, "
        "equivalence-preserving refactors). These REMOVE or rewrite code BY "
        "DESIGN; that is the point, not a red flag. Removing code that is "
        "genuinely unused preserves behaviour — APPROVE it. Reject ONLY if a "
        "removed/changed element is actually load-bearing in a way the tests miss "
        "— e.g. an import kept for a registration/side-effect, or a branch some "
        "untested input still reaches.",
        "- **Bug fixes** (a failing test now passes). Scrutinise whether the suite "
        "was made to pass by DELETING or short-cutting untested behaviour rather "
        "than genuinely fixing it. A change that passes by deleting an untested "
        "branch, or hard-coding the expected output, is NOT faithful.",
        "",
    ]
    if goal:
        parts += [f"## Goal\n{goal}", ""]
    parts += [f"## Diff\n```diff\n{diff}\n```", ""]
    if docstring:
        parts += [
            "## Intent (docstring of the touched code — the source of truth for "
            f"behaviour the tests may not pin)\n{docstring}", "",
        ]
    if faithfulness:
        parts += [
            "## Faithfulness report (machine-derived, no human spec)\n"
            "Surviving mutants = behaviour no test pins; behaviour deltas vs "
            "base = outputs that changed (each must be a change the failing test "
            f"DEMANDED, else it is a silent regression).\n{faithfulness}", "",
        ]
    parts += [
        "## Output",
        "Reply with EXACTLY one fenced json block and nothing else:",
        "```json",
        '{"approved": true|false, "concerns": ["..."], "rationale": "..."}',
        "```",
        "Approve when you are confident the change preserves all behaviour the "
        "goal intends to keep. 'When in doubt, reject' applies to doubt about a "
        "BEHAVIOUR CHANGE or a load-bearing removal — NOT to deletions that are "
        "provably unused cleanup. Do not reject a behaviour-neutral maintenance "
        "change merely because it removes lines.",
    ]
    return "\n".join(parts)


def parse_verdict(text: str) -> CriticVerdict:
    """Parse the model's fenced json verdict. Fail-closed: any parse failure or
    a missing/false ``approved`` yields a non-approval."""
    if not text:
        return CriticVerdict(False, ["empty critic output"], parsed=False)
    m = _VERDICT_BLOCK.search(text)
    raw = m.group(1) if m else text.strip()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return CriticVerdict(False, ["unparseable critic verdict"], parsed=False)
    if not isinstance(data, dict) or "approved" not in data:
        return CriticVerdict(False, ["verdict missing 'approved'"], parsed=False)
    approved = data.get("approved") is True  # only literal true approves
    concerns = data.get("concerns") or []
    if not isinstance(concerns, list):
        concerns = [str(concerns)]
    return CriticVerdict(
        approved=approved,
        concerns=[str(c) for c in concerns],
        rationale=str(data.get("rationale", "")),
    )


async def review_change(
    diff: str,
    *,
    provider,
    model_id: str,
    goal: str | None = None,
    docstring: str | None = None,
    faithfulness: str | None = None,
    max_tokens: int = 1024,
) -> CriticVerdict:
    """Ask a (cross-model) reviewer to adjudicate a change's faithfulness.

    Returns a :class:`CriticVerdict`; fail-closed on any provider/parse error
    (an unreadable critic never approves). The deterministic gates
    (verify/mutation) remain authoritative; this adds the judgment they cannot.
    """
    from ..providers.base import Message

    prompt = build_review_prompt(
        diff, goal=goal, docstring=docstring, faithfulness=faithfulness,
    )
    try:
        response = await provider.complete_with_tools(
            messages=[Message.user(prompt)], model_id=model_id, tools=[],
            max_tokens=max_tokens,
        )
    except Exception as exc:  # provider error → fail-closed
        return CriticVerdict(False, [f"critic provider error: {exc}"], parsed=False)
    return parse_verdict(getattr(response, "text", "") or "")
