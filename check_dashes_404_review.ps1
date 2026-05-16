$content = Get-Content 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.04-wellness-program-recommendations.md' -Raw -Encoding UTF8
$emDash = [char]0x2014
$enDash = [char]0x2013
$emCount = ([regex]::Matches($content, $emDash)).Count
$enCount = ([regex]::Matches($content, $enDash)).Count
Write-Output ("em dashes: " + $emCount)
Write-Output ("en dashes: " + $enCount)
