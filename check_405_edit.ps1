$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.05-medication-adherence-intervention-targeting.md'
$text = Get-Content -Raw -Path $path

$emDashCount = ([regex]::Matches($text, [char]0x2014)).Count
$enDashCount = ([regex]::Matches($text, [char]0x2013)).Count
Write-Host "em-dash count: $emDashCount"
Write-Host "en-dash count: $enDashCount"

Write-Host "Non-ASCII characters:"
$codes = @{}
foreach ($c in $text.ToCharArray()) {
    if ([int]$c -gt 127) {
        $k = [int]$c
        if (-not $codes.ContainsKey($k)) { $codes[$k] = 0 }
        $codes[$k]++
    }
}
foreach ($k in ($codes.Keys | Sort-Object)) {
    $hex = '{0:X4}' -f $k
    $ch = [char]$k
    Write-Host ("  U+{0} ({1}): {2}" -f $hex, $ch, $codes[$k])
}

Write-Host ""
Write-Host "Looking for any 'demonstrates' / 'leverage' / 'seamlessly' / 'we are excited' / 'we need to talk' / 'cutting-edge':"
$patterns = @('demonstrates', 'leverage', 'seamlessly', 'we are excited', 'we need to talk', 'cutting-edge', 'state-of-the-art', 'industry-leading', 'best-in-class', 'unleash', 'empower', 'paradigm', 'holistic', 'synergy', 'game-changing')
foreach ($p in $patterns) {
    $hits = [regex]::Matches($text, $p, 'IgnoreCase').Count
    if ($hits -gt 0) {
        Write-Host ("  '{0}' : {1}" -f $p, $hits)
    }
}

Write-Host ""
Write-Host "Number of TODO markers (preserved):"
$todoCount = ([regex]::Matches($text, '<!-- TODO')).Count
Write-Host "  $todoCount"

Write-Host ""
Write-Host "Header hierarchy check:"
$lines = Get-Content -Path $path
$lineNum = 0
foreach ($line in $lines) {
    $lineNum++
    if ($line -match '^(#{1,6})\s+(.+)$') {
        $depth = $matches[1].Length
        $title = $matches[2]
        Write-Host ("  L{0,4}  {1} {2}" -f $lineNum, ('#' * $depth), $title)
    }
}
