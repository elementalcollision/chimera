#!/usr/bin/env bash
# scripts/ab_arena.sh — N-way head-to-head of code models across graded probes
# (ADR 0183 A.1). Generalises the 2-arm A/B (ab_soak.sh) to a LEADERBOARD: run
# every model in AB_MODELS on every probe, grade each against the probe's
# canonical <spec>.accept.py, and rank. Optional AB_TRIALS=N repeats each cell
# for a distribution (the variance fix from the first battery).
#
# Default field — the four operator-suggested open code-tier models (opus is the
# Anthropic safety-net, not a suggested code model; add it via AB_MODELS if wanted):
#   moonshotai/kimi-k2.7-code  deepseek/deepseek-v4-pro  z-ai/glm-5.1  qwen/qwen3.7-max
#
# Usage:
#   bash scripts/ab_arena.sh                          # all probes, default field
#   AB_TRIALS=2 bash scripts/ab_arena.sh mind/ab/roman-probe.md
#   AB_MODELS="moonshotai/kimi-k2.7-code z-ai/glm-5.1" bash scripts/ab_arena.sh
#   TASK_DRYRUN=1 bash scripts/ab_arena.sh            # validate, no spend
# Any real_task_soak.sh knob (caps, walls, CHIMERA_ACT_MAX_TOKENS) passes
# through to every cell unchanged.
#
# Manual-handoff: nothing merges; worktrees are left for review.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
REPO_ROOT="$(pwd)"
if [ -f .env ]; then set -a; . ./.env; set +a; fi

DEFAULT_MODELS="moonshotai/kimi-k2.7-code deepseek/deepseek-v4-pro z-ai/glm-5.1 qwen/qwen3.7-max"
read -r -a MODELS <<<"${AB_MODELS:-$DEFAULT_MODELS}"

PROBES=("$@")
if [ "${#PROBES[@]}" -eq 0 ]; then
    for f in "$REPO_ROOT"/mind/ab/*-probe.md; do
        [ -f "${f%.md}.accept.py" ] && PROBES+=("$f")
    done
fi
[ "${#PROBES[@]}" -gt 0 ] || { echo "ab_arena: no probes (need mind/ab/*-probe.md with a sibling .accept.py)"; exit 2; }

TRIALS="${AB_TRIALS:-1}"; [ "$TRIALS" -ge 1 ] 2>/dev/null || TRIALS=1

# Pin base to a SHA — immune to a concurrent merge moving the ref mid-run (same
# rationale + footgun as ab_battery.sh).
AB_BASE="${AB_BASE:-${TASK_BASE:-main}}"
BASE_SHA="$(git -C "$REPO_ROOT" rev-parse --verify "$AB_BASE" 2>/dev/null || echo "$AB_BASE")"

STATE_DIR="${CHIMERA_STATE_DIR:-$REPO_ROOT/state}"
STAMP="$(date -u +%Y-%m-%d-%H%M%S)"
SUMMARY="$STATE_DIR/ab_arena_${STAMP}.txt"
ROWS="$(mktemp -t ab-arena-rows.XXXXXX)"
mkdir -p "$STATE_DIR"

# model id → filesystem/run-id-safe short label (strip vendor prefix, sanitise)
label_for() { printf '%s' "$1" | sed 's#.*/##; s/[^A-Za-z0-9]/_/g'; }

echo "=== ab_arena: ${#MODELS[@]} models × ${#PROBES[@]} probe(s) × ${TRIALS} trial(s) ==="
for m in "${MODELS[@]}"; do echo "  model : $m"; done
for p in "${PROBES[@]}"; do echo "  probe : $(basename "$p")"; done
echo "  base  : ${AB_BASE} @ ${BASE_SHA} (pinned)"
echo "  soaks : $(( ${#MODELS[@]} * ${#PROBES[@]} * TRIALS )) total"
echo "  summary → $SUMMARY"
echo

# load_spec SPEC → sets SPEC_OK, SPEC_SLUG, TASK_*, ACCEPT_ABS (globals)
load_spec() {
    local spec="$1"
    eval "$(uv run python - "$spec" <<'PY'
import shlex, sys
from pathlib import Path
from chimera.core.backlog import parse_spec
s = parse_spec(Path(sys.argv[1]))
if not s.valid:
    print("SPEC_OK=0"); raise SystemExit(0)
print("SPEC_OK=1")
print(f"SPEC_SLUG={shlex.quote(s.slug)}")
for k, v in s.task_env().items():
    print(f"export {k}={shlex.quote(v)}")
PY
)"
    local acc="${spec%.md}.accept.py"
    ACCEPT_ABS=""
    [ -f "$acc" ] && ACCEPT_ABS="$(cd "$(dirname "$acc")" && pwd)/$(basename "$acc")"
}

