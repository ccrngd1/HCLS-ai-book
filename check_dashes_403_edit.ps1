$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.03-provider-directory-search-optimization.md'
$c = Get-Content -Raw -Encoding UTF8 $f
$matches = [regex]::Matches($c, '[\u2013\u2014]')
Write-Host "Total dashes found: $($matches.Count)"
foreach ($m in $matches) {
    $idx = $m.Index
    $line = ($c.Substring(0, $idx) -split "`n").Count
    $char = $c[$idx]
    $code = [int]$char
    $start = [Math]::Max(0, $idx - 30)
    $len = [Math]::Min(60, $c.Length - $start)
    $snip = $c.Substring($start, $len) -replace "`r?`n", " | "
    Write-Host ("line {0} code U+{1:x4} snippet: ...{2}..." -f $line, $code, $snip)
}
