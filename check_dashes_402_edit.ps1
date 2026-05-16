$file = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.02-patient-education-content-matching.md'
$content = Get-Content -Raw $file -Encoding UTF8
$emCount = ([regex]::Matches($content, [char]0x2014)).Count
$enCount = ([regex]::Matches($content, [char]0x2013)).Count
Write-Host "em dashes (U+2014): $emCount"
Write-Host "en dashes (U+2013): $enCount"

# Find lines with em or en dashes
$lines = Get-Content $file -Encoding UTF8
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match [char]0x2014) {
        Write-Host ("EM line {0}: {1}" -f ($i+1), $lines[$i])
    }
    if ($lines[$i] -match [char]0x2013) {
        Write-Host ("EN line {0}: {1}" -f ($i+1), $lines[$i])
    }
}
