$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.02-patient-education-content-matching.md'
$content = Get-Content -Path $path -Raw
$emDash = [char]0x2014
$enDash = [char]0x2013
$emCount = ([regex]::Matches($content, $emDash)).Count
$enCount = ([regex]::Matches($content, $enDash)).Count
$todoCount = ([regex]::Matches($content, '<!-- TODO')).Count
Write-Host ('Em-dash count: ' + $emCount)
Write-Host ('En-dash count: ' + $enCount)
Write-Host ('TODO comment count: ' + $todoCount)
Write-Host ''
Write-Host 'TODO comments (first 200 chars each):'
$matches = [regex]::Matches($content, '<!-- TODO[^>]+-->', 'Singleline')
$i = 0
foreach ($m in $matches) {
    $i++
    $snippet = $m.Value
    if ($snippet.Length -gt 250) { $snippet = $snippet.Substring(0, 250) + '...' }
    Write-Host ('--- TODO #' + $i + ' ---')
    Write-Host $snippet
    Write-Host ''
}
