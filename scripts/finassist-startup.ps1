# Windows PowerShell 5.1+ host implementation used by both public entry points.
# Docker owns application supervision. This manager never launches a second
# host backend/frontend, removes volumes, pulls Ollama models, or evaluates .env.
param([switch]$LibraryOnly)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$script:Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd('\', '/')
$script:Secrets = @()
$script:LogFile = $null
$script:ErrorFile = $null
$script:ComposeArgs = @()
$script:Services = @()
$script:Lock = $null
$script:CommandTimeout = 600

function Get-Value($Object, [string]$Name, $Default = $null) {
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -ne $property) { return $property.Value }
    return $Default
}
function Get-Timeout([string]$Name, [int]$Default) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    $number = 0
    if (-not [int]::TryParse($value, [ref]$number) -or $number -lt 1 -or $number -gt 3600) {
        throw "$Name must be an integer between 1 and 3600 seconds."
    }
    return $number
}
function Protect-Text([string]$Text) {
    foreach ($secret in $script:Secrets) {
        if ($secret.Length -ge 1) { $Text = $Text.Replace($secret, '[REDACTED]') }
    }
    $Text = $Text -replace '(?i)([a-z][a-z0-9+.-]*://)[^/@\s]+:[^/@\s]+@', '$1[REDACTED]@'
    $Text = $Text -replace '(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*', 'Bearer [REDACTED]'
    return ($Text -replace '(?i)((?:password|token|api[_-]?key|secret)\s*[=:]\s*)[^\s,;]+', '$1[REDACTED]')
}
function Write-Log([string]$Message, [string]$Level = 'INFO') {
    $line = '[{0}] [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, (Protect-Text $Message)
    Write-Host $line
    if ($script:LogFile) { Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8 }
    if ($Level -eq 'ERROR' -and $script:ErrorFile) { Add-Content -LiteralPath $script:ErrorFile -Value $line -Encoding UTF8 }
}
function Quote-NativeArgument([string]$Value) {
    # Windows CommandLineToArgvW quoting, including trailing backslashes.
    return '"' + (($Value -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
}
function Invoke-Native([string]$Program, [string[]]$Arguments, [int]$Timeout = 0) {
    if ($Timeout -eq 0) { $Timeout = $script:CommandTimeout }
    $resolved = (Get-Command $Program -ErrorAction Stop).Source
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $resolved
    $info.Arguments = (@($Arguments | ForEach-Object { Quote-NativeArgument $_ }) -join ' ')
    $info.WorkingDirectory = $script:Root
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.StandardOutputEncoding = [Text.Encoding]::UTF8
    $info.StandardErrorEncoding = [Text.Encoding]::UTF8
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    $started = $false
    try {
        $null = $process.Start()
        $started = $true
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit($Timeout * 1000)) {
            # Only this manager's own CLI child is terminated, never a server.
            $process.Kill()
            $process.WaitForExit()
            throw "A $Program operation exceeded $Timeout seconds; services may still be running."
        }
        return [pscustomobject]@{ Code = $process.ExitCode; Out = $stdout.Result; Err = $stderr.Result }
    } finally {
        if ($started -and -not $process.HasExited) { $process.Kill() }
        $process.Dispose()
    }
}
function Docker([string[]]$Arguments, [switch]$QuietFailure, [int]$Timeout = 0) {
    $result = Invoke-Native 'docker.exe' $Arguments $Timeout
    if ($result.Code -ne 0 -and -not $QuietFailure) {
        if ($result.Err) { Write-Log $result.Err.Trim() 'ERROR' }
        throw 'Docker operation failed. See the startup/error logs; no persistent data was removed.'
    }
    return $result
}
function Compose([string[]]$Arguments, [switch]$QuietFailure, [int]$Timeout = 0) {
    return Docker (@($script:ComposeArgs) + $Arguments) -QuietFailure:$QuietFailure -Timeout $Timeout
}
function Parse-Options([string[]]$Arguments) {
    $options = @{ Action = 'start'; Clean = $true; Deep = $false; Build = $false; Follow = $false; Help = $false }
    $actionSet = $false
    foreach ($argument in $Arguments) {
        switch -Exact ($argument) {
            { $_ -in '--help', '-h' } { $options.Help = $true }
            { $_ -in '--restart', '--stop', '--status', '--logs' } {
                if ($actionSet) { throw 'Choose only one action: --restart, --stop, --status, or --logs.' }
                $options.Action = $argument.Substring(2); $actionSet = $true
            }
            '--no-clean' { $options.Clean = $false }
            '--deep-clean' { $options.Deep = $true }
            '--build' { $options.Build = $true }
            '--follow' { $options.Follow = $true }
            default { throw "Unknown option: $argument. Use --help." }
        }
    }
    if ($options.Deep -and -not $options.Clean) { throw '--deep-clean conflicts with --no-clean.' }
    if ($options.Action -notin 'start', 'restart' -and ($options.Deep -or -not $options.Clean -or $options.Build)) {
        throw 'Cleanup/build options apply only to start/restart.'
    }
    if ($options.Follow -and $options.Action -ne 'logs') { throw '--follow requires --logs.' }
    return $options
}
function Show-Help {
    @'
FinAssist AI startup manager
  .\start.ps1                         Safe cleanup and verified startup
  .\start.ps1 --restart               Gracefully restart project services
  .\start.ps1 --stop                  Stop project services; preserve volumes/Ollama
  .\start.ps1 --status                Show resolved ports, container state and HTTP status
  .\start.ps1 --logs [--follow]        Sanitized service logs; Ctrl+C stops following
  .\start.ps1 --no-clean              Skip cleanup
  .\start.ps1 --deep-clean            Also clear disposable dist/coverage outputs
  .\start.ps1 --build                 Explicit image rebuild
  .\start.ps1 --help                  Show help without accessing Docker
Git Bash / Windows-drive WSL checkout: ./start.sh [same options]
Timeout environment variables (seconds, 1..3600): FINASSIST_DOCKER_TIMEOUT=120,
FINASSIST_READY_TIMEOUT=300, FINASSIST_STOP_TIMEOUT=20, FINASSIST_COMMAND_TIMEOUT=600.
No execution-policy changes, model downloads, volume deletion or global pruning.
'@ | Write-Host
}
function Normalize-Root([string]$Path) {
    $Path = $Path -replace '^/mnt/([a-z])/', '$1:/' -replace '^/([a-z])/', '$1:/'
    return [IO.Path]::GetFullPath($Path.Replace('/', '\')).TrimEnd('\').ToLowerInvariant()
}
function Assert-RealDirectory([string]$Path) {
    if ((Get-Item -LiteralPath $script:Root -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Refused a symlink/junction as the project root.'
    }
    $root = Normalize-Root $script:Root
    $candidate = Normalize-Root $Path
    if (-not $candidate.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Refused path outside the project.' }
    $cursor = $Path
    while ((Normalize-Root $cursor) -ne $root) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Refused a symlink/junction in a cleanup/build/state path.'
            }
        }
        $cursor = Split-Path -Parent $cursor
    }
}
function Initialize-Logs {
    $directory = Join-Path $script:Root 'logs'
    Assert-RealDirectory $directory
    $null = New-Item -ItemType Directory -Path $directory -Force
    $script:RunId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $PID
    $script:LogFile = Join-Path $directory ('startup-' + $script:RunId + '.log')
    $script:ErrorFile = Join-Path $directory ('errors-' + $script:RunId + '.log')
}
function Acquire-Lock {
    $directory = Join-Path $script:Root '.finassist-state'
    Assert-RealDirectory $directory
    $null = New-Item -ItemType Directory -Path $directory -Force
    $path = Join-Path $directory 'startup.lock'
    Assert-RealDirectory $path
    try { $script:Lock = [IO.File]::Open($path, 'OpenOrCreate', 'ReadWrite', 'None') }
    catch { throw 'Another FinAssist startup/stop operation is running. A stale lock file alone does not block startup.' }
}
function Load-Configuration([bool]$Application = $true) {
    if (-not (Test-Path -LiteralPath (Join-Path $script:Root '.env') -PathType Leaf)) { throw 'Missing .env. Configure it once from .env.example; no file was created or changed.' }
    $files = @(@('compose.yaml', 'compose.yml', 'docker-compose.yaml', 'docker-compose.yml') | Where-Object { Test-Path -LiteralPath (Join-Path $script:Root $_) })
    if ($files.Count -ne 1) { throw 'Expected exactly one root Compose file. Resolve ambiguous Compose files explicitly.' }
    $script:ComposeArgs = @('compose', '--project-directory', $script:Root, '-f', (Join-Path $script:Root $files[0]))
    # Config can contain credentials: capture privately, never print it or raw errors.
    $result = Compose @('config', '--format', 'json') -QuietFailure
    if ($result.Code -ne 0) { throw 'Compose configuration could not be resolved. Check .env/interpolation locally; resolved secrets were not logged.' }
    $script:Config = $result.Out | ConvertFrom-Json
    $script:Project = $script:Config.name
    $script:Services = @($script:Config.services.PSObject.Properties.Name)
    foreach ($service in $script:Config.services.PSObject.Properties) {
        $environment = Get-Value $service.Value 'environment'
        if ($environment) {
            foreach ($entry in $environment.PSObject.Properties) {
                if ($entry.Name -match '(?i)PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE_KEY|DATABASE_URL') { $script:Secrets += [string]$entry.Value }
            }
        }
    }
    if (-not $Application) { return }
    # Identify application roles from build contexts and real project files.
    $script:Backend = $null; $script:Frontend = $null
    foreach ($service in $script:Config.services.PSObject.Properties) {
        $build = Get-Value $service.Value 'build'
        $context = [string](Get-Value $build 'context' '')
        if ($context -and (Normalize-Root $context) -eq (Normalize-Root (Join-Path $script:Root 'backend'))) { $script:Backend = $service.Name }
        if ($context -and (Normalize-Root $context) -eq (Normalize-Root (Join-Path $script:Root 'frontend'))) { $script:Frontend = $service.Name }
    }
    if (-not $script:Backend -or -not $script:Frontend) { throw 'Could not identify the Compose backend/frontend build contexts. This manager will not invent host startup commands.' }
    $script:BackendConfig = $script:Config.services.($script:Backend)
    $script:FrontendConfig = $script:Config.services.($script:Frontend)
    $script:BackendEnv = $script:BackendConfig.environment
    if ((Get-Value $script:BackendEnv 'LLM_PROVIDER') -ne 'ollama') { throw 'The resolved backend provider must be ollama; configuration was not modified.' }
    $script:Model = [string](Get-Value $script:BackendEnv 'OLLAMA_MODEL' '')
    $script:OllamaURL = [string](Get-Value $script:BackendEnv 'OLLAMA_BASE_URL' '')
    if (-not $script:Model -or -not $script:OllamaURL) { throw 'Resolved Ollama URL/model is missing.' }
    $script:BackendURL = Get-PublishedURL $script:BackendConfig
    $script:FrontendURL = Get-PublishedURL $script:FrontendConfig
    $script:ApiPrefix = [string](Get-Value $script:BackendEnv 'API_V1_PREFIX' '/api')
    $script:ReadinessURL = $script:BackendURL + $script:ApiPrefix.TrimEnd('/') + '/health/ready'
    $script:FrontendApi = [string](Get-Value $script:FrontendConfig.build.args 'VITE_API_URL' '')
    if ($script:FrontendApi.TrimEnd('/') -ne ($script:BackendURL + $script:ApiPrefix).TrimEnd('/')) {
        throw 'The frontend build API URL does not match the resolved published backend URL. Correct Compose/build settings; no configuration was changed.'
    }
    $cors = [string](Get-Value $script:BackendEnv 'CORS_ORIGINS' '')
    if ($script:FrontendURL -notin @($cors.Split(',') | ForEach-Object { $_.Trim() })) { throw 'CORS_ORIGINS does not include the published frontend URL.' }
}
function Get-PublishedURL($Service) {
    $ports = @(Get-Value $Service 'ports' @() | Where-Object { (Get-Value $_ 'protocol' 'tcp') -eq 'tcp' })
    if ($ports.Count -ne 1) { throw 'Expected exactly one published TCP application port.' }
    $port = [string]$ports[0].published
    if ($port -notmatch '^\d+$') { throw 'Application published port must be a single fixed port.' }
    return 'http://localhost:' + $port
}
function Ensure-Docker([bool]$Start) {
    $deadline = (Get-Date).AddSeconds($script:DockerTimeout)
    $attempted = $false
    do {
        $info = Docker @('info', '--format', '{{.ServerVersion}}') -QuietFailure -Timeout 8
        if ($info.Code -eq 0) { Write-Log 'Docker Engine connected.' 'OK'; return }
        if (-not $Start) { throw 'Docker Engine is unavailable; no service was changed. Start Docker Desktop.' }
        if (-not $attempted) {
            $attempted = $true
            $paths = @(
                (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
                (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\frontend\Docker Desktop.exe'),
                (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe')
            )
            $desktop = @($paths | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1)
            if ($desktop.Count -eq 0) { throw 'Docker Desktop was not found at its supported Windows installation paths. Start it manually and enable WSL integration if needed.' }
            if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
                $null = Start-Process -FilePath $desktop[0] -WindowStyle Hidden -PassThru
                Write-Log 'Launched installed Docker Desktop; waiting for its engine.'
            }
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw 'Docker Engine did not become available before FINASSIST_DOCKER_TIMEOUT. Check Docker Desktop permissions, engine status and WSL integration.'
}
function Get-OwnedContainers {
    $result = Docker @('ps', '-aq', '--filter', ('label=com.docker.compose.project=' + $script:Project))
    $owned = @()
    foreach ($id in @($result.Out -split '\s+' | Where-Object { $_ })) {
        $data = Docker @('inspect', '--format', '{{json .Config.Labels}}', $id)
        $labels = $data.Out | ConvertFrom-Json
        $directory = [string](Get-Value $labels 'com.docker.compose.project.working_dir' '')
        if (-not $directory -or (Normalize-Root $directory) -ne (Normalize-Root $script:Root)) {
            throw "Compose project-name collision for container $id. Its working-directory label does not match this checkout; it will not be stopped."
        }
        $owned += $id
    }
    return $owned
}
function Test-OwnedHostProcess($Process) {
    $command = [string](Get-Value $Process 'CommandLine' '')
    $name = [string](Get-Value $Process 'Name' '')
    if (-not $command) { return $false }
    # Require an absolute project path with a directory boundary, plus a known
    # runner. A generic `python -m uvicorn app.main:app` cannot prove ownership.
    $frontend = [regex]::Escape((Join-Path $script:Root 'frontend')).Replace('\\', '[\\/]')
    $backend = [regex]::Escape((Join-Path $script:Root 'backend')).Replace('\\', '[\\/]')
    if ($name -match '^node(?:\.exe)?$') {
        return $command -match ('(?:^|\s|\")' + $frontend + '[\\/]node_modules[\\/]vite[\\/]')
    }
    if ($name -notmatch '^(python(?:w)?|uvicorn)(?:\.exe)?$') { return $false }
    $appDirectory = '--app-dir(?:=|\s+)\"?' + $backend + '(?:\"|\s|$)'
    $mainFile = '(?:^|\s|\")' + $backend + '[\\/]app[\\/]main\.py(?:\"|\s|$)'
    return (($command -match 'uvicorn.*app\.main:app' -and $command -match $appDirectory) -or $command -match $mainFile)
}
function Stop-OwnedHostProcesses {
    foreach ($process in @(Get-CimInstance Win32_Process | Where-Object { Test-OwnedHostProcess $_ })) {
        $processId = [int]$process.ProcessId; $born = $process.CreationDate
        Write-Log "Requesting graceful shutdown of verified FinAssist $($process.Name) PID $processId."
        $null = Invoke-Native 'taskkill.exe' @('/PID', [string]$processId) 5
        $deadline = (Get-Date).AddSeconds($script:StopTimeout)
        do {
            $current = Get-CimInstance Win32_Process -Filter "ProcessId=$processId"
            if (-not $current -or $current.CreationDate -ne $born) { break }
            Start-Sleep -Milliseconds 500
        } while ((Get-Date) -lt $deadline)
        if ($current -and $current.CreationDate -eq $born -and (Test-OwnedHostProcess $current)) {
            Write-Log "Graceful timeout expired; terminating verified FinAssist PID $processId." 'WARN'
            Stop-Process -Id $processId -Force -ErrorAction Stop
        }
    }
}
function Stop-Project {
    $owned = @(Get-OwnedContainers)
    if ($owned.Count) {
        Write-Log "Stopping $($owned.Count) verified project container(s), including stale services; timeout $($script:StopTimeout)s."
        $null = Docker (@('stop', '--time', [string]$script:StopTimeout) + $owned)
    }
    Stop-OwnedHostProcesses
    Write-Log 'Project services stopped. Containers, volumes, uploads, chat history and shared Ollama were preserved.' 'OK'
}
function Assert-FreePorts {
    try { $allListeners = @(Get-NetTCPConnection -State Listen -ErrorAction Stop) }
    catch { throw 'Windows TCP listener inspection is unavailable. Refusing startup without a reliable port-ownership check.' }
    foreach ($service in $script:Config.services.PSObject.Properties) {
        foreach ($binding in @(Get-Value $service.Value 'ports' @())) {
            if ((Get-Value $binding 'protocol' 'tcp') -ne 'tcp') { throw 'A new non-TCP published service needs an explicit ownership check.' }
            $port = [int]$binding.published
            $listeners = @($allListeners | Where-Object { $_.LocalPort -eq $port })
            foreach ($listener in $listeners) {
                $process = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $listener.OwningProcess)
                $name = if ($process) { $process.Name } else { 'unidentified process' }
                throw "Required port $port ($($service.Name)) is occupied by $name PID $($listener.OwningProcess). Ownership was not proven; nothing was killed. Inspect Get-NetTCPConnection and Docker published ports."
            }
        }
    }
}
function Remove-SafeCaches([bool]$Deep) {
    $paths = @('.pytest_cache', '.ruff_cache', '.mypy_cache', 'backend/.pytest_cache', 'backend/.ruff_cache', 'backend/.mypy_cache',
        'frontend/.vite', 'frontend/node_modules/.vite', 'frontend/node_modules/.vite-temp')
    foreach ($tree in @('backend/app', 'backend/tests', 'backend/alembic')) {
        $pending = New-Object 'Collections.Generic.Stack[string]'
        $pending.Push((Join-Path $script:Root $tree))
        while ($pending.Count) {
            $directory = $pending.Pop()
            if (-not (Test-Path -LiteralPath $directory)) { continue }
            Assert-RealDirectory $directory
            foreach ($child in Get-ChildItem -LiteralPath $directory -Directory -Force) {
                if ($child.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
                if ($child.Name -in '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache') { $paths += $child.FullName }
                elseif ($child.Name -notin '.runtime', '.cache', 'uploads', '.model-cache') { $pending.Push($child.FullName) }
            }
        }
    }
    if ($Deep) { $paths += @('frontend/dist', 'frontend/coverage', 'backend/htmlcov') }
    foreach ($relative in $paths) {
        $target = if ([IO.Path]::IsPathRooted($relative)) { $relative } else { Join-Path $script:Root $relative }
        if (-not (Test-Path -LiteralPath $target)) { continue }
        Assert-RealDirectory $target
        # Verify every descendant too: do not recursively follow a junction.
        Assert-NoLinks $target
        Remove-Item -LiteralPath $target -Recurse -Force
        Write-Log ('Removed disposable cache: ' + $target.Substring($script:Root.Length + 1))
    }
}
function Assert-NoLinks([string]$Path) {
    $pending = New-Object 'Collections.Generic.Stack[string]'
    $pending.Push($Path)
    while ($pending.Count) {
        $item = Get-Item -LiteralPath $pending.Pop() -Force
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Cleanup refused a symlink/junction.' }
        if ($item.PSIsContainer) { foreach ($child in Get-ChildItem -LiteralPath $item.FullName -Force) { $pending.Push($child.FullName) } }
    }
}
function Invoke-Http([string]$URL, [string]$Method = 'GET', [string]$Body = '') {
    try {
        $parameters = @{ Uri = $URL; Method = $Method; TimeoutSec = 5; UseBasicParsing = $true; ErrorAction = 'Stop' }
        if ($Body) { $parameters.Body = $Body; $parameters.ContentType = 'application/json' }
        return Invoke-WebRequest @parameters
    } catch { return $null }
}
function Ensure-Ollama {
    $uri = $null
    if (-not [Uri]::TryCreate($script:OllamaURL, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -notin 'http', 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
        throw 'Ollama URL must be HTTP(S) without credentials, query or fragment.'
    }
    # host.docker.internal is for the backend container, not the Windows probe.
    $local = $uri.Host -in 'host.docker.internal', 'localhost', '127.0.0.1', '::1'
    $builder = New-Object UriBuilder($uri)
    if ($uri.Host -eq 'host.docker.internal') { $builder.Host = '127.0.0.1' }
    $script:HostOllamaURL = $builder.Uri.AbsoluteUri.TrimEnd('/')
    $response = Invoke-Http ($script:HostOllamaURL + '/api/tags')
    if (-not $response -and $local) {
        $ollama = Get-Command ollama.exe -ErrorAction SilentlyContinue
        if (-not $ollama) { throw 'Ollama is unavailable. Install/start the Windows Ollama application. No model was downloaded.' }
        $existing = @(Get-Process -Name 'ollama*' -ErrorAction SilentlyContinue)
        $occupied = @(Get-NetTCPConnection -State Listen -LocalPort $uri.Port -ErrorAction SilentlyContinue)
        if ($occupied.Count -and -not $existing.Count) { throw 'Ollama endpoint is occupied by an unverified service; refusing to start another server.' }
        if (-not $existing.Count -and -not $occupied.Count) {
            # Start only with the requested binding for this child; no machine
            # settings change. Do not expose the API on 0.0.0.0 automatically.
            if ($uri.Host -in '::1') { throw 'Start the configured IPv6 Ollama service manually.' }
            $oldHost = [Environment]::GetEnvironmentVariable('OLLAMA_HOST', 'Process')
            try {
                if (-not $oldHost) { $env:OLLAMA_HOST = '127.0.0.1:' + $uri.Port }
                $null = Start-Process -FilePath $ollama.Source -ArgumentList 'serve' -WindowStyle Hidden -PassThru
            } finally { [Environment]::SetEnvironmentVariable('OLLAMA_HOST', $oldHost, 'Process') }
            Write-Log 'Started the installed Windows Ollama server; no model download requested.'
        }
        $deadline = (Get-Date).AddSeconds($script:ReadyTimeout)
        do {
            $response = Invoke-Http ($script:HostOllamaURL + '/api/tags')
            if ($response) { break }
            Start-Sleep -Seconds 2
        } while ((Get-Date) -lt $deadline)
    }
    if (-not $response) { throw 'Configured Ollama API is unavailable. Check the host binding and Docker/WSL network configuration.' }
    $tags = $response.Content | ConvertFrom-Json
    if ($script:Model -notin @($tags.models | ForEach-Object { $_.name })) { throw "Configured model '$($script:Model)' is not installed at the selected Ollama API. Install it manually; no automatic pull is permitted." }
    $body = @{ model = $script:Model } | ConvertTo-Json -Compress
    $show = Invoke-Http ($script:HostOllamaURL + '/api/show') 'POST' $body
    if (-not $show) { throw 'Ollama could list the model but /api/show could not verify it.' }
    Write-Log "Ollama connected; installed model verified: $($script:Model)." 'OK'
}
function Get-BuildFingerprint($Service) {
    $context = [string]$Service.build.context
    Assert-RealDirectory $context
    $ignored = @('node_modules', '.venv', 'venv', '__pycache__', '.git', '.pytest_cache', '.ruff_cache', '.mypy_cache', '.model-cache', 'uploads', 'dist', 'coverage', 'htmlcov', '.vite', '.runtime', '.cache')
    $pending = New-Object 'Collections.Generic.Stack[string]'
    $pending.Push($context)
    $files = @()
    while ($pending.Count) {
        foreach ($item in Get-ChildItem -LiteralPath $pending.Pop() -Force) {
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Build context contains an unsupported symlink/junction.' }
            if ($item.PSIsContainer) { if ($item.Name -notin $ignored) { $pending.Push($item.FullName) } }
            elseif ($item.Name -notmatch '^\.env(?:\.|$)|\.(?:log|pyc|pyo|db|sqlite3?)$') { $files += $item.FullName }
        }
    }
    $builder = New-Object Text.StringBuilder
    $null = $builder.Append(($Service.build | ConvertTo-Json -Depth 20 -Compress))
    foreach ($file in @($files | Sort-Object)) {
        $null = $builder.Append($file.Substring($context.Length)).Append((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash)
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($builder.ToString()))).Replace('-', '') }
    finally { $sha.Dispose() }
}
function Get-BuildPlan([bool]$Force) {
    $script:Fingerprints = @{}
    $rebuild = $Force
    foreach ($service in $script:Config.services.PSObject.Properties) {
        if (-not (Get-Value $service.Value 'build')) { continue }
        $hash = Get-BuildFingerprint $service.Value
        $script:Fingerprints[$service.Name] = $hash
        $image = [string](Get-Value $service.Value 'image' ($script:Project + '-' + $service.Name))
        $inspect = Docker @('image', 'inspect', '--format', '{{.Id}}', $image) -QuietFailure
        $path = Join-Path $script:Root ('.finassist-state/image-' + $service.Name + '.json')
        Assert-RealDirectory $path
        $previous = $null
        if (Test-Path -LiteralPath $path) { try { $previous = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json } catch { $previous = $null } }
        if ($inspect.Code -ne 0 -or -not $previous -or $previous.hash -ne $hash -or $previous.image -ne $inspect.Out.Trim()) { $rebuild = $true }
    }
    return $rebuild
}
function Save-BuildPlan {
    foreach ($service in $script:Fingerprints.Keys) {
        $config = $script:Config.services.$service
        $image = [string](Get-Value $config 'image' ($script:Project + '-' + $service))
        $inspect = Docker @('image', 'inspect', '--format', '{{.Id}}', $image)
        $path = Join-Path $script:Root ('.finassist-state/image-' + $service + '.json')
        Assert-RealDirectory $path
        @{ hash = $script:Fingerprints[$service]; image = $inspect.Out.Trim() } | ConvertTo-Json | Set-Content -LiteralPath $path -Encoding UTF8
    }
}
function Get-ServiceStates {
    $ids = Compose @('ps', '--all', '-q')
    $states = @()
    foreach ($id in @($ids.Out -split '\s+' | Where-Object { $_ })) {
        $value = Docker @('inspect', '--format', '{{index .Config.Labels "com.docker.compose.service"}}|{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}', $id)
        $parts = $value.Out.Trim().Split('|')
        # Stale, stopped services remain preserved as containers. They are not
        # members of the current required dependency graph.
        if ($parts[0] -notin $script:Services) { continue }
        $states += [pscustomobject]@{ Service = $parts[0]; State = $parts[1]; Health = $parts[2] }
    }
    return $states
}
function Wait-Application {
    $deadline = (Get-Date).AddSeconds($script:ReadyTimeout)
    do {
        $states = @(Get-ServiceStates)
        foreach ($state in $states) {
            if ($state.State -in 'exited', 'dead' -or $state.Health -eq 'unhealthy') { throw "Service $($state.Service) failed: $($state.State)/$($state.Health)." }
        }
        $present = @($states | ForEach-Object { $_.Service })
        $missing = @($script:Services | Where-Object { $_ -notin $present })
        $notHealthy = @($states | Where-Object { $_.State -ne 'running' -or $_.Health -notin 'healthy', 'none' })
        $backend = Invoke-Http $script:ReadinessURL
        $frontend = Invoke-Http ($script:FrontendURL + '/health')
        if (-not $missing.Count -and -not $notHealthy.Count -and $backend -and $frontend) {
            $ready = $backend.Content | ConvertFrom-Json
            if ($ready.status -eq 'ready' -and @($ready.services.PSObject.Properties | Where-Object { $_.Value.status -ne 'up' }).Count -eq 0) {
                # The existing backend diagnostic validates container->host URL
                # AND model inventory, without downloading/loading/generating.
                $null = Compose @('exec', '-T', $script:Backend, 'python', '-m', 'app.diagnostics.ollama')
                return
            }
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw 'Application readiness timed out. A running container alone is not sufficient; inspect the service logs.'
}
function Capture-Logs {
    if (-not $script:LogFile) { return }
    foreach ($service in $script:Services) {
        $result = Compose @('logs', '--no-color', '--timestamps', '--tail', '200', $service) -QuietFailure -Timeout 15
        $path = Join-Path $script:Root ('logs/' + $service + '-' + $script:RunId + '.log')
        Assert-RealDirectory $path
        (Protect-Text ($result.Out + $result.Err)) | Set-Content -LiteralPath $path -Encoding UTF8
    }
}
function Show-Status {
    $states = @(Get-ServiceStates)
    foreach ($service in $script:Config.services.PSObject.Properties) {
        $found = @($states | Where-Object { $_.Service -eq $service.Name })
        $description = if ($found.Count) { ($found | ForEach-Object { $_.State + '/' + $_.Health }) -join ', ' } else { 'not created' }
        $ports = @(@(Get-Value $service.Value 'ports' @()) | ForEach-Object { [string](Get-Value $_ 'host_ip' '*') + ':' + $_.published + '->' + $_.target }) -join ', '
        Write-Log "$($service.Name): $description; published ports: $ports"
    }
    $backend = Invoke-Http $script:ReadinessURL
    $frontend = Invoke-Http ($script:FrontendURL + '/health')
    Write-Log ('Backend readiness: ' + $(if ($backend) { 'responding' } else { 'not ready' }))
    Write-Log ('Frontend health: ' + $(if ($frontend) { 'responding' } else { 'not ready' }))
    Write-Log "Configured Ollama model: $($script:Model); container URL: $($script:OllamaURL)"
}
function Show-Logs([bool]$Follow) {
    do {
        # Poll with --since when following so the manager can redact secrets;
        # never pipe an unfiltered docker log stream to the console.
        $until = (Get-Date).ToUniversalTime().ToString('o')
        $arguments = @('logs', '--no-color', '--timestamps', '--until', $until)
        if (Get-Variable since -Scope Local -ErrorAction SilentlyContinue) { $arguments += @('--since', $since) }
        else { $arguments += @('--tail', '100') }
        $result = Compose $arguments
        if ($result.Out) { Write-Host (Protect-Text $result.Out) }
        if ($result.Err) { Write-Host (Protect-Text $result.Err) }
        $since = $until
        if ($Follow) { Start-Sleep -Seconds 2 }
    } while ($Follow)
}
function Invoke-Main([string[]]$Arguments) {
    $options = Parse-Options $Arguments
    if ($options.Help) { Show-Help; return 0 }
    $script:CommandTimeout = Get-Timeout 'FINASSIST_COMMAND_TIMEOUT' 600
    $script:DockerTimeout = Get-Timeout 'FINASSIST_DOCKER_TIMEOUT' 120
    $script:ReadyTimeout = Get-Timeout 'FINASSIST_READY_TIMEOUT' 300
    $script:StopTimeout = Get-Timeout 'FINASSIST_STOP_TIMEOUT' 20
    if ($options.Action -in 'start', 'restart', 'stop') { Initialize-Logs; Acquire-Lock }
    $null = Get-Command docker.exe -ErrorAction Stop
    $version = Docker @('compose', 'version') -QuietFailure
    if ($version.Code -ne 0) { throw 'Docker Compose v2 is required. Install/update Docker Desktop.' }
    Load-Configuration ($options.Action -notin 'stop', 'logs')
    Ensure-Docker ($options.Action -in 'start', 'restart')
    $null = @(Get-OwnedContainers) # fail closed on a project-name collision
    switch ($options.Action) {
        'status' { Show-Status; return 0 }
        'logs' { Show-Logs $options.Follow; return 0 }
        'stop' { Stop-Project; return 0 }
    }
    Write-Log ('Discovered Compose services: ' + ($script:Services -join ', '))
    Write-Log 'Backend and frontend are Docker-managed; host Python/Node/npm are not runtime prerequisites.'
    Ensure-Ollama # validate shared model before disrupting a working project
    $rebuild = Get-BuildPlan $options.Build
    Stop-Project
    Assert-FreePorts
    if ($options.Clean) { Remove-SafeCaches $options.Deep }
    Write-Log $(if ($rebuild) { 'Building missing/changed/requested images (Docker layer cache retained).' } else { 'Build inputs and image IDs unchanged; reusing images.' })
    $arguments = @('up', '-d', '--wait', '--wait-timeout', [string]$script:ReadyTimeout)
    $arguments += $(if ($rebuild) { '--build' } else { '--no-build' })
    # Compose enforces the real depends_on/healthcheck graph and runs the
    # existing Alembic command; no services or migrations are invented here.
    $result = Compose $arguments -Timeout ([Math]::Max($script:CommandTimeout, $script:ReadyTimeout + 30))
    if ($result.Out) { Write-Log $result.Out.Trim() }
    if ($result.Err) { Write-Log $result.Err.Trim() }
    Wait-Application
    Save-BuildPlan
    Capture-Logs
    foreach ($state in @(Get-ServiceStates)) { Write-Log "$($state.Service): $($state.State)/$($state.Health)" 'OK' }
    Write-Log 'FINASSIST AI READY' 'OK'
    Write-Log "Frontend: $($script:FrontendURL)"
    Write-Log "Backend: $($script:BackendURL); API Docs: $($script:BackendURL)/docs"
    Write-Log "Ollama: $($script:OllamaURL); model: $($script:Model)"
    Write-Log "Logs: $($script:Root)\logs (startup, errors, and one file per Compose service)"
    return 0
}

if (-not $LibraryOnly) {
    $code = 1
    try { $code = Invoke-Main $args }
    catch {
        Write-Log $_.Exception.Message 'ERROR'
        if ($script:LogFile -and $script:Services.Count) { try { Capture-Logs } catch { Write-Log 'Could not capture container logs.' 'WARN' } }
        Write-Log 'Not ready. Partial containers remain under Docker supervision for diagnosis. Use --status, --logs, or --stop. Volumes and shared Ollama were preserved.' 'WARN'
    } finally {
        # Also runs on Ctrl+C. No stale PID files or orphan log-follow children.
        if ($script:Lock) { $script:Lock.Dispose() }
    }
    exit $code
}
