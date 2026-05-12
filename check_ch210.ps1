$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter02.10-multi-modal-clinical-reasoning.md'
$content = Get-Content -Raw -Path $path -Encoding UTF8
$em = [char]0x2014
$en = [char]0x2013
$emCount = ([regex]::Matches($content, [regex]::Escape($em))).Count
$enCount = ([regex]::Matches($content, [regex]::Escape($en))).Count
Write-Host "em-dash count: $emCount"
Write-Host "en-dash count: $enCount"
