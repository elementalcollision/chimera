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
    local script_name="$1"
    local self_pid=$$
    # pgrep -f matches against the full command line. -l prints "<pid> <cmd>".
    # We drop our own PID and anything whose pid matches a known parent
    # (the shell that sourced this file).
    local others
    others=$(pgrep -fl "$script_name" 2>/dev/null \
        | awk -v me="$self_pid" '$1 != me { print $1 }')
    if [ -n "$others" ]; then
        echo "FATAL: another $script_name instance is already running:" >&2
        echo "$others" | while read -r pid; do
            ps -o pid=,etime=,command= -p "$pid" 2>/dev/null >&2 || true
        done
        echo "" >&2
        echo "Stop it first: pkill -f $script_name" >&2
        echo "Then retry this launch." >&2
        return 2
    fi
    return 0
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
