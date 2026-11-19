# Export every slide of the Round 1 deck to PNG with PowerPoint (for a visual check). Needs PowerPoint installed.
# Usage: powershell -File scripts\deck\render.ps1
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$deck = Join-Path $root "submission\round1\Canon_Round1.pptx"
$qa = Join-Path $root "submission\round1\qa"
New-Item -ItemType Directory -Force $qa | Out-Null
Get-ChildItem $qa -Filter *.PNG -ErrorAction SilentlyContinue | Remove-Item
$pp = New-Object -ComObject PowerPoint.Application
$p = $pp.Presentations.Open($deck, $true, $false, $false)
$p.Export($qa, "PNG", 1600, 900)
$p.Close()
$pp.Quit()
Get-ChildItem $qa | ForEach-Object { Write-Output ("{0}  {1:N0} bytes" -f $_.Name, $_.Length) }
