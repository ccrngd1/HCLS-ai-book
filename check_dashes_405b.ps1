$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.05-medication-adherence-intervention-targeting.md'
$content = Get-Content -Path $path -Raw

# Count specifically each codepoint
$em2014 = 0  # em dash
$en2013 = 0  # en dash
$tri25BC = 0 # downward triangle
$tri25BA = 0 # rightward triangle
foreach ($ch in $content.ToCharArray()) {
    $cp = [int][char]$ch
    if ($cp -eq 0x2014) { $em2014++ }
    elseif ($cp -eq 0x2013) { $en2013++ }
    elseif ($cp -eq 0x25BC) { $tri25BC++ }
    elseif ($cp -eq 0x25BA) { $tri25BA++ }
}
Write-Output "Em dashes (U+2014): $em2014"
Write-Output "En dashes (U+2013): $en2013"
Write-Output "Down triangles (U+25BC): $tri25BC"
Write-Output "Right triangles (U+25BA): $tri25BA"

# Find specific lines with en dashes
$lines = Get-Content -Path $path
$lineNum = 0
foreach ($line in $lines) {
    $lineNum++
    foreach ($ch in $line.ToCharArray()) {
        if ([int][char]$ch -eq 0x2013) {
            Write-Output "EN DASH ON LINE ${lineNum}"
            break
        }
    }
}
