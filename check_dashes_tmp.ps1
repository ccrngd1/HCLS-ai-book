$content = Get-Content -Raw 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter02.03-clinical-documentation-improvement.md'
$emChar = [char]0x2014
$enChar = [char]0x2013
$emCount = ([regex]::Matches($content, [regex]::Escape($emChar))).Count
$enCount = ([regex]::Matches($content, [regex]::Escape($enChar))).Count
Write-Output ("Em dashes: " + $emCount)
Write-Output ("En dashes: " + $enCount)