# grade_accept WORKTREE → "passed total" of the accept oracle vs the produced module
grade_accept() {
    local wt="$1"
    [ -n "$ACCEPT_ABS" ] || { echo "- -"; return; }
    [ -d "$wt" ] || { echo "0 0"; return; }
    cp "$ACCEPT_ABS" "$wt/tests/_ab_accept.py" 2>/dev/null || { echo "0 0"; return; }
    local out; out="$(cd "$wt" && uv run pytest tests/_ab_accept.py -q --no-header -p no:cacheprovider 2>&1)"
    rm -f "$wt/tests/_ab_accept.py" 2>/dev/null || true
    local p f e
    p="$(printf '%s' "$out" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' | tail -1)"
    f="$(printf '%s' "$out" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' | tail -1)"
    e="$(printf '%s' "$out" | grep -oE '[0-9]+ error'  | grep -oE '[0-9]+' | tail -1)"
    echo "${p:-0} $(( ${p:-0} + ${f:-0} + ${e:-0} ))"
}

if [ "${TASK_DRYRUN:-0}" = "1" ]; then
    for spec in "${PROBES[@]}"; do
        load_spec "$spec"
        if [ "${SPEC_OK:-0}" != "1" ]; then echo "  INVALID spec: $spec"; continue; fi
        echo "  probe $SPEC_SLUG → accept=${ACCEPT_ABS:-<none>}  field=${MODELS[*]}"
    done
    echo "(dryrun) no soak launched, no spend."; rm -f "$ROWS"; exit 0
fi

for spec in "${PROBES[@]}"; do
    load_spec "$spec"
    if [ "${SPEC_OK:-0}" != "1" ]; then echo "ab_arena: WARN invalid spec $spec — skipping"; continue; fi
    if [ -z "$ACCEPT_ABS" ]; then echo "ab_arena: WARN $SPEC_SLUG has no accept oracle — skipping"; continue; fi
    echo "════════ probe: $SPEC_SLUG ════════"
    for model in "${MODELS[@]}"; do
        mlabel="$(label_for "$model")"
        for trial in $(seq 1 "$TRIALS"); do
            tag="$mlabel"; [ "$TRIALS" -gt 1 ] && tag="${mlabel}-t${trial}"
            wt="$REPO_ROOT/../chimera-soak-arena-${SPEC_SLUG}-${tag}-${STAMP}"
            echo "──── $SPEC_SLUG · $model · ${trial}/${TRIALS} ────"
            log="$(mktemp -t ab-arena-soak.XXXXXX)"
            CHIMERA_ACT_FORCE_MODEL="$model" \
            RUN_ID_SUFFIX="arena-${tag}" \
            WORKTREE="$wt" \
            TASK_BASE="$BASE_SHA" \
                bash "$REPO_ROOT/scripts/real_task_soak.sh" >"$log" 2>&1
            line="$(grep '\[soak-outcome\]' "$log" | tail -1 || true)"
            rm -f "$log"
            cost=0; rid="arena-${tag}"
            if [ -n "$line" ]; then
                eval "$(printf '%s\n' "$line" | sed -E 's/.*\[soak-outcome\] //; s/([a-z_]+)=([^ ]*)/O_\1="\2"/g')"
                # shellcheck disable=SC2154  # O_* set by the eval above
                cost="${O_cost_usd:-0}"; rid="${O_run_id:-$rid}"
                uv run chimera crawl record --run-id "$rid" --slug "${SPEC_SLUG}-${tag}" \
                    --gate "${O_gate:-fail}" --committed "${O_committed:-0}" \
                    --cost-usd "$cost" --branch "${O_branch:-}" --base "${O_base:-$BASE_SHA}" \
                    >/dev/null 2>&1 || true
            fi
            read -r passed total <<<"$(grade_accept "$wt")"
            echo "    → ${model}: spec_pass=${passed}/${total}  cost=\$${cost}"
            echo "$SPEC_SLUG $trial $model ${passed:-0} ${total:-0} ${cost:-0}" >> "$ROWS"
        done
    done
    echo
done

# ── leaderboard (python aggregation) ───────────────────────────
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

