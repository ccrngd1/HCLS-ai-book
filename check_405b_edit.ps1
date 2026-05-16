$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.05-medication-adherence-intervention-targeting.md'
$text = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)

$emDashCount = ([regex]::Matches($text, [char]0x2014)).Count
$enDashCount = ([regex]::Matches($text, [char]0x2013)).Count
$smartQuoteOpen = ([regex]::Matches($text, [char]0x201C)).Count
$smartQuoteClose = ([regex]::Matches($text, [char]0x201D)).Count
$smartApos = ([regex]::Matches($text, [char]0x2019)).Count
Write-Host "em-dash count: $emDashCount"
Write-Host "en-dash count: $enDashCount"
Write-Host "open smart quote (U+201C): $smartQuoteOpen"
Write-Host "close smart quote (U+201D): $smartQuoteClose"
Write-Host "smart apostrophe (U+2019): $smartApos"

Write-Host ""
Write-Host "Locations of any em-dashes:"
$lines = [System.IO.File]::ReadAllLines($path, [System.Text.Encoding]::UTF8)
$lineNum = 0
foreach ($line in $lines) {
    $lineNum++
    if ($line.Contains([char]0x2014)) {
        Write-Host ("  L{0}: {1}" -f $lineNum, $line)
    }
}

Write-Host ""
Write-Host "Locations of en-dashes:"
$lineNum = 0
foreach ($line in $lines) {
    $lineNum++
    if ($line.Contains([char]0x2013)) {
        Write-Host ("  L{0}: {1}" -f $lineNum, $line.Substring(0, [Math]::Min(150, $line.Length)))
    }
}

Write-Host ""
Write-Host "Hits for 'demonstrates' (style flag):"
$lineNum = 0
foreach ($line in $lines) {
    $lineNum++
    if ($line -match 'demonstrates') {
        Write-Host ("  L{0}: {1}" -f $lineNum, $line.Substring(0, [Math]::Min(180, $line.Length)))
    }
}
