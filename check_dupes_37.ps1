$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.07-patient-deterioration-early-warning.md'
$content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
$lines = $content -split "`n"
$i = 0
foreach ($line in $lines) {
    $i++
    if ($line -match '\b([A-Za-z]{3,})\s+\1\b') {
        Write-Output ("L" + $i + ": " + $matches[0] + " :: " + $line.Substring(0, [Math]::Min(180, $line.Length)))
    }
}
