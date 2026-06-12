# Post-merge validation handoff — 2026-06-12

**Purpose.** Hand off from the cloud session (no API keys, loopback-only) to a
**local keyed environment** to finish validating the entropy/graph + federation
work. Everything below was either completed in the cloud session or is blocked
on something only a local/keyed run can provide (provider API keys, real TLS
certs, longer wall-clock soaks).

> Workflow note: this doc was created **locally** in the working tree. Sync
> local ↔ repository (`git pull`, then commit/push this file on a branch) before
> acting on it, so the handoff travels with the code it describes.

---

## 1. What is already merged & certified (no action needed)

| Area | PRs | Status |
|---|---|---|
| Six insertions (ADR 0167–0172) | #275/#276 + certification #282–#289 | **Accepted**, live-fire certified (journal rounds 0–4) |
| Model-backed peers (ADR 0174) | #286, promoted #290 | **Accepted** (live-fire harness; 21 unit tests) |
| Remote-federation drill (0167/0168 over real HTTP) | #290 | **Merged** — `remote_federation_drill` |
| First default-ON flag + registry-default reads (ADR 0179) | #291 | **Merged on green** (CHIMERA_FEDERATION_METRICS default-ON) |
| Security/validation/TLS substrate (ADR 0175–0178) | #287/#288 | Accepted |

All **behavioural** flags remain **default-OFF**: `CHIMERA_PEER_SELECTION`,
`CHIMERA_FANOUT_BUDGET`, `CHIMERA_ANNEAL_REHEAT`, `CHIMERA_COMPLEXITY_ROUTING`,
`CHIMERA_TOOL_PREFILTER`, `CHIMERA_BOLTZMANN_ALLOC`, `CHIMERA_MODEL_PEERS`. Only
the zero-hot-path observability flag `CHIMERA_FEDERATION_METRICS` is default-ON.

---

## 2. What the cloud session could NOT validate (the actual handoff)

### 2a. Behavioural-flag soaks in a keyed environment (HIGHEST PRIORITY)

The cloud container has **no `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY`**, so no
flag that changes ACT/loop behaviour could be exercised against real provider
calls. Before graduating **any** behavioural flag to default-ON, run the
all-flags envelope soak (the harness that caught the ADR 0169 NameError) with
current `main`:

```bash
# keyed env, repo root
export ANTHROPIC_API_KEY=... OPENROUTER_API_KEY=...
# all behavioural flags ON together — the interaction surface
export CHIMERA_PEER_SELECTION=1 CHIMERA_FANOUT_BUDGET=1 CHIMERA_FANOUT_MAX_WIDTH=2 \
       CHIMERA_ANNEAL_REHEAT=1 CHIMERA_COMPLEXITY_ROUTING=1 CHIMERA_TOOL_PREFILTER=1 \
       CHIMERA_BOLTZMANN_ALLOC=1 CHIMERA_MODEL_PEERS=1
uv run chimera run --cycles 5      # or the project's soak entrypoint
```

Expected: ACT makes LLM calls, converges, gate PASS — i.e. NOT the "0 LLM calls"
failure that the routing-soak campaign (mind/research/routing-soak-campaign-2026-06-08.md)
found and that ADR 0169's amendment fixed. Compare against the flags-OFF run as
an A/B (that campaign's method).

Per-flag value soaks (which to graduate next, ranked by the certification
evidence):
- **CHIMERA_ENTROPY_SIGNALS** — observability, loop-wired; lowest-risk
  *behavioural-adjacent* graduation after federation metrics. Validate the
  per-cycle emission adds no meaningful latency/log-noise, then it's a candidate
  for the next default-ON (its own ADR, à la 0179).
- **CHIMERA_COMPLEXITY_ROUTING / CHIMERA_TOOL_PREFILTER** — token/cost wins;
  measure cost delta over a soak before graduating.
- **CHIMERA_PEER_SELECTION / CHIMERA_MODEL_PEERS / CHIMERA_FANOUT_BUDGET** —
  only meaningful in a multi-model/peer deployment; graduate when that's the
  default topology.

### 2b. TLS federation drill (ADR 0178) — the one open transport item

`remote_federation_drill` runs over **loopback cleartext** today. Close the TLS
caveat by running it (or the `federation_http_drill`) with real certs:

```bash
# generate a self-signed cert/key, then:
export CHIMERA_TLS_CERT=/path/cert.pem CHIMERA_TLS_KEY=/path/key.pem
# point the MCP http client at https and a CA bundle / verify setting
uv run chimera scenario remote_federation_drill
```

Note: the MCP `streamablehttp_client` may need an SSL-context/verify hook to
trust a self-signed cert; if it doesn't expose one, that's a small follow-up
(thread a `verify`/CA option through `MCPServerConfig`). TLS *serving*
(`serve_http` + `_tls_config`) is already unit-covered; what's unvalidated is a
full **dispatch over TLS**.

### 2c. Re-run the drill locally (smoke — works without keys)

These pass in the cloud container and should pass anywhere with `uv`:

```bash
uv run chimera scenario remote_federation_drill   # ADR 0167+0168 over real HTTP
uv run chimera scenario federation_http_drill      # single-peer HTTP transport
uv run pytest tests/test_remote_federation_drill.py -q   # slow; spawns 3 servers
```

---

## 3. Default-ON graduation ladder (the policy ADR 0179 starts)

ADR 0179 established the mechanism (`flag_enabled` honours the registry
`default`) and graduated the one zero-risk flag. The ladder from here, each
gated by §2a soak evidence and its own short ADR:

1. ✅ `CHIMERA_FEDERATION_METRICS` (done — pure observability)
2. `CHIMERA_ENTROPY_SIGNALS` (observability, loop-wired) — next, on latency/noise check
3. `CHIMERA_COMPLEXITY_ROUTING`, `CHIMERA_TOOL_PREFILTER` — on cost-delta evidence
4. `CHIMERA_FANOUT_BUDGET`, `CHIMERA_ANNEAL_REHEAT`, `CHIMERA_BOLTZMANN_ALLOC` — on behavioural soak
5. `CHIMERA_PEER_SELECTION`, `CHIMERA_MODEL_PEERS` — when multi-peer is the default topology

To graduate a flag: flip its `REGISTRY` default `None → "1"` in
`chimera/config.py`, update its `tests/test_*` default-assertion + add an
explicit-disable test, write the ADR, confirm `tests/test_flag_matrix.py` /
`tests/test_flag_registry.py` stay green.

---

## 4. Local ↔ repository sync (do this first)

```bash
git checkout main && git pull origin main          # get #290 + #291
# create a working branch for validation artifacts
git checkout -b claude/post-merge-validation
git add mind/handoff/post-merge-validation-2026-06-12.md
git commit -m "docs: post-merge validation handoff"
git push -u origin claude/post-merge-validation
```

Then run §2a/§2b in the keyed env and record results back into
`mind/research/` (a `routing-soak-campaign-2026-06-12.md` follow-up) before
graduating the next flag.

---

## 5. Quick reference — verified-green test slices (cloud session)

- `tests/test_remote_federation_drill.py` (real 3-server spawn) — 1 passed
- `tests/test_federation_metrics.py` (incl. default-on + explicit-disable) — green
- `tests/test_flag_registry.py` + `tests/test_flag_matrix.py` — 71 passed
- `tests/test_model_peers.py` — 21 passed
- federation + entropy-family slice — 133–150 passed
- `ruff check chimera tests` — clean
- control-plane: `tsc --noEmit` clean + production `next build` green
