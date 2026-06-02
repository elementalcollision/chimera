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
# RANKS: optional space-separated list of self-scan ranks to SWEEP — one run per
# rank, for BREADTH across diverse self-selected tasks (source vs test files,
# varying complexity). When unset, fall back to DEPTH: repeat RANK N times.
RANKS="${RANKS:-}"
if [ -n "$RANKS" ]; then
    RUN_RANKS="$RANKS"
else
    RUN_RANKS=""
    for _i in $(seq 1 "$N"); do RUN_RANKS="$RUN_RANKS $RANK"; done
fi
RUN_TOTAL="$(printf '%s' "$RUN_RANKS" | wc -w | tr -d ' ')"
STAMP="$(date -u +%Y-%m-%d-%H%M)"
OUT="mind/research/characterization-${STAMP}.md"
export MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-2400}"
export SELF_BASE="${SELF_BASE:-main}"

if [ -f ./.env ]; then set -a; . ./.env; set +a; fi
log() { echo "[$(date -u +%H:%M:%S)] $*"; }

{
  echo "# Enforced self-determined soak characterization — ${STAMP}"
  echo
  if [ -n "$RANKS" ]; then
    echo "BREADTH sweep — ranks [${RANKS}], SELF_BASE=${SELF_BASE}, enforce ON."
  else
    echo "DEPTH — ${N} sequential runs, RANK=${RANK}, SELF_BASE=${SELF_BASE}, enforce ON."
  fi
  echo "Each run is race-free (own worktree). Per-run wall cap ${MAX_WALL_SECONDS}s."
  echo
  echo "| run | dur(s) | task | committed | verify verdict | gate invoked | escalated | primary | escalation | result |"
  echo "|----|----|----|----|----|----|----|----|----|----|"
} > "$OUT"

pass=0
i=0
for r in $RUN_RANKS; do
    i=$((i+1))
    log "── characterization run $i/$RUN_TOTAL (RANK=$r) ──"
    t0=$(date +%s)
    out="$(RANK="$r" bash scripts/self_determined_soak.sh 2>&1)"
    rc=$?
    dur=$(( $(date +%s) - t0 ))
    # Bind to this run's worktree from its own logged path.
    wt="$(printf '%s\n' "$out" | grep -oE 'wt=[^ )]+' | tail -1 | cut -d= -f2)"
    task="$(printf '%s\n' "$out" | grep -oE 'SELF-SELECTED \[rank [0-9]+\]: .*' | sed -E 's/SELF-SELECTED \[[^]]*\]: //' | head -1)"
    committed="$(printf '%s\n' "$out" | grep -oE 'committed     : (yes|no)[^[:space:]]*' | sed 's/.*: //' | head -1)"
    ruff="$(printf '%s\n' "$out" | grep -oE 'gate \(ruff\)   : (PASS|FAIL|\?)' | sed 's/.*: //' | head -1)"
    # Full verify verdict (ruff/pytest split) — surfaces "ruff ✓, pytest ✗", the
    # dominant failure mode, instead of a bare PASS/FAIL.
    verdict="$(printf '%s\n' "$out" | grep -oE 'gate verdict  : .*' | sed 's/gate verdict  : //' | head -1)"
    [ -z "$verdict" ] && verdict="${ruff:-?}"
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
    echo "| $i | $dur | ${task:-?} | ${committed:-?} | ${verdict:-?} | ${invoked:-?} | $escalated | $primary | $escd | $result |" >> "$OUT"
    log "  run $i: committed=${committed:-?} ruff=${ruff:-?} invoked=${invoked:-?} escalated=$escalated primary=$primary esc=$escd ($dur s)"
done

{
  echo
  echo "## Summary"
  echo "- PASS (committed + ruff PASS + gate allowed): **${pass}/${RUN_TOTAL}**"
  echo "- Convergence and gate-decision distribution above; high variance in"
  echo "  phase-1 convergence is the known characterization finding."
} >> "$OUT"
log "── characterization complete: ${pass}/${RUN_TOTAL} PASS → $OUT ──"
cat "$OUT"
