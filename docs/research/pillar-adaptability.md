# Pillar: Adaptability

## TL;DR

Chimera should adopt three core adaptability patterns from autoresearch-unified:

1. **Environment-Aware Bootstrapping**: Detect hardware/platform at startup and inject platform-specific constraints and opportunities directly into the LLM system prompt (GPU memory, FLOPS tier, backend capabilities).
2. **History-Informed Inner Loop**: Feed formatted experiment history (categorized by strategy type, keep/discard ratios per category) directly to the LLM before each proposal, allowing it to see what has worked and what has stagnated.
3. **Drift Detection + Prompt Injection**: Detect strategy stagnation (e.g., >80% of recent 15 experiments are learning-rate tuning with <2 keeps) and append a dynamic nudge to the LLM prompt suggesting alternative strategy directions, without modifying the underlying plan.

---

## Pattern 1: Environment-Aware Dynamic System Prompt

**Source:** `research/_clones/autoresearch-unified/tui/llm_backend.py:25–104` & `tui/hardware.py:116–141`

**What it does:**
At startup, `get_hardware_summary()` (hardware.py:116) probes the environment for chip name, memory, core count, and peak TFLOPS by querying platform-specific APIs: `hl-smi` (Intel Gaudi), `torch.cuda` (NVIDIA/AMD), `sysctl` (Apple Silicon). Then `get_system_prompt(hw_info)` (llm_backend.py:25) generates a **dynamic system prompt** that interpolates hardware facts into the base Claude instructions. Example (llm_backend.py:69–73): if memory ≥40GB, the prompt says "HBM is generous — time budget is the dominant constraint"; if <40GB, it says "Memory is limited — be mindful of depth and batch sizes." Platform-specific notes (llm_backend.py:35–67) embed backend hints: "torch.compile uses HIP graph capture" for ROCm 7.x, "CK Flash Attention is explicitly selected" for AMD ROCm 6.x, etc.

**Why we adopt:**
Eliminates the need for separate system prompts per hardware tier or platform. The LLM becomes aware of its operating constraints without explicit rule-based branching. Improves proposal quality early by grounding suggestions in what the hardware can actually do.

**How it fits Chimera:**
On agent startup, call an environment probe that maps to hardware tier, available backends, memory, and inferred time budget. Build `get_system_prompt()` as a template function that interpolates facts into the base system prompt. Pass the resulting prompt to all LLM calls, ensuring consistency across the agent's lifetime. Example: if Chimera runs on low-memory edge device, prompt suggests "small batch = more gradient steps = better"; on GPU cluster, prompt suggests "prioritize throughput and distributed training considerations."

---

## Pattern 2: Formatted History + Strategy Classification

**Source:** `research/_clones/autoresearch-unified/tui/results.py:191–224`, `tui/orchestrator.py:655–671`

**What it does:**
`format_history_for_prompt()` (results.py:191) reads the TSV results and renders a human-readable table with exp ID, status (keep/discard/crash), metrics, and description. Below the table, it adds a "Strategy summary footer" (results.py:212–222) that counts experiments per category (learning_rate, architecture, batch_size, schedule, regularization, infrastructure). The footer also shows "tried / kept" per category, e.g., "learning_rate: 12 tried, 3 kept" — giving the LLM visibility into **which directions have been fruitful**. Before calling the LLM, `_run_experiment()` (orchestrator.py:662) passes this formatted history + current hardware info + current best metric into the user prompt.

**Why we adopt:**
Giving the LLM a structured view of history prevents "amnesia" — it can see what categories have plateau'd and redirect. Strategy categorization (`classify_experiment()`, results.py:148–175) is automatic and requires no manual tagging. The summary footer is a **lightweight nudge mechanism** that doesn't require modifying the system prompt.

**How it fits Chimera:**
Store experiment results (or task outcomes) in a structured format: exp_id, description, outcome, strategy_category. Implement `classify_outcome()` that maps descriptions to high-level strategy buckets (e.g., if task is "optimize hyperparams," bucket outcome as "lr_tune", "arch_mod", "regularization"). Before querying the LLM for the next proposal, run `format_history_for_prompt()` to generate a summary that shows: recent experiments (last N rows), per-category success rates, metrics trend (best so far, recent trend). Pass this formatted history as part of the user prompt on every iteration.

---

## Pattern 3: Drift Detection + Nudge Injection

**Source:** `research/_clones/autoresearch-unified/tui/orchestrator.py:582–615`, `orchestrator.py:665–667`

**What it does:**
`_detect_stagnation()` (orchestrator.py:582) examines the last 15 experiments: if fewer than 2 have been kept, it **counts how many were learning_rate changes**. If ≥8 out of the recent 15 were learning-rate tuning with ≤2 keeps, it returns a **nudge string**. The nudge (orchestrator.py:607–613) is a markdown string suggesting "try a fundamentally different approach: batch size changes, architectural modifications, or schedule shape changes." This nudge is **appended to the results_history** before calling the LLM (orchestrator.py:665–667), so the LLM sees it as part of the prompt context, not as a system constraint.

