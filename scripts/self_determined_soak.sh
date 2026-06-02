#!/usr/bin/env bash
# scripts/self_determined_soak.sh — Chimera SELF-SELECTS its own work, then builds
# it under the enforced critic gate. The keystone self-determination step:
# self_scan (the WHAT leg, ADR 0161) RANKS behaviour-neutral maintenance tasks;
# this wrapper auto-picks the agent's TOP-ranked candidate (no human chooses the
# task) and runs a real_task_soak on it with CHIMERA_CRITIC_ENFORCE=1.
#
# The agent's own ranking decides what gets built; the gate (live-validated,
# ADR 0162) is the safety floor. Fallback OFF — only the agent's own gated
# git_commit can land. Manual handoff: never pushes/PRs/merges.
#
# RANK=N picks the Nth-ranked candidate (default 1 = the top pick).
# CAMPAIGN_DRYRUN=1 prints the self-selected task without launching.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"
RANK="${RANK:-1}"
if [ -f ./.env ]; then set -a; . ./.env; set +a; fi

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

# 1. Ask the agent's origination faculty to rank the work, and auto-pick rank N.
log "── self-scan: ranking candidates (auto-pick rank $RANK) ──"
scan="$(uv run chimera self-scan --limit "$RANK" 2>/dev/null)"
cmd="$(printf '%s\n' "$scan" | grep -E '^\s*\$ TASK_GOAL=' | sed -E 's/^[[:space:]]*\$ //' | tail -1)"
if [ -z "$cmd" ]; then
    log "FATAL: self-scan produced no runnable candidate."; exit 2
