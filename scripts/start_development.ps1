<#
.SYNOPSIS
    Start the Video Agent Studio backend and frontend.

.DESCRIPTION
    This script does not switch branches. It starts the services only when
    the current branch is exactly "development".
#>

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$currentBranch = (& git -C $repoRoot branch --show-current).Trim()

if ($LASTEXITCODE -ne 0) {
    Write-Error "Could not read the current Git branch. Run this script inside the video_agent repository."
    exit 1
}

if ($currentBranch -ne "development") {
    Write-Host "Current branch is '$currentBranch'. Please manually switch to the development branch and run this script again." -ForegroundColor Yellow
    exit 1
}

$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$npmPath = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source

if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Error "Python environment not found: $pythonPath"
    exit 1
}

if ([string]::IsNullOrWhiteSpace($npmPath)) {
    Write-Error "npm.cmd was not found. Install Node.js and make sure npm is on PATH."
    exit 1
}

$frontendDir = Join-Path $repoRoot "studio-ui"
if (-not (Test-Path -LiteralPath (Join-Path $frontendDir "package.json"))) {
    Write-Error "Frontend project not found: $frontendDir\package.json"
    exit 1
}

Write-Host "Starting Video Agent Studio on the development branch..." -ForegroundColor Cyan

$backend = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList @("run_studio.py") `
    -WorkingDirectory $repoRoot `
    -PassThru

$frontend = Start-Process `
    -FilePath $npmPath `
    -ArgumentList @("run", "dev") `
    -WorkingDirectory $frontendDir `
    -PassThru

Write-Host "Backend started (PID $($backend.Id)): http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "Frontend started (PID $($frontend.Id)): http://127.0.0.1:5173" -ForegroundColor Green
Write-Host "Stop the two spawned processes when you are finished." -ForegroundColor DarkGray

