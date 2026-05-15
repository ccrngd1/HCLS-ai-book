$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.04-medication-dispensing-anomalies.md'
$lines = Get-Content -LiteralPath $path
$enDash = [char]0x2013
$lineNum = 0
foreach ($line in $lines) {
    $lineNum++
    if ($line.Contains($enDash)) {
        Write-Output ("Line " + $lineNum + ": " + $line)
    }
}
