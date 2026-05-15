$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.07-patient-deterioration-early-warning.md'
$lines = [System.IO.File]::ReadAllLines($path, [System.Text.Encoding]::UTF8)
$i = 0
foreach ($line in $lines) {
    $i++
    if ($line -match '^```') {
        Write-Output ("Line " + $i + ": [" + $line + "]")
    }
}
