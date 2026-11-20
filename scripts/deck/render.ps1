# Export every slide of a Round 1 deck to PNG with PowerPoint (for a visual check), and optionally to PDF. Needs PowerPoint installed.
# Usage: powershell -File scripts\deck\render.ps1                                   (Canon_Round1.pptx -> submission\round1\qa)
#        powershell -File scripts\deck\render.ps1 -Deck Canon_Round1_v3.pptx -Out qa_v3 -Pdf
# -Deck and -Out are relative to submission\round1 unless absolute. -Pdf also writes <deck>.pdf next to the deck.
param([string]$Deck = "Canon_Round1.pptx", [string]$Out = "qa", [int]$Width = 1600, [int]$Height = 900, [switch]$Pdf)
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$r1 = Join-Path $root "submission\round1"
if (-not [System.IO.Path]::IsPathRooted($Deck)) { $Deck = Join-Path $r1 $Deck }
if (-not [System.IO.Path]::IsPathRooted($Out)) { $Out = Join-Path $r1 $Out }
New-Item -ItemType Directory -Force $Out | Out-Null
Get-ChildItem $Out -Filter *.PNG -ErrorAction SilentlyContinue | Remove-Item
$pp = New-Object -ComObject PowerPoint.Application
$p = $pp.Presentations.Open($Deck, $true, $false, $false)
$p.Export($Out, "PNG", $Width, $Height)
if ($Pdf) { $p.SaveAs([System.IO.Path]::ChangeExtension($Deck, ".pdf"), 32) }   # 32 = ppSaveAsPDF
$p.Close()
$pp.Quit()
Get-ChildItem $Out | ForEach-Object { Write-Output ("{0}  {1:N0} bytes" -f $_.Name, $_.Length) }
