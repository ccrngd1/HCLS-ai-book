$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.05-medication-adherence-intervention-targeting.md'
$lines = Get-Content -Path $path
# Look at line 153 and look for specific char codes
$line = $lines[152]
Write-Output "Line 153 length: $($line.Length)"
$idx = 0
foreach ($ch in $line.ToCharArray()) {
    $cp = [int][char]$ch
    if ($cp -eq 0x2013) {
        Write-Output "Found en dash at index $idx"
        # Print context
        $start = [Math]::Max(0, $idx - 5)
        $end = [Math]::Min($line.Length, $idx + 5)
        $context = $line.Substring($start, $end - $start)
        Write-Output "  Context: '$context'"
        Write-Output "  Surrounding chars (codepoints):"
        for ($i = $start; $i -lt $end; $i++) {
            $c = $line[$i]
            $cph = [int][char]$c
            Write-Output ("    [$i] = U+{0:X4}" -f $cph)
        }
    }
    $idx++
}
