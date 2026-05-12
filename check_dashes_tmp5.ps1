$path = "C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.02-patient-no-show-pattern-detection.md"
$bytes = [System.IO.File]::ReadAllBytes($path)
$c = [System.Text.Encoding]::UTF8.GetString($bytes)

$em = ($c.ToCharArray() | Where-Object { [int]$_ -eq 0x2014 }).Count
$en = ($c.ToCharArray() | Where-Object { [int]$_ -eq 0x2013 }).Count
Write-Host ("em-dash U+2014: " + $em)
Write-Host ("en-dash U+2013: " + $en)

$pattern = [regex]'[\u2013\u2014]'
$i = 0
foreach ($m in $pattern.Matches($c)) {
    $i++
    if ($i -le 12) {
        $start = [Math]::Max(0, $m.Index - 30)
        $len = [Math]::Min(60, $c.Length - $start)
        $snippet = $c.Substring($start, $len) -replace "`r?`n", ' '
        $codepoint = [int][char]$m.Value
        [System.Console]::Out.WriteLine("match " + $i + " U+" + ('{0:X4}' -f $codepoint) + " -> " + $snippet)
    }
}
Write-Host ("total dash matches: " + $i)
