$path = "C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.02-patient-no-show-pattern-detection.md"
$outpath = "C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\dash_report.txt"
$bytes = [System.IO.File]::ReadAllBytes($path)
$c = [System.Text.Encoding]::UTF8.GetString($bytes)
$lines = @()

$em = ($c.ToCharArray() | Where-Object { [int]$_ -eq 0x2014 }).Count
$en = ($c.ToCharArray() | Where-Object { [int]$_ -eq 0x2013 }).Count
$lines += "em-dash U+2014: $em"
$lines += "en-dash U+2013: $en"

$pattern = [regex]'[\u2013\u2014]'
$i = 0
foreach ($m in $pattern.Matches($c)) {
    $i++
    $start = [Math]::Max(0, $m.Index - 40)
    $len = [Math]::Min(80, $c.Length - $start)
    $snippet = $c.Substring($start, $len) -replace "`r?`n", ' '
    $codepoint = [int][char]$m.Value
    $lines += ("match " + $i + " U+" + ('{0:X4}' -f $codepoint) + " -> " + $snippet)
}
$lines += ("total matches: " + $i)

# Also count hyphens in ranges
$hyphenRangeCount = ([regex]'\d-\d').Matches($c).Count
$lines += ("hyphen-joined digit ranges (e.g., 4-6): " + $hyphenRangeCount)

[System.IO.File]::WriteAllLines($outpath, $lines, [System.Text.Encoding]::UTF8)
