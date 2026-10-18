<#
.SYNOPSIS
  Starts the Foundry Account Intelligence demo in its own terminal window.

.DESCRIPTION
  One command from any terminal:  .\start.ps1
  The server runs in a separate window, so this terminal stays free. The script checks Python and the
  packages, waits until the app answers, reports whether live mode (Azure) is available and opens the browser.

.EXAMPLE
  .\start.ps1                    # server in a new terminal, browser opens
  .\start.ps1 -WithTests         # also opens a second terminal that runs the offline test suite
  .\start.ps1 -Reload            # development: the server restarts when you edit files in app\
  .\start.ps1 -Port 9000 -NoBrowser
  .\start.ps1 -Stop              # stops the terminals and the server started by this script
  .\start.ps1 -Check             # pre-flight before you go on stage: files, Azure sign-in, every model, running app
  .\start.ps1 -Rehearse          # the check plus a timed run of the live demo flow (-Full also runs Trust Lab and Bake-off live)
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [switch]$NoBrowser,
    [switch]$Reload,
    [switch]$WithTests,
    [switch]$Check,
    [switch]$Rehearse,
    [switch]$Full,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$PidFile = Join-Path $Root ".start-pids-$Port.json"   # one record per port, so several instances do not overwrite each other
$Url = "http://127.0.0.1:$Port"
$ShellExe = (Get-Process -Id $PID).Path   # the same PowerShell that runs this script (pwsh or powershell)

function Write-Step($text) { Write-Host "  $text" -ForegroundColor Cyan }
function Write-Ok($text) { Write-Host "  $text" -ForegroundColor Green }
function Write-Warn($text) { Write-Host "  $text" -ForegroundColor Yellow }

function Get-Listeners([int]$p) {
    Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique
}

function Get-AppStatus([int]$p) {
    try { Invoke-RestMethod "http://127.0.0.1:$p/api/status" -TimeoutSec 3 } catch { $null }
}

function Start-Terminal([string]$Title, [string]$Command) {
    # EncodedCommand avoids every quoting problem with paths and arguments.
    $safeRoot = $Root.Replace("'", "''")
    $script = "`$Host.UI.RawUI.WindowTitle = '$Title'; Set-Location -LiteralPath '$safeRoot'; $Command"
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
    Start-Process -FilePath $ShellExe -ArgumentList @('-NoExit', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded) -WorkingDirectory $Root -PassThru
}

function Stop-Tree([int]$id) {
    # Kills the process and everything it started. cmd swallows the error when the process is already gone.
    & cmd.exe /c "taskkill /PID $id /T /F >nul 2>&1"
}

function Get-Workers([int]$parentId) {
    # uvicorn --reload starts the worker through multiprocessing; it can outlive its supervisor.
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "parent_pid=$parentId\b" }
}

function Test-OurServer([int]$id, [int]$p) {
    $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue).CommandLine
    if ($cmd) {
        if ($cmd -match 'app\.main:app') { return $true }
        return ($cmd -match 'multiprocessing\.spawn' -and [bool](Get-AppStatus $p))
    }
    # the process that opened the port is gone: ours only if one of its reload workers still holds the socket
    return [bool](Get-Workers $id) -or [bool](Get-AppStatus $p)
}

function Stop-Server([int]$id) {
    foreach ($worker in @(Get-Workers $id)) { Stop-Tree $worker.ProcessId }
    Stop-Tree $id
}

Write-Host ''
Write-Host '  Foundry Account Intelligence' -ForegroundColor White

# ------------------------------------------------------------------ stop
if ($Stop) {
    $stopped = 0
    if (Test-Path $PidFile) {
        foreach ($recorded in @(Get-Content $PidFile -Raw | ConvertFrom-Json)) {
            if (Get-Process -Id $recorded.pid -ErrorAction SilentlyContinue) {
                Stop-Tree $recorded.pid; $stopped++; Write-Step "closed terminal '$($recorded.title)' (PID $($recorded.pid))"
            }
        }
        Remove-Item $PidFile -Force
    }
    for ($round = 0; $round -lt 6; $round++) {
        $owners = @(Get-Listeners $Port)
        if ($owners.Count -eq 0) { break }
        foreach ($owner in $owners) {
            if (Test-OurServer $owner $Port) { Stop-Server $owner; $stopped++; Write-Step "stopped server process (PID $owner)" }
        }
        Start-Sleep -Milliseconds 500
    }
    $free = @(Get-Listeners $Port).Count -eq 0
    if ($stopped -and $free) { Write-Ok "Stopped. Port $Port is free." }
    elseif ($stopped) { Write-Warn "Stopped the app, but port $Port is still in use by another program." }
    elseif (-not $free) { Write-Warn "Port $Port is used by another program, not by this app. Nothing was stopped." }
    else { Write-Warn "Nothing to stop. The app is not running on port $Port." }
    Write-Host ''
    return
}

