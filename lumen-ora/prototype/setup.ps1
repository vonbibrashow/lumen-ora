#Requires -Version 5.1
<#
.SYNOPSIS
    Lumen Ora — One-shot installer

.DESCRIPTION
    Run once on a fresh machine to set up everything needed to run Lumen Ora.

    Steps:
      1. Check prerequisites (Python 3.11+, WSL2 Ubuntu-22.04, Git)
      2. Install Python dependencies
      3. Build the policy engine in WSL2
      4. Optionally download the Qwen2.5 7B and/or 3B GGUF models
      5. Verify llama-server.exe is present
      6. Print a final status report

.EXAMPLE
    cd prototype
    .\setup.ps1

.NOTES
    Run from the prototype\ directory or from anywhere — uses $PSScriptRoot for all paths.
#>

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
$Proto       = $PSScriptRoot
$BridgeDir   = Join-Path $Proto "inference-bridge"
$ModelsDir   = Join-Path $BridgeDir "models"
$LlamaCppDir = Join-Path $BridgeDir "llama-cpp"
$PolicyDir   = Join-Path $Proto "policy-engine"

$Model7B     = Join-Path $ModelsDir "qwen2.5-7b-instruct-q4_k_m.gguf"
$Model3B     = Join-Path $ModelsDir "qwen2.5-3b-instruct-q4_k_m.gguf"
$LlamaExe    = Join-Path $LlamaCppDir "llama-server.exe"

$Url7B = "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf"
$Url3B = "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf"

# Status tracking for the final report
$StatusPythonDeps   = "UNKNOWN"
$StatusPolicyEngine = "UNKNOWN"
$StatusModel7B      = "UNKNOWN"
$StatusLlamaServer  = "UNKNOWN"

Write-Host ""
Write-Host "============================================"
Write-Host "  Lumen Ora — Setup"
Write-Host "============================================"
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
Write-Host "[1/5] Checking prerequisites..."
Write-Host ""

# Python 3.11+
Write-Host "  Checking Python..."
$pythonOk = $false
try {
    $pyVer = & python --version 2>&1
    if ($pyVer -match "Python (\d+)\.(\d+)") {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 11)) {
            Write-Host "  Python $major.$minor — OK" -ForegroundColor Green
            $pythonOk = $true
        } else {
            Write-Host "  Python $major.$minor is too old. Need 3.11+." -ForegroundColor Red
            Write-Host "  Install from: https://www.python.org/downloads/" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Could not parse Python version: $pyVer" -ForegroundColor Red
        Write-Host "  Install from: https://www.python.org/downloads/" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  Python not found." -ForegroundColor Red
    Write-Host "  Install from: https://www.python.org/downloads/" -ForegroundColor Yellow
}

if (-not $pythonOk) {
    Write-Host ""
    Write-Host "ERROR: Python 3.11+ is required. Install it and re-run setup.ps1." -ForegroundColor Red
    exit 1
}

# WSL2 + Ubuntu-22.04
Write-Host "  Checking WSL2 + Ubuntu-22.04..."
$wslOk = $false
try {
    $wslList = & wsl -l -v 2>&1 | Out-String
    # wsl -l -v output uses UTF-16 on some systems — strip null bytes
    $wslList = $wslList -replace "`0", ""
    if ($wslList -match "Ubuntu-22\.04") {
        Write-Host "  WSL2 Ubuntu-22.04 — OK" -ForegroundColor Green
        $wslOk = $true
    } else {
        Write-Host "  Ubuntu-22.04 not found in WSL." -ForegroundColor Yellow
        Write-Host "  Run: wsl --install -d Ubuntu-22.04" -ForegroundColor Yellow
        Write-Host "  The policy engine requires WSL2. You can still run Lumen Ora without it" -ForegroundColor Yellow
        Write-Host "  but policy enforcement will default to Allow." -ForegroundColor Yellow
    }
} catch {
    Write-Host "  WSL not available: $_" -ForegroundColor Yellow
    Write-Host "  Enable WSL2 and run: wsl --install -d Ubuntu-22.04" -ForegroundColor Yellow
}

