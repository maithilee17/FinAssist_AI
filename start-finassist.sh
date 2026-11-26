#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$SCRIPT_DIR"
cd -- "$PROJECT_ROOT"

LOG_DIR="$PROJECT_ROOT/logs"
mkdir -p -- "$LOG_DIR"
LOG_FILE="$LOG_DIR/startup-$(date '+%Y%m%d-%H%M%S').log"

exec 3>&1 4>&2
exec > >(
    while IFS= read -r line || [[ -n "$line" ]]; do
        printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$line" | tee -a "$LOG_FILE"
    done
) 2>&1
LOGGER_PID=$!

finish_logging() {
    exec 1>&3 2>&4
    wait "$LOGGER_PID" 2>/dev/null || true
    exec 3>&- 4>&-
}

on_error() {
    local status=$?
    trap - ERR
    printf 'FAIL: startup stopped near script line %s (exit %s).\n' "${BASH_LINENO[0]:-unknown}" "$status"
    printf 'No volumes or persistent application data were removed.\n'
    printf 'Inspect: %s\n' "$LOG_FILE"
    printf 'Diagnostics: docker compose ps --all\n'
    printf '             docker compose logs --tail=100 backend chroma postgres frontend\n'
    finish_logging
    exit "$status"
}
trap on_error ERR

pass() { printf 'PASS: %s\n' "$*"; }
info() { printf 'INFO: %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*"; }
die() { printf 'FAIL: %s\n' "$*" >&2; return 1; }

command_required() {
    command -v "$1" >/dev/null 2>&1 || die "$2"
}

read_env_value() {
    local key="$1" value
    value="$({
        awk -v wanted="$key" '
            /^[[:space:]]*#/ { next }
            {
                line=$0
                sub(/\r$/, "", line)
                split(line, fields, "=")
                name=fields[1]
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
                if (name == wanted) {
                    sub(/^[^=]*=/, "", line)
                    found=line
                }
            }
            END { print found }
        ' "$PROJECT_ROOT/.env"
    } 2>/dev/null)"
    value="${value#\"}"; value="${value%\"}"
    value="${value#\'}"; value="${value%\'}"
    printf '%s' "$value"
}

http_ready() {
    local url="$1"
    local code
    code="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
        --connect-timeout 3 --max-time 8 "$url" 2>/dev/null || true)"
    [[ "$code" =~ ^2[0-9][0-9]$ ]]
}

wait_for_http() {
    local label="$1" url="$2" attempts="$3" delay="$4"
    local attempt
    for ((attempt=1; attempt<=attempts; attempt++)); do
        if http_ready "$url"; then
            pass "$label is ready ($url)"
            return 0
        fi
        if (( attempt == 1 || attempt % 5 == 0 )); then
            info "Waiting for $label ($attempt/$attempts)..."
        fi
        sleep "$delay"
    done
    die "$label did not become ready at $url within $((attempts * delay)) seconds."
}

container_state() {
    local service="$1" container_id
    container_id="$(docker compose ps -q "$service" 2>/dev/null || true)"
    [[ -n "$container_id" ]] || { printf 'missing'; return 0; }
    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
        "$container_id" 2>/dev/null || printf 'unknown'
}

wait_for_service() {
    local service="$1" attempts="$2" delay="$3"
    local attempt state
    for ((attempt=1; attempt<=attempts; attempt++)); do
        state="$(container_state "$service")"
        case "$state" in
            healthy|running)
                pass "Compose service '$service' is $state"
                return 0
                ;;
            unhealthy|exited|dead)
                die "Compose service '$service' entered state '$state'. Run: docker compose logs --tail=100 $service"
                ;;
        esac
        if (( attempt == 1 || attempt % 5 == 0 )); then
            info "Waiting for Compose service '$service' (state: $state, $attempt/$attempts)..."
        fi
        sleep "$delay"
    done
    die "Compose service '$service' did not become healthy within $((attempts * delay)) seconds."
}

