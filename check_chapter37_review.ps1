$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.07-patient-deterioration-early-warning.md'
$bytes = [System.IO.File]::ReadAllBytes($path)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)

$emCount = 0
$enCount = 0
foreach ($ch in $text.ToCharArray()) {
    if ([int]$ch -eq 0x2014) { $emCount++ }
    if ([int]$ch -eq 0x2013) { $enCount++ }
}
Write-Host "Total chars: $($text.Length)"
Write-Host "Em-dash (U+2014) count: $emCount"
Write-Host "En-dash (U+2013) count: $enCount"

# Show context for any em-dashes found
if ($emCount -gt 0) {
    $lines = $text -split "`n"
    for ($i = 0; $i -lt $lines.Length; $i++) {
        if ($lines[$i] -match [char]0x2014) {
            Write-Host "Em-dash on line $($i+1): $($lines[$i])"
        }
    }
}

# Check for doc-voice anti-patterns (case-insensitive)
$antiPatterns = @(
    'this recipe demonstrates',
    'we are excited',
    'in this recipe we will',
    'AWS architects, we'
)
foreach ($pat in $antiPatterns) {
    $matches = [regex]::Matches($text, $pat, 'IgnoreCase')
    Write-Host "Anti-pattern '$pat': $($matches.Count) match(es)"
}

# TODO marker count
$todoMatches = [regex]::Matches($text, '<!-- TODO')
Write-Host "TODO markers: $($todoMatches.Count)"

# Header counts
$h1 = ([regex]::Matches($text, '(?m)^# ')).Count
$h2 = ([regex]::Matches($text, '(?m)^## ')).Count
$h3 = ([regex]::Matches($text, '(?m)^### ')).Count
$h4 = ([regex]::Matches($text, '(?m)^#### ')).Count
Write-Host "H1: $h1, H2: $h2, H3: $h3, H4: $h4"
