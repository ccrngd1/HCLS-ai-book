$path = "C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.02-patient-no-show-pattern-detection.md"
$c = Get-Content -Raw $path

# Specifically extract context around every [\u2013] occurrence
$pattern = [regex]'[\u2013\u2014]'
$i = 0
foreach ($m in $pattern.Matches($c)) {
    $i++
    $start = [Math]::Max(0, $m.Index - 40)
    $len = [Math]::Min(80, $c.Length - $start)
    $snippet = $c.Substring($start, $len) -replace "`r?`n", ' '
    $codepoint = [int][char]$m.Value
    Write-Host ("match " + $i + " char U+" + ('{0:X4}' -f $codepoint) + " -> " + $snippet)
}
Write-Host ("total: " + $i)
