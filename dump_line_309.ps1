$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.09-cybersecurity-access-pattern-anomalies.md'
$lines = Get-Content $f
$line = $lines[458]  # 0-indexed, so line 459 is index 458
Write-Host "Line 459 length: $($line.Length)"
for ($j = 0; $j -lt $line.Length; $j++) {
  $ch = $line[$j]
  $code = [int][char]$ch
  $hex = "{0:X4}" -f $code
  if ($code -ge 32 -and $code -le 126) {
    $disp = [string]$ch
  } else {
    $disp = "?"
  }
  $msg = "  pos " + $j + ": U+" + $hex + " (" + $disp + ")"
  Write-Host $msg
}
