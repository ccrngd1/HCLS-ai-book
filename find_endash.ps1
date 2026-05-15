$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.08-readmission-risk-anomaly-detection.md'
$c = Get-Content $f
$en = [char]0x2013
$lineNo = 0
foreach ($line in $c) {
  $lineNo++
  if ($line.Contains($en)) {
    Write-Host ("L" + $lineNo + ": " + $line.Substring(0, [Math]::Min($line.Length, 200)))
  }
}
