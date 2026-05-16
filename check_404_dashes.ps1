$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.04-python-example.md'
$content = Get-Content -Path $path -Raw
$emDashes = ([regex]'\u2014').Matches($content).Count
$enDashes = ([regex]'\u2013').Matches($content).Count
$lines = (Get-Content -Path $path).Count
Write-Output "em_dashes=$emDashes en_dashes=$enDashes lines=$lines"
