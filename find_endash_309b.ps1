$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.09-cybersecurity-access-pattern-anomalies.md'
$lines = Get-Content $f
for ($i = 0; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -match [char]0x2013) {
    $line = $lines[$i]
    Write-Host "=== Line $($i+1) ==="
    for ($j = 0; $j -lt $line.Length; $j++) {
      $ch = $line[$j]
      $code = [int][char]$ch
      if ($code -eq 0x2013) {
        $start = [Math]::Max(0, $j - 20)
        $end = [Math]::Min($line.Length - 1, $j + 20)
        $context = $line.Substring($start, $end - $start + 1)
        $msg = "  Position " + $j + ": U+2013 (EN DASH) context: '" + $context + "'"
        Write-Host $msg
      }
    }
  }
}
