# scripts/_soak_common.sh — shared safety helpers for long_cycle soak runners.
#
# Sourced by long_cycle_soak_v*.sh, long_cycle_remediation.sh, and
# long_cycle_multi_agent.sh. Two responsibilities:
#
#   1. soak_refuse_concurrent <script_basename>
#      Exits non-zero if another instance of the same script is already
#      alive. The soak v6 post-mortem (mind/postmortems/soak-v6-2026-05-22.md
#      Failure A) traced three failed launches to overlapping runners sharing
#      a hardcoded log path; this guard prevents the collision class.
#
#   2. soak_install_killgroup_trap
#      Installs an EXIT/INT/TERM trap that walks the descendant tree and
#      sends SIGTERM. Without it, `chimera run` children survive parent
#      death and keep appending to the log file orphaned.
#
# Both helpers are intentionally portable to macOS bash 3.2 (no associative
# arrays, no setsid). They depend on pgrep and pkill, which are present on
# Darwin and Linux.

soak_refuse_concurrent() {
    # Pidfile-based concurrent-instance check.
    #
    # Background: the original implementation used `pgrep -fl "$script_name"`
    # to find other running instances. This was unreliable because bash's
    # `$()` command substitution forks a SUBSHELL with the SAME argv as the
    # parent script (e.g. `bash long_cycle_soak_v31.sh`), so pgrep finds
    # itself, awk, AND the subshell — all matching the pattern. The awk
    # filter dropped self but couldn't distinguish parent-script subshells
    # from genuine concurrent instances. Diagnosed during v31 R1 daemonized
    # launch (see mind/research/v31-silent-death-postmortem-2026-05-24.md).
    #
    # Replacement: write our PID to a stable pidfile keyed on the script
    # name. On a future invocation, read the pidfile and `kill -0` the PID;
    # if alive, refuse. If dead (stale pidfile) or no pidfile, overwrite
    # and continue. The pidfile is self-healing: no explicit cleanup needed
    # on exit, because the next invocation overwrites stale entries.
    #
    # Fail-safe escape hatch: SOAK_SKIP_CONCURRENT_CHECK=1 bypasses both
    # the pidfile read and write. Useful when operator knows no other
    # instance is running (e.g. fresh reboot) or for daemonized launches
    # under non-standard process trees where the operator has already
    # verified isolation.

    local script_name="$1"

    # Escape hatch — operator can bypass entirely.
    if [ "${SOAK_SKIP_CONCURRENT_CHECK:-0}" = "1" ]; then
        return 0
    fi

    local self_pid=$$
    # $0 is the soak runner that sourced this file; it lives in scripts/.
    # The repo's state/ is a sibling.
    local repo_root
    repo_root="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)" || repo_root="$PWD"
    local pidfile="${repo_root}/state/soak-${script_name%.sh}.pid"
    mkdir -p "$(dirname "$pidfile")" 2>/dev/null || true

    if [ -f "$pidfile" ]; then
        local existing_pid
        existing_pid=$(cat "$pidfile" 2>/dev/null | tr -d '[:space:]')
        if [ -n "$existing_pid" ] && [ "$existing_pid" != "$self_pid" ] \
           && kill -0 "$existing_pid" 2>/dev/null; then
            echo "FATAL: another $script_name instance is already running (PID $existing_pid):" >&2
            ps -o pid=,etime=,command= -p "$existing_pid" 2>/dev/null >&2 || true
            echo "" >&2
            echo "If you're sure no other instance is running, the pidfile is stale:" >&2
            echo "  rm $pidfile" >&2
            echo "Or to bypass this check for a single launch:" >&2
            echo "  SOAK_SKIP_CONCURRENT_CHECK=1 $0" >&2
            return 2
        fi
        # PID dead or matches self → fall through to overwrite.
    fi

    echo "$self_pid" > "$pidfile"
    return 0
}

soak_extract_sentinel_path() {
    # Parse an INBOX.md and print the first backtick-quoted
    # `mind/research/<name>.md` path. v7/v8/v9 runners were cloned
    # forward from v6 with the INBOX text updated but a sibling
    # INVESTIGATION_DOC constant left pointing at the v6 filename;
    # the runner then grep-checked the wrong file for the
    # READY-FOR-REMEDIATION sentinel and phase 1 spun forever even
    # when the agent produced the correct deliverable. Extracting
    # the target from the INBOX text removes the drift class.
    local inbox="$1"
    if [ ! -f "$inbox" ]; then
        return 1
    fi
    grep -oE '`mind/research/[A-Za-z0-9_-]+\.md`' "$inbox" \
        | head -n 1 \
        | tr -d '`'
}

soak_install_killgroup_trap() {
    # Capture the parent PID at trap-install time so the trap function
    # uses the script's PID, not a subshell's.
    local _soak_root_pid=$$
    # shellcheck disable=SC2317
    _soak_kill_descendants() {
        local root="$1"
        # Recurse via pgrep -P (children of <root>). Post-order: kill
        # grandchildren before children so SIGTERM doesn't get lost to a
        # parent that exits and re-parents its children to init.
        local kid
        for kid in $(pgrep -P "$root" 2>/dev/null); do
            _soak_kill_descendants "$kid"
            kill -TERM "$kid" 2>/dev/null || true
        done
    }
    # shellcheck disable=SC2317
    _soak_cleanup() {
        _soak_kill_descendants "$_soak_root_pid"
    }
    trap _soak_cleanup EXIT
    trap '_soak_cleanup; exit 130' INT
    trap '_soak_cleanup; exit 143' TERM
}
