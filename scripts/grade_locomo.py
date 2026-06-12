"""Grade Chimera's LoCoMo hypothesis JSONL via OpenRouter (ADR 0144).

Mirrors :mod:`scripts.grade_longmemeval` 1:1 in structure (same
LLM-judge mechanic, same reasoning-judge blocklist + override knob,
same ``max_tokens=16`` budget, same default judge model). The judge
prompt templates are the LongMemEval upstream templates re-used per
LoCoMo category — see the module docstring's "category mapping" section
for the mapping rationale.

The deliberate re-use of LongMemEval's judge family means ADR 0143's
noise envelope characterisation remains comparable across benchmarks.
Swapping the judge invalidates that comparability.

Usage
-----
::

    uv run python scripts/grade_locomo.py \\
        /tmp/chimera-baseline-locomo/results.jsonl \\
        /tmp/locomo/locomo10.json \\
        /tmp/chimera-baseline-locomo/results.graded.jsonl \\
        [openai/gpt-4o-mini]            # judge model (optional)

LoCoMo category → judge prompt template mapping
-----------------------------------------------

* ``single-hop`` / ``multi-hop`` / ``open-domain`` → LongMemEval's
  ``single-session-user`` template (yes/no, contains-correct-answer).
* ``temporal-reasoning`` → LongMemEval's ``temporal-reasoning``
  template (includes off-by-one tolerance for day/week/month answers).
* ``adversarial`` → LongMemEval's abstention template (does the model
  identify the question as unanswerable?).

This mapping is intentional: same judge + same prompt families = the
ADR 0143 noise envelope stays cross-benchmark-comparable.

Footgun (carried over from ADR 0143 / scripts/grade_longmemeval.py)
-------------------------------------------------------------------

Reasoning-model judges (``o1``, ``o3``, ``o4-mini``, …) consume the
``max_tokens=16`` budget on hidden chain-of-thought and silently zero
the graded JSONL. Default judge is ``openai/gpt-4o-mini``; reasoning
judges are blocklisted with an override knob
(``CHIMERA_GRADE_ALLOW_REASONING_JUDGE=1``) for operators who know
what they're doing.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


# ── Judge prompt templates (re-used from LongMemEval — see docstring) ──


def get_anscheck_prompt(category, question, answer, response):
    """LoCoMo-category → LongMemEval-template dispatch.

    ``category`` is the canonical adapter label
    (single-hop / multi-hop / temporal-reasoning / open-domain /
    adversarial).
    """
    if category == "adversarial":
        template = (
            "I will give you an unanswerable question, an explanation, and a response from a "
            "model. Please answer yes if the model correctly identifies the question as "
            "unanswerable. The model could say that the information is incomplete, or some "
            "other information is given but the asked information is not.\n\nQuestion: {}\n\n"
            "Explanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the "
            "question as unanswerable? Answer yes or no only."
        )
    elif category == "temporal-reasoning":
        template = (
            "I will give you a question, a correct answer, and a response from a model. "
            "Please answer yes if the response contains the correct answer. Otherwise, "
            "answer no. If the response is equivalent to the correct answer or contains "
            "all the intermediate steps to get the correct answer, you should also answer yes. "
            "If the response only contains a subset of the information required by the answer, "
            "answer no. In addition, do not penalize off-by-one errors for the number of days. "
            "If the question asks for the number of days/weeks/months, etc., and the model "
            "makes off-by-one errors (e.g., predicting 19 days when the answer is 18), the "
            "model's response is still correct. \n\nQuestion: {}\n\nCorrect Answer: {}\n\n"
            "Model Response: {}\n\nIs the model response correct? Answer yes or no only."
        )
    else:
        # single-hop / multi-hop / open-domain / (uncategorised) fallback
        template = (
            "I will give you a question, a correct answer, and a response from a model. "
            "Please answer yes if the response contains the correct answer. Otherwise, "
            "answer no. If the response is equivalent to the correct answer or contains "
            "all the intermediate steps to get the correct answer, you should also answer yes. "
            "If the response only contains a subset of the information required by the answer, "
            "answer no. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
            "Is the model response correct? Answer yes or no only."
        )
    return template.format(question, answer, response)


# Default judge — see module docstring footgun section.
DEFAULT_JUDGE = "openai/gpt-4o-mini"

_REASONING_JUDGE_BLOCKLIST = frozenset({
    "openai/o1",
    "openai/o1-mini",
    "openai/o1-preview",
    "openai/o3",
    "openai/o3-mini",
    "openai/o4-mini",
})


async def grade_one(provider, model_id, prompt):
    from chimera.providers import Message
    response = await provider.complete_with_tools(
        messages=[Message.user(prompt)],
        model_id=model_id,
        tools=[],
        max_tokens=16,
    )
    return (response.text or "").strip()


def _build_reference_map(ref_data):
    """Map item_id ("conv-26::qa0") → (category_label, question, gold_answer).

    Walks the upstream ``locomo10.json`` shape (list of conversations,
    each with a ``qa`` list).
    """
    from chimera.evals.locomo import canonical_category

    out: dict[str, tuple[str, str, str]] = {}
    for sample in ref_data:
        if not isinstance(sample, dict):
            continue
        sample_id = str(sample.get("sample_id") or "")
        for idx, qa in enumerate(sample.get("qa") or []):
            if not isinstance(qa, dict):
                continue
            item_id = f"{sample_id}::qa{idx}"
            cat_raw = qa.get("category")
            try:
                cat_int = int(cat_raw) if cat_raw is not None else 0
            except (TypeError, ValueError):
                cat_int = 0
            out[item_id] = (
                canonical_category(cat_int),
                str(qa.get("question") or ""),
                str(qa.get("answer") if qa.get("answer") is not None else ""),
            )
    return out


async def main():
    if len(sys.argv) < 4:
        print(
            "usage: grade_locomo.py <hyp.jsonl> <ref.json> <out.jsonl> [judge_model]\n"
            f"       default judge: {DEFAULT_JUDGE}",
            file=sys.stderr,
        )
        sys.exit(2)

    hyp_path = Path(sys.argv[1])
    ref_path = Path(sys.argv[2])
    out_path = Path(sys.argv[3])
    judge_model = sys.argv[4] if len(sys.argv) > 4 else DEFAULT_JUDGE

    if judge_model in _REASONING_JUDGE_BLOCKLIST and not os.environ.get(
        "CHIMERA_GRADE_ALLOW_REASONING_JUDGE"
    ):
        print(
            f"error: judge model {judge_model!r} is a reasoning model whose hidden "
            f"chain-of-thought consumes the max_tokens=16 budget, yielding empty "
            f"grades and silently zeroing every row. See module docstring + ADR 0143.\n"
            f"override: set CHIMERA_GRADE_ALLOW_REASONING_JUDGE=1 if you know what "
            f"you're doing (e.g. you've raised max_tokens in this script).",
            file=sys.stderr,
        )
        sys.exit(2)

    # NOTE: scripts/grade_longmemeval.py pins sys.path to the main
    # checkout for non-uv-run invocations. Here we trust the active
    # interpreter (typically `uv run`) — pinning a hard path would
    # shadow the worktree's chimera.evals.locomo with the parent
    # checkout's (where locomo.py doesn't yet exist on main).
    from chimera.providers import OpenRouterProvider

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("error: OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(2)

    provider = OpenRouterProvider()

    ref_data = json.load(open(ref_path))
    ref_map = _build_reference_map(ref_data)

    hyps = [json.loads(line) for line in open(hyp_path) if line.strip()]
    print(f"grading {len(hyps)} hypotheses with judge={judge_model}...")

    out_rows = []
    for i, h in enumerate(hyps):
        qid = h.get('item_id') or h.get('question_id')
        if qid not in ref_map:
            print(f"  skip {qid}: not in reference")
            continue
        category, question, gold = ref_map[qid]
        hyp_text = h.get('hypothesis') or h.get('answer') or ''

        prompt = get_anscheck_prompt(category, question, gold, hyp_text)
        verdict_text = await grade_one(provider, judge_model, prompt)
        is_correct = 'yes' in verdict_text.lower()

        out = dict(h)
        out['autoeval_label'] = {'model': judge_model, 'label': is_correct, 'raw': verdict_text}
        out['is_correct'] = is_correct
        out['category'] = category
        out_rows.append(out)
        print(
            f"  [{i+1:>2}/{len(hyps)}] {category:>20} {qid[:24]} → "
            f"{'✓' if is_correct else '✗'} ({verdict_text!r})"
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        for r in out_rows:
            fh.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(out_rows)} graded rows → {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
