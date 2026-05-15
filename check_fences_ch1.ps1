$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter01.10-historical-chart-migration.md'
$lines = [System.IO.File]::ReadAllLines($path, [System.Text.Encoding]::UTF8)
$i = 0
foreach ($line in $lines) {
    $i++
    if ($line -match '^```') {
        Write-Output ("L" + $i + ": [" + $line + "]")
    }
}
