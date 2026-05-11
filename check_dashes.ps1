$file = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter02.02-medical-terminology-simplification.md'
$bytes = [System.IO.File]::ReadAllBytes($file)
$content = [System.Text.Encoding]::UTF8.GetString($bytes)

$emDash = [char]0x2014
$enDash = [char]0x2013

$emCount = 0
$enCount = 0
for ($i = 0; $i -lt $content.Length; $i++) {
    if ($content[$i] -eq $emDash) { $emCount++ }
    if ($content[$i] -eq $enDash) { $enCount++ }
}
Write-Output "em count: $emCount"
Write-Output "en count: $enCount"

# Find line numbers containing en dashes
$lines = $content -split "`n"
for ($j = 0; $j -lt $lines.Length; $j++) {
    $line = $lines[$j]
    if ($line.Contains($enDash)) {
        $ln = $j + 1
        Write-Output "EN Line ${ln}: $line"
    }
    if ($line.Contains($emDash)) {
        $ln = $j + 1
        Write-Output "EM Line ${ln}: $line"
    }
}
