# Research note — Modeling OpenRouter Fusion into the Chimera stack

**Date:** 2026-06-04
**Trigger:** Operator shared the OpenRouter Fusion docs and asked: *"Review this
and model what it would look like in the Chimera stack."*
**Outcome:** ADR 0164 (deliberation boundary). This note is the working analysis
behind it.

---

## 1. What Fusion is (as fetched, 2026-06-04)

A **beta server-side tool**. You add `{"type":"openrouter:fusion"}` to a
chat-completion `tools` array. OpenRouter then:

1. **Panel** — runs 1–8 models in parallel, each with web search/fetch enabled,
   on the user prompt.
2. **Judge** — a designated judge model reads the panel answers and produces a
   *structured comparison* (not a merge).
3. **Outer model** — your request's model consumes that analysis to write the
   final answer.

Auto-fires only when the model judges multiple perspectives worthwhile;
`tool_choice:"required"` forces it. Parameters (`parameters` object):
`analysis_models[]` (panel, default a quality preset), `model` (judge, defaults
to the outer model), `max_tool_calls` (1–16, default 8), `max_completion_tokens`,
`temperature` (0–2), `reasoning`. Recursion-guarded
(`x-openrouter-fusion-depth`).

**Failure semantics (the load-bearing detail):**
- ≥1 panelist succeeds → `status:"ok"` + `failed_models[]`.
- Judge fails but panels succeed → `analysis` omitted, raw `responses` returned.
- All panels down / rate-limited / no credit → `status:"error"` + `failure_reason`.

Response shape:

```json
{"status":"ok",
 "analysis":{"consensus":[…],"contradictions":[{"topic":…,"stances":[…]}],
             "partial_coverage":[…],"unique_insights":[{"model":…,"insight":…}],
             "blind_spots":[…]},
 "responses":[{"model":"anthropic/claude-opus-4.5","content":"…"}, …]}
```

## 2. The central finding: Chimera already *is* a Fusion engine — three times

Fusion is a managed clone of a pattern Chimera built locally and built *stricter*:

| Fusion | Chimera analogue | File |
|---|---|---|
| Parallel panel | `cross_critique()` — `asyncio.gather`, witnesses cheapest-first | `chimera/skills/cross_critique.py:85` |
| Judge → structured verdict | `AlignmentCeremony.run()` → `CeremonyVerdict` (aggregates 5 strategy reports) | `chimera/a2a/alignment.py:271` |
| 2-model panel + adjudication | critic gate: primary `sonnet-4-6` + escalator `opus-4-7` | `chimera/core/critic_gate.py` |
| `analysis_models[]` | `witnesses=(opus-4-7, gpt-5.1-codex-max, gemini-3.1-pro-preview)` | `cross_critique.py` |
| Server-side fan-out | cross-model sub-agent spawn (Phase 3.4) | — |

So this was never a "do we add a feature" question. It is: **where does the
managed version beat ours, and where does it break our guarantees?**

## 3. The mechanical asymmetry (request passes, response doesn't)

The request side is a one-liner — `complete_with_tools` forwards `tools` verbatim:

```python
# chimera/providers/openrouter.py:243
if tools:
    body["tools"] = tools          # {"type":"openrouter:fusion", …} rides through
```

But the **response** side assumes *client-side* tool calling — it extracts
`tool_calls` for the ACT loop to dispatch (lines 271–282). Fusion resolves
*server-side*; its `analysis` comes back inside `message.content`, never as a
dispatchable `tool_use` block. **A naive `tools`-injection would silently drop the
structured analysis.** Any real integration needs a typed parse path
(`parse_fusion_analysis → FusionAnalysis`), not a passthrough.

## 4. Fit map

**✅ Good fit — PLAN-phase idea divergence (Creativity pillar).**
`blind_spots` + `unique_insights`, web-grounded, are precisely what the proposer
wants for the open-ended "*what is worth building?*" question. Low-stakes-if-wrong
→ fail-soft is fine. Conceptual shape, sibling to `cross_critique`:

```python
async def fusion_deliberate(prompt, *, judge, panel, provider: OpenRouterProvider) -> FusionAnalysis:
    resp = await provider.complete_with_tools(
        [Message.user(prompt)], model_id=judge,
        tools=[{"type":"openrouter:fusion",
                "parameters":{"analysis_models": panel, "model": judge,
                              "max_tool_calls": 6}}],
    )
    return parse_fusion_analysis(resp)   # consensus / contradictions / blind_spots / …
```

**🚫 Wrong fit — the critic gate / alignment ceremony / submit_pr.validate().**
The gate is **calibrated** (0% false-approve / 27 cases) and **fail-closed**.
Fusion is **uncalibrated** (we own neither panel prompt nor judge rubric),
**opaque** (deliberation not replayable), **fail-soft** (`ok` while panelists
drop). Routing enforcement through it would:
- trade a *measured* 0%-false-approve adjudicator for an unmeasured one;
- break `critic-gate-log.jsonl` replayability — we'd log the verdict, not the why;
- invert fail-closed → fail-soft at the commit chokepoint (charter inversion).

Same logic excludes the ceremony (lockdown must be deterministic + local) and
`submit_pr.validate()` (secret/entropy scans cannot be delegated to an opaque
service — the surface I was *correctly blocked* from weakening, 2026-06-02).

## 5. Trust / cost / safety

- **Trust (ADR 0008):** server-chosen panel = unattested input. PLAN-side OK;
  ENFORCE-side no. Fusion lives strictly on the PLAN side.
- **Cost:** 1 Fusion call = N panel + 1 judge, web-enabled, **unpriced by
  Chimera** → a hole in `cost_estimate.py::_price_table()`. The value dossier
  could say "$0.0037 / commit" *only* because Chimera prices every call. **Fusion
  is a metering regression.** Tolerable for occasional ideation, not a hot path.
- **Safety:** panel-internal web-fetch = uncontrolled egress + injection surface
  Chimera's own tools gate. Fine for PLAN, not near ENFORCE.

## 6. Verdict (→ ADR 0164)

Model it as an **optional, default-OFF PLAN-phase `deliberate()` capability** that
augments the Creativity pillar with web-grounded panel breadth — **explicitly
walled off from the critic gate, alignment ceremony, and submit_pr validation.**

The honest one-liner: **Fusion trades Chimera's two crown jewels — fail-closed
adjudication and measured per-call cost — for not having to write an
`asyncio.gather`. So it belongs only where neither jewel matters: open-ended PLAN
ideation.** The durable artifact here is the *recorded boundary*, not an
integration; the boundary is what stops a future change from quietly routing
enforcement through an opaque server tool.

## 7. Falsification notes

- I verified the request passthrough and the response-extraction asymmetry against
  the actual `openrouter.py` source rather than assuming symmetry — the silent-drop
  failure mode is real, not hypothetical.
- The "Chimera already does this" claim is grounded in three concrete symbols
  (`cross_critique`, `AlignmentCeremony`, `critic_gate`), not a vibe.
- Open question left unresolved (honestly): whether Fusion's web-grounded panel
  *actually* produces better PLAN proposals than Chimera's local Opus-PLAN +
  dedup + critic. That is an empirical A/B, deferred — this note asserts only the
  *boundary*, not a quality win.
