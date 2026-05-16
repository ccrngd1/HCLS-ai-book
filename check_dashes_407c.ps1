$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.07-care-management-program-enrollment.md'
$emDash = [char]0x2014
$enDash = [char]0x2013
# Read raw bytes and decode as UTF-8 explicitly
$bytes = [System.IO.File]::ReadAllBytes($path)
$content = [System.Text.Encoding]::UTF8.GetString($bytes)
$emCount = ([regex]::Matches($content, [regex]::Escape($emDash))).Count
$enCount = ([regex]::Matches($content, [regex]::Escape($enDash))).Count
Write-Host "em-dash count (UTF-8 decoded): $emCount"
Write-Host "en-dash count (UTF-8 decoded): $enCount"

# Also check using Get-Content -Encoding UTF8
$lines = Get-Content -LiteralPath $path -Encoding UTF8
$total = 0
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].Contains($emDash)) {
        $total++
        $line = $lines[$i]
        $idx = $line.IndexOf($emDash)
        $start = [Math]::Max(0, $idx - 40)
        $end = [Math]::Min($line.Length - 1, $idx + 40)
        $snip = $line.Substring($start, $end - $start + 1)
        Write-Host ("Line {0} (em-dash): {1}" -f ($i+1), $snip)
    }
}
Write-Host "Total lines with em-dash (Get-Content UTF8): $total"
