@echo off
:: ============================================================================
:: Lumen Ora — One-click launcher (Windows)
:: ============================================================================
::
:: Usage:
::   Double-click start.bat  — OR —  run from a command prompt inside
::   the prototype\ directory.
::
:: What this script does:
::   1. Starts llama-server (Qwen2.5-7B) on port 8080 if not already running.
::      Waits 8 s for the model to load into RAM.
::   2. Starts the Python inference bridge on port 8765 if not already running.
::      Waits 2 s for FastAPI to come up.
::   3. Launches the context shell in the foreground (this window).
::      The shell itself starts the Rust policy engine via WSL2 automatically.
::
:: Prerequisites:
::   pip install httpx rich   (minimum for the shell)
::   WSL2 with Ubuntu-22.04  (for the policy engine)
::   cargo build              (inside wsl, in prototype/policy-engine/)
:: ============================================================================

setlocal
set PYTHONIOENCODING=utf-8

:: Determine the directory containing this script so relative paths work
:: regardless of where the user launches from.
set "PROTO=%~dp0"
:: Strip trailing backslash
if "%PROTO:~-1%"=="\" set "PROTO=%PROTO:~0,-1%"

:: ── 1. llama-server on port 8080 ─────────────────────────────────────────────
echo.
echo [lumen] Checking llama-server (port 8080)...
netstat -ano | findstr ":8080 " >nul 2>&1
if %errorlevel% equ 0 (
    echo [lumen] llama-server already running.
) else (
    echo [lumen] Starting llama-server...
    start "llama-server" "%PROTO%\inference-bridge\llama-cpp\llama-server.exe" ^
        --model "%PROTO%\inference-bridge\models\qwen2.5-7b-instruct-q4_k_m.gguf" ^
        --ctx-size 4096 ^
        --host 127.0.0.1 ^
        --port 8080
    echo [lumen] Waiting 8 s for the model to load...
    timeout /t 8 /nobreak >nul
)

:: ── 2. Inference bridge on port 8765 ─────────────────────────────────────────
echo [lumen] Checking inference bridge (port 8765)...
netstat -ano | findstr ":8765 " >nul 2>&1
if %errorlevel% equ 0 (
    echo [lumen] Inference bridge already running.
) else (
    echo [lumen] Starting inference bridge...
    start "lumen-bridge" python "%PROTO%\inference-bridge\bridge.py"
    echo [lumen] Waiting 2 s for bridge to come up...
    timeout /t 2 /nobreak >nul
)

:: ── 3. Context shell (foreground) ────────────────────────────────────────────
echo [lumen] Launching context shell...
echo.
python "%PROTO%\context-shell\shell.py"

endlocal
