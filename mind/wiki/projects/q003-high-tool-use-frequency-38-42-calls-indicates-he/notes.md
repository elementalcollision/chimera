# Notes — q003

*Topic:* High tool_use frequency (38/42 calls) indicates heavy reliance on tool-augmented reasoning or code generation.

*Cycle:* 142

## Findings

## Findings Note: High Tool-Use Frequency in LLM Agents

A 38-of-42 tool-call ratio (90.5%) isn't just high — it's a symptom of a now well-documented pathology in tool-augmented LLM agents. Three recent papers converge on the same finding: agents over-call tools, often to their own detriment.

**The "tool-use tax."** Zhang et al. (2026) demonstrate that tool-augmented reasoning does *not* universally beat native chain-of-thought. In the presence of semantic distractors — irrelevant data interleaved with task-relevant information — the overhead of the tool-calling protocol itself degrades performance. They decompose this into prompt-formatting cost, protocol overhead, and actual tool-execution gain. The punchline: gains from tools frequently fail to offset the tax. Their G-STEP gating mechanism partially recovers the loss but can't eliminate it ([arxiv.org/abs/2605.00136](https://arxiv.org/abs/2605.00136)).

**The overuse is a learned behavior, not a reasoned choice.** Zeng et al. (2026) identify two root causes. First, a "knowledge epistemic illusion" — models cannot accurately perceive the boundary of their own internal knowledge and default to tool calls. Second, outcome-only reward signals in RL training inadvertently reward tool use regardless of efficiency. By balancing reward signals during training, they cut unnecessary tool calls by 66.7–82.8% *with no accuracy sacrifice* ([arxiv.org/abs/2604.19749](https://arxiv.org/abs/2604.19749)).

**The most surprising finding: models already know, they just don't listen.** Sun et al. (2026) show that tool necessity is linearly decodable from pre-generation hidden states with AUROC 0.89–0.96 across six models. The model "knows" whether a tool is needed before it generates a single token — but it fails to act on that signal. Their Probe&Prefill intervention reads the hidden-state signal and steers generation accordingly, reducing tool calls by 48% with only 1.7% accuracy loss, while baseline prompt-engineering achieves comparable reduction only with 5× higher accuracy cost ([arxiv.org/abs/2605.09252](https://arxiv.org/abs/2605.09252)).

**State of the art:** The field is converging on lightweight, inference-time gating mechanisms (linear probes, meta-cognition triggers) rather than heavier RL-based retraining. The deeper lesson: high tool-use frequency is less about capability and more about a misalignment between what the model implicitly knows and what it explicitly decides. For an agent like Chimera running at 90%+ tool-call rates, the implication is clear — a simple linear probe over the pre-generation hidden state could likely cut tool calls nearly in half with negligible quality loss.