detect_host_environment() {
    local kernel
    kernel="$(uname -s)"
    case "$kernel" in
        MINGW*|MSYS*|CYGWIN*) HOST_ENVIRONMENT='Git Bash' ;;
        Linux*)
            if grep -qiE '(microsoft|wsl)' /proc/version 2>/dev/null; then
                HOST_ENVIRONMENT='WSL'
            else
                die 'This Windows launcher supports Git Bash or WSL. Native Linux is not the intended host for Windows Ollama.'
            fi
            ;;
        *) die "Unsupported shell environment: $kernel. Use Git Bash or WSL on Windows." ;;
    esac
    pass "Compatible shell detected: $HOST_ENVIRONMENT"
}

windows_ollama_http_ready() {
    if [[ "$HOST_ENVIRONMENT" == 'Git Bash' ]]; then
        http_ready 'http://127.0.0.1:11434/api/tags'
        return
    fi

    if http_ready 'http://127.0.0.1:11434/api/tags'; then
        return 0
    fi

    if command -v powershell.exe >/dev/null 2>&1; then
        powershell.exe -NoProfile -NonInteractive -Command \
            'try { $r=Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5; if ($r.StatusCode -eq 200) { exit 0 } }; exit 1' \
            >/dev/null 2>&1
        return
    fi
    return 1
}

start_windows_ollama() {
    command_required powershell.exe \
        'Ollama is installed on Windows but cannot be started from this shell. Start the Ollama application, then rerun FinAssist.'
    info 'Starting the existing Windows Ollama installation...'
    powershell.exe -NoProfile -NonInteractive -Command \
        '$exe=(Get-Command ollama.exe -ErrorAction Stop).Source; Start-Process -FilePath $exe -ArgumentList "serve" -WindowStyle Hidden' \
        >/dev/null
}

windows_ollama_process_running() {
    command -v powershell.exe >/dev/null 2>&1 || return 1
    powershell.exe -NoProfile -NonInteractive -Command \
        'if (Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like "ollama*" }) { exit 0 }; exit 1' \
        >/dev/null 2>&1
}

find_ollama_command() {
    if command -v ollama >/dev/null 2>&1; then
        OLLAMA_COMMAND='ollama'
    elif command -v ollama.exe >/dev/null 2>&1; then
        OLLAMA_COMMAND='ollama.exe'
    elif command -v powershell.exe >/dev/null 2>&1 && \
        powershell.exe -NoProfile -NonInteractive -Command \
            'if (Get-Command ollama.exe -ErrorAction SilentlyContinue) { exit 0 }; exit 1' \
            >/dev/null 2>&1; then
        OLLAMA_COMMAND='powershell.exe'
    else
        die 'Ollama was not found. Install Ollama for Windows from https://ollama.com/download, then rerun this script.'
    fi
    pass 'Ollama installation found'
}

ollama_cli() {
    if [[ "$OLLAMA_COMMAND" == 'powershell.exe' ]]; then
        local command_line='& ollama.exe'
        local argument
        for argument in "$@"; do
            command_line+=" '$(printf '%s' "$argument" | sed "s/'/''/g")'"
        done
        powershell.exe -NoProfile -NonInteractive -Command "$command_line" | tr -d '\r'
    else
        "$OLLAMA_COMMAND" "$@" | tr -d '\r'
    fi
}

ollama_model_available() {
    ollama_cli list 2>/dev/null | awk 'NR > 1 { print $1 }' | grep -Fqx -- "$OLLAMA_MODEL"
}

wait_for_ollama() {
    local attempt
    for ((attempt=1; attempt<=30; attempt++)); do
        if windows_ollama_http_ready; then
            pass 'Ollama host API is ready (http://127.0.0.1:11434)'
            return 0
        fi
        if (( attempt == 1 || attempt % 5 == 0 )); then
            info "Waiting for the Windows Ollama API ($attempt/30)..."
        fi
        sleep 2
    done
    die 'Ollama did not become ready within 60 seconds. Start the Windows Ollama application and confirm http://127.0.0.1:11434/api/tags.'
}

verify_backend_ollama() {
    docker compose exec -T backend python -c '
import sys
import httpx

base_url = sys.argv[1].rstrip("/")
model = sys.argv[2]
response = httpx.get(f"{base_url}/api/tags", timeout=10)
response.raise_for_status()
models = response.json().get("models", [])
if not any(item.get("name") == model for item in models):
    raise SystemExit(f"Configured Ollama model is not visible to the backend: {model}")
print("Backend reached Ollama and found the configured model.")
' "$OLLAMA_BASE_URL" "$OLLAMA_MODEL"
    pass 'Backend-to-Ollama connectivity is ready'
}

