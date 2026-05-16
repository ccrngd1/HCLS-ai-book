$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.01-appointment-reminder-channel-optimization.md'
$lines = Get-Content -Encoding UTF8 $f
$inFence = $false
$fenceLang = ''
$ln = 0
$langs = @{}
foreach ($l in $lines) {
    $ln++
    if ($l -match '^```(.*)$') {
        if (-not $inFence) {
            $inFence = $true
            $fenceLang = $matches[1].Trim()
            if ([string]::IsNullOrEmpty($fenceLang)) { $fenceLang = '(none)' }
            if ($langs.ContainsKey($fenceLang)) { $langs[$fenceLang]++ } else { $langs[$fenceLang] = 1 }
        } else {
            $inFence = $false
        }
    }
}
Write-Host "Fenced block languages used in 4.01:"
$langs.GetEnumerator() | Sort-Object Name | ForEach-Object { Write-Host "$($_.Key): $($_.Value)" }
