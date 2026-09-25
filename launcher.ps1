$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

$configFile = Join-Path $ScriptDir 'config.json'
if (-not (Test-Path $configFile)) {
    Write-Host 'config.json missing! Generating default...' -ForegroundColor Yellow
    $defaultConfig = @{
        Global = @{
            ApiKey = ''
            Session = 'deziree'
            Modal = 'enabled'
            Memory = 'enabled'
            AlphaCoreInstruction = 'enabled'
            AutonomousControl = 'disabled'
        }
        'main.py' = @{
            AudioMode = 'half'
            VisionMode = 'continuous'
            VoiceOutput = 'enabled'
            Voice = 'Leda'
            InputMode = 'both'
            Tools = 'enabled'
            MCP = 'disabled'
            Proactivity = 'enabled'
            Resolution = 'medium'
            ChunkSize = '1024'
            TriggerTokens = '104857'
            TargetTokens = '52428'
            FileSystem = 'enabled'
        }
    }
    $defaultConfig | ConvertTo-Json -Depth 10 | Set-Content $configFile
}

$configRaw = Get-Content $configFile -Raw | ConvertFrom-Json
# Convert PSCustomObject to Hashtable so the menu script can mutate it
$config = @{}
foreach ($k in $configRaw.psobject.properties.name) {
    $config[$k] = @{}
    foreach ($subK in $configRaw.$k.psobject.properties.name) {
        $config[$k][$subK] = $configRaw.$k.$subK
    }
}

$envHasKey = $false
$envFile = Join-Path $ScriptDir '.env'
if (Test-Path $envFile) {
    $envContent = Get-Content $envFile -Raw
    if ($envContent -match 'GOOGLE_API_KEY=|GEMINI_API_KEY=') {
        $envHasKey = $true
    }
}

if (-not $envHasKey -and [string]::IsNullOrWhiteSpace($config.Global.ApiKey)) {
    $config.Global.ApiKey = Read-Host 'Enter Gemini API Key (Required for first run)'
    $config | ConvertTo-Json -Depth 10 | Set-Content $configFile
}

Clear-Host
Write-Host '========================================' -ForegroundColor Cyan
Write-Host '             AlphaLive                  ' -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan
Write-Host ''

# --- Select Script to Run ---
$selectedScript = 'gui.py'
$scriptDone = $false
while (-not $scriptDone) {
    Write-Host 'Select Boot Mode:' -ForegroundColor Green
    Write-Host '[0] GUI              (AlphaLive Control Interface - RECOMMENDED)' -ForegroundColor Cyan
    Write-Host '[1] main.py          (Alpha Core - Console)' -ForegroundColor Green
    Write-Host ''
    Write-Host 'Press 0 or 1 (Enter = GUI): ' -ForegroundColor Yellow -NoNewline
    
    $key = [console]::ReadKey($true)
    if ($key.KeyChar -eq '0' -or $key.Key -eq 'Enter') { $selectedScript = 'gui.py'; $scriptDone = $true }
    elseif ($key.KeyChar -eq '1') { $selectedScript = 'main.py'; $scriptDone = $true }
    Clear-Host
    Write-Host '========================================' -ForegroundColor Cyan
    Write-Host '             AlphaLive                  ' -ForegroundColor Cyan
    Write-Host '========================================' -ForegroundColor Cyan
    Write-Host ''
}

Write-Host "Engine Selected: $selectedScript" -ForegroundColor Green
Write-Host ''

$configEntered = $false
$timeout = 5
while ($timeout -gt 0) {
    Write-Host "`rStarting AlphaLive in $timeout seconds... Press any key to enter Configuration." -NoNewline -ForegroundColor Yellow
    $start = Get-Date
    while ((Get-Date) - $start -lt [TimeSpan]::FromSeconds(1)) {
        if ([console]::KeyAvailable) {
            $key = [console]::ReadKey($true)
            $configEntered = $true
            break
        }
        Start-Sleep -Milliseconds 50
    }
    if ($configEntered) { break }
    $timeout--
}
Write-Host "`r                                                                                          `r" -NoNewline

