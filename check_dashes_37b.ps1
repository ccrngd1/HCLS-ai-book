$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.07-patient-deterioration-early-warning.md'
$content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
$emDash = [char]0x2014
$enDash = [char]0x2013
$emCount = ([regex]::Matches($content, $emDash)).Count
$enCount = ([regex]::Matches($content, $enDash)).Count
Write-Output "EmDashes (U+2014): $emCount"
Write-Output "EnDashes (U+2013): $enCount"

# Find en dash locations
$lines = $content -split "`n"
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].Contains($enDash)) {
        Write-Output ("Line " + ($i + 1) + ": " + $lines[$i].Substring(0, [Math]::Min(200, $lines[$i].Length)))
    }
}

# Find em dash locations
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].Contains($emDash)) {
        Write-Output ("EM Line " + ($i + 1) + ": " + $lines[$i].Substring(0, [Math]::Min(200, $lines[$i].Length)))
    }
}
