#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd -- "$SCRIPT_DIR"

if ! command -v docker >/dev/null 2>&1; then
    printf 'Docker CLI was not found. No services were changed.\n' >&2
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    printf 'Docker Desktop engine is unavailable. No services were changed.\n' >&2
    exit 1
fi

printf 'Stopping FinAssist Compose services without removing containers or volumes...\n'
docker compose stop frontend backend chroma postgres
printf 'FinAssist services stopped. Persistent volumes and Ollama remain untouched.\n'
printf 'Restart with: ./start-finassist.sh\n'
