$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.06-care-gap-prioritization.md'
$lines = Get-Content $f -Encoding UTF8

# Check for any non-ASCII chars besides arrows we know about
Write-Host "=== Non-ASCII characters (excluding common arrows/stars) ==="
for ($i = 0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($line)
    foreach ($b in $bytes) {
        if ($b -gt 127) {
            # Non-ASCII; let's show this line
            Write-Host "Line $($i+1): $line"
            break
        }
    }
}
