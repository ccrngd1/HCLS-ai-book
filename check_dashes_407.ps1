$path = 'C:\Users\lawsnic\OneDrive - amazon.com\Documents\HCLS-ai-book\chapter04.07-care-management-program-enrollment.md'
$content = Get-Content -Raw -LiteralPath $path
$emDash = [char]0x2014
$enDash = [char]0x2013
$emCount = ([regex]::Matches($content, [regex]::Escape($emDash))).Count
$enCount = ([regex]::Matches($content, [regex]::Escape($enDash))).Count
Write-Host "em-dash count: $emCount"
Write-Host "en-dash count: $enCount"
if ($emCount -gt 0) {
    $lines = Get-Content -LiteralPath $path
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i].Contains($emDash)) {
            Write-Host ("Line {0}: {1}" -f ($i+1), $lines[$i])
        }
    }
}
