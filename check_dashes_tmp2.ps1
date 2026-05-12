$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter02.10-multi-modal-clinical-reasoning.md'
$content = Get-Content -Raw $path -Encoding UTF8
$em = [char]0x2014
$en = [char]0x2013
$emCount = ([regex]::Matches($content, [regex]::Escape($em))).Count
$enCount = ([regex]::Matches($content, [regex]::Escape($en))).Count
Write-Host ("Em dashes: " + $emCount)
Write-Host ("En dashes: " + $enCount)

# Also check for visible bracket-style TODOs
$todoBracket = ([regex]::Matches($content, '\[TODO')).Count
Write-Host ("Bracket TODOs: " + $todoBracket)

# Count HTML-comment TODOs
$htmlTodo = ([regex]::Matches($content, '<!--\s*TODO')).Count
Write-Host ("HTML-comment TODOs: " + $htmlTodo)
