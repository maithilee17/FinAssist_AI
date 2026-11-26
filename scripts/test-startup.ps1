# Standalone offline safety/lifecycle checks; no Pester or running daemon needed.
# All Docker, HTTP, and process enumeration is mocked before lifecycle tests.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'finassist-startup.ps1') -LibraryOnly
$repository = $script:Root
$testBase = Join-Path ([IO.Path]::GetTempPath()) ('finassist-startup-tests-' + [guid]::NewGuid())
$script:Root = Join-Path $testBase 'project with spaces'
$null = New-Item -ItemType Directory -Path $script:Root -Force
$script:Checks = 0
function Check([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw "FAILED: $Message" }
    $script:Checks++
}
function Must-Throw([scriptblock]$Operation, [string]$Message) {
    $failed = $false
    try { & $Operation | Out-Null } catch { $failed = $true }
    Check $failed $Message
}
try {
    Check ((Parse-Options @('--restart', '--build')).Build) 'build/restart parsing'
    Check ((Parse-Options @('--status')).Action -eq 'status') 'status parsing'
    Check ((Parse-Options @('--help')).Help) 'help parsing'
    foreach ($bad in @(@('--unknown'), @('--stop', '--build'), @('--no-clean', '--deep-clean'), @('--status', '--stop'), @('--follow'))) {
        Must-Throw { Parse-Options $bad } 'invalid/contradictory options rejected'
    }
    $node = [pscustomobject]@{ Name = 'node.exe'; CommandLine = 'node "' + $script:Root + '\frontend\node_modules\vite\bin\vite.js"' }
    Check (Test-OwnedHostProcess $node) 'absolute project Vite entry recognized'
    Check (-not (Test-OwnedHostProcess ([pscustomobject]@{Name='node.exe'; CommandLine='node C:\other\node_modules\vite\bin\vite.js'}))) 'unrelated Node protected'
    Check (-not (Test-OwnedHostProcess ([pscustomobject]@{Name='python.exe'; CommandLine='python -m uvicorn app.main:app'}))) 'ambiguous Python protected'
    Check (-not (Test-OwnedHostProcess ([pscustomobject]@{Name='python.exe'; CommandLine='python -m uvicorn app.main:app --extra "' + $script:Root + '\backend"'}))) 'path in arbitrary argument does not establish ownership'
    Check (-not (Test-OwnedHostProcess ([pscustomobject]@{Name='node.exe'; CommandLine='node "' + $script:Root + '-other\frontend\node_modules\vite\bin\vite.js"'}))) 'directory-prefix collision protected'
    Check (Test-OwnedHostProcess ([pscustomobject]@{Name='python.exe'; CommandLine='python -m uvicorn app.main:app --app-dir "' + $script:Root + '\backend"'})) 'explicit backend app directory recognized'
    Must-Throw { Assert-RealDirectory $testBase } 'out-of-root paths refused'
    Must-Throw { Assert-RealDirectory $script:Root } 'project root itself cannot be deleted'

    $persistent = @('.env', 'backend/uploads/report.pdf', 'backend/.model-cache/model.bin', 'backend/.venv/keep.txt', 'frontend/node_modules/keep.txt', 'frontend/package-lock.json', 'postgres-data/keep.txt')
    $disposable = @('backend/app/__pycache__/test.pyc', 'backend/.pytest_cache/test', 'frontend/node_modules/.vite/cache', 'frontend/dist/index.html')
    foreach ($relative in @($persistent + $disposable)) {
        $path = Join-Path $script:Root $relative
        $null = New-Item -ItemType Directory -Path (Split-Path $path) -Force
        Set-Content -LiteralPath $path -Value 'sentinel'
    }
    Remove-SafeCaches $false
    foreach ($relative in $persistent) { Check (Test-Path -LiteralPath (Join-Path $script:Root $relative)) "preserved $relative" }
    Check (-not (Test-Path -LiteralPath (Join-Path $script:Root 'backend/app/__pycache__'))) 'source bytecode cache removed'
    Check (Test-Path -LiteralPath (Join-Path $script:Root 'frontend/dist/index.html')) 'dist preserved without deep-clean'
    Remove-SafeCaches $true
    Check (-not (Test-Path -LiteralPath (Join-Path $script:Root 'frontend/dist'))) 'deep-clean removes only disposable dist'
    foreach ($relative in $persistent) { Check (Test-Path -LiteralPath (Join-Path $script:Root $relative)) "deep-clean preserved $relative" }

    $outside = Join-Path $testBase 'outside-project'
    $null = New-Item -ItemType Directory -Path $outside
    Set-Content -LiteralPath (Join-Path $outside 'keep.txt') -Value 'sentinel'
    $junction = Join-Path $script:Root '.pytest_cache'
    $junctionCreated = $false
    try { $null = New-Item -ItemType Junction -Path $junction -Target $outside; $junctionCreated = $true }
    catch { Write-Host 'SKIP: OS junction creation is unavailable; junction integration check not run.' }
    if ($junctionCreated) {
        Must-Throw { Remove-SafeCaches $false } 'cleanup refuses a junction escape'
        Check (Test-Path -LiteralPath (Join-Path $outside 'keep.txt')) 'junction target preserved'
        Remove-Item -LiteralPath $junction -Force
    }
    Acquire-Lock
    Must-Throw { Acquire-Lock } 'concurrent startup lock rejected'
    $script:Lock.Dispose(); $script:Lock = $null
    Acquire-Lock # an existing stale file is harmless after the handle is released
    $script:Lock.Dispose(); $script:Lock = $null

    Set-Content -LiteralPath (Join-Path $script:Root 'docker-compose.yml') -Value 'name: fixture'
    $null = New-Item -ItemType Directory -Path (Join-Path $script:Root 'frontend/src') -Force
    Set-Content -LiteralPath (Join-Path $script:Root 'frontend/src/app.js') -Value 'fixture'
    Set-Content -LiteralPath (Join-Path $script:Root 'backend/app/main.py') -Value 'fixture'
    $script:Fixture = @{
        name='finassist-startup-test'; services=@{
            postgres=@{ image='postgres:17'; healthcheck=@{test=@('CMD','true')} }
            chroma=@{ image='chroma:test'; ports=@(@{published='18001';target=8000;protocol='tcp';host_ip='127.0.0.1'}) }
            backend=@{ build=@{context=(Join-Path $script:Root 'backend')}; environment=@{
                LLM_PROVIDER='ollama'; OLLAMA_MODEL='qwen3:4b-instruct'; OLLAMA_BASE_URL='http://host.docker.internal:11434';
                CORS_ORIGINS='http://localhost:15173'; API_V1_PREFIX='/api'; JWT_SECRET_KEY='FAKE_TEST_SECRET'
            }; ports=@(@{published='18000';target=8000;protocol='tcp';host_ip='127.0.0.1'}) }
            frontend=@{ build=@{context=(Join-Path $script:Root 'frontend');args=@{VITE_API_URL='http://localhost:18000/api'}};
                ports=@(@{published='15173';target=80;protocol='tcp';host_ip='127.0.0.1'}) }
        }
    }
    $script:FakeRunning = $false; $script:UpCalls = @(); $script:Stops = 0; $script:IncludeOrphan = $false
    function Docker([string[]]$Arguments, [switch]$QuietFailure, [int]$Timeout=0) {
        $out = ''; $code = 0
        if ($Arguments -contains 'config') { $out = $script:Fixture | ConvertTo-Json -Depth 30 }
        elseif ($Arguments -contains 'up') { $script:UpCalls += ($Arguments -join ' '); $script:FakeRunning = $true }
        elseif ($Arguments[0] -eq 'stop') { $script:FakeRunning=$false; $script:Stops++ }
        elseif ($Arguments -contains 'ps') {
            if ($script:FakeRunning) {
                $out="postgres`nchroma`nbackend`nfrontend"
                if ($script:IncludeOrphan) { $out += "`nold-worker" }
            }
        }
        elseif ($Arguments[0] -eq 'image') { $out = 'sha256:fixture-' + $Arguments[-1] }
        elseif ($Arguments[0] -eq 'inspect') {
            if ($Arguments -contains '{{json .Config.Labels}}') {
                $out = @{'com.docker.compose.project.working_dir'=$script:Root} | ConvertTo-Json
            } elseif ($Arguments[-1] -eq 'old-worker') { $out='old-worker|exited|none' }
            else { $out = $Arguments[-1] + '|running|' + $(if ($Arguments[-1] -eq 'frontend') {'none'} else {'healthy'}) }
        }
        elseif ($Arguments -contains 'logs') { $out = 'test log FAKE_TEST_SECRET' }
        return [pscustomobject]@{Code=$code;Out=$out;Err=''}
    }
    function Get-CimInstance { return @() }
    function Get-NetTCPConnection { return @() }
    function Invoke-Http([string]$URL, [string]$Method='GET', [string]$Body='') {
        if ($URL -match '/api/tags$') { return [pscustomobject]@{ Content='{"models":[{"name":"qwen3:4b-instruct"}]}' } }
        if ($URL -match '/api/show$') { return [pscustomobject]@{ Content='{}' } }
        return [pscustomobject]@{Content='{"status":"ready","services":{"postgres":{"status":"up"},"chroma":{"status":"up"},"ollama":{"status":"up"}}}'}
    }
    Check ((Invoke-Main @()) -eq 0) 'mocked full startup succeeds'
    if ($script:Lock) { $script:Lock.Dispose(); $script:Lock=$null }
    Check ($script:UpCalls[0] -match '--build') 'first startup builds missing/untracked inputs'
    Check ((Invoke-Main @('--no-clean')) -eq 0) 'mocked repeated startup succeeds'
    if ($script:Lock) { $script:Lock.Dispose(); $script:Lock=$null }
    Check ($script:UpCalls[1] -match '--no-build') 'repeat startup reuses matching image IDs and inputs'
    Check ($script:Stops -eq 1) 'repeat startup stops only verified prior project containers'
    Check ($script:Model -eq 'qwen3:4b-instruct') 'model preserved'
    Check ($script:FrontendURL -eq 'http://localhost:15173') 'frontend port resolved from Compose'
    $script:IncludeOrphan = $true
    Check (@(Get-ServiceStates).Count -eq 4) 'preserved stopped orphan is excluded from current readiness graph'
    $script:IncludeOrphan = $false
    $allLogs = Get-ChildItem -LiteralPath (Join-Path $script:Root 'logs') -Filter '*.log' | Get-Content -Raw
    Check (-not (($allLogs -join '') -match 'FAKE_TEST_SECRET')) 'service logs redact resolved secrets'
    Check ((Get-Content -LiteralPath (Join-Path $script:Root '.env') -Raw).Trim() -eq 'sentinel') '.env untouched by lifecycle'
    Check ((Protect-Text 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.secret.signature') -notmatch 'eyJhbGci') 'generated bearer tokens redacted'

    $upBefore = $script:UpCalls.Count; $stopsBefore = $script:Stops
    function Invoke-Http([string]$URL, [string]$Method='GET', [string]$Body='') {
        return [pscustomobject]@{ Content='{"models":[{"name":"another-model"}]}' }
    }
    Must-Throw { Invoke-Main @('--no-clean') } 'missing configured model blocks startup'
    if ($script:Lock) { $script:Lock.Dispose(); $script:Lock=$null }
    Check ($script:UpCalls.Count -eq $upBefore -and $script:Stops -eq $stopsBefore) 'failed model preflight does not disrupt running services'

    function Get-NetTCPConnection { return @([pscustomobject]@{ LocalPort=18000; OwningProcess=99999 }) }
    Must-Throw { Assert-FreePorts } 'unrelated/unknown port owner blocks startup instead of killing'
    function Get-NetTCPConnection { return @() }
    $oldDocker = ${function:Docker}
    function Docker([string[]]$Arguments, [switch]$QuietFailure, [int]$Timeout=0) {
        if ($Arguments[0] -eq 'inspect' -and $Arguments -contains '{{json .Config.Labels}}') {
            return [pscustomobject]@{Code=0;Out='{"com.docker.compose.project.working_dir":"C:\\unrelated-project"}';Err=''}
        }
        & $oldDocker -Arguments $Arguments
    }
    Must-Throw { Get-OwnedContainers } 'same-name Compose project in another directory is protected'
    Write-Host "PASS: $($script:Checks) offline startup safety/lifecycle checks. No live services were changed."
} finally {
    if ($script:Lock) { $script:Lock.Dispose() }
    $script:LogFile=$null; $script:ErrorFile=$null
    # Only this newly generated, absolute temporary fixture tree is removed.
    $resolvedBase = [IO.Path]::GetFullPath($testBase)
    if ($resolvedBase.StartsWith([IO.Path]::GetFullPath([IO.Path]::GetTempPath()), [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $resolvedBase) -like 'finassist-startup-tests-*') {
        Remove-Item -LiteralPath $resolvedBase -Recurse -Force
    }
}