hash_backend_context() {
    (
        cd -- "$PROJECT_ROOT"
        {
            printf '%s\0' \
                'backend/Dockerfile' \
                'backend/.dockerignore' \
                'backend/requirements.txt' \
                'backend/alembic.ini' \
                'backend/docker-entrypoint.sh'
            find backend/app backend/alembic -type f \
                ! -path '*/__pycache__/*' \
                ! -path '*/.cache/*' \
                ! -path '*/.runtime/*' \
                ! -path 'backend/app/evaluation/real_world/documents/*.pdf' \
                ! -path 'backend/app/evaluation/end_to_end/results.json' \
                ! -path 'backend/app/evaluation/end_to_end/resume_results.json' \
                ! -name '*.pyc' ! -name '*.pyo' ! -name '*.log' -print0
        } | sort -z | while IFS= read -r -d '' file; do
            sha256sum -- "$file"
        done
    ) | sha256sum | awk '{ print $1 }'
}

hash_frontend_context() {
    (
        cd -- "$PROJECT_ROOT"
        {
            find frontend \
                \( -type d \( -name node_modules -o -name dist -o -name .vite \) -prune \) -o \
                \( -type f ! -name '*.log' ! -name '.env' ! -name '.env.*' -print0 \)
            printf 'compose-build-args:%s:%s:%s:%s\0' \
                "$(read_env_value BACKEND_PORT)" \
                "$(read_env_value CSRF_COOKIE_NAME)" \
                "$(read_env_value MAX_UPLOAD_SIZE_MB)" \
                "$(read_env_value VITE_PROCESSING_TIMEOUT_MS)"
        } | sort -z | while IFS= read -r -d '' file; do
            if [[ "$file" == compose-build-args:* ]]; then
                printf '%s\n' "$file" | sha256sum
            else
                sha256sum -- "$file"
            fi
        done
    ) | sha256sum | awk '{ print $1 }'
}

