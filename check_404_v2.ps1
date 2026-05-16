$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.04-wellness-program-recommendations.md'
$content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
$emDashCount = ([regex]::Matches($content, [char]0x2014)).Count
$enDashCount = ([regex]::Matches($content, [char]0x2013)).Count
Write-Output "Em dashes (U+2014): $emDashCount"
Write-Output "En dashes (U+2013): $enDashCount"

# Find any em or en dashes
$lines = [System.IO.File]::ReadAllLines($path, [System.Text.Encoding]::UTF8)
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].Contains([char]0x2014)) {
        Write-Output ("EM line " + ($i+1) + ": " + $lines[$i])
    }
    if ($lines[$i].Contains([char]0x2013)) {
        Write-Output ("EN line " + ($i+1) + ": " + $lines[$i])
    }
}
Write-Output "Done"
