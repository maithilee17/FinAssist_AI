$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.env')) {
    throw 'Create .env once from .env.example and configure PostgreSQL/JWT secrets. No file was changed.'
}
# Compose handles interpolation and quoting. Never print resolved secrets.
docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose configuration is invalid.' }
$configText = docker compose config --format json
if ($LASTEXITCODE -ne 0) { throw 'Could not resolve Compose settings.' }
$composeSettings = $configText | ConvertFrom-Json
$backendPort = $composeSettings.services.backend.ports[0].published
$frontendPort = $composeSettings.services.frontend.ports[0].published
docker info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop and verify engine access.' }
# This transient container uses the existing backend image and resolved Compose
# settings to test the actual container-to-host path, without running migrations.
docker compose run --rm --no-deps --entrypoint python backend -m app.diagnostics.ollama
if ($LASTEXITCODE -ne 0) {
    throw 'Ollama check failed. Start Ollama, verify the model and OLLAMA_DOCKER_BASE_URL. If the backend image is absent, first run docker compose build backend frontend. No model was downloaded.'
}
docker compose up -d --build --wait --wait-timeout 300
if ($LASTEXITCODE -ne 0) { throw 'Startup failed. Inspect docker compose logs --tail=100. Volumes were preserved.' }
try {
    $ready = Invoke-RestMethod "http://localhost:$backendPort/api/health/ready" -TimeoutSec 15
    if ($ready.status -ne 'ready') { throw 'Dependencies are not ready.' }
} catch {
    throw 'Backend readiness failed. Inspect /api/health/ready and backend logs.'
}
Write-Host "FinAssist started: http://localhost:$frontendPort. Safe stop: docker compose stop"