build_changed_images() {
    command_required sha256sum 'sha256sum is required to detect changed Docker build inputs.'
    local state_dir="$PROJECT_ROOT/.finassist-state"
    local backend_state="$state_dir/backend-build.sha256"
    local frontend_state="$state_dir/frontend-build.sha256"
    local backend_hash frontend_hash previous
    local -a build_services=()

    mkdir -p -- "$state_dir"
    backend_hash="$(hash_backend_context)"
    frontend_hash="$(hash_frontend_context)"

    previous="$(cat "$backend_state" 2>/dev/null || true)"
    if [[ "$previous" != "$backend_hash" ]] || \
        ! docker image inspect finassist-ai-backend:latest >/dev/null 2>&1; then
        build_services+=(backend)
    else
        pass 'Backend build inputs are unchanged; existing image will be reused'
    fi

    previous="$(cat "$frontend_state" 2>/dev/null || true)"
    if [[ "$previous" != "$frontend_hash" ]] || \
        ! docker image inspect finassist-ai-frontend:latest >/dev/null 2>&1; then
        build_services+=(frontend)
    else
        pass 'Frontend build inputs are unchanged; existing image will be reused'
    fi

    if (( ${#build_services[@]} > 0 )); then
        info "Building ${#build_services[@]} changed local image(s):"
        printf '  %s\n' "${build_services[@]}"
        docker compose build "${build_services[@]}"
    else
        pass 'No backend or frontend image rebuild is required'
    fi

    printf '%s\n' "$backend_hash" > "$backend_state.tmp"
    mv -f -- "$backend_state.tmp" "$backend_state"
    printf '%s\n' "$frontend_hash" > "$frontend_state.tmp"
    mv -f -- "$frontend_state.tmp" "$frontend_state"
}

cat <<'EOF'
============================================================
 FinAssist AI — safe one-command startup
============================================================
EOF
info "Project root: $PROJECT_ROOT"
info "Startup log: $LOG_FILE"

detect_host_environment
command_required curl 'curl is required for bounded health checks. Git Bash includes it; install curl in WSL if necessary.'
command_required docker 'Docker CLI was not found. Install/start Docker Desktop and enable WSL integration if using WSL.'
docker compose version >/dev/null 2>&1 || die 'Docker Compose v2 is unavailable. Update Docker Desktop so `docker compose` works.'
pass 'Docker Compose v2 is available'
docker info >/dev/null 2>&1 || die 'Docker Desktop engine is unavailable. Start Docker Desktop, wait until it is ready, and rerun this script.'
pass 'Docker Desktop engine is available'

[[ -f "$PROJECT_ROOT/.env" ]] || die 'Missing .env. Create it once from .env.example, set strong local secrets, select Ollama, and rerun. The startup script will not create or overwrite it.'
pass 'Private .env exists and will not be modified'

LLM_PROVIDER="$(read_env_value LLM_PROVIDER)"
OLLAMA_BASE_URL="$(read_env_value OLLAMA_DOCKER_BASE_URL)"
OLLAMA_MODEL="$(read_env_value OLLAMA_MODEL)"
[[ "${LLM_PROVIDER,,}" == 'ollama' ]] || die "LLM_PROVIDER must be 'ollama' for local startup (currently '${LLM_PROVIDER:-unset}'). Update .env; it was not modified."
[[ -n "$OLLAMA_BASE_URL" ]] || OLLAMA_BASE_URL='http://host.docker.internal:11434'
[[ -n "$OLLAMA_MODEL" ]] || OLLAMA_MODEL='qwen2.5:7b'
pass "Ollama provider selected with model '$OLLAMA_MODEL'"

if [[ "$OLLAMA_BASE_URL" != 'http://host.docker.internal:11434' ]]; then
    warn "OLLAMA_BASE_URL is '$OLLAMA_BASE_URL'. Docker Desktop normally requires http://host.docker.internal:11434."
fi

find_ollama_command
if windows_ollama_http_ready; then
    pass 'Ollama was already running; no duplicate server was started'
elif windows_ollama_process_running; then
    info 'An Ollama process already exists but is not ready; waiting instead of starting a duplicate server.'
else
    start_windows_ollama
fi
wait_for_ollama

if ollama_model_available; then
    pass "Ollama model '$OLLAMA_MODEL' is installed"
else
    die "Model '$OLLAMA_MODEL' is missing. After approval run: ollama pull $OLLAMA_MODEL"
fi

info 'Running Level 1 project-local cleanup...'
bash "$PROJECT_ROOT/cleanup-finassist.sh"

docker compose config --quiet
pass 'Docker Compose configuration is valid'

build_changed_images

info 'Starting PostgreSQL and ChromaDB without recreating persistent volumes...'
docker compose up -d postgres chroma
wait_for_service postgres 40 3
wait_for_service chroma 60 3
wait_for_http 'ChromaDB heartbeat' 'http://127.0.0.1:8001/api/v2/heartbeat' 30 2

info 'Starting the backend; its existing entry command applies pending Alembic upgrades before Uvicorn...'
docker compose up -d backend
wait_for_service backend 100 3
wait_for_http 'Backend liveness' 'http://127.0.0.1:8000/api/health/live' 30 2
wait_for_http 'Backend readiness' 'http://127.0.0.1:8000/api/health/ready' 30 2
verify_backend_ollama

info 'Starting the frontend...'
docker compose up -d frontend
wait_for_http 'Frontend' 'http://127.0.0.1:5173' 40 2

printf '\n'
printf 'FinAssist startup report\n'
printf '  PASS  Ollama API and model: %s\n' "$OLLAMA_MODEL"
printf '  PASS  PostgreSQL container health\n'
printf '  PASS  ChromaDB container and HTTP heartbeat\n'
printf '  PASS  Backend liveness and dependency readiness\n'
printf '  PASS  Backend-to-Ollama connectivity\n'
printf '  PASS  Frontend HTTP availability\n'
printf '\nOpen FinAssist: http://localhost:5173\n'
printf 'Backend API:    http://localhost:8000/docs\n'
printf 'Startup log:    %s\n' "$LOG_FILE"
printf 'Safe stop:      ./stop-finassist.sh\n'
finish_logging
