$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.03-provider-directory-search-optimization.md'
$bytes = [System.IO.File]::ReadAllBytes($path)
$utf8 = [System.Text.Encoding]::UTF8
$txt = $utf8.GetString($bytes)
$em = [regex]::Matches($txt, [char]0x2014)
$en = [regex]::Matches($txt, [char]0x2013)
Write-Host ("em dashes (U+2014): {0}" -f $em.Count)
Write-Host ("en dashes (U+2013): {0}" -f $en.Count)
$lines = $txt -split "`n"
for ($i=0; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line.Contains([char]0x2013)) {
        $idx = $line.IndexOf([char]0x2013)
        $start = [Math]::Max(0, $idx - 30)
        $end_pos = [Math]::Min($line.Length, $idx + 30)
        Write-Host ("EN-DASH line {0}: ...{1}..." -f ($i+1), $line.Substring($start, $end_pos - $start))
    }
    if ($line.Contains([char]0x2014)) {
        $idx = $line.IndexOf([char]0x2014)
        $start = [Math]::Max(0, $idx - 30)
        $end_pos = [Math]::Min($line.Length, $idx + 30)
        Write-Host ("EM-DASH line {0}: ...{1}..." -f ($i+1), $line.Substring($start, $end_pos - $start))
    }
}
