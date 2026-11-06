# Disaster Commander Edge - local development launcher for Windows PowerShell.
#
# Usage (from the repo root):
#   .\scripts\dev.ps1                 # create .venv if needed, install deps, start the server
#   .\scripts\dev.ps1 -SkipInstall    # skip pip install (faster restarts)
#
# If execution policy blocks the script:
#   powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1
#
# Seeding: set DCE_SEED_PASSWORD in the current shell before running, for one run only:
#   $env:DCE_SEED_PASSWORD = '<dev password>'
# The password is passed through the process environment and is never written to disk.
# Clear it afterwards with: Remove-Item Env:DCE_SEED_PASSWORD
#
# Sandbox: if Docker is reachable, DCE_SANDBOX_RUNNER defaults to docker. If not, it defaults to
# local, which is NOT isolated. Local mode is for development on trusted code only.

[CmdletBinding()]
param(
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$BackendDir = Join-Path $RepoRoot 'backend'
$VenvDir    = Join-Path $BackendDir '.venv'
$VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
$Requirements = Join-Path $BackendDir 'requirements.txt'
$Url        = 'http://127.0.0.1:8000'

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

# --- 1. Python and virtual environment ------------------------------------
if (-not (Test-Path $VenvPython)) {
    Write-Step 'Creating backend\.venv'
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & py -3.12 -m venv $VenvDir
    } else {
        $python = Get-Command python -ErrorAction Stop
        & $python.Source -m venv $VenvDir
    }
    if (-not (Test-Path $VenvPython)) { throw "Virtual environment was not created at $VenvDir." }
} else {
    Write-Step 'Using existing backend\.venv'
}

# --- 2. Dependencies --------------------------------------------------------
if ($SkipInstall) {
    Write-Step 'Skipping dependency install (-SkipInstall)'
} else {
    Write-Step 'Installing backend requirements'
    if (-not (Test-Path $Requirements)) { throw "Missing $Requirements." }
    & $VenvPython -m pip install --upgrade pip --quiet
    & $VenvPython -m pip install -r $Requirements
}

# --- 3. Sandbox runner selection -----------------------------------------
$dockerOk = $false
try {
    & docker info *> $null
    $dockerOk = ($LASTEXITCODE -eq 0)
} catch {
    $dockerOk = $false
}

if (-not $env:DCE_SANDBOX_RUNNER) {
    if ($dockerOk) {
        $env:DCE_SANDBOX_RUNNER = 'docker'
    } else {
        $env:DCE_SANDBOX_RUNNER = 'local'
    }
}

Write-Step "Sandbox runner: $($env:DCE_SANDBOX_RUNNER)"
if ($env:DCE_SANDBOX_RUNNER -eq 'local') {
    Write-Warning 'LOCAL sandbox mode is NOT isolated. Generated code runs as your Windows user. Use only for development with trusted inputs. Production must use docker.'
}
if ($env:DCE_SANDBOX_RUNNER -eq 'docker' -and -not $dockerOk) {
    Write-Warning 'DCE_SANDBOX_RUNNER=docker but "docker info" failed. Agent tasks will fail until Docker is running.'
}

if (-not $env:DCE_ENV) { $env:DCE_ENV = 'development' }

# --- 4. Seed (only when the password is in the environment) ----------------
Push-Location $BackendDir
try {
    if ($env:DCE_SEED_PASSWORD) {
        Write-Step 'Seeding development accounts (DCE_SEED_PASSWORD is set)'
        & $VenvPython -m app.seed
        if ($LASTEXITCODE -ne 0) { throw "Seeding failed with exit code $LASTEXITCODE." }
    } else {
        Write-Step 'Skipping seed (set DCE_SEED_PASSWORD in this shell to seed the demo accounts)'
    }

    # --- 5. Start the server ----------------------------------------------
    Write-Step "Starting uvicorn on $Url (Ctrl+C to stop)"
    Write-Host "Open: $Url" -ForegroundColor Green
    & $VenvPython -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
} finally {
    Pop-Location
}
