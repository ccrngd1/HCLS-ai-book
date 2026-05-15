$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.04-medication-dispensing-anomalies.md'
$bytes = [System.IO.File]::ReadAllBytes($path)
$content = [System.Text.Encoding]::UTF8.GetString($bytes)
$lines = $content -split "`r?`n"
$enDash = [char]0x2013
$emDash = [char]0x2014
$lineNum = 0
$foundEn = 0
$foundEm = 0
foreach ($line in $lines) {
    $lineNum++
    if ($line.IndexOf($enDash) -ge 0) {
        $foundEn++
        Write-Output ("EN-DASH Line " + $lineNum + ": " + $line.Trim())
    }
    if ($line.IndexOf($emDash) -ge 0) {
        $foundEm++
        Write-Output ("EM-DASH Line " + $lineNum + ": " + $line.Trim())
    }
}
Write-Output ("`nTotals: en-dash lines = " + $foundEn + ", em-dash lines = " + $foundEm)
