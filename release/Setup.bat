@echo off
title AlphaLive Setup
cd /d "%~dp0"
set "SETUP_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText('%~f0'); Invoke-Expression $s.Substring($s.IndexOf('##PS'+'##')+6)"
exit /b %ERRORLEVEL%
##PS##
$ErrorActionPreference = "Stop"
$WorkspaceDir = $env:SETUP_DIR.TrimEnd('\')
Set-Location $WorkspaceDir

Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "  AlphaLive // Setup" -ForegroundColor Cyan
Write-Host "==============================================================" -ForegroundColor Cyan
Write-Host "[*] Directory: $WorkspaceDir" -ForegroundColor Gray
Write-Host ""

# ---- 1. Python (install automatically if missing) ----
function Find-Python {
    $c = Get-Command python -All -ErrorAction SilentlyContinue | Where-Object { $_.Source -and $_.Source -notmatch 'WindowsApps' }
    foreach ($x in $c) { return @($x.Source) }
    if (Get-Command py -ErrorAction SilentlyContinue) { return @("py", "-3") }
    return $null
}

$Py = Find-Python
if (-not $Py) {
    Write-Host "[*] Python not found. Installing Python 3.11 automatically..." -ForegroundColor Cyan
    $Installer = Join-Path $env:TEMP "python-3.11.9-amd64.exe"
    try {
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe" -OutFile $Installer -UseBasicParsing
        Start-Process -FilePath $Installer -ArgumentList "/quiet","InstallAllUsers=0","PrependPath=1","Include_pip=1","Include_test=0","Include_launcher=0" -Wait
        Remove-Item $Installer -Force -ErrorAction SilentlyContinue
    } catch {
        Write-Host "[*] Direct download failed, trying winget..." -ForegroundColor Yellow
        try { winget install --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements } catch {}
    }
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User") + ";" + $env:Path
    $Default = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
    if (Test-Path $Default) { $Py = @($Default) } else { $Py = Find-Python }
}
if (-not $Py) {
    Write-Host "[ERROR] Automatic Python install failed. Install Python 3.10+ from https://www.python.org/downloads/ (tick 'Add Python to PATH') and re-run." -ForegroundColor Red
    Read-Host "Press Enter to close"; exit 1
}
$PyExe = $Py[0]; $PyArgs = @(); if ($Py.Count -gt 1) { $PyArgs = $Py[1..($Py.Count-1)] }
Write-Host "[OK] Python: $($Py -join ' ')" -ForegroundColor Green
& $PyExe @PyArgs --version

# ---- 2. Virtual environment ----
$Venv = Join-Path $WorkspaceDir ".venv\Scripts\python.exe"
if (-not (Test-Path $Venv)) {
    Write-Host "[*] Creating virtual environment (.venv)..." -ForegroundColor Cyan
    & $PyExe @PyArgs -m venv (Join-Path $WorkspaceDir ".venv")
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Failed to create .venv" -ForegroundColor Red; Read-Host "Press Enter to close"; exit 1 }
}

# ---- 3. Dependencies ----
Write-Host "[*] Installing dependencies (1-3 minutes)..." -ForegroundColor Cyan
& $Venv -m pip install --upgrade pip --quiet
$Req = Join-Path $WorkspaceDir "requirements.txt"
if (Test-Path $Req) { & $Venv -m pip install -r $Req } else { $LASTEXITCODE = 1 }
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] Retrying core packages..." -ForegroundColor Yellow
    & $Venv -m pip install PyQt6 pyqtgraph google-genai mss pyautogui pillow requests aiohttp psutil pygame SpeechRecognition pywin32
}

# ---- 4. Config + API key ----
$Cfg = Join-Path $WorkspaceDir "config.json"
$data = $null
if (Test-Path $Cfg) { try { $data = Get-Content $Cfg -Raw | ConvertFrom-Json } catch {} }
if (-not $data) { $data = [pscustomobject]@{} }
if (-not $data.Global) { $data | Add-Member -NotePropertyName Global -NotePropertyValue ([pscustomobject]@{ ActiveBackend="gemini"; ActiveVoice="leda"; DesktopControl="enabled"; AudioMode="half"; Mood="default"; DisplayMonitorIndex=0 }) -Force }

