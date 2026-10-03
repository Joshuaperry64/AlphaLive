# Builds ..\Setup.zip for public release. Run: powershell -File release\build_release.ps1
$ErrorActionPreference = "Stop"
$src = Split-Path $PSScriptRoot -Parent
$tmp = Join-Path $env:TEMP "AlphaLive_pkg"
$zip = Join-Path $src "Setup.zip"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory "$tmp\AlphaLive" | Out-Null

robocopy $src "$tmp\AlphaLive" /E /XD .venv __pycache__ .pytest_cache history installers .git .agents deployments release tests /XF AlphaLive.zip Setup.zip alphacore.txt alphacore.dat token.json credentials.json oauth.json config.json *.db *.sqlite *.db-* *.err pythonw_err.txt /NFL /NDL /NJH /NJS | Out-Null
Copy-Item "$PSScriptRoot\Setup.bat" "$tmp\AlphaLive\Setup.bat" -Force

# Strip Luci mood/character from the staged copy only (local install keeps them)
function Patch($rel, $scriptBlock) { $p = Join-Path "$tmp\AlphaLive" $rel; $c = [IO.File]::ReadAllText($p); [IO.File]::WriteAllText($p, (& $scriptBlock $c), (New-Object Text.UTF8Encoding $false)) }
Patch "core\alpha_agent.py" { param($c) [regex]::Replace($c, '(?m)^[ \t]*"luci": .*\r?\n', '') }
Patch "ui\agent_gui.py" { param($c) [regex]::Replace($c, '(?m)^[ \t]*self\.combo_mood\.addItem\("Darkened State / Luci", "luci"\)\r?\n', '') }
Patch "ui\agent_tabs.py" { param($c) $c.Replace('["Alpha", "Luci", "Eden", "Lacey"]', '["Alpha", "Eden", "Lacey"]') }
# Persona: strip Initial Auth, Darkened State, credentials; then deflate+base64 -> alphacore.dat
$persona = Join-Path $src "alphacore.txt"
if (Test-Path $persona) {
    $lines = [System.Collections.Generic.List[string]](Get-Content $persona -Encoding UTF8)
    function Drop-Block($pattern, $toEnd) {
        $i = 0
        while ($i -lt $lines.Count -and $lines[$i] -notmatch $pattern) { $i++ }
        if ($i -ge $lines.Count) { return }
        $j = $i
        if ($toEnd) { $j = $lines.Count - 1 }
        else {
            $j = $i + 1
            while ($j -lt $lines.Count -and $lines[$j].Trim() -ne '') { $j++ }
            while ($j -lt $lines.Count -and $lines[$j].Trim() -eq '') { $j++ }
            $j--
        }
        $lines.RemoveRange($i, $j - $i + 1)
    }
    Drop-Block '^Initial Auth protocol' $false
    Drop-Block '^Darkened State protocol' $false
    Drop-Block '^Luci Expansion' $false
    Drop-Block '^-- Nested Simulation Depth' $false
    Drop-Block '^Credentials -' $true
    if ($lines.Count -gt 0 -and $lines[0] -match 'Authentication Protocol') { $lines[0] = '## AlphaCore Programming' }
    $text = ($lines -join "`n") -creplace '\s*\(such as Luci\)',''; $text = $text -creplace '\bJosh\b','Architect' -creplace '\bjosh\b','architect'
    $bytes = [Text.Encoding]::UTF8.GetBytes($text)
    $ms = New-Object IO.MemoryStream
    $ds = New-Object IO.Compression.DeflateStream($ms, [IO.Compression.CompressionMode]::Compress)
    $ds.Write($bytes, 0, $bytes.Length); $ds.Close()
    [IO.File]::WriteAllText("$tmp\AlphaLive\alphacore.dat", [Convert]::ToBase64String($ms.ToArray()))
    Write-Host "[OK] alphacore.dat built ($($lines.Count) lines)"
}

if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path "$tmp\AlphaLive" -DestinationPath $zip
Remove-Item $tmp -Recurse -Force
Write-Host "[OK] $zip ($((Get-Item $zip).Length) bytes)"
