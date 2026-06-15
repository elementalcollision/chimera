#!/usr/bin/env bash
# scripts/ab_battery.sh — run the GRADED code-model A/B across a battery of
# probes and aggregate into one decision-grade scorecard (ADR 0183 A.1).
#
# Each probe is run through scripts/ab_soak.sh (both model arms, each graded
# against the probe's canonical <spec>.accept.py). This driver collects every
# probe's per-arm spec-pass + cost and rolls them up: per-model totals, per-probe
# winners, and an overall recommendation. A single task can mislead (see the
# 2026-06-15 first run); a varied battery is the evidence the code-tier
# default-routing flip is gated on.
#
# Usage:
#   bash scripts/ab_battery.sh                       # all mind/ab/*-probe.md w/ accept
#   bash scripts/ab_battery.sh mind/ab/a.md mind/ab/b.md   # explicit, ordered
#   TASK_DRYRUN=1 bash scripts/ab_battery.sh         # validate each probe, no spend
# Any ab_soak.sh / real_task_soak.sh knob (caps, walls, AB_ARM_*_MODEL,
# CHIMERA_ACT_MAX_TOKENS) passes through to every probe unchanged.
#
# Manual-handoff: nothing merges. Worktrees are left for review; `git worktree
# prune` after.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
REPO_ROOT="$(pwd)"
if [ -f .env ]; then set -a; . ./.env; set +a; fi

