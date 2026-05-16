$f1 = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.09-cybersecurity-access-pattern-anomalies.md'
$f2 = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter03.09-python-example.md'

foreach ($f in @($f1, $f2)) {
  $content = Get-Content $f -Raw
  $em = ([regex]::Matches($content, [char]0x2014)).Count
  $en = ([regex]::Matches($content, [char]0x2013)).Count
  Write-Host "$f"
  Write-Host "  Em dashes (U+2014): $em"
  Write-Host "  En dashes (U+2013): $en"
}
