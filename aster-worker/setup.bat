@echo off
echo ===================================================
echo     AlphaLive W2 Worker - Environment Setup
echo ===================================================
echo.

echo [1/3] Creating Python Virtual Environment...
python -m venv .venv
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to create virtual environment. Ensure Python is installed and in your PATH.
    pause
    exit /b 1
)

echo [2/3] Installing Dependencies...
call .venv\Scripts\activate.bat
pip install --upgrade pip
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Failed to install requirements.
    pause
    exit /b 1
)

echo [3/3] Dependencies Installed Successfully!
echo.
echo Would you like to install the W2 Background Service now?
echo This will register 'worker_main.py' to launch automatically at login.
set /p install_service="Install service? (y/n): "

if /i "%install_service%"=="y" (
    echo Installing service...
    powershell -NoProfile -ExecutionPolicy Bypass -File .\install_w2_service.ps1
) else (
    echo Skipping service installation.
    echo You can run it manually at any time by executing: powershell -ExecutionPolicy Bypass -File .\install_w2_service.ps1
)

echo.
echo Setup Complete!
pause
