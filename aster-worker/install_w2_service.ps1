$taskName = "AlphaLive_W2_Worker"
$cwd = (Get-Location).Path
$pythonPath = Join-Path $cwd ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonPath)) {
    $pythonPath = "pythonw.exe"
}
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument "main.py --aster-worker" -WorkingDirectory $cwd
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force
Write-Host "W2 Hidden Service successfully installed!"
Write-Host "It will automatically run whenever $env:USERNAME logs in."
Start-Sleep -Seconds 5
