$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.09-cybersecurity-access-pattern-anomalies.md'
$f2 = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.09-python-example.md'

foreach ($file in @($f, $f2)) {
  $content = [System.IO.File]::ReadAllText($file, [System.Text.Encoding]::UTF8)
  $em = ([regex]::Matches($content, [char]0x2014)).Count
  $en = ([regex]::Matches($content, [char]0x2013)).Count
  $minus_unicode = ([regex]::Matches($content, [char]0x2212)).Count
  $hyphen = ([regex]::Matches($content, "--")).Count
  Write-Host "File: $file"
  Write-Host "  Em dashes (U+2014): $em"
  Write-Host "  En dashes (U+2013): $en"
  Write-Host "  Minus signs (U+2212): $minus_unicode"
  Write-Host "  Double hyphens '--': $hyphen"
}
