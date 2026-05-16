$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.06-care-gap-prioritization.md'
$bytes = [System.IO.File]::ReadAllBytes($path)
# UTF-8 em dash is bytes 0xE2, 0x80, 0x94
$count = 0
$positions = @()
for ($i = 0; $i -lt $bytes.Length - 2; $i++) {
    if ($bytes[$i] -eq 0xE2 -and $bytes[$i+1] -eq 0x80 -and $bytes[$i+2] -eq 0x94) {
        $count++
        $positions += $i
    }
}
Write-Host "UTF-8 em dash byte sequence count: $count"
Write-Host "Positions: $($positions -join ',')"

# Also check for U+2014 in the read text
$text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
$emCount = 0
$emLines = @{}
$lineNum = 1
$colNum = 0
for ($i = 0; $i -lt $text.Length; $i++) {
    if ($text[$i] -eq "`n") { $lineNum++; $colNum = 0; continue }
    $colNum++
    if ([int]$text[$i] -eq 0x2014) {
        $emCount++
        if (-not $emLines.ContainsKey($lineNum)) { $emLines[$lineNum] = 0 }
        $emLines[$lineNum]++
    }
}
Write-Host "Em dash chars in text: $emCount"
foreach ($k in $emLines.Keys | Sort-Object) {
    Write-Host "Line ${k}: $($emLines[$k]) em dashes"
}
