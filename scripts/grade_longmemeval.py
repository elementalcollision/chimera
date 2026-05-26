"""Grade Chimera's LongMemEval hypothesis JSONL via OpenRouter.

Mirrors the upstream ``src/evaluation/evaluate_qa.py`` prompt template
exactly so scores are comparable. Uses Chimera's
``OpenRouterProvider`` + a configurable judge model. Writes a graded
JSONL with ``autoeval_label`` per row so
``chimera.evals.longmemeval.summarize_results`` can aggregate it.

Usage
-----
::

    uv run python scripts/grade_longmemeval.py \\
        /tmp/chimera-baseline-s/results.jsonl \\
        /Users/dave/Claude_Primary/LongMemEval/data/longmemeval_oracle.json \\
        /tmp/chimera-baseline-s/results.graded.jsonl \\
        [openai/gpt-4o-mini]            # judge model (optional)

Default judge: ``openai/gpt-4o-mini``
-------------------------------------

**Footgun (2026-05-25, ADR 0143):** Earlier copies of this script
defaulted the judge to ``openai/o4-mini``. o4-mini is a reasoning
model — its hidden chain-of-thought consumes the ``max_tokens=16``
budget before any visible text is emitted, so every grade silently
returns the empty string and is labelled wrong. That zeros out the
graded JSONL across the board and was caught by T2.1c's noise-envelope
chip when comparing graders.

Default is now ``openai/gpt-4o-mini`` (small, fast, deterministic-ish
under low max_tokens, used by every load-bearing baseline note). If
you swap in a different judge, **the noise envelope in ADR 0143 is
grader-conditional and must be re-characterised** — do not extrapolate
across judges.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path


# ── Upstream prompt template (verbatim from evaluate_qa.py) ──────


def get_anscheck_prompt(task, question, answer, response, abstention=False):
    if not abstention:
        if task in ('single-session-user', 'single-session-assistant', 'multi-session'):
            template = (
                "I will give you a question, a correct answer, and a response from a model. "
                "Please answer yes if the response contains the correct answer. Otherwise, "
                "answer no. If the response is equivalent to the correct answer or contains "
                "all the intermediate steps to get the correct answer, you should also answer yes. "
                "If the response only contains a subset of the information required by the answer, "
                "answer no. \n\nQuestion: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
                "Is the model response correct? Answer yes or no only."
            )
        elif task == 'temporal-reasoning':
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
        elif task == 'knowledge-update':
            template = (
                "I will give you a question, a correct answer, and a response from a model. "
                "Please answer yes if the response contains the correct answer. Otherwise, "
                "answer no. If the response contains some previous information along with an "
                "updated answer, the response should be considered as correct as long as the "
                "updated answer is the required answer.\n\nQuestion: {}\n\nCorrect Answer: {}\n\n"
                "Model Response: {}\n\nIs the model response correct? Answer yes or no only."
            )
        elif task == 'single-session-preference':
            template = (
                "I will give you a question, a rubric for desired personalized response, and a "
                "response from a model. Please answer yes if the response satisfies the desired "
                "response. Otherwise, answer no. The model does not need to reflect all the points "
                "in the rubric. The response is correct as long as it recalls and utilizes the "
                "user's personal information correctly.\n\nQuestion: {}\n\nRubric: {}\n\n"
                "Model Response: {}\n\nIs the model response correct? Answer yes or no only."
            )
        else:
            raise ValueError(f"Unknown task type: {task}")
    else:
        template = (
            "I will give you an unanswerable question, an explanation, and a response from a "
            "model. Please answer yes if the model correctly identifies the question as "
            "unanswerable. The model could say that the information is incomplete, or some "
            "other information is given but the asked information is not.\n\nQuestion: {}\n\n"
            "Explanation: {}\n\nModel Response: {}\n\nDoes the model correctly identify the "
            "question as unanswerable? Answer yes or no only."
        )
    return template.format(question, answer, response)


# Default judge — see module docstring for the footgun explanation.
DEFAULT_JUDGE = "openai/gpt-4o-mini"

# A small set of model IDs whose visible output is starved by the
# upstream max_tokens=16 budget because they consume the budget on
# hidden reasoning tokens. Refusing these by default prevents the
# silent "everything is wrong" failure mode documented in ADR 0143.
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


async def main():
    if len(sys.argv) < 4:
        print(
            "usage: grade_longmemeval.py <hyp.jsonl> <ref.json> <out.jsonl> [judge_model]\n"
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

    sys.path.insert(0, '/Users/dave/uberagent')
    from chimera.providers import OpenRouterProvider

    if not os.environ.get("OPENROUTER_API_KEY"):
        print("error: OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(2)

    provider = OpenRouterProvider()

    # Load reference (the upstream dataset is a JSON array).
    ref = json.load(open(ref_path))
    qid2ref = {e['question_id']: e for e in ref}

    # Load hypotheses (our JSONL).
    hyps = [json.loads(l) for l in open(hyp_path) if l.strip()]
    print(f"grading {len(hyps)} hypotheses with judge={judge_model}...")

    out_rows = []
    for i, h in enumerate(hyps):
        qid = h.get('question_id') or h.get('item_id')
        if qid not in qid2ref:
            print(f"  skip {qid}: not in reference")
            continue
        ref_e = qid2ref[qid]
        qtype = ref_e['question_type']
        question = ref_e['question']
        gold = ref_e['answer']
        hyp_text = h.get('hypothesis') or h.get('answer') or ''
        is_abstention = '_abs' in qid

        prompt = get_anscheck_prompt(qtype, question, gold, hyp_text, abstention=is_abstention)
        verdict_text = await grade_one(provider, judge_model, prompt)
        is_correct = 'yes' in verdict_text.lower()

        out = dict(h)
        out['autoeval_label'] = {'model': judge_model, 'label': is_correct, 'raw': verdict_text}
        out['is_correct'] = is_correct  # for summarize_results
        out['category'] = qtype          # canonical from reference
        out_rows.append(out)
        print(f"  [{i+1:>2}/{len(hyps)}] {qtype:>28} {qid[:8]} → {'✓' if is_correct else '✗'} ({verdict_text!r})")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        for r in out_rows:
            fh.write(json.dumps(r) + "\n")
    print(f"\nwrote {len(out_rows)} graded rows → {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
