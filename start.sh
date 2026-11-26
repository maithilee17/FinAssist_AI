#!/usr/bin/env bash
# Windows host adapter: Compose, ports and Ollama must be inspected on Windows,
# including when this entry point is invoked through Docker Desktop's WSL bridge.
set -Eeuo pipefail
on_error() {
    local code=$?
    printf 'FinAssist launcher failed at line %s (exit %s). No persistent-data cleanup was requested.\n' "${BASH_LINENO[0]:-unknown}" "$code" >&2
    exit "$code"
}
trap on_error ERR
trap 'printf "FinAssist launch interrupted; inspect ./start.sh --status.\n" >&2; exit 130' INT
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
usage() {
    cat <<'EOF'
Usage: ./start.sh [--restart|--stop|--status|--logs] [options]
  --no-clean       Skip disposable cache cleanup
  --deep-clean     Also remove frontend/dist and test coverage output
  --build          Explicitly rebuild Compose build images
  --follow         Follow logs (with --logs); Ctrl+C leaves services running
  --help           Show this help without accessing Docker

Default: stop verified project instances, clean safe caches, reuse unchanged
images, start all configured Compose services and verify application readiness.
No volumes, uploads, models, environments or dependency directories are deleted.
Windows PowerShell equivalent: .\start.ps1 [same options]
Timeouts: FINASSIST_DOCKER_TIMEOUT=120 FINASSIST_READY_TIMEOUT=300
          FINASSIST_STOP_TIMEOUT=20 FINASSIST_COMMAND_TIMEOUT=600 (seconds)
EOF
}
action=start; chosen=0; clean=0; deep=0; build=0; follow=0
for argument in "$@"; do
    case "$argument" in
        --help|-h) usage; exit 0 ;;
        --restart|--stop|--status|--logs)
            (( chosen == 0 )) || { echo 'Choose only one action.' >&2; exit 2; }
            action="${argument#--}"; chosen=1 ;;
        --no-clean) clean=1 ;;
        --deep-clean) deep=1 ;;
        --build) build=1 ;;
        --follow) follow=1 ;;
        *) printf 'Unknown option: %s\n' "$argument" >&2; usage >&2; exit 2 ;;
    esac
done
(( clean == 0 || deep == 0 )) || { echo '--no-clean conflicts with --deep-clean.' >&2; exit 2; }
if [[ "$action" != start && "$action" != restart ]] && (( clean || deep || build )); then
    echo 'Cleanup/build options apply only to start/restart.' >&2; exit 2
fi
[[ "$action" == logs || "$follow" == 0 ]] || { echo '--follow requires --logs.' >&2; exit 2; }

case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
        command -v cygpath >/dev/null || { echo 'Git Bash cygpath is required.' >&2; exit 1; }
        windows_script="$(cygpath -w "$ROOT/start.ps1")"
        ;;
    Linux*)
        grep -qiE 'microsoft|wsl' /proc/version || { echo 'Use Git Bash, Windows PowerShell, or WSL on Windows.' >&2; exit 1; }
        command -v wslpath >/dev/null || { echo 'WSL interop/wslpath is required.' >&2; exit 1; }
        windows_script="$(wslpath -w "$ROOT/start.ps1")"
        [[ "$windows_script" != \\* ]] || { echo 'Keep this project on a Windows drive (for example /mnt/c). WSL Linux-filesystem checkouts are not supported by this Windows host manager.' >&2; exit 1; }
        # Only this distribution's explicitly verified native dev servers.
        # The Windows adapter handles Windows processes separately.
        if [[ "$action" == start || "$action" == restart || "$action" == stop ]]; then
            bash "$ROOT/scripts/wsl-processes.sh" "$ROOT" "${FINASSIST_STOP_TIMEOUT:-20}"
        fi
        ;;
    *) echo 'This launcher targets Windows: use Git Bash, PowerShell, or WSL.' >&2; exit 1 ;;
esac
if command -v pwsh.exe >/dev/null; then
    powershell_host=pwsh.exe
elif command -v powershell.exe >/dev/null; then
    powershell_host=powershell.exe
else
    echo 'Windows PowerShell / WSL Windows interop is required.' >&2; exit 1
fi
# Do not bypass execution policy or alter machine settings. Arguments remain
# separate tokens; neither .env nor user arguments are evaluated as shell code.
export MSYS_NO_PATHCONV=1
exec "$powershell_host" -NoLogo -NoProfile -File "$windows_script" "$@"
