$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.06-care-gap-prioritization.md'
$content = Get-Content -Path $path -Raw
$emCount = 0
$enCount = 0
foreach ($c in $content.ToCharArray()) {
    if ([int][char]$c -eq 0x2014) { $emCount++ }
    if ([int][char]$c -eq 0x2013) { $enCount++ }
}
Write-Host "Em dash (U+2014) count: $emCount"
Write-Host "En dash (U+2013) count: $enCount"

# show lines containing em dashes
$lines = Get-Content -Path $path
$ln = 0
foreach ($line in $lines) {
    $ln++
    if ($line -match [char]0x2014) {
        Write-Host "EM-LINE ${ln}: $line"
    }
}
