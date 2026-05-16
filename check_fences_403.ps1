$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.03-provider-directory-search-optimization.md'
$lines = Get-Content -Encoding UTF8 $f
$inFence = $false
$fenceLang = ''
$fenceStart = 0
$ln = 0
$noLangFences = @()
foreach ($l in $lines) {
    $ln++
    if ($l -match '^```(.*)$') {
        if (-not $inFence) {
            $inFence = $true
            $fenceLang = $matches[1].Trim()
            $fenceStart = $ln
            if ([string]::IsNullOrEmpty($fenceLang)) {
                $noLangFences += "Line ${ln}: opening fence with no language"
            }
        } else {
            $inFence = $false
            $fenceLang = ''
        }
    }
}
Write-Host "Fences without language tags:"
$noLangFences | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "Total fences without lang: $($noLangFences.Count)"