PROBES=("$@")
if [ "${#PROBES[@]}" -eq 0 ]; then
    for f in "$REPO_ROOT"/mind/ab/*-probe.md; do
        [ -f "${f%.md}.accept.py" ] && PROBES+=("$f")
    done
fi
[ "${#PROBES[@]}" -gt 0 ] || { echo "ab_battery: no probes (need mind/ab/*-probe.md with a sibling .accept.py)"; exit 2; }

STATE_DIR="${CHIMERA_STATE_DIR:-$REPO_ROOT/state}"
STAMP="$(date -u +%Y-%m-%d-%H%M%S)"
SUMMARY="$STATE_DIR/ab_battery_${STAMP}.txt"
ROWS="$(mktemp -t ab-battery-rows.XXXXXX)"
mkdir -p "$STATE_DIR"

# Pin the base ref to a SHA ONCE, up front, and pass it to every probe as
# TASK_BASE. A battery runs for hours; if it tracked the moving "main" ref and
# someone merged mid-run, in-flight worktrees (branched from the old tip) would
# see the new commits as a phantom diff and the phase-2 deliverable sentinel
# would never fire — spinning each affected arm to its wall ceiling (observed
# 2026-06-15). A fixed SHA immunises the whole battery from concurrent merges.
AB_BASE="${AB_BASE:-${TASK_BASE:-main}}"
BASE_SHA="$(git -C "$REPO_ROOT" rev-parse --verify "$AB_BASE" 2>/dev/null || echo "$AB_BASE")"
# ab_soak resolves TASK_BASE from each spec's frontmatter; this override wins,
# so every probe shares the one pinned SHA.
export TASK_BASE_OVERRIDE="$BASE_SHA"

# AB_TRIALS: run each (probe, arm) cell this many times. >1 turns the battery's
# single-sample verdict into a DISTRIBUTION — the fix for the large run-to-run
# variance the first battery exposed (2026-06-15): one trial per cell can flip
# a winner. Wall + spend scale linearly: ~15–20 min/arm × 2 arms × TRIALS × probes.
TRIALS="${AB_TRIALS:-1}"
[ "$TRIALS" -ge 1 ] 2>/dev/null || TRIALS=1

echo "=== ab_battery: ${#PROBES[@]} probe(s) × ${TRIALS} trial(s) → graded A/B each ==="
for p in "${PROBES[@]}"; do echo "  - $(basename "$p")"; done
echo "  base    → ${AB_BASE} @ ${BASE_SHA} (pinned; immune to concurrent merges)"
echo "  trials  → ${TRIALS} per cell ($(( ${#PROBES[@]} * TRIALS * 2 )) soaks total)"
echo "  summary → $SUMMARY"
echo

if [ "${TASK_DRYRUN:-0}" = "1" ]; then
    for spec in "${PROBES[@]}"; do
        echo "──────── (dryrun) $(basename "$spec") ────────"
        AB_SPEC="$spec" TASK_DRYRUN=1 bash "$REPO_ROOT/scripts/ab_soak.sh" 2>&1 | grep -E "accept:|arm [AB]|invalid|not found" || true
    done
    echo "(dryrun) no soak launched, no spend."
    rm -f "$ROWS"; exit 0
fi

for spec in "${PROBES[@]}"; do
    slug="$(basename "${spec%.md}")"
    echo "════════ probe: $slug (${TRIALS} trial(s)) ════════"
    for trial in $(seq 1 "$TRIALS"); do
        # Only tag worktrees/branches/ledger with a trial id when there's >1
        # trial, so single-shot behaviour (and ledger slugs) stay unchanged.
        tag_env=""; [ "$TRIALS" -gt 1 ] && { tag_env="t${trial}"; echo "──── $slug trial ${trial}/${TRIALS} ────"; }
        out="$(AB_RUN_TAG="$tag_env" AB_SPEC="$spec" bash "$REPO_ROOT/scripts/ab_soak.sh")" || true
        printf '%s\n' "$out"
        report="$(printf '%s\n' "$out" | sed -nE 's/.*report written: (.*)$/\1/p' | tail -1)"
        if [ -z "$report" ] || [ ! -f "$report" ]; then
            echo "ab_battery: WARN no report for $slug trial $trial"; continue
        fi
        # Arm rows are those whose spec_pass column ($6) matches N/M. Emit:
        #   "<probe> <trial> <model> <passed> <total> <cost>"
        awk -v probe="$slug" -v trial="$trial" \
            '$6 ~ /^[0-9]+\/[0-9]+$/ { split($6,a,"/"); print probe, trial, $2, a[1], a[2], $5 }' \
            "$report" >> "$ROWS"
        echo
    done
done

# ── scorecard (python aggregation) ─────────────────────────────
uv run python - "$ROWS" "$STAMP" <<'PY' | tee "$SUMMARY"
import sys
from collections import defaultdict

rows = []
with open(sys.argv[1]) as fh:
    for line in fh:
        parts = line.split()
        if len(parts) != 6:
            continue
        probe, trial, model, p, t, c = parts
        rows.append((probe, int(trial), model, int(p), int(t), float(c)))
stamp = sys.argv[2]

print(f"=== BATTERY SCORECARD ({stamp}) ===\n")
if not rows:
    print("No graded arm rows collected — were the probes accept-graded? "
          "(each needs a sibling <spec>.accept.py)")
    raise SystemExit(0)


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


probes, models = [], []
for r in rows:
    if r[0] not in probes:
        probes.append(r[0])
    if r[2] not in models:
        models.append(r[2])

# cell[(probe, model)] = list of (passed, total, cost) across trials
cell = defaultdict(list)
for probe, _trial, model, p, t, c in rows:
    cell[(probe, model)].append((p, t, c))
ntrials = max(len(v) for v in cell.values())
print(f"Trials per cell: up to {ntrials}\n")

# per-probe table: mean spec-pass over trials [min–max], mean $ — winner by
# mean pass, ties broken by cheaper mean cost.
print("Per-probe spec-pass — mean/total [min–max], mean$ (winner: higher mean pass; tie→cheaper):")
print(f"  {'probe':<20}" + "".join(f"{m.split('/')[-1]:<28}" for m in models) + "winner")
wins = defaultdict(int)
for probe in probes:
    cells, best_m, best_key = [], None, None
    for m in models:
        v = cell.get((probe, m))
        if not v:
            cells.append("—"); continue
        ps = [x[0] for x in v]; tot = v[0][1]; mc = mean([x[2] for x in v])
        rng = f"[{min(ps)}-{max(ps)}]" if len(ps) > 1 else ""
        cells.append(f"{mean(ps):.1f}/{tot}{rng} ${mc:.3f}")
        key = (mean(ps), -mc)  # higher mean pass, then cheaper
        if best_key is None or key > best_key:
            best_m, best_key = m, key
    if best_m:
        wins[best_m] += 1
    winner = best_m.split("/")[-1] if best_m else "—"
    print(f"  {probe:<20}" + "".join(f"{c:<28}" for c in cells) + winner)

# per-model pooled across every trial × probe
print("\nPer-model pooled (all trials × probes):")
print(f"  {'model':<28}{'runs':<6}{'spec_pass':<16}{'mean$/run':<11}{'probe_wins':<10}")
pool_p, pool_t, pool_c = {}, {}, {}
for m in models:
    mr = [r for r in rows if r[2] == m]
    pool_p[m] = sum(r[3] for r in mr); pool_t[m] = sum(r[4] for r in mr)
    pool_c[m] = sum(r[5] for r in mr)
    rate = f"{pool_p[m]}/{pool_t[m]} ({100*pool_p[m]/pool_t[m]:.0f}%)" if pool_t[m] else "0/0"
    mc = pool_c[m] / len(mr) if mr else 0.0
    print(f"  {m:<28}{len(mr):<6}{rate:<16}{mc:<11.4f}{wins[m]:<10}")

# within-cell variance — the headline the multi-trial mode exists to surface
spreads = [max(x[0] for x in v) - min(x[0] for x in v) for v in cell.values() if len(v) > 1]
if spreads:
    print(f"\n  Within-cell variance: mean spread {mean(spreads):.1f} cases "
          f"(max {max(spreads)}) across {len(spreads)} repeated cells.")

# overall verdict — quality (pooled %) first, then cost; flag if quality is
# within noise so the call is made on the robust signal (cost).
print("\nOVERALL:")
def rate(m):
    return pool_p[m] / pool_t[m] if pool_t[m] else 0.0
best = max(models, key=lambda m: (rate(m), -pool_c[m]))
if len(models) == 2:
    o = next(m for m in models if m != best)
    cheaper = min(models, key=lambda m: pool_c[m])
    print(f"  {best.split('/')[-1]}: {100*rate(best):.0f}% vs "
          f"{o.split('/')[-1]}: {100*rate(o):.0f}%  |  "
          f"mean$/run {pool_c[best]/max(1,len([r for r in rows if r[2]==best])):.4f} vs "
          f"{pool_c[o]/max(1,len([r for r in rows if r[2]==o])):.4f}")
    if abs(rate(best) - rate(o)) < 0.05:
        print("  Quality within ~5pp → treat as a TIE; decide on cost.")
        print(f"  → Cheaper (robust signal): {cheaper.split('/')[-1]}.")
    else:
        print(f"  → {best.split('/')[-1]} leads on quality beyond noise"
              + ("" if best == cheaper else f"; {cheaper.split('/')[-1]} is cheaper") + ".")
    print("  Decision stays operator-gated.")
else:
    print(f"  Leader: {best} ({100*rate(best):.0f}%).")
PY

echo
echo "[ab_battery] summary written: $SUMMARY"
rm -f "$ROWS"
echo "[ab_battery] worktrees left for review; discard with: git worktree prune"
exit 0
