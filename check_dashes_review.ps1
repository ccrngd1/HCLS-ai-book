$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.04-medication-dispensing-anomalies.md'
$content = Get-Content -Raw -LiteralPath $path
$emDash = [char]0x2014
$enDash = [char]0x2013
$emCount = 0
$enCount = 0
foreach ($ch in $content.ToCharArray()) {
    if ($ch -eq $emDash) { $emCount++ }
    if ($ch -eq $enDash) { $enCount++ }
}
Write-Output ("em-dash count: " + $emCount)
Write-Output ("en-dash count: " + $enCount)

# Also count word-count
$words = ($content -split '\s+').Count
Write-Output ("word count approx: " + $words)
