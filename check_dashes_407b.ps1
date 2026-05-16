$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.07-care-management-program-enrollment.md'
$emDash = [char]0x2014
$lines = Get-Content -LiteralPath $path
$out = @()
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i].Contains($emDash)) {
        # Find positions
        $line = $lines[$i]
        $positions = @()
        for ($j = 0; $j -lt $line.Length; $j++) {
            if ($line[$j] -eq $emDash) { $positions += $j }
        }
        $context = ""
        foreach ($p in $positions) {
            $start = [Math]::Max(0, $p - 30)
            $end = [Math]::Min($line.Length - 1, $p + 30)
            $snip = $line.Substring($start, $end - $start + 1)
            # Replace em-dash with [EM]
            $snip = $snip.Replace($emDash, '[EM]')
            $context += "  pos=$p ctx=" + $snip + "`n"
        }
        $out += "Line $($i+1):`n$context"
    }
}
$out | Out-File -LiteralPath 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\dash_report_407.txt' -Encoding UTF8
Get-Content -LiteralPath 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\dash_report_407.txt'
