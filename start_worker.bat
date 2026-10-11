@echo off
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" worker_main.py --aster-worker %*
) else if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" worker_main.py --aster-worker %*
) else (
    start "" python worker_main.py --aster-worker %* 2>nul || start "" python worker_main.py --aster-worker %*
)
exit /b 0
