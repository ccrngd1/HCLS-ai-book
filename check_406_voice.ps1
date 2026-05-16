$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.06-care-gap-prioritization.md'
$lines = Get-Content $f -Encoding UTF8

# Voice drift / marketing patterns
Write-Host "=== Voice drift scan ==="
$patterns = @(
    'This recipe demonstrates',
    'We are excited',
    'AWS architects, we need',
    'seamlessly',
    'cutting-edge',
    'state-of-the-art',
    'industry-leading',
    'unleash',
    'game-changing',
    'paradigm shift',
    'best-in-class',
    'synergy',
    'holistic'
)
foreach ($p in $patterns) {
    $found = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match [regex]::Escape($p)) {
            Write-Host "  HIT line $($i+1): $($lines[$i])"
            $found = $true
        }
    }
    if (-not $found) { Write-Host "  ok: '$p' not found" }
}

# Code fence balance
Write-Host ""
Write-Host "=== Code fence check ==="
$fenceCount = 0
$openFences = @()
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^```') {
        $fenceCount++
        if ($fenceCount % 2 -eq 1) {
            $lang = $lines[$i] -replace '^```', ''
            $openFences += "$($i+1): lang='$lang'"
        }
    }
}
Write-Host "  Total fence lines: $fenceCount"
if ($fenceCount % 2 -ne 0) {
    Write-Host "  WARN: unbalanced fences"
} else {
    Write-Host "  Fences balanced"
}
Write-Host "  Open fences:"
foreach ($of in $openFences) { Write-Host "    $of" }

# URLs
Write-Host ""
Write-Host "=== URL extraction ==="
$urls = @()
foreach ($line in $lines) {
    $matches = [regex]::Matches($line, 'https?://[^\s\)]+')
    foreach ($m in $matches) {
        $urls += $m.Value
    }
}
$urls | Sort-Object -Unique | ForEach-Object { Write-Host "  $_" }
