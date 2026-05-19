@echo off
REM ============================================================
REM  Lumen Ora - Top-level installer (Windows)
REM
REM  This is the friendly front door. It checks PowerShell,
REM  unblocks the setup script, and hands off to prototype\setup.ps1
REM  which does the real work (prereqs -> deps -> WSL build -> models).
REM ============================================================

setlocal enabledelayedexpansion

echo.
echo ============================================================
echo   Lumen Ora Installer
echo   Local AI assistant with a Rust policy gate
echo ============================================================
echo.

REM -- Verify we're being run from the repo root --
if not exist "%~dp0prototype\setup.ps1" (
    echo [ERROR] Could not find prototype\setup.ps1
    echo Run install.bat from the repository root.
    exit /b 1
)

REM -- Verify PowerShell is available --
where powershell >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PowerShell not found on PATH.
    echo Lumen Ora's installer needs Windows PowerShell 5.1 or later.
    exit /b 1
)

echo This will:
echo   1. Check prerequisites (Python 3.11+, WSL2 Ubuntu-22.04, Git)
echo   2. Install Python dependencies (~500 MB)
echo   3. Build the Rust policy engine in WSL2
echo   4. Optionally download the Qwen2.5 7B model (~4.4 GB) and/or 3B (~2 GB)
echo.

set /p CONFIRM="Continue? [Y/n]: "
if /i "!CONFIRM!"=="n" (
    echo Cancelled.
    exit /b 0
)

echo.
echo Handing off to PowerShell...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0prototype\setup.ps1"
set EXITCODE=%ERRORLEVEL%

if %EXITCODE% NEQ 0 (
    echo.
    echo [FAIL] Installer exited with code %EXITCODE%.
    echo Re-run the script and read the error output above.
    exit /b %EXITCODE%
)

echo.
echo ============================================================
echo   Install complete.
echo
echo   To start Lumen Ora:    prototype\start.bat
echo   To run the test suite: cd prototype ^&^& python test_e2e.py
echo ============================================================
exit /b 0
