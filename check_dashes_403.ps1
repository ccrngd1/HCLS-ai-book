$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.03-provider-directory-search-optimization.md'
$c = Get-Content $f -Raw
$em = [regex]::Matches($c, [char]0x2014).Count
$en = [regex]::Matches($c, [char]0x2013).Count
Write-Host "em-dashes: $em"
Write-Host "en-dashes: $en"
