@echo off
setlocal enabledelayedexpansion
title AlphaLive - Main Entrypoint

:: Ensure working directory is the script's directory
cd /d "%~dp0"

echo ===================================================
echo   Starting AlphaLive via main.py entrypoint...
echo ===================================================

:: Check for virtual environment in workspace
if exist ".venv\Scripts\python.exe" (
    echo [System] Activating local virtual environment (.venv)...
    call ".venv\Scripts\activate.bat"
    python core\main.py %*
) else (
    echo [System] Local .venv not found. Attempting system Python...
    where python >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        python core\main.py %*
    ) else (
        where py >nul 2>&1
        if %ERRORLEVEL% equ 0 (
            py -3 core\main.py %*
        ) else (
            echo [Error] Python was not found in PATH!
            pause
            exit /b 1
        )
    )
)

if %ERRORLEVEL% neq 0 (
    echo.
    echo [AlphaLive] Process exited with code %ERRORLEVEL%.
    pause
)
