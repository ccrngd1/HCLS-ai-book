$file = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.02-patient-education-content-matching.md'
$content = Get-Content -Raw $file -Encoding UTF8

# Specifically check for em-dash, en-dash, and box drawing components used as horizontal dashes
$em = ([regex]::Matches($content, [char]0x2014)).Count  # em
$en = ([regex]::Matches($content, [char]0x2013)).Count  # en
$boxLight = ([regex]::Matches($content, [char]0x2500)).Count  # box drawings light horizontal
$boxHeavy = ([regex]::Matches($content, [char]0x2501)).Count  # box drawings heavy horizontal
$horizontalBar = ([regex]::Matches($content, [char]0x2015)).Count  # horizontal bar
$figureDash = ([regex]::Matches($content, [char]0x2012)).Count  # figure dash
$minusSign = ([regex]::Matches($content, [char]0x2212)).Count  # math minus

Write-Host "U+2014 em dash: $em"
Write-Host "U+2013 en dash: $en"
Write-Host "U+2012 figure dash: $figureDash"
Write-Host "U+2015 horizontal bar: $horizontalBar"
Write-Host "U+2212 minus sign: $minusSign"
Write-Host "U+2500 box light: $boxLight (decorative, OK in ASCII art)"
Write-Host "U+2501 box heavy: $boxHeavy (decorative)"

# Total non-ASCII non-box dashes that could be problems
$problemTotal = $em + $horizontalBar + $figureDash + $minusSign
Write-Host ""
Write-Host "Total problem dashes (excluding en dash & box drawing): $problemTotal"
