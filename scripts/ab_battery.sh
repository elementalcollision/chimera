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

echo "=== ab_battery: ${#PROBES[@]} probe(s) → graded A/B each ==="
for p in "${PROBES[@]}"; do echo "  - $(basename "$p")"; done
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
    echo "════════ probe: $slug ════════"
    out="$(AB_SPEC="$spec" bash "$REPO_ROOT/scripts/ab_soak.sh")" || true
    printf '%s\n' "$out"
    report="$(printf '%s\n' "$out" | sed -nE 's/.*report written: (.*)$/\1/p' | tail -1)"
    if [ -z "$report" ] || [ ! -f "$report" ]; then
        echo "ab_battery: WARN no report for $slug"; continue
    fi
    # Arm rows are those whose spec_pass column ($6) matches N/M. Emit:
    #   "<probe> <model> <passed> <total> <cost>"
    awk -v probe="$slug" '$6 ~ /^[0-9]+\/[0-9]+$/ { split($6,a,"/"); print probe, $2, a[1], a[2], $5 }' "$report" >> "$ROWS"
    echo
done

# ── scorecard (python aggregation) ─────────────────────────────
uv run python - "$ROWS" "$STAMP" <<'PY' | tee "$SUMMARY"
import sys
from collections import defaultdict

rows = []
with open(sys.argv[1]) as fh:
    for line in fh:
        parts = line.split()
        if len(parts) != 5:
            continue
        probe, model, p, t, c = parts
        rows.append((probe, model, int(p), int(t), float(c)))
stamp = sys.argv[2]

print(f"=== BATTERY SCORECARD ({stamp}) ===\n")
if not rows:
    print("No graded arm rows collected — were the probes accept-graded? "
          "(each needs a sibling <spec>.accept.py)")
    raise SystemExit(0)

probes = []
for r in rows:
    if r[0] not in probes:
        probes.append(r[0])
models = []
for r in rows:
    if r[1] not in models:
        models.append(r[1])

# per-probe table + winners
pp = {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}
wins = defaultdict(int)
print("Per-probe spec-pass (winner = higher pass; tie → cheaper):")
hdr = f"  {'probe':<22}" + "".join(f"{m.split('/')[-1]:<22}" for m in models) + "winner"
print(hdr)
for probe in probes:
    cells = []
    best_model, best_pass, best_cost = None, -1, None
    tie = False
    for m in models:
        if (probe, m) in pp:
            p, t, c = pp[(probe, m)]
            cells.append(f"{p}/{t} (${c:.4f})")
            if p > best_pass:
                best_model, best_pass, best_cost, tie = m, p, c, False
            elif p == best_pass:
                if best_cost is None or c < best_cost:
                    best_model, best_cost = m, c
                tie = True
        else:
            cells.append("—")
    winner = best_model.split("/")[-1] if best_model else "—"
    if tie:
        winner += " (tie→cost)"
    wins[best_model] += 1
    row = f"  {probe:<22}" + "".join(f"{c:<22}" for c in cells) + winner
    print(row)

# per-model totals
print("\nPer-model totals:")
print(f"  {'model':<30}{'probes':<8}{'spec_pass':<14}{'cost_usd':<12}{'probe_wins':<10}")
tot_pass = {}
tot_all = {}
tot_cost = {}
for m in models:
    mp = [r for r in rows if r[1] == m]
    tp = sum(r[2] for r in mp); ta = sum(r[3] for r in mp); tc = sum(r[4] for r in mp)
    tot_pass[m], tot_all[m], tot_cost[m] = tp, ta, tc
    rate = f"{tp}/{ta} ({100*tp/ta:.0f}%)" if ta else "0/0"
    print(f"  {m:<30}{len(mp):<8}{rate:<14}{tc:<12.4f}{wins[m]:<10}")

# overall verdict
print("\nOVERALL:")
best = max(models, key=lambda m: (tot_pass[m], -tot_cost[m]))
others = [m for m in models if m != best]
if len(models) == 2 and others:
    o = others[0]
    dp = tot_pass[best] - tot_pass[o]
    dc = tot_cost[best] - tot_cost[o]
    if tot_pass[best] == tot_pass[o]:
        cheaper = min(models, key=lambda m: tot_cost[m])
        print(f"  TIE on quality ({tot_pass[best]}/{tot_all[best]}). Cheaper: "
              f"{cheaper} (${tot_cost[cheaper]:.4f}).")
    else:
        sign = "more" if dc > 0 else "less"
        print(f"  {best} leads on quality: "
              f"{tot_pass[best]}/{tot_all[best]} vs {tot_pass[o]}/{tot_all[o]} "
              f"(+{dp} cases), at ${abs(dc):.4f} {sign} total cost.")
        print(f"  → Routing implication: {'favours promoting' if best.startswith('moonshotai') else 'does NOT favour'} "
              f"the code tier's kimi lead. Decision stays operator-gated.")
else:
    print(f"  Leader: {best} ({tot_pass[best]}/{tot_all[best]}).")
PY

echo
echo "[ab_battery] summary written: $SUMMARY"
rm -f "$ROWS"
echo "[ab_battery] worktrees left for review; discard with: git worktree prune"
exit 0
