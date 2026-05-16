$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.09-cybersecurity-access-pattern-anomalies.md'
$lines = Get-Content $f
for ($i = 0; $i -lt $lines.Count; $i++) {
  if ($lines[$i] -match [char]0x2013) {
    Write-Host "Line $($i+1): $($lines[$i])"
  }
}
