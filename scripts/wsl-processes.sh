#!/usr/bin/env bash
set -Eeuo pipefail
root="$(cd -- "$1" && pwd -P)"; timeout="$2"
[[ "$timeout" =~ ^[1-9][0-9]*$ ]] && (( timeout <= 3600 )) || { echo 'Invalid FINASSIST_STOP_TIMEOUT.' >&2; exit 2; }
owned() {
    local pid="$1" cwd cmd executable
    cwd="$(readlink -e "/proc/$pid/cwd" 2>/dev/null || true)"
    [[ "$cwd" == "$root/backend" || "$cwd" == "$root/frontend" ]] || return 1
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
    executable="$(readlink "/proc/$pid/exe" 2>/dev/null || true)"
    case "$cwd:$executable:$cmd" in
        "$root/backend":*python*:*uvicorn*app.main:app*|"$root/backend":*uvicorn*:*app.main:app*) return 0 ;;
        "$root/frontend":*node*:*node_modules/vite/*) return 0 ;;
    esac
    return 1
}
for process in /proc/[0-9]*; do
    pid="${process##*/}"
    owned "$pid" || continue
    # Record Linux start ticks; never signal a reused PID.
    born="$(awk '{print $22}' "$process/stat" 2>/dev/null || true)"
    [[ -n "$born" ]] || continue
    printf 'Stopping verified WSL FinAssist development server PID %s (TERM).\n' "$pid"
    kill -TERM "$pid" 2>/dev/null || true
    deadline=$((SECONDS + timeout))
    while kill -0 "$pid" 2>/dev/null && (( SECONDS < deadline )); do sleep 1; done
    if owned "$pid" && [[ "$(awk '{print $22}' "$process/stat" 2>/dev/null || true)" == "$born" ]]; then
        kill -KILL "$pid" 2>/dev/null || true
    fi
done