# Git
Write-Host "  Checking Git..."
$gitOk = $false
try {
    $gitVer = & git --version 2>&1
    if ($gitVer -match "git version") {
        Write-Host "  $gitVer — OK" -ForegroundColor Green
        $gitOk = $true
    }
} catch {
    Write-Host "  Git not found." -ForegroundColor Yellow
    Write-Host "  Install from: https://git-scm.com/download/win" -ForegroundColor Yellow
}

Write-Host ""

# ---------------------------------------------------------------------------
# 2. Python dependencies
# ---------------------------------------------------------------------------
Write-Host "[2/5] Installing Python dependencies..."
Write-Host ""

$pipPackages = @(
    "httpx", "fastapi", "uvicorn", "sse-starlette", "pydantic",
    "rich", "ddgs", "faster-whisper", "pyttsx3", "sounddevice",
    "soundfile", "keyboard", "pillow"
)
$pipArgs = @("install") + $pipPackages

try {
    Write-Host "  Running: pip install $($pipPackages -join ' ')"
    Write-Host ""
    & pip @pipArgs
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "  Python dependencies installed." -ForegroundColor Green
        $StatusPythonDeps = "OK"
    } else {
        Write-Host ""
        Write-Host "  pip exited with code $LASTEXITCODE. Check errors above." -ForegroundColor Red
        $StatusPythonDeps = "FAILED"
    }
} catch {
    Write-Host "  pip install failed: $_" -ForegroundColor Red
    $StatusPythonDeps = "FAILED"
}

Write-Host ""

# ---------------------------------------------------------------------------
# 3. Build the policy engine in WSL2
# ---------------------------------------------------------------------------
Write-Host "[3/5] Building policy engine in WSL2..."
Write-Host ""

if (-not $wslOk) {
    Write-Host "  Skipping — WSL2 Ubuntu-22.04 not available." -ForegroundColor Yellow
    $StatusPolicyEngine = "SKIPPED (no WSL2)"
} else {
    # Convert Windows path to WSL path:
    # e.g. C:\Users\foo\lumen-ora\prototype\policy-engine
    #  ->  /mnt/c/Users/foo/lumen-ora/prototype/policy-engine
    $protoWsl = "/mnt/" + ($PolicyDir -replace "^([A-Za-z]):", '$1').Substring(0,1).ToLower() +
                "/" + ($PolicyDir -replace "^[A-Za-z]:\\", "" -replace "\\", "/")

    Write-Host "  WSL path: $protoWsl"
    Write-Host "  Running: cargo build (this may take a few minutes on first run)..."
    Write-Host ""

    try {
        & wsl -d Ubuntu-22.04 -- bash -c "cd '$protoWsl' && cargo build 2>&1"
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "  Policy engine built successfully." -ForegroundColor Green
            $StatusPolicyEngine = "OK"
        } else {
            Write-Host ""
            Write-Host "  cargo build failed (exit $LASTEXITCODE). See errors above." -ForegroundColor Red
            Write-Host "  Ensure Rust is installed in WSL: curl https://sh.rustup.rs -sSf | sh" -ForegroundColor Yellow
            $StatusPolicyEngine = "FAILED"
        }
    } catch {
        Write-Host "  WSL build failed: $_" -ForegroundColor Red
        $StatusPolicyEngine = "FAILED"
    }
}

Write-Host ""

# ---------------------------------------------------------------------------
# 4. Download models
# ---------------------------------------------------------------------------
Write-Host "[4/5] Checking models..."
Write-Host ""

if (-not (Test-Path $ModelsDir)) {
    New-Item -ItemType Directory -Path $ModelsDir -Force | Out-Null
}

