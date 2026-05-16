$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.04-wellness-program-recommendations.md'
$content = Get-Content -Path $path -Raw
$emDashCount = ([regex]::Matches($content, [char]0x2014)).Count
$enDashCount = ([regex]::Matches($content, [char]0x2013)).Count
Write-Output "Em dashes (U+2014): $emDashCount"
Write-Output "En dashes (U+2013): $enDashCount"

# Find any lines containing em or en dashes
$lines = Get-Content -Path $path
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match [char]0x2014) {
        Write-Output ("EM line " + ($i+1) + ": " + $lines[$i])
    }
    if ($lines[$i] -match [char]0x2013) {
        Write-Output ("EN line " + ($i+1) + ": " + $lines[$i])
    }
}
