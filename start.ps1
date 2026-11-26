# Native Windows entry point. No Git Bash, host Python or host Node is needed:
# the discovered backend and frontend both run in Compose containers.
$ErrorActionPreference = 'Stop'
try {
    & (Join-Path $PSScriptRoot 'scripts\finassist-startup.ps1') @args
    exit $LASTEXITCODE
} catch {
    Write-Error 'FinAssist startup manager could not run. Check PowerShell execution policy and scripts/finassist-startup.ps1.'
    exit 1
}
