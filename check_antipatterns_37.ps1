$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.07-patient-deterioration-early-warning.md'
$bytes = [System.IO.File]::ReadAllBytes($path)
$text = [System.Text.Encoding]::UTF8.GetString($bytes)
$lines = $text -split "`n"

$antiPatterns = @(
    'this recipe demonstrates',
    'we are excited',
    'in this recipe we will',
    'AWS architects, we'
)
foreach ($pat in $antiPatterns) {
    Write-Host "=== '$pat' ==="
    for ($i = 0; $i -lt $lines.Length; $i++) {
        if ($lines[$i] -match [regex]::Escape($pat)) {
            Write-Host "Line $($i+1): $($lines[$i].Substring(0, [Math]::Min(140, $lines[$i].Length)))"
        }
    }
}
