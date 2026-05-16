$files = @(
    'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.05-medication-adherence-intervention-targeting.md',
    'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.04-wellness-program-recommendations.md',
    'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.06-care-gap-prioritization.md'
)
foreach ($f in $files) {
    Write-Host "=== $f ==="
    $lines = Get-Content $f -Encoding UTF8
    $cnt = 0
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^```([a-zA-Z0-9]*)\s*$') {
            $cnt++
            $lang = $matches[1]
            if ($cnt % 2 -eq 1) {
                Write-Host "  Line $($i+1): OPEN lang='$lang'"
            }
        }
    }
    Write-Host ""
}
