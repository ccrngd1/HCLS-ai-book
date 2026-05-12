$path = "C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.02-patient-no-show-pattern-detection.md"
$c = Get-Content -Raw $path
$em = [regex]::Matches($c, [char]0x2014).Count
$en = [regex]::Matches($c, [char]0x2013).Count
Write-Host "recipe em-dash: $em"
Write-Host "recipe en-dash: $en"

$refPath = "C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter01.01-insurance-card-scanning.md"
$r = Get-Content -Raw $refPath
$rem = [regex]::Matches($r, [char]0x2014).Count
$ren = [regex]::Matches($r, [char]0x2013).Count
Write-Host "ch1.1 em-dash: $rem"
Write-Host "ch1.1 en-dash: $ren"

# line numbers for any en-dash
Get-Content $path | Select-String -Pattern ([char]0x2013) | Select-Object -First 10 | ForEach-Object { Write-Host ("line " + $_.LineNumber + ": " + $_.Line.Substring(0, [Math]::Min(120, $_.Line.Length))) }
