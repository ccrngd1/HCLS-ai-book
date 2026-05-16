$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.06-care-gap-prioritization.md'
$bytes = [System.IO.File]::ReadAllBytes($f)
$em = 0
$en = 0
for ($i = 0; $i -lt $bytes.Length - 2; $i++) {
    if ($bytes[$i] -eq 0xE2 -and $bytes[$i+1] -eq 0x80) {
        if ($bytes[$i+2] -eq 0x94) { $em++ }
        elseif ($bytes[$i+2] -eq 0x93) { $en++ }
    }
}
Write-Host "em-dash count: $em"
Write-Host "en-dash count: $en"

Write-Host ""
Write-Host "=== Headers ==="
$lines = Get-Content $f -Encoding UTF8
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^(#+)\s') {
        Write-Host "$($i+1): $($lines[$i])"
    }
}
