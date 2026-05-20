# Notes — q002

*Topic:* Fresh session initiation; no prior history to analyze for patterns or repetition.

*Cycle:* 1

## Findings

## Findings Note: Cold-Start Personalization in LLM-Based Systems

The "cold-start problem" — personalizing an AI system before any user history exists — has spawned a surge of research as LLMs move into production. Three recent papers reveal a rapidly maturing field where the central insight is counterintuitive: **bigger models don't solve cold-start; structured reasoning about what to ask next does.**

**State of the Art.** Two competing paradigms dominate. Zhao et al. (2025) pursue *meta-learning for prompt-tuning* — using MAML and Reptile to learn soft-prompt embeddings that encode user behavioral priors, achieving real-time personalization in ~275ms on consumer GPUs [arxiv.org/abs/2507.16672]. In contrast, Bose et al. (2026) from Meta/UW/Allen AI propose **Pep**, a *training-free Bayesian approach* that learns a structured world model of preference correlations offline, then performs lightweight online inference to select maximally informative questions [arxiv.org/abs/2602.15012]. Pep reaches 80.8% preference alignment vs. 68.5% for RL baselines, using 3–5× fewer interactions and only ~10K parameters versus 8B.

**Most Surprising Finding.** The Bose et al. paper exposes a damning failure mode: RL-trained elicitation policies *collapse to static question sequences that ignore user responses*. When two users give different answers to the same question, RL changes its follow-up only 0–28% of the time. Pep, with its factored Bayesian model, adapts follow-ups 39–62% of the time. The bottleneck isn't model capacity — it's the ability to exploit the *factored structure* of preference data. RL's terminal reward signal simply cannot recover per-dimension information.

**Broader landscape.** Amazon Alexa's TAI system (Kong et al., 2023) tackles the same problem from the conversational side, using teachable interactions to bootstrap user models [arxiv.org/abs/2309.05127]. Hafnar & Demšar (2024) demonstrate zero-shot LLM personalization for game level generation, outperforming traditional procedural methods on player retention [arxiv.org/abs/2402.10133].

The unifying thread: cold-start personalization is fundamentally a *routing problem* — dozens of preference dimensions exist, but individual users care about only a handful, and which ones depends on who's asking. The winning approaches aren't the largest models; they're the ones that ask the right questions and actually listen to the answers.
