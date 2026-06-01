#!/usr/bin/env bash
# scripts/validation_enforcement.sh — ADR 0162 item-7 live validation.
#
# The falsifiable claim: with CHIMERA_CRITIC_ENFORCE=1 and a clean calibration
# record, the in-loop critic gate BLOCKS the canonical silent regression (the
# `isdigit`-dropped to_snake that the green gate accepted in the first soak) from
# being committed — and ALLOWS a faithful fix. This drives the regression and the
# clean fix through the REAL gate (`check_commit_critic`) with the LIVE critic.
#
# Self-contained: builds a throwaway temp git repo (never touches the real tree),
# loads providers from ./.env, runs both cases, prints PASS/FAIL on the claim.
# Never pushes/PRs/merges. Costs ~2 live critic calls per case (reject escalates).
#
# Usage:  bash scripts/validation_enforcement.sh
#   CHIMERA_CRITIC_TIER  (unused here; the gate picks sonnet primary / opus escalator)

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"

if [ -f ./.env ]; then set -a; . ./.env; set +a; fi
export CHIMERA_CRITIC_ENFORCE=1
unset CHIMERA_ALLOW_CRITIC_REJECT 2>/dev/null || true

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
cd "$tmp" || exit 1
git init -q -b main
git config user.email "v@v"; git config user.name "v"
mkdir -p state

# A clean calibration record — the gate refuses to enforce without one. This
# mirrors the just-measured live result (27 cases, false-approve 0).
cat > state/critic-calibration-latest.json <<'JSON'
{"total": 27, "false_approve": 0, "false_reject": 3, "accuracy": 0.89}
JSON

# HEAD: the buggy pre-fix to_snake (uppercase-prev guard — the v43 bug).
cat > strcase.py <<'PY'
def to_snake(s: str) -> str:
    """Convert CamelCase to snake_case.

    Inserts '_' before an uppercase letter when the preceding character
    is lowercase or a digit.
    """
    result = []
    for i, ch in enumerate(s):
        if ch.isupper() and i > 0 and (s[i - 1].isupper() or s[i - 1].isdigit()):
            result.append("_")
        result.append(ch.lower())
    return "".join(result)
PY
git add strcase.py; git commit -q -m "seed: buggy to_snake"

run_case () {  # $1=label  (strcase.py already written + staged in $tmp)
    # Run python from the REPO (so `chimera` imports) but adjudicate the TEMP
    # repo by passing it as repo_root — the gate reads the staged diff there.
    ( cd "$REPO" && uv run python - "$1" "$tmp" <<'PY'
import sys, asyncio
from pathlib import Path
from chimera.core.critic_gate import check_commit_critic
label, root = sys.argv[1], Path(sys.argv[2])
d = asyncio.run(check_commit_critic(root, goal="fix to_snake so the camel tests pass"))
verd = d.verdict.summary() if d.verdict else "(none)"
print(f"CASE {label}: allowed={d.allowed} source={d.source}")
print(f"  verdict: {verd}")
if d.escalation is not None:
    print(f"  escalation: {d.escalation.summary()}")
sys.exit(0 if d.allowed else 1)
PY
    )
}

echo "=== ADR 0162 enforcement live validation ==="
echo

# CASE A — the silent regression: drop the digit branch (islower() only). This
# is the gate-PASSING change the soak accepted; the critic must REJECT it.
cat > strcase.py <<'PY'
def to_snake(s: str) -> str:
    """Convert CamelCase to snake_case.

    Inserts '_' before an uppercase letter when the preceding character
    is lowercase or a digit.
    """
    result = []
    for i, ch in enumerate(s):
        if ch.isupper() and i > 0 and s[i - 1].islower():
            result.append("_")
        result.append(ch.lower())
    return "".join(result)
PY
git add strcase.py
run_case "A (isdigit-dropped silent regression — expect BLOCKED)"
A_RC=$?
git restore --staged strcase.py 2>/dev/null || git reset -q strcase.py
echo

# CASE B — the faithful fix: lowercase-or-digit (matches the docstring). The
# critic must APPROVE.
cat > strcase.py <<'PY'
def to_snake(s: str) -> str:
    """Convert CamelCase to snake_case.

    Inserts '_' before an uppercase letter when the preceding character
    is lowercase or a digit.
    """
    result = []
    for i, ch in enumerate(s):
        if ch.isupper() and i > 0 and (s[i - 1].islower() or s[i - 1].isdigit()):
            result.append("_")
        result.append(ch.lower())
    return "".join(result)
PY
git add strcase.py
run_case "B (faithful lowercase-or-digit fix — expect ALLOWED)"
B_RC=$?
echo

echo "=== RESULT ==="
# Falsifiable claim: A blocked (rc!=0) AND B allowed (rc==0).
if [ "$A_RC" -ne 0 ] && [ "$B_RC" -eq 0 ]; then
    echo "PASS — gate BLOCKED the silent regression and ALLOWED the faithful fix."
    exit 0
else
    echo "FAIL — A_rc=$A_RC (want !=0, blocked)  B_rc=$B_RC (want 0, allowed)"
    exit 1
fi
