$content = Get-Content -Raw 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.06-healthcare-fraud-waste-abuse-detection.md'
$emDash = [char]0x2014
$enDash = [char]0x2013
$emCount = ([regex]::Matches($content, $emDash)).Count
$enCount = ([regex]::Matches($content, $enDash)).Count
Write-Output "EmDashes: $emCount"
Write-Output "EnDashes: $enCount"
