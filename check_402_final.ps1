$f = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.02-patient-education-content-matching.md'
$c = Get-Content -Raw -Encoding UTF8 $f
$em = ([regex]::Matches($c, [char]0x2014)).Count
$en = ([regex]::Matches($c, [char]0x2013)).Count
$todos = ([regex]::Matches($c, '<!-- TODO')).Count
Write-Host ("em-dashes (U+2014): " + $em)
Write-Host ("en-dashes (U+2013): " + $en)
Write-Host ("TODO markers: " + $todos)
Write-Host "---- TODO contexts ----"
$matches = [regex]::Matches($c, '<!-- TODO[^>]*-->', 'Singleline')
foreach ($m in $matches) {
  $snippet = $m.Value
  if ($snippet.Length -gt 200) { $snippet = $snippet.Substring(0,200) + '...' }
  Write-Host $snippet
  Write-Host '----'
}
