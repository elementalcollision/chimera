# Release prep — LongMemEval Tier-1 close-out (2026-05-25)

**Purpose**: Prepare a release that locks in the durable 90.80% LongMemEval
corpus baseline (PR #70) as a citable project capability, and closes out the
Tier-2B implicit-preference-inference investigation cleanly with Option C as
the recommended forward path.

**Companion to**:
- [`longmemeval-baseline-post-t1.5-2026-05-25.md`](./longmemeval-baseline-post-t1.5-2026-05-25.md) — PR #70's load-bearing 90.80% baseline.
- [`longmemeval-baseline-post-pr75-2026-05-25.md`](./longmemeval-baseline-post-pr75-2026-05-25.md) — PR #77's FAIL verdict closing Option B at the adapter+prompt layer.
- [`post-baseline-development-priorities-2026-05-24.md`](./post-baseline-development-priorities-2026-05-24.md) — PR #57's Tier-1 chip queue this release closes.

This chip ships no code, no tests, no new ADRs, no version-manifest changes.
Operator gates the merge and the tag push.

---

## Version recommendation

**Recommend: `v4.114.0`** (next sub-version in the v4.x train).

Latest tag: `v4.113.0` (per `git tag --list 'v*' | sort -V | tail -1`). The
v4.x line is the active release train; v4.0 (ADR 0025) established the
stability contract for SQLite schema, graph store, mind layout, env vars,
HTTP endpoints, and CLI verbs. **None of those surfaces changed** across
T1.1–T1.5 or the Tier-2B investigation:

- T1.1 (token budget) — added one `--answer-max-tokens` default; no new env
  var or schema change.
- T1.2 / T1.5 (temporal-aware dialectic, ADR 0136) — added content to the
  dialectic prompt and the LongMemEval adapter's synthetic peer-card; no
  promised-surface change.
- T1.3 (preference-aware dialectic, ADR 0137) — single sentence appended to
  the dialectic prompt.
- T1.4 (post-T1 baseline) — measurement chip.
- Tier-2B (PRs #71–#77) — investigation closed without persistent code
  surface change (PR #75 reverted by PR #77).

Per the **default-to-conservative** rule from the chip charter, **v5.0 is
not justified**. v5.0 would require either (a) a breaking change to a
surface ADR 0025 promises stable, or (b) a comparably large architectural
flag-day. Neither obtains. The LongMemEval integration (ADR 0135) is a new
internal eval surface, not a backward-incompatible change to a promised
contract.

Operator may override to a different version (e.g. `v4.114.0` could be
called `v4.200.0` if the operator prefers a "feature-train marker"
convention). The chip writes the changelog entry with the version it
recommends; operator can rename in the tag step.

---

## What this release locks in

### Tier-1 wins (T1.1 → T1.5) — landed pre-release

| Chip | PR | What landed | Corpus impact |
|---|---|---|---:|
| T1.1 — token budget | #61 | `--answer-max-tokens=2048` default in adapter | empty-hypothesis rate ~0.4–0.8% (was higher) |
| T1.2 — temporal-aware dialectic | #62, ADR 0136 | One sentence on cross-session temporal integration in `_DIALECTIC_PROMPT` | +70.98pp on temporal subset (smoke) |
| T1.3 — preference-aware dialectic | #65, ADR 0137 | One sentence on honoring stated preferences | +categorical lift; no corpus regression |
| T1.4 — post-Tier-1 baseline | #67 | 500-item sweep, measurement chip | **80.60% overall** at `7e379ae` |
| T1.5 — timestamp grounding | #69, ADR 0136 amend | `**Today's date:**` + `**Session date:**` headers in adapter peer-card | **+36.85pp temporal, +10.20pp overall → 90.80%** at `14192658` |

PR #70 published 90.80% / `14192658` as the regression floor. This release
ships against that floor.

### Methodology wins — durable infrastructure

- **PR #68 grounding-vs-wording template** — diagnose the failure-mode
  taxonomy *before* shipping a prompt or grounding change. Replayed by
  PR #71's Tier-2B diagnostic note.
- **PR #76 pre-registered Gate A / Gate B / regression-check framework** —
  paired-item gates beat aggregate-percentage gates at n=30.
- **PR #77 corpus-pre-promotion finding** — n=30 single-category spikes
  *cannot* see collateral damage in the other five categories. Promotion
  requires a corpus sweep, full stop. Future spike charters must either
  measure beyond the target category or mandate corpus measurement before
  status flip.

### Tier-2B — investigation closed with Option C

ADR 0138 (Proposed, 2026-05-25) was the Tier-2B diagnostic chip targeting
single-session-preference (the only category not clearing 75% at the
post-T1.5 baseline; 46.67%, 14/30). The investigation went:

| PR | Chip | Result |
|---|---|---|
| #71 | Diagnostic note + ADR 0138 Proposed | Behavior-consistency cliff identified; Option A (prompt extension) falsified by Test 2 of the companion note |
| #72 | Option B v1 spike (`## User context` regex) | Gate B fail; reverted by #74 |
| #73 | Spike result note | Documented Gate B failure |
| #74 | Revert of #72 | Returned `main` to PR #70 baseline |
| #75 | Option B v2 spike (redesigned heuristic) | Landed on `main` after spike showed Gate A pass / Gate B borderline |
| #76 | Respike result + Path-3 charter | Pre-registered the corpus sweep as the falsifying experiment |
| #77 | Path-3 corpus sweep | **90.00% overall (−0.80pp), SPP +6.67pp** — FAIL on overall gate; PR #75 reverted |

**Structural finding (PR #77 §"Why Option B is now closed at this layer")**:

> The adapter cannot promote implicit-preference signal without changing
> prominence-for-other-categories in ways the model isn't robust to. This is
> a layering problem (one global peer-card serving all six task shapes),
> not a heuristic-quality problem.

Two independent designs in the same content-shape family
(PR #72 noisy regex; PR #75 tightened conditioning) produced net-negative
overall accuracy. The forward path is **not** "v3 of the heuristic" — it is
either Option C-i (hybrid retrieval at the dialectic boundary, ADR 0134's
deferred vector path) or Option C-ii (ingestion-time category-aware peer-card
composition), both net-new design work tracked as future chips.

This release **accepts 46.67% as the architectural floor for
single-session-preference at the adapter+prompt layer** and treats the
peer-card layering finding as a load-bearing constraint for any future
design in this space.

---

## Known limitations called out by the release

1. **Single-session-preference plateaus at 46.67%** (14/30) on
   `longmemeval_oracle`. Not a defect — a layering ceiling. Future work
   tracked as a separate chip; see ADR 0138 Option C subsection (to be added
   by this PR).
2. **T2.1 hybrid retrieval (ADR 0134's vector path)** — Deferred per PR #69,
   not because the design is wrong but because PR #69 falsified its premise
   (the temporal regression was content-shape, not retrieval-mechanism). The
   case for revisiting it is now stronger given Option C-i is the recommended
   forward path for single-session-preference.
3. **T2.2 long-horizon `_s` corpus sweep** — Not run. The 90.80% baseline is
   `longmemeval_oracle.json` only. `_s` (long-horizon) is a separate
   measurement and may surface different failure modes. Future chip.
4. **Two likely judge false-negatives** (per PR #70 §"Cross-category"):
   gpt-4o-mini's strict literal matching marked
   `08f4fc43` ("Thirty days elapsed") and `gpt4_e072b769` ("just under three
   weeks") wrong despite functionally correct answers. Treating these as
   ground-truth errors would put the headline at 91.20% / temporal at
   91.73%. The headline reported is the strict-judge number.
5. **Spike-vs-corpus per-item disagreement** (PR #77 §"n=30 spike vs n=500
   corpus alignment") — only 1 of 30 single-session-preference items
   (`d24813b1`) flipped reliably across spike and corpus runs. The o4-mini
   answer-side has run-to-run stochasticity that single-item gate framings
   under-account for. Spike protocol refinement (e.g. multi-seed averaging
   or stratified sampling beyond target category) is a future chip flagged
   but not in scope here.

---

## Release artifacts (Phase 2 — what this chip writes)

1. **`CHANGELOG.md`** — new file at repo root (none exists today; per chip
   discipline this is the right moment to create one). Entry under
   `v4.114.0` (2026-05-25) covering Tier-1 wins, Tier-2B closure,
   methodology wins, known limitations. Cross-links to ADRs 0135–0138 and
   PRs #61–#77.
2. **`docs/adr/0138-implicit-preference-inference.md`** — amend with an
   **`## Option C — adopted 2026-05-25`** subsection. Status stays
   **Proposed** (the diagnostic ADR remains a diagnostic; the spike result
   notes carry the load-bearing evidence; Option C is the recommended
   forward path for future design work, not a shipped intervention).
3. **`docs/adr/README.md`** — header count drift fix only. Current header
   reads "135 architecture decision records"; the table has 137 entries.
   Update to 137. No status changes needed (0135–0137 are already Accepted;
   0138 stays Proposed; 0134 stays Proposed — Path 3 corpus FAIL doesn't
   flip its status either).
4. **`mind/research/release-prep-2026-05-25.md`** — this design note.

**File count: 4**, within the chip's 3–5 file scope.

**Not in this chip** (per Phase 3 of the charter):
- No `pyproject.toml` version bump (operator decides if/when)
- No tag push (operator's final action after merge)
- No new ADR (release closes work; doesn't open design space)
- No top-level README capability claim (optional in charter; declined here
  to keep file count tight — the CHANGELOG.md entry plus the linked ADRs
  carry the public claim adequately)
- No T2.1 hybrid retrieval / T2.2 `_s` corpus work
- No spike-protocol refinement chip
- No knowledge-update layering diagnostic (PR #77's surfaced concern; future
  chip)

---

## Why this release shape

Three pieces of evidence drove the close-out shape:

- **Dollar-curve plateau on the Tier-1 chain.** T1.1–T1.5 lifted the corpus
  from 60% smoke baseline → 90.80% with roughly $10 of inference spend and
  four prompt/adapter chips. Two consecutive Tier-2B chips at ~$2 each
  delivered net-negative results (PR #72 reverted before corpus; PR #75
  reverted by PR #77). Marginal cost of further oracle-set work is
  high — the natural next experiment is shape-change (T2.1 retrieval) or
  corpus-change (T2.2 long-horizon), not iteration on the heuristic.
- **The peer-card layering finding is durable.** PR #77's structural
  conclusion — *one global peer-card cannot serve six task shapes without
  category-prominence collisions* — is a load-bearing input to any future
  per-category intervention, including T2.1 hybrid retrieval's surface design.
  Captured in ADR 0138's Option C amendment so it doesn't drift out of the
  decision record.
- **Shipping locks in the methodology.** The diagnose-before-shipping (PR #68),
  paired-item-gate (PR #76), and corpus-pre-promotion (PR #77) patterns
  proved themselves across this chain. A release tag makes the chain
  citable for future LongMemEval work — and for any future evals integration
  that hits the same "n=30 single-category spike doesn't see collateral
  damage" pattern.

---

## READY-FOR-RELEASE

| Artifact | Path | Action |
|---|---|---|
| Changelog entry | `CHANGELOG.md` | Create file, add `v4.114.0` entry |
| ADR 0138 amendment | `docs/adr/0138-implicit-preference-inference.md` | Append Option C subsection; status stays Proposed |
| ADR README header | `docs/adr/README.md` | Update "135 architecture decision records" → "137" |
| Design note | `mind/research/release-prep-2026-05-25.md` | This file (committed alongside the rest) |

**Recommended git tag**: `v4.114.0` at the squash-merge HEAD of the
release PR. **Operator action**; chip does not push the tag.

**Optional follow-up** (not in this chip): if operator chooses to bump
`pyproject.toml` to match the release tag, that's a one-line edit they can
do alongside the tag push.
