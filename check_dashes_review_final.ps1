$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.07-patient-deterioration-early-warning.md'
$content = Get-Content -Raw $path -Encoding UTF8
$emdash  = ([regex]::Matches($content, [char]0x2014)).Count
$endash  = ([regex]::Matches($content, [char]0x2013)).Count
Write-Output "em-dash (U+2014) count: $emdash"
Write-Output "en-dash (U+2013) count: $endash"
$lines = Get-Content $path -Encoding UTF8
for ($i=0; $i -lt $lines.Length; $i++) {
  if ($lines[$i] -match [char]0x2014) {
    Write-Output ("  em-dash on line {0}: {1}" -f ($i+1), $lines[$i].Substring(0, [Math]::Min(120, $lines[$i].Length)))
  }
  if ($lines[$i] -match [char]0x2013) {
    Write-Output ("  en-dash on line {0}: {1}" -f ($i+1), $lines[$i].Substring(0, [Math]::Min(120, $lines[$i].Length)))
  }
}
