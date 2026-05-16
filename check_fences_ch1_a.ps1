$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter01.05-medication-reconciliation-document-extraction.md'
if (-not (Test-Path $f)) {
    $f = (Get-ChildItem 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter01.*.md' | Select-Object -First 1).FullName
}
Write-Host "Checking: $f"
$lines = Get-Content -Encoding UTF8 $f
$inFence = $false
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
Write-Host "Fenced block languages:"
$langs.GetEnumerator() | Sort-Object Name | ForEach-Object { Write-Host "$($_.Key): $($_.Value)" }
