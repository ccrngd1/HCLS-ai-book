$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.05-medication-adherence-intervention-targeting.md'
$text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)

$emDashCount = ([regex]::Matches($text, [char]0x2014)).Count
$enDashCount = ([regex]::Matches($text, [char]0x2013)).Count
$todoCount = ([regex]::Matches($text, '<!-- TODO')).Count
$wordCount = (($text -split '\s+').Count)

Write-Host "After edit:"
Write-Host "  em-dash count:  $emDashCount"
Write-Host "  en-dash count:  $enDashCount"
Write-Host "  TODO markers:   $todoCount"
Write-Host "  word count:     $wordCount"

Write-Host ""
Write-Host "Body-text -ly hyphen patterns (excluding TODO blocks):"
$lines = [System.IO.File]::ReadAllLines($path, [System.Text.Encoding]::UTF8)
$lineNum = 0
$inTodo = $false
foreach ($line in $lines) {
    $lineNum++
    if ($line -match '<!-- TODO') { $inTodo = $true }
    $lineToCheck = if ($inTodo) { '' } else { $line }
    if ($line -match '-->' -and -not ($line -match '<!-- TODO.*-->')) { $inTodo = $false }
    if ($line -match '<!-- TODO.*-->') { continue }
    if (-not $inTodo -and $line -match '\b(similarly|actively|poorly|likely|widely|commonly|heavily|sparsely|recently|virtually|deliberately|carefully|seemingly|particularly|primarily)-\w+') {
        Write-Host ("  L{0}: {1}" -f $lineNum, $matches[0])
    }
}