fi
# Extract the self-selected task fields (for the record) without blind-eval risk.
sel_goal="$(printf '%s' "$cmd"  | sed -E 's/.*TASK_GOAL="([^"]*)".*/\1/')"
sel_files="$(printf '%s' "$cmd" | sed -E 's/.*TASK_FILES="([^"]*)".*/\1/')"
log "  SELF-SELECTED [rank $RANK]: $sel_goal"
log "  files: $sel_files"

# Test-backed anchor ("Both"): if the self-selected file has a matching
# tests/test_<name>.py, attach it as TASK_TEST so the agent has a crisp acceptance
# signal (verify + faithfulness), not just "ruff clean".
sel_test=""
for f in $sel_files; do
    cand="tests/test_$(basename "$f")"
    if [ -f "$cand" ]; then sel_test="$cand"; break; fi
done
[ -n "$sel_test" ] && log "  test anchor: $sel_test" \
    || log "  test anchor: (none — verify --ruff is the only anchor)"

# Worktree base for the soak (default main, which now carries the refreshed
# tier ladders). Override with SELF_BASE to test an unmerged branch.
SELF_BASE="${SELF_BASE:-main}"

# 2. Enforcement ON. ACT model: by DEFAULT use the refreshed `sonnet` spread
#    ladder (deepseek-v4-pro → minimax → glm → qwen → mistral → gemini → claude),
#    so the build loop exercises the operator-selected diverse models. Pin a
#    single model only if the operator explicitly sets CHIMERA_ACT_FORCE_MODEL.
export CHIMERA_CRITIC_ENFORCE=1
ACT_DESC="spread ladder (sonnet tier)"
if [ -n "${CHIMERA_ACT_FORCE_MODEL:-}" ]; then
    export CHIMERA_ACT_FORCE_MODEL
    ACT_DESC="pinned $CHIMERA_ACT_FORCE_MODEL"
fi
export CHIMERA_SOAK_AUTOCOMMIT="0"
export PHASE1_CAP_USD="${PHASE1_CAP_USD:-3.00}"
export PHASE2_CAP_USD="${PHASE2_CAP_USD:-1.50}"
export MAX_WALL_SECONDS="${MAX_WALL_SECONDS:-2100}"
export COOLDOWN_SECONDS="${COOLDOWN_SECONDS:-10}"
# Ensure the gate can enforce (calibration record must exist & be clean).
fa="$(uv run python -c "import json;print(json.load(open('state/critic-calibration-latest.json')).get('false_approve'))" 2>/dev/null || echo missing)"
if [ "$fa" != "0" ]; then
    log "FATAL: calibration false_approve=$fa (need 0). Run chimera critic-calibrate."; exit 2
fi
log "  enforce=ON  fallback=OFF  calibration false_approve=$fa"

if [ "${CAMPAIGN_DRYRUN:-0}" = "1" ]; then
    log "dryrun — would run: $cmd"; exit 0
fi

# 3. Build it: run the self-selected soak under enforcement, with the capable ACT
#    model, the test anchor (if any), and the chosen worktree base.
# Bind THIS invocation to a UNIQUE worktree path (real_task_soak honours $WORKTREE)
# so the collector reads our own run — not whatever `ls -t` surfaces, which
# cross-contaminated results when soaks ran concurrently.
WT="$REPO/../chimera-soak-realtask-selfdet-$$-$(date -u +%Y%m%d-%H%M%S)"
export WORKTREE="$WT"
cmd="$(printf '%s' "$cmd" | sed -E "s|TASK_BASE=\"[^\"]*\"|TASK_BASE=\"$SELF_BASE\"|")"
[ -n "$sel_test" ] && cmd="TASK_TEST=\"$sel_test\" $cmd"
log "── launching self-determined soak (enforced, ACT=$ACT_DESC, base=$SELF_BASE, wt=$WT) ──"
eval "$cmd" >/dev/null 2>&1 || true

# 4. Collect — bound to OUR worktree, not `ls -t` (no cross-run race).
wt="$WT"
committed="no"; gate="?"; verdict="?"; touched="-"; gatelog="(none)"; allowed="no"; approved="-"
if [ -n "$wt" ] && [ -d "$wt" ]; then
    base="$(cd "$wt" && git rev-parse --abbrev-ref HEAD 2>/dev/null)"
    sha="$(cd "$wt" && git log --format='%h %s' "$SELF_BASE"..HEAD 2>/dev/null | grep '\[agent\]' | head -1)"
    [ -n "$sha" ] && committed="yes ($sha)"
    touched="$(cd "$wt" && git diff --name-only "$SELF_BASE"..HEAD 2>/dev/null | tr '\n' ' ')"
    # Capture the FULL verify verdict line (e.g. "FAIL — ruff ✓, pytest ✗") so the
    # ruff/pytest split is visible — a green ruff with broken pytest (the agent
    # hand-edited and broke the suite) is the dominant failure mode and must not
    # be hidden behind a bare PASS/FAIL.
    verdict="$(cd "$wt" && uv run chimera verify --ruff ${sel_files} 2>&1 | tail -1)"
    gate="$(printf '%s' "$verdict" | grep -oE 'PASS|FAIL' || echo '?')"
    if [ -f "$wt/state/critic-gate-log.jsonl" ]; then
        gatelog="$(wc -l < "$wt/state/critic-gate-log.jsonl" | tr -d ' ') decision(s)"
        grep -q '"allowed": true' "$wt/state/critic-gate-log.jsonl" && allowed="yes"
        approved="$(grep -oE '"approved": (true|false|null)' "$wt/state/critic-gate-log.jsonl" | tail -1)"
    fi
    # finding-#2 instrument: did check_commit_critic actually run on the commit?
    if [ -f "$wt/state/critic-gate-debug.jsonl" ]; then
        gate_invoked="yes ($(grep -c '"event": "enter"' "$wt/state/critic-gate-debug.jsonl") enter)"
    else
        gate_invoked="NO (gate never invoked → commit bypassed the gated path)"
    fi
fi
log "── result ──"
log "  self-selected : $sel_goal"
log "  committed     : $committed"
log "  gate (ruff)   : $gate"
log "  gate verdict  : $verdict"
log "  touched       : $touched"
log "  gate log      : $gatelog   allowed-entry=$allowed   last-$approved"
log "  gate invoked  : ${gate_invoked:-?}"
log "  review        : cd $wt && git log -p "$SELF_BASE"..HEAD && cat state/critic-gate-log.jsonl"
echo
if [ "${committed%% *}" = "yes" ] && [ "$gate" = "PASS" ] && [ "$allowed" = "yes" ]; then
    echo "PASS — Chimera self-selected a task, built it, and the enforced gate approved its self-commit."
    exit 0
fi
echo "INCONCLUSIVE — committed=$committed gate=$gate allowed=$allowed (inspect the worktree)."
exit 1
