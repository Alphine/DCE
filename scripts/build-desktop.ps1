# Disaster Commander Edge - Windows desktop installer build (Tauri 2).
#
# Usage (from the repo root, in PowerShell):
#   .\scripts\build-desktop.ps1
#
# Runs `npm run build:desktop` inside the MSVC x64 environment from the installed Visual Studio,
# because link.exe is not on PATH by default. Output:
#   src-tauri\target\release\bundle\nsis\*.exe
#   src-tauri\target\release\bundle\msi\*.msi

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot

$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path $vswhere)) { throw "vswhere.exe not found. Install Visual Studio Build Tools with the C++ workload." }

$vsPath = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsPath) { throw "No Visual Studio installation with the MSVC x64 toolchain was found." }

$vcvars = Join-Path $vsPath 'VC\Auxiliary\Build\vcvars64.bat'
if (-not (Test-Path $vcvars)) { throw "vcvars64.bat not found at $vcvars" }

Push-Location $RepoRoot
try {
    cmd /c "`"$vcvars`" >nul && npm run build:desktop"
    if ($LASTEXITCODE -ne 0) { throw "Desktop build failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
