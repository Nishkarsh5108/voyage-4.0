# Render each tab of submission/round1/demo/index.html to a PNG with headless Edge (for slide figures and for checking the page).
# Usage: powershell -File scripts\demo\screenshots.ps1 [-Width 1600] [-Height 1000]
param([int]$Width = 1600, [int]$Height = 1000, [int]$Scale = 2, [string[]]$Tabs = @('mess', 'mess-canon', 'match', 'rooms', 'acts', 'offer', 'proof'))

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$edge = @("C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", "C:\Program Files\Microsoft\Edge\Application\msedge.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { Write-Output "Edge not found"; exit 1 }
$outDir = Join-Path $root "submission\round1\screens"
New-Item -ItemType Directory -Force $outDir | Out-Null
$base = "file:///" + ((Join-Path $root "submissionound1\demo\index.html") -replace '\\', '/')
$profile = Join-Path $env:TEMP "edge_headless_canon"
foreach ($t in $Tabs) {
    $out = Join-Path $outDir "$t.png"
    Remove-Item $out -ErrorAction SilentlyContinue
    $budget = if ($t -eq 'match') { 15000 } else { 5000 }   # the map tab waits for tiles
    $args = @("--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=$Width,$Height", "--force-device-scale-factor=$Scale", "--virtual-time-budget=$budget",
              "--user-data-dir=$profile", "--screenshot=$out", "$base#$t")
    Start-Process -FilePath $edge -ArgumentList $args -Wait -WindowStyle Hidden
    if (Test-Path $out) { Write-Output ("{0}: {1:N0} bytes" -f $t, (Get-Item $out).Length) } else { Write-Output ("{0}: no screenshot" -f $t) }
}
