$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.07-patient-deterioration-early-warning.md'
$content = Get-Content -Raw $path
$emDash = [char]0x2014
$enDash = [char]0x2013
$emCount = ([regex]::Matches($content, $emDash)).Count
$enCount = ([regex]::Matches($content, $enDash)).Count
Write-Output "EmDashes: $emCount"
Write-Output "EnDashes: $enCount"

# Find en dash locations
$lines = Get-Content $path
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match $enDash) {
        Write-Output ("Line " + ($i + 1) + ": " + $lines[$i].Substring(0, [Math]::Min(150, $lines[$i].Length)))
    }
}
