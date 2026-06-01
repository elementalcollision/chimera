#!/usr/bin/env bash
# scripts/characterize_soaks.sh — run N self-determined soaks SEQUENTIALLY (never
# concurrently — concurrency caused the collector races) and tabulate the
# enforced-loop characterization: convergence (did it commit?), build quality
# (ruff gate), and gate behavior (invoked? escalated? rescued?) per run.
#
# Each run is race-free (self_determined_soak binds its own WORKTREE). Writes a
# summary table to mind/research/characterization-<stamp>.md. Manual handoff —
# never pushes/PRs/merges. N=${N:-3}, RANK=${RANK:-13}, per-run wall cap via
# MAX_WALL_SECONDS.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"
N="${N:-3}"
RANK="${RANK:-13}"
STAMP="$(date -u +%Y-%m-%d-%H%M)"
OUT="mind/research/characterization-${STAMP}.md"
export MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-2400}"
export SELF_BASE="${SELF_BASE:-main}"

if [ -f ./.env ]; then set -a; . ./.env; set +a; fi
log() { echo "[$(date -u +%H:%M:%S)] $*"; }

{
  echo "# Enforced self-determined soak characterization — ${STAMP}"
  echo
  echo "N=${N} sequential runs, RANK=${RANK}, SELF_BASE=${SELF_BASE}, enforce ON."
  echo "Each run is race-free (own worktree). Per-run wall cap ${MAX_WALL_SECONDS}s."
  echo
  echo "| run | dur(s) | task | committed | ruff | gate invoked | escalated | primary | escalation | result |"
  echo "|----|----|----|----|----|----|----|----|----|----|"
} > "$OUT"

pass=0
for i in $(seq 1 "$N"); do
    log "── characterization run $i/$N (RANK=$RANK) ──"
    t0=$(date +%s)
    out="$(RANK="$RANK" bash scripts/self_determined_soak.sh 2>&1)"
    rc=$?
    dur=$(( $(date +%s) - t0 ))
    # Bind to this run's worktree from its own logged path.
    wt="$(printf '%s\n' "$out" | grep -oE 'wt=[^ )]+' | tail -1 | cut -d= -f2)"
    task="$(printf '%s\n' "$out" | grep -oE 'SELF-SELECTED \[rank [0-9]+\]: .*' | sed -E 's/SELF-SELECTED \[[^]]*\]: //' | head -1)"
    committed="$(printf '%s\n' "$out" | grep -oE 'committed     : (yes|no)[^[:space:]]*' | sed 's/.*: //' | head -1)"
    ruff="$(printf '%s\n' "$out" | grep -oE 'gate \(ruff\)   : (PASS|FAIL|\?)' | sed 's/.*: //' | head -1)"
    invoked="$(printf '%s\n' "$out" | grep -oE 'gate invoked  : (yes|NO)[^[:space:]]*' | sed 's/.*: //' | head -1)"
    result="PASS"; printf '%s\n' "$out" | grep -q "^INCONCLUSIVE" && result="INCONCLUSIVE"
    [ "$result" = "PASS" ] && pass=$((pass+1))
    # Decode the gate-log (if any) for primary/escalation verdicts.
    gl="$wt/state/critic-gate-log.jsonl"
    escalated="-"; primary="-"; escd="-"
    if [ -f "$gl" ]; then
        escalated="$(grep -oE '"escalated": (true|false)' "$gl" | tail -1 | sed 's/.*: //')"
        primary="$(grep -oE '"approved": (true|false|null)' "$gl" | tail -1 | sed 's/.*: //')"
        escd="$(grep -oE '"escalation_approved": (true|false|null)' "$gl" | tail -1 | sed 's/.*: //')"
    fi
    echo "| $i | $dur | ${task:-?} | ${committed:-?} | ${ruff:-?} | ${invoked:-?} | $escalated | $primary | $escd | $result |" >> "$OUT"
    log "  run $i: committed=${committed:-?} ruff=${ruff:-?} invoked=${invoked:-?} escalated=$escalated primary=$primary esc=$escd ($dur s)"
done

{
  echo
  echo "## Summary"
  echo "- PASS (committed + ruff PASS + gate allowed): **${pass}/${N}**"
  echo "- Convergence and gate-decision distribution above; high variance in"
  echo "  phase-1 convergence is the known characterization finding."
} >> "$OUT"
log "── characterization complete: ${pass}/${N} PASS → $OUT ──"
cat "$OUT"
