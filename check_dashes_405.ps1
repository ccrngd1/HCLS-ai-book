$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.05-medication-adherence-intervention-targeting.md'
$content = Get-Content -Path $path -Raw
$em = 0
$en = 0
foreach ($ch in $content.ToCharArray()) {
    if ([int][char]$ch -eq 0x2014) { $em++ }
    elseif ([int][char]$ch -eq 0x2013) { $en++ }
}
Write-Output "Em dashes (U+2014): $em"
Write-Output "En dashes (U+2013): $en"

# Find lines with em or en dashes
$lines = Get-Content -Path $path
$lineNum = 0
foreach ($line in $lines) {
    $lineNum++
    if ($line -match "[\u2013\u2014]") {
        Write-Output "Line ${lineNum}: $line"
    }
}
