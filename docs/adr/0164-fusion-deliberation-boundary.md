# ADR 0164 — OpenRouter Fusion: a deliberation boundary, not a gate

**Status:** Proposed (analysis + boundary decision; no integration shipped)
**Date:** 2026-06-04
**Builds on:** ADR 0160 (internal critic), ADR 0162 (in-loop critic enforcement),
ADR 0008 (trust ladder), ADR 0013 (alignment ceremony); relates to the
multi-witness critique surface (`chimera/skills/cross_critique.py`, v4.8)

## Context

OpenRouter shipped **Fusion** (beta), a *server-side* deliberation tool. You add
`{"type": "openrouter:fusion"}` to a chat-completion `tools` array; OpenRouter
then runs a **panel** of 1–8 models in parallel (each with web search/fetch),
hands their answers to a **judge** model, and returns a *structured comparison*
— not a merge:

```json
{"status":"ok",
 "analysis":{"consensus":[…],"contradictions":[…],"partial_coverage":[…],
             "unique_insights":[…],"blind_spots":[…]},
 "responses":[{"model":"…","content":"…"}]}
```

Configurable via `parameters`: `analysis_models[]` (the panel), `model` (the
judge), `max_tool_calls` (1–16), `max_completion_tokens`, `temperature`,
`reasoning`. Recursion-guarded (`x-openrouter-fusion-depth`). **Fail-soft:**
`status:"ok"` is returned even when some panelists drop out (`failed_models[]`),
and `analysis` is omitted (raw `responses` only) if the judge fails. Hard failure
(`status:"error"`) requires *all* panelists down / rate-limited / out of credit.

The temptation is obvious — and it is the wrong frame. Fusion is **not a new
capability** for Chimera. It is a managed re-implementation of a pattern Chimera
already owns and builds *more strictly*:

| Fusion concept | Existing Chimera analogue | Location |
|---|---|---|
| Panel of N models answer in parallel | `cross_critique()` fans witnesses concurrently (`asyncio.gather`, cheapest-first) | `chimera/skills/cross_critique.py:85` |
| Judge synthesizes a structured verdict | `AlignmentCeremony.run()` → `CeremonyVerdict` | `chimera/a2a/alignment.py:271` |
| Two-model panel + adjudication | critic gate: primary `sonnet-4-6` + escalator `opus-4-7` | `chimera/core/critic_gate.py` |
| `analysis_models[]` | `witnesses=(opus-4-7, gpt-5.1-codex-max, gemini-3.1-pro-preview)` | `cross_critique.py` |
| Server-side fan-out | local cross-model sub-agent spawn (Phase 3.4) | — |

So the real question is **not** "should we add Fusion" but: *where does a managed,
opaque, fail-**soft** panel beat Chimera's local, transparent, fail-**closed**
panel — and where does it actively break Chimera's guarantees?*

## Decision

Treat Fusion as an **optional PLAN-phase deliberation primitive only**, walled
off from every enforcement surface. Concretely:

1. **ALLOWED — PLAN-phase idea divergence (Creativity pillar).** Fusion's
   `blind_spots` + `unique_insights`, web-grounded, are exactly the breadth the
   proposer wants for the open-ended, *low-stakes-if-wrong* question "**what is
   worth building?**" A missed panelist there costs nothing, so fail-soft is
   acceptable. This is the one genuinely *additive* value: web-grounded panel
   breadth without writing the orchestration.

2. **FORBIDDEN — the critic gate (ADR 0162), the alignment ceremony (ADR 0013),
   and `submit_pr.validate()`.** These are load-bearing and must stay local:
   - The gate is **calibrated** (0% false-approve across 27 cases) and
     **fail-closed** (unparseable verdict = rejection). Fusion is *uncalibrated*
     (we control neither panel prompts nor judge rubric), *opaque* (the exact
     deliberation is not replayable), and *fail-soft* (`status:"ok"` while
     panelists silently drop). Routing the commit chokepoint through Fusion would
     swap a measured 0%-false-approve adjudicator for an unmeasured one, break
     `critic-gate-log.jsonl` replayability (we could record the verdict but not
     *why*), and invert a fail-closed boundary into a fail-soft one — the precise
     opposite of the gate's charter.
   - Lockdown / alignment decisions must be deterministic and local (ADR 0013).
   - `submit_pr.validate()` secret-path + Shannon-entropy scans **cannot** be
     delegated to an opaque service — that is the exact surface the classifier
     correctly blocked from being weakened (2026-06-02 `allow_entropy` episode).

3. **If integrated**, ship behind a default-OFF config flag as a sibling to
   `cross_critique` (a `fusion_deliberate()` returning a typed `FusionAnalysis`),
   with a dedicated response-parse path. Note the mechanical asymmetry: the
   request side is a passthrough (`complete_with_tools` already forwards `tools`
   verbatim — `chimera/providers/openrouter.py:243`), but the **response** side
   (lines 271–282) extracts `tool_calls` for the *client-side* ACT loop to
   execute. Fusion resolves *server-side*; its `analysis` returns inside
   `message.content`, never as a dispatchable `tool_use` block. A naive injection
   would silently drop the structured analysis — so a real integration needs a
   typed parse, not a one-line passthrough.

## Why the boundary (threat / cost model)

- **Trust (ADR 0008).** Server-side panel selection is a new, unattested input.
  Anything influencing `WHAT`/`PLAN` may be ungated; anything touching `ENFORCE`
  must be local. Fusion lives strictly on the PLAN side of that line.
- **Cost.** One Fusion call = N panel calls + 1 judge call, each web-enabled,
  **server-side and unpriced by Chimera**. This punches a hole in
  `cost_estimate.py::_price_table()`, whose per-model `$/M` accounting cannot see
  inside a Fusion call. The value dossier (`mind/research/value-assessment-keep-
  or-kill-2026-06-03.md`) could state "$0.0037 / commit" only because Chimera
  prices *every* call; Fusion returns an opaque aggregate. **Net: a metering
  regression** — acceptable for occasional PLAN ideation, not for any hot path.
- **Safety.** Web-fetch *inside* the panel is an uncontrolled egress and
  prompt-injection surface that Chimera's own tools gate. Fine for PLAN ideation,
  unacceptable near ENFORCE.

## Consequences

- The Creativity pillar *may* gain a wider, web-grounded divergence option, gated
  behind a flag — at the cost of opacity and unmetered spend on that path.
- The durable artifact is the **recorded boundary**: "managed multi-model
  deliberation is allowed to inform *what we do*, never to decide *whether a
  change is safe to land*." Chimera's two crown jewels — fail-closed adjudication
  and measured per-call cost — are explicitly *not* traded away for not writing
  an `asyncio.gather`.
- Reversible and inert by default: no flag, no Fusion.

## Status note

**Proposed, not built.** No code ships with this ADR; it records the design model
and the boundary so a future integration cannot quietly route enforcement through
an opaque server tool. Companion analysis:
`mind/research/fusion-deliberation-model-2026-06-04.md`.