# ------------------------------------------------------------------ checks
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { throw 'Python was not found. Install Python 3.12 from https://www.python.org/downloads/ and run this script again.' }
Write-Step "Python: $(& python --version 2>&1)"

& python -c "import fastapi, uvicorn, openpyxl, openai, azure.identity, dotenv" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Step 'Installing the Python packages (first run only)...'
    & python -m pip install -r (Join-Path $Root 'requirements.txt') --quiet --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw 'Installing the packages failed. Run: python -m pip install -r requirements.txt' }
}

if (-not (Test-Path (Join-Path $Root '.env'))) {
    Copy-Item (Join-Path $Root '.env.example') (Join-Path $Root '.env')
    Write-Step 'Created .env from .env.example (edit it to point at your own Foundry resource).'
}

# ------------------------------------------------------------------ pre-flight
if ($Check -or $Rehearse) {
    $preflight = @('-m', 'app.preflight', '--url', $Url)
    if ($Rehearse) { $preflight += '--rehearse' }
    if ($Full) { $preflight += '--full' }
    $env:PYTHONIOENCODING = 'utf-8'
    Push-Location $Root
    try { & python @preflight; $code = $LASTEXITCODE } finally { Pop-Location }
    Write-Host ''
    exit $code
}

# ------------------------------------------------------------------ already running?
$owners = @(Get-Listeners $Port)
if ($owners.Count -gt 0) {
    if (Get-AppStatus $Port) {
        Write-Ok "The app is already running at $Url"
        if (-not $NoBrowser) { Start-Process $Url }
        Write-Host "  Stop it with: .\start.ps1 -Stop$(if ($Port -ne 8765) { " -Port $Port" })"
        Write-Host ''
        return
    }
    $name = (Get-Process -Id $owners[0] -ErrorAction SilentlyContinue).ProcessName
    throw "Port $Port is used by another program ($name, PID $($owners[0])). Choose another port: .\start.ps1 -Port 9000"
}

# ------------------------------------------------------------------ start the terminals
$started = @()
$serverArgs = "app.main:app --host 127.0.0.1 --port $Port" + $(if ($Reload) { ' --reload --reload-dir app' } else { '' })
$serverCmd = "Write-Host 'Foundry demo server on $Url  (Ctrl+C stops it)' -ForegroundColor Cyan; python -m uvicorn $serverArgs"
$server = Start-Terminal -Title 'Foundry demo: server' -Command $serverCmd
$started += [pscustomobject]@{ title = 'server'; pid = $server.Id }
Write-Step "Server terminal opened (PID $($server.Id))"

if ($WithTests) {
    $testCmd = "Write-Host 'Offline test suite' -ForegroundColor Cyan; python -m pytest -q -p no:cacheprovider; Write-Host ''; Write-Host 'Done. Add RUN_LIVE=1 and -m live to include the live tests.' -ForegroundColor DarkGray"
    $tests = Start-Terminal -Title 'Foundry demo: tests' -Command $testCmd
    $started += [pscustomobject]@{ title = 'tests'; pid = $tests.Id }
    Write-Step "Test terminal opened (PID $($tests.Id))"
}
ConvertTo-Json -InputObject @($started) | Set-Content $PidFile -Encoding utf8

# ------------------------------------------------------------------ wait until it answers
Write-Step 'Waiting for the app to answer...'
$status = $null
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline -and -not $status) {
    if (-not (Get-Process -Id $server.Id -ErrorAction SilentlyContinue)) { throw 'The server terminal closed unexpectedly. Run .\start.ps1 again and read the error in the new window.' }
    Start-Sleep -Milliseconds 600
    $status = Get-AppStatus $Port
}
if (-not $status) { throw "The app did not answer within 60 seconds. Check the server terminal for errors." }

Write-Ok "Ready at $Url"
if ($status.live_available) { Write-Ok "Live mode available (Foundry: $($status.endpoint))" }
else { Write-Warn 'Live mode not available, the app runs in offline replay. Run "az login" and restart to use live mode.' }
if (-not $NoBrowser) { Start-Process $Url }
Write-Host "  Stop everything with: .\start.ps1 -Stop$(if ($Port -ne 8765) { " -Port $Port" })"
Write-Host ''

