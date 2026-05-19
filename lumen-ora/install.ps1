#Requires -Version 5.1
<#
.SYNOPSIS
    Lumen Ora - Top-level installer (PowerShell)

.DESCRIPTION
    Friendly wrapper around prototype\setup.ps1. Run this from the
    repository root after `git clone`. Handles execution-policy
    issues and prints a final status report.

.EXAMPLE
    .\install.ps1

.EXAMPLE
    .\install.ps1 -SkipConfirm     # non-interactive

.NOTES
    On Linux/macOS use install.sh instead (coming in Phase 4).
#>

[CmdletBinding()]
param(
    [switch]$SkipConfirm
)

$ErrorActionPreference = 'Stop'

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Lumen Ora Installer" -ForegroundColor Cyan
Write-Host "  Local AI assistant with a Rust policy gate" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$repoRoot = $PSScriptRoot
$setupScript = Join-Path $repoRoot "prototype\setup.ps1"

if (-not (Test-Path $setupScript)) {
    Write-Host "[ERROR] Could not find prototype\setup.ps1" -ForegroundColor Red
    Write-Host "Run install.ps1 from the repository root." -ForegroundColor Red
    exit 1
}

Write-Host "This will:"
Write-Host "  1. Check prerequisites (Python 3.11+, WSL2 Ubuntu-22.04, Git)"
Write-Host "  2. Install Python dependencies (~500 MB)"
Write-Host "  3. Build the Rust policy engine in WSL2"
Write-Host "  4. Optionally download the Qwen2.5 7B model (~4.4 GB) and/or 3B (~2 GB)"
Write-Host ""

if (-not $SkipConfirm) {
    $confirm = Read-Host "Continue? [Y/n]"
    if ($confirm -match '^[nN]') {
        Write-Host "Cancelled."
        exit 0
    }
}

Write-Host ""
Write-Host "Handing off to prototype\setup.ps1..." -ForegroundColor Cyan
Write-Host ""

& $setupScript
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    Write-Host ""
    Write-Host "[FAIL] Installer exited with code $exitCode." -ForegroundColor Red
    Write-Host "Re-run the script and read the error output above." -ForegroundColor Red
    exit $exitCode
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Install complete." -ForegroundColor Green
Write-Host ""
Write-Host "  To start Lumen Ora:    prototype\start.ps1"
Write-Host "  To run the test suite: cd prototype; python test_e2e.py"
Write-Host "============================================================" -ForegroundColor Green
exit 0