print(f"=== ARENA LEADERBOARD ({stamp}) ===\n")
if not rows:
    print("No graded rows collected — do the probes have <spec>.accept.py oracles?")
    raise SystemExit(0)


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


probes, models = [], []
for r in rows:
    if r[0] not in probes:
        probes.append(r[0])
    if r[2] not in models:
        models.append(r[2])

cell = defaultdict(list)  # (probe, model) -> [(passed, total, cost), ...]
for probe, _trial, model, p, t, c in rows:
    cell[(probe, model)].append((p, t, c))
ntrials = max(len(v) for v in cell.values())
print(f"Trials per cell: up to {ntrials}\n")

# per-probe table: mean spec-pass [min-max], mean$, with the probe winner starred
wins = defaultdict(int)
print("Per-probe spec-pass — mean/total [min-max] (mean$):")
print(f"  {'probe':<18}" + "".join(f"{m.split('/')[-1]:<26}" for m in models))
for probe in probes:
    best_m, best_key = None, None
    for m in models:
        v = cell.get((probe, m))
        if not v:
            continue
        key = (mean([x[0] for x in v]), -mean([x[2] for x in v]))
        if best_key is None or key > best_key:
            best_m, best_key = m, key
    if best_m:
        wins[best_m] += 1
    cells = []
    for m in models:
        v = cell.get((probe, m))
        if not v:
            cells.append("—"); continue
        ps = [x[0] for x in v]; tot = v[0][1]; mc = mean([x[2] for x in v])
        rng = f"[{min(ps)}-{max(ps)}]" if len(ps) > 1 else ""
        star = "*" if m == best_m else " "
        cells.append(f"{star}{mean(ps):.1f}/{tot}{rng} ${mc:.3f}")
    print(f"  {probe:<18}" + "".join(f"{c:<26}" for c in cells))

# leaderboard: pooled spec-pass %, mean $/run, probe wins — sorted best-first
print("\nLEADERBOARD (pooled over all probes × trials; * = probe wins):")
stat = {}
for m in models:
    mr = [r for r in rows if r[2] == m]
    tp = sum(r[3] for r in mr); ta = sum(r[4] for r in mr); tc = sum(r[5] for r in mr)
    stat[m] = (tp, ta, tc, len(mr))
ranked = sorted(models, key=lambda m: (stat[m][0] / stat[m][1] if stat[m][1] else 0, -stat[m][2]), reverse=True)
print(f"  {'#':<3}{'model':<28}{'spec_pass':<16}{'mean$/run':<11}{'probe_wins':<10}")
for i, m in enumerate(ranked, 1):
    tp, ta, tc, n = stat[m]
    rate = f"{tp}/{ta} ({100*tp/ta:.0f}%)" if ta else "0/0"
    mc = tc / n if n else 0.0
    print(f"  {i:<3}{m:<28}{rate:<16}{mc:<11.4f}{wins[m]:<10}")

spreads = [max(x[0] for x in v) - min(x[0] for x in v) for v in cell.values() if len(v) > 1]
if spreads:
    print(f"\n  Within-cell variance: mean spread {mean(spreads):.1f} cases "
          f"(max {max(spreads)}) across {len(spreads)} repeated cells.")

# verdict — quality leader, with cost framing and a noise caveat
print("\nVERDICT:")
top = ranked[0]
tr = stat[top][0] / stat[top][1] if stat[top][1] else 0
cheapest = min(models, key=lambda m: stat[m][2] / max(1, stat[m][3]))
near = [m for m in models if m != top
        and stat[m][1] and abs(stat[m][0]/stat[m][1] - tr) < 0.05]
print(f"  Quality leader: {top.split('/')[-1]} ({100*tr:.0f}%).")
if near:
    names = ", ".join(n.split('/')[-1] for n in near)
    print(f"  Within ~5pp (statistical tie): {names} → decide among these on cost.")
print(f"  Cheapest/run: {cheapest.split('/')[-1]} "
      f"(${stat[cheapest][2]/max(1,stat[cheapest][3]):.4f}).")
if ntrials < 2:
    print("  NOTE: single trial per cell — quality ranks are noisy "
          "(see within-cell variance once AB_TRIALS>1). Cost is the robust signal.")
print("  Decision stays operator-gated.")
PY

echo
echo "[ab_arena] summary written: $SUMMARY"
rm -f "$ROWS"
echo "[ab_arena] worktrees left for review; discard with: git worktree prune"
exit 0