function Show-Menu {
    param($title, $props, $obj)
    $done = $false
    while (-not $done) {
        Clear-Host
        Write-Host '========================================' -ForegroundColor Green
        Write-Host "         $title" -ForegroundColor Green
        Write-Host '========================================' -ForegroundColor Green
        Write-Host ''
        $i = 1
        foreach ($p in $props) {
            $val = $obj.$p
            Write-Host "[$i] $p : $val" -ForegroundColor Green
            $i++
        }
        Write-Host '[0] Back' -ForegroundColor Green
        Write-Host ''
        $choice = Read-Host 'Enter number'
        
        if ($choice -eq '0' -or $choice -eq '') {
            $done = $true
        } else {
            $idx = [int]$choice - 1
            if ($idx -ge 0 -and $idx -lt $props.Count) {
                $p = $props[$idx]
                $currentVal = $obj.$p
                $booleanFields = @('Modal','Memory','AlphaCoreInstruction','AutonomousControl','VoiceOutput','Tools','FileSystem','MCP','Proactivity','Playwright','DesktopControl')
                if ($booleanFields -contains $p) {
                    Write-Host '[1] enabled' -ForegroundColor Cyan
                    Write-Host '[2] disabled' -ForegroundColor Cyan
                    $toggle = Read-Host "Select value for $p (Current: $currentVal)"
                    if ($toggle -eq '1') { $obj.$p = 'enabled' }
                    elseif ($toggle -eq '2') { $obj.$p = 'disabled' }
                } elseif ($p -eq 'Headless') {
                    Write-Host '[1] false' -ForegroundColor Cyan
                    Write-Host '[2] true' -ForegroundColor Cyan
                    $toggle = Read-Host "Select value for $p (Current: $currentVal)"
                    if ($toggle -eq '1') { $obj.$p = 'false' }
                    elseif ($toggle -eq '2') { $obj.$p = 'true' }
                } else {
                    $newVal = Read-Host "Enter new value for $p (Current: $currentVal)"
                    if (-not [string]::IsNullOrWhiteSpace($newVal)) {
                        $obj.$p = $newVal
                    }
                }
            }
        }
    }
}

if ($configEntered) {
    $mainDone = $false
    while (-not $mainDone) {
        Clear-Host
        Write-Host '========================================' -ForegroundColor Green
        Write-Host '      AlphaLive Master Configuration    ' -ForegroundColor Green
        Write-Host '========================================' -ForegroundColor Green
        Write-Host ''
        Write-Host '[1] Global Settings' -ForegroundColor Green
        Write-Host '[2] main.py Settings' -ForegroundColor Green
        Write-Host '[0] Save & Exit' -ForegroundColor Green
        Write-Host ''
        $choice = Read-Host 'Enter number'
        if ($choice -eq '0' -or $choice -eq '') {
            $mainDone = $true
        } elseif ($choice -eq '1') {
            $props = @('ApiKey', 'Session', 'Modal', 'Memory', 'AlphaCoreInstruction', 'AutonomousControl')
            Show-Menu 'Global Settings' $props $config.Global
        } elseif ($choice -eq '2') {
            $props = @('AudioMode', 'VisionMode', 'VoiceOutput', 'Voice', 'InputMode', 'DesktopControl', 'FileSystem', 'Proactivity', 'ThinkingLevel', 'Resolution', 'ChunkSize', 'TriggerTokens', 'TargetTokens')
            Show-Menu 'main.py Settings' $props $config.'main.py'
        }
    }
    # Save config
    $config | ConvertTo-Json -Depth 10 | Set-Content $configFile
}

Clear-Host
$Host.UI.RawUI.WindowTitle = 'AlphaCore System Launcher'

Write-Host '------------------------------------------------' -ForegroundColor Green
Write-Host 'BOOTING ALPHALIVE KERNEL...' -ForegroundColor Green
Write-Host "Engine: $selectedScript | Session: $($config.Global.Session) | Modal Proxy: $($config.Global.Modal)" -ForegroundColor Green
Write-Host '------------------------------------------------' -ForegroundColor Green
Write-Host ''

$wsUrl = 'off'

if ($config.Global.Modal -eq 'enabled' -or $config.Global.Modal -eq 'true') {
    Write-Host '[System] Compiling and deploying cloud architecture to Modal...'
    $env:PYTHONIOENCODING = "utf-8"
    modal deploy modalmode.py *>$null
    if ($config.Global.Memory -eq 'enabled') {
        Write-Host '[System] ChromaDB Vector Memory Online.'
    }
    Write-Host '[System] Routing through Modal Cloud Proxy...'
    $wsUrl = 'wss://josh64perry--alphalive-proxy-fastapi-app.modal.run/ws'
} else {
    if ($config.Global.Memory -eq 'enabled') {
        Write-Host '[System] ChromaDB Vector Memory Online.'
    }
    Write-Host '[System] Direct SDK connection active.'
    Write-Host ''
}

if (Test-Path "$ScriptDir\.venv\Scripts\Activate.ps1") {
    . "$ScriptDir\.venv\Scripts\Activate.ps1"
}

$env:ALPHALIVE_CONFIG = $configFile
$env:ALPHALIVE_ENGINE = $selectedScript
$env:ALPHALIVE_WS_URL = $wsUrl
$env:ALPHALIVE_SESSION = [string]$config.Global.Session
if (-not [string]::IsNullOrWhiteSpace($config.Global.ApiKey)) {
    $env:GEMINI_API_KEY = $config.Global.ApiKey
}

& python $selectedScript

Write-Host "`nAlphaLive closed. Press any key to exit..."
$Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown') | Out-Null