**Why we adopt:**
Drift detection is **low-overhead**: a single pass through recent results. The nudge mechanism is **non-disruptive**: it's a text injection, not a plan revision. The LLM can ignore it if it has a good reason. It's **stateless**: no model state or memory is required, just a heuristic check. Catches the most common stagnation pattern: over-reliance on a single tuning lever (learning rate) when other strategies are underexplored.

**How it fits Chimera:**
Implement `detect_drift()` that checks: recent N outcomes (e.g., last 15 tasks), success rate: if ≤20% and ≥80% are from a single strategy bucket, flag as drift, return a nudge string (or None). Call `detect_drift()` before every LLM query. If drift is detected, append the nudge to the user prompt: "The last 15 attempts have been heavily focused on [strategy]. Consider trying [alternatives]." Log which drift nudges were triggered (for analysis), but don't block the proposal — the LLM is free to ignore or follow the nudge.

---

## Pattern 4: Near-Duplicate Detection + Re-Query

**Source:** `research/_clones/autoresearch-unified/tui/orchestrator.py:525–549`, `orchestrator.py:689–708`

**What it does:**
After the LLM generates a proposal, `_is_near_duplicate()` checks if an identical or very similar experiment has already been tried. Exact match check (orchestrator.py:540): case-insensitive string equality on the description. Semantic match check (orchestrator.py:545–546): extract (PARAM_NAME, target_value) pairs from the description using regex. If two descriptions propose the same param ↦ same value, they are duplicates even if the wording differs. If a duplicate is detected, the orchestrator **re-queries the LLM** with an appended nudge (orchestrator.py:694–701): "Your proposal '...' is a near-duplicate of a previous experiment. Please propose a DIFFERENT modification." Max 2 retry attempts (orchestrator.py:690); if still a duplicate after retries, proceed anyway (orchestrator.py:708).

**Why we adopt:**
Prevents wasted compute from redundant experiments. Semantic matching (via regex extraction) catches paraphrases and typos. Re-query is **cheap** relative to running a full experiment (1 API call vs. 5+ minutes of training).

**How it fits Chimera:**
After LLM proposes a task or plan modification, check if an equivalent proposal has already been executed. For code/config changes: normalize and compare AST or canonical form. For plans: extract key decisions (e.g., "increase batch_size to 64") and match against prior decisions. If duplicate detected: re-query with nudge, up to 2 times. Log retries for post-mortem analysis.

---

## Rejected / Weak Spots

- **Baseline Reset at Dataset Boundary**: autoresearch-unified resets the training script to a "clean" state when starting a new dataset run (`_ensure_clean_baseline()`, orchestrator.py:402–460). This prevents hyperparameter optimization from one dataset leaking to the next. **Chimera decision**: adopt if multi-task, but defer to the task scheduler — Chimera's job is adaptation within a task, not cross-task isolation.
- **Heartbeat Monitoring**: Orchestrator writes a `.runner_status.json` heartbeat every experiment (orchestrator.py:193–206). Useful for RunPod monitoring but orthogonal to adaptability. **Chimera decision**: skip for now; add if Chimera needs external liveness probes.
- **Implicit Strategy Categorization**: autoresearch infers strategy category post-hoc from the description. **Chimera could improve**: ask the LLM to output `STRATEGY: batch_size` explicitly, reducing false negatives in drift detection.

---

## Open Questions for the User

1. **Environment Probing Scope** — How extensive should Chimera's hardware detection be? Just available backends, plus memory/cores, plus software stack versions, plus estimated time budget per task?
2. **History Format** — TSV (like autoresearch) or integrated with an existing memory/observation system? Per-task or global?
3. **Drift Detection Tuning** — The autoresearch heuristic (8/15 learning-rate changes with ≤2 keeps) is tuned for HPO. What numbers are right for Chimera's task space?
4. **Re-Query Budget** — 2 re-queries on duplicate detection enough? Should re-queries have their own retry budget on API failure?
5. **Multi-Task Adaptation** — If Chimera runs multiple tasks sequentially, should insights from Task A transfer to Task B?

---

## References

- `research/_clones/autoresearch-unified/tui/orchestrator.py` — main loop, drift detector, duplicate guard
- `research/_clones/autoresearch-unified/tui/llm_backend.py:25–104` — dynamic system prompt
- `research/_clones/autoresearch-unified/tui/hardware.py:116–141` — hardware probing
- `research/_clones/autoresearch-unified/tui/results.py:148–224` — history formatting + strategy classification
- `research/_clones/autoresearch-unified/backends/__init__.py:26–140` — platform auto-detection
