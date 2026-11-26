#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$SCRIPT_DIR"

usage() {
    cat <<'EOF'
Usage: ./cleanup-finassist.sh [--clean-build-cache]

Default cleanup removes only regenerated project-local artifacts:
  - Python __pycache__ directories and .pyc/.pyo files in source/test trees
  - pytest and Ruff caches
  - Vite cache and frontend/dist production output

--clean-build-cache requests Docker build-cache cleanup. FinAssist deliberately
does not run a global Docker prune: BuildKit does not reliably identify cache by
Compose project. The request is reported and safely skipped.
EOF
}

REQUEST_BUILD_CACHE=false
for argument in "$@"; do
    case "$argument" in
        --clean-build-cache) REQUEST_BUILD_CACHE=true ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$argument" >&2; usage >&2; exit 2 ;;
    esac
done

safe_remove() {
    local target="$1"
    [[ -e "$target" || -L "$target" ]] || return 0

    local parent resolved
    parent="$(cd -- "$(dirname -- "$target")" && pwd -P)"
    resolved="$parent/$(basename -- "$target")"
    case "$resolved" in
        "$PROJECT_ROOT"/*) ;;
        *)
            printf 'REFUSED: cleanup target is outside the project: %s\n' "$resolved" >&2
            return 1
            ;;
    esac

    rm -rf -- "$resolved"
    printf 'Removed disposable artifact: %s\n' "${resolved#"$PROJECT_ROOT"/}"
}

remove_python_artifacts() {
    local source_root cache_file
    for source_root in \
        "$PROJECT_ROOT/backend/app" \
        "$PROJECT_ROOT/backend/tests" \
        "$PROJECT_ROOT/backend/alembic"; do
        [[ -d "$source_root" ]] || continue
        while IFS= read -r -d '' cache_file; do
            if [[ -d "$cache_file" ]]; then
                safe_remove "$cache_file"
            else
                rm -f -- "$cache_file"
                printf 'Removed disposable artifact: %s\n' "${cache_file#"$PROJECT_ROOT"/}"
            fi
        done < <(
            find "$source_root" \
                \( -type d -name '__pycache__' -print0 -prune \) -o \
                \( -type f \( -name '*.pyc' -o -name '*.pyo' \) -print0 \)
        )
    done
}

printf 'FinAssist safe cleanup\n'
printf 'Project: %s\n' "$PROJECT_ROOT"

remove_python_artifacts

for disposable in \
    "$PROJECT_ROOT/.pytest_cache" \
    "$PROJECT_ROOT/.ruff_cache" \
    "$PROJECT_ROOT/backend/.pytest_cache" \
    "$PROJECT_ROOT/backend/.ruff_cache" \
    "$PROJECT_ROOT/frontend/.vite" \
    "$PROJECT_ROOT/frontend/dist"; do
    safe_remove "$disposable"
done

if [[ "$REQUEST_BUILD_CACHE" == true ]]; then
    cat <<'EOF'
Docker build-cache cleanup requested but safely skipped.
Docker BuildKit cache is shared globally and does not provide a dependable
Compose-project ownership filter. FinAssist will not run global Docker pruning
or remove images belonging to other applications.
EOF
fi

cat <<'EOF'
Preserved: .env, Docker volumes, databases, Chroma collections, uploads,
embedding/model caches, Ollama models, virtual environments, node_modules,
dependency caches, source code, migrations, evaluation artifacts, and logs.
EOF
