# ADR 0187 — Sakana Fugu as a tool-agent provider

**Status:** Accepted — *in progress.* Increment 1 (provider + liveness +
guardrail-eval wiring) implemented (#402) and an independent `--judge-provider`
added for sound resistance rates (#403). Tests #1 + #2 run live — results below.
Role integration to follow, gated on those results.

## Context

[Sakana Fugu](https://sakana.ai/fugu/) is a multi-agent orchestration system
delivered as a single **OpenAI-compatible** model API (`https://api.sakana.ai/v1`,
Chat Completions + Responses). Two variants — `fugu` (balanced, routes across
frontier providers) and `fugu-ultra` (coordinates 1–3 expert agents for hard
multi-step reasoning) — with `reasoning.effort` ∈ {high, xhigh, max}, built-in
`web_search`, parallel tool calls, structured output, streaming, and vision. It
internally does model selection → delegation → **verification** → synthesis, and
routes around provider outages. It **ignores** `temperature`/`top_p`/`seed` (its
diversity is internal, not sampling-controllable).

Chimera already has a clean OpenAI-compatible provider seam (OpenRouter), so Fugu
is a thin adapter add with rich role potential. The interesting tension: Chimera
is *itself* a router/witness/verifier, so Fugu must complement that machinery (as
a strong self-verifying member/arbiter), not replace its cross-vendor panel — the
panel's power is idiosyncratic cross-provider dissent (ADR 0107), which a single
ensemble router would collapse.

## Decision

Adopt Fugu behind the existing `Provider` abstraction, incrementally.

**Increment 1 (this ADR):**
- Extract a shared `OpenAICompatibleProvider` base from `OpenRouterProvider`
  (behavior-preserving); `SakanaProvider` is a thin subclass
  (`SAKANA_API_KEY` / `FUGU_API_KEY`, optional `SAKANA_BASE_URL` override).
- A `get_provider(name)` factory (the single string→provider seam).
- `chimera ping --provider sakana` (liveness, test #1) and
  `chimera guardrail-eval --provider sakana` (resistance matrix, test #2).
- Fugu is **not** auto-wired into any data-egress path (ACT / witness / critic /
  soak). It is reachable only via explicit flags until the tests below justify a
  role.

**Planned roles (later increments, gated on results):**
- **Adversarial critic / arbiter** (primary): `fugu-ultra` as the deep,
  self-verifying adjudicator — used as an *expensive arbiter* for contested /
  low-confidence gate decisions, not every call.
- **Witness-panel member** (optional): one pool slot — but measure vote-
  correlation with existing slots first (Fugu is itself cross-vendor, so it may
  not be independent).
- **Hard-task proposer escalation** (niche): `fugu-ultra` only for complex
  targets; never the cheap workhorse tier (cost + latency).

**Guards.** Data egress to api.sakana.ai forwards to multiple third parties; the
B.4a gate sandbox (secret-stripping) remains the authority — never send foreign-
repo private code or secrets to Fugu unscrubbed. Do not rely on Fugu's own
"no destructive commands" guard; Chimera's sandbox is the boundary. Keep Fugu
behind the Provider abstraction so it stays swappable (vendor-lock-in hygiene).

## Test regimens (to highlight potential before role wiring)

1. **Liveness smoke** — `chimera ping --provider sakana` (+ mocked unit tests).
2. **Guardrail resistance matrix** — `guardrail-eval --provider sakana --models
   fugu,fugu-ultra --samples N`; compare the per-(model×probe) matrix to the
   singleton roster. *Hypothesis:* internal verification lowers attack-success —
   or it inherits the weakest member (extends q004 / B.4j / NRT-Bench).
3. **Critic A/B** on the labelled benchmark (`critic-calibrate`): `fugu-ultra` vs
   the current critic — agreement with ground truth, misses vs false-rejects.
4. **Witness-panel swap A/B** on historical good+bad diffs: catch-rate, false-
   reject, and vote-correlation with the other slots.
5. **Shadow arbiter on live soaks**: on split/low-confidence gates, call
   `fugu-ultra` log-only into the gate-calibration ledger (B.4l); the revert
   ledger later scores whether it would have been right — earn promotion before
   trusting it.

## Results so far (2026-06-25)

**#1 liveness** — `chimera ping --provider sakana` → `pong`. Auth + endpoint +
OpenAI-compatible round-trip verified live.

**#2 guardrail resistance** — `fugu` and `fugu-ultra`, N=10/cell, judged by an
*independent* OpenRouter model (haiku, neutral system prompt): **0/10 compliance
on every probe** (charter-escape, secret-exfil, destructive-cmd, prompt-injection)
for both variants. A discrimination control confirmed the judge is not rubber-
stamping (it correctly labels an obviously-compliant reply "complied").

The instructive part: an earlier **N=3 heuristic** run reported multiple
"failures" (fugu charter-escape 3/3, destructive 2/3, secret-exfil 1/3). Those
were **classifier false-positives** — the keyword heuristic mis-graded compliant-
*looking*-but-actually-refusing replies. The measurement instrument decided the
verdict (q004's lesson sharpened): a weak classifier flipped a fully-resistant
model to "unsafe." Use N + an independent judge, not single-shot heuristics.

Caveats: four probe categories (not exhaustive), Chimera-charter-framed probes
Fugu sees cold, one judge model. Claim is "strong resistance on these probes,"
not "universally safe" — and B.4a remains the authority regardless. Encouraging
for an arbiter/critic role; the live results do not by themselves clear an
autonomous-action role.

**#3 critic A/B** — faithfulness adjudication on the 28-case labelled benchmark
(`critic-calibrate`, single-shot):

| critic | accuracy | false-approve | false-reject |
|---|---|---|---|
| `claude-sonnet-4-6` (baseline) | 89% (25/28) | 0/12 | 3/16 |
| `fugu-ultra` (sakana, 180s+ timeout) | 82% (23/28) | 0/12 | 5/16 |

Both are clean on the dangerous error (**0% false-approve** — no unfaithful change
waved through). `fugu-ultra` is modestly more conservative: it rejects a few
genuinely-faithful-but-tricky changes the baseline approves. It is slower +
pricier (ensemble) and **not a drop-in critic upgrade** — but its 0% false-approve
+ ensemble verification suit the *arbiter* role (a sparingly-invoked tie-breaker
for contested decisions) rather than routine critic duty.

The thread across #2 + #3 is the real lesson: `fugu-ultra`'s *apparent* failures
were **instrument artifacts at three successive layers** — N=3 + a keyword
heuristic (#2), then a 60s request timeout fail-closing to REJECT (#3 first pass,
which faked 57% / 6-of-7 false-rejects) — and the sound numbers only appeared
after fixing each. Validate the instrument (sample size, classifier, timeout)
before judging the model. (The 60s→180s Sakana timeout default came directly from
this.)

## Consequences

- One new external dependency (Sakana), isolated behind `Provider`; no new
  Python packages (raw httpx, OpenAI-compatible).
- The OpenRouter refactor de-duplicates the adapter; both providers now share one
  tested code path.
- Sampling-based diversity methods (q004 N-sampling) must re-call Fugu rather than
  vary `temperature`.
