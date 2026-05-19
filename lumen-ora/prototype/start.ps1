#Requires -Version 5.1
<#
.SYNOPSIS
    Lumen Ora — One-click launcher (PowerShell)

.DESCRIPTION
    Equivalent of start.bat but using PowerShell idioms.

    What this script does:
      1. Starts llama-server (Qwen2.5-7B) on port 8080 if not already running.
         Waits 8 s for the model to load into RAM.
      2. Starts the Python inference bridge on port 8765 if not already running.
         Waits 2 s for FastAPI to come up.
      3. Launches the context shell in the foreground (this window).
         The shell itself starts the Rust policy engine via WSL2 automatically.

.EXAMPLE
    .\start.ps1

.NOTES
    Prerequisites:
      pip install httpx rich   (minimum for the shell)
      WSL2 with Ubuntu-22.04  (for the policy engine)
      cargo build              (inside wsl, in prototype/policy-engine/)
#>

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'

# Resolve the prototype directory (where this script lives).
$Proto = $PSScriptRoot

function Test-PortListening {
    param([int]$Port)
    $result = Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue 2>$null
    return $result
}

# ── 1. llama-server on port 8080 ───────────────────────────────────────────────
Write-Host ""
Write-Host "[lumen] Checking llama-server (port 8080)..."
if (Test-PortListening -Port 8080) {
    Write-Host "[lumen] llama-server already running."
} else {
    Write-Host "[lumen] Starting llama-server..."
    $llamaExe  = Join-Path $Proto "inference-bridge\llama-cpp\llama-server.exe"
    $llamaModel = Join-Path $Proto "inference-bridge\models\qwen2.5-7b-instruct-q4_k_m.gguf"
    Start-Process -FilePath $llamaExe `
        -ArgumentList "--model `"$llamaModel`" --ctx-size 4096 --host 127.0.0.1 --port 8080" `
        -WindowStyle Normal
    Write-Host "[lumen] Waiting 8 s for the model to load..."
    Start-Sleep -Seconds 8
}

# ── 2. Inference bridge on port 8765 ───────────────────────────────────────────
Write-Host "[lumen] Checking inference bridge (port 8765)..."
if (Test-PortListening -Port 8765) {
    Write-Host "[lumen] Inference bridge already running."
} else {
    Write-Host "[lumen] Starting inference bridge..."
    $bridgeScript = Join-Path $Proto "inference-bridge\bridge.py"
    Start-Process -FilePath "python" `
        -ArgumentList "`"$bridgeScript`"" `
        -WindowStyle Normal
    Write-Host "[lumen] Waiting 2 s for bridge to come up..."
    Start-Sleep -Seconds 2
}

# ── 3. Context shell (foreground) ──────────────────────────────────────────────
Write-Host "[lumen] Launching context shell..."
Write-Host ""
$shellScript = Join-Path $Proto "context-shell\shell.py"
& python $shellScript
