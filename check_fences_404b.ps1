$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.04-wellness-program-recommendations.md'
$bytes = [System.IO.File]::ReadAllBytes($path)
$content = [System.Text.Encoding]::UTF8.GetString($bytes)
$lines = $content -split "`n"
$inFence = $false
$fenceCount = 0
for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line -match "^``````") {
        $fenceCount++
        $tag = $line.TrimStart('`').Trim()
        if ($fenceCount % 2 -eq 1) {
            Write-Output ("Open fence at line " + ($i+1) + ": tag=[" + $tag + "]")
        }
    }
}
Write-Output "Total fence lines in 4.4: $fenceCount"