# 7B model
if (Test-Path $Model7B) {
    Write-Host "  Qwen2.5-7B model found." -ForegroundColor Green
    $StatusModel7B = "OK"
} else {
    Write-Host "  Qwen2.5-7B model not found." -ForegroundColor Yellow
    $answer = Read-Host "  Download Qwen2.5-7B model? (~4.7 GB) [y/N]"
    if ($answer -match "^[Yy]") {
        Write-Host "  Downloading to: $Model7B"
        Write-Host "  This may take 10-30 minutes depending on your connection..."
        try {
            # Prefer curl.exe (ships with Windows 10+) for progress display
            if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
                & curl.exe -L --progress-bar -o $Model7B $Url7B
            } else {
                $ProgressPreference = 'SilentlyContinue'
                Invoke-WebRequest -Uri $Url7B -OutFile $Model7B -UseBasicParsing
                $ProgressPreference = 'Continue'
            }
            if (Test-Path $Model7B) {
                Write-Host "  7B model downloaded." -ForegroundColor Green
                $StatusModel7B = "OK"
            } else {
                Write-Host "  Download appeared to complete but file not found." -ForegroundColor Red
                $StatusModel7B = "NOT DOWNLOADED"
            }
        } catch {
            Write-Host "  Download failed: $_" -ForegroundColor Red
            $StatusModel7B = "NOT DOWNLOADED"
        }
    } else {
        Write-Host "  Skipping 7B model download."
        $StatusModel7B = "NOT DOWNLOADED"
    }
}

# 3B model
if (Test-Path $Model3B) {
    Write-Host "  Qwen2.5-3B model found." -ForegroundColor Green
} else {
    $answer3B = Read-Host "  Also download Qwen2.5-3B (faster, ~2 GB)? [y/N]"
    if ($answer3B -match "^[Yy]") {
        Write-Host "  Downloading 3B model to: $Model3B"
        try {
            if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
                & curl.exe -L --progress-bar -o $Model3B $Url3B
            } else {
                $ProgressPreference = 'SilentlyContinue'
                Invoke-WebRequest -Uri $Url3B -OutFile $Model3B -UseBasicParsing
                $ProgressPreference = 'Continue'
            }
            if (Test-Path $Model3B) {
                Write-Host "  3B model downloaded." -ForegroundColor Green
            } else {
                Write-Host "  3B download appeared to complete but file not found." -ForegroundColor Yellow
            }
        } catch {
            Write-Host "  3B download failed: $_" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  Skipping 3B model download."
    }
}

Write-Host ""

# ---------------------------------------------------------------------------
# 5. Check llama-server binary
# ---------------------------------------------------------------------------
Write-Host "[5/5] Checking llama-server binary..."
Write-Host ""

if (Test-Path $LlamaExe) {
    Write-Host "  llama-server.exe found." -ForegroundColor Green
    $StatusLlamaServer = "OK"
} else {
    Write-Host "  llama-server.exe not found." -ForegroundColor Red
    Write-Host ""
    Write-Host "  Download from: https://github.com/ggerganov/llama.cpp/releases" -ForegroundColor Yellow
    Write-Host "  Look for a Windows release asset (e.g. llama-*-bin-win-avx2-x64.zip)" -ForegroundColor Yellow
    Write-Host "  Extract and place llama-server.exe (and all DLLs) here:" -ForegroundColor Yellow
    Write-Host "    $LlamaCppDir" -ForegroundColor Cyan
    $StatusLlamaServer = "MISSING"
}

Write-Host ""

# ---------------------------------------------------------------------------
# Final status report
# ---------------------------------------------------------------------------
Write-Host "============================================"
Write-Host "  Setup complete!"
Write-Host "============================================"
Write-Host ""
Write-Host "  Python deps   : $StatusPythonDeps"
Write-Host "  Policy engine : $StatusPolicyEngine"
Write-Host "  7B model      : $StatusModel7B"
Write-Host "  llama-server  : $StatusLlamaServer"
Write-Host ""

$allOk = ($StatusPythonDeps -eq "OK") -and
         ($StatusPolicyEngine -eq "OK" -or $StatusPolicyEngine -like "SKIPPED*") -and
         ($StatusModel7B -eq "OK") -and
         ($StatusLlamaServer -eq "OK")

if ($allOk) {
    Write-Host "  Everything looks good!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  To launch:" -ForegroundColor Cyan
    Write-Host "    cd prototype" -ForegroundColor Cyan
    Write-Host "    .\start.ps1" -ForegroundColor Cyan
} else {
    Write-Host "  Some items need attention (see above)." -ForegroundColor Yellow
    Write-Host "  Fix any FAILED or MISSING items, then re-run setup.ps1 or start.ps1." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  To launch once ready:" -ForegroundColor Cyan
    Write-Host "    cd prototype" -ForegroundColor Cyan
    Write-Host "    .\start.ps1" -ForegroundColor Cyan
}

Write-Host ""