if ($data.Global.ApiKey) {
    Write-Host "[OK] API key already configured." -ForegroundColor Green
} else {
    $Url = "https://aistudio.google.com/apikey"
    $esc = [char]27
    Write-Host ""
    Write-Host "=== Gemini API Key ===" -ForegroundColor Cyan
    Write-Host "Get a free key here (Ctrl+Click): " -NoNewline
    Write-Host "$esc]8;;$Url$esc\$Url$esc]8;;$esc\" -ForegroundColor Yellow
    $open = Read-Host "Open it in your browser now? (Y/N, default Y)"
    if ($open -eq "" -or $open -match "^[Yy]") { Start-Process $Url }
    $key = (Read-Host "Paste your API key (or press Enter to skip)").Trim()
    if ($key) {
        $data.Global | Add-Member -NotePropertyName ApiKey -NotePropertyValue $key -Force
        Write-Host "[OK] API key saved." -ForegroundColor Green
    } else {
        Write-Host "[INFO] Skipped. Add it later in the SETTINGS tab." -ForegroundColor Gray
    }
}
$data | ConvertTo-Json -Depth 10 | Set-Content $Cfg -Encoding utf8

# ---- 4b. Modal login (optional) ----
if (Test-Path (Join-Path $env:USERPROFILE ".modal.toml")) {
    Write-Host "[OK] Modal already configured." -ForegroundColor Green
} else {
    Write-Host ""
    $m = Read-Host "Set up Modal cloud GPU now? Runs 'modal setup' (Y/N, default N)"
    if ($m -match "^[Yy]") { & $Venv -m modal setup } else { Write-Host "[INFO] Skipped. Run '.venv\Scripts\python.exe -m modal setup' later." -ForegroundColor Gray }
}

# ---- 4c. Modal secrets (optional) ----
if (Test-Path (Join-Path $env:USERPROFILE ".modal.toml")) {
    $h = Read-Host "Create Modal secret 'huggingface-secret' with your HF_TOKEN? (Y/N, default N)"
    if ($h -match "^[Yy]") {
        $hfUrl = "https://huggingface.co/settings/tokens"
        $e = [char]27
        Write-Host "Get a token here (Ctrl+Click): " -NoNewline
        Write-Host "$e]8;;$hfUrl$e\$hfUrl$e]8;;$e\" -ForegroundColor Yellow
        $sec = Read-Host "Paste your Hugging Face token (hf_...)" -AsSecureString
        $hf = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
        if ($hf) { & $Venv -m modal secret create huggingface-secret "HF_TOKEN=$hf" --force; $hf = $null }
    }
    if ($data.Global.ApiKey) {
        $g = Read-Host "Create Modal secret 'gemini-secret' with your Gemini API key? (Y/N, default N)"
        if ($g -match "^[Yy]") { & $Venv -m modal secret create gemini-secret "GEMINI_API_KEY=$($data.Global.ApiKey)" --force }
    }
}

# ---- 5. Desktop shortcut ----
try {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) "AlphaLive.lnk"))
    $sc.TargetPath = Join-Path $WorkspaceDir "start.bat"
    $sc.WorkingDirectory = $WorkspaceDir
    $ico = Join-Path $WorkspaceDir "alphalive.ico"
    if (Test-Path $ico) { $sc.IconLocation = $ico }
    $sc.Save()
    Write-Host "[OK] Desktop shortcut created." -ForegroundColor Green
} catch { Write-Host "[INFO] Shortcut skipped: $_" -ForegroundColor Gray }

Write-Host ""
Write-Host "[SUCCESS] Setup complete. Launch with the desktop shortcut or start.bat." -ForegroundColor Green
$l = Read-Host "Launch AlphaLive now? (Y/N, default Y)"
if ($l -eq "" -or $l -match "^[Yy]") { Start-Process -FilePath (Join-Path $WorkspaceDir "start.bat") -WorkingDirectory $WorkspaceDir }
